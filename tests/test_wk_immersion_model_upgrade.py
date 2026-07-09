"""Tests for wk_immersion model upgrade."""

from __future__ import annotations

import unittest
from pathlib import Path

UPGRADE_PATH = Path(__file__).resolve().parent.parent / "anki_addon" / "wk_immersion" / "model_upgrade.py"


class ModelUpgradeTests(unittest.TestCase):
    def test_upgrade_ensures_mining_cloze_fields(self) -> None:
        source = UPGRADE_PATH.read_text(encoding="utf-8")
        self.assertIn("ClozeSentence", source)
        self.assertIn("ShowJjBack", source)
        self.assertIn("MINING_CLOZE_TEMPLATE_MARKER", source)

    def test_upgrade_loads_shared_templates(self) -> None:
        source = UPGRADE_PATH.read_text(encoding="utf-8")
        self.assertIn("mining_templates", source)
        self.assertIn("MINING_FRONT", source)


if __name__ == "__main__":
    unittest.main()
