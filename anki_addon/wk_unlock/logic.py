"""
Pure unlock/maturity logic for wk_unlock (testable without Anki runtime).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

ANKI_QUEUE_SUSPENDED = -1

DEFAULT_MATURE_MIN_INTERVAL_DAYS = 7  # WaniKani Guru I (srs_stage 5) — “guru’d at least once”
DEFAULT_BURNED_INTERVAL_DAYS = 365
# When True: unlock Core Vocabulary without Core Kanji maturity; never unlock
# Core Radicals/Kanji (those decks stay suspended under retire mode).
DEFAULT_RETIRE_KANJI_RADICAL_PHONETIC_STUDY = True

WK_LOCKED_TAG = "wk-locked"
WK_DEPS_MET_TAG = "wk-deps-met"
WK_MATURE_TAG = "wk-mature"
WK_CORE_TAG = "wk-core"
PHONETIC_FAMILY_TAG = "phonetic-family"

# Conjugation / type drills unlock from Core Vocabulary maturity (WkSubjectId),
# not from Kanji Meaning Anchor PrerequisiteIds.
VOCAB_GATED_SUPPLEMENTARY_TAGS = frozenset(
    {
        "conjugation-verb",
        "conjugation-adjective",
        "conjugation-reverse",
        "verb-type",
        "adjective-type",
        "satori-conjugation",
    }
)

SUBJECT_KIND_VOCABULARY = "vocabulary"
SUBJECT_KIND_KANJI = "kanji"
SUBJECT_KIND_RADICAL = "radical"


@dataclass(frozen=True)
class WkUnlockConfig:
    mature_min_interval_days: int = DEFAULT_MATURE_MIN_INTERVAL_DAYS
    mature_require_all_card_types: bool = True
    burned_interval_days: int = DEFAULT_BURNED_INTERVAL_DAYS
    retire_kanji_radical_phonetic_study: bool = DEFAULT_RETIRE_KANJI_RADICAL_PHONETIC_STUDY


@dataclass(frozen=True)
class CardState:
    ivl: int
    queue: int
    reps: int = 0


@dataclass(frozen=True)
class NoteUnlockState:
    note_id: int
    wk_subject_id: Optional[int]
    prerequisite_ids: Tuple[int, ...]
    tags: Tuple[str, ...]
    cards: Tuple[CardState, ...]


@dataclass(frozen=True)
class UnlockAction:
    note_id: int
    unsuspend: bool
    add_tags: Tuple[str, ...]
    remove_tags: Tuple[str, ...]


def parse_prerequisite_ids(value: Optional[str]) -> Tuple[int, ...]:
    if not value:
        return ()
    ids: List[int] = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return tuple(ids)


def card_meets_maturity(
    card: CardState,
    *,
    config: WkUnlockConfig,
) -> bool:
    if card.queue == ANKI_QUEUE_SUSPENDED:
        return False
    if card.ivl >= config.burned_interval_days:
        return True
    return card.ivl >= config.mature_min_interval_days


def subject_is_mature(cards: Sequence[CardState], *, config: WkUnlockConfig) -> bool:
    active = [card for card in cards if card.queue != ANKI_QUEUE_SUSPENDED]
    if not active:
        return False
    if config.mature_require_all_card_types:
        return all(card_meets_maturity(card, config=config) for card in active)
    return any(card_meets_maturity(card, config=config) for card in active)


def build_mature_subject_ids(
    notes: Sequence[NoteUnlockState],
    *,
    config: WkUnlockConfig,
) -> Set[int]:
    mature: Set[int] = set()
    for note in notes:
        if note.wk_subject_id is None:
            continue
        if subject_is_mature(note.cards, config=config):
            mature.add(note.wk_subject_id)
    return mature


def prerequisites_met(
    prerequisite_ids: Sequence[int],
    mature_subject_ids: Set[int],
) -> bool:
    if not prerequisite_ids:
        return True
    return all(prerequisite_id in mature_subject_ids for prerequisite_id in prerequisite_ids)


def any_prerequisites_met(
    prerequisite_ids: Sequence[int],
    subject_ids: Set[int],
) -> bool:
    if not prerequisite_ids or not subject_ids:
        return False
    return any(prerequisite_id in subject_ids for prerequisite_id in prerequisite_ids)


def core_subject_kind_from_tags(tags: Sequence[str]) -> Optional[str]:
    """Infer radical/kanji/vocabulary from note tags."""
    tag_set = {str(tag) for tag in tags}
    if SUBJECT_KIND_VOCABULARY in tag_set:
        return SUBJECT_KIND_VOCABULARY
    if SUBJECT_KIND_KANJI in tag_set:
        return SUBJECT_KIND_KANJI
    if SUBJECT_KIND_RADICAL in tag_set:
        return SUBJECT_KIND_RADICAL
    return None


def uses_core_vocab_unlock(tags: Sequence[str]) -> bool:
    """True for conjugation / verb·adj type notes gated by Core Vocabulary."""
    return bool(VOCAB_GATED_SUPPLEMENTARY_TAGS.intersection(tags))


def subject_reviewed_once(cards: Sequence[CardState]) -> bool:
    active = [card for card in cards if card.queue != ANKI_QUEUE_SUSPENDED]
    if not active:
        return False
    return any(card.reps > 0 for card in active)


def build_reviewed_once_subject_ids(notes: Sequence[NoteUnlockState]) -> Set[int]:
    reviewed: Set[int] = set()
    for note in notes:
        if note.wk_subject_id is None:
            continue
        if subject_reviewed_once(note.cards):
            reviewed.add(note.wk_subject_id)
    return reviewed


def unlock_actions_for_notes(
    notes: Sequence[NoteUnlockState],
    *,
    config: WkUnlockConfig,
    mature_subject_ids: Optional[Set[int]] = None,
) -> List[UnlockAction]:
    mature_ids = mature_subject_ids if mature_subject_ids is not None else build_mature_subject_ids(notes, config=config)
    actions: List[UnlockAction] = []

    for note in notes:
        if note.wk_subject_id is None:
            continue

        became_mature = subject_is_mature(note.cards, config=config)
        tag_set = set(note.tags)
        add_tags: List[str] = []
        remove_tags: List[str] = []
        unsuspend = False

        if became_mature and WK_MATURE_TAG not in tag_set:
            add_tags.append(WK_MATURE_TAG)

        waiting_on_deps = WK_LOCKED_TAG in tag_set or any(card.queue == ANKI_QUEUE_SUSPENDED for card in note.cards)
        kind = core_subject_kind_from_tags(note.tags)
        if config.retire_kanji_radical_phonetic_study:
            # Vocab unlocks without Core Kanji maturity; radicals/kanji stay suspended.
            if kind == SUBJECT_KIND_VOCABULARY and waiting_on_deps:
                unsuspend = True
                if WK_LOCKED_TAG in tag_set:
                    remove_tags.append(WK_LOCKED_TAG)
                if WK_DEPS_MET_TAG not in tag_set:
                    add_tags.append(WK_DEPS_MET_TAG)
        elif waiting_on_deps and prerequisites_met(note.prerequisite_ids, mature_ids):
            unsuspend = True
            if WK_LOCKED_TAG in tag_set:
                remove_tags.append(WK_LOCKED_TAG)
            if WK_DEPS_MET_TAG not in tag_set:
                add_tags.append(WK_DEPS_MET_TAG)

        if unsuspend or add_tags or remove_tags:
            actions.append(
                UnlockAction(
                    note_id=note.note_id,
                    unsuspend=unsuspend,
                    add_tags=tuple(add_tags),
                    remove_tags=tuple(remove_tags),
                )
            )

    return actions


def supplementary_unlock_actions_for_notes(
    notes: Sequence[NoteUnlockState],
    *,
    core_mature_subject_ids: Set[int],
    kanji_meaning_mature_subject_ids: Set[int],
    core_reviewed_once_subject_ids: Optional[Set[int]] = None,
) -> List[UnlockAction]:
    """Unsuspend supplementary notes when their unlock prereqs are mature.

    Phonetic-family notes unlock when any kanji in PrerequisiteIds has been reviewed
    once (reps > 0) in Kanji Meaning Anchor (or leftover core kanji).

    Conjugation / verb·adj type notes unlock when their linked ``WkSubjectId``
    vocabulary is Guru+ in Core Vocabulary (PrerequisiteIds kanji are ignored).

    Other notes with PrerequisiteIds unlock when those kanji are Guru+ in Kanji
    Meaning Anchor. Remaining supplementary notes unlock when WkSubjectId is mature
    in core.
    """
    reviewed_once_ids = core_reviewed_once_subject_ids or set()
    actions: List[UnlockAction] = []
    for note in notes:
        if WK_CORE_TAG in note.tags:
            continue
        if note.wk_subject_id is None:
            continue
        tag_set = set(note.tags)
        waiting_on_lock = WK_LOCKED_TAG in tag_set or any(
            card.queue == ANKI_QUEUE_SUSPENDED for card in note.cards
        )
        if not waiting_on_lock:
            continue
        if PHONETIC_FAMILY_TAG in tag_set and note.prerequisite_ids:
            deps_met = any_prerequisites_met(note.prerequisite_ids, reviewed_once_ids)
        elif uses_core_vocab_unlock(note.tags):
            deps_met = note.wk_subject_id in core_mature_subject_ids
        elif note.prerequisite_ids:
            deps_met = prerequisites_met(note.prerequisite_ids, kanji_meaning_mature_subject_ids)
        else:
            deps_met = note.wk_subject_id in core_mature_subject_ids
        if not deps_met:
            continue
        add_tags: List[str] = []
        remove_tags: List[str] = []
        if WK_LOCKED_TAG in tag_set:
            remove_tags.append(WK_LOCKED_TAG)
        if WK_DEPS_MET_TAG not in tag_set:
            add_tags.append(WK_DEPS_MET_TAG)
        actions.append(
            UnlockAction(
                note_id=note.note_id,
                unsuspend=True,
                add_tags=tuple(add_tags),
                remove_tags=tuple(remove_tags),
            )
        )
    return actions


def index_notes_by_subject_id(notes: Sequence[NoteUnlockState]) -> Dict[int, NoteUnlockState]:
    indexed: Dict[int, NoteUnlockState] = {}
    for note in notes:
        if note.wk_subject_id is not None:
            indexed[note.wk_subject_id] = note
    return indexed


@dataclass(frozen=True)
class MiningHintState:
    note_id: int
    wk_subject_id: Optional[int]
    prerequisite_ids: Tuple[int, ...]
    hint_stage: int


@dataclass(frozen=True)
class MiningHintUpdate:
    note_id: int
    hint_stage: str
    show_english: str
    show_kana: str
    show_jj_back: str


def mining_hint_display_flags(hint_stage: int) -> Tuple[str, str, str, str]:
    stage = max(0, min(2, int(hint_stage)))
    return (
        str(stage),
        "1" if stage == 0 else "",
        "1" if stage < 2 else "",
        "1" if stage >= 2 else "",
    )


def compute_mining_hint_stage(
    wk_subject_id: Optional[int],
    prerequisite_ids: Sequence[int],
    *,
    kanji_meaning_mature_subject_ids: Set[int],
    core_mature_subject_ids: Set[int],
) -> int:
    stage = 0
    if prerequisites_met(prerequisite_ids, kanji_meaning_mature_subject_ids):
        stage = 1
    if wk_subject_id is not None and wk_subject_id in core_mature_subject_ids:
        stage = 2
    return stage


def mining_hint_updates_for_notes(
    notes: Sequence[MiningHintState],
    *,
    kanji_meaning_mature_subject_ids: Set[int],
    core_mature_subject_ids: Set[int],
) -> List[MiningHintUpdate]:
    updates: List[MiningHintUpdate] = []
    for note in notes:
        new_stage = compute_mining_hint_stage(
            note.wk_subject_id,
            note.prerequisite_ids,
            kanji_meaning_mature_subject_ids=kanji_meaning_mature_subject_ids,
            core_mature_subject_ids=core_mature_subject_ids,
        )
        if new_stage == note.hint_stage:
            continue
        hint_stage, show_english, show_kana, show_jj_back = mining_hint_display_flags(new_stage)
        updates.append(
            MiningHintUpdate(
                note_id=note.note_id,
                hint_stage=hint_stage,
                show_english=show_english,
                show_kana=show_kana,
                show_jj_back=show_jj_back,
            )
        )
    return updates
