#!/usr/bin/env python3
"""Restore native wk_shadowing_* SentenceAudio on Shadowing Immersion / Candidate notes.

A prior Voicevox --force pass replaced packaged clips with wk_immersion_sent_*.wav.
This re-points SentenceAudio at the original media (and clears SentenceAudioEasy).

Usage (Anki open with AnkiConnect):

  python3 scripts/restore_shadowing_native_audio.py
  python3 scripts/restore_shadowing_native_audio.py --note-type "WK Shadowing Candidate"
  python3 scripts/restore_shadowing_native_audio.py --projects-dir ~/shadowing/cli/projects
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shadowing_decks import (  # noqa: E402
    SHADOWING_CANDIDATE_NOTE_TYPE_NAME,
    SHADOWING_NOTE_TYPE_NAME,
    find_native_shadowing_media,
    load_shadowing_project,
    native_shadowing_media_stem_from_duplicate_key,
    resolve_clip_path,
    stage_clip_media,
)

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
DEFAULT_MEDIA_DIR = (
    Path.home() / "Library/Application Support/Anki2/User 1/collection.media"
)
SHADOWING_NOTE_TYPES = (
    SHADOWING_NOTE_TYPE_NAME,
    SHADOWING_CANDIDATE_NOTE_TYPE_NAME,
)


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if payload.get("error"):
        raise RuntimeError(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def field_value(fields: dict, name: str) -> str:
    return ((fields.get(name) or {}).get("value") or "").strip()


def store_media_file(base_url: str, path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    stored = anki_connect(
        base_url,
        "storeMediaFile",
        filename=path.name,
        data=data,
    )
    return str(stored or path.name)


def try_restage_from_projects(
    *,
    projects_dir: Path,
    duplicate_key: str,
    staging_dir: Path,
) -> Path | None:
    parts = [p.strip() for p in duplicate_key.split("|") if p.strip()]
    if len(parts) < 2:
        return None
    source_id, sentence_id = parts[0], parts[1]
    video_tail = source_id.removeprefix("source-")
    candidates = []
    for name in (video_tail, source_id):
        if name:
            candidates.append(projects_dir / name)
    if not projects_dir.is_dir():
        return None
    for child in projects_dir.iterdir():
        if not child.is_dir():
            continue
        source_json = child / "source.json"
        if not source_json.is_file():
            continue
        try:
            payload = json.loads(source_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sid = str(payload.get("id") or "").strip()
        if sid == source_id or str(payload.get("videoId") or "") == video_tail:
            candidates.append(child)
    seen: set[Path] = set()
    for project_dir in candidates:
        resolved = project_dir.resolve()
        if resolved in seen or not (resolved / "sentences.json").is_file():
            continue
        seen.add(resolved)
        try:
            project = load_shadowing_project(resolved)
        except (OSError, ValueError, FileNotFoundError):
            continue
        sentence = next(
            (s for s in project.sentences if s.sentence_id == sentence_id),
            None,
        )
        if sentence is None:
            continue
        filename, media_path = stage_clip_media(project, sentence, staging_dir)
        if media_path is not None and media_path.is_file():
            return media_path
        clip = resolve_clip_path(project, sentence)
        if clip is not None and clip.is_file():
            dest = staging_dir / (
                filename
                or f"{native_shadowing_media_stem_from_duplicate_key(duplicate_key)}{clip.suffix}"
            )
            staging_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(clip, dest)
            return dest
    return None


def restore_note(
    *,
    base_url: str,
    note_id: int,
    fields: dict,
    media_dir: Path,
    projects_dir: Path | None,
    staging_dir: Path,
    dry_run: bool,
) -> str:
    duplicate_key = field_value(fields, "DuplicateKey")
    current = field_value(fields, "SentenceAudio")
    stem = native_shadowing_media_stem_from_duplicate_key(duplicate_key)
    if not stem:
        return "skip-no-key"

    media_path = find_native_shadowing_media(media_dir, stem=stem)
    if media_path is None and projects_dir is not None:
        media_path = try_restage_from_projects(
            projects_dir=projects_dir,
            duplicate_key=duplicate_key,
            staging_dir=staging_dir,
        )
    if media_path is None:
        return "missing"

    sound = f"[sound:{media_path.name}]"
    already_native = current == sound or current == media_path.name
    easy = field_value(fields, "SentenceAudioEasy")
    if already_native and not easy:
        return "ok"

    if dry_run:
        return "would-restore"

    # Ensure Anki media has the file (restaged copies may only be in staging_dir).
    if media_path.parent.resolve() != media_dir.resolve():
        store_media_file(base_url, media_path)
    elif not (media_dir / media_path.name).is_file():
        store_media_file(base_url, media_path)

    update_fields = {"SentenceAudio": sound}
    if "SentenceAudioEasy" in fields:
        update_fields["SentenceAudioEasy"] = ""
    anki_connect(
        base_url,
        "updateNoteFields",
        note={"id": note_id, "fields": update_fields},
    )
    return "restored"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument(
        "--note-type",
        default=None,
        choices=list(SHADOWING_NOTE_TYPES),
        help="Limit to one Shadowing note type (default: both)",
    )
    parser.add_argument(
        "--media-dir",
        type=Path,
        default=DEFAULT_MEDIA_DIR,
        help="Anki collection.media directory",
    )
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=Path.home() / "shadowing/cli/projects",
        help="Shadowing CLI projects root (used when media file is missing)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    note_types = [args.note_type] if args.note_type else list(SHADOWING_NOTE_TYPES)
    staging_dir = REPO_ROOT / "out" / "media" / "shadowing"
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        models = set(anki_connect(args.anki_connect, "modelNames") or [])
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {args.anki_connect}. "
            f"Is Anki open?\n{exc}"
        ) from exc

    totals: dict[str, int] = {}
    for model_name in note_types:
        if model_name not in models:
            print(f"skip missing note type: {model_name}")
            continue
        note_ids = list(
            anki_connect(args.anki_connect, "findNotes", query=f'note:"{model_name}"')
        )
        if not note_ids:
            print(f"{model_name}: 0 notes")
            continue
        infos = anki_connect(args.anki_connect, "notesInfo", notes=note_ids)
        counts: dict[str, int] = {}
        for info in infos:
            status = restore_note(
                base_url=args.anki_connect,
                note_id=int(info["noteId"]),
                fields=info.get("fields") or {},
                media_dir=args.media_dir,
                projects_dir=args.projects_dir if args.projects_dir.is_dir() else None,
                staging_dir=staging_dir,
                dry_run=args.dry_run,
            )
            counts[status] = counts.get(status, 0) + 1
            totals[status] = totals.get(status, 0) + 1
            if status in {"missing", "skip-no-key"}:
                key = field_value(info.get("fields") or {}, "DuplicateKey")
                print(f"  {status}: note {info['noteId']} {key}")
        print(
            f"{model_name}: "
            + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )
    print(
        "totals: "
        + ", ".join(f"{k}={v}" for k, v in sorted(totals.items()) if v)
        + (" (dry-run)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())