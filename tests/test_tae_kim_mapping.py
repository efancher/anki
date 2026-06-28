"""Tests for Hanabira → Tae Kim section mapping."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tae_kim_mapping import (
    conjugation_cap_for_tae_kim,
    load_tae_kim_sections,
    map_grammar_point_to_tae_kim_section,
    parse_tae_kim_lesson_cap,
)


class TaeKimMappingTests(unittest.TestCase):
    def test_section_three_is_basic_grammar(self) -> None:
        sections = load_tae_kim_sections()
        basic = next(section for section in sections if section.num == 3)
        self.assertEqual(basic.slug, "basic-grammar")
        self.assertEqual(basic.name, "Basic Grammar")

    def test_kudasai_maps_to_essential(self) -> None:
        point = {
            "_jlpt": "N5",
            "title": "Verb て ください (Verb-te kudasai)",
            "formation": "Verb て-form + ください",
            "short_explanation": "Please do (request).",
        }
        section = map_grammar_point_to_tae_kim_section(point)
        self.assertEqual(section.num, 4)
        self.assertEqual(section.slug, "essential-grammar")

    def test_wake_maps_to_special(self) -> None:
        point = {
            "_jlpt": "N3",
            "title": "～わけだ (〜wake da)",
            "formation": "Clause + わけだ",
            "short_explanation": "It means that; no wonder.",
        }
        section = map_grammar_point_to_tae_kim_section(point)
        self.assertEqual(section.num, 5)

    def test_parse_lesson_cap_by_subsection_slug(self) -> None:
        chapter, lesson_num = parse_tae_kim_lesson_cap(
            "basic:introduction-to-particles"
        )
        self.assertEqual(chapter, "basic")
        self.assertEqual(lesson_num, 3)

    def test_parse_lesson_cap_by_subsection_title(self) -> None:
        chapter, lesson_num = parse_tae_kim_lesson_cap("Introduction to Particles")
        self.assertEqual(chapter, "basic")
        self.assertEqual(lesson_num, 3)

    def test_conjugation_cap_state_of_being_is_na_adjective_only(self) -> None:
        cap = conjugation_cap_for_tae_kim(
            max_tae_kim_lesson="expressing-state-of-being",
            max_tae_kim_section=3,
        )
        self.assertEqual(cap.verb_forms, frozenset())
        self.assertEqual(cap.i_adjective_forms, frozenset())
        self.assertIn("polite", cap.na_adjective_forms)

    def test_conjugation_cap_adjectives_includes_i_adjective(self) -> None:
        cap = conjugation_cap_for_tae_kim(
            max_tae_kim_lesson="adjectives",
            max_tae_kim_section=3,
        )
        self.assertIn("plain_negative", cap.i_adjective_forms)
        self.assertEqual(cap.verb_forms, frozenset())

    def test_conjugation_cap_verb_basics_includes_polite_present(self) -> None:
        cap = conjugation_cap_for_tae_kim(
            max_tae_kim_lesson="verb-basics",
            max_tae_kim_section=3,
        )
        self.assertEqual(cap.verb_forms, frozenset({"polite_present"}))


if __name__ == "__main__":
    unittest.main()
