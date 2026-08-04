"""
Upgrade Yomitan/Migaku immersion note types in-place for cloze + shadow templates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Sequence

from .logic import FIELD_SENTENCE_AUDIO, FIELD_SENTENCE_AUDIO_EASY
from .mining_note_types import MINING_NOTE_TYPES, MINING_TEMPLATE_UPGRADE_NOTE_TYPES

if TYPE_CHECKING:
    from anki.collection import Collection

MINING_CLOZE_TEMPLATE_MARKER = "cloze-sentence"
MINING_SHADOW_TEMPLATE_MARKER = "shadow-card"
MINING_LEGACY_TEMPLATE_MARKER = "word-block"

MINING_FIELDS_TO_ENSURE: Sequence[str] = (
    "Translation",
    "Image",
    "ClozeSentence",
    "WkSubjectId",
    "PrerequisiteIds",
    "WkMeaning",
    "HintGlossary",
    "HintStage",
    "ShowEnglish",
    "ShowKana",
    "ShowJjBack",
    "SentenceKana",
    "DictLinksJa",
    "DictLinksEn",
)


def _ensure_fields(col: "Collection", model, field_names: Sequence[str]) -> bool:
    changed = False
    existing = {field["name"] for field in model["flds"]}
    for name in field_names:
        if name in existing:
            continue
        col.models.add_field(model, col.models.new_field(name))
        changed = True
    return changed


def _ensure_templates(model) -> bool:
    from .mining_templates import (
        MINING_BACK,
        MINING_FRONT,
        MINING_SHADOW_BACK,
        MINING_SHADOW_FRONT,
    )

    changed = False
    has_cloze = False
    has_shadow = False
    for template in model["tmpls"]:
        front = template.get("qfmt") or ""
        if MINING_SHADOW_TEMPLATE_MARKER in front:
            has_shadow = True
            continue
        if MINING_CLOZE_TEMPLATE_MARKER not in front:
            template["name"] = "Sentence cloze → word"
            template["qfmt"] = MINING_FRONT
            template["afmt"] = MINING_BACK
            changed = True
        has_cloze = True

    if not has_cloze and model["tmpls"]:
        template = model["tmpls"][0]
        template["name"] = "Sentence cloze → word"
        template["qfmt"] = MINING_FRONT
        template["afmt"] = MINING_BACK
        changed = True
        has_cloze = True

    if has_cloze and not has_shadow:
        # Anki model template dict — add via collection API when available.
        new_template = {
            "name": "Shadow → pitch",
            "qfmt": MINING_SHADOW_FRONT,
            "afmt": MINING_SHADOW_BACK,
        }
        model["tmpls"].append(new_template)
        changed = True
    return changed


def ensure_immersion_model(col: "Collection") -> bool:
    """
    Add mining cloze fields and upgrade templates when outdated.
    Returns True if any mining note type was modified.
    """
    any_changed = False
    for note_type_name in sorted(MINING_NOTE_TYPES):
        model = col.models.by_name(note_type_name)
        if model is None:
            continue

        changed = _ensure_fields(col, model, MINING_FIELDS_TO_ENSURE)
        field_names = [field["name"] for field in model["flds"]]
        if FIELD_SENTENCE_AUDIO not in field_names:
            col.models.add_field(model, col.models.new_field(FIELD_SENTENCE_AUDIO))
            changed = True
        if FIELD_SENTENCE_AUDIO_EASY not in field_names:
            col.models.add_field(model, col.models.new_field(FIELD_SENTENCE_AUDIO_EASY))
            changed = True
        for extra in (
            "Synonyms",
            "Antonyms",
            "PitchAccents",
            "PitchPositions",
            "PitchGraphs",
            "SentencePitchGraphs",
        ):
            if extra not in field_names:
                col.models.add_field(model, col.models.new_field(extra))
                changed = True

        # Satori keeps its own back (sentence EN + no shadow card).
        if note_type_name in MINING_TEMPLATE_UPGRADE_NOTE_TYPES and _ensure_templates(model):
            changed = True

        if changed:
            col.models.save(model)
            any_changed = True
    return any_changed
