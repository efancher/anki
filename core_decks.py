"""
core_decks.py

Build WaniKani core SRS decks (radicals, kanji, vocabulary) with prerequisite metadata.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, TYPE_CHECKING

import genanki

if TYPE_CHECKING:
    from wk_sentence_tts import SentenceTtsConfig

from wk_decks import (
    COMMON_CSS,
    DECK_IDS,
    DECK_NAMES,
    DEFAULT_SENTENCE_AUDIO_VOICE,
    MODEL_IDS,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WK_MNEMONIC_CSS,
    WkModel,
    all_wk_kanji_subjects,
    context_sentences_html,
    ensure_radical_media_files,
    meta_html,
    primary_meanings,
    primary_readings,
    kanji_index_by_characters,
    meaning_mnemonic_html,
    radical_description_html,
    radical_display,
    radical_subjects,
    reading_mnemonic_html,
    readings_detail_html,
    stable_guid,
    subject_is_hidden,
    subject_style_class,
    subject_type_flags,
    subject_type_label,
    versioned_css,
    write_apkg,
    WK_SHARED_MEDIA_SUBDIR,
)
from wk_reading_audio import (
    DEFAULT_WK_READING_VOICE,
    READING_AUDIO_CSS,
    ReadingAudioProgressBar,
    prepare_reading_audio_field,
)
from wk_scheduling import WkCardScheduleSpec, schedule_spec_for_assignment
from wk_study_priority import SubjectPriority, priority_score_for, priority_tags, wk_level_to_jlpt

CORE_RADICAL_KIND = "core-radical"
CORE_ITEM_KIND = "core-item"
CORE_TAG = "wk-core"


def priority_score_fallback(subject: dict) -> int:
    level = int((subject.get("data") or {}).get("level") or 60)
    return priority_score_for(wk_level_to_jlpt(level), level)


def format_prerequisite_ids(subject: dict) -> str:
    ids = subject["data"].get("component_subject_ids") or []
    return ",".join(str(component_id) for component_id in ids)


def all_core_vocab_subjects(subjects: Sequence[dict], args) -> List[dict]:
    return [
        subject
        for subject in subjects
        if subject.get("object") == "vocabulary"
        and int(subject["data"].get("level", 999)) <= args.max_level
        and not subject_is_hidden(subject)
    ]


def core_meta_html(subject: dict, assignment_index: Dict[int, dict]) -> str:
    return meta_html(subject, assignment_index).replace(
        f"template {MODEL_TEMPLATE_VERSIONS['item']}",
        f"template {MODEL_TEMPLATE_VERSIONS['core_item']}",
    )


def make_core_radical_model() -> WkModel:
    return WkModel(
        MODEL_IDS["core_radical"],
        NOTE_TYPE_NAMES["core_radical"],
        template_key="core_radical",
        fields=[
            {"name": "GuidKey"},
            {"name": "Radical"},
            {"name": "Meaning"},
            {"name": "Level"},
            {"name": "WkSubjectId"},
            {"name": "PrerequisiteIds"},
            {"name": "Description"},
        ],
        templates=[
            {
                "name": "Radical Meaning",
                "qfmt": """
                <div class='prompt'>Radical meaning?</div>
                <div class='radical-display'>{{Radical}}</div>
                <div class='meta'>WK Level {{Level}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class='meaning'>{{Meaning}}</div>
                {{#Description}}<h3>Description</h3><div class='notes'>{{Description}}</div>{{/Description}}
                """,
            }
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.radical-display { margin: 12px 0; }
.radical-display .jp { font-size: 42px; }
.radical-img {
  max-height: 128px;
  max-width: 128px;
  vertical-align: middle;
}
.radical-text { font-size: 32px; color: #cfcfcf; }
"""
            + WK_MNEMONIC_CSS,
            "core_radical",
        ),
    )


def make_core_item_model() -> WkModel:
    return WkModel(
        MODEL_IDS["core_item"],
        NOTE_TYPE_NAMES["core_item"],
        template_key="core_item",
        fields=[
            {"name": "GuidKey"},
            {"name": "Expression"},
            {"name": "Reading"},
            {"name": "ReadingAudio"},
            {"name": "Meaning"},
            {"name": "Mnemonic"},
            {"name": "ReadingMnemonic"},
            {"name": "SubjectType"},
            {"name": "ReadingsDetail"},
            {"name": "Meta"},
            {"name": "ContextSentences"},
            {"name": "StyleClass"},
            {"name": "IsKanji"},
            {"name": "IsVocabulary"},
            {"name": "WkSubjectId"},
            {"name": "PrerequisiteIds"},
        ],
        templates=[
            {
                "name": "Review",
                "qfmt": """
                <div class="wk-card {{StyleClass}}">
                <div class="subject-badge">{{SubjectType}}</div>
                <div class="prompt">
                  Recall the meaning, then type the reading (kana).
                  {{#IsKanji}}<div class="prompt-hint">On'yomi / kun'yomi</div>{{/IsKanji}}
                  {{#IsVocabulary}}<div class="prompt-hint">Vocabulary reading</div>{{/IsVocabulary}}
                </div>
                <div class="jp">{{Expression}}</div>
                <div class="type-answer">{{type:Reading}}</div>
                </div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="meaning answer">{{Meaning}}</div>
                <div class="reading answer">{{Reading}}</div>
                {{#ReadingAudio}}<div class="reading-audio">{{ReadingAudio}}</div>{{/ReadingAudio}}
                {{#ReadingsDetail}}<div class="reading-detail">{{ReadingsDetail}}</div>{{/ReadingsDetail}}
                {{#Mnemonic}}<h3>Meaning mnemonic</h3><div class="notes">{{Mnemonic}}</div>{{/Mnemonic}}
                {{#ReadingMnemonic}}<h3>Reading mnemonic</h3><div class="notes">{{ReadingMnemonic}}</div>{{/ReadingMnemonic}}
                {{#ContextSentences}}<h3>Context</h3>{{ContextSentences}}{{/ContextSentences}}
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.type-answer { margin: 16px auto; max-width: 520px; font-size: 28px; }
"""
            + READING_AUDIO_CSS
            + WK_MNEMONIC_CSS,
            "core_item",
        ),
    )


def _attach_schedule_specs(
    deck: genanki.Deck,
    specs: Dict[str, WkCardScheduleSpec],
    *,
    bootstrap_scheduling: bool,
) -> None:
    if bootstrap_scheduling and specs:
        deck.wk_schedule_specs = specs


def _schedule_spec_for_subject(
    kind: str,
    subject: dict,
    assignment_index: Dict[int, dict],
    *,
    bootstrap_scheduling: bool,
    suspend_unstarted: bool,
) -> Optional[WkCardScheduleSpec]:
    if not bootstrap_scheduling:
        return None
    guid = stable_guid(kind, subject["id"])
    assignment = assignment_index.get(subject["id"])
    return schedule_spec_for_assignment(
        guid,
        assignment,
        suspend_unstarted=suspend_unstarted,
        suspend_locked=True,
    )


def add_core_item_note(
    deck: genanki.Deck,
    model: WkModel,
    subject: dict,
    assignment_index: Dict[int, dict],
    kind: str,
    *,
    reading_audio_field: str = "",
    priority_entry: Optional[SubjectPriority] = None,
    include_grammar_role_tags: bool = False,
    radical_index: Optional[Mapping[int, dict]] = None,
    subject_by_id: Optional[Mapping[int, dict]] = None,
    vocab_by_characters: Optional[Mapping[str, dict]] = None,
    kanji_by_characters: Optional[Mapping[str, dict]] = None,
) -> str:
    data = subject["data"]
    expr = data.get("characters") or ""
    reading = "、".join(primary_readings(subject)) or ""
    is_kanji, is_vocabulary = subject_type_flags(subject)
    guid = stable_guid(kind, subject["id"])
    note = genanki.Note(
        model=model,
        fields=[
            guid,
            html.escape(expr),
            html.escape(reading),
            reading_audio_field,
            html.escape("; ".join(primary_meanings(subject))),
            meaning_mnemonic_html(
                subject,
                radical_index,
                subject_by_id=subject_by_id,
            ),
            reading_mnemonic_html(
                subject,
                subject_by_id=subject_by_id,
                vocab_by_characters=vocab_by_characters,
                kanji_by_characters=kanji_by_characters,
            ),
            html.escape(subject_type_label(subject)),
            readings_detail_html(subject),
            core_meta_html(subject, assignment_index),
            context_sentences_html(subject),
            subject_style_class(subject),
            is_kanji,
            is_vocabulary,
            str(subject["id"]),
            format_prerequisite_ids(subject),
        ],
        tags=[
            "wanikani",
            CORE_TAG,
            subject.get("object") or "item",
            f"wk-level-{data.get('level', 0)}",
            *(priority_tags(
                priority_entry,
                subject_object=subject.get("object") or "",
                include_grammar_role_tags=include_grammar_role_tags,
            ) if priority_entry is not None else []),
        ],
        guid=guid,
    )
    deck.add_note(note)
    return guid


def build_core_radical_deck(
    radicals: Sequence[dict],
    assignment_index: Dict[int, dict],
    output_dir: Path,
    *,
    bootstrap_scheduling: bool = False,
    suspend_unstarted: bool = True,
    priority_index: Optional[Dict[int, SubjectPriority]] = None,
    include_grammar_role_tags: bool = False,
    kanji_items: Sequence[dict] = (),
) -> Tuple[Path, genanki.Deck]:
    from wk_decks import radical_display_html

    deck = genanki.Deck(DECK_IDS["core-radical"], DECK_NAMES["core-radical"])
    model = make_core_radical_model()
    media_names, media_paths = ensure_radical_media_files(radicals)
    deck.wk_media_files = media_paths
    schedule_specs: Dict[str, WkCardScheduleSpec] = {}
    kanji_by_characters = kanji_index_by_characters(kanji_items)

    for radical in sorted(
        radicals,
        key=lambda item: (
            (priority_index or {}).get(int(item["id"])).priority_score
            if (priority_index or {}).get(int(item["id"])) is not None
            else priority_score_fallback(item),
            item["data"].get("level", 999),
            radical_display(item),
        ),
    ):
        data = radical["data"]
        level = int(data.get("level") or 0)
        guid = stable_guid(CORE_RADICAL_KIND, radical["id"])
        priority_entry = (priority_index or {}).get(int(radical["id"]))
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                radical_display_html(radical, media_names),
                html.escape("; ".join(primary_meanings(radical))),
                str(level),
                str(radical["id"]),
                "",
                radical_description_html(radical, kanji_by_characters),
            ],
            tags=[
                "wanikani",
                CORE_TAG,
                "radical",
                f"wk-level-{level}",
                *(priority_tags(
                    priority_entry,
                    subject_object=radical.get("object") or "radical",
                    include_grammar_role_tags=include_grammar_role_tags,
                ) if priority_entry is not None else []),
            ],
            guid=guid,
        )
        deck.add_note(note)
        spec = _schedule_spec_for_subject(
            CORE_RADICAL_KIND,
            radical,
            assignment_index,
            bootstrap_scheduling=bootstrap_scheduling,
            suspend_unstarted=suspend_unstarted,
        )
        if spec is not None:
            schedule_specs[guid] = spec

    _attach_schedule_specs(deck, schedule_specs, bootstrap_scheduling=bootstrap_scheduling)
    out = output_dir / "wk_core_radicals.apkg"
    write_apkg(deck, out, patch_apkg_scheduling=bootstrap_scheduling)
    return out, deck


