"""
kanji_meaning_decks.py

Kanji Meaning Anchor: a lightweight kanji -> English meaning recall deck, decoupled
from reading production. No import-time unlock gating — study freely. Vocab
supplementary decks (dictation, vocab cloze) unlock when their kanji components
are Guru+ here.

Front: kanji character only (no reading, no vocabulary context).
Back: primary WK meaning(s).
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import genanki

from wk_decks import (
    COMMON_CSS,
    DECK_IDS,
    DECK_NAMES,
    MODEL_IDS,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WK_SRS_STAGE_GURU_1,
    WkModel,
    primary_meanings,
    srs_stage,
    stable_guid,
    versioned_css,
    write_apkg,
)

KANJI_MEANING_KIND = "kanji-meaning"

# Build-time inclusion filter only (relevant when --no-wk-progress-filter is off).
# Guru I so the anchor surfaces earlier than the Master-level dictation/vocab-cloze
# defaults -- it is meant to run alongside/before full reading mastery, not after it.
KANJI_MEANING_DEFAULT_MIN_SRS = WK_SRS_STAGE_GURU_1

KANJI_MEANING_DECK_ID = DECK_IDS["kanji-meaning"]
KANJI_MEANING_MODEL_ID = MODEL_IDS["kanji_meaning"]
KANJI_MEANING_DECK_NAME = DECK_NAMES["kanji-meaning"]
KANJI_MEANING_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["kanji_meaning"]
KANJI_MEANING_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["kanji_meaning"]
KANJI_MEANING_MODEL_TEMPLATE_KEY = "kanji_meaning"

KANJI_MEANING_CSS = """
.kanji-meaning-jp { font-size: 76px; margin: 32px 0 8px; }
"""


class KanjiMeaningItem(NamedTuple):
    kanji: dict
    expression: str
    meaning: str


def collect_kanji_meaning_items(
    kanji_items: Sequence[dict],
    assignment_index: Dict[int, dict],
    *,
    min_srs: int = 0,
) -> List[KanjiMeaningItem]:
    items: List[KanjiMeaningItem] = []
    for kanji in sorted(
        kanji_items,
        key=lambda item: (item["data"].get("level", 999), item["data"].get("characters") or ""),
    ):
        if srs_stage(kanji, assignment_index) < min_srs:
            continue
        expr = str(kanji["data"].get("characters") or "").strip()
        meanings = primary_meanings(kanji)
        if not expr or not meanings:
            continue
        items.append(
            KanjiMeaningItem(
                kanji=kanji,
                expression=expr,
                meaning="; ".join(meanings),
            )
        )
    return items


def make_kanji_meaning_model() -> WkModel:
    return WkModel(
        KANJI_MEANING_MODEL_ID,
        KANJI_MEANING_NOTE_TYPE_NAME,
        template_key=KANJI_MEANING_MODEL_TEMPLATE_KEY,
        fields=[
            {"name": "GuidKey"},
            {"name": "WkSubjectId"},
            {"name": "Expression"},
            {"name": "Meaning"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Kanji Meaning",
                "qfmt": """
                <div class="prompt">Meaning?</div>
                <div class="kanji-meaning-jp">{{Expression}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="meaning answer">{{Meaning}}</div>
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS + KANJI_MEANING_CSS,
            KANJI_MEANING_MODEL_TEMPLATE_KEY,
        ),
    )


def build_kanji_meaning_deck(
    items: Sequence[KanjiMeaningItem],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    interval_map: Optional[Dict[int, int]] = None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(KANJI_MEANING_DECK_ID, KANJI_MEANING_DECK_NAME)
    model = make_kanji_meaning_model()
    template_label = KANJI_MEANING_TEMPLATE_VERSION

    for item in items:
        kanji = item.kanji
        data = kanji["data"]
        level = data.get("level", "?")
        srs = srs_stage(kanji, assignment_index)
        guid = stable_guid(KANJI_MEANING_KIND, kanji["id"])
        meta = f"WK L{level} · SRS {srs} · template {template_label}"

        note_tags = [
            "wanikani",
            "kanji-meaning",
            "kanji",
            f"wk-level-{level}",
        ]
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                str(kanji["id"]),
                html.escape(item.expression),
                html.escape(item.meaning),
                html.escape(meta),
            ],
            tags=note_tags,
            guid=guid,
        )
        deck.add_note(note)

    out = output_dir / "wk_kanji_meaning.apkg"
    write_apkg(deck, out)
    return out, deck
