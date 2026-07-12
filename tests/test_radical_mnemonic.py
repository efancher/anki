"""Tests for same-as-kanji / same-as-radical mnemonic substitution."""

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
    kanji_is_same_as_radical,
    kanji_meaning_mnemonic_raw,
    matching_same_radical_for_kanji,
    radical_description_html,
    radical_index_by_id,
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

    def test_kanji_same_as_radical_uses_radical_mnemonic(self) -> None:
        items = _load_subjects()
        kanji = next(s for s in items if s.get("object") == "kanji" and s["id"] == 517)
        radical = next(s for s in items if s.get("object") == "radical" and s["id"] == 327)
        radical_index = radical_index_by_id([radical])

        self.assertTrue(kanji_is_same_as_radical(kanji))
        self.assertEqual(matching_same_radical_for_kanji(kanji, radical_index), radical)
        raw = kanji_meaning_mnemonic_raw(kanji, radical_index)
        self.assertEqual(raw, radical["data"]["meaning_mnemonic"].strip())
        self.assertIn("ice", raw.lower())
        self.assertNotIn("same as the radical", raw.lower())

    def test_kanji_radical_for_x_are_the_same_phrasing(self) -> None:
        items = _load_subjects()
        kanji = next(s for s in items if s.get("object") == "kanji" and s["id"] == 644)  # 食
        radical = next(s for s in items if s.get("object") == "radical" and s["id"] == 139)
        radical_index = radical_index_by_id([radical])
        self.assertTrue(kanji_is_same_as_radical(kanji))
        raw = kanji_meaning_mnemonic_raw(kanji, radical_index)
        self.assertEqual(raw, radical["data"]["meaning_mnemonic"].strip())
        self.assertIn("goose", raw.lower())
        self.assertNotIn("lucky you", raw.lower())

    def test_composition_story_with_same_is_not_treated_as_deferral(self) -> None:
        items = _load_subjects()
        town = next(s for s in items if s.get("object") == "kanji" and s["id"] == 556)
        self.assertFalse(kanji_is_same_as_radical(town))

    def test_kanji_with_own_story_keeps_kanji_mnemonic(self) -> None:
        items = _load_subjects()
        kanji = next(s for s in items if s.get("object") == "kanji" and s["id"] == 440)  # 一
        radical_index = radical_index_by_id(
            [s for s in items if s.get("object") == "radical"]
        )
        self.assertFalse(kanji_is_same_as_radical(kanji))
        raw = kanji_meaning_mnemonic_raw(kanji, radical_index)
        self.assertEqual(raw, kanji["data"]["meaning_mnemonic"].strip())


if __name__ == "__main__":
    unittest.main()
