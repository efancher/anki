#!/usr/bin/env python3
"""
Print Cure Dolly–style gloss worksheets for Satori immersion sentences.

Practice mapping Japanese order → sticky English. Satori's fluent translation
stays on the EN line; CHUNK / ROLE / LIT are blanks for you to fill.

Duplicate sentences (same JP from different target words) are collapsed.
By default an answer key is appended after the blanks (heuristic CHUNK/ROLE/LIT).

Generated answers are cached under .wk_cache/satori_gloss/answers.json so re-runs
reuse prior output (and skip the MyMemory MT calls). Use --refresh-cache to
regenerate, or --no-cache to bypass the cache entirely.

Requires Anki + AnkiConnect (default http://127.0.0.1:8765), or pass a sentence
directly:

  python3 scripts/satori_gloss_worksheet.py
  python3 scripts/satori_gloss_worksheet.py --limit 5
  python3 scripts/satori_gloss_worksheet.py --selected
  python3 scripts/satori_gloss_worksheet.py --note-id 2031086401000
  python3 scripts/satori_gloss_worksheet.py --sentence '暖かい春がやって来ました。' \\
      --translation 'The warm spring came along.'
  python3 scripts/satori_gloss_worksheet.py -o /tmp/gloss.txt
  python3 scripts/satori_gloss_worksheet.py -o /tmp/gloss.txt --answers-file /tmp/gloss-answers.txt
  python3 scripts/satori_gloss_worksheet.py --no-answers
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
    GLOSS_ANSWER_CACHE_FILENAME,
    GLOSS_ANSWER_CACHE_SUBDIR,
    GlossSentence,
    dedupe_gloss_items,
    format_answer_key,
    format_worksheets,
    gloss_items_from_notes,
    load_gloss_answer_cache,
    save_gloss_answer_cache,
)

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
DEFAULT_LIMIT = 10
# Pull extra notes before dedupe so --limit counts unique sentences.
NOTE_FETCH_MULTIPLIER = 5
NOTE_FETCH_CAP = 200
DEFAULT_CACHE_PATH = (
    REPO_ROOT / ".wk_cache" / GLOSS_ANSWER_CACHE_SUBDIR / GLOSS_ANSWER_CACHE_FILENAME
)


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
    fetch_limit: int,
) -> List[int]:
    if note_ids:
        return [int(nid) for nid in note_ids]
    if selected:
        ids = anki_connect(base_url, "guiSelectedNotes") or []
        if not ids:
            raise SystemExit("No notes selected in the Anki browser.")
        return [int(nid) for nid in ids]
    ids = anki_connect(base_url, "findNotes", query=query) or []
    return [int(nid) for nid in ids][:fetch_limit]


def load_from_anki(
    base_url: str,
    *,
    selected: bool,
    note_ids: Sequence[int],
    query: str,
    limit: int,
) -> List[GlossSentence]:
    fetch_limit = limit
    if not note_ids and not selected:
        fetch_limit = min(max(limit * NOTE_FETCH_MULTIPLIER, limit), NOTE_FETCH_CAP)
    ids = resolve_note_ids(
        base_url,
        selected=selected,
        note_ids=note_ids,
        query=query,
        fetch_limit=fetch_limit,
    )
    if not ids:
        raise SystemExit(f"No notes matched query: {query!r}")
    notes = anki_connect(base_url, "notesInfo", notes=ids) or []
    items = dedupe_gloss_items(gloss_items_from_notes(notes))
    if not items:
        raise SystemExit("Matched notes had no Sentence / ClozeSentence field.")
    if not note_ids and not selected:
        items = items[:limit]
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
        help=f"Max unique sentences from --query (default: {DEFAULT_LIMIT})",
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
    parser.add_argument(
        "--answers-file",
        type=Path,
        default=None,
        help="Write answer key only to this path (blanks still print/save via -o)",
    )
    parser.add_argument(
        "--no-answers",
        action="store_true",
        help="Omit the appended answer key from the main output",
    )
    parser.add_argument(
        "--cache-file",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help=f"Answer cache path (default: {DEFAULT_CACHE_PATH})",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Do not read or write the answer cache (always regenerate)",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore existing cached answers and overwrite them with fresh output",
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

    include_answers = not args.no_answers and args.answers_file is None
    generating_answers = include_answers or args.answers_file is not None

    answer_cache: Optional[dict] = None
    if generating_answers and not args.no_cache:
        answer_cache = {} if args.refresh_cache else load_gloss_answer_cache(args.cache_file)

    text = format_worksheets(
        items, include_answers=include_answers, answer_cache=answer_cache
    )
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote {args.output}", file=sys.stderr)
    if args.answers_file is not None:
        answers = format_answer_key(items, answer_cache=answer_cache)
        args.answers_file.parent.mkdir(parents=True, exist_ok=True)
        args.answers_file.write_text(answers + "\n", encoding="utf-8")
        print(f"Wrote answers {args.answers_file}", file=sys.stderr)
    if answer_cache is not None:
        save_gloss_answer_cache(args.cache_file, answer_cache)
        print(
            f"Cached {len(answer_cache)} answer(s) → {args.cache_file}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
