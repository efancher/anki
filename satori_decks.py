"""
satori_decks.py

Immersion · Satori — sentence cloze cards from a Satori Reader CSV export.

Front: cloze blank in Context1 + type Expression (kanji).
Back: full sentence, reading, word English, sentence translation (always shown).
"""

from __future__ import annotations

import csv
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import genanki

from wk_decks import (
    COMMON_CSS,
    DECK_IDS,
    DECK_NAMES,
    MODEL_IDS,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WkModel,
    stable_guid,
    versioned_css,
    write_apkg,
)

REPO_ROOT = Path(__file__).resolve().parent
IMMERSION_LOGIC = REPO_ROOT / "anki_addon" / "wk_immersion"
if str(IMMERSION_LOGIC) not in sys.path:
    sys.path.insert(0, str(IMMERSION_LOGIC))

from mining_logic import (  # noqa: E402
    CLOZE_BLANK_DISPLAY,
    blank_targets_for_expression,
    enrich_mining_note_fields,
    plain_mining_text,
)

# Kanji ranges (CJK unified + extension A + compatibility ideographs).
_KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def kanji_stem(text: str) -> str:
    """Contiguous substring from the first kanji to the last kanji (inclusive).

    Kanji do not change when a word conjugates, so this stem is a stable anchor
    for a target word even when it appears inflected in the sentence.
    Returns '' when the text has no kanji.
    """
    indices = [index for index, ch in enumerate(text) if _KANJI_RE.match(ch)]
    if not indices:
        return ""
    return text[indices[0] : indices[-1] + 1]


def build_satori_cloze_sentence(
    sentence: str, expression: str, reading: str
) -> Tuple[str, str]:
    """Satori front cloze. Returns (cloze_html, plain_sentence).

    - Target word contains kanji → highlight the kanji stem (learn readings in
      context). Works for conjugated verbs/adjectives because kanji are invariant.
    - Hiragana-only word → blank it with underscores.
    """
    plain = plain_mining_text(sentence)
    if not plain:
        return "", ""
    stem = kanji_stem(plain_mining_text(expression))
    if stem:
        idx = plain.find(stem)
        if idx >= 0:
            before = html.escape(plain[:idx])
            target = html.escape(stem)
            after = html.escape(plain[idx + len(stem) :])
            highlight = f'<span class="cloze-target">{target}</span>'
            return f"{before}{highlight}{after}", plain
    for target in blank_targets_for_expression(expression, reading):
        clean = plain_mining_text(target)
        if not clean:
            continue
        idx = plain.find(clean)
        if idx >= 0:
            before = html.escape(plain[:idx])
            after = html.escape(plain[idx + len(clean) :])
            blank = f'<span class="cloze-blank">{CLOZE_BLANK_DISPLAY}</span>'
            return f"{before}{blank}{after}", plain
    return html.escape(plain), plain

SATORI_KIND = "satori-mining"
SATORI_TAG = "satori-mining"
SATORI_DECK_ID = DECK_IDS["satori"]
SATORI_MODEL_ID = MODEL_IDS["satori"]
SATORI_DECK_NAME = DECK_NAMES["satori"]
SATORI_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["satori"]
SATORI_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["satori"]
SATORI_MODEL_TEMPLATE_KEY = "satori"
SATORI_EXPORT_FILENAME = "wk_satori.apkg"

# Same field layout as Migaku immersion so enrich/unlock helpers stay compatible.
SATORI_FIELD_NAMES: Tuple[str, ...] = (
    "DuplicateKey",
    "Expression",
    "Reading",
    "Translation",
    "Furigana",
    "PitchAccents",
    "PitchPositions",
    "PitchGraphs",
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
    "SentenceAudioEasy",
    "VoicevoxAudio",
    "VoicevoxSpeakerId",
    "UserNotes",
    "SourceUrl",
    "SourceTitle",
    "Meta",
)

SATORI_FRONT = """
<div class="mining-card">
  {{#ClozeSentence}}<div class="cloze-sentence jp">{{ClozeSentence}}</div>{{/ClozeSentence}}
  {{^ClozeSentence}}{{#Sentence}}<div class="cloze-sentence jp">{{Sentence}}</div>{{/Sentence}}{{/ClozeSentence}}
  <div class="hint-block">
    {{#WkMeaning}}<div class="hint-meaning">{{WkMeaning}}</div>{{/WkMeaning}}
  </div>
  <div class="type-prompt">{{type:Reading}}</div>
</div>
"""

SATORI_SENTENCE_TTS = "{{tts ja_JP:Sentence}}"

