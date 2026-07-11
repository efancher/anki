"""
Configure Migaku Anki add-on field maps for WK Migaku Immersion.

Migaku stores mappings in its add-on config (migakuFields), keyed by note type id.
Each Anki field maps to a Migaku CardFields attribute (targetWord, sentence, …).
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

MINING_DECK_NAME = "Immersion · Migaku Mining"
MINING_NOTE_TYPE = "WK Migaku Immersion"

# Migaku CardFields attribute names — see Migaku-Anki-Addon src/card_types.py
MIGAKU_TYPE_BY_FIELD: Dict[str, str] = {
    "DuplicateKey": "none",
    "Expression": "targetWordNoSyntax",
    "Reading": "reading",
    "Translation": "translation",
    "Furigana": "none",
    "PitchAccents": "none",
    "PitchPositions": "none",
    "PitchGraphs": "none",
    "Glossary": "definitions",
    "Synonyms": "none",
    "Antonyms": "none",
    "Image": "firstImage",
    "ClozeSentence": "none",
    "WkSubjectId": "none",
    "PrerequisiteIds": "none",
    "WkMeaning": "none",
    "HintGlossary": "none",
    "HintStage": "none",
    "ShowEnglish": "none",
    "ShowKana": "none",
    "ShowJjBack": "none",
    "SentenceKana": "none",
    "DictLinksJa": "none",
    "DictLinksEn": "none",
    "Sentence": "sentenceNoSyntax",
    "SentenceFurigana": "none",
    "Audio": "wordAudio",
    "SentenceAudio": "sentenceAudio",
    "VoicevoxAudio": "none",
    "VoicevoxSpeakerId": "none",
    "UserNotes": "notes",
    "SourceUrl": "none",
    "SourceTitle": "none",
    "Meta": "none",
}


def build_field_map(field_names: Sequence[str]) -> Dict[str, str]:
    return {name: MIGAKU_TYPE_BY_FIELD.get(name, "none") for name in field_names}


def find_migaku_addon_id(addon_manager) -> Optional[str]:
    for addon_id in addon_manager.allAddons():
        meta = addon_manager.addonMeta(addon_id)
        name = (meta.get("name") or "").lower()
        if "migaku" in name and "anki" in name:
            return addon_id
    return None


def note_types_to_configure(col) -> List[str]:
    names = [MINING_NOTE_TYPE]
    plus_name = f"{MINING_NOTE_TYPE}+"
    if col.models.by_name(plus_name):
        names.append(plus_name)
    return names


def configure_migaku_field_map(col, addon_manager) -> str:
    """Write Migaku migakuFields + default deck/note type. Returns summary message."""
    migaku_addon_id = find_migaku_addon_id(addon_manager)
    if not migaku_addon_id:
        raise RuntimeError(
            "Migaku Anki add-on not found. Install it from AnkiWeb, then restart Anki."
        )

    deck = col.decks.by_name(MINING_DECK_NAME)
    if deck is None:
        raise RuntimeError(
            f'Deck {MINING_DECK_NAME!r} not found. Import out/wk_migaku.apkg first.'
        )

    primary = col.models.by_name(MINING_NOTE_TYPE)
    if primary is None:
        raise RuntimeError(
            f'Note type {MINING_NOTE_TYPE!r} not found. Import out/wk_migaku.apkg first.'
        )

    config = addon_manager.getConfig(migaku_addon_id) or {}
    migaku_fields: Dict[str, Dict[str, str]] = dict(config.get("migakuFields") or {})
    configured: List[str] = []

    for note_type_name in note_types_to_configure(col):
        model = col.models.by_name(note_type_name)
        if model is None:
            continue
        field_names = [field["name"] for field in model["flds"]]
        migaku_fields[str(model["id"])] = build_field_map(field_names)
        configured.append(note_type_name)

    config["migakuFields"] = migaku_fields
    config["migakuNotetypeId"] = int(primary["id"])
    config["migakuDeckId"] = int(deck["id"])
    addon_manager.writeConfig(migaku_addon_id, config)

    lines = [
        "Migaku field map configured:",
        f"  Deck: {MINING_DECK_NAME}",
        f"  Primary note type: {MINING_NOTE_TYPE} (id {primary['id']})",
        f"  Mapped note types: {', '.join(configured)}",
        "",
        "Key mappings:",
        "  Expression → Target Word (no syntax)",
        "  Reading → Reading",
        "  Sentence → Sentence (no syntax)",
        "  Translation → Sentence Translation",
        "  Glossary → Definitions",
        "  Image → First Image",
        "  SentenceAudio → Sentence Audio",
        "  Audio → Word Audio",
        "",
        "Restart Anki if Migaku still shows old maps, then mine a test card.",
    ]
    return "\n".join(lines)
