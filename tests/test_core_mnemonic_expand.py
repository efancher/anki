"""Tests for core kanji/vocab mnemonic expansion (same-as radical/kanji/vocab)."""

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
    kanji_meaning_mnemonic_raw,
    radical_index_by_id,
    reading_mnemonic_is_pure_stub,
    strip_wk_mnemonic_tags,
    subject_index_by_id,
    subject_meaning_mnemonic_raw,
    subject_reading_mnemonic_raw,
    vocab_index_by_characters,
)

WK_CACHE = REPO_ROOT / ".wk_cache" / "subjects_vocabulary_kanji_radical.json"


def _load_subjects() -> list:
    if not WK_CACHE.is_file():
        raise unittest.SkipTest("WK subject cache not available")
    payload = json.loads(WK_CACHE.read_text(encoding="utf-8"))
    return list(payload.get("items") or [])


class CoreMnemonicExpandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.items = _load_subjects()
        cls.by_id = subject_index_by_id(cls.items)
        cls.radicals = radical_index_by_id(cls.items)
        cls.vocab_by_chars = vocab_index_by_characters(cls.items)
        cls.kanji_by_chars = kanji_index_by_characters(cls.items)

    def _subject(self, subject_id: int) -> dict:
        return self.by_id[subject_id]

    def test_courage_kanji_uses_radical_meaning_mnemonic(self) -> None:
        kanji = self._subject(941)  # 勇
        radical = self._subject(437)
        raw = kanji_meaning_mnemonic_raw(kanji, self.radicals)
        self.assertEqual(raw, radical["data"]["meaning_mnemonic"].strip())
        self.assertIn("mama", raw.lower())
        self.assertNotIn("exactly the same", raw.lower())

    def test_vocab_same_as_kanji_meaning_uses_kanji_story(self) -> None:
        vocab = self._subject(2507)  # 刀
        kanji = self._subject(458)
        raw = subject_meaning_mnemonic_raw(
            vocab,
            radical_index=self.radicals,
            subject_by_id=self.by_id,
        )
        self.assertEqual(
            raw,
            kanji_meaning_mnemonic_raw(kanji, self.radicals),
        )
        self.assertNotIn("exactly the same", (raw or "").lower())

    def test_atsumaru_uses_atsumeru_reading_mnemonic(self) -> None:
        atsumaru = next(
            item
            for item in self.items
            if item.get("object") == "vocabulary"
            and item["data"].get("characters") == "集まる"
        )
        atsumeru = next(
            item
            for item in self.items
            if item.get("object") == "vocabulary"
            and item["data"].get("characters") == "集める"
        )
        self.assertTrue(
            reading_mnemonic_is_pure_stub(atsumaru["data"].get("reading_mnemonic"))
        )
        raw = subject_reading_mnemonic_raw(
            atsumaru,
            subject_by_id=self.by_id,
            vocab_by_characters=self.vocab_by_chars,
            kanji_by_characters=self.kanji_by_chars,
        )
        self.assertIsNotNone(raw)
        assert raw is not None
        self.assertIn("ah, two", strip_wk_mnemonic_tags(raw).lower())
        self.assertIn(
            strip_wk_mnemonic_tags(atsumeru["data"]["reading_mnemonic"]).lower()[:40],
            strip_wk_mnemonic_tags(raw).lower(),
        )
        self.assertNotEqual(
            strip_wk_mnemonic_tags(raw),
            strip_wk_mnemonic_tags(atsumaru["data"]["reading_mnemonic"]),
        )

    def test_kotaeru_uses_kanji_reading_mnemonic(self) -> None:
        kotaeru = next(
            item
            for item in self.items
            if item.get("object") == "vocabulary"
            and item["data"].get("characters") == "答える"
        )
        kanji = next(
            item
            for item in self.items
            if item.get("object") == "kanji" and item["data"].get("characters") == "答"
        )
        raw = subject_reading_mnemonic_raw(
            kotaeru,
            subject_by_id=self.by_id,
            vocab_by_characters=self.vocab_by_chars,
            kanji_by_characters=self.kanji_by_chars,
        )
        self.assertIsNotNone(raw)
        assert raw is not None
        self.assertIn(
            strip_wk_mnemonic_tags(kanji["data"]["reading_mnemonic"]).lower()[:40],
            strip_wk_mnemonic_tags(raw).lower(),
        )
        self.assertNotIn("as you'd expect", strip_wk_mnemonic_tags(raw).lower())

    def test_yuuki_jukugo_uses_component_kanji_reading_mnemonics(self) -> None:
        yuuki = next(
            item
            for item in self.items
            if item.get("object") == "vocabulary"
            and item["data"].get("characters") == "勇気"
        )
        raw = subject_reading_mnemonic_raw(
            yuuki,
            subject_by_id=self.by_id,
            vocab_by_characters=self.vocab_by_chars,
            kanji_by_characters=self.kanji_by_chars,
        )
        self.assertIsNotNone(raw)
        assert raw is not None
        plain = strip_wk_mnemonic_tags(raw).lower()
        self.assertIn("youth", plain)
        self.assertIn("key", plain)
        self.assertNotIn("jukugo word", plain)

    def test_own_reading_story_is_kept(self) -> None:
        hito = next(
            item
            for item in self.items
            if item.get("object") == "vocabulary"
            and item["data"].get("characters") == "人"
        )
        original = hito["data"]["reading_mnemonic"].strip()
        raw = subject_reading_mnemonic_raw(
            hito,
            subject_by_id=self.by_id,
            vocab_by_characters=self.vocab_by_chars,
            kanji_by_characters=self.kanji_by_chars,
        )
        self.assertEqual(raw, original)


if __name__ == "__main__":
    unittest.main()