def _populate_core_item_deck(
    deck: genanki.Deck,
    model: WkModel,
    items: Sequence[dict],
    assignment_index: Dict[int, dict],
    output_dir: Path,
    *,
    bootstrap_scheduling: bool,
    suspend_unstarted: bool,
    reading_audio: bool,
    wk_voice: str,
    tts_voice: str,
    refresh_reading_audio: bool,
    tts_config: Optional["SentenceTtsConfig"] = None,
    priority_index: Optional[Dict[int, SubjectPriority]] = None,
    include_grammar_role_tags: bool = False,
    radical_index: Optional[Mapping[int, dict]] = None,
    subject_by_id: Optional[Mapping[int, dict]] = None,
    vocab_by_characters: Optional[Mapping[str, dict]] = None,
    kanji_by_characters: Optional[Mapping[str, dict]] = None,
) -> Dict[str, WkCardScheduleSpec]:
    schedule_specs: Dict[str, WkCardScheduleSpec] = {}
    media_files: List[str] = []
    media_dir = output_dir / WK_SHARED_MEDIA_SUBDIR
    audio_ok = 0

    if reading_audio:
        from wk_reading_audio import resolve_tts_config
        from wk_sentence_tts import format_sentence_tts_label

        config = resolve_tts_config(tts_config, tts_voice=tts_voice)
        print(
            f"Reading audio (vocab: WK {wk_voice}, kanji: {format_sentence_tts_label(config)})..."
        )

    progress = ReadingAudioProgressBar(len(items), label="Reading audio", enabled=reading_audio)

    for subject in items:
        audio_field = ""
        if reading_audio:
            audio_field, media_paths = prepare_reading_audio_field(
                subject,
                media_dir,
                wk_voice=wk_voice,
                tts_config=tts_config,
                tts_voice=tts_voice,
                refresh=refresh_reading_audio,
            )
            if media_paths:
                media_files.extend(media_paths)
                audio_ok += 1
            progress.advance()

        guid = add_core_item_note(
            deck,
            model,
            subject,
            assignment_index,
            CORE_ITEM_KIND,
            reading_audio_field=audio_field,
            priority_entry=(priority_index or {}).get(int(subject["id"])),
            include_grammar_role_tags=include_grammar_role_tags,
            radical_index=radical_index,
            subject_by_id=subject_by_id,
            vocab_by_characters=vocab_by_characters,
            kanji_by_characters=kanji_by_characters,
        )
        spec = _schedule_spec_for_subject(
            CORE_ITEM_KIND,
            subject,
            assignment_index,
            bootstrap_scheduling=bootstrap_scheduling,
            suspend_unstarted=suspend_unstarted,
        )
        if spec is not None:
            schedule_specs[guid] = spec

    if reading_audio:
        progress.finish(ok_count=audio_ok)
    if media_files:
        existing = list(getattr(deck, "wk_media_files", []) or [])
        deck.wk_media_files = existing + media_files
    return schedule_specs


