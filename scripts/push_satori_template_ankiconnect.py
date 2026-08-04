#!/usr/bin/env python3
"""Push WK Satori Immersion card templates + CSS via AnkiConnect.

Use this instead of re-importing out/wk_satori.apkg when notes already exist.
Anki skips duplicate notes on import; enabling "Update existing notes" would also
blank SentenceAudio / SentenceAudioEasy (the .apkg ships those fields empty).

Usage (Anki open with AnkiConnect):

  python3 scripts/push_satori_template_ankiconnect.py
  python3 scripts/push_satori_template_ankiconnect.py --backfill-meanings
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
    resolve_satori_word_meaning,
    should_skip_copula_cloze,
)
from shadowing_decks import (  # noqa: E402
    SHADOWING_CANDIDATE_NOTE_TYPE_NAME,
    SHADOWING_NOTE_TYPE_NAME,
    make_shadowing_candidate_model,
    make_shadowing_model,
)

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"

IMMERSION_DECK_NAMES = (
    "Immersion · Satori",
    "Immersion · Shadowing",
    "Immersion · Shadowing Candidates",
)
IMMERSION_AUDIO_CONFIG_NAME = "WK Immersion Audio"


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


def ensure_immersion_deck_audio_config(base_url: str) -> None:
    """Give immersion decks their own options group with autoplay off.

    Target/Reading/Normal use ``[sound:]`` so AnkiMobile can play them, but that
    would also autoplay under the shared WK FSRS group. Autoplay-off + template JS
    that clicks ``.autoplay-audio`` keeps sentence/Easy autoplay only.
    """
    existing_names = set(anki_connect(base_url, "deckNames") or [])
    present = [name for name in IMMERSION_DECK_NAMES if name in existing_names]
    if not present:
        return

    config_id = None
    for deck_name in present:
        cfg = anki_connect(base_url, "getDeckConfig", deck=deck_name)
        if isinstance(cfg, dict) and cfg.get("name") == IMMERSION_AUDIO_CONFIG_NAME:
            config_id = cfg.get("id")
            break

    if config_id is None:
        donor = anki_connect(base_url, "getDeckConfig", deck=present[0])
        if not isinstance(donor, dict) or donor.get("id") is None:
            raise SystemExit(f"Could not read deck config for {present[0]!r}")
        config_id = anki_connect(
            base_url,
            "cloneDeckConfigId",
            name=IMMERSION_AUDIO_CONFIG_NAME,
            cloneFrom=donor["id"],
        )

    anki_connect(base_url, "setDeckConfigId", decks=present, configId=config_id)
    cfg = anki_connect(base_url, "getDeckConfig", deck=present[0])
    if not isinstance(cfg, dict):
        raise SystemExit("getDeckConfig returned a non-object after assign")
    if cfg.get("autoplay") is not False or cfg.get("name") != IMMERSION_AUDIO_CONFIG_NAME:
        cfg["name"] = IMMERSION_AUDIO_CONFIG_NAME
        cfg["autoplay"] = False
        anki_connect(base_url, "saveDeckConfig", config=cfg)
    print(
        f"Immersion decks use {IMMERSION_AUDIO_CONFIG_NAME!r} "
        f"(autoplay off; template JS plays .autoplay-audio)."
    )


def wrap_bare_audio_fields(base_url: str, model_name: str) -> int:
    """Rewrite bare media filenames to ``[sound:]`` so AnkiMobile can play them."""
    fields_by_model = {
        SATORI_NOTE_TYPE_NAME: ("Audio", "ReadingAudio", "SentenceAudio"),
        SHADOWING_NOTE_TYPE_NAME: ("Audio", "ReadingAudio"),
        SHADOWING_CANDIDATE_NOTE_TYPE_NAME: ("Audio", "ReadingAudio"),
    }
    wanted = fields_by_model.get(model_name)
    if not wanted:
        return 0
    note_ids = list(anki_connect(base_url, "findNotes", query=f'note:"{model_name}"'))
    if not note_ids:
        return 0
    updated = 0
    # Batch in chunks to keep payloads reasonable
    chunk_size = 100
    for start in range(0, len(note_ids), chunk_size):
        chunk = note_ids[start : start + chunk_size]
        infos = anki_connect(base_url, "notesInfo", notes=chunk)
        for info in infos:
            fields = info.get("fields") or {}
            patch: dict[str, str] = {}
            for name in wanted:
                raw = ((fields.get(name) or {}).get("value") or "").strip()
                if not raw or (raw.startswith("[sound:") and raw.endswith("]")):
                    continue
                if "[" in raw or "]" in raw or " " in raw:
                    continue
                patch[name] = f"[sound:{raw}]"
            if not patch:
                continue
            anki_connect(
                base_url,
                "updateNoteFields",
                note={"id": info["noteId"], "fields": patch},
            )
            updated += 1
    return updated


def ensure_audio_fields(base_url: str, model_name: str) -> None:
    """Add media fields the templates expect but older Anki note types may lack."""
    fields = list(anki_connect(base_url, "modelFieldNames", modelName=model_name))
    if model_name == SATORI_NOTE_TYPE_NAME:
        wanted: tuple[str, ...] = (
            "SentenceAudio",
            "SentenceAudioEasy",
            "Audio",
            "ReadingAudio",
            "SentencePitchGraphs",
        )
    elif model_name == SHADOWING_NOTE_TYPE_NAME:
        wanted = ("Audio", "ReadingAudio", "SentencePitchGraphs")
    elif model_name == SHADOWING_CANDIDATE_NOTE_TYPE_NAME:
        wanted = ("Audio", "ReadingAudio", "SentencePitchGraphs")
    else:
        return
    for name in wanted:
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


def backfill_word_meanings(base_url: str, model_name: str) -> int:
    """Fill empty WkMeaning from curated Satori fallbacks (CSV English often blank)."""
    note_ids = list(anki_connect(base_url, "findNotes", query=f'note:"{model_name}"'))
    if not note_ids:
        return 0
    infos = anki_connect(base_url, "notesInfo", notes=note_ids)
    updated = 0
    for info in infos:
        fields = info.get("fields") or {}

        def value(name: str) -> str:
            return (fields.get(name) or {}).get("value") or ""

        if value("WkMeaning").strip():
            continue
        expression = value("Expression")
        meaning = resolve_satori_word_meaning(expression)
        if not meaning:
            continue
        anki_connect(
            base_url,
            "updateNoteFields",
            note={"id": info["noteId"], "fields": {"WkMeaning": meaning}},
        )
        updated += 1
        print(f"  WkMeaning ← {expression!r}: {meaning}")
    return updated


def delete_opaque_copula_notes(base_url: str, model_name: str) -> int:
    """Remove です/だ cloze notes that import now skips (opaque copula blanks)."""
    note_ids = list(anki_connect(base_url, "findNotes", query=f'note:"{model_name}"'))
    if not note_ids:
        return 0
    infos = anki_connect(base_url, "notesInfo", notes=note_ids)
    to_delete: list[int] = []
    for info in infos:
        fields = info.get("fields") or {}

        def value(name: str) -> str:
            return (fields.get(name) or {}).get("value") or ""

        expression = value("Expression")
        reading = value("Reading")
        sentence = value("Sentence")
        if should_skip_copula_cloze(expression, reading, sentence):
            to_delete.append(int(info["noteId"]))
            print(f"  delete opaque copula note {info['noteId']}: {expression!r}")
    if to_delete:
        anki_connect(base_url, "deleteNotes", notes=to_delete)
    return len(to_delete)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument("--model", default=SATORI_NOTE_TYPE_NAME)
    parser.add_argument(
        "--no-refresh-cloze",
        action="store_true",
        help="Only push template/CSS; skip recomputing ClozeSentence on notes",
    )
    parser.add_argument(
        "--cloze-only",
        action="store_true",
        help="Only recompute ClozeSentence (no template/CSS push). Use for Shadowing too.",
    )
    parser.add_argument(
        "--backfill-meanings",
        action="store_true",
        help="Fill empty WkMeaning from curated fallbacks; delete opaque です/だ notes.",
    )
    args = parser.parse_args(argv)

    models = set(anki_connect(args.anki_connect, "modelNames") or [])
    if args.model not in models:
        raise SystemExit(
            f"Note type {args.model!r} not found. "
            "Import the matching .apkg once first (Add)."
        )

    if not args.cloze_only:
        ensure_audio_fields(args.anki_connect, args.model)
        ensure_immersion_deck_audio_config(args.anki_connect)
        wrapped = wrap_bare_audio_fields(args.anki_connect, args.model)
        if wrapped:
            print(f"Wrapped bare audio filenames as [sound:] on {wrapped} note(s).")
        if args.model == SATORI_NOTE_TYPE_NAME:
            model = make_satori_model()
            version_label = SATORI_TEMPLATE_VERSION
        elif args.model == SHADOWING_NOTE_TYPE_NAME:
            from shadowing_decks import SHADOWING_TEMPLATE_VERSION

            model = make_shadowing_model()
            version_label = SHADOWING_TEMPLATE_VERSION
        elif args.model == SHADOWING_CANDIDATE_NOTE_TYPE_NAME:
            from shadowing_decks import SHADOWING_CANDIDATE_TEMPLATE_VERSION

            model = make_shadowing_candidate_model()
            version_label = SHADOWING_CANDIDATE_TEMPLATE_VERSION
        else:
            raise SystemExit(
                f"Unknown model {args.model!r}; use --cloze-only for cloze refresh only."
            )
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
            f"(repo template {version_label})."
        )
    if not args.no_refresh_cloze:
        updated = refresh_cloze_fields(args.anki_connect, args.model)
        print(f"Recomputed ClozeSentence on {updated} note(s) for {args.model}.")
    if args.backfill_meanings:
        if args.model != SATORI_NOTE_TYPE_NAME:
            raise SystemExit("--backfill-meanings only applies to WK Satori Immersion.")
        filled = backfill_word_meanings(args.anki_connect, args.model)
        deleted = delete_opaque_copula_notes(args.anki_connect, args.model)
        print(
            f"Backfilled WkMeaning on {filled} note(s); "
            f"deleted {deleted} opaque copula note(s)."
        )
    if not args.cloze_only:
        print(
            "Then synthesize Target (surface) + sentence audio:\n"
            '  python3 scripts/synthesize_immersion_sentence_audio.py '
            '--note-type "WK Satori Immersion"\n'
            "Or Target only:\n"
            '  python3 scripts/synthesize_immersion_sentence_audio.py '
            '--surface-only --note-type "WK Satori Immersion"'
        )
        print(
            "Refresh Shadowing clozes the same way:\n"
            '  python3 scripts/push_satori_template_ankiconnect.py '
            '--cloze-only --model "WK Shadowing Immersion"\n'
            '  python3 scripts/push_satori_template_ankiconnect.py '
            '--cloze-only --model "WK Shadowing Candidate"'
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
