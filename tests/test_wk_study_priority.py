"""Tests for wk_study_priority."""

from __future__ import annotations

import unittest

from grammar_decks import GrammarCardItem
from tae_kim_mapping import TaeKimLesson, TaeKimSection
from wk_study_priority import (
    build_core_priority_index,
    build_tae_kim_subject_orders,
    build_tae_kim_track_map,
    jlpt_sort_rank,
    priority_score_for,
    priority_tags,
    wk_level_to_jlpt,
)


def _section(num: int = 3) -> TaeKimSection:
    return TaeKimSection(num=num, slug="basic-grammar", name="Basic Grammar", guide_url="")


def _lesson(num: int) -> TaeKimLesson:
    return TaeKimLesson(
        chapter_slug="basic",
        chapter_name="Basic Grammar",
        num=num,
        slug=f"lesson-{num}",
        name=f"Lesson {num}",
        has_cards=True,
        section_num=3,
    )


class WkStudyPriorityTests(unittest.TestCase):
    def test_wk_level_to_jlpt(self) -> None:
        self.assertEqual(wk_level_to_jlpt(3), "N5")
        self.assertEqual(wk_level_to_jlpt(15), "N4")
        self.assertEqual(wk_level_to_jlpt(50), "N1")

    def test_jlpt_rank_orders_n5_before_n1(self) -> None:
        self.assertLess(jlpt_sort_rank("N5"), jlpt_sort_rank("N1"))

    def test_tae_kim_match_boosts_kanji_priority(self) -> None:
        kanji_early = {
            "id": 1,
            "object": "kanji",
            "data": {"characters": "学", "level": 8},
        }
        kanji_late = {
            "id": 2,
            "object": "kanji",
            "data": {"characters": "猫", "level": 8},
        }
        vocab = {
            "id": 30,
            "object": "vocabulary",
            "data": {"characters": "学生", "level": 5, "component_subject_ids": [1]},
        }
        grammar = GrammarCardItem(
            point_id="p1",
            jlpt="N5",
            order=1,
            title="State of being",
            short_explanation="",
            formation="",
            cloze_sentence="＿＿＿。",
            full_sentence="学生だ。",
            sentence_en="",
            type_expression="学生だ。",
            hint="",
            tae_kim_section=_section(),
            tae_kim_lesson=_lesson(1),
        )
        index = build_core_priority_index(
            [],
            [kanji_early, kanji_late],
            [vocab],
            tae_kim_exercise_cards=[grammar],
        )
        self.assertLess(index[1].priority_score, index[2].priority_score)
        self.assertIsNotNone(index[1].tae_kim_order)
        self.assertIsNone(index[2].tae_kim_order)

    def test_priority_tags_include_tk_grammar_vocab_when_matched(self) -> None:
        from wk_study_priority import TK_GRAMMAR_VOCAB_TAG, SubjectPriority, priority_tags

        entry = SubjectPriority(
            subject_id=1,
            wk_level=5,
            jlpt="N5",
            priority_score=0,
            tae_kim_order=30001,
            tae_kim_direct=True,
        )
        tags = priority_tags(entry, subject_object="vocabulary")
        self.assertIn(TK_GRAMMAR_VOCAB_TAG, tags)
        self.assertIn("tk-priority-30001", tags)

    def test_prerequisite_radical_gets_tae_kim_boost(self) -> None:
        from wk_study_priority import TK_GRAMMAR_PREREQ_TAG

        radical = {
            "id": 100,
            "object": "radical",
            "data": {"characters": "学", "level": 1},
        }
        kanji = {
            "id": 1,
            "object": "kanji",
            "data": {"characters": "学", "level": 8, "component_subject_ids": [100]},
        }
        grammar = GrammarCardItem(
            point_id="p1",
            jlpt="N5",
            order=1,
            title="Study",
            short_explanation="",
            formation="",
            cloze_sentence="＿＿＿",
            full_sentence="学",
            sentence_en="",
            type_expression="学",
            hint="",
            tae_kim_section=_section(),
            tae_kim_lesson=_lesson(1),
        )
        index = build_core_priority_index([radical], [kanji], [], tae_kim_exercise_cards=[grammar])
        self.assertIn(TK_GRAMMAR_PREREQ_TAG, priority_tags(index[100], subject_object="radical"))
        self.assertLess(index[100].priority_score, priority_score_for("N5", 8))

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

    def test_kanji_not_matched_inside_compound(self) -> None:
        kanji_se = {"id": 1, "object": "kanji", "data": {"characters": "背", "level": 8}}
        orders = build_tae_kim_subject_orders(
            [kanji_se],
            [],
            [(30001, "背景がきれい。")],
        )
        self.assertNotIn(1, orders)

    def test_vocab_matches_reading_in_tae_kim_text(self) -> None:
        vocab = {
            "id": 10,
            "object": "vocabulary",
            "data": {
                "characters": "学生",
                "level": 5,
                "readings": [{"reading": "がくせい"}],
            },
        }
        orders = build_tae_kim_subject_orders(
            [],
            [vocab],
            [(30001, "がくせいです。")],
        )
        self.assertEqual(orders[10], 30001)

    def test_kanji_vocab_does_not_match_particle_ha(self) -> None:
        """葉 (は) must not match the topic particle は in exercise sentences."""
        kanji_ha = {"id": 750, "object": "kanji", "data": {"characters": "葉", "level": 10}}
        vocab_ha = {
            "id": 7629,
            "object": "vocabulary",
            "data": {
                "characters": "葉",
                "level": 10,
                "readings": [{"reading": "は", "primary": True}],
                "component_subject_ids": [750],
            },
        }
        particle_sentence = "私は大学生だ。"
        orders = build_tae_kim_subject_orders(
            [kanji_ha],
            [vocab_ha],
            [(30003, particle_sentence)],
        )
        self.assertNotIn(750, orders)
        self.assertNotIn(7629, orders)

    def test_tae_kim_vocabulary_entries_boost_matching_kanji(self) -> None:
        kanji_gaku = {
            "id": 1,
            "object": "kanji",
            "data": {"characters": "学", "level": 8},
        }
        vocab_gakusei = {
            "id": 30,
            "object": "vocabulary",
            "data": {"characters": "学生", "level": 5, "component_subject_ids": [1]},
        }
        index = build_core_priority_index(
            [],
            [kanji_gaku],
            [vocab_gakusei],
            tae_kim_priority_entries=[(30001, "学生")],
        )
        self.assertIsNotNone(index[1].tae_kim_order)
        self.assertIsNotNone(index[30].tae_kim_order)

    def test_priority_uses_production_answer_not_sentence_context(self) -> None:
        from wk_study_priority import _text_entries_from_grammar_cards

        kanji_tei = {"id": 1020, "object": "kanji", "data": {"characters": "底", "level": 17}}
        vocab_tei = {
            "id": 3991,
            "object": "vocabulary",
            "data": {
                "characters": "底",
                "level": 17,
                "readings": [{"reading": "そこ"}],
                "component_subject_ids": [1020],
            },
        }
        vocab_daigaku = {
            "id": 3436,
            "object": "vocabulary",
            "data": {
                "characters": "大学生",
                "level": 5,
                "readings": [{"reading": "だいがくせい"}],
            },
        }
        card = GrammarCardItem(
            point_id="particle-context",
            jlpt="N5",
            order=1,
            title="Particle は",
            short_explanation="",
            formation="",
            cloze_sentence="アリス） そこ＿＿＿図書館じゃない？",
            full_sentence="アリス） そこ は 図書館じゃない？",
            sentence_en="",
            type_expression="は",
            hint="",
            tae_kim_section=_section(),
            tae_kim_lesson=_lesson(3),
        )
        entries = _text_entries_from_grammar_cards([card])
        orders = build_tae_kim_subject_orders(
            [kanji_tei],
            [vocab_tei, vocab_daigaku],
            entries,
        )
        self.assertNotIn(1020, orders)
        self.assertNotIn(3991, orders)
        self.assertNotIn(3436, orders)

    def test_build_tae_kim_track_map_splits_direct_and_prereq(self) -> None:
        radical = {
            "id": 100,
            "object": "radical",
            "data": {"characters": "学", "level": 1},
        }
        kanji = {
            "id": 1,
            "object": "kanji",
            "data": {"characters": "学", "level": 8, "component_subject_ids": [100]},
        }
        vocab = {
            "id": 30,
            "object": "vocabulary",
            "data": {"characters": "学生", "level": 5, "component_subject_ids": [1]},
        }
        vocabulary_by_lesson = {
            "expressing-state-of-being": [(30001, "学生")],
        }
        track_map = build_tae_kim_track_map(
            [radical],
            [kanji],
            [vocab],
            vocabulary_by_lesson,
            reading_lesson_order=["expressing-state-of-being", "introduction-to-particles"],
        )
        self.assertEqual(track_map["reading_lessons"], ["expressing-state-of-being"])
        lesson = track_map["lessons"]["expressing-state-of-being"]
        self.assertIn(30, lesson["direct_subject_ids"])
        self.assertIn(1, lesson["prereq_subject_ids"])
        self.assertIn(100, lesson["prereq_subject_ids"])
        self.assertNotIn(30, lesson["prereq_subject_ids"])

    def test_priority_tags_omit_grammar_role_when_disabled(self) -> None:
        from wk_study_priority import TK_GRAMMAR_VOCAB_TAG, SubjectPriority

        entry = SubjectPriority(
            subject_id=1,
            wk_level=5,
            jlpt="N5",
            priority_score=0,
            tae_kim_order=30001,
            tae_kim_direct=True,
        )
        tags = priority_tags(entry, subject_object="vocabulary", include_grammar_role_tags=False)
        self.assertNotIn(TK_GRAMMAR_VOCAB_TAG, tags)
        self.assertIn("tk-priority-30001", tags)


if __name__ == "__main__":
    unittest.main()
