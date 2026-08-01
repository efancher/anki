#!/usr/bin/env python3
"""Backfill PitchAccents / PitchPositions / PitchGraphs on immersion notes.

Uses a Yomitan-format pitch dictionary (Kanjium by default). Does not touch audio.

Usage (Anki open with AnkiConnect):

  python3 scripts/backfill_immersion_pitch_ankiconnect.py
  python3 scripts/backfill_immersion_pitch_ankiconnect.py --dry-run
  python3 scripts/backfill_immersion_pitch_ankiconnect.py --model "WK Shadowing Immersion"
  python3 scripts/backfill_immersion_pitch_ankiconnect.py --force   # overwrite existing pitch
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from immersion_pitch import (  # noqa: E402
    load_immersion_pitch_index,
    pitch_field_values,
    resolve_pitch_dict_path,
)

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
DEFAULT_MODELS = (
    "WK Satori Immersion",
    "WK Shadowing Immersion",
)
BATCH_SIZE = 50


def anki_connect(base_url: str, action: str, **params: object) -> Any:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {base_url}. "
            f"Is Anki open with AnkiConnect installed?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def field_value(note: dict, name: str) -> str:
    fields = note.get("fields") or {}
    payload = fields.get(name) or {}
    if isinstance(payload, dict):
        return str(payload.get("value") or "")
    return str(payload or "")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        default=[],
        help="Note type to patch (repeatable; default: Satori + Shadowing Immersion)",
    )
    parser.add_argument("--pitch-dict", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite notes that already have PitchPositions",
    )
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    pitch_path = resolve_pitch_dict_path(
        args.pitch_dict.expanduser().resolve() if args.pitch_dict else None
    )
    if pitch_path is None:
        raise SystemExit(
            "Pitch dictionary not found. Pass --pitch-dict or set WK_PITCH_DICT."
        )
    print(f"Loading pitch dictionary: {pitch_path}")
    pitch_index = load_immersion_pitch_index(pitch_path)

    models = args.models or list(DEFAULT_MODELS)
    available = set(anki_connect(args.anki_connect, "modelNames") or [])
    updated = 0
    skipped = 0
    missing = 0

    for model_name in models:
        if model_name not in available:
            print(f"Skip missing note type: {model_name}")
            continue
        note_ids = list(
            anki_connect(
                args.anki_connect,
                "findNotes",
                query=f'note:"{model_name}"',
            )
            or []
        )
        print(f"{model_name}: {len(note_ids)} notes")
        for start in range(0, len(note_ids), BATCH_SIZE):
            batch = note_ids[start : start + BATCH_SIZE]
            notes = anki_connect(args.anki_connect, "notesInfo", notes=batch) or []
            for note in notes:
                if args.limit and updated >= args.limit:
                    print(
                        f"Updated {updated}, skipped {skipped}, no-match {missing}"
                    )
                    return 0
                expression = field_value(note, "Expression").strip()
                reading = field_value(note, "Reading").strip()
                existing_pos = field_value(note, "PitchPositions").strip()
                if existing_pos and not args.force:
                    skipped += 1
                    continue
                pitch_fields = pitch_field_values(expression, reading, pitch_index)
                if not pitch_fields["PitchPositions"]:
                    missing += 1
                    continue
                if (
                    pitch_fields["PitchAccents"] == field_value(note, "PitchAccents")
                    and pitch_fields["PitchPositions"] == existing_pos
                    and pitch_fields["PitchGraphs"] == field_value(note, "PitchGraphs")
                ):
                    skipped += 1
                    continue
                updated += 1
                if updated <= 12:
                    print(
                        f"{'DRY ' if args.dry_run else ''}"
                        f"{expression} ({reading}) → {pitch_fields['PitchPositions']}"
                    )
                elif updated == 13:
                    print("…")
                if not args.dry_run:
                    anki_connect(
                        args.anki_connect,
                        "updateNoteFields",
                        note={"id": note["noteId"], "fields": pitch_fields},
                    )

    print(f"Updated {updated}, skipped {skipped}, no-match {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
