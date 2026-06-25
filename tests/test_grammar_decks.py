"""Tests for Hanabira grammar deck generation."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from grammar_decks import (
    blank_grammar_in_sentence,
    collect_grammar_cards,
    grammar_blank_tokens,
    grammar_point_id,
    hanabira_grammar_cache_path,
    jlpt_within_cap,
    sentence_unknown_kanji,
)


SAMPLE_POINT = {
    "_jlpt": "N5",
    "title": "A。けれども、～B。 (A. Keredomo, ~B.)",
    "short_explanation": "Express contrast; 'but', 'however'.",
    "formation": "Statement A + けれども、+ Statement B",
    "s_tag": "25",
    "examples": [
        {
            "jp": "今日は晴れている。けれども、寒いです。",
            "en": "It is sunny today. However, it is cold.",
        }
    ],
}


class GrammarDeckTests(unittest.TestCase):
    def test_jlpt_within_cap(self) -> None:
        self.assertTrue(jlpt_within_cap("N5", "N2"))
        self.assertTrue(jlpt_within_cap("N2", "N2"))
        self.assertFalse(jlpt_within_cap("N1", "N2"))

    def test_grammar_blank_tokens_extracts_japanese(self) -> None:
        tokens = grammar_blank_tokens(SAMPLE_POINT)
        self.assertIn("けれども", tokens)

    def test_blank_grammar_in_sentence(self) -> None:
        tokens = grammar_blank_tokens(SAMPLE_POINT)
        result = blank_grammar_in_sentence(SAMPLE_POINT["examples"][0]["jp"], tokens)
        self.assertIsNotNone(result)
        cloze, chunk = result
        self.assertIn("＿", cloze)
        self.assertEqual(chunk, "けれども")

    def test_sentence_unknown_kanji(self) -> None:
        self.assertEqual(sentence_unknown_kanji("今日は寒い", {"今", "日"}), 1)
        self.assertEqual(sentence_unknown_kanji("今日は寒い", {"今", "日", "寒"}), 0)

    def test_collect_from_cached_hanabira(self) -> None:
        cache_path = hanabira_grammar_cache_path("N5")
        if not cache_path.is_file():
            self.skipTest("Hanabira cache not present; run wk_decks.py --deck grammar once")
        cards = collect_grammar_cards(
            max_jlpt="N5",
            max_examples_per_point=1,
            max_unknown_kanji=99,
            known_kanji=set(),
            refresh=False,
        )
        self.assertGreater(len(cards), 50)
        self.assertTrue(all(card.jlpt == "N5" for card in cards))

    def test_grammar_point_id_is_stable(self) -> None:
        first = grammar_point_id(SAMPLE_POINT, 0)
        second = grammar_point_id(SAMPLE_POINT, 0)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
