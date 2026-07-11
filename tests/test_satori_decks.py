"""Tests for Satori Reader → Immersion · Satori import."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from satori_decks import (
    SATORI_DECK_NAME,
    SATORI_NOTE_TYPE_NAME,
    build_satori_deck,
    make_satori_model,
    parse_satori_csv,
    satori_note_fields,
)


SAMPLE_ROWS = [
    {
        "CardID": "id-warm-je",
        "CardType": "JE",
        "Expression": "暖かい",
        "Expression-ReadingsOnly": "あたたかい",
        "Expression-ReadingsInline": " 暖[あたた]かい",
        "English": "warm (air temperature)",
        "PartsOfSpeech": "adj-i",
        "Context1": "暖かい春がやって来ました。",
        "Context1-ReadingsInline": " 暖[あたた]かい 春[はる]がやって 来[き]ました。",
        "Context1-Translation": "The warm spring came along.",
        "UserNotes": "",
    },
    {
        "CardID": "id-warm-ej",
        "CardType": "EJ",
        "Expression": "暖かい",
        "Expression-ReadingsOnly": "あたたかい",
        "Expression-ReadingsInline": " 暖[あたた]かい",
        "English": "warm (air temperature)",
        "PartsOfSpeech": "adj-i",
        "Context1": "暖かい春がやって来ました。",
        "Context1-ReadingsInline": " 暖[あたた]かい 春[はる]がやって 来[き]ました。",
        "Context1-Translation": "The warm spring came along.",
        "UserNotes": "",
    },
]


def write_sample_csv(path: Path, rows=None) -> None:
    rows = rows or SAMPLE_ROWS
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class SatoriDecksTests(unittest.TestCase):
    def test_parse_defaults_to_je_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "export.csv"
            write_sample_csv(csv_path)
            cards = parse_satori_csv(csv_path)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].expression, "暖かい")
        self.assertEqual(cards[0].card_type, "JE")

    def test_parse_include_ej(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "export.csv"
            write_sample_csv(csv_path)
            cards = parse_satori_csv(csv_path, card_types=("JE", "EJ"))
        self.assertEqual(len(cards), 2)

    def test_note_fields_keep_english_and_cloze(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "export.csv"
            write_sample_csv(csv_path)
            card = parse_satori_csv(csv_path)[0]
        fields = satori_note_fields(card)
        model = make_satori_model()
        by_name = {field["name"]: value for field, value in zip(model.fields, fields)}
        self.assertEqual(by_name["Expression"], "暖かい")
        self.assertEqual(by_name["Reading"], "あたたかい")
        self.assertEqual(by_name["WkMeaning"], "warm (air temperature)")
        self.assertEqual(by_name["Translation"], "The warm spring came along.")
        self.assertIn("cloze-blank", by_name["ClozeSentence"])
        self.assertNotIn("暖かい", by_name["ClozeSentence"])
        self.assertEqual(by_name["SourceTitle"], "Satori Reader")
        self.assertEqual(by_name["ShowKana"], "")
        self.assertIn("暖[あたた]かい", by_name["Furigana"])
        self.assertIn("春[はる]", by_name["SentenceFurigana"])

    def test_templates_keep_kana_off_front_and_use_furigana_filter(self) -> None:
        model = make_satori_model()
        front = model.templates[0]["qfmt"]
        back = model.templates[0]["afmt"]
        self.assertIn("{{type:Reading}}", front)
        self.assertNotIn("ShowKana", front)
        self.assertNotIn("hint-reading", front)
        self.assertIn("{{furigana:SentenceFurigana}}", back)
        self.assertIn("{{furigana:Furigana}}", back)
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "export.csv"
            write_sample_csv(csv_path)
            cards = parse_satori_csv(csv_path)
            apkg_path, deck = build_satori_deck(cards, Path(tmp))
            self.assertTrue(apkg_path.is_file())
            self.assertEqual(deck.name, SATORI_DECK_NAME)
            self.assertEqual(len(deck.notes), 1)
            self.assertEqual(SATORI_NOTE_TYPE_NAME, "WK Satori Immersion")


if __name__ == "__main__":
    unittest.main()