SATORI_BACK = """
{{FrontSide}}
<hr>
<div class="answer-word jp">
  {{#Furigana}}{{furigana:Furigana}}{{/Furigana}}
  {{^Furigana}}{{Expression}}{{#Reading}} <span class="reading answer">{{Reading}}</span>{{/Reading}}{{/Furigana}}
</div>
{{#WkMeaning}}<div class="meaning answer">{{WkMeaning}}</div>{{/WkMeaning}}
{{#Sentence}}
<div class="context">
  <div class="sentence-audio-block">
  {{#SentenceAudioEasy}}
  <div class="audio-row">
    <div class="audio-label meta">Easy</div>
    <div class="sentence-audio sentence-tts-file">{{SentenceAudioEasy}}</div>
  </div>
  {{/SentenceAudioEasy}}
  {{#SentenceAudio}}
  <div class="audio-row">
    <div class="audio-label meta">Normal</div>
    <audio class="sentence-audio-manual" controls preload="none" src="{{SentenceAudio}}"></audio>
  </div>
  {{/SentenceAudio}}
  {{^SentenceAudioEasy}}
  {{^SentenceAudio}}
  {{#VoicevoxAudio}}<div class="sentence-audio voicevox-audio">{{VoicevoxAudio}}</div>{{/VoicevoxAudio}}
  {{^VoicevoxAudio}}
  <div class="sentence-tts">""" + SATORI_SENTENCE_TTS + """</div>
  {{/VoicevoxAudio}}
  {{/SentenceAudio}}
  {{/SentenceAudioEasy}}
  </div>
  {{#SentenceFurigana}}<div class="jp context-furigana">{{furigana:SentenceFurigana}}</div>{{/SentenceFurigana}}
  {{^SentenceFurigana}}<div class="jp">{{Sentence}}</div>{{/SentenceFurigana}}
  {{#Translation}}<div class="sentence-en">{{Translation}}</div>{{/Translation}}
</div>
{{/Sentence}}
{{#Glossary}}
<div class="word-def word-def-glossary">
  <div class="meta word-def-label">Notes</div>
  <div class="word-def-body">{{Glossary}}</div>
</div>
{{/Glossary}}
{{#UserNotes}}
<div class="user-notes">
  <div class="meta user-notes-label">Your notes</div>
  <div class="user-notes-body">{{UserNotes}}</div>
</div>
{{/UserNotes}}
{{#SourceTitle}}<div class="source">{{SourceTitle}}</div>{{/SourceTitle}}
<div class="meta">{{Meta}}</div>
<script>
(function () {
  document.querySelectorAll("audio.sentence-audio-manual").forEach(function (audio) {
    var src = (audio.getAttribute("src") || "").trim();
    var match = src.match(/\\[sound:([^\\]]+)\\]/);
    if (match) {
      audio.setAttribute("src", match[1]);
    }
  });
})();
</script>
"""

SATORI_CSS = """
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
.cloze-target {
  color: #4fc3f7;
  border-bottom: 3px solid #4fc3f7;
  padding: 0 2px;
  font-weight: 600;
}
.hint-block { margin: 12px auto; max-width: 640px; font-size: 20px; line-height: 1.5; }
.hint-meaning { color: #c8e6c9; margin-bottom: 6px; }
.type-prompt { margin: 18px auto; max-width: 520px; font-size: 28px; }
.answer-word { font-size: 36px; margin: 12px auto; line-height: 1.8; }
.answer-word ruby rt { font-size: 14px; color: #d8d8d8; }
.context { font-size: 28px; margin: 12px auto; max-width: 760px; line-height: 1.6; }
.context-furigana { line-height: 2.1; }
.context-furigana ruby rt { font-size: 14px; color: #d8d8d8; }
.sentence-audio-block { margin: 8px 0 12px; }
.audio-row { margin: 6px 0; }
.audio-label { font-size: 13px; margin-bottom: 2px; }
.sentence-audio, .sentence-tts { margin: 2px 0 6px; }
.sentence-audio-manual {
  display: block;
  width: 100%;
  max-width: 420px;
  margin: 2px 0 6px;
  height: 32px;
}
.sentence-en { font-size: 18px; color: #c8e6c9; margin-top: 10px; }
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
.user-notes { text-align: left; margin: 12px auto; max-width: 760px; }
.source { font-size: 14px; color: #aaa; margin-top: 8px; }
"""


@dataclass(frozen=True)
class SatoriCard:
    card_id: str
    card_type: str
    expression: str
    reading: str
    expression_furigana: str
    english: str
    parts_of_speech: str
    sentence: str
    sentence_furigana: str
    sentence_translation: str
    user_notes: str


def make_satori_model() -> WkModel:
    return WkModel(
        SATORI_MODEL_ID,
        SATORI_NOTE_TYPE_NAME,
        template_key=SATORI_MODEL_TEMPLATE_KEY,
        fields=[{"name": name} for name in SATORI_FIELD_NAMES],
        templates=[
            {
                "name": "Sentence cloze → word",
                "qfmt": SATORI_FRONT,
                "afmt": SATORI_BACK,
            },
        ],
        css=versioned_css(COMMON_CSS + SATORI_CSS, SATORI_MODEL_TEMPLATE_KEY),
    )


