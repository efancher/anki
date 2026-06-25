"""Tests for Hanabira → Tae Kim section mapping."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tae_kim_mapping import (
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


if __name__ == "__main__":
    unittest.main()
