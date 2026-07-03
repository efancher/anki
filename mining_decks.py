"""
mining_decks.py

Empty Yomitan mining deck + note type for live sentence/term mining via AnkiConnect.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import genanki

from wk_decks import (
    COMMON_CSS,
    DECK_NAMES,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WkModel,
    versioned_css,
    write_apkg,
)

MINING_DECK_ID = 2059400132
MINING_MODEL_ID = 1865429028
MINING_DECK_NAME = DECK_NAMES["mining"]
MINING_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["mining"]
MINING_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["mining"]
MINING_MODEL_TEMPLATE_KEY = "mining"
MINING_TAG = "yomitan-mining"


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
""",
            MINING_MODEL_TEMPLATE_KEY,
        ),
    )


def build_mining_deck(output_dir: Path) -> Tuple[Path, genanki.Deck]:
    """Export an empty mining deck so Yomitan can target the note type after import."""
    deck = genanki.Deck(MINING_DECK_ID, MINING_DECK_NAME)
    deck.add_model(make_mining_model())
    out = output_dir / "wk_mining.apkg"
    write_apkg(deck, out)
    return out, deck
