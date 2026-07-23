"""Tests for Core Item phonetic-family hint HTML."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core_decks import make_core_item_model
from wk_decks import core_phonetic_hint_html, matching_phonetic_signal_onyomi


def _kanji(
    subject_id: int,
    char: str,
    *,
    onyomi: list[str],
    kunyomi: list[str] | None = None,
    primary_on: bool = True,
) -> dict:
    readings = []
    for index, reading in enumerate(onyomi):
        readings.append(
            {
                "reading": reading,
                "type": "onyomi",
                "primary": primary_on and index == 0,
                "accepted_answer": primary_on and index == 0,
            }
        )
    for index, reading in enumerate(kunyomi or []):
        readings.append(
            {
                "reading": reading,
                "type": "kunyomi",
                "primary": (not primary_on) and index == 0,
                "accepted_answer": (not primary_on) and index == 0,
            }
        )
    return {
        "id": subject_id,
        "object": "kanji",
        "data": {"characters": char, "level": 5, "readings": readings},
    }


def _vocab(subject_id: int, characters: str, reading: str, *, kanji_id: int) -> dict:
    return {
        "id": subject_id,
        "object": "vocabulary",
        "data": {
            "characters": characters,
            "level": 5,
            "component_subject_ids": [kanji_id],
            "readings": [{"reading": reading, "primary": True, "accepted_answer": True}],
        },
    }


KEISEI_KANJI = {
    "時": {"readings": ["じ"], "phonetic": "寺", "type": "comp_phonetic"},
    "持": {"readings": ["じ"], "phonetic": "寺", "type": "comp_phonetic"},
    "寺": {"readings": ["じ"], "type": "hieroglyph"},
    "食": {"readings": ["しょく"], "type": "hieroglyph"},
}
KEISEI_PHONETIC = {
    "寺": {"readings": ["じ"], "compounds": ["侍", "待", "持", "時", "特", "詩", "等"]},
}


class CorePhoneticHintTests(unittest.TestCase):
    def test_matching_onyomi_for_family_kanji(self) -> None:
        kanji = _kanji(100, "時", onyomi=["じ"])
        comp, matched = matching_phonetic_signal_onyomi(
            kanji, "時", KEISEI_KANJI, KEISEI_PHONETIC
        )
        self.assertEqual(comp, "寺")
        self.assertEqual(matched, ["じ"])

    def test_no_match_when_primary_is_kunyomi_only(self) -> None:
        kanji = _kanji(101, "時", onyomi=["じ"], kunyomi=["とき"], primary_on=False)
        comp, matched = matching_phonetic_signal_onyomi(
            kanji, "時", KEISEI_KANJI, KEISEI_PHONETIC
        )
        self.assertEqual(comp, "")
        self.assertEqual(matched, [])

    def test_core_hint_html_for_kanji(self) -> None:
        html_out = core_phonetic_hint_html(
            _kanji(100, "時", onyomi=["じ"]),
            keisei_kanji=KEISEI_KANJI,
            keisei_phonetic=KEISEI_PHONETIC,
        )
        self.assertIn("phonetic-hint", html_out)
        self.assertIn("寺", html_out)
        self.assertIn("じ", html_out)

    def test_core_hint_empty_without_phonetic_component(self) -> None:
        html_out = core_phonetic_hint_html(
            _kanji(200, "食", onyomi=["しょく"]),
            keisei_kanji=KEISEI_KANJI,
            keisei_phonetic=KEISEI_PHONETIC,
        )
        self.assertEqual(html_out, "")

    def test_single_kanji_vocab_hint(self) -> None:
        kanji = _kanji(100, "時", onyomi=["じ"])
        vocab = _vocab(300, "時", "じ", kanji_id=100)
        html_out = core_phonetic_hint_html(
            vocab,
            keisei_kanji=KEISEI_KANJI,
            keisei_phonetic=KEISEI_PHONETIC,
            subject_by_id={100: kanji},
        )
        self.assertIn("寺", html_out)
        self.assertIn("じ", html_out)

    def test_kun_vocab_no_hint(self) -> None:
        kanji = _kanji(110, "持", onyomi=["じ"], kunyomi=["も"])
        vocab = _vocab(301, "持つ", "もつ", kanji_id=110)
        # component_subject_ids length 1 but reading is not on'yomi signal
        html_out = core_phonetic_hint_html(
            vocab,
            keisei_kanji=KEISEI_KANJI,
            keisei_phonetic=KEISEI_PHONETIC,
            subject_by_id={110: kanji},
        )
        self.assertEqual(html_out, "")

    def test_multi_kanji_vocab_skipped(self) -> None:
        vocab = {
            "id": 400,
            "object": "vocabulary",
            "data": {
                "characters": "時計",
                "component_subject_ids": [100, 101],
                "readings": [{"reading": "とけい", "primary": True}],
            },
        }
        html_out = core_phonetic_hint_html(
            vocab,
            keisei_kanji=KEISEI_KANJI,
            keisei_phonetic=KEISEI_PHONETIC,
            subject_by_id={100: _kanji(100, "時", onyomi=["じ"])},
        )
        self.assertEqual(html_out, "")

    def test_core_item_model_includes_phonetic_hint_field(self) -> None:
        model = make_core_item_model()
        fields = [field["name"] for field in model.fields]
        self.assertIn("PhoneticHint", fields)
        self.assertIn("{{PhoneticHint}}", model.templates[0]["afmt"])


if __name__ == "__main__":
    unittest.main()
