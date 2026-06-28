"""
Pure unlock/maturity logic for wk_unlock (testable without Anki runtime).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

ANKI_QUEUE_SUSPENDED = -1

DEFAULT_MATURE_MIN_INTERVAL_DAYS = 7  # WaniKani Guru I (srs_stage 5) — “guru’d at least once”
DEFAULT_BURNED_INTERVAL_DAYS = 365

WK_LOCKED_TAG = "wk-locked"
WK_DEPS_MET_TAG = "wk-deps-met"
WK_MATURE_TAG = "wk-mature"
WK_CORE_TAG = "wk-core"


@dataclass(frozen=True)
class WkUnlockConfig:
    mature_min_interval_days: int = DEFAULT_MATURE_MIN_INTERVAL_DAYS
    mature_require_all_card_types: bool = True
    burned_interval_days: int = DEFAULT_BURNED_INTERVAL_DAYS


@dataclass(frozen=True)
class CardState:
    ivl: int
    queue: int


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
        if waiting_on_deps and prerequisites_met(note.prerequisite_ids, mature_ids):
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
    mature_subject_ids: Set[int],
) -> List[UnlockAction]:
    """Unsuspend supplementary notes when their linked WkSubjectId is mature in core."""
    actions: List[UnlockAction] = []
    for note in notes:
        if WK_CORE_TAG in note.tags:
            continue
        if note.wk_subject_id is None:
            continue
        tag_set = set(note.tags)
        waiting_on_core = WK_LOCKED_TAG in tag_set or any(
            card.queue == ANKI_QUEUE_SUSPENDED for card in note.cards
        )
        if not waiting_on_core:
            continue
        if note.wk_subject_id not in mature_subject_ids:
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
