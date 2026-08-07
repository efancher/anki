"""Tests for Anki furigana bracket alignment."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anki_furigana import anki_furigana_brackets, word_furigana_brackets


class AnkiFuriganaTests(unittest.TestCase):
    def test_sentence_alignment(self) -> None:
        self.assertEqual(
            anki_furigana_brackets(
                "私は隣の町です。電車で",
                "わたくしはとなりのまちです。でんしゃで",
            ),
            "私[わたくし]は 隣[となり]の 町[まち]です。 電車[でんしゃ]で",
        )

    def test_space_before_kanji_after_kana_prefix(self) -> None:
        """Anki needs a space so せんせい sits on 先生, not ひし先生."""
        self.assertEqual(
            anki_furigana_brackets("はい。ひし先生です。", "はい。ひしせんせいです。"),
            "はい。ひし 先生[せんせい]です。",
        )

    def test_neighborhood_kana_run(self) -> None:
        self.assertEqual(
            anki_furigana_brackets("え、マジで?近所じゃん。", "え、マジで?きんじょじゃん。"),
            "え、マジで? 近所[きんじょ]じゃん。",
        )

    def test_counter_ke(self) -> None:
        self.assertEqual(
            anki_furigana_brackets("1ヶ月だよ。", "1かげつだよ。"),
            "1 ヶ月[かげつ]だよ。",
        )

    def test_mismatch_returns_empty(self) -> None:
        self.assertEqual(anki_furigana_brackets("電車で", "でんしゃ"), "")

    def test_word_furigana(self) -> None:
        self.assertEqual(word_furigana_brackets("電車", "でんしゃ"), "電車[でんしゃ]")
        self.assertEqual(word_furigana_brackets("〜歳", "さい"), "〜 歳[さい]")
        self.assertEqual(word_furigana_brackets("こんにちは", "こんにちは"), "")


if __name__ == "__main__":
    unittest.main()
