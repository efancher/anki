"""Regression tests for N5 priority tagging after filtered-deck retirement."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import FILTERED_DECK_DEFINITIONS
from wk_study_priority import (
    JLPT_N5_PREREQ_TAG,
    JLPT_N5_VOCAB_TAG,
    build_core_priority_index,
    priority_tags,
)

REMOVAL_SCRIPT = REPO_ROOT / "scripts" / "remove_wk_filtered_decks_ankiconnect.py"


def _load_removal_script():
    spec = importlib.util.spec_from_file_location("remove_wk_filtered_decks", REMOVAL_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FilteredDeckPriorityTests(unittest.TestCase):
    def test_filtered_deck_definitions_stay_retired(self) -> None:
        self.assertEqual(FILTERED_DECK_DEFINITIONS, [])


class FilteredDeckRemovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script = _load_removal_script()

    def test_matches_both_retired_deck_families(self) -> None:
        for name in (
            "WK::Core Vocabulary",
            "WK::Grammar · Current Tae Kim lesson",
            "Immersion Core · Shadowing · Vocabulary",
            "Immersion Core · Candidates · Kanji",
        ):
            with self.subTest(name=name):
                self.assertTrue(self.script.is_retired_filtered_deck(name))

    def test_keeps_home_and_immersion_study_decks(self) -> None:
        for name in (
            "WaniKani Core · Vocabulary",
            "WaniKani Core · Kanji",
            "Immersion · Shadowing",
            "Immersion · Shadowing Candidates",
            "Immersion · Satori",
        ):
            with self.subTest(name=name):
                self.assertFalse(self.script.is_retired_filtered_deck(name))

    def test_every_immersion_core_deck_has_a_home(self) -> None:
        for source in ("Satori", "Shadowing", "Candidates"):
            for kind, home in (
                ("Kanji", self.script.CORE_KANJI_DECK),
                ("Vocabulary", self.script.CORE_VOCABULARY_DECK),
            ):
                name = f"Immersion Core · {source} · {kind}"
                with self.subTest(name=name):
                    self.assertEqual(
                        self.script.HOME_DECK_BY_FILTERED_NAME.get(name), home
                    )

    def test_n5_prereq_tags_from_priority_index(self) -> None:
        radical = {
            "id": 200,
            "object": "radical",
            "data": {"characters": "一", "level": 1},
        }
        kanji = {
            "id": 20,
            "object": "kanji",
            "data": {"characters": "一", "level": 5, "component_subject_ids": [200]},
        }
        index = build_core_priority_index([radical], [kanji], [])
        self.assertIn(JLPT_N5_VOCAB_TAG, priority_tags(index[20], subject_object="kanji"))
        self.assertIn(JLPT_N5_PREREQ_TAG, priority_tags(index[200], subject_object="radical"))

if __name__ == "__main__":
    unittest.main()