def _cell(row: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""


def parse_satori_csv(
    path: Path,
    *,
    card_types: Optional[Sequence[str]] = None,
) -> List[SatoriCard]:
    """Parse a Satori Reader export. Default: JE production cards only."""
    allowed = {ctype.upper() for ctype in (card_types or ("JE",))}
    cards: List[SatoriCard] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            card_type = _cell(row, "CardType").upper()
            if allowed and card_type not in allowed:
                continue
            expression = _cell(row, "Expression")
            sentence = _cell(row, "Context1")
            if not expression or not sentence:
                continue
            cards.append(
                SatoriCard(
                    card_id=_cell(row, "CardID") or f"{expression}|{sentence}",
                    card_type=card_type,
                    expression=expression,
                    reading=_cell(row, "Expression-ReadingsOnly"),
                    expression_furigana=_cell(row, "Expression-ReadingsInline"),
                    english=_cell(row, "English"),
                    parts_of_speech=_cell(row, "PartsOfSpeech"),
                    sentence=sentence,
                    sentence_furigana=_cell(row, "Context1-ReadingsInline"),
                    sentence_translation=_cell(row, "Context1-Translation"),
                    user_notes=_cell(row, "UserNotes"),
                )
            )
    return cards


def satori_note_fields(card: SatoriCard, *, wk_entry: Optional[dict] = None) -> List[str]:
    cloze_html, plain_sentence = build_satori_cloze_sentence(
        card.sentence, card.expression, card.reading
    )
    enrichment = enrich_mining_note_fields(
        expression=card.expression,
        reading=card.reading,
        sentence=plain_sentence or card.sentence,
        sentence_furigana=card.sentence_furigana,
        glossary=card.parts_of_speech,
        translation=card.english,
        wk_entry=wk_entry,
    )
    # Always keep Satori English visible (word + sentence), independent of hint stage.
    # Kana stays on the back only (via {{furigana:…}} / Reading) — never as a front hint.
    wk_meaning = enrichment.wk_meaning or card.english
    translation = card.sentence_translation
    glossary = card.parts_of_speech
    duplicate_key = f"{card.card_id}|{enrichment.expression}|{enrichment.sentence}"
    meta = f"Satori · {card.card_type} · template {SATORI_TEMPLATE_VERSION}"
    expression_furigana = (card.expression_furigana or "").strip()
    sentence_furigana = (card.sentence_furigana or "").strip()
    raw_html_fields = {
        "ClozeSentence",
        "DictLinksJa",
        "DictLinksEn",
        "SentenceFurigana",
        "Furigana",
    }
    values = {
        "DuplicateKey": duplicate_key,
        "Expression": enrichment.expression,
        "Reading": enrichment.reading or card.reading,
        "Translation": translation,
        "Furigana": expression_furigana,
        "PitchAccents": "",
        "PitchPositions": "",
        "PitchGraphs": "",
        "Glossary": glossary,
        "Synonyms": "",
        "Antonyms": "",
        "Image": "",
        "ClozeSentence": cloze_html or enrichment.cloze_sentence,
        "WkSubjectId": enrichment.wk_subject_id,
        "PrerequisiteIds": enrichment.prerequisite_ids,
        "WkMeaning": wk_meaning,
        "HintGlossary": enrichment.hint_glossary,
        "HintStage": "0",
        # Satori always shows English on the front; unlock must not clear these.
        "ShowEnglish": "1",
        "ShowKana": "",
        "ShowJjBack": "",
        "SentenceKana": enrichment.sentence_kana,
        "DictLinksJa": enrichment.dict_links_ja,
        "DictLinksEn": enrichment.dict_links_en,
        "Sentence": enrichment.sentence,
        "SentenceFurigana": sentence_furigana,
        "Audio": "",
        "SentenceAudio": "",
        "SentenceAudioEasy": "",
        "VoicevoxAudio": "",
        "VoicevoxSpeakerId": "",
        "UserNotes": card.user_notes,
        "SourceUrl": "",
        "SourceTitle": "Satori Reader",
        "Meta": meta,
    }
    fields: List[str] = []
    for name in SATORI_FIELD_NAMES:
        value = values[name]
        if name in raw_html_fields:
            fields.append(value)
        else:
            fields.append(html.escape(value))
    return fields


def build_satori_deck(
    cards: Sequence[SatoriCard],
    output_dir: Path,
    *,
    wk_index: Optional[dict] = None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(SATORI_DECK_ID, SATORI_DECK_NAME)
    model = make_satori_model()
    by_expression = (wk_index or {}).get("by_expression") or {}

    for card in cards:
        wk_entry = by_expression.get(card.expression)
        guid = stable_guid(SATORI_KIND, card.card_id)
        note = genanki.Note(
            model=model,
            fields=satori_note_fields(card, wk_entry=wk_entry),
            tags=["immersion", SATORI_TAG, f"satori-{card.card_type.lower()}"],
            guid=guid,
        )
        deck.add_note(note)

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / SATORI_EXPORT_FILENAME
    write_apkg(deck, out)
    return out, deck
