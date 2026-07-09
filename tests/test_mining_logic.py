"""Tests for mining cloze logic."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IMMERSION_DIR = REPO_ROOT / "anki_addon" / "wk_immersion"
if str(IMMERSION_DIR) not in sys.path:
    sys.path.insert(0, str(IMMERSION_DIR))

from mining_logic import (
    build_cloze_sentence,
    build_sentence_kana,
    enrich_mining_note_fields,
    glossary_snippet,
    mining_hint_display_flags,
)


class MiningLogicTests(unittest.TestCase):
    def test_build_cloze_sentence_replaces_target(self) -> None:
        cloze, plain = build_cloze_sentence("私は学生です。", ["学生"])
        self.assertEqual(plain, "私は学生です。")
        self.assertIn("cloze-blank", cloze)
        self.assertNotIn("学生", cloze)

    def test_build_sentence_kana_from_ruby(self) -> None:
        kana = build_sentence_kana("<ruby>学生<rt>がくせい</rt></ruby>です。", "", "")
        self.assertIn("がくせい", kana)

    def test_enrich_mining_note_fields_stage_zero(self) -> None:
        result = enrich_mining_note_fields(
            expression="学生",
            reading="がくせい",
            sentence="私は学生です。",
            sentence_furigana="",
            glossary="【名】学ぶ人。",
            wk_entry={
                "id": 123,
                "meaning": "student",
                "prerequisite_ids": "10,11",
            },
        )
        self.assertEqual(result.hint_stage, "0")
        self.assertEqual(result.show_english, "1")
        self.assertEqual(result.show_kana, "1")
        self.assertEqual(result.show_jj_back, "")
        self.assertEqual(result.wk_subject_id, "123")
        self.assertIn("cloze-blank", result.cloze_sentence)

    def test_glossary_snippet_truncates(self) -> None:
        long_text = "あ" * 200
        snippet = glossary_snippet(long_text, max_len=20)
        self.assertLessEqual(len(snippet), 20)
        self.assertTrue(snippet.endswith("…"))

    def test_mining_hint_display_flags(self) -> None:
        self.assertEqual(mining_hint_display_flags(0), ("0", "1", "1", ""))
        self.assertEqual(mining_hint_display_flags(1), ("1", "", "1", ""))
        self.assertEqual(mining_hint_display_flags(2), ("2", "", "", "1"))


if __name__ == "__main__":
    unittest.main()
