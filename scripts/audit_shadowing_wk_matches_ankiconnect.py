#!/usr/bin/env python3
"""Audit Shadowing Immersion notes whose WK subject no longer matches their sentence.

Legacy directory imports matched WK vocabulary by scanning the sentence, and an
over-eager kanji-stem key could attach the wrong subject: the 年 of 同い年 became
２０１１年, the 担 of 担任 became 担ぐ. Such a note asks for a reading the sentence
never contains, so its front and back disagree.

This re-runs the current matcher over each note's Sentence and reports notes whose
WkSubjectId is no longer produced. Reporting only by default; --delete removes them
so a rebuilt package can re-import the sentence with the right subjects.

Usage (Anki open with AnkiConnect):

  python3 scripts/audit_shadowing_wk_matches_ankiconnect.py
  python3 scripts/audit_shadowing_wk_matches_ankiconnect.py --note-type "WK Shadowing Candidate"
  python3 scripts/audit_shadowing_wk_matches_ankiconnect.py --delete
"""

from __future__ import annotations

import argparse
import json
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
)
from shadowing_match import match_wk_vocab_in_sentence  # noqa: E402

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
DEFAULT_WK_INDEX = REPO_ROOT / "out" / "wk_mining_vocab_index.json"
SHADOWING_NOTE_TYPES = (
    SHADOWING_NOTE_TYPE_NAME,
    SHADOWING_CANDIDATE_NOTE_TYPE_NAME,
)
ANKI_CONNECT_TIMEOUT_SECONDS = 180


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=ANKI_CONNECT_TIMEOUT_SECONDS) as response:
        payload = json.load(response)
    if payload.get("error"):
        raise RuntimeError(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def field_value(fields: dict, name: str) -> str:
    return ((fields.get(name) or {}).get("value") or "").strip()


def audit_note_type(
    *,
    base_url: str,
    model_name: str,
    index: dict,
    match_cache: dict[str, dict[str, str]],
) -> list[dict]:
    note_ids = list(anki_connect(base_url, "findNotes", query=f'note:"{model_name}"'))
    if not note_ids:
        print(f"{model_name}: 0 notes")
        return []
    infos = anki_connect(base_url, "notesInfo", notes=note_ids)
    stale: list[dict] = []
    for info in infos:
        fields = info.get("fields") or {}
        sentence = field_value(fields, "Sentence")
        subject_id = field_value(fields, "WkSubjectId")
        # Candidate notes carry no WK subject, so there is nothing to verify.
        if not sentence or not subject_id:
            continue
        if sentence not in match_cache:
            match_cache[sentence] = {
                str(match.wk_entry["id"]): match.expression
                for match in match_wk_vocab_in_sentence(sentence, index)
            }
        matched = match_cache[sentence]
        if subject_id in matched:
            continue
        stale.append(
            {
                "note_id": int(info["noteId"]),
                "model": model_name,
                "expression": field_value(fields, "Expression"),
                "reading": field_value(fields, "Reading"),
                "subject_id": subject_id,
                "sentence": sentence,
                "now_matched": sorted(matched.values()),
            }
        )
    print(f"{model_name}: {len(note_ids)} notes, {len(stale)} no longer matched")
    return stale


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
        "--wk-index",
        type=Path,
        default=DEFAULT_WK_INDEX,
        help=f"WK mining vocab index JSON (default: {DEFAULT_WK_INDEX})",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete the reported notes (default: report only)",
    )
    args = parser.parse_args(argv)

    if not args.wk_index.is_file():
        raise SystemExit(
            f"WK index not found: {args.wk_index}\n"
            "Generate it first (python3 wk_decks.py --from-config)."
        )
    index = json.loads(args.wk_index.read_text(encoding="utf-8"))

    try:
        models = set(anki_connect(args.anki_connect, "modelNames") or [])
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {args.anki_connect}. Is Anki open?\n{exc}"
        ) from exc

    note_types = [args.note_type] if args.note_type else list(SHADOWING_NOTE_TYPES)
    match_cache: dict[str, dict[str, str]] = {}
    stale: list[dict] = []
    for model_name in note_types:
        if model_name not in models:
            print(f"skip missing note type: {model_name}")
            continue
        stale.extend(
            audit_note_type(
                base_url=args.anki_connect,
                model_name=model_name,
                index=index,
                match_cache=match_cache,
            )
        )

    if not stale:
        print("\nno mismatched notes")
        return 0

    print()
    for item in stale:
        print(f"{item['note_id']}  {item['expression']} ({item['reading']}) "
              f"subject={item['subject_id']}")
        print(f"    sentence: {item['sentence']}")
        print(f"    now matches: {', '.join(item['now_matched']) or '(none)'}")

    if not args.delete:
        print(f"\n{len(stale)} mismatched notes (report only; pass --delete to remove)")
        return 0

    anki_connect(args.anki_connect, "deleteNotes", notes=[i["note_id"] for i in stale])
    print(f"\ndeleted {len(stale)} mismatched notes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
