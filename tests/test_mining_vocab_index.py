"""Tests for WK mining vocab index."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mining_vocab_index import build_mining_vocab_index, lookup_wk_vocab


def mock_vocab(vocab_id: int, chars: str, reading: str, *, kanji_ids=(10, 11)) -> dict:
    return {
        "id": vocab_id,
        "object": "vocabulary",
        "data": {
            "characters": chars,
            "readings": [{"reading": reading, "primary": True}],
            "meanings": [{"meaning": "student", "primary": True}],
            "component_subject_ids": list(kanji_ids),
        },
    }


class MiningVocabIndexTests(unittest.TestCase):
    def test_lookup_by_expression(self) -> None:
        index = build_mining_vocab_index([mock_vocab(123, "学生", "がくせい")])
        entry = lookup_wk_vocab("学生", "がくせい", index)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["id"], 123)
        self.assertEqual(entry["meaning"], "student")

    def test_lookup_by_reading(self) -> None:
        index = build_mining_vocab_index([mock_vocab(456, "食べる", "たべる")])
        entry = lookup_wk_vocab("", "たべる", index)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["id"], 456)


if __name__ == "__main__":
    unittest.main()
