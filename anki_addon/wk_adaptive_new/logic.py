"""
Pure logic for WK adaptive new-card limits.

Review load high → fewer new cards. Remaining new budget fills in priority order:
radicals → kanji → vocabulary → supplementary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Mapping, Optional, Sequence, Set, Tuple


DEFAULT_DAILY_WORKLOAD_TARGET = 200
DEFAULT_MAX_NEW_TOTAL = 15
DEFAULT_SUPPLEMENTARY_MAX_NEW = 5
DEFAULT_BASE_PRESET_NAME = "WK FSRS"
PRESET_NAME_PREFIX = "WK FSRS · New ·"

# Immersion-driven new-card priority: subjects mined from immersion (Satori)
# and their prerequisite closure lead the new queue, ahead of the JLPT/level
# baseline ordering. Tag applied to Satori notes by satori_decks.py.
DEFAULT_IMMERSION_PRIORITY_ENABLED = True
DEFAULT_IMMERSION_TAG = "satori-mining"
DEFAULT_IMMERSION_TAGS = ("satori-mining", "shadowing-mining")
# Also unlock (unsuspend) the immersion closure so mined words + prereqs can
# actually enter the new queue, not just get reordered within already-unlocked
# cards. Paced by each tier's new/day limit, so this does not flood reviews.
DEFAULT_IMMERSION_UNSUSPEND_ENABLED = True

# Sort rank for the immersion-first grouping (lower = introduced earlier).
IMMERSION_RANK_LEAD = 0
IMMERSION_RANK_REST = 1
# Fallback baseline score when a subject is absent from wk_study_priority.json.
UNRANKED_BASELINE_SCORE = 999_999_999

CORE_RADICALS_DECK = "WaniKani Core · Radicals"
CORE_KANJI_DECK = "WaniKani Core · Kanji"
CORE_VOCABULARY_DECK = "WaniKani Core · Vocabulary"

DEFAULT_CORE_TIERS = (
    CORE_RADICALS_DECK,
    CORE_KANJI_DECK,
    CORE_VOCABULARY_DECK,
)


@dataclass(frozen=True)
class WkAdaptiveNewConfig:
    daily_workload_target: int = DEFAULT_DAILY_WORKLOAD_TARGET
    max_new_total: int = DEFAULT_MAX_NEW_TOTAL
    supplementary_max_new: int = DEFAULT_SUPPLEMENTARY_MAX_NEW
    base_preset_name: str = DEFAULT_BASE_PRESET_NAME
    review_count_scope: str = "tag:wk-core"
    core_tiers: Sequence[str] = field(default_factory=lambda: DEFAULT_CORE_TIERS)
    auto_run_on_load: bool = True
    immersion_priority_enabled: bool = DEFAULT_IMMERSION_PRIORITY_ENABLED
    # Legacy single-tag field kept for backward-compatible configs.
    immersion_tag: str = DEFAULT_IMMERSION_TAG
    # Preferred multi-source seed tags (Satori + Shadowing by default).
    immersion_tags: Sequence[str] = field(default_factory=lambda: DEFAULT_IMMERSION_TAGS)
    immersion_unsuspend: bool = DEFAULT_IMMERSION_UNSUSPEND_ENABLED


def effective_immersion_tags(config: WkAdaptiveNewConfig) -> Tuple[str, ...]:
    """Resolve immersion seed tags from list and/or legacy scalar config."""
    tags = [str(tag).strip() for tag in (config.immersion_tags or ()) if str(tag).strip()]
    if tags:
        # Preserve order while uniquifying.
        seen = set()
        ordered: List[str] = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                ordered.append(tag)
        return tuple(ordered)
    legacy = str(config.immersion_tag or "").strip()
    return (legacy,) if legacy else ()


@dataclass(frozen=True)
class TierAvailability:
    deck_name: str
    preset_suffix: str
    available_new: int


def preset_name_for_suffix(base_preset_name: str, suffix: str) -> str:
    return f"{PRESET_NAME_PREFIX}{suffix}"


def compute_new_budget(
    review_load: int,
    *,
    daily_workload_target: int = DEFAULT_DAILY_WORKLOAD_TARGET,
    max_new_total: int = DEFAULT_MAX_NEW_TOTAL,
) -> int:
    """Scale new-card budget down as due review load approaches the daily workload target."""
    if daily_workload_target <= 0:
        return 0
    if review_load >= daily_workload_target:
        return 0
    scaled = int(max_new_total * (daily_workload_target - review_load) / daily_workload_target)
    return max(0, min(max_new_total, scaled))


def allocate_new_by_priority(
    budget: int,
    tiers: Sequence[TierAvailability],
    *,
    supplementary_max_new: int = DEFAULT_SUPPLEMENTARY_MAX_NEW,
) -> Mapping[str, int]:
    """Fill new slots in tier order; supplementary tier is capped separately."""
    remaining = max(0, budget)
    allocations: dict[str, int] = {}

    for tier in tiers:
        if tier.preset_suffix == "Supplementary":
            cap = min(remaining, supplementary_max_new, tier.available_new)
        else:
            cap = min(remaining, tier.available_new)
        allocations[tier.deck_name] = cap
        remaining -= cap

    return allocations


def build_tier_plan(
    review_load: int,
    tier_availability: Sequence[TierAvailability],
    *,
    config: WkAdaptiveNewConfig,
) -> tuple[int, Mapping[str, int]]:
    budget = compute_new_budget(
        review_load,
        daily_workload_target=config.daily_workload_target,
        max_new_total=config.max_new_total,
    )
    allocations = allocate_new_by_priority(
        budget,
        tier_availability,
        supplementary_max_new=config.supplementary_max_new,
    )
    return budget, allocations


def parse_subject_ids(text: str) -> List[int]:
    """Parse a comma/space-separated WkSubjectId or PrerequisiteIds field into ints."""
    if not text:
        return []
    ids: List[int] = []
    for token in text.replace(",", " ").split():
        try:
            ids.append(int(token))
        except ValueError:
            continue
    return ids


def expand_immersion_closure(
    seed_ids: Set[int],
    prereq_map: Mapping[int, Sequence[int]],
) -> Set[int]:
    """Expand a seed of subject ids over prerequisite edges (vocab → kanji → radicals).

    ``prereq_map`` maps a subject id to its direct prerequisite ids (from each core
    note's ``PrerequisiteIds``). Returns the transitive closure including the seed.
    """
    closure: Set[int] = set(seed_ids)
    frontier: List[int] = list(seed_ids)
    while frontier:
        subject_id = frontier.pop()
        for prereq_id in prereq_map.get(subject_id, ()):  # type: ignore[arg-type]
            if prereq_id not in closure:
                closure.add(prereq_id)
                frontier.append(prereq_id)
    return closure


def new_card_sort_key(
    subject_id: Optional[int],
    baseline_score: int,
    card_id: int,
    immersion_ids: Set[int],
) -> Tuple[int, int, int]:
    """Immersion subjects (and prereqs) lead, then baseline JLPT/level score, then id."""
    is_immersion = (
        IMMERSION_RANK_LEAD
        if subject_id is not None and subject_id in immersion_ids
        else IMMERSION_RANK_REST
    )
    return (is_immersion, baseline_score, card_id)


def immersion_cards_to_unsuspend(
    entries: Sequence[Tuple[Optional[int], int]],
    immersion_ids: Set[int],
) -> List[int]:
    """Pick suspended-new card ids whose subject is in the immersion closure.

    ``entries`` is ``(subject_id, card_id)`` for each currently suspended new
    core card. Cards without a subject id (or outside the closure) are left
    suspended so unrelated locked cards are untouched.
    """
    if not immersion_ids:
        return []
    return [
        card_id
        for subject_id, card_id in entries
        if subject_id is not None and subject_id in immersion_ids
    ]


def sorted_new_card_ids(
    entries: Sequence[Tuple[Optional[int], int, int]],
    immersion_ids: Set[int],
) -> List[int]:
    """Order new-card entries ``(subject_id, baseline_score, card_id)`` for the queue.

    Immersion-linked subjects and their prerequisites come first (ordered by the
    baseline score, so radical→kanji→vocab and JLPT/level order is preserved within
    each group), followed by everything else by baseline score.
    """
    ordered = sorted(
        entries,
        key=lambda item: new_card_sort_key(item[0], item[1], item[2], immersion_ids),
    )
    return [card_id for _subject_id, _score, card_id in ordered]
