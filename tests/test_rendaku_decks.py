"""Tests for rendaku compound reading detection."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rendaku_decks import (
    RendakuItem,
    analyze_two_kanji_rendaku,
    collect_rendaku_items,
    make_rendaku_model,
    rendaku_note_text,
    voice_rendaku,
)


def kanji_subject(subject_id: int, char: str, *, readings: list[dict]) -> dict:
    return {
        "id": subject_id,
        "object": "kanji",
        "data": {
            "characters": char,
            "level": 5,
            "readings": readings,
        },
    }


def vocab_subject(
    subject_id: int,
    chars: str,
    reading: str,
    component_ids: list[int],
    *,
    level: int = 5,
) -> dict:
    return {
        "id": subject_id,
        "object": "vocabulary",
        "data": {
            "characters": chars,
            "level": level,
            "component_subject_ids": component_ids,
            "readings": [{"reading": reading, "primary": True, "accepted_answer": True}],
            "meanings": [{"meaning": "test meaning", "primary": True}],
        },
    }


class RendakuDeckTests(unittest.TestCase):
    def test_voice_rendaku(self) -> None:
        self.assertEqual(voice_rendaku("かわ"), "がわ")
        self.assertEqual(voice_rendaku("ひ"), "び")
        self.assertIsNone(voice_rendaku("ま"))

    def test_rendaku_note_text(self) -> None:
        self.assertEqual(rendaku_note_text("川", "かわ", "がわ"), "川: か → が (rendaku)")

    def test_analyze_yamagawa(self) -> None:
        mountain = kanji_subject(
            1,
            "山",
            readings=[
                {"reading": "やま", "type": "kunyomi", "primary": True},
                {"reading": "さん", "type": "onyomi"},
            ],
        )
        river = kanji_subject(
            2,
            "川",
            readings=[
                {"reading": "かわ", "type": "kunyomi", "primary": True},
                {"reading": "せん", "type": "onyomi"},
            ],
        )
        vocab = vocab_subject(10, "山川", "やまがわ", [1, 2])
        kanji_by_id = {1: mountain, 2: river}
        result = analyze_two_kanji_rendaku(vocab, kanji_by_id)
        self.assertIsNotNone(result)
        r1, r2_base, r2_voiced, second_char, reading = result
        self.assertEqual((r1, r2_base, r2_voiced, second_char, reading), ("やま", "かわ", "がわ", "川", "やまがわ"))

    def test_skips_plain_compound(self) -> None:
        left = kanji_subject(1, "大", readings=[{"reading": "おお", "type": "kunyomi", "primary": True}])
        right = kanji_subject(2, "学", readings=[{"reading": "がく", "type": "onyomi", "primary": True}])
        vocab = vocab_subject(10, "大学", "だいがく", [1, 2])
        self.assertIsNone(analyze_two_kanji_rendaku(vocab, {1: left, 2: right}))

    def test_collect_respects_min_srs(self) -> None:
        mountain = kanji_subject(1, "山", readings=[{"reading": "やま", "type": "kunyomi", "primary": True}])
        river = kanji_subject(2, "川", readings=[{"reading": "かわ", "type": "kunyomi", "primary": True}])
        vocab = vocab_subject(10, "山川", "やまがわ", [1, 2])
        assignment_index = {10: {"data": {"srs_stage": 1}}}
        items = collect_rendaku_items(
            [vocab],
            [mountain, river],
            assignment_index,
            min_srs=7,
        )
        self.assertEqual(items, [])
        assignment_index[10]["data"]["srs_stage"] = 7
        items = collect_rendaku_items(
            [vocab],
            [mountain, river],
            assignment_index,
            min_srs=7,
        )
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], RendakuItem)

    def test_rendaku_model_places_answer_audio_on_back_only(self) -> None:
        model = make_rendaku_model()
        qfmt = model.templates[0]["qfmt"]
        afmt = model.templates[0]["afmt"]
        self.assertNotIn("AnswerAudio", qfmt)
        self.assertIn("AnswerAudio", afmt)


if __name__ == "__main__":
    unittest.main()