def build_core_kanji_deck(
    kanji_items: Sequence[dict],
    assignment_index: Dict[int, dict],
    output_dir: Path,
    *,
    bootstrap_scheduling: bool = False,
    suspend_unstarted: bool = True,
    reading_audio: bool = True,
    wk_voice: str = DEFAULT_WK_READING_VOICE,
    tts_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    tts_config: Optional["SentenceTtsConfig"] = None,
    refresh_reading_audio: bool = False,
    priority_index: Optional[Dict[int, SubjectPriority]] = None,
    include_grammar_role_tags: bool = False,
    radical_index: Optional[Mapping[int, dict]] = None,
    subject_by_id: Optional[Mapping[int, dict]] = None,
    vocab_by_characters: Optional[Mapping[str, dict]] = None,
    kanji_by_characters: Optional[Mapping[str, dict]] = None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["core-kanji"], DECK_NAMES["core-kanji"])
    model = make_core_item_model()
    sorted_items = sorted(
        kanji_items,
        key=lambda item: (
            (priority_index or {}).get(int(item["id"])).priority_score
            if (priority_index or {}).get(int(item["id"])) is not None
            else priority_score_fallback(item),
            item["data"].get("level", 999),
            item["data"].get("characters") or "",
        ),
    )
    schedule_specs = _populate_core_item_deck(
        deck,
        model,
        sorted_items,
        assignment_index,
        output_dir,
        bootstrap_scheduling=bootstrap_scheduling,
        suspend_unstarted=suspend_unstarted,
        reading_audio=reading_audio,
        wk_voice=wk_voice,
        tts_voice=tts_voice,
        tts_config=tts_config,
        refresh_reading_audio=refresh_reading_audio,
        priority_index=priority_index,
        include_grammar_role_tags=include_grammar_role_tags,
        radical_index=radical_index,
        subject_by_id=subject_by_id,
        vocab_by_characters=vocab_by_characters,
        kanji_by_characters=kanji_by_characters,
    )
    _attach_schedule_specs(deck, schedule_specs, bootstrap_scheduling=bootstrap_scheduling)
    out = output_dir / "wk_core_kanji.apkg"
    write_apkg(
        deck,
        out,
        media_files=getattr(deck, "wk_media_files", None),
        patch_apkg_scheduling=bootstrap_scheduling,
    )
    return out, deck


