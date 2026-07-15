"""Tests for immersion-driven new-card priority in wk_adaptive_new logic."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGIC_PATH = REPO_ROOT / "anki_addon" / "wk_adaptive_new" / "logic.py"


def _load_logic_module():
    spec = importlib.util.spec_from_file_location("wk_adaptive_new_logic_immersion", LOGIC_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wk_adaptive_new_logic_immersion"] = module
    spec.loader.exec_module(module)
    return module


logic = _load_logic_module()
WkAdaptiveNewConfig = logic.WkAdaptiveNewConfig
expand_immersion_closure = logic.expand_immersion_closure
immersion_cards_to_unsuspend = logic.immersion_cards_to_unsuspend
parse_subject_ids = logic.parse_subject_ids
sorted_new_card_ids = logic.sorted_new_card_ids


class ParseSubjectIdsTests(unittest.TestCase):
    def test_parses_comma_and_space_separated(self) -> None:
        self.assertEqual(parse_subject_ids("10, 20 30"), [10, 20, 30])

    def test_skips_non_numeric_and_empty(self) -> None:
        self.assertEqual(parse_subject_ids(""), [])
        self.assertEqual(parse_subject_ids("10,,x,20"), [10, 20])


class ExpandImmersionClosureTests(unittest.TestCase):
    def test_vocab_expands_to_kanji_and_radicals(self) -> None:
        # vocab 900 → kanji 400 → radical 100 (+ radical 101)
        prereq_map = {900: [400], 400: [100, 101]}
        closure = expand_immersion_closure({900}, prereq_map)
        self.assertEqual(closure, {900, 400, 100, 101})

    def test_seed_kept_when_no_prereqs(self) -> None:
        self.assertEqual(expand_immersion_closure({5}, {}), {5})

    def test_handles_cycles_without_infinite_loop(self) -> None:
        prereq_map = {1: [2], 2: [1]}
        self.assertEqual(expand_immersion_closure({1}, prereq_map), {1, 2})

    def test_multiple_seeds_union(self) -> None:
        prereq_map = {900: [400], 901: [401], 400: [100], 401: [100]}
        closure = expand_immersion_closure({900, 901}, prereq_map)
        self.assertEqual(closure, {900, 901, 400, 401, 100})


class SortedNewCardIdsTests(unittest.TestCase):
    def test_immersion_subjects_lead_by_baseline_score(self) -> None:
        # entries: (subject_id, baseline_score, card_id)
        entries = [
            (10, 50_000, 1001),   # non-immersion, low score
            (400, 30_000, 1002),  # immersion (kanji prereq), higher score
            (900, 40_000, 1003),  # immersion (vocab)
            (11, 20_000, 1004),   # non-immersion, lowest score
        ]
        immersion_ids = {900, 400}
        order = sorted_new_card_ids(entries, immersion_ids)
        # Immersion first (400 before 900 by baseline score), then non-immersion by score.
        self.assertEqual(order, [1002, 1003, 1004, 1001])

    def test_none_subject_id_is_never_immersion(self) -> None:
        entries = [
            (None, 10, 2001),
            (900, 999_999_999, 2002),
        ]
        order = sorted_new_card_ids(entries, {900})
        self.assertEqual(order, [2002, 2001])

    def test_empty_immersion_set_falls_back_to_baseline(self) -> None:
        entries = [
            (10, 50_000, 1),
            (11, 20_000, 2),
        ]
        self.assertEqual(sorted_new_card_ids(entries, set()), [2, 1])


class ImmersionCardsToUnsuspendTests(unittest.TestCase):
    def test_selects_only_closure_subjects(self) -> None:
        # entries: (subject_id, card_id) for suspended new core cards
        entries = [
            (400, 3001),   # immersion → unsuspend
            (900, 3002),   # immersion → unsuspend
            (77, 3003),    # unrelated locked card → stay suspended
            (None, 3004),  # no subject → stay suspended
        ]
        picked = immersion_cards_to_unsuspend(entries, {900, 400})
        self.assertEqual(picked, [3001, 3002])

    def test_empty_closure_unsuspends_nothing(self) -> None:
        entries = [(400, 1), (900, 2)]
        self.assertEqual(immersion_cards_to_unsuspend(entries, set()), [])


class ImmersionConfigDefaultsTests(unittest.TestCase):
    def test_defaults_enabled_with_satori_tag(self) -> None:
        config = WkAdaptiveNewConfig()
        self.assertTrue(config.immersion_priority_enabled)
        self.assertEqual(config.immersion_tag, "satori-mining")
        self.assertTrue(config.immersion_unsuspend)


if __name__ == "__main__":
    unittest.main()
