"""
Upgrade WK Migaku Immersion note type in-place for mining cloze template.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Sequence

from .logic import FIELD_SENTENCE_AUDIO, MINING_NOTE_TYPE

if TYPE_CHECKING:
    from anki.collection import Collection

MINING_CLOZE_TEMPLATE_MARKER = "cloze-sentence"
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


def ensure_immersion_model(col: "Collection") -> bool:
    """
    Add mining cloze fields and upgrade templates when outdated.
    Returns True if the note type was modified.
    """
    model = col.models.by_name(MINING_NOTE_TYPE)
    if model is None:
        return False

    changed = _ensure_fields(col, model, MINING_FIELDS_TO_ENSURE)
    field_names = [field["name"] for field in model["flds"]]
    if FIELD_SENTENCE_AUDIO not in field_names:
        col.models.add_field(model, col.models.new_field(FIELD_SENTENCE_AUDIO))
        changed = True
    for extra in ("Synonyms", "Antonyms"):
        if extra not in field_names:
            col.models.add_field(model, col.models.new_field(extra))
            changed = True

    for template in model["tmpls"]:
        front = template.get("qfmt") or ""
        if MINING_CLOZE_TEMPLATE_MARKER not in front:
            from .mining_templates import MINING_BACK, MINING_FRONT

            template["name"] = "Sentence cloze → word"
            template["qfmt"] = MINING_FRONT
            template["afmt"] = MINING_BACK
            changed = True

    if changed:
        col.models.save(model)
    return changed
