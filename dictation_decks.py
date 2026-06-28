"""
dictation_decks.py

Native-audio dictation decks: hear WaniKani pronunciation, type the reading
(hiragana/katakana). The answer side shows the full WK word (kanji + kana) and reading.

Audio source: subject.data.pronunciation_audios (Kyoko / Kenichi, MP3 preferred).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import genanki
import html

from wk_decks import (
    CACHE_DIR,
    COMMON_CSS,
    DECK_NAMES,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WK_SHARED_MEDIA_SUBDIR,
    WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME,
    WkModel,
    first_reading,
    load_srs_stage_interval_days,
    primary_meanings,
    srs_stage,
    stable_guid,
    supplementary_import_tags,
    versioned_css,
    write_apkg,
)
from wk_reading_audio import (
    DEFAULT_WK_READING_VOICE,
    WK_READING_VOICES,
    ReadingAudioProgressBar,
    _audio_extension,
    dictation_audio_basename,
    ensure_pronunciation_audio_file,
    select_pronunciation_audio,
    voice_actor_slug,
)
DEFAULT_DICTATION_VOICE = DEFAULT_WK_READING_VOICE
DICTATION_DEFAULT_MIN_SRS = 7
DICTATION_VOICES = WK_READING_VOICES

DICTATION_DECK_ID = 2059400127
DICTATION_MODEL_ID = 1865429024
DICTATION_DECK_NAME = DECK_NAMES["dictation"]
DICTATION_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["dictation"]
DICTATION_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["dictation"]
DICTATION_MODEL_TEMPLATE_KEY = "dictation"


class DictationItem(NamedTuple):
    vocab: dict
    expression: str
    reading: str
    meaning: str


def dictation_expression(vocab: dict) -> str:
    """Full WK surface form (kanji + kana) shown on the answer side."""
    return str((vocab.get("data") or {}).get("characters") or "").strip()


def collect_vocab_dictation_items(
    vocab_items: Sequence[dict],
    assignment_index: Dict[int, dict],
    *,
    min_srs: int,
    voice_actor: str = DEFAULT_DICTATION_VOICE,
) -> List[DictationItem]:
    items: List[DictationItem] = []
    for vocab in sorted(
        vocab_items,
        key=lambda item: (item["data"].get("level", 999), item["data"].get("characters") or ""),
    ):
        if srs_stage(vocab, assignment_index) < min_srs:
            continue
        if select_pronunciation_audio(vocab, voice_actor=voice_actor) is None:
            continue
        expr = dictation_expression(vocab)
        reading = first_reading(vocab)
        if not expr or not reading:
            continue
        items.append(
            DictationItem(
                vocab=vocab,
                expression=expr,
                reading=reading,
                meaning="; ".join(primary_meanings(vocab)),
            )
        )
    return items


def make_dictation_model() -> WkModel:
    return WkModel(
        DICTATION_MODEL_ID,
        DICTATION_NOTE_TYPE_NAME,
        template_key=DICTATION_MODEL_TEMPLATE_KEY,
        fields=[
            {"name": "GuidKey"},
            {"name": "WkSubjectId"},
            {"name": "PronunciationAudio"},
            {"name": "Expression"},
            {"name": "Reading"},
            {"name": "Meaning"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Dictation",
                "qfmt": """
                <div class="prompt">Type what you hear (kana)</div>
                {{#PronunciationAudio}}<div class="pronunciation-audio">{{PronunciationAudio}}</div>{{/PronunciationAudio}}
                <div class="type-answer">{{type:Reading}}</div>
                <div class="meta">{{Meta}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="jp answer">{{Expression}}</div>
                <div class="reading answer">{{Reading}}</div>
                <div class="meaning answer">{{Meaning}}</div>
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.prompt { font-size: 18px; }
.pronunciation-audio { margin: 20px auto; }
.type-answer { margin: 20px auto; max-width: 520px; font-size: 32px; }
.jp.answer { font-size: 42px; margin-top: 8px; }
""",
            DICTATION_MODEL_TEMPLATE_KEY,
        ),
    )


def build_dictation_deck(
    items: Sequence[DictationItem],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    voice_actor: str = DEFAULT_DICTATION_VOICE,
    refresh_audio: bool = False,
    interval_map=None,
) -> Tuple[Path, genanki.Deck, List[str]]:
    deck = genanki.Deck(DICTATION_DECK_ID, DICTATION_DECK_NAME)
    model = make_dictation_model()
    template_label = DICTATION_TEMPLATE_VERSION
    stage_interval_map = interval_map or load_srs_stage_interval_days(
        CACHE_DIR / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME
    )
    media_dir = output_dir / WK_SHARED_MEDIA_SUBDIR
    media_files: List[str] = []
    audio_ok = 0
    audio_cached = 0
    audio_new = 0

    print(f"Dictation audio (WaniKani native, voice={voice_actor})...")
    progress = ReadingAudioProgressBar(len(items), label="Dictation audio")
    for item in items:
        vocab = item.vocab
        data = vocab["data"]
        level = data.get("level", "?")
        srs = srs_stage(vocab, assignment_index)
        guid = stable_guid("dictation", vocab["id"], voice_actor_slug(voice_actor))
        meta = f"WK L{level} · SRS {srs} · {voice_actor} · template {template_label}"

        audio_entry = select_pronunciation_audio(vocab, voice_actor=voice_actor)
        ext = _audio_extension(
            str((audio_entry or {}).get("content_type") or ""),
            str((audio_entry or {}).get("url") or ""),
        )
        basename = dictation_audio_basename(vocab, voice_actor, ext)
        dest = media_dir / basename
        ok, was_cached = ensure_pronunciation_audio_file(
            vocab,
            voice_actor=voice_actor,
            dest_path=dest,
            refresh=refresh_audio,
        )
        audio_field = ""
        if ok:
            audio_field = f"[sound:{basename}]"
            media_files.append(str(dest.resolve()))
            audio_ok += 1
            if was_cached:
                audio_cached += 1
            else:
                audio_new += 1

        note_tags = [
            "wanikani",
            "dictation",
            f"wk-level-{level}",
            f"voice-{voice_actor_slug(voice_actor)}",
        ]
        note_tags.extend(supplementary_import_tags(vocab, assignment_index, interval_map=stage_interval_map))
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                str(vocab["id"]),
                audio_field,
                html.escape(item.expression),
                html.escape(item.reading),
                html.escape(item.meaning),
                html.escape(meta),
            ],
            tags=note_tags,
            guid=guid,
        )
        deck.add_note(note)
        progress.advance()

    progress.finish(
        ok_count=audio_ok,
        detail=f"{audio_new} new, {audio_cached} cached",
    )
    deck.wk_media_files = media_files
    out = output_dir / "wk_dictation.apkg"
    write_apkg(deck, out, media_files=media_files or None)
    return out, deck, media_files
