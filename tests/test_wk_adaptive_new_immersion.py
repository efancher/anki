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
ranked_immersion_closure = logic.ranked_immersion_closure
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

    def test_satori_rank_leads_shadowing_despite_baseline_score(self) -> None:
        entries = [
            (100, 50_000, 1),  # Satori
            (200, 10_000, 2),  # Shadowing has a better baseline
            (300, 1_000, 3),   # Non-immersion
        ]
        self.assertEqual(
            sorted_new_card_ids(entries, {100: 0, 200: 1}),
            [1, 2, 3],
        )


class RankedImmersionClosureTests(unittest.TestCase):
    def test_tag_order_ranks_closures_and_shared_prereqs_take_best_rank(self) -> None:
        ranks = ranked_immersion_closure(
            {
                "satori-mining": {900},
                "shadowing-mining": {901},
            },
            {
                900: [400],
                901: [400, 401],
                400: [100],
                401: [101],
            },
            ("satori-mining", "shadowing-mining"),
        )
        self.assertEqual(ranks[900], 0)
        self.assertEqual(ranks[400], 0)
        self.assertEqual(ranks[100], 0)
        self.assertEqual(ranks[901], 1)
        self.assertEqual(ranks[401], 1)
        self.assertEqual(ranks[101], 1)


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
    def test_defaults_enabled_with_satori_and_shadowing_tags(self) -> None:
        config = WkAdaptiveNewConfig()
        self.assertTrue(config.immersion_priority_enabled)
        self.assertEqual(config.immersion_tag, "satori-mining")
        self.assertEqual(tuple(config.immersion_tags), ("satori-mining", "shadowing-mining"))
        self.assertTrue(config.immersion_unsuspend)
        self.assertEqual(
            logic.effective_immersion_tags(config),
            ("satori-mining", "shadowing-mining"),
        )

    def test_effective_tags_prefer_list_over_legacy(self) -> None:
        config = WkAdaptiveNewConfig(
            immersion_tag="legacy-only",
            immersion_tags=("shadowing-mining", "satori-mining", "shadowing-mining"),
        )
        self.assertEqual(
            logic.effective_immersion_tags(config),
            ("shadowing-mining", "satori-mining"),
        )

    def test_effective_tags_fall_back_to_legacy_scalar(self) -> None:
        config = WkAdaptiveNewConfig(immersion_tag="custom-mining", immersion_tags=())
        self.assertEqual(logic.effective_immersion_tags(config), ("custom-mining",))


class ImmersionCoreFilteredLogicTests(unittest.TestCase):
    def test_filter_non_radical_subject_ids(self) -> None:
        kind_by_id = {
            100: logic.SUBJECT_KIND_RADICAL,
            400: logic.SUBJECT_KIND_KANJI,
            900: logic.SUBJECT_KIND_VOCABULARY,
        }
        kept = logic.filter_non_radical_subject_ids({100, 400, 900, 999}, kind_by_id)
        self.assertEqual(kept, {400, 900})

    def test_wk_linked_immersion_core_ids_drops_radicals(self) -> None:
        prereq_map = {900: [400], 400: [100, 101]}
        kind_by_id = {
            100: logic.SUBJECT_KIND_RADICAL,
            101: logic.SUBJECT_KIND_RADICAL,
            400: logic.SUBJECT_KIND_KANJI,
            900: logic.SUBJECT_KIND_VOCABULARY,
        }
        linked = logic.wk_linked_immersion_core_ids({900}, prereq_map, kind_by_id)
        self.assertEqual(linked, {900, 400})

    def test_candidate_linked_subject_ids_expression_and_kanji_chars(self) -> None:
        linked = logic.candidate_linked_subject_ids(
            ["食べる", "習慣"],
            {"食べる": 900},
            {"食": 400, "習": 401, "慣": 402},
        )
        self.assertEqual(linked, {900, 400, 401, 402})

    def test_candidate_linked_expands_vocab_prereqs_without_radicals(self) -> None:
        linked = logic.candidate_linked_subject_ids(
            ["食べる"],
            {"食べる": 900},
            {"食": 400},
            prereq_map={900: [400], 400: [100]},
            kind_by_id={
                100: logic.SUBJECT_KIND_RADICAL,
                400: logic.SUBJECT_KIND_KANJI,
                900: logic.SUBJECT_KIND_VOCABULARY,
            },
        )
        self.assertEqual(linked, {900, 400})

    def test_immersion_core_filtered_search(self) -> None:
        search = logic.immersion_core_filtered_search(
            logic.CORE_KANJI_DECK,
            logic.IMMERSION_CORE_TAG_SATORI,
        )
        self.assertIn('deck:"WaniKani Core · Kanji"', search)
        self.assertIn("tag:immersion-core::satori", search)
        self.assertIn("is:new", search)
        self.assertIn("-is:suspended", search)

    def test_tag_sync_actions_add_and_remove(self) -> None:
        actions = logic.immersion_core_tag_sync_actions(
            [
                (1, 900, ("wk-core",)),
                (2, 400, ("wk-core", logic.IMMERSION_CORE_TAG_SATORI)),
                (3, 401, ("wk-core", logic.IMMERSION_CORE_TAG_SHADOWING)),
                (4, None, ("wk-core", logic.IMMERSION_CORE_TAG_CANDIDATES)),
            ],
            {
                logic.IMMERSION_CORE_TAG_SATORI: {900},
                logic.IMMERSION_CORE_TAG_SHADOWING: {400},
                logic.IMMERSION_CORE_TAG_CANDIDATES: set(),
            },
        )
        by_note = {action.note_id: action for action in actions}
        self.assertEqual(by_note[1].add_tags, (logic.IMMERSION_CORE_TAG_SATORI,))
        self.assertEqual(by_note[1].remove_tags, ())
        self.assertEqual(by_note[2].add_tags, (logic.IMMERSION_CORE_TAG_SHADOWING,))
        self.assertEqual(by_note[2].remove_tags, (logic.IMMERSION_CORE_TAG_SATORI,))
        self.assertEqual(by_note[3].add_tags, ())
        self.assertEqual(by_note[3].remove_tags, (logic.IMMERSION_CORE_TAG_SHADOWING,))
        self.assertEqual(by_note[4].add_tags, ())
        self.assertEqual(by_note[4].remove_tags, (logic.IMMERSION_CORE_TAG_CANDIDATES,))

    def test_six_filtered_deck_definitions(self) -> None:
        self.assertEqual(len(logic.IMMERSION_CORE_FILTERED_DECKS), 6)
        names = [name for name, _home, _tag in logic.IMMERSION_CORE_FILTERED_DECKS]
        self.assertIn("Immersion Core · Satori · Kanji", names)
        self.assertIn("Immersion Core · Candidates · Vocabulary", names)


if __name__ == "__main__":
    unittest.main()
