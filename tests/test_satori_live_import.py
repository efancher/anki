"""Tests for live Satori AnkiConnect import helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from satori_decks import SatoriCard, satori_note_field_map, satori_note_tags
from satori_live_import import (
    build_satori_note_index,
    fields_need_update,
    merge_satori_fields_for_update,
    resolve_existing_note_id,
)


def _card(**overrides: str) -> SatoriCard:
    base = {
        "card_id": "id-1",
        "card_type": "JE",
        "expression": "青い",
        "reading": "あおい",
        "expression_furigana": "",
        "english": "blue",
        "parts_of_speech": "adj-i",
        "sentence": "空は青い。",
        "sentence_furigana": "",
        "sentence_translation": "The sky is blue.",
        "user_notes": "",
    }
    base.update(overrides)
    return SatoriCard(**base)  # type: ignore[arg-type]


class SatoriLiveImportTests(unittest.TestCase):
    def test_merge_preserves_nonempty_audio(self) -> None:
        new_fields = {
            "Expression": "青い",
            "SentenceAudio": "",
            "Audio": "",
            "ReadingAudio": "[sound:new.mp3]",
        }
        existing = {
            "Expression": "古い",
            "SentenceAudio": "[sound:old_sentence.mp3]",
            "Audio": "[sound:old_target.mp3]",
            "ReadingAudio": "",
        }
        merged = merge_satori_fields_for_update(new_fields, existing)
        self.assertEqual(merged["Expression"], "青い")
        self.assertEqual(merged["SentenceAudio"], "[sound:old_sentence.mp3]")
        self.assertEqual(merged["Audio"], "[sound:old_target.mp3]")
        self.assertEqual(merged["ReadingAudio"], "[sound:new.mp3]")

    def test_resolve_by_duplicate_key(self) -> None:
        fields = satori_note_field_map(_card())
        note = {
            "noteId": 99,
            "fields": {"DuplicateKey": {"value": fields["DuplicateKey"]}},
        }
        by_key, by_card_id = build_satori_note_index([note])
        found = resolve_existing_note_id(
            _card(),
            fields,
            by_key=by_key,
            by_card_id=by_card_id,
            notes_by_id={99: note},
        )
        self.assertEqual(found, 99)

    def test_resolve_by_card_id_when_sentence_field_differs(self) -> None:
        """Same Satori CardID still matches if DuplicateKey sentence drift."""
        live_key = "id-1|青い|空は青いです。"
        note = {
            "noteId": 42,
            "fields": {
                "DuplicateKey": {"value": live_key},
                "Expression": {"value": "青い"},
                "Sentence": {"value": "空は青いです。"},
            },
        }
        by_key, by_card_id = build_satori_note_index([note])
        fields = satori_note_field_map(_card())  # sentence without です
        self.assertNotEqual(fields["DuplicateKey"], live_key)
        found = resolve_existing_note_id(
            _card(),
            fields,
            by_key=by_key,
            by_card_id=by_card_id,
            notes_by_id={42: note},
        )
        self.assertEqual(found, 42)

    def test_fields_need_update(self) -> None:
        self.assertTrue(
            fields_need_update(
                {"Expression": "a"},
                {"Expression": "b"},
                model_fields=["Expression"],
            )
        )
        self.assertFalse(
            fields_need_update(
                {"Expression": "a", "Audio": ""},
                {"Expression": "a", "Audio": "[sound:x.mp3]"},
                model_fields=["Expression"],
            )
        )

    def test_tags_include_satori_mining(self) -> None:
        tags = satori_note_tags(_card())
        self.assertIn("satori-mining", tags)
        self.assertIn("satori-je", tags)


if __name__ == "__main__":
    unittest.main()
