#!/usr/bin/env python3
"""Patch conjugation BuildHtml onto live notes when .apkg field updates fail.

Adds BuildHtml + updates templates/CSS, then fills stacked conjugation explanations
from each note's dictionary/conjugated fields and tags.

Usage (Anki open with AnkiConnect):
  python3 scripts/patch_conjugation_build_ankiconnect.py
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import (  # noqa: E402
    I_ADJECTIVE_CONJUGATION_FORMS,
    NA_ADJECTIVE_CONJUGATION_FORMS,
    VERB_CONJUGATION_FORMS,
    conjugation_build_html,
    make_conjugation_model,
    make_conjugation_reverse_model,
)

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
DEFAULT_FORWARD = "WK Update-Safe Conjugation+++"
DEFAULT_REVERSE = "WK Update-Safe Conjugation Reverse++++"
BATCH_SIZE = 40

PROMPT_TO_FORM: Dict[str, str] = {}
for _forms in (VERB_CONJUGATION_FORMS, I_ADJECTIVE_CONJUGATION_FORMS, NA_ADJECTIVE_CONJUGATION_FORMS):
    for key, prompt in _forms:
        PROMPT_TO_FORM[prompt] = key

WORD_CLASS_FROM_LABEL = {
    "Godan verb": "godan",
    "Ichidan verb": "ichidan",
    "する verb": "suru_verb",
    "Irregular verb": "irregular_verb",
    "い-adjective": "i_adjective",
    "な-adjective": "na_adjective",
}
WORD_CLASS_TAGS = {
    "godan": "godan",
    "ichidan": "ichidan",
    "suru-verb": "suru_verb",
    "irregular-verb": "irregular_verb",
    "i-adjective": "i_adjective",
    "na-adjective": "na_adjective",
}
FORM_TAGS = {
    "polite_present",
    "polite_negative",
    "polite_past",
    "plain_negative",
    "plain_past",
    "te_form",
    "plain_past_negative",
    "polite",
}


def anki_connect(base_url: str, action: str, **params: object) -> object:
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


def note_field(note: dict, name: str) -> str:
    return note.get("fields", {}).get(name, {}).get("value", "")


def ensure_build_field(base_url: str, model_name: str) -> None:
    fields: List[str] = list(anki_connect(base_url, "modelFieldNames", modelName=model_name))
    if "BuildHtml" in fields:
        return
    index = fields.index("Meta") if "Meta" in fields else len(fields)
    anki_connect(
        base_url,
        "modelFieldAdd",
        modelName=model_name,
        fieldName="BuildHtml",
        index=index,
    )


def update_templates(base_url: str, model_name: str, maker) -> None:
    model = maker()
    tmpl = model.templates[0]
    anki_connect(
        base_url,
        "updateModelTemplates",
        model={
            "name": model_name,
            "templates": {tmpl["name"]: {"Front": tmpl["qfmt"], "Back": tmpl["afmt"]}},
        },
    )
    anki_connect(
        base_url,
        "updateModelStyling",
        model={"name": model_name, "css": model.css},
    )


def infer_word_class(note: dict, tags: Set[str]) -> Optional[str]:
    label = note_field(note, "WordClass")
    if label in WORD_CLASS_FROM_LABEL:
        return WORD_CLASS_FROM_LABEL[label]
    for tag, key in WORD_CLASS_TAGS.items():
        if tag in tags:
            return key
    return None


def infer_form_key(note: dict, tags: Set[str]) -> Optional[str]:
    for tag in tags:
        if tag in FORM_TAGS:
            return tag
    return PROMPT_TO_FORM.get(note_field(note, "Prompt"))


def patch_model(base_url: str, model_name: str, maker) -> Tuple[int, int]:
    print(f"== {model_name}")
    ensure_build_field(base_url, model_name)
    update_templates(base_url, model_name, maker)
    note_ids: List[int] = list(
        anki_connect(base_url, "findNotes", query=f'note:"{model_name}"') or []
    )
    updated = missing = 0
    for start in range(0, len(note_ids), BATCH_SIZE):
        batch = note_ids[start : start + BATCH_SIZE]
        notes = anki_connect(base_url, "notesInfo", notes=batch) or []
        actions: List[dict] = []
        for note in notes:
            tags = set(note.get("tags") or [])
            word_class = infer_word_class(note, tags)
            form_key = infer_form_key(note, tags)
            dict_expr = note_field(note, "DictExpression")
            dict_reading = note_field(note, "DictReading")
            conj_expr = note_field(note, "ConjExpression")
            conj_reading = note_field(note, "ConjReading")
            if not word_class or not form_key or not dict_expr or not conj_expr:
                missing += 1
                continue
            build = conjugation_build_html(
                word_class,
                form_key,
                dict_expr,
                dict_reading,
                conj_expr,
                conj_reading,
            )
            if note_field(note, "BuildHtml") == build:
                continue
            actions.append(
                {
                    "action": "updateNoteFields",
                    "params": {
                        "note": {
                            "id": note["noteId"],
                            "fields": {"BuildHtml": build},
                        }
                    },
                }
            )
        if actions:
            anki_connect(base_url, "multi", actions=actions)
            updated += len(actions)
        print(
            f"  {min(start + BATCH_SIZE, len(note_ids))}/{len(note_ids)} "
            f"updated={updated} missing={missing}"
        )
    return updated, missing


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument("--forward-model", default=DEFAULT_FORWARD)
    parser.add_argument("--reverse-model", default=DEFAULT_REVERSE)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    u1, m1 = patch_model(args.anki_connect, args.forward_model, make_conjugation_model)
    u2, m2 = patch_model(args.anki_connect, args.reverse_model, make_conjugation_reverse_model)
    print(f"Done. forward updated={u1} missing={m1}; reverse updated={u2} missing={m2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
