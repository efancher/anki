"""Tests for Satori → conjugation drills."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from satori_conjugation_decks import (
    SATORI_CONJ_EXPORT_FILENAME,
    build_satori_conjugations_from_csv,
    collect_satori_conjugation_drills,
    load_wk_conjugation_lemmas,
    satori_pos_to_word_class,
)
from satori_decks import SatoriCard, parse_satori_csv


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
        "CardID": "id-eat-je",
        "CardType": "JE",
        "Expression": "食べる",
        "Expression-ReadingsOnly": "たべる",
        "Expression-ReadingsInline": " 食[た]べる",
        "English": "to eat",
        "PartsOfSpeech": "v1",
        "Context1": "ご飯を食べる。",
        "Context1-ReadingsInline": " ご飯[はん]を 食[た]べる。",
        "Context1-Translation": "I eat a meal.",
        "UserNotes": "",
    },
    {
        "CardID": "id-noun-je",
        "CardType": "JE",
        "Expression": "机",
        "Expression-ReadingsOnly": "つくえ",
        "Expression-ReadingsInline": " 机[つくえ]",
        "English": "desk",
        "PartsOfSpeech": "n",
        "Context1": "机がある。",
        "Context1-ReadingsInline": " 机[つくえ]がある。",
        "Context1-Translation": "There is a desk.",
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


class SatoriConjugationTests(unittest.TestCase):
    def test_pos_map(self) -> None:
        self.assertEqual(satori_pos_to_word_class("adj-i"), "i_adjective")
        self.assertEqual(satori_pos_to_word_class("adj-na"), "na_adjective")
        self.assertEqual(satori_pos_to_word_class("v1"), "ichidan")
        self.assertEqual(satori_pos_to_word_class("v5r"), "godan")
        self.assertEqual(satori_pos_to_word_class("vs"), "suru_verb")
        self.assertEqual(satori_pos_to_word_class("vk"), "irregular_verb")
        self.assertIsNone(satori_pos_to_word_class("n"))
        self.assertIsNone(satori_pos_to_word_class(""))

    def test_collects_adj_and_verb_skips_noun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "export.csv"
            write_sample_csv(csv_path)
            cards = parse_satori_csv(csv_path)
        drills = collect_satori_conjugation_drills(cards)
        expressions = {drill.dict_expr for drill in drills}
        self.assertIn("暖かい", expressions)
        self.assertIn("食べる", expressions)
        self.assertNotIn("机", expressions)
        warm = [d for d in drills if d.dict_expr == "暖かい"]
        self.assertTrue(any(d.form_key == "plain_negative" for d in warm))
        eat = [d for d in drills if d.dict_expr == "食べる"]
        self.assertTrue(any(d.form_key == "te_form" and d.conj_reading == "たべて" for d in eat))

    def test_skip_wk_lemmas(self) -> None:
        cards = [
            SatoriCard(
                card_id="x",
                card_type="JE",
                expression="食べる",
                reading="たべる",
                expression_furigana="",
                english="to eat",
                parts_of_speech="v1",
                sentence="食べる。",
                sentence_furigana="",
                sentence_translation="",
                user_notes="",
            )
        ]
        drills = collect_satori_conjugation_drills(
            cards, skip_lemmas={("食べる", "たべる")}
        )
        self.assertEqual(drills, [])

    def test_load_lemmas_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lemmas.json"
            path.write_text('{"lemmas": [["食べる", "たべる"]]}', encoding="utf-8")
            lemmas = load_wk_conjugation_lemmas(path)
        self.assertEqual(lemmas, {("食べる", "たべる")})

    def test_build_apkg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "export.csv"
            write_sample_csv(csv_path)
            apkg, deck, drills = build_satori_conjugations_from_csv(csv_path, Path(tmp))
            self.assertTrue(apkg.is_file())
            self.assertEqual(apkg.name, SATORI_CONJ_EXPORT_FILENAME)
            self.assertGreater(len(deck.notes), 0)
            self.assertEqual(len(deck.notes), len(drills))


if __name__ == "__main__":
    unittest.main()
