"""
Runtime Tae Kim grammar-track sync (testable without Anki).

Applies tk-grammar-vocab / tk-grammar-prereq tags from wk_tae_kim_track_map.json
based on profile config (current lesson + ahead prereq lessons).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

TK_GRAMMAR_VOCAB_TAG = "tk-grammar-vocab"
TK_GRAMMAR_PREREQ_TAG = "tk-grammar-prereq"
WK_CORE_TAG = "wk-core"

DEFAULT_AHEAD_PREREQ_LESSONS = 1


@dataclass(frozen=True)
class TaeKimTrackConfig:
    max_tae_kim_lesson: str
    ahead_prereq_lessons: int = DEFAULT_AHEAD_PREREQ_LESSONS
    auto_run_on_load: bool = True
    auto_update_filtered_decks: bool = True


@dataclass(frozen=True)
class CoreNoteTrackState:
    note_id: int
    wk_subject_id: Optional[int]
    tags: Tuple[str, ...]


@dataclass(frozen=True)
class TrackTagAction:
    note_id: int
    add_tags: Tuple[str, ...]
    remove_tags: Tuple[str, ...]


def parse_track_config(payload: Mapping[str, object]) -> Optional[TaeKimTrackConfig]:
    cap = payload.get("max_tae_kim_lesson")
    if not cap or not str(cap).strip():
        return None
    return TaeKimTrackConfig(
        max_tae_kim_lesson=str(cap).strip(),
        ahead_prereq_lessons=max(0, int(payload.get("ahead_prereq_lessons", DEFAULT_AHEAD_PREREQ_LESSONS))),
        auto_run_on_load=bool(payload.get("auto_run_on_load", True)),
        auto_update_filtered_decks=bool(payload.get("auto_update_filtered_decks", True)),
    )


def active_and_ahead_lesson_slugs(
    track_map: Mapping[str, object],
    config: TaeKimTrackConfig,
) -> Tuple[List[str], List[str]]:
    reading_lessons = list(track_map.get("reading_lessons") or [])
    if not reading_lessons:
        return [], []
    cap = config.max_tae_kim_lesson
    cap_index = -1
    for index, slug in enumerate(reading_lessons):
        if slug == cap:
            cap_index = index
            break
    if cap_index < 0:
        return [], []
    active = reading_lessons[: cap_index + 1]
    ahead = reading_lessons[
        cap_index + 1 : cap_index + 1 + config.ahead_prereq_lessons
    ]
    return active, ahead


def grammar_role_for_subject(
    subject_id: int,
    track_map: Mapping[str, object],
    active_lessons: Sequence[str],
    ahead_lessons: Sequence[str],
) -> Tuple[bool, bool]:
    """Return (is_grammar_vocab, is_grammar_prereq) for a WkSubjectId."""
    lessons = track_map.get("lessons") or {}
    if not isinstance(lessons, dict):
        return False, False

    is_vocab = False
    is_prereq = False
    for slug in active_lessons:
        lesson = lessons.get(slug) or {}
        direct = set(lesson.get("direct_subject_ids") or [])
        prereq = set(lesson.get("prereq_subject_ids") or [])
        if subject_id in direct:
            is_vocab = True
        if subject_id in prereq:
            is_prereq = True
    for slug in ahead_lessons:
        lesson = lessons.get(slug) or {}
        prereq = set(lesson.get("prereq_subject_ids") or [])
        if subject_id in prereq:
            is_prereq = True
    if is_vocab:
        is_prereq = False
    return is_vocab, is_prereq


def track_tag_actions_for_notes(
    notes: Sequence[CoreNoteTrackState],
    track_map: Mapping[str, object],
    config: TaeKimTrackConfig,
) -> List[TrackTagAction]:
    active, ahead = active_and_ahead_lesson_slugs(track_map, config)
    if not active:
        return []
    actions: List[TrackTagAction] = []
    for note in notes:
        if WK_CORE_TAG not in note.tags or note.wk_subject_id is None:
            continue
        tag_set = set(note.tags)
        want_vocab, want_prereq = grammar_role_for_subject(
            note.wk_subject_id,
            track_map,
            active,
            ahead,
        )
        add: List[str] = []
        remove: List[str] = []
        if want_vocab and TK_GRAMMAR_VOCAB_TAG not in tag_set:
            add.append(TK_GRAMMAR_VOCAB_TAG)
        if not want_vocab and TK_GRAMMAR_VOCAB_TAG in tag_set:
            remove.append(TK_GRAMMAR_VOCAB_TAG)
        if want_prereq and TK_GRAMMAR_PREREQ_TAG not in tag_set:
            add.append(TK_GRAMMAR_PREREQ_TAG)
        if not want_prereq and TK_GRAMMAR_PREREQ_TAG in tag_set:
            remove.append(TK_GRAMMAR_PREREQ_TAG)
        if add or remove:
            actions.append(
                TrackTagAction(
                    note_id=note.note_id,
                    add_tags=tuple(add),
                    remove_tags=tuple(remove),
                )
            )
    return actions


def lesson_tag_for_slug(slug: str, *, chapter: str = "basic") -> str:
    return f"tk-lesson-{chapter}-{slug}"


def current_lesson_filtered_searches(
    lesson_slug: str,
    *,
    grammar_deck: str = "Japanese Grammar Context",
    exercises_deck: str = "Japanese Grammar Exercises",
    due_or_new: str = "(is:due OR is:new)",
    not_suspended: str = "-is:suspended",
) -> Dict[str, str]:
    lesson_tag = lesson_tag_for_slug(lesson_slug)
    return {
        "WK::Grammar · Current Tae Kim lesson": (
            f'deck:"{grammar_deck}" tag:{lesson_tag} {due_or_new} {not_suspended}'
        ),
        "WK::Grammar Exercises · Current Tae Kim lesson": (
            f'deck:"{exercises_deck}" tag:tae-kim-exercise tag:{lesson_tag} '
            f"{due_or_new} {not_suspended}"
        ),
    }


def bump_lesson_slug(
    track_map: Mapping[str, object],
    current_slug: str,
) -> Optional[str]:
    reading_lessons = list(track_map.get("reading_lessons") or [])
    try:
        index = reading_lessons.index(current_slug)
    except ValueError:
        return None
    if index + 1 >= len(reading_lessons):
        return None
    return reading_lessons[index + 1]
