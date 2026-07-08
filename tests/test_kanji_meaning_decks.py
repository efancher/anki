"""Tests for the Kanji Meaning Anchor supplementary deck."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kanji_meaning_decks import (
    KanjiMeaningItem,
    build_kanji_meaning_deck,
    collect_kanji_meaning_items,
    make_kanji_meaning_model,
)
from wk_decks import WK_SRS_STAGE_GURU_1


def kanji_subject(subject_id: int, char: str, meanings: list, *, level: int = 5) -> dict:
    return {
        "id": subject_id,
        "object": "kanji",
        "data": {
            "characters": char,
            "level": level,
            "meanings": meanings,
        },
    }


class KanjiMeaningDeckTests(unittest.TestCase):
    def test_collect_uses_primary_meaning(self) -> None:
        kanji = kanji_subject(
            1,
            "水",
            [
                {"meaning": "Water", "primary": True},
                {"meaning": "Aqua", "primary": False},
            ],
        )
        items = collect_kanji_meaning_items([kanji], {})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].expression, "水")
        self.assertEqual(items[0].meaning, "Water")

    def test_collect_skips_kanji_without_meanings(self) -> None:
        kanji = kanji_subject(2, "火", [])
        self.assertEqual(collect_kanji_meaning_items([kanji], {}), [])

    def test_collect_respects_min_srs(self) -> None:
        kanji = kanji_subject(42, "木", [{"meaning": "Tree", "primary": True}])
        assignment_index = {42: {"data": {"subject_id": 42, "srs_stage": 1}}}
        self.assertEqual(
            collect_kanji_meaning_items([kanji], assignment_index, min_srs=WK_SRS_STAGE_GURU_1),
            [],
        )
        assignment_index[42]["data"]["srs_stage"] = WK_SRS_STAGE_GURU_1
        items = collect_kanji_meaning_items([kanji], assignment_index, min_srs=WK_SRS_STAGE_GURU_1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].expression, "木")

    def test_model_front_shows_only_kanji(self) -> None:
        model = make_kanji_meaning_model()
        qfmt = model.templates[0]["qfmt"]
        afmt = model.templates[0]["afmt"]
        self.assertIn("{{Expression}}", qfmt)
        self.assertNotIn("{{Meaning}}", qfmt)
        self.assertIn("{{Meaning}}", afmt)

    def test_build_deck_has_no_unlock_tags(self) -> None:
        kanji = kanji_subject(99, "山", [{"meaning": "Mountain", "primary": True}])
        item = KanjiMeaningItem(kanji=kanji, expression="山", meaning="Mountain")
        assignment_index = {99: {"data": {"subject_id": 99, "srs_stage": 1}}}

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            apkg_path, deck = build_kanji_meaning_deck([item], output_dir, assignment_index)
            self.assertEqual(apkg_path.name, "wk_kanji_meaning.apkg")
            self.assertEqual(len(deck.notes), 1)
            note = deck.notes[0]
            self.assertEqual(note.fields[1], "99")
            self.assertEqual(note.fields[2], "山")
            self.assertEqual(note.fields[3], "Mountain")
            self.assertNotIn("wk-locked", note.tags)
            self.assertIn("kanji-meaning", note.tags)

    def test_build_deck_never_adds_locked_tag(self) -> None:
        kanji = kanji_subject(100, "川", [{"meaning": "River", "primary": True}])
        item = KanjiMeaningItem(kanji=kanji, expression="川", meaning="River")
        assignment_index = {100: {"data": {"subject_id": 100, "srs_stage": WK_SRS_STAGE_GURU_1}}}

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            _, deck = build_kanji_meaning_deck([item], output_dir, assignment_index)
            note = deck.notes[0]
            self.assertNotIn("wk-locked", note.tags)


if __name__ == "__main__":
    unittest.main()
