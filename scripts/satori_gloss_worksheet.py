#!/usr/bin/env python3
"""
Print Cure Dolly–style gloss worksheets for Satori immersion sentences.

Practice mapping Japanese order → sticky English. Satori's fluent translation
stays on the EN line; CHUNK / ROLE / LIT are blanks for you to fill.

Requires Anki + AnkiConnect (default http://127.0.0.1:8765), or pass a sentence
directly:

  python3 scripts/satori_gloss_worksheet.py
  python3 scripts/satori_gloss_worksheet.py --limit 5
  python3 scripts/satori_gloss_worksheet.py --selected
  python3 scripts/satori_gloss_worksheet.py --note-id 2031086401000
  python3 scripts/satori_gloss_worksheet.py --sentence '暖かい春がやって来ました。' \\
      --translation 'The warm spring came along.'
  python3 scripts/satori_gloss_worksheet.py -o /tmp/gloss.txt
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from satori_gloss import (  # noqa: E402
    DEFAULT_DECK,
    DEFAULT_NOTE_TYPE,
    GlossSentence,
    format_worksheets,
    gloss_items_from_notes,
)

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
DEFAULT_LIMIT = 10


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {base_url}. "
            f"Is Anki open with AnkiConnect installed?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def resolve_note_ids(
    base_url: str,
    *,
    selected: bool,
    note_ids: Sequence[int],
    query: str,
    limit: int,
) -> List[int]:
    if note_ids:
        return [int(nid) for nid in note_ids]
    if selected:
        ids = anki_connect(base_url, "guiSelectedNotes") or []
        if not ids:
            raise SystemExit("No notes selected in the Anki browser.")
        return [int(nid) for nid in ids]
    ids = anki_connect(base_url, "findNotes", query=query) or []
    return [int(nid) for nid in ids][:limit]


def load_from_anki(
    base_url: str,
    *,
    selected: bool,
    note_ids: Sequence[int],
    query: str,
    limit: int,
) -> List[GlossSentence]:
    ids = resolve_note_ids(
        base_url,
        selected=selected,
        note_ids=note_ids,
        query=query,
        limit=limit,
    )
    if not ids:
        raise SystemExit(f"No notes matched query: {query!r}")
    notes = anki_connect(base_url, "notesInfo", notes=ids) or []
    items = gloss_items_from_notes(notes)
    if not items:
        raise SystemExit("Matched notes had no Sentence / ClozeSentence field.")
    return items


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--anki-connect",
        default=DEFAULT_ANKI_CONNECT,
        help=f"AnkiConnect URL (default: {DEFAULT_ANKI_CONNECT})",
    )
    parser.add_argument(
        "--query",
        default=f'note:"{DEFAULT_NOTE_TYPE}" deck:"{DEFAULT_DECK}"',
        help="Anki browser query when not using --selected / --note-id / --sentence",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Max notes from --query (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--note-id",
        type=int,
        action="append",
        default=[],
        dest="note_ids",
        help="Specific note id (repeatable)",
    )
    parser.add_argument(
        "--selected",
        action="store_true",
        help="Use notes selected in the Anki browser",
    )
    parser.add_argument(
        "--sentence",
        default="",
        help="Ad-hoc Japanese sentence (skips Anki)",
    )
    parser.add_argument(
        "--translation",
        default="",
        help="Ad-hoc English (with --sentence)",
    )
    parser.add_argument(
        "--expression",
        default="",
        help="Optional target word label (with --sentence)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write worksheet text to this path (also prints to stdout)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.sentence:
        items = [
            GlossSentence(
                japanese=args.sentence.strip(),
                english=args.translation.strip(),
                expression=args.expression.strip(),
            )
        ]
    else:
        items = load_from_anki(
            args.anki_connect,
            selected=args.selected,
            note_ids=args.note_ids,
            query=args.query,
            limit=args.limit,
        )

    text = format_worksheets(items)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
