"""
mining_decks.py

Yomitan mining deck + note type for live sentence/term mining via AnkiConnect.

Includes one suspended placeholder card so Anki imports the deck and note type
(zero-card decks are skipped on import).
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Tuple

import genanki

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

MINING_DECK_ID = 2059400132
MINING_MODEL_ID = 1865429028
MINING_DECK_NAME = DECK_NAMES["mining"]
MINING_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["mining"]
MINING_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["mining"]
MINING_MODEL_TEMPLATE_KEY = "mining"
MINING_TAG = "yomitan-mining"
MINING_SETUP_TAG = "mining-setup"
MINING_SETUP_KIND = "mining-setup"
MINING_SETUP_DUPLICATE_KEY = "wk-yomitan-mining-setup"
# Anki built-in TTS — reads Sentence field (whole phrase); uses system ja_JP voice.
MINING_SENTENCE_TTS = "{{tts ja_JP:Sentence}}"


def make_mining_model() -> WkModel:
    return WkModel(
        MINING_MODEL_ID,
        MINING_NOTE_TYPE_NAME,
        template_key=MINING_MODEL_TEMPLATE_KEY,
        fields=[
            {"name": "DuplicateKey"},
            {"name": "Expression"},
            {"name": "Reading"},
            {"name": "Glossary"},
            {"name": "Sentence"},
            {"name": "ClozePrefix"},
            {"name": "ClozeBody"},
            {"name": "ClozeSuffix"},
            {"name": "TypeExpression"},
            {"name": "SentenceFurigana"},
            {"name": "Audio"},
            {"name": "SourceUrl"},
            {"name": "SourceTitle"},
            {"name": "WkSubjectId"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Sentence cloze",
                "qfmt": """
                {{#Sentence}}
                <div class="prompt">Type the missing word</div>
                <div class="jp context">{{ClozePrefix}}<span class="cloze-blank">＿＿＿</span>{{ClozeSuffix}}</div>
                <div class="type-answer">{{type:TypeExpression}}</div>
                {{/Sentence}}
                {{^Sentence}}
                <div class="prompt">Reading and meaning?</div>
                <div class="jp">{{Expression}}</div>
                {{/Sentence}}
                <div class="meta">{{Meta}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="jp answer">{{Expression}}</div>
                <div class="reading answer">{{Reading}}</div>
                <div class="meaning answer">{{Glossary}}</div>
                {{#Sentence}}
                <div class="context">
                  <div class="sentence-tts">"""
                + MINING_SENTENCE_TTS
                + """</div>
                  <div class="jp">{{Sentence}}</div>
                  {{#SentenceFurigana}}<div class="reading">{{SentenceFurigana}}</div>{{/SentenceFurigana}}
                </div>
                {{/Sentence}}
                {{#Audio}}<div class="sentence-audio">{{Audio}}</div>{{/Audio}}
                {{#SourceTitle}}<div class="source">{{SourceTitle}}</div>{{/SourceTitle}}
                {{#SourceUrl}}<div class="source"><a href="{{SourceUrl}}">{{SourceUrl}}</a></div>{{/SourceUrl}}
                {{#WkSubjectId}}<div class="meta">WK subject {{WkSubjectId}}</div>{{/WkSubjectId}}
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.context { font-size: 28px; margin: 12px auto; max-width: 760px; line-height: 1.6; }
.cloze-blank { color: #9ecfff; letter-spacing: 0.08em; }
.type-answer { margin-top: 12px; }
.source { font-size: 13px; color: #aaa; margin-top: 8px; word-break: break-all; }
.sentence-tts { margin: 8px 0; }
""",
            MINING_MODEL_TEMPLATE_KEY,
        ),
    )


def _mining_setup_note(model: WkModel) -> genanki.Note:
    guid = stable_guid(MINING_SETUP_KIND, 1)
    meta = f"placeholder · template {MINING_TEMPLATE_VERSION} · delete after first Yomitan mine"
    glossary = (
        "Placeholder so Anki imports this deck and note type. "
        "Mine a word from Yomitan, then delete this suspended card in Browse."
    )
    return genanki.Note(
        model=model,
        fields=[
            MINING_SETUP_DUPLICATE_KEY,
            "（セットアップ）",
            "",
            html.escape(glossary),
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            html.escape(meta),
        ],
        tags=[MINING_TAG, MINING_SETUP_TAG],
        guid=guid,
    )


def build_mining_deck(output_dir: Path) -> Tuple[Path, genanki.Deck]:
    """Export mining deck with a suspended setup card (Anki skips zero-card decks)."""
    deck = genanki.Deck(MINING_DECK_ID, MINING_DECK_NAME)
    model = make_mining_model()
    deck.add_model(model)
    deck.add_note(_mining_setup_note(model))
    out = output_dir / "wk_mining.apkg"
    write_apkg(deck, out)
    patch_apkg_suspend_notes_with_tag(out, MINING_SETUP_TAG)
    return out, deck
