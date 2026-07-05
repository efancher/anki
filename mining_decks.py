"""
mining_decks.py

Open Yomitan immersion deck + note type for live sentence/term mining via AnkiConnect.

Front: mined vocabulary (+ furigana or kana reading). Back: pitch, J–J definition + thesaurus
hooks (Glossary / Synonyms / Antonyms), sentence audio, UserNotes.

Audio on back: separate **Word** player (Yomitan `{audio}` clip or TTS) and **Sentence** player
(SentenceAudio / VOICEVOX, or TTS on Sentence).

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
MINING_MODEL_ID = 1865429029
MINING_DECK_NAME = DECK_NAMES["mining"]
MINING_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["mining"]
MINING_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["mining"]
MINING_MODEL_TEMPLATE_KEY = "mining"
MINING_TAG = "yomitan-mining"
MINING_SETUP_TAG = "mining-setup"
MINING_SETUP_KIND = "mining-setup"
MINING_SETUP_DUPLICATE_KEY = "wk-yomitan-mining-setup"
MINING_SENTENCE_TTS = "{{tts ja_JP:Sentence}}"

MINING_FRONT_WORD = """
<div class="word-block">
  {{#Furigana}}<div class="jp furigana">{{Furigana}}</div>{{/Furigana}}
  {{^Furigana}}<div class="jp">{{Expression}}</div>{{/Furigana}}
  {{#Reading}}<div class="reading front-reading">{{Reading}}</div>{{/Reading}}
</div>
"""

MINING_BACK_WORD = """
{{#Furigana}}<div class="jp answer">{{Furigana}}</div>{{/Furigana}}
{{^Furigana}}<div class="jp answer">{{Expression}}</div>{{/Furigana}}
{{#Reading}}<div class="reading answer">{{Reading}}</div>{{/Reading}}
{{#PitchAccents}}
<div class="pitch"><b>Pitch:</b> {{PitchAccents}}{{#PitchPositions}} <span class="pitch-pos">({{PitchPositions}})</span>{{/PitchPositions}}</div>
{{/PitchAccents}}
{{#PitchGraphs}}<div class="pitch-graphs">{{PitchGraphs}}</div>{{/PitchGraphs}}
"""

MINING_BACK_WORD_DEFS = """
{{#Glossary}}
<div class="word-def word-def-glossary">
  <div class="meta word-def-label">意味</div>
  <div class="word-def-body">{{Glossary}}</div>
</div>
{{/Glossary}}
{{#Synonyms}}
<div class="word-def word-def-synonyms">
  <div class="meta word-def-label">類</div>
  <div class="word-def-body">{{Synonyms}}</div>
</div>
{{/Synonyms}}
{{#Antonyms}}
<div class="word-def word-def-antonyms">
  <div class="meta word-def-label">対</div>
  <div class="word-def-body">{{Antonyms}}</div>
</div>
{{/Antonyms}}
"""

MINING_WORD_TTS_READING = "{{tts ja_JP:Reading}}"
MINING_WORD_TTS_EXPRESSION = "{{tts ja_JP:Expression}}"

MINING_BACK_WORD_AUDIO = (
    """
{{#Audio}}
<div class="word-audio-block">
  <div class="audio-label meta">Word</div>
  <div class="word-audio">{{Audio}}</div>
</div>
{{/Audio}}
{{^Audio}}
<div class="word-audio-block">
  <div class="audio-label meta">Word</div>
  {{#Reading}}<div class="word-tts">"""
    + MINING_WORD_TTS_READING
    + """</div>{{/Reading}}
  {{^Reading}}<div class="word-tts">"""
    + MINING_WORD_TTS_EXPRESSION
    + """</div>{{/Reading}}
</div>
{{/Audio}}
"""
)

MINING_BACK_SENTENCE_AUDIO = (
    """
  <div class="sentence-audio-block">
  <div class="audio-label meta">Sentence</div>
  {{#SentenceAudio}}<div class="sentence-audio sentence-tts-file">{{SentenceAudio}}</div>{{/SentenceAudio}}
  {{^SentenceAudio}}
  {{#VoicevoxAudio}}<div class="sentence-audio voicevox-audio">{{VoicevoxAudio}}</div>{{/VoicevoxAudio}}
  {{^VoicevoxAudio}}
  <div class="sentence-tts">"""
    + MINING_SENTENCE_TTS
    + """</div>
  {{/VoicevoxAudio}}
  {{/SentenceAudio}}
  </div>
"""
)

MINING_BACK_CONTEXT = (
    """
{{#Sentence}}
<div class="context">"""
    + MINING_BACK_SENTENCE_AUDIO
    + """
  {{#SentenceFurigana}}<div class="jp context-furigana">{{SentenceFurigana}}</div>{{/SentenceFurigana}}
  {{^SentenceFurigana}}<div class="jp">{{Sentence}}</div>{{/SentenceFurigana}}
</div>
{{/Sentence}}
"""
)


def make_mining_model() -> WkModel:
    return WkModel(
        MINING_MODEL_ID,
        MINING_NOTE_TYPE_NAME,
        template_key=MINING_MODEL_TEMPLATE_KEY,
        fields=[
            {"name": "DuplicateKey"},
            {"name": "Expression"},
            {"name": "Reading"},
            {"name": "Furigana"},
            {"name": "PitchAccents"},
            {"name": "PitchPositions"},
            {"name": "PitchGraphs"},
            {"name": "Glossary"},
            {"name": "Synonyms"},
            {"name": "Antonyms"},
            {"name": "Sentence"},
            {"name": "SentenceFurigana"},
            {"name": "Audio"},
            {"name": "SentenceAudio"},
            {"name": "VoicevoxAudio"},
            {"name": "VoicevoxSpeakerId"},
            {"name": "UserNotes"},
            {"name": "SourceUrl"},
            {"name": "SourceTitle"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Word → sentence",
                "qfmt": MINING_FRONT_WORD,
                "afmt": """
                {{FrontSide}}
                <hr>
                """
                + MINING_BACK_WORD
                + MINING_BACK_WORD_DEFS
                + MINING_BACK_WORD_AUDIO
                + """
                {{#UserNotes}}
                <div class="user-notes">
                  <div class="meta user-notes-label">Your notes</div>
                  <div class="user-notes-body">{{UserNotes}}</div>
                </div>
                {{/UserNotes}}
                """
                + MINING_BACK_CONTEXT
                + """
                {{#SourceTitle}}<div class="source">{{SourceTitle}}</div>{{/SourceTitle}}
                {{#SourceUrl}}<div class="source"><a href="{{SourceUrl}}">{{SourceUrl}}</a></div>{{/SourceUrl}}
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.word-block { margin: 8px auto; max-width: 760px; }
.furigana ruby { font-size: 42px; }
.furigana rt { font-size: 22px; color: #d8d8d8; }
.front-reading { font-size: 30px; margin-top: 8px; }
.context { font-size: 28px; margin: 12px auto; max-width: 760px; line-height: 1.6; }
.context-furigana { line-height: 1.8; }
.context-furigana ruby { font-size: 28px; }
.context-furigana rt { font-size: 16px; color: #d8d8d8; }
.pitch { font-size: 18px; margin: 10px auto; max-width: 760px; }
.pitch-pos { color: #aaa; font-size: 15px; }
.pitch-graphs { margin: 8px auto; max-width: 760px; }
.word-def {
  text-align: left;
  margin: 12px auto;
  max-width: 760px;
  padding: 10px 12px;
  border-left: 3px solid #5a7a5a;
  background: rgba(90, 122, 90, 0.08);
  font-size: 18px;
  line-height: 1.55;
}
.word-def-label { margin-bottom: 6px; letter-spacing: 0.06em; }
.word-def-synonyms { border-left-color: #6a7a9a; background: rgba(106, 122, 154, 0.08); }
.word-def-antonyms { border-left-color: #9a6a7a; background: rgba(154, 106, 122, 0.08); }
.nightMode .word-def,
.card.nightMode .word-def,
.night_mode .word-def {
  background: rgba(255, 255, 255, 0.06);
}
.source { font-size: 13px; color: #aaa; margin-top: 8px; word-break: break-all; }
.audio-label { font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 4px; opacity: 0.85; }
.word-audio-block, .sentence-audio-block { margin: 10px auto; max-width: 760px; }
.word-audio, .word-tts, .sentence-tts { margin: 4px 0; }
.sentence-audio { margin: 4px 0; }
.user-notes {
  text-align: left;
  margin: 16px auto;
  max-width: 760px;
  padding: 12px 14px;
  border-left: 3px solid #6a8fc7;
  background: rgba(106, 143, 199, 0.08);
}
.user-notes-label { margin-bottom: 6px; font-style: italic; }
.user-notes-body {
  font-size: 18px;
  line-height: 1.55;
  white-space: pre-wrap;
}
.nightMode .user-notes,
.card.nightMode .user-notes,
.night_mode .user-notes {
  background: rgba(106, 143, 199, 0.15);
}
.nightMode .furigana rt,
.card.nightMode .furigana rt,
.night_mode .furigana rt,
.nightMode .context-furigana rt,
.card.nightMode .context-furigana rt,
.night_mode .context-furigana rt {
  color: #eeeeee;
}
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
            "",
            "",
            "",
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
