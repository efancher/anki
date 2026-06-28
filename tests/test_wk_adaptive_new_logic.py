"""Tests for wk_adaptive_new pure logic."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "anki_addon" / "wk_adaptive_new"))

from logic import (  # noqa: E402
    TierAvailability,
    allocate_new_by_priority,
    build_tier_plan,
    compute_new_budget,
    WkAdaptiveNewConfig,
)


class WkAdaptiveNewLogicTests(unittest.TestCase):
    def test_compute_new_budget_scales_with_review_load(self) -> None:
        self.assertEqual(compute_new_budget(0, daily_workload_target=200, max_new_total=15), 15)
        self.assertEqual(compute_new_budget(100, daily_workload_target=200, max_new_total=15), 7)
        self.assertEqual(compute_new_budget(200, daily_workload_target=200, max_new_total=15), 0)
        self.assertEqual(compute_new_budget(250, daily_workload_target=200, max_new_total=15), 0)

    def test_allocate_new_by_priority_fills_radicals_first(self) -> None:
        tiers = (
            TierAvailability("Radicals", "Radicals", available_new=10),
            TierAvailability("Kanji", "Kanji", available_new=10),
            TierAvailability("Vocab", "Vocabulary", available_new=10),
        )
        allocations = allocate_new_by_priority(12, tiers)
        self.assertEqual(allocations["Radicals"], 10)
        self.assertEqual(allocations["Kanji"], 2)
        self.assertEqual(allocations["Vocab"], 0)

    def test_allocate_new_by_priority_caps_supplementary(self) -> None:
        tiers = (
            TierAvailability("Radicals", "Radicals", available_new=0),
            TierAvailability("Kanji", "Kanji", available_new=0),
            TierAvailability("Vocab", "Vocabulary", available_new=0),
            TierAvailability("__supplementary__", "Supplementary", available_new=20),
        )
        allocations = allocate_new_by_priority(15, tiers, supplementary_max_new=5)
        self.assertEqual(allocations["__supplementary__"], 5)

    def test_build_tier_plan_end_to_end(self) -> None:
        config = WkAdaptiveNewConfig(max_new_total=10)
        tiers = (
            TierAvailability("Radicals", "Radicals", available_new=4),
            TierAvailability("Kanji", "Kanji", available_new=4),
            TierAvailability("Vocab", "Vocabulary", available_new=4),
        )
        budget, allocations = build_tier_plan(100, tiers, config=config)
        self.assertEqual(budget, 5)
        self.assertEqual(allocations["Radicals"], 4)
        self.assertEqual(allocations["Kanji"], 1)
        self.assertEqual(allocations["Vocab"], 0)


if __name__ == "__main__":
    unittest.main()
