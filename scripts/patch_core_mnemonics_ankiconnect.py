#!/usr/bin/env python3
"""Expand deferred WK Core Item meaning/reading mnemonics in live Anki.

Rewrites Mnemonic / ReadingMnemonic on `WK Core Item` notes when WK copy only
points at a radical, kanji, or related vocab (same-as / on'yomi-kun'yomi stubs).

Usage (Anki open with AnkiConnect):
  python3 scripts/patch_core_mnemonics_ankiconnect.py
  python3 scripts/patch_core_mnemonics_ankiconnect.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import (  # noqa: E402
    kanji_index_by_characters,
    meaning_mnemonic_html,
    radical_index_by_id,
    reading_mnemonic_html,
    subject_index_by_id,
    vocab_index_by_characters,
)

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
DEFAULT_MODEL = "WK Core Item"
# Anki may keep notes on a cloned note type after field/template updates (e.g. WK Core Item++).
MODEL_CANDIDATES = (
    "WK Core Item++",
    "WK Core Item+",
    "WK Core Item",
)
DEFAULT_CACHE = REPO_ROOT / ".wk_cache" / "subjects_vocabulary_kanji_radical.json"
BATCH_SIZE = 40


def anki_connect(base_url: str, action: str, **params: object) -> Any:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {base_url}. "
            f"Is Anki open with AnkiConnect installed?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def load_subjects(cache_path: Path) -> List[dict]:
    if not cache_path.is_file():
        raise SystemExit(f"Missing WK subject cache: {cache_path}")
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    items = list(payload.get("items") or [])
    if not items:
        raise SystemExit(f"No subjects in {cache_path}")
    return items


def field_map(note: dict) -> Dict[str, str]:
    fields = note.get("fields") or {}
    return {name: (payload.get("value") or "") for name, payload in fields.items()}


def resolve_models(base_url: str, requested: Optional[str]) -> List[str]:
    available = set(anki_connect(base_url, "modelNames") or [])
    if requested:
        if requested not in available:
            raise SystemExit(f"Note type not found: {requested}")
        return [requested]
    models = [name for name in MODEL_CANDIDATES if name in available]
    if not models and DEFAULT_MODEL in available:
        models = [DEFAULT_MODEL]
    if not models:
        raise SystemExit(
            "No WK Core Item note types found. Pass --model explicitly."
        )
    return models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument(
        "--model",
        default="",
        help="Note type to patch (default: auto-detect WK Core Item / + / ++)",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max notes to update (0=all)")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print summary (and first few sample updates)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    subjects = load_subjects(args.cache)
    radical_index = radical_index_by_id(subjects)
    subject_by_id = subject_index_by_id(subjects)
    vocab_by_characters = vocab_index_by_characters(subjects)
    kanji_by_characters = kanji_index_by_characters(subjects)

    models = resolve_models(args.anki_connect, args.model or None)
    updated = 0
    skipped = 0
    missing = 0
    sample_printed = 0

    for model_name in models:
        note_ids = list(
            anki_connect(
                args.anki_connect,
                "findNotes",
                query=f'note:"{model_name}"',
            )
            or []
        )
        print(f"Found {len(note_ids)} {model_name} notes")
        if not note_ids:
            continue

        for start in range(0, len(note_ids), BATCH_SIZE):
            batch_ids = note_ids[start : start + BATCH_SIZE]
            notes = anki_connect(args.anki_connect, "notesInfo", notes=batch_ids) or []
            for note in notes:
                if args.limit and updated >= args.limit:
                    print(
                        f"Updated {updated}, skipped {skipped}, missing subject {missing}"
                    )
                    return
                fields = field_map(note)
                subject_id_raw = (fields.get("WkSubjectId") or "").strip()
                if not subject_id_raw.isdigit():
                    skipped += 1
                    continue
                subject = subject_by_id.get(int(subject_id_raw))
                if subject is None:
                    missing += 1
                    continue
                new_meaning = meaning_mnemonic_html(
                    subject,
                    radical_index,
                    subject_by_id=subject_by_id,
                )
                new_reading = reading_mnemonic_html(
                    subject,
                    subject_by_id=subject_by_id,
                    vocab_by_characters=vocab_by_characters,
                    kanji_by_characters=kanji_by_characters,
                )
                changes: Dict[str, str] = {}
                if new_meaning and new_meaning != fields.get("Mnemonic", ""):
                    changes["Mnemonic"] = new_meaning
                if new_reading and new_reading != fields.get("ReadingMnemonic", ""):
                    changes["ReadingMnemonic"] = new_reading
                if not changes:
                    skipped += 1
                    continue
                updated += 1
                expr = fields.get("Expression") or subject_id_raw
                if sample_printed < 12:
                    print(
                        f"{'DRY ' if args.dry_run else ''}"
                        f"update {expr} ({subject_id_raw}): {', '.join(changes.keys())}"
                    )
                    sample_printed += 1
                    if args.quiet and sample_printed == 12:
                        print("…")
                elif not args.quiet:
                    print(
                        f"{'DRY ' if args.dry_run else ''}"
                        f"update {expr} ({subject_id_raw}): {', '.join(changes.keys())}"
                    )
                if not args.dry_run:
                    anki_connect(
                        args.anki_connect,
                        "updateNoteFields",
                        note={"id": note["noteId"], "fields": changes},
                    )

    print(f"Updated {updated}, skipped {skipped}, missing subject {missing}")


if __name__ == "__main__":
    main()
