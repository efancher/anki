"""Tests for WK mining vocab index."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mining_vocab_index import build_mining_vocab_index, lookup_wk_vocab


def mock_vocab(
    vocab_id: int,
    chars: str,
    reading: str,
    *,
    kanji_ids=(10, 11),
    parts_of_speech: list | None = None,
) -> dict:
    return {
        "id": vocab_id,
        "object": "vocabulary",
        "data": {
            "characters": chars,
            "readings": [{"reading": reading, "primary": True}],
            "meanings": [{"meaning": "student", "primary": True}],
            "parts_of_speech": list(parts_of_speech or []),
            "component_subject_ids": list(kanji_ids),
        },
    }


class MiningVocabIndexTests(unittest.TestCase):
    def test_lookup_by_expression(self) -> None:
        index = build_mining_vocab_index(
            [mock_vocab(123, "学生", "がくせい", parts_of_speech=["noun"])]
        )
        entry = lookup_wk_vocab("学生", "がくせい", index)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["id"], 123)
        self.assertEqual(entry["meaning"], "student")
        self.assertEqual(entry["parts_of_speech"], ["noun"])

    def test_lookup_by_reading(self) -> None:
        index = build_mining_vocab_index([mock_vocab(456, "食べる", "たべる")])
        entry = lookup_wk_vocab("", "たべる", index)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["id"], 456)

    def test_lookup_does_not_confuse_homophones(self) -> None:
        """週間 is not in WK; must not resolve to 習慣 via shared reading しゅうかん."""
        index = build_mining_vocab_index(
            [
                {
                    "id": 4813,
                    "object": "vocabulary",
                    "data": {
                        "characters": "習慣",
                        "readings": [{"reading": "しゅうかん", "primary": True}],
                        "meanings": [
                            {"meaning": "Custom", "primary": True},
                            {"meaning": "Habit", "primary": False},
                        ],
                        "component_subject_ids": [10, 11],
                    },
                }
            ]
        )
        self.assertIsNone(lookup_wk_vocab("週間", "しゅうかん", index))
        self.assertEqual(lookup_wk_vocab("習慣", "しゅうかん", index)["id"], 4813)


if __name__ == "__main__":
    unittest.main()
