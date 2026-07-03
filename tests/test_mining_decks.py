"""Tests for Yomitan mining deck note type."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mining_decks import MINING_NOTE_TYPE_NAME, make_mining_model


class MiningDeckTests(unittest.TestCase):
    def test_first_field_is_duplicate_key(self) -> None:
        fields = [field["name"] for field in make_mining_model().fields]
        self.assertEqual(fields[0], "DuplicateKey")

    def test_note_type_name(self) -> None:
        model = make_mining_model()
        self.assertEqual(model.name, MINING_NOTE_TYPE_NAME)


if __name__ == "__main__":
    unittest.main()
