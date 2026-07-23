"""Tests for core_decks.py — prerequisite fields and subject selection."""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core_decks import (
    CORE_ITEM_KIND,
    CORE_RADICAL_KIND,
    all_core_vocab_subjects,
    format_prerequisite_ids,
    make_core_item_model,
    make_core_radical_model,
)
from wk_decks import NOTE_TYPE_NAMES, radical_subjects, stable_guid, subject_is_hidden


def mock_vocab(vocab_id: int, *, components: list[int], characters: str = "食べる") -> dict:
    return {
        "id": vocab_id,
        "object": "vocabulary",
        "data": {
            "characters": characters,
            "level": 5,
            "component_subject_ids": components,
            "meanings": [{"meaning": "to eat", "primary": True}],
            "readings": [{"reading": "たべる", "primary": True}],
        },
    }


def mock_kanji(kanji_id: int, *, components: list[int], characters: str = "食") -> dict:
    return {
        "id": kanji_id,
        "object": "kanji",
        "data": {
            "characters": characters,
            "level": 5,
            "component_subject_ids": components,
            "meanings": [{"meaning": "eat", "primary": True}],
            "readings": [{"reading": "しょく", "primary": True}],
        },
    }


class CoreDecksTests(unittest.TestCase):
    def test_prerequisite_ids_from_vocab(self) -> None:
        vocab = mock_vocab(100, components=[42])
        self.assertEqual(format_prerequisite_ids(vocab), "42")

    def test_prerequisite_ids_from_kanji_with_multiple_radicals(self) -> None:
        kanji = mock_kanji(200, components=[1, 2, 3])
        self.assertEqual(format_prerequisite_ids(kanji), "1,2,3")

    def test_prerequisite_ids_empty_for_radical(self) -> None:
        radical = {"id": 9, "object": "radical", "data": {"level": 1}}
        self.assertEqual(format_prerequisite_ids(radical), "")

    def test_stable_core_guids(self) -> None:
        self.assertEqual(stable_guid(CORE_RADICAL_KIND, 55), stable_guid("core-radical", 55))
        self.assertEqual(stable_guid(CORE_ITEM_KIND, 77), stable_guid("core-item", 77))

    def test_core_models_include_link_fields(self) -> None:
        radical_fields = [field["name"] for field in make_core_radical_model().fields]
        item_fields = [field["name"] for field in make_core_item_model().fields]
        self.assertIn("WkSubjectId", radical_fields)
        self.assertIn("PrerequisiteIds", radical_fields)
        self.assertIn("WkSubjectId", item_fields)
        self.assertIn("PrerequisiteIds", item_fields)
        self.assertIn("PhoneticHint", item_fields)

    def test_core_item_model_has_single_review_template(self) -> None:
        model = make_core_item_model()
        templates = [template["name"] for template in model.templates]
        self.assertEqual(templates, ["Review"])
        qfmt = model.templates[0]["qfmt"]
        self.assertIn("{{type:Reading}}", qfmt)
        self.assertNotIn("ReadingAudio", qfmt)
        afmt = model.templates[0]["afmt"]
        self.assertIn("{{Meaning}}", afmt)
        self.assertIn("ReadingAudio", afmt)

    def test_core_note_type_names(self) -> None:
        self.assertEqual(NOTE_TYPE_NAMES["core_radical"], "WK Core Radical")
        self.assertEqual(NOTE_TYPE_NAMES["core_item"], "WK Core Item")

    def test_all_core_vocab_subjects_excludes_hidden(self) -> None:
        visible = mock_vocab(1, components=[])
        hidden = mock_vocab(2, components=[])
        hidden["data"]["hidden_at"] = "2018-12-05T00:00:00Z"
        args = argparse.Namespace(max_level=60)
        selected = all_core_vocab_subjects([visible, hidden], args)
        self.assertEqual([item["id"] for item in selected], [1])

    def test_radical_subjects_excludes_hidden(self) -> None:
        visible = {
            "id": 1,
            "object": "radical",
            "data": {"level": 1, "meanings": [{"meaning": "Ground", "primary": True}]},
        }
        hidden = {
            "id": 59,
            "object": "radical",
            "data": {
                "level": 3,
                "hidden_at": "2018-12-05T18:38:50.736614Z",
                "meanings": [{"meaning": "Raptor Cage", "primary": True}],
            },
        }
        args = argparse.Namespace(max_level=60)
        selected = radical_subjects([visible, hidden], args)
        self.assertEqual([item["id"] for item in selected], [1])

    def test_subject_is_hidden(self) -> None:
        self.assertFalse(subject_is_hidden({"data": {}}))
        self.assertFalse(subject_is_hidden({"data": {"hidden_at": None}}))
        self.assertTrue(subject_is_hidden({"data": {"hidden_at": "2018-12-05T00:00:00Z"}}))

    def test_all_core_vocab_subjects_respects_max_level(self) -> None:
        subjects = [
            mock_vocab(1, components=[], characters="low"),
            mock_vocab(2, components=[], characters="high"),
        ]
        subjects[0]["data"]["level"] = 3
        subjects[1]["data"]["level"] = 10
        args = argparse.Namespace(max_level=5)
        selected = all_core_vocab_subjects(subjects, args)
        self.assertEqual([item["id"] for item in selected], [1])


if __name__ == "__main__":
    unittest.main()