def build_core_vocab_deck(
    vocab_items: Sequence[dict],
    assignment_index: Dict[int, dict],
    output_dir: Path,
    *,
    bootstrap_scheduling: bool = False,
    suspend_unstarted: bool = True,
    reading_audio: bool = True,
    wk_voice: str = DEFAULT_WK_READING_VOICE,
    tts_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    tts_config: Optional["SentenceTtsConfig"] = None,
    refresh_reading_audio: bool = False,
    priority_index: Optional[Dict[int, SubjectPriority]] = None,
    include_grammar_role_tags: bool = False,
    radical_index: Optional[Mapping[int, dict]] = None,
    subject_by_id: Optional[Mapping[int, dict]] = None,
    vocab_by_characters: Optional[Mapping[str, dict]] = None,
    kanji_by_characters: Optional[Mapping[str, dict]] = None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["core-vocabulary"], DECK_NAMES["core-vocabulary"])
    model = make_core_item_model()
    sorted_items = sorted(
        vocab_items,
        key=lambda item: (
            (priority_index or {}).get(int(item["id"])).priority_score
            if (priority_index or {}).get(int(item["id"])) is not None
            else priority_score_fallback(item),
            item["data"].get("level", 999),
            item["data"].get("characters") or "",
        ),
    )
    schedule_specs = _populate_core_item_deck(
        deck,
        model,
        sorted_items,
        assignment_index,
        output_dir,
        bootstrap_scheduling=bootstrap_scheduling,
        suspend_unstarted=suspend_unstarted,
        reading_audio=reading_audio,
        wk_voice=wk_voice,
        tts_voice=tts_voice,
        tts_config=tts_config,
        refresh_reading_audio=refresh_reading_audio,
        priority_index=priority_index,
        include_grammar_role_tags=include_grammar_role_tags,
        radical_index=radical_index,
        subject_by_id=subject_by_id,
        vocab_by_characters=vocab_by_characters,
        kanji_by_characters=kanji_by_characters,
    )
    _attach_schedule_specs(deck, schedule_specs, bootstrap_scheduling=bootstrap_scheduling)
    out = output_dir / "wk_core_vocabulary.apkg"
    write_apkg(
        deck,
        out,
        media_files=getattr(deck, "wk_media_files", None),
        patch_apkg_scheduling=bootstrap_scheduling,
    )
    return out, deck
