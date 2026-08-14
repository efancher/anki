"""Headless Anki CLI: login, pull, run (add-on ops), push.

All AnkiWeb-facing operations are incremental only by default (see
sync.FullSyncRequired) — this module never picks upload-vs-download for you.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from anki.collection import Collection

from . import addons, auth, paths, sync, validate, workspace


def cmd_login(_args: argparse.Namespace) -> int:
    paths.ensure_workspace()
    with tempfile.TemporaryDirectory() as tmp:
        scratch = str(Path(tmp) / "scratch.anki2")
        stored = auth.interactive_login(scratch_collection_path=scratch)
    print(f"Saved AnkiWeb sync token to {paths.AUTH_FILE} (0600).")
    print(f"Endpoint: {stored.endpoint or '(default AnkiWeb)'}")
    return 0


def _print_snapshot(label: str, snap: validate.CollectionSnapshot) -> None:
    print(f"[{label}] decks={snap.deck_count} notes={snap.note_count} "
          f"cards={snap.card_count} suspended={snap.suspended_count} "
          f"sqlite_integrity={'ok' if snap.sqlite_integrity_ok else 'FAILED: ' + snap.sqlite_integrity_report}")
    for tag, count in snap.counts_by_tag.items():
        print(f"    tag:{tag} = {count}")


def cmd_pull(args: argparse.Namespace) -> int:
    paths.ensure_workspace()
    stored = auth.require_auth()
    try:
        result = sync.sync_collection(
            paths.PROFILE_DIR,
            stored,
            sync_media=False,
            allow_full_sync=args.allow_full_sync,
        )
    except sync.FullSyncRequired as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3

    if result.updated_auth is not None:
        auth.save_auth(result.updated_auth)
        stored = result.updated_auth
        print(f"AnkiWeb redirected this account to a dedicated sync host; saved for future syncs.")

    print(f"Sync: {result.required}" + (f" — {result.server_message}" if result.server_message else ""))

    if args.media:
        print("Syncing media (this can take a while the first time)...")
        sync.sync_media(paths.PROFILE_DIR, stored)

    workspace.refresh_working_copy()
    print(f"working/ refreshed from profile/.")

    snap = validate.snapshot(paths.PROFILE_DIR)
    _print_snapshot("profile", snap)
    if not snap.sqlite_integrity_ok:
        print("WARNING: sqlite integrity check did not report 'ok'.", file=sys.stderr)
        return 4
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    paths.ensure_workspace()
    stored = auth.load_auth()
    if stored is None:
        print("Not logged in. Run: scripts/anki_headless_login")
        return 1
    col_path = paths.collection_path(paths.PROFILE_DIR)
    if not col_path.is_file():
        print("No local profile yet. Run: scripts/anki_sync_pull")
        return 0
    status = None
    col = Collection(str(col_path))
    try:
        status = col.sync_status(auth.to_sync_auth(stored))
    finally:
        col.close()
    names = {0: "NO_CHANGES", 1: "NORMAL_SYNC", 2: "FULL_SYNC"}
    print(f"AnkiWeb status: {names.get(status.required, status.required)}")
    snap = validate.snapshot(paths.PROFILE_DIR)
    _print_snapshot("profile", snap)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    paths.ensure_workspace()
    stored = auth.require_auth()

    if args.sync_before:
        rc = cmd_pull(argparse.Namespace(allow_full_sync=None, media=False))
        if rc != 0:
            return rc

    target_dir = paths.PROFILE_DIR if args.target == "profile" else paths.WORKING_DIR
    before = validate.snapshot(target_dir)

    backup_path = workspace.backup_profile(f"pre-run-{'-'.join(args.operations)}") if args.target == "profile" else None

    ops = addons.OPERATIONS.keys() if "all" in args.operations else args.operations
    results = []
    col = Collection(str(paths.collection_path(target_dir)))
    try:
        for op_name in ops:
            fn = addons.OPERATIONS[op_name]
            result = fn(col, target_dir)
            results.append(result)
            print(f"--- {result.operation} ---")
            print(result.summary)
    finally:
        col.close()

    after = validate.snapshot(target_dir)
    print("--- changes ---")
    for line in validate.diff(before, after):
        print(f"  {line}")
    if backup_path:
        print(f"Backup before this run: {backup_path}")

    if args.target == "profile" and args.sync_after:
        try:
            sync_result = sync.sync_collection(
                paths.PROFILE_DIR, stored, sync_media=False, allow_full_sync=args.allow_full_sync
            )
        except sync.FullSyncRequired as exc:
            print(f"REFUSED to sync changes up: {exc}", file=sys.stderr)
            print("Your changes are saved locally in profile/ but NOT yet on AnkiWeb.", file=sys.stderr)
            return 3
        print(f"Synced to AnkiWeb: {sync_result.required}")

    return 0


def cmd_push(args: argparse.Namespace) -> int:
    paths.ensure_workspace()
    stored = auth.require_auth()

    if args.promote_working:
        backup_path = workspace.promote_working_to_profile(backup_label="pre-promote")
        print(f"Promoted working/ -> profile/. Backup of prior profile/: {backup_path}")
    else:
        backup_path = workspace.backup_profile("pre-push")
        print(f"Backup of profile/ before push: {backup_path}")

    snap = validate.snapshot(paths.PROFILE_DIR)
    _print_snapshot("profile (about to push)", snap)
    if not snap.sqlite_integrity_ok:
        print("REFUSED: sqlite integrity check failed, not pushing.", file=sys.stderr)
        return 4

    if args.dry_run:
        print("--dry-run: not syncing to AnkiWeb.")
        return 0

    try:
        result = sync.sync_collection(
            paths.PROFILE_DIR, stored, sync_media=args.media, allow_full_sync=args.allow_full_sync
        )
    except sync.FullSyncRequired as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    if result.updated_auth is not None:
        auth.save_auth(result.updated_auth)
        print(f"AnkiWeb redirected this account to a dedicated sync host; saved for future syncs.")
    print(f"Pushed to AnkiWeb: {result.required}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anki-headless")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Interactively obtain and store an AnkiWeb sync token")
    p_login.set_defaults(func=cmd_login)

    p_pull = sub.add_parser("pull", help="Sync AnkiWeb -> profile/, refresh working/")
    p_pull.add_argument("--media", action="store_true", help="Also sync media (slow, off by default)")
    p_pull.add_argument("--allow-full-sync", choices=["upload", "download"], default=None)
    p_pull.set_defaults(func=cmd_pull)

    p_status = sub.add_parser("status", help="Show sync status and local collection counts")
    p_status.set_defaults(func=cmd_status)

    p_run = sub.add_parser("run", help="Run one or more headless add-on operations")
    p_run.add_argument(
        "operations", nargs="+", choices=list(addons.OPERATIONS.keys()) + ["all"]
    )
    p_run.add_argument("--target", choices=["profile", "working"], default="profile")
    p_run.add_argument("--sync-before", dest="sync_before", action="store_true", default=True)
    p_run.add_argument("--no-sync-before", dest="sync_before", action="store_false")
    p_run.add_argument("--sync-after", dest="sync_after", action="store_true", default=True)
    p_run.add_argument("--no-sync-after", dest="sync_after", action="store_false")
    p_run.add_argument("--allow-full-sync", choices=["upload", "download"], default=None)
    p_run.set_defaults(func=cmd_run)

    p_push = sub.add_parser("push", help="Sync profile/ (or promoted working/) up to AnkiWeb")
    p_push.add_argument("--promote-working", action="store_true", help="Replace profile/ with working/ first (backed up)")
    p_push.add_argument("--dry-run", action="store_true")
    p_push.add_argument("--media", action="store_true")
    p_push.add_argument("--allow-full-sync", choices=["upload", "download"], default=None)
    p_push.set_defaults(func=cmd_push)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
