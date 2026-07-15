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
    build_satori_cloze_sentence,
    build_satori_deck,
    kanji_stem,
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
        # 暖かい has a kanji stem (暖) → highlight it, do not blank.
        self.assertIn("cloze-target", by_name["ClozeSentence"])
        self.assertIn("暖", by_name["ClozeSentence"])
        self.assertNotIn("cloze-blank", by_name["ClozeSentence"])
        self.assertEqual(by_name["SourceTitle"], "Satori Reader")
        self.assertEqual(by_name["ShowKana"], "")
        self.assertEqual(by_name["ShowEnglish"], "1")
        self.assertIn("暖[あたた]かい", by_name["Furigana"])
        self.assertIn("春[はる]", by_name["SentenceFurigana"])

    def test_templates_keep_kana_off_front_and_use_furigana_filter(self) -> None:
        model = make_satori_model()
        front = model.templates[0]["qfmt"]
        back = model.templates[0]["afmt"]
        self.assertIn("{{type:Reading}}", front)
        self.assertNotIn("ShowKana", front)
        self.assertNotIn("ShowEnglish", front)
        self.assertIn("{{WkMeaning}}", front)
        self.assertNotIn("hint-reading", front)
        self.assertIn("{{furigana:SentenceFurigana}}", back)
        self.assertIn("{{furigana:Furigana}}", back)
        self.assertIn("{{SentenceAudio}}", back)
        self.assertIn("{{SentenceAudioEasy}}", back)
        self.assertIn("Normal", back)
        self.assertIn("Easy", back)
        self.assertIn("sentence-audio-manual", back)
        self.assertLess(back.index("Easy"), back.index("Normal"))
        self.assertIn("{{tts ja_JP:Sentence}}", back)
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "export.csv"
            write_sample_csv(csv_path)
            cards = parse_satori_csv(csv_path)
            apkg_path, deck = build_satori_deck(cards, Path(tmp))
            self.assertTrue(apkg_path.is_file())
            self.assertEqual(deck.name, SATORI_DECK_NAME)
            self.assertEqual(len(deck.notes), 1)
            self.assertEqual(SATORI_NOTE_TYPE_NAME, "WK Satori Immersion")


class SatoriClozeTests(unittest.TestCase):
    def test_kanji_stem(self) -> None:
        self.assertEqual(kanji_stem("作る"), "作")
        self.assertEqual(kanji_stem("小鳥"), "小鳥")
        self.assertEqual(kanji_stem("暖かい"), "暖")
        self.assertEqual(kanji_stem("持ち込む"), "持ち込")
        self.assertEqual(kanji_stem("ある"), "")

    def test_conjugated_verb_highlights_kanji_stem(self) -> None:
        cloze, plain = build_satori_cloze_sentence(
            "ある小鳥の夫婦が、木に巣を作りました。", "作る", "つくる"
        )
        self.assertIn('<span class="cloze-target">作</span>', cloze)
        self.assertNotIn("cloze-blank", cloze)
        # Okurigana stays visible next to the highlighted kanji.
        self.assertIn("作</span>りました", cloze)
        self.assertEqual(plain, "ある小鳥の夫婦が、木に巣を作りました。")

    def test_all_kanji_noun_highlighted_whole(self) -> None:
        cloze, _ = build_satori_cloze_sentence(
            "ある小鳥の夫婦が、木に巣を作りました。", "小鳥", "ことり"
        )
        self.assertIn('<span class="cloze-target">小鳥</span>', cloze)
        self.assertNotIn("cloze-blank", cloze)

    def test_hiragana_only_word_is_blanked(self) -> None:
        cloze, _ = build_satori_cloze_sentence("これはとても綺麗だ。", "とても", "とても")
        self.assertIn("cloze-blank", cloze)
        self.assertNotIn("cloze-target", cloze)
        self.assertNotIn("とても", cloze)


if __name__ == "__main__":
    unittest.main()
