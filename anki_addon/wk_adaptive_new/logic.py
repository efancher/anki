"""
Pure logic for WK adaptive new-card limits.

Review load high → fewer new cards. Remaining new budget fills in priority order:
radicals → kanji → vocabulary → supplementary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


DEFAULT_DAILY_WORKLOAD_TARGET = 200
DEFAULT_MAX_NEW_TOTAL = 15
DEFAULT_SUPPLEMENTARY_MAX_NEW = 5
DEFAULT_BASE_PRESET_NAME = "WK FSRS"
PRESET_NAME_PREFIX = "WK FSRS · New ·"

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
