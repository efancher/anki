"""Tests for anki_headless/: everything that doesn't require a live AnkiWeb
account. Needs the real `anki` package (pinned in .venv-headless) — skipped
entirely if it isn't importable, same reasoning as
tests/test_anki25_collection_compat.py (this venv vs. the main repo venv).

Run with:
  .venv-headless/bin/python3 -m pytest tests/test_anki_headless.py -q
"""
from __future__ import annotations

import json
import stat

import pytest

pytest.importorskip("anki")

from anki.collection import Collection  # noqa: E402

from anki_headless import addons, auth, paths, sync, validate, workspace  # noqa: E402


@pytest.fixture
def workspace_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(paths, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(paths, "WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr(paths, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(paths, "OUTGOING_DIR", tmp_path / "outgoing")
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(paths, "AUTH_FILE", tmp_path / "config" / "auth.json")
    paths.ensure_workspace()
    return tmp_path


def _make_collection(profile_dir) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    col = Collection(str(paths.collection_path(profile_dir)))
    col.decks.id("Test Deck", create=True)
    col.close()


# --- paths ---------------------------------------------------------------


def test_ensure_workspace_creates_all_dirs(workspace_dirs):
    for d in (paths.PROFILE_DIR, paths.WORKING_DIR, paths.BACKUPS_DIR, paths.OUTGOING_DIR, paths.CONFIG_DIR):
        assert d.is_dir()


def test_collection_path_and_media_dir(workspace_dirs):
    profile = paths.PROFILE_DIR
    assert paths.collection_path(profile) == profile / "collection.anki2"
    assert paths.media_dir(profile) == profile / "collection.media"


# --- auth ------------------------------------------------------------------


def test_auth_round_trip_and_permissions(workspace_dirs):
    assert auth.load_auth() is None
    stored = auth.StoredAuth(hkey="secrettoken", endpoint="https://example.invalid")
    auth.save_auth(stored)

    loaded = auth.load_auth()
    assert loaded is not None
    assert loaded.hkey == "secrettoken"
    assert loaded.endpoint == "https://example.invalid"

    mode = stat.S_IMODE(paths.AUTH_FILE.stat().st_mode)
    assert mode == 0o600

    # never stores anything beyond hkey/endpoint (e.g. no raw password field)
    payload = json.loads(paths.AUTH_FILE.read_text())
    assert set(payload.keys()) == {"hkey", "endpoint"}


def test_require_auth_raises_when_missing(workspace_dirs):
    with pytest.raises(SystemExit):
        auth.require_auth()


# --- validate ----------------------------------------------------------------


def test_sqlite_integrity_check_ok_on_fresh_collection(workspace_dirs):
    _make_collection(paths.PROFILE_DIR)
    ok, report = validate.sqlite_integrity_check(paths.collection_path(paths.PROFILE_DIR))
    assert ok is True
    assert report == "ok"


def test_snapshot_counts_empty_collection(workspace_dirs):
    _make_collection(paths.PROFILE_DIR)
    snap = validate.snapshot(paths.PROFILE_DIR)
    assert snap.note_count == 0
    assert snap.card_count == 0
    assert snap.sqlite_integrity_ok is True
    assert snap.counts_by_tag == {"wk-core": 0, "wk-locked": 0}


def test_diff_reports_no_changes_when_identical(workspace_dirs):
    _make_collection(paths.PROFILE_DIR)
    before = validate.snapshot(paths.PROFILE_DIR)
    after = validate.snapshot(paths.PROFILE_DIR)
    assert validate.diff(before, after) == ["no count changes"]


def test_diff_reports_note_and_card_deltas(workspace_dirs):
    _make_collection(paths.PROFILE_DIR)
    before = validate.snapshot(paths.PROFILE_DIR)

    col = Collection(str(paths.collection_path(paths.PROFILE_DIR)))
    basic = col.models.by_name("Basic")
    note = col.new_note(basic)
    note["Front"] = "front"
    note["Back"] = "back"
    col.add_note(note, col.decks.id("Test Deck", create=True))
    col.close()

    after = validate.snapshot(paths.PROFILE_DIR)
    lines = validate.diff(before, after)
    assert any(line.startswith("notes: 0 -> 1") for line in lines)
    assert any(line.startswith("cards: 0 -> 1") for line in lines)


# --- workspace ---------------------------------------------------------------


def test_refresh_working_copy_derives_from_profile(workspace_dirs):
    _make_collection(paths.PROFILE_DIR)
    working = workspace.refresh_working_copy()
    assert working == paths.WORKING_DIR
    assert paths.collection_path(paths.WORKING_DIR).is_file()


def test_backup_profile_never_overwrites(workspace_dirs, monkeypatch):
    _make_collection(paths.PROFILE_DIR)
    monkeypatch.setattr(workspace, "_timestamp", lambda: "fixed")

    first = workspace.backup_profile("test")
    assert first == paths.BACKUPS_DIR / "fixed-test"
    assert first.is_dir()

    with pytest.raises(FileExistsError):
        workspace.backup_profile("test")


def test_promote_working_to_profile_backs_up_first(workspace_dirs):
    _make_collection(paths.PROFILE_DIR)
    workspace.refresh_working_copy()

    # mutate working/ only
    col = Collection(str(paths.collection_path(paths.WORKING_DIR)))
    basic = col.models.by_name("Basic")
    note = col.new_note(basic)
    note["Front"] = "front"
    note["Back"] = "back"
    col.add_note(note, col.decks.id("Test Deck", create=True))
    col.close()

    before_profile = validate.snapshot(paths.PROFILE_DIR)
    assert before_profile.note_count == 0

    backup_path = workspace.promote_working_to_profile()
    assert backup_path.is_dir()
    # the backup preserves the pre-promote (empty) state
    backup_snap = validate.snapshot(backup_path)
    assert backup_snap.note_count == 0

    after_profile = validate.snapshot(paths.PROFILE_DIR)
    assert after_profile.note_count == 1


# --- addons (headless aqt stub) -----------------------------------------------


def test_run_health_check_headless(workspace_dirs):
    _make_collection(paths.PROFILE_DIR)
    col = Collection(str(paths.collection_path(paths.PROFILE_DIR)))
    result = addons.run_health_check(col, paths.PROFILE_DIR)
    col.close()
    assert result.operation == "health-check"
    assert "WK Health Check" in result.summary


def test_run_unlock_pass_headless_no_op_on_empty_collection(workspace_dirs):
    _make_collection(paths.PROFILE_DIR)
    col = Collection(str(paths.collection_path(paths.PROFILE_DIR)))
    result = addons.run_unlock_pass(col, paths.PROFILE_DIR)
    col.close()
    assert result.details == {"unlocked": 0, "updated": 0}


def test_run_apply_deck_options_headless_reports_missing_config(workspace_dirs):
    _make_collection(paths.PROFILE_DIR)
    col = Collection(str(paths.collection_path(paths.PROFILE_DIR)))
    result = addons.run_apply_deck_options(col, paths.PROFILE_DIR)
    col.close()
    assert "No anki_deck_options.json" in result.summary


# --- sync (no network) ---------------------------------------------------------


def test_full_sync_required_message_names_the_direction():
    exc = sync.FullSyncRequired("FULL_UPLOAD")
    assert "FULL_UPLOAD" in str(exc)
    assert "Refusing to guess" in str(exc)


def test_sync_collection_rejects_invalid_allow_full_sync_value(workspace_dirs):
    _make_collection(paths.PROFILE_DIR)
    bogus_auth = auth.StoredAuth(hkey="x", endpoint=None)
    with pytest.raises(ValueError):
        sync.sync_collection(paths.PROFILE_DIR, bogus_auth, allow_full_sync="sideways")
