"""Tests for Yomitan mining duplicate keys and WK vocab lookup."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mining_logic import (
    build_vocab_lookup,
    match_wk_vocab_id,
    mining_duplicate_key,
    normalize_mining_text,
    sentence_already_in_set,
)


class MiningLogicTests(unittest.TestCase):
    def test_duplicate_key_differs_by_sentence(self) -> None:
        self.assertEqual(mining_duplicate_key("食べる"), "食べる")
        self.assertEqual(
            mining_duplicate_key("食べる", "毎日食べる。"),
            "食べる|毎日食べる。",
        )
        self.assertNotEqual(
            mining_duplicate_key("食べる", "毎日食べる。"),
            mining_duplicate_key("食べる", "よく食べる。"),
        )

    def test_normalize_strips_whitespace(self) -> None:
        self.assertEqual(normalize_mining_text("  橋　はし  "), "橋はし")

    def test_match_wk_vocab_by_surface(self) -> None:
        lookup = build_vocab_lookup(
            [
                {
                    "id": 100,
                    "object": "vocabulary",
                    "data": {
                        "characters": "橋",
                        "level": 10,
                        "readings": [{"reading": "はし", "primary": True}],
                    },
                }
            ]
        )
        self.assertEqual(match_wk_vocab_id("橋", "はし", lookup), 100)

    def test_match_wk_vocab_disambiguates_by_reading(self) -> None:
        lookup = build_vocab_lookup(
            [
                {
                    "id": 1,
                    "object": "vocabulary",
                    "data": {
                        "characters": "橋",
                        "level": 10,
                        "readings": [{"reading": "はし", "primary": True}],
                    },
                },
                {
                    "id": 2,
                    "object": "vocabulary",
                    "data": {
                        "characters": "橋",
                        "level": 20,
                        "readings": [{"reading": "きょう", "primary": True}],
                    },
                },
            ]
        )
        self.assertEqual(match_wk_vocab_id("橋", "きょう", lookup), 2)
        self.assertEqual(match_wk_vocab_id("橋", "はし", lookup), 1)

    def test_sentence_already_in_set(self) -> None:
        known = {normalize_mining_text("学生が本を読んでいる。"): True}
        self.assertTrue(sentence_already_in_set("学生が 本を 読んでいる。", known))
        self.assertFalse(sentence_already_in_set("別の文。", known))


if __name__ == "__main__":
    unittest.main()
