"""
kanji_meaning_decks.py

Kanji Meaning Anchor: a lightweight kanji -> English meaning recall deck, decoupled
from reading production. No import-time unlock gating — study freely. Vocab
supplementary decks (dictation, vocab cloze) unlock when their kanji components
are Guru+ here.

Front: kanji character only (no reading, no vocabulary context).
Back: primary WK meaning(s), small radical building blocks, meaning mnemonic.
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
    WK_MNEMONIC_CSS,
    WK_SRS_STAGE_GURU_1,
    WkModel,
    ensure_radical_media_files,
    kanji_radicals_front_html,
    meaning_mnemonic_html,
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
.kanji-meaning-radicals {
  margin: 16px auto 8px;
  max-width: 760px;
}
.kanji-meaning-radicals .radicals-front-piece {
  font-size: 22px;
  margin: 4px 10px;
}
.kanji-meaning-radicals .radicals-front-piece .jp { font-size: 28px; }
.kanji-meaning-radicals .radical-img {
  max-height: 36px;
  max-width: 36px;
  vertical-align: middle;
}
.kanji-meaning-radicals .radicals-front-meaning {
  font-size: 12px;
  color: #aaa;
  margin-top: 2px;
}
.kanji-meaning-mnemonic { margin-top: 16px; text-align: left; max-width: 640px; margin-left: auto; margin-right: auto; }
.kanji-meaning-mnemonic h3 { font-size: 15px; margin: 0 0 8px; color: #bbb; }
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
            {"name": "RadicalsHtml"},
            {"name": "MeaningMnemonic"},
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
                {{#RadicalsHtml}}
                <div class="kanji-meaning-radicals">{{RadicalsHtml}}</div>
                {{/RadicalsHtml}}
                {{#MeaningMnemonic}}
                <div class="kanji-meaning-mnemonic">
                  <h3>Meaning mnemonic</h3>
                  <div class="notes">{{MeaningMnemonic}}</div>
                </div>
                {{/MeaningMnemonic}}
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS + WK_MNEMONIC_CSS + KANJI_MEANING_CSS,
            KANJI_MEANING_MODEL_TEMPLATE_KEY,
        ),
    )


def build_kanji_meaning_deck(
    items: Sequence[KanjiMeaningItem],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    radical_index: Optional[Dict[int, dict]] = None,
    interval_map: Optional[Dict[int, int]] = None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(KANJI_MEANING_DECK_ID, KANJI_MEANING_DECK_NAME)
    model = make_kanji_meaning_model()
    template_label = KANJI_MEANING_TEMPLATE_VERSION
    radicals_by_id = radical_index or {}

    component_radicals = [
        radicals_by_id[component_id]
        for item in items
        for component_id in item.kanji["data"].get("component_subject_ids") or []
        if component_id in radicals_by_id
    ]
    media_names, media_paths = ensure_radical_media_files(component_radicals)
    deck.wk_media_files = media_paths

    for item in items:
        kanji = item.kanji
        data = kanji["data"]
        level = data.get("level", "?")
        srs = srs_stage(kanji, assignment_index)
        guid = stable_guid(KANJI_MEANING_KIND, kanji["id"])
        meta = f"WK L{level} · SRS {srs} · template {template_label}"
        radicals_html = (
            kanji_radicals_front_html(kanji, radicals_by_id, media_names) if radicals_by_id else ""
        )

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
                radicals_html,
                meaning_mnemonic_html(kanji),
                html.escape(meta),
            ],
            tags=note_tags,
            guid=guid,
        )
        deck.add_note(note)

    out = output_dir / "wk_kanji_meaning.apkg"
    write_apkg(deck, out)
    return out, deck
