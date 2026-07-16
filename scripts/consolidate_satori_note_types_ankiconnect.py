#!/usr/bin/env python3
"""Consolidate forked 'WK Satori Immersion+' note types into the canonical one.

Anki forks a note type by appending '+' to the *incoming* name when an import's
field order/schema differs from an existing note type of the same name. Because
Anki dedups imports by GUID, notes stuck under the forked type are then skipped
on every future import and become invisible to tooling that queries the
canonical note type (gloss worksheet, audio backfill, new-card prioritization).

This migrates every note under a forked type back to the canonical type via
AnkiConnect's ``updateNoteModel``. Card scheduling is preserved (card ids,
intervals, reps, and due stay intact). Fields transfer by name; a fork has the
same field *names* as the canonical type, only the order differs.

AnkiConnect has no delete-model action, so the emptied fork type must be removed
manually afterwards: Tools -> Manage Note Types -> select the '+' type -> Delete.

Usage (Anki open with AnkiConnect):
  python3 scripts/consolidate_satori_note_types_ankiconnect.py
  python3 scripts/consolidate_satori_note_types_ankiconnect.py --dry-run
  python3 scripts/consolidate_satori_note_types_ankiconnect.py \
      --target "WK Satori Immersion" --source "WK Satori Immersion+"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
# Anki appends one or more '+' to a forked note type's name.
FORK_SUFFIX_PATTERN = r"\++$"

try:
    from satori_decks import SATORI_NOTE_TYPE_NAME as DEFAULT_TARGET  # noqa: E402
except Exception:  # noqa: BLE001 — keep usable even if satori_decks deps are missing
    DEFAULT_TARGET = "WK Satori Immersion"


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {base_url}. Is Anki open with AnkiConnect?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def detect_fork_types(base_url: str, target: str) -> List[str]:
    """Note types named like the target with a trailing run of '+' (e.g. 'Name+')."""
    pattern = re.compile(re.escape(target) + FORK_SUFFIX_PATTERN)
    return sorted(name for name in anki_connect(base_url, "modelNames") if pattern.fullmatch(name))


def migrate_source(
    base_url: str, source: str, target: str, target_fields: Sequence[str], *, dry_run: bool
) -> int:
    note_ids = anki_connect(base_url, "findNotes", query=f'note:"{source}"')
    if not note_ids:
        print(f"  {source}: no notes; nothing to migrate.")
        return 0

    infos = anki_connect(base_url, "notesInfo", notes=note_ids)
    source_fields = set(infos[0]["fields"].keys()) if infos else set()
    target_set = set(target_fields)
    dropped = source_fields - target_set
    empty = target_set - source_fields
    if dropped:
        print(f"  WARNING: {source} fields not in target (values dropped): {sorted(dropped)}")
    if empty:
        print(f"  note: target-only fields left empty on migrated notes: {sorted(empty)}")

    if dry_run:
        print(f"  {source}: would migrate {len(infos)} note(s) -> {target}")
        return 0

    migrated = 0
    for info in infos:
        fields: Dict[str, str] = {
            name: value["value"]
            for name, value in info["fields"].items()
            if name in target_set
        }
        anki_connect(
            base_url,
            "updateNoteModel",
            note={
                "id": info["noteId"],
                "modelName": target,
                "fields": fields,
                "tags": info.get("tags", []),
            },
        )
        migrated += 1
    print(f"  {source}: migrated {migrated} note(s) -> {target}")
    return migrated


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT, help="AnkiConnect URL")
    parser.add_argument(
        "--target", default=DEFAULT_TARGET, help=f"Canonical note type (default: {DEFAULT_TARGET})"
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        dest="sources",
        help="Forked note type to migrate (repeatable). Default: auto-detect '<target>+' types.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would migrate, change nothing"
    )
    args = parser.parse_args(argv)

    models = anki_connect(args.anki_connect, "modelNames")
    if args.target not in models:
        raise SystemExit(f"Target note type not found: {args.target!r}")

    sources = args.sources or detect_fork_types(args.anki_connect, args.target)
    if not sources:
        print(f"No forked note types found for target {args.target!r}. Nothing to do.")
        return 0

    target_fields = anki_connect(args.anki_connect, "modelFieldNames", modelName=args.target)
    print(f"Target: {args.target} ({len(target_fields)} fields)")
    print(f"Forked source type(s): {sources}")

    total = 0
    for source in sources:
        if source not in models:
            print(f"  {source}: not found, skipping.")
            continue
        total += migrate_source(
            args.anki_connect, source, args.target, target_fields, dry_run=args.dry_run
        )

    if args.dry_run:
        print("\nDry run: no changes made.")
        return 0

    remaining = {s: len(anki_connect(args.anki_connect, "findNotes", query=f'note:"{s}"')) for s in sources}
    target_count = len(anki_connect(args.anki_connect, "findNotes", query=f'note:"{args.target}"'))
    print(f"\nMigrated {total} note(s). {args.target} now holds {target_count} note(s).")
    emptied = [s for s, n in remaining.items() if n == 0]
    if emptied:
        print(
            "Now delete the emptied fork type(s) in Anki "
            "(Tools -> Manage Note Types -> Delete): " + ", ".join(emptied)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
