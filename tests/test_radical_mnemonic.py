"""Tests for same-as-kanji radical mnemonic substitution."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import (
    kanji_index_by_characters,
    radical_description_html,
    radical_is_same_as_kanji,
    radical_meaning_mnemonic_raw,
)

WK_CACHE = REPO_ROOT / ".wk_cache" / "subjects_vocabulary_kanji_radical.json"


def _load_subjects() -> list:
    if not WK_CACHE.is_file():
        raise unittest.SkipTest("WK subject cache not available")
    payload = json.loads(WK_CACHE.read_text(encoding="utf-8"))
    return list(payload.get("items") or [])


class RadicalMnemonicTests(unittest.TestCase):
    def test_radical_is_same_as_kanji_detection(self) -> None:
        items = _load_subjects()
        older_brother_radical = next(
            s for s in items if s.get("object") == "radical" and s["id"] == 191
        )
        ground_radical = next(
            s for s in items if s.get("object") == "radical" and s["id"] == 1
        )
        self.assertTrue(radical_is_same_as_kanji(older_brother_radical))
        self.assertFalse(radical_is_same_as_kanji(ground_radical))

    def test_same_as_kanji_radical_uses_kanji_meaning_mnemonic(self) -> None:
        items = _load_subjects()
        radical = next(s for s in items if s.get("object") == "radical" and s["id"] == 191)
        kanji = next(s for s in items if s.get("object") == "kanji" and s["id"] == 515)
        kanji_index = kanji_index_by_characters([kanji])

        raw = radical_meaning_mnemonic_raw(radical, kanji_index)
        self.assertIsNotNone(raw)
        assert raw is not None
        self.assertEqual(raw, kanji["data"]["meaning_mnemonic"].strip())
        self.assertIn("mouth", raw.lower())
        self.assertNotIn("refresher", raw.lower())

    def test_non_same_as_kanji_keeps_radical_mnemonic(self) -> None:
        items = _load_subjects()
        radical = next(s for s in items if s.get("object") == "radical" and s["id"] == 1)
        kanji_index = kanji_index_by_characters(
            [s for s in items if s.get("object") == "kanji"]
        )

        raw = radical_meaning_mnemonic_raw(radical, kanji_index)
        self.assertEqual(raw, radical["data"]["meaning_mnemonic"].strip())

    def test_description_html_renders_kanji_mnemonic_tags(self) -> None:
        radical = {
            "object": "radical",
            "id": 99,
            "data": {
                "characters": "兄",
                "meaning_mnemonic": (
                    "This radical is the same as the kanji. It means <radical>older brother</radical>."
                ),
            },
        }
        kanji = {
            "object": "kanji",
            "id": 515,
            "data": {
                "characters": "兄",
                "meaning_mnemonic": (
                    "Who's someone who's just a <radical>mouth</radical> with "
                    "<radical>legs</radical>? That's your <kanji>older brother</kanji>."
                ),
                "reading_mnemonic": "Reading story about <reading>Kyoto</reading>.",
            },
        }
        html_out = radical_description_html(radical, kanji_index_by_characters([kanji]))
        self.assertIn("wk-mnemonic-kanji", html_out)
        self.assertIn("mouth", html_out)
        self.assertNotIn("Kyoto", html_out)


if __name__ == "__main__":
    unittest.main()
