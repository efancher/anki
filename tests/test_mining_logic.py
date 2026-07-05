"""Tests for mining duplicate-key helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mining_logic import mining_duplicate_key


class MiningLogicTests(unittest.TestCase):
    def test_same_expression_different_sentence(self) -> None:
        a = mining_duplicate_key("食べる", "ご飯を食べる。")
        b = mining_duplicate_key("食べる", "パンを食べる。")
        self.assertNotEqual(a, b)

    def test_term_only_key(self) -> None:
        self.assertEqual(mining_duplicate_key("食べる", ""), "食べる")


if __name__ == "__main__":
    unittest.main()
