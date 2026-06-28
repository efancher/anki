"""Tests for WK mnemonic HTML highlighting."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import wk_mnemonic_html


class WkMnemonicHtmlTests(unittest.TestCase):
    def test_highlights_radical_and_kanji_tags(self) -> None:
        raw = (
            "In a <radical>rice paddy</radical> you find a <radical>heart</radical> "
            "and it makes you <kanji>think</kanji>."
        )
        rendered = wk_mnemonic_html(raw)
        self.assertIn("wk-mnemonic-radical", rendered)
        self.assertIn("rice paddy", rendered)
        self.assertIn("wk-mnemonic-kanji", rendered)
        self.assertIn("think", rendered)
        self.assertNotIn("<radical>", rendered)
        self.assertNotIn("<kanji>", rendered)

    def test_highlights_reading_tag(self) -> None:
        raw = "What is it? <reading>Oh! Moe</reading> (おも)"
        rendered = wk_mnemonic_html(raw)
        self.assertIn("wk-mnemonic-reading", rendered)
        self.assertIn("Oh! Moe", rendered)

    def test_escapes_plain_text(self) -> None:
        rendered = wk_mnemonic_html('Say "hello" & <goodbye>')
        self.assertIn("&quot;hello&quot;", rendered)
        self.assertIn("&lt;goodbye&gt;", rendered)

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(wk_mnemonic_html(""), "")
        self.assertEqual(wk_mnemonic_html(None), "")


if __name__ == "__main__":
    unittest.main()
