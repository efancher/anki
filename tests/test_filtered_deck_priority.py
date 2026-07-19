"""Regression tests for N5 priority tagging after filtered-deck retirement."""

from __future__ import annotations

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

class FilteredDeckPriorityTests(unittest.TestCase):
    def test_filtered_deck_definitions_stay_retired(self) -> None:
        self.assertEqual(FILTERED_DECK_DEFINITIONS, [])

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
