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
    strip_migaku_syntax,
)


class MiningLogicTests(unittest.TestCase):
    def test_build_cloze_sentence_replaces_target(self) -> None:
        cloze, plain = build_cloze_sentence("私は学生です。", ["学生"])
        self.assertEqual(plain, "私は学生です。")
        self.assertIn("cloze-blank", cloze)
        self.assertNotIn("学生", cloze)

    def test_build_cloze_sentence_strips_migaku_syntax(self) -> None:
        raw = "皆[みな;n2]さんは学生[がくせい;h]です。"
        cloze, plain = build_cloze_sentence(raw, ["学生"])
        self.assertEqual(plain, "皆さんは学生です。")
        self.assertIn("cloze-blank", cloze)

    def test_enrich_strips_migaku_syntax_fields(self) -> None:
        raw_sentence = (
            "皆[みな;n2]さん と 一緒[いっしょ;h] に{、}"
            "日本語[にほんご;h]の 勉強[べんきょう;h] を 頑張[がんば;k3]りましょう"
        )
        result = enrich_mining_note_fields(
            expression="頑張[がんば;k3]り",
            reading="がんばり",
            sentence=raw_sentence,
            sentence_furigana="",
            glossary="",
            wk_entry=None,
        )
        self.assertEqual(result.sentence, "皆さんと一緒に、日本語の勉強を頑張りましょう")
        self.assertEqual(result.expression, "頑張り")
        self.assertIn("cloze-blank", result.cloze_sentence)

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

    def test_glossary_snippet_strips_yomitan_css_and_extracts_sense(self) -> None:
        raw = (
            '<style>.yomitan-glossary [data-content="x"] { color: red; }</style>'
            '<div class="yomitan-glossary">'
            "意味 (小学館例解学習国語 第十二版) １ねがい【願４い】 名 ネガイ"
            "❶ねがうこと。例 ぼくの願いを聞いてください。"
            "</div>"
        )
        snippet = glossary_snippet(raw)
        self.assertEqual(snippet, "ねがうこと")
        self.assertNotIn("yomitan", snippet)
        self.assertNotIn("{", snippet)

    def test_enrich_skips_jj_and_jisho_when_wk_meaning_present(self) -> None:
        result = enrich_mining_note_fields(
            expression="学生",
            reading="がくせい",
            sentence="私は学生です。",
            sentence_furigana="",
            glossary="❶学ぶ人。",
            translation="student from migaku",
            wk_entry={"id": 123, "meaning": "student", "prerequisite_ids": "10"},
        )
        self.assertEqual(result.wk_meaning, "student")
        self.assertEqual(result.hint_glossary, "")
        self.assertEqual(result.dict_links_en, "")

    def test_enrich_uses_translation_as_english_hint(self) -> None:
        result = enrich_mining_note_fields(
            expression="願い",
            reading="ねがい",
            sentence="お願いします。",
            sentence_furigana="",
            glossary="❶ねがうこと。",
            translation="request",
            wk_entry=None,
        )
        self.assertEqual(result.hint_glossary, "")
        self.assertEqual(result.dict_links_en, "")

    def test_mining_hint_display_flags(self) -> None:
        self.assertEqual(mining_hint_display_flags(0), ("0", "1", "1", ""))
        self.assertEqual(mining_hint_display_flags(1), ("1", "", "1", ""))
        self.assertEqual(mining_hint_display_flags(2), ("2", "", "", "1"))


if __name__ == "__main__":
    unittest.main()
