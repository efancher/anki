#!/usr/bin/env python3
"""Patch Core Item PhoneticHint + templates via AnkiConnect.

Adds/fills PhoneticHint on WK Core Item notes when the card reading is an
on'yomi that the kanji's Keisei phonetic component usually signals.
Single-kanji vocabulary included; multi-kanji skipped.

Usage (Anki open with AnkiConnect):

  python3 scripts/patch_core_phonetic_hint_ankiconnect.py --from-cache
  python3 scripts/patch_core_phonetic_hint_ankiconnect.py --from-cache --templates-only
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_MODEL = "WK Core Item++"
ANKI_CONNECT_URL = "http://127.0.0.1:8765"
BATCH_SIZE = 50
KEISEI_PHONETIC = REPO_ROOT / ".wk_cache" / "keisei" / "phonetic_esc.json"
KEISEI_KANJI = REPO_ROOT / ".wk_cache" / "keisei" / "kanji_esc.json"
SUBJECTS_CACHE = REPO_ROOT / ".wk_cache" / "subjects_vocabulary_kanji_radical.json"


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
    candidates = [name for name in names if name.startswith("WK Core Item")]
    if not candidates:
        raise SystemExit("No WK Core Item note type found in Anki.")
    return max(candidates, key=len)


def load_json(path: Path) -> object:
    if not path.is_file():
        raise SystemExit(f"Missing cache file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_subjects_by_id() -> Dict[int, dict]:
    payload = load_json(SUBJECTS_CACHE)
    items = payload.get("items") if isinstance(payload, dict) else payload
    by_id: Dict[int, dict] = {}
    for subject in items or []:
        if not isinstance(subject, dict) or "id" not in subject:
            continue
        by_id[int(subject["id"])] = subject
    return by_id


def ensure_phonetic_hint_field(model_name: str) -> None:
    fields = anki_connect("modelFieldNames", modelName=model_name)
    if "PhoneticHint" in fields:
        return
    # Insert after ReadingsDetail when present; else append.
    index = len(fields)
    if "ReadingsDetail" in fields:
        index = fields.index("ReadingsDetail") + 1
    anki_connect(
        "modelFieldAdd",
        modelName=model_name,
        fieldName="PhoneticHint",
        index=index,
    )
    print(f"Added PhoneticHint field to {model_name}")


def push_templates(model_name: str) -> None:
    from core_decks import make_core_item_model
    from wk_decks import MODEL_TEMPLATE_VERSIONS

    ensure_phonetic_hint_field(model_name)
    model = make_core_item_model()
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
        f"({MODEL_TEMPLATE_VERSIONS['core_item']})"
    )


def find_core_note_ids(model_name: str) -> List[int]:
    note_ids = anki_connect(
        "findNotes",
        query=f'note:"{model_name}" (deck:"WaniKani Core · Kanji" OR deck:"WaniKani Core · Vocabulary")',
    )
    if not note_ids:
        note_ids = anki_connect("findNotes", query=f'note:"{model_name}" tag:wk-core')
    return [int(note_id) for note_id in note_ids]


def patch_note_fields(model_name: str) -> None:
    from wk_decks import core_phonetic_hint_html

    ensure_phonetic_hint_field(model_name)
    keisei_phonetic = load_json(KEISEI_PHONETIC)
    keisei_kanji = load_json(KEISEI_KANJI)
    subject_by_id = load_subjects_by_id()
    note_ids = find_core_note_ids(model_name)
    print(f"Found {len(note_ids)} core notes")

    updated = 0
    unchanged = 0
    skipped = 0
    for start in range(0, len(note_ids), BATCH_SIZE):
        chunk = note_ids[start : start + BATCH_SIZE]
        for info in anki_connect("notesInfo", notes=chunk):
            fields = info["fields"]
            subject_id_text = fields.get("WkSubjectId", {}).get("value", "").strip()
            try:
                subject_id = int(subject_id_text)
            except ValueError:
                skipped += 1
                continue
            subject = subject_by_id.get(subject_id)
            if subject is None:
                skipped += 1
                continue
            hint = core_phonetic_hint_html(
                subject,
                keisei_kanji=keisei_kanji,
                keisei_phonetic=keisei_phonetic,
                subject_by_id=subject_by_id,
            )
            current = fields.get("PhoneticHint", {}).get("value", "")
            if current == hint:
                unchanged += 1
                continue
            anki_connect(
                "updateNoteFields",
                note={
                    "id": info["noteId"],
                    "fields": {"PhoneticHint": hint},
                },
            )
            updated += 1

    print(
        f"Patched PhoneticHint on {updated} notes "
        f"({unchanged} already current, {skipped} skipped)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="Required: use .wk_cache Keisei + subjects files.",
    )
    parser.add_argument(
        "--templates-only",
        action="store_true",
        help="Only push templates/CSS (and ensure PhoneticHint field).",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Note type name (default: {DEFAULT_MODEL})",
    )
    args = parser.parse_args()
    if not args.from_cache:
        raise SystemExit("Pass --from-cache (Keisei/subjects are read from .wk_cache).")

    model_name = resolve_model_name(args.model)
    print(f"Using note type: {model_name}")
    push_templates(model_name)
    if args.templates_only:
        return
    patch_note_fields(model_name)


if __name__ == "__main__":
    main()
