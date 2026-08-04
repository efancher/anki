"""
mining_decks.py

Yomitan immersion deck + note type for sentence mining via AnkiConnect.

Cards:
  1. Sentence cloze → type reading (progressive WK hints)
  2. Shadow → pitch (listen / speak; pitch on back)

Includes one suspended placeholder card so Anki imports the deck and note type.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import genanki
import importlib.util

from wk_decks import (
    COMMON_CSS,
    DECK_NAMES,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WkModel,
    stable_guid,
    versioned_css,
    write_apkg,
)
from wk_scheduling import patch_apkg_suspend_notes_with_tag

# Load templates without importing anki_addon.wk_immersion (needs Anki runtime).
_TEMPLATES_PATH = (
    Path(__file__).resolve().parent / "anki_addon" / "wk_immersion" / "mining_templates.py"
)
_SPEC = importlib.util.spec_from_file_location("wk_mining_templates", _TEMPLATES_PATH)
assert _SPEC and _SPEC.loader
_TEMPLATES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_TEMPLATES)
MINING_BACK = _TEMPLATES.MINING_BACK
MINING_CSS_EXTRA = _TEMPLATES.MINING_CSS_EXTRA
MINING_FRONT = _TEMPLATES.MINING_FRONT
MINING_SENTENCE_TTS = _TEMPLATES.MINING_SENTENCE_TTS
MINING_SHADOW_BACK = _TEMPLATES.MINING_SHADOW_BACK
MINING_SHADOW_FRONT = _TEMPLATES.MINING_SHADOW_FRONT

MINING_DECK_ID = 2059400132
MINING_MODEL_ID = 1865429029
MINING_DECK_NAME = DECK_NAMES["mining"]
MINING_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["mining"]
MINING_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["mining"]
MINING_MODEL_TEMPLATE_KEY = "mining"
MINING_TAG = "yomitan-mining"
MINING_SETUP_TAG = "mining-setup"
MINING_SETUP_KIND = "mining-setup"
MINING_SETUP_DUPLICATE_KEY = "wk-yomitan-mining-setup"
MINING_EXPORT_FILENAME = "wk_mining.apkg"

MINING_FIELD_NAMES: Tuple[str, ...] = (
    "DuplicateKey",
    "Expression",
    "Reading",
    "Translation",
    "Furigana",
    "PitchAccents",
    "PitchPositions",
    "PitchGraphs",
    "SentencePitchGraphs",
    "Glossary",
    "Synonyms",
    "Antonyms",
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
    "Sentence",
    "SentenceFurigana",
    "Audio",
    "SentenceAudio",
    "VoicevoxAudio",
    "VoicevoxSpeakerId",
    "UserNotes",
    "SourceUrl",
    "SourceTitle",
    "Meta",
)


def make_mining_model() -> WkModel:
    return WkModel(
        MINING_MODEL_ID,
        MINING_NOTE_TYPE_NAME,
        template_key=MINING_MODEL_TEMPLATE_KEY,
        fields=[{"name": name} for name in MINING_FIELD_NAMES],
        templates=[
            {
                "name": "Sentence cloze → word",
                "qfmt": MINING_FRONT,
                "afmt": MINING_BACK,
            },
            {
                "name": "Shadow → pitch",
                "qfmt": MINING_SHADOW_FRONT,
                "afmt": MINING_SHADOW_BACK,
            },
        ],
        css=versioned_css(COMMON_CSS + MINING_CSS_EXTRA, MINING_MODEL_TEMPLATE_KEY),
    )


def _empty_mining_fields() -> List[str]:
    return [""] * len(MINING_FIELD_NAMES)


def _field_index(name: str) -> int:
    return MINING_FIELD_NAMES.index(name)


def _mining_setup_note(model: WkModel) -> genanki.Note:
    guid = stable_guid(MINING_SETUP_KIND, 1)
    meta = f"placeholder · template {MINING_TEMPLATE_VERSION} · delete after first Yomitan mine"
    fields = _empty_mining_fields()
    fields[_field_index("DuplicateKey")] = MINING_SETUP_DUPLICATE_KEY
    fields[_field_index("Expression")] = "（セットアップ）"
    fields[_field_index("ClozeSentence")] = html.escape(
        "（セットアップ — Yomitan で単語を追加してください）"
    )
    fields[_field_index("Glossary")] = html.escape(
        "Placeholder so Anki imports this deck and note type. "
        "Mine from Yomitan with Anki open, then delete this suspended card in Browse."
    )
    fields[_field_index("Meta")] = html.escape(meta)
    return genanki.Note(
        model=model,
        fields=fields,
        tags=[MINING_TAG, MINING_SETUP_TAG],
        guid=guid,
    )


def build_mining_deck(
    output_dir: Path,
    *,
    vocab_items: Optional[Sequence[dict]] = None,
) -> Tuple[Path, genanki.Deck]:
    """Export mining deck with a suspended setup card (Anki skips zero-card decks)."""
    if vocab_items:
        from mining_vocab_index import write_mining_vocab_index

        index_path = write_mining_vocab_index(vocab_items, output_dir)
        print(f"Mining vocab index: {index_path} ({len(vocab_items)} vocab subjects)")
    deck = genanki.Deck(MINING_DECK_ID, MINING_DECK_NAME)
    model = make_mining_model()
    deck.add_model(model)
    deck.add_note(_mining_setup_note(model))
    out = output_dir / MINING_EXPORT_FILENAME
    write_apkg(deck, out)
    patch_apkg_suspend_notes_with_tag(out, MINING_SETUP_TAG)
    return out, deck
