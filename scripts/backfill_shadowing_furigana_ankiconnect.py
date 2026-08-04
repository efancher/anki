#!/usr/bin/env python3
"""Backfill SentenceFurigana / SentenceKana / Furigana on Shadowing immersion notes.

Shadowing projects store a full-kana ``reading`` per sentence; imports used to leave
``SentenceFurigana`` empty, so card backs showed plain kanji only. This walks one or
more project dirs, aligns japanese+reading into Anki bracket markup, and updates
matching notes via AnkiConnect.

Usage (Anki open with AnkiConnect):

  python3 scripts/backfill_shadowing_furigana_ankiconnect.py \\
    ~/shadowing/cli/projects/FkX4A-ZLBrc
  python3 scripts/backfill_shadowing_furigana_ankiconnect.py --dry-run \\
    ~/shadowing/cli/projects
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anki_furigana import anki_furigana_brackets, word_furigana_brackets  # noqa: E402
from shadowing_decks import (  # noqa: E402
    SHADOWING_NOTE_TYPE_NAME,
    load_shadowing_project,
)

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
BATCH_SIZE = 50


def anki_connect(base_url: str, action: str, **params: object) -> Any:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"AnkiConnect error ({action}): {exc}") from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect error ({action}): {payload['error']}")
    return payload.get("result")


def iter_project_roots(paths: Sequence[Path]) -> Iterable[Path]:
    for path in paths:
        path = path.expanduser().resolve()
        if (path / "sentences.json").is_file() or (path / "source.json").is_file():
            yield path
            continue
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_dir() and (
                    (child / "sentences.json").is_file()
                    or (child / "source.json").is_file()
                ):
                    yield child


def reading_by_sentence_id(project_root: Path) -> Dict[str, Tuple[str, str]]:
    """Map sentence_id → (japanese, reading)."""
    project = load_shadowing_project(project_root)
    return {
        sentence.sentence_id: (sentence.japanese, sentence.reading)
        for sentence in project.sentences
    }


def field_value(fields: Dict[str, Any], name: str) -> str:
    return ((fields.get(name) or {}).get("value") or "").strip()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "projects",
        nargs="+",
        type=Path,
        help="Shadowing project dir(s) or a parent containing projects",
    )
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite non-empty SentenceFurigana / Furigana fields",
    )
    parser.add_argument(
        "--model",
        default=SHADOWING_NOTE_TYPE_NAME,
        help=f"Note type (default: {SHADOWING_NOTE_TYPE_NAME})",
    )
    args = parser.parse_args(argv)

    sentence_lookup: Dict[str, Tuple[str, str]] = {}
    for root in iter_project_roots(args.projects):
        print(f"Loading {root}…")
        sentence_lookup.update(reading_by_sentence_id(root))
    if not sentence_lookup:
        raise SystemExit("No sentences found in the given project path(s).")

    note_ids = list(
        anki_connect(args.anki_connect, "findNotes", query=f'note:"{args.model}"')
    )
    print(f"Scanning {len(note_ids)} note(s)…")
    updated = skipped = missing = failed_align = 0

    for start in range(0, len(note_ids), BATCH_SIZE):
        batch = note_ids[start : start + BATCH_SIZE]
        infos = anki_connect(args.anki_connect, "notesInfo", notes=batch)
        for info in infos:
            fields = info.get("fields") or {}
            duplicate_key = field_value(fields, "DuplicateKey")
            parts = [p for p in duplicate_key.split("|") if p]
            if len(parts) < 2:
                skipped += 1
                continue
            sentence_id = parts[1]
            pair = sentence_lookup.get(sentence_id)
            if pair is None:
                missing += 1
                continue
            japanese, reading = pair
            sentence_field = field_value(fields, "Sentence") or japanese
            sentence_furigana = anki_furigana_brackets(sentence_field, reading)
            if not sentence_furigana:
                failed_align += 1
                continue
            expression = field_value(fields, "Expression")
            reading_field = field_value(fields, "Reading")
            word_furigana = word_furigana_brackets(expression, reading_field)
            existing_sf = field_value(fields, "SentenceFurigana")
            existing_f = field_value(fields, "Furigana")
            existing_sk = field_value(fields, "SentenceKana")
            patch: Dict[str, str] = {}
            if args.force or not existing_sf:
                patch["SentenceFurigana"] = sentence_furigana
            if reading and (args.force or not existing_sk):
                patch["SentenceKana"] = reading
            if word_furigana and (args.force or not existing_f):
                patch["Furigana"] = word_furigana
            if not patch:
                skipped += 1
                continue
            if args.dry_run:
                updated += 1
                continue
            anki_connect(
                args.anki_connect,
                "updateNoteFields",
                note={"id": info["noteId"], "fields": patch},
            )
            updated += 1

    action = "would update" if args.dry_run else "updated"
    print(
        f"Done: {action} {updated}; skipped {skipped}; "
        f"no project sentence {missing}; align failed {failed_align}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
