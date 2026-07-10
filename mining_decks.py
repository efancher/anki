"""
mining_decks.py

Open Yomitan immersion deck + note type for live sentence/term mining via AnkiConnect.

Front: sentence cloze + progressive hints + type target word in kanji.
Back: full sentence + VOICEVOX audio; J–J and reference material after vocab is Guru+ in core.

Includes one suspended placeholder card so Anki imports the deck and note type.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

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

MINING_FIELD_NAMES: Tuple[str, ...] = (
    "DuplicateKey",
    "Expression",
    "Reading",
    "Furigana",
    "PitchAccents",
    "PitchPositions",
    "PitchGraphs",
    "Glossary",
    "Synonyms",
    "Antonyms",
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

MINING_FRONT = """
<div class="mining-card">
  {{#ClozeSentence}}<div class="cloze-sentence jp">{{ClozeSentence}}</div>{{/ClozeSentence}}
  {{^ClozeSentence}}{{#Sentence}}<div class="cloze-sentence jp">{{Sentence}}</div>{{/Sentence}}{{/ClozeSentence}}
  <div class="hint-block">
    {{#ShowKana}}{{#Reading}}<div class="hint-reading">{{Reading}}</div>{{/Reading}}{{/ShowKana}}
    {{#ShowEnglish}}{{#WkMeaning}}<div class="hint-meaning">{{WkMeaning}}</div>{{/WkMeaning}}{{/ShowEnglish}}
    {{#ShowEnglish}}{{^WkMeaning}}{{{DictLinksEn}}}{{/WkMeaning}}{{/ShowEnglish}}
    {{#ShowEnglish}}{{^WkMeaning}}{{#HintGlossary}}<div class="hint-glossary"><span class="meta">意味</span> {{HintGlossary}}</div>{{/HintGlossary}}{{/WkMeaning}}{{/ShowEnglish}}
    {{#ShowEnglish}}
    {{#PitchAccents}}<div class="hint-pitch"><span class="meta">Pitch</span> {{PitchAccents}}{{#PitchPositions}} <span class="pitch-pos">({{PitchPositions}})</span>{{/PitchPositions}}</div>{{/PitchAccents}}
    {{/ShowEnglish}}
  </div>
  <div class="type-prompt">{{type:Expression}}</div>
</div>
"""

MINING_BACK_CONTEXT = (
    """
{{#Sentence}}
<div class="context">
"""
    + """
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
    + """
  {{#SentenceFurigana}}<div class="jp context-furigana">{{SentenceFurigana}}</div>{{/SentenceFurigana}}
  {{^SentenceFurigana}}<div class="jp">{{Sentence}}</div>{{/SentenceFurigana}}
</div>
{{/Sentence}}
"""
)

MINING_BACK_STAGE2 = """
{{#ShowJjBack}}
{{#SentenceKana}}<div class="sentence-kana-block"><div class="meta">Speak (kana)</div><div class="sentence-kana jp">{{SentenceKana}}</div></div>{{/SentenceKana}}
{{#PitchAccents}}<div class="pitch"><b>Pitch:</b> {{PitchAccents}}{{#PitchPositions}} <span class="pitch-pos">({{PitchPositions}})</span>{{/PitchPositions}}</div>{{/PitchAccents}}
{{#PitchGraphs}}<div class="pitch-graphs">{{PitchGraphs}}</div>{{/PitchGraphs}}
{{{DictLinksJa}}}
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
{{#Audio}}
<div class="word-audio-block">
  <div class="audio-label meta">Word</div>
  <div class="word-audio">{{Audio}}</div>
</div>
{{/Audio}}
{{/ShowJjBack}}
"""


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
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="answer-word jp">{{Expression}}{{#Reading}} <span class="reading answer">{{Reading}}</span>{{/Reading}}</div>
                """
                + MINING_BACK_CONTEXT
                + MINING_BACK_STAGE2
                + """
                {{#UserNotes}}
                <div class="user-notes">
                  <div class="meta user-notes-label">Your notes</div>
                  <div class="user-notes-body">{{UserNotes}}</div>
                </div>
                {{/UserNotes}}
                {{#SourceTitle}}<div class="source">{{SourceTitle}}</div>{{/SourceTitle}}
                {{#SourceUrl}}<div class="source"><a href="{{SourceUrl}}">{{SourceUrl}}</a></div>{{/SourceUrl}}
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.mining-card { max-width: 760px; margin: 0 auto; }
.cloze-sentence { font-size: 34px; line-height: 1.55; margin: 16px 0; }
.cloze-blank {
  display: inline-block;
  min-width: 3em;
  border-bottom: 3px solid #fbc02d;
  color: #fbc02d;
  letter-spacing: 0.08em;
  padding: 0 4px;
}
.hint-block { margin: 12px auto; max-width: 640px; font-size: 20px; line-height: 1.5; }
.hint-reading { font-size: 28px; margin-bottom: 6px; color: #d8d8d8; }
.hint-meaning { color: #c8e6c9; margin-bottom: 6px; }
.hint-pitch, .hint-glossary { font-size: 16px; margin-top: 8px; text-align: left; }
.hint-glossary .meta, .hint-pitch .meta { margin-right: 6px; }
.type-prompt { margin: 18px auto; max-width: 520px; font-size: 28px; }
.answer-word { font-size: 36px; margin: 12px auto; }
.context { font-size: 28px; margin: 12px auto; max-width: 760px; line-height: 1.6; }
.context-furigana { line-height: 1.8; }
.context-furigana ruby { font-size: 28px; }
.context-furigana rt { font-size: 16px; color: #d8d8d8; }
.sentence-kana-block { margin: 14px auto; max-width: 760px; text-align: left; }
.sentence-kana { font-size: 24px; line-height: 1.6; color: #d8d8d8; }
.dict-links { font-size: 15px; margin: 8px 0; }
.dict-label { font-weight: bold; margin-right: 4px; }
.dict-links a { margin-right: 6px; }
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
.nightMode .context-furigana rt,
.card.nightMode .context-furigana rt,
.night_mode .context-furigana rt {
  color: #eeeeee;
}
""",
            MINING_MODEL_TEMPLATE_KEY,
        ),
    )


def _empty_mining_fields() -> List[str]:
    return [""] * len(MINING_FIELD_NAMES)


def _mining_setup_note(model: WkModel) -> genanki.Note:
    guid = stable_guid(MINING_SETUP_KIND, 1)
    meta = f"placeholder · template {MINING_TEMPLATE_VERSION} · delete after first Yomitan mine"
    fields = _empty_mining_fields()
    fields[0] = MINING_SETUP_DUPLICATE_KEY
    fields[1] = "（セットアップ）"
    fields[10] = html.escape("（セットアップ — Yomitan で単語を追加してください）")
    fields[7] = html.escape(
        "Placeholder so Anki imports this deck and note type. "
        "Mine a word from Yomitan, then delete this suspended card in Browse."
    )
    fields[-1] = html.escape(meta)
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
    out = output_dir / "wk_mining.apkg"
    write_apkg(deck, out)
    patch_apkg_suspend_notes_with_tag(out, MINING_SETUP_TAG)
    return out, deck
