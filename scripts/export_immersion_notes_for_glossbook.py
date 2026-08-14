"""Read-only export of immersion notes for the Glossbook unified-app import.

One-time, one-directional: dumps `WK Satori Immersion` / `WK Shadowing
Immersion` / `WK Shadowing Candidate` note fields to a JSON file that
`jp_sentence_splits/scripts/import-anki-sentences.ts` reads separately.
Never writes to the collection (no add_note/update_note/push anywhere in
this script) and never prints note content to the terminal beyond counts.

Prerequisite: run `scripts/anki_sync_pull` first so `anki_headless`'s local
profile is up to date. This script does not sync.

Usage:
    .venv-headless/bin/python3 scripts/export_immersion_notes_for_glossbook.py \
        [--out out/glossbook_import_export.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anki.collection import Collection  # noqa: E402

from anki_headless import paths  # noqa: E402

NOTE_TYPES: tuple[str, ...] = (
    "WK Satori Immersion",
    "WK Shadowing Immersion",
    "WK Shadowing Candidate",
)

DEFAULT_OUT = REPO_ROOT / "out" / "glossbook_import_export.json"


def export_note_type(col: Collection, note_type: str) -> List[Dict[str, object]]:
    notes = []
    for note_id in col.find_notes(f'note:"{note_type}"'):
        note = col.get_note(note_id)
        fields = dict(note.items())
        notes.append(
            {
                "noteType": note_type,
                "duplicateKey": fields.get("DuplicateKey", ""),
                "fields": fields,
            }
        )
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    col = Collection(str(paths.collection_path(paths.PROFILE_DIR)))
    try:
        all_notes: List[Dict[str, object]] = []
        for note_type in NOTE_TYPES:
            notes = export_note_type(col, note_type)
            print(f"{note_type}: {len(notes)} notes")
            all_notes.extend(notes)
    finally:
        col.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(all_notes, ensure_ascii=False, indent=2))
    print(f"Wrote {len(all_notes)} notes to {args.out}")


if __name__ == "__main__":
    main()
