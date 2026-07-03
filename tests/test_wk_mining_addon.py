"""Tests for wk_mining add-on logic (mirrors mining_logic)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_LOGIC = REPO_ROOT / "anki_addon" / "wk_mining" / "logic.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import importlib.util

spec = importlib.util.spec_from_file_location("wk_mining_logic", ADDON_LOGIC)
assert spec and spec.loader
wk_mining_logic = importlib.util.module_from_spec(spec)
sys.modules["wk_mining_logic"] = wk_mining_logic
spec.loader.exec_module(wk_mining_logic)


class WkMiningAddonLogicTests(unittest.TestCase):
    def test_link_mining_note_fields_locks_immature(self) -> None:
        lookup = {"食べる": [{"id": 42, "level": 5, "readings": ["たべる"]}]}
        updates, add_tags, remove_tags = wk_mining_logic.link_mining_note_fields(
            {"Expression": "食べる", "Reading": "たべる", "WkSubjectId": ""},
            lookup,
            mature_subject_ids=set(),
        )
        self.assertEqual(updates["WkSubjectId"], "42")
        self.assertIn("wk-locked", add_tags)
        self.assertEqual(remove_tags, [])

    def test_link_mining_note_fields_unlocks_mature(self) -> None:
        lookup = {"食べる": [{"id": 42, "level": 5, "readings": ["たべる"]}]}
        _, add_tags, remove_tags = wk_mining_logic.link_mining_note_fields(
            {"Expression": "食べる", "Reading": "たべる", "WkSubjectId": "42"},
            lookup,
            mature_subject_ids={42},
        )
        self.assertNotIn("wk-locked", add_tags)
        self.assertIn("wk-locked", remove_tags)


if __name__ == "__main__":
    unittest.main()
