"""
vocab_sentence_decks.py

Context-sentence vocabulary decks using WK context_sentences:

- Sentence Meaning: highlighted vocab in a WK sentence → recall English meaning.
- Sentence Reading: same front → type kana reading for the highlighted word.

Unlock: wk-locked until kanji components are Guru+ in Kanji Meaning Anchor
(same PrerequisiteIds / wk_unlock path as dictation and vocab cloze).
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

import genanki

from wk_decks import (
    COMMON_CSS,
    DECK_IDS,
    DECK_NAMES,
    MODEL_IDS,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WK_SHARED_MEDIA_SUBDIR,
    WK_SRS_STAGE_MASTER,
    WkModel,
    ensure_sentence_audio_file,
    first_reading,
    prepare_sentence_for_tts,
    primary_meanings,
    srs_stage,
    stable_guid,
    strip_html,
    tts_audio_basename_for_config,
    versioned_css,
    vocab_cloze_blank_targets,
    vocab_kanji_prerequisite_ids,
    vocab_supplementary_import_tags,
    write_apkg,
)
from wk_sentence_tts import SentenceTtsConfig, require_sentence_tts
from wk_reading_audio import ReadingAudioProgressBar

VOCAB_SENTENCE_KIND_MEANING = "vocab-sentence-meaning"
VOCAB_SENTENCE_KIND_READING = "vocab-sentence-reading"

VOCAB_SENTENCE_DEFAULT_MIN_SRS = WK_SRS_STAGE_MASTER
VOCAB_SENTENCE_SENTENCE_AUDIO_DEFAULT = True

VOCAB_SENTENCE_MEANING_DECK_ID = DECK_IDS["vocab-sentence-meaning"]
VOCAB_SENTENCE_READING_DECK_ID = DECK_IDS["vocab-sentence-reading"]
VOCAB_SENTENCE_MEANING_MODEL_ID = MODEL_IDS["vocab_sentence_meaning"]
VOCAB_SENTENCE_READING_MODEL_ID = MODEL_IDS["vocab_sentence_reading"]
VOCAB_SENTENCE_MEANING_DECK_NAME = DECK_NAMES["vocab-sentence-meaning"]
VOCAB_SENTENCE_READING_DECK_NAME = DECK_NAMES["vocab-sentence-reading"]
VOCAB_SENTENCE_MEANING_NOTE_TYPE = NOTE_TYPE_NAMES["vocab_sentence_meaning"]
VOCAB_SENTENCE_READING_NOTE_TYPE = NOTE_TYPE_NAMES["vocab_sentence_reading"]
VOCAB_SENTENCE_MEANING_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["vocab_sentence_meaning"]
VOCAB_SENTENCE_READING_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["vocab_sentence_reading"]
VOCAB_SENTENCE_MEANING_TEMPLATE_KEY = "vocab_sentence_meaning"
VOCAB_SENTENCE_READING_TEMPLATE_KEY = "vocab_sentence_reading"

VOCAB_SENTENCE_SHARED_CSS = """
.sentence-jp { font-size: 34px; line-height: 1.55; margin: 16px 0; }
.sentence-jp .target {
  background: rgba(255, 235, 59, 0.18);
  border-bottom: 2px solid #fbc02d;
  font-weight: 700;
  padding: 0 2px;
}
.sentence-audio { margin: 12px auto 8px; }
.type-answer { margin: 16px auto; max-width: 520px; font-size: 28px; }
.context .jp { font-size: 28px; margin-top: 8px; }
"""


class VocabSentenceItem(NamedTuple):
    vocab: dict
    highlighted_sentence: str
    full_sentence: str
    sentence_en: str
    source_ja: str
    expression: str
    reading: str
    meaning: str


def highlight_target_in_sentence(
    sentence: str,
    targets: Sequence[str],
) -> Optional[Tuple[str, str]]:
    """Wrap the first matching target in a highlight span. Returns (html, plain) or None."""
    plain = strip_html(sentence)
    if not plain:
        return None
    for target in targets:
        idx = plain.find(target)
        if idx >= 0:
            before = html.escape(plain[:idx])
            target_html = html.escape(target)
            after = html.escape(plain[idx + len(target):])
            highlighted = f'{before}<span class="target">{target_html}</span>{after}'
            return highlighted, plain
    return None


def select_vocab_sentence_highlight(vocab: dict) -> Optional[Tuple[dict, str, str]]:
    """Pick the first WK context sentence where the vocab can be highlighted."""
    if vocab.get("object") != "vocabulary":
        return None
    targets = vocab_cloze_blank_targets(vocab)
    if not targets:
        return None
    for sentence in vocab["data"].get("context_sentences") or []:
        highlighted = highlight_target_in_sentence(sentence.get("ja") or "", targets)
        if highlighted:
            html_sentence, full = highlighted
            return sentence, html_sentence, full
    return None


def collect_vocab_sentence_items(
    vocab_items: Sequence[dict],
    assignment_index: Dict[int, dict],
    *,
    min_srs: int,
) -> List[VocabSentenceItem]:
    items: List[VocabSentenceItem] = []
    for vocab in sorted(
        vocab_items,
        key=lambda item: (item["data"].get("level", 999), item["data"].get("characters") or ""),
    ):
        if srs_stage(vocab, assignment_index) < min_srs:
            continue
        selected = select_vocab_sentence_highlight(vocab)
        if not selected:
            continue
        sentence, highlighted, full = selected
        data = vocab["data"]
        expr = (data.get("characters") or "").strip()
        reading = first_reading(vocab)
        meaning = "; ".join(primary_meanings(vocab))
        if not expr or not reading or not meaning:
            continue
        items.append(
            VocabSentenceItem(
                vocab=vocab,
                highlighted_sentence=highlighted,
                full_sentence=full,
                sentence_en=strip_html(sentence.get("en")),
                source_ja=sentence.get("ja") or "",
                expression=expr,
                reading=reading,
                meaning=meaning,
            )
        )
    return items


def collect_vocab_sentence_tts_texts(items: Sequence[VocabSentenceItem]) -> List[str]:
    """Return TTS strings for prefetch (one per item; deduped later in wk_decks)."""
    texts: List[str] = []
    for item in items:
        texts.append(
            prepare_sentence_for_tts(
                item.full_sentence,
                item.vocab,
                source_ja=item.source_ja,
            )
        )
    return texts


def _sentence_audio_field(
    item: VocabSentenceItem,
    *,
    media_dir: Path,
    sentence_audio: bool,
    sentence_tts_config: SentenceTtsConfig,
    refresh_sentence_audio: bool,
    media_files: List[str],
    media_paths_seen: Set[str],
    stats: Dict[str, int],
) -> str:
    if not sentence_audio:
        return ""
    tts_text = prepare_sentence_for_tts(
        item.full_sentence,
        item.vocab,
        source_ja=item.source_ja,
    )
    basename = tts_audio_basename_for_config(tts_text, sentence_tts_config)
    if not basename:
        return ""
    dest = media_dir / basename
    ok, was_cached = ensure_sentence_audio_file(
        tts_text,
        sentence_tts_config,
        dest,
        refresh=refresh_sentence_audio,
    )
    if not ok:
        return ""
    dest_str = str(dest.resolve())
    if dest_str not in media_paths_seen:
        media_files.append(dest_str)
        media_paths_seen.add(dest_str)
    stats["ok"] += 1
    if was_cached:
        stats["cached"] += 1
    else:
        stats["new"] += 1
    return f"[sound:{basename}]"


def _build_vocab_sentence_deck_notes(
    items: Sequence[VocabSentenceItem],
    *,
    deck: genanki.Deck,
    model: WkModel,
    kind: str,
    kind_tag: str,
    template_label: str,
    assignment_index: Dict[int, dict],
    media_dir: Path,
    sentence_audio: bool,
    sentence_tts_config: SentenceTtsConfig,
    refresh_sentence_audio: bool,
    progress_label: str,
) -> Tuple[List[str], Dict[str, int]]:
    media_files: List[str] = []
    media_paths_seen: Set[str] = set()
    stats = {"ok": 0, "cached": 0, "new": 0}
    progress = ReadingAudioProgressBar(len(items), label=progress_label, enabled=sentence_audio)

    for item in items:
        guid = stable_guid(kind, item.vocab["id"])
        audio_field = _sentence_audio_field(
            item,
            media_dir=media_dir,
            sentence_audio=sentence_audio,
            sentence_tts_config=sentence_tts_config,
            refresh_sentence_audio=refresh_sentence_audio,
            media_files=media_files,
            media_paths_seen=media_paths_seen,
            stats=stats,
        )
        fields, note_tags = _shared_note_fields(
            item,
            guid=guid,
            template_label=template_label,
            assignment_index=assignment_index,
            sentence_audio_field=audio_field,
        )
        note_tags.append(kind_tag)
        deck.add_note(
            genanki.Note(
                model=model,
                fields=fields,
                tags=note_tags,
                guid=guid,
            )
        )
        progress.advance()

    if sentence_audio and items:
        progress.finish(
            ok_count=stats["ok"],
            detail=f"{stats['new']} new, {stats['cached']} cached",
        )
    return media_files, stats


def make_vocab_sentence_meaning_model() -> WkModel:
    return WkModel(
        VOCAB_SENTENCE_MEANING_MODEL_ID,
        VOCAB_SENTENCE_MEANING_NOTE_TYPE,
        template_key=VOCAB_SENTENCE_MEANING_TEMPLATE_KEY,
        fields=[
            {"name": "GuidKey"},
            {"name": "WkSubjectId"},
            {"name": "PrerequisiteIds"},
            {"name": "HighlightedSentence"},
            {"name": "SentenceAudio"},
            {"name": "Expression"},
            {"name": "Reading"},
            {"name": "Meaning"},
            {"name": "FullSentence"},
            {"name": "SentenceEnglish"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Sentence meaning",
                "qfmt": """
                <div class="prompt">Meaning of the highlighted word?</div>
                <div class="sentence-jp">{{HighlightedSentence}}</div>
                {{#SentenceAudio}}<div class="sentence-audio">{{SentenceAudio}}</div>{{/SentenceAudio}}
                <div class="meta">{{Meta}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="meaning answer">{{Meaning}}</div>
                <div class="reading answer">{{Reading}}</div>
                <div class="jp answer">{{Expression}}</div>
                <div class="context">
                  <div class="jp">{{FullSentence}}</div>
                  <div class="meaning">{{SentenceEnglish}}</div>
                </div>
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(COMMON_CSS + VOCAB_SENTENCE_SHARED_CSS, VOCAB_SENTENCE_MEANING_TEMPLATE_KEY),
    )


def make_vocab_sentence_reading_model() -> WkModel:
    return WkModel(
        VOCAB_SENTENCE_READING_MODEL_ID,
        VOCAB_SENTENCE_READING_NOTE_TYPE,
        template_key=VOCAB_SENTENCE_READING_TEMPLATE_KEY,
        fields=[
            {"name": "GuidKey"},
            {"name": "WkSubjectId"},
            {"name": "PrerequisiteIds"},
            {"name": "HighlightedSentence"},
            {"name": "SentenceAudio"},
            {"name": "Expression"},
            {"name": "Reading"},
            {"name": "Meaning"},
            {"name": "FullSentence"},
            {"name": "SentenceEnglish"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Sentence reading",
                "qfmt": """
                <div class="prompt">Reading of the highlighted word (kana)?</div>
                <div class="sentence-jp">{{HighlightedSentence}}</div>
                {{#SentenceAudio}}<div class="sentence-audio">{{SentenceAudio}}</div>{{/SentenceAudio}}
                <div class="type-answer">{{type:Reading}}</div>
                <div class="meta">{{Meta}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="reading answer">{{Reading}}</div>
                <div class="jp answer">{{Expression}}</div>
                <div class="meaning answer">{{Meaning}}</div>
                <div class="context">
                  <div class="jp">{{FullSentence}}</div>
                  <div class="meaning">{{SentenceEnglish}}</div>
                </div>
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(COMMON_CSS + VOCAB_SENTENCE_SHARED_CSS, VOCAB_SENTENCE_READING_TEMPLATE_KEY),
    )


def _shared_note_fields(
    item: VocabSentenceItem,
    *,
    guid: str,
    template_label: str,
    assignment_index: Dict[int, dict],
    sentence_audio_field: str,
) -> Tuple[List[str], List[str]]:
    vocab = item.vocab
    level = vocab["data"].get("level", "?")
    srs = srs_stage(vocab, assignment_index)
    meta = f"WK L{level} · SRS {srs} · template {template_label}"
    note_tags = [
        "wanikani",
        "vocab-sentence",
        f"wk-level-{level}",
    ]
    note_tags.extend(vocab_supplementary_import_tags(vocab))
    fields = [
        guid,
        str(vocab["id"]),
        vocab_kanji_prerequisite_ids(vocab),
        item.highlighted_sentence,
        sentence_audio_field,
        html.escape(item.expression),
        html.escape(item.reading),
        html.escape(item.meaning),
        html.escape(item.full_sentence),
        html.escape(item.sentence_en),
        html.escape(meta),
    ]
    return fields, note_tags


def build_vocab_sentence_meaning_deck(
    items: Sequence[VocabSentenceItem],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    sentence_audio: bool = True,
    sentence_tts_config: Optional[SentenceTtsConfig] = None,
    sentence_audio_voice: str = "ja-JP-NanamiNeural",
    refresh_sentence_audio: bool = False,
) -> Tuple[Path, genanki.Deck, List[str]]:
    tts_config = sentence_tts_config or SentenceTtsConfig.edge_only(sentence_audio_voice)
    deck = genanki.Deck(VOCAB_SENTENCE_MEANING_DECK_ID, VOCAB_SENTENCE_MEANING_DECK_NAME)
    model = make_vocab_sentence_meaning_model()
    template_label = VOCAB_SENTENCE_MEANING_TEMPLATE_VERSION
    media_dir = output_dir / WK_SHARED_MEDIA_SUBDIR
    if sentence_audio:
        require_sentence_tts(tts_config)
    media_files, _stats = _build_vocab_sentence_deck_notes(
        items,
        deck=deck,
        model=model,
        kind=VOCAB_SENTENCE_KIND_MEANING,
        kind_tag="vocab-sentence-meaning",
        template_label=template_label,
        assignment_index=assignment_index,
        media_dir=media_dir,
        sentence_audio=sentence_audio,
        sentence_tts_config=tts_config,
        refresh_sentence_audio=refresh_sentence_audio,
        progress_label="Vocab sentence meaning cards",
    )
    out = output_dir / "wk_vocab_sentence_meaning.apkg"
    write_apkg(deck, out, media_files=media_files or None)
    return out, deck, media_files


def build_vocab_sentence_reading_deck(
    items: Sequence[VocabSentenceItem],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    sentence_audio: bool = True,
    sentence_tts_config: Optional[SentenceTtsConfig] = None,
    sentence_audio_voice: str = "ja-JP-NanamiNeural",
    refresh_sentence_audio: bool = False,
) -> Tuple[Path, genanki.Deck, List[str]]:
    tts_config = sentence_tts_config or SentenceTtsConfig.edge_only(sentence_audio_voice)
    deck = genanki.Deck(VOCAB_SENTENCE_READING_DECK_ID, VOCAB_SENTENCE_READING_DECK_NAME)
    model = make_vocab_sentence_reading_model()
    template_label = VOCAB_SENTENCE_READING_TEMPLATE_VERSION
    media_dir = output_dir / WK_SHARED_MEDIA_SUBDIR
    if sentence_audio:
        require_sentence_tts(tts_config)
    media_files, _stats = _build_vocab_sentence_deck_notes(
        items,
        deck=deck,
        model=model,
        kind=VOCAB_SENTENCE_KIND_READING,
        kind_tag="vocab-sentence-reading",
        template_label=template_label,
        assignment_index=assignment_index,
        media_dir=media_dir,
        sentence_audio=sentence_audio,
        sentence_tts_config=tts_config,
        refresh_sentence_audio=refresh_sentence_audio,
        progress_label="Vocab sentence reading cards",
    )
    out = output_dir / "wk_vocab_sentence_reading.apkg"
    write_apkg(deck, out, media_files=media_files or None)
    return out, deck, media_files
