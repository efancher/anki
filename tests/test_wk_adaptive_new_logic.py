"""Tests for wk_adaptive_new pure logic."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGIC_PATH = REPO_ROOT / "anki_addon" / "wk_adaptive_new" / "logic.py"


def _load_logic_module():
    spec = importlib.util.spec_from_file_location("wk_adaptive_new_logic", LOGIC_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wk_adaptive_new_logic"] = module
    spec.loader.exec_module(module)
    return module


logic = _load_logic_module()
TierAvailability = logic.TierAvailability
allocate_new_by_priority = logic.allocate_new_by_priority
build_tier_plan = logic.build_tier_plan
compute_new_budget = logic.compute_new_budget
WkAdaptiveNewConfig = logic.WkAdaptiveNewConfig


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
