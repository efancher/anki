"""Tests for wk_study_priority."""

from __future__ import annotations

import unittest

from wk_study_priority import (
    build_core_priority_index,
    jlpt_sort_rank,
    priority_score_for,
    priority_tags,
    wk_level_to_jlpt,
)


class WkStudyPriorityTests(unittest.TestCase):
    def test_wk_level_to_jlpt(self) -> None:
        self.assertEqual(wk_level_to_jlpt(3), "N5")
        self.assertEqual(wk_level_to_jlpt(15), "N4")
        self.assertEqual(wk_level_to_jlpt(50), "N1")

    def test_jlpt_rank_orders_n5_before_n1(self) -> None:
        self.assertLess(jlpt_sort_rank("N5"), jlpt_sort_rank("N1"))

    def test_priority_score_uses_jlpt_and_wk_level(self) -> None:
        n5_early = priority_score_for("N5", 3)
        n5_late = priority_score_for("N5", 10)
        n1_early = priority_score_for("N1", 3)
        self.assertLess(n5_early, n5_late)
        self.assertLess(n5_early, n1_early)

    def test_n5_direct_and_prereq_tags(self) -> None:
        from wk_study_priority import JLPT_N5_PREREQ_TAG, JLPT_N5_VOCAB_TAG

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
        vocab = {
            "id": 21,
            "object": "vocabulary",
            "data": {"characters": "一人", "level": 5, "component_subject_ids": [20]},
        }
        index = build_core_priority_index([radical], [kanji], [vocab])
        self.assertIn(JLPT_N5_VOCAB_TAG, priority_tags(index[20], subject_object="kanji"))
        self.assertIn(JLPT_N5_VOCAB_TAG, priority_tags(index[21], subject_object="vocabulary"))
        self.assertIn(JLPT_N5_PREREQ_TAG, priority_tags(index[200], subject_object="radical"))
        self.assertNotIn(JLPT_N5_VOCAB_TAG, priority_tags(index[200], subject_object="radical"))

    def test_priority_tags_include_jlpt_band(self) -> None:
        from wk_study_priority import SubjectPriority

        entry = SubjectPriority(subject_id=1, wk_level=5, jlpt="N5", priority_score=0)
        self.assertIn("priority-jlpt-N5", priority_tags(entry, subject_object="kanji"))


if __name__ == "__main__":
    unittest.main()
