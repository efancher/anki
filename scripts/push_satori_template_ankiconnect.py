#!/usr/bin/env python3
"""Push WK Satori Immersion card templates + CSS via AnkiConnect.

Use this instead of re-importing out/wk_satori.apkg when notes already exist.
Anki skips duplicate notes on import; enabling "Update existing notes" would also
blank SentenceAudio / SentenceAudioEasy (the .apkg ships those fields empty).

Usage (Anki open with AnkiConnect):

  python3 scripts/push_satori_template_ankiconnect.py
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

from satori_decks import (  # noqa: E402
    SATORI_NOTE_TYPE_NAME,
    SATORI_TEMPLATE_VERSION,
    build_satori_cloze_sentence,
    make_satori_model,
)

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {base_url}. "
            f"Is Anki open with AnkiConnect installed?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def ensure_audio_fields(base_url: str, model_name: str) -> None:
    fields = list(anki_connect(base_url, "modelFieldNames", modelName=model_name))
    for name in ("SentenceAudio", "SentenceAudioEasy"):
        if name in fields:
            continue
        anki_connect(
            base_url,
            "modelFieldAdd",
            modelName=model_name,
            fieldName=name,
            index=len(fields),
        )
        fields.append(name)
        print(f"  added field {name}")


def refresh_cloze_fields(base_url: str, model_name: str) -> int:
    """Recompute ClozeSentence for every note from its stored Sentence/Expression.

    Needed because ClozeSentence is a stored field: template pushes alone do not
    change it, and re-importing the .apkg skips existing notes.
    """
    note_ids = list(anki_connect(base_url, "findNotes", query=f'note:"{model_name}"'))
    if not note_ids:
        return 0
    infos = anki_connect(base_url, "notesInfo", notes=note_ids)
    updated = 0
    for info in infos:
        fields = info.get("fields") or {}

        def value(name: str) -> str:
            return (fields.get(name) or {}).get("value") or ""

        sentence = value("Sentence")
        expression = value("Expression")
        reading = value("Reading")
        if not sentence or not expression:
            continue
        cloze_html, _ = build_satori_cloze_sentence(sentence, expression, reading)
        if not cloze_html or cloze_html == value("ClozeSentence"):
            continue
        anki_connect(
            base_url,
            "updateNoteFields",
            note={"id": info["noteId"], "fields": {"ClozeSentence": cloze_html}},
        )
        updated += 1
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument("--model", default=SATORI_NOTE_TYPE_NAME)
    parser.add_argument(
        "--no-refresh-cloze",
        action="store_true",
        help="Only push template/CSS; skip recomputing ClozeSentence on notes",
    )
    args = parser.parse_args(argv)

    models = set(anki_connect(args.anki_connect, "modelNames") or [])
    if args.model not in models:
        raise SystemExit(
            f"Note type {args.model!r} not found. "
            "Import out/wk_satori.apkg once first (Add)."
        )

    ensure_audio_fields(args.anki_connect, args.model)
    model = make_satori_model()
    tmpl = model.templates[0]
    anki_connect(
        args.anki_connect,
        "updateModelTemplates",
        model={
            "name": args.model,
            "templates": {
                tmpl["name"]: {"Front": tmpl["qfmt"], "Back": tmpl["afmt"]},
            },
        },
    )
    anki_connect(
        args.anki_connect,
        "updateModelStyling",
        model={"name": args.model, "css": model.css},
    )
    print(
        f"Updated {args.model} templates + CSS "
        f"(repo template {SATORI_TEMPLATE_VERSION}: highlight kanji, blank kana-only; "
        "Easy autoplay, Normal manual)."
    )
    if not args.no_refresh_cloze:
        updated = refresh_cloze_fields(args.anki_connect, args.model)
        print(f"Recomputed ClozeSentence on {updated} note(s).")
    print(
        "Then unwrap Normal audio if both speeds still autoplay:\n"
        '  python3 scripts/synthesize_immersion_sentence_audio.py '
        '--note-type "WK Satori Immersion"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
