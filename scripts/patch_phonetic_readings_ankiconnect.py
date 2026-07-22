#!/usr/bin/env python3
"""Patch phonetic-family notes + templates via AnkiConnect.

Updates:
  - Card template layout (phonetic component first; focus table CSS)
  - PhoneticReadings ordered most→least with WK keywords
  - AnchorHtml family focus table (Reading / Started / Total)

Usage (Anki open with AnkiConnect):

  python3 scripts/patch_phonetic_readings_ankiconnect.py --from-cache
  python3 scripts/patch_phonetic_readings_ankiconnect.py --from-cache --templates-only
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Set

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_MODEL = "WK Update-Safe Phonetic Drill++"
ANKI_CONNECT_URL = "http://127.0.0.1:8765"
BATCH_SIZE = 40
KEISEI_PHONETIC = REPO_ROOT / ".wk_cache" / "keisei" / "phonetic_esc.json"
KEISEI_KANJI = REPO_ROOT / ".wk_cache" / "keisei" / "kanji_esc.json"
SUBJECTS_CACHE = REPO_ROOT / ".wk_cache" / "subjects_vocabulary_kanji_radical.json"
ASSIGNMENTS_CACHE = (
    REPO_ROOT
    / ".wk_cache"
    / "assignments_srs_stages_1_2_3_4_5_6_7_8_9_started_true_subject_types_radical_kanji_vocabulary.json"
)


def anki_connect(action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        ANKI_CONNECT_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            "Could not reach AnkiConnect at "
            f"{ANKI_CONNECT_URL}. Is Anki open with AnkiConnect installed?\n"
            f"{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action} failed: {payload['error']}")
    return payload["result"]


def resolve_model_name(preferred: str) -> str:
    names = anki_connect("modelNames")
    if preferred in names:
        return preferred
    candidates = [
        name for name in names if name.startswith("WK Update-Safe Phonetic Drill")
    ]
    if not candidates:
        raise SystemExit("No WK Update-Safe Phonetic Drill note type found in Anki.")
    return max(candidates, key=len)


def push_templates(model_name: str) -> None:
    from wk_decks import MODEL_TEMPLATE_VERSIONS, make_phonetic_drill_model

    model = make_phonetic_drill_model()
    templates = {
        tpl["name"]: {"Front": tpl["qfmt"], "Back": tpl["afmt"]} for tpl in model.templates
    }
    anki_connect(
        "updateModelTemplates",
        model={"name": model_name, "templates": templates},
    )
    anki_connect(
        "updateModelStyling",
        model={"name": model_name, "css": model.css},
    )
    print(
        f"Pushed templates + CSS for {model_name} "
        f"({MODEL_TEMPLATE_VERSIONS['phonetic_drill']})"
    )


def load_json(path: Path) -> object:
    if not path.is_file():
        raise SystemExit(f"Missing cache file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_started_kanji_ids() -> Set[int]:
    payload = load_json(ASSIGNMENTS_CACHE)
    items = payload.get("items") if isinstance(payload, dict) else payload
    started: Set[int] = set()
    for item in items or []:
        data = item.get("data") or {}
        if data.get("subject_type") != "kanji":
            continue
        if data.get("started_at"):
            started.add(int(data["subject_id"]))
    return started


def load_all_kanji_by_char() -> Dict[str, dict]:
    payload = load_json(SUBJECTS_CACHE)
    items = payload.get("items") if isinstance(payload, dict) else payload
    by_char: Dict[str, dict] = {}
    for subject in items or []:
        if subject.get("object") != "kanji":
            continue
        char = (subject.get("data") or {}).get("characters")
        if char:
            by_char[char] = subject
    return by_char


def find_phonetic_note_ids(model_name: str) -> List[int]:
    note_ids = anki_connect(
        "findNotes",
        query=f'deck:"WaniKani Phonetic Families" note:"{model_name}"',
    )
    if not note_ids:
        note_ids = anki_connect("findNotes", query='deck:"WaniKani Phonetic Families"')
    return [int(note_id) for note_id in note_ids]


def patch_note_fields(model_name: str) -> None:
    from wk_decks import (
        best_reading_keyword_by_kana,
        phonetic_component_readings_label,
        phonetic_family_focus_html,
        phonetic_wk_family_members,
    )

    subjects_payload = load_json(SUBJECTS_CACHE)
    subjects = (
        subjects_payload.get("items")
        if isinstance(subjects_payload, dict)
        else subjects_payload
    )
    keyword_by_kana = best_reading_keyword_by_kana(subjects)
    keisei_phonetic = load_json(KEISEI_PHONETIC)
    keisei_kanji = load_json(KEISEI_KANJI)
    all_kanji_by_char = load_all_kanji_by_char()
    started_ids = load_started_kanji_ids()

    print(f"Keywords: {len(keyword_by_kana)} · started kanji: {len(started_ids)}")
    if "しょ" in keyword_by_kana:
        print(f"Sample: しょ - {keyword_by_kana['しょ']}")

    note_ids = find_phonetic_note_ids(model_name)
    print(f"Found {len(note_ids)} phonetic notes")

    updated = 0
    unchanged = 0
    for start in range(0, len(note_ids), BATCH_SIZE):
        chunk = note_ids[start : start + BATCH_SIZE]
        for info in anki_connect("notesInfo", notes=chunk):
            fields = info["fields"]
            piece = fields["PhoneticPiece"]["value"]
            subject_id_text = fields["WkSubjectId"]["value"].strip()
            try:
                subject_id = int(subject_id_text)
            except ValueError:
                subject_id = -1

            focus_members = phonetic_wk_family_members(
                piece, keisei_phonetic, all_kanji_by_char
            )
            readings = phonetic_component_readings_label(
                piece,
                keisei_phonetic,
                keyword_by_kana=keyword_by_kana,
                members=focus_members,
                started_kanji_ids=started_ids,
                keisei_kanji=keisei_kanji,
            )
            anchor = phonetic_family_focus_html(
                piece,
                focus_members,
                subject_id,
                started_ids,
                all_kanji_by_char,
                keisei_phonetic,
                keisei_kanji,
                keyword_by_kana=keyword_by_kana,
            )
            current_readings = fields.get("PhoneticReadings", {}).get("value", "")
            current_anchor = fields.get("AnchorHtml", {}).get("value", "")
            if current_readings == readings and current_anchor == anchor:
                unchanged += 1
                continue
            anki_connect(
                "updateNoteFields",
                note={
                    "id": info["noteId"],
                    "fields": {
                        "PhoneticReadings": readings,
                        "AnchorHtml": anchor,
                    },
                },
            )
            updated += 1

    print(f"Patched fields on {updated} notes ({unchanged} already current).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="Rebuild PhoneticReadings + AnchorHtml from WK/Keisei caches",
    )
    parser.add_argument(
        "--templates-only",
        action="store_true",
        help="Only push card templates/CSS",
    )
    parser.add_argument(
        "--skip-templates",
        action="store_true",
        help="Do not push templates/CSS",
    )
    args = parser.parse_args()

    model_name = resolve_model_name(DEFAULT_MODEL)
    print(f"Using note type: {model_name}")

    if not args.skip_templates:
        push_templates(model_name)
    if args.templates_only:
        return
    if not args.from_cache:
        raise SystemExit("Pass --from-cache to rebuild note fields (or --templates-only).")
    patch_note_fields(model_name)


if __name__ == "__main__":
    main()
