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
    resolve_satori_word_meaning,
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

    def test_fallback_meaning_when_csv_english_blank(self) -> None:
        self.assertEqual(
            resolve_satori_word_meaning("そして"),
            "and; and then",
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "export.csv"
            write_sample_csv(
                csv_path,
                [
                    {
                        "CardID": "id-soshite",
                        "CardType": "JE",
                        "Expression": "そして",
                        "Expression-ReadingsOnly": "そして",
                        "Expression-ReadingsInline": "そして",
                        "English": "",
                        "PartsOfSpeech": "conj",
                        "Context1": "そして、真似をして羽をバタバタさせていました。",
                        "Context1-ReadingsInline": "そして、真似をして羽をバタバタさせていました。",
                        "Context1-Translation": "And, imitating, they were flapping their wings.",
                        "UserNotes": "",
                    }
                ],
            )
            card = parse_satori_csv(csv_path)[0]
        fields = satori_note_fields(card)
        model = make_satori_model()
        by_name = {field["name"]: value for field, value in zip(model.fields, fields)}
        self.assertEqual(by_name["WkMeaning"], "and; and then")

    def test_templates_keep_kana_off_front_and_use_furigana_filter(self) -> None:
        model = make_satori_model()
        front = model.templates[0]["qfmt"]
        back = model.templates[0]["afmt"]
        self.assertIn("{{type:Reading}}", front)
        self.assertNotIn("ShowKana", front)
        self.assertNotIn("ShowEnglish", front)
        self.assertIn("{{WkMeaning}}", front)
        self.assertIn("{{HintGlossary}}", front)
        self.assertIn("{{{DictLinksEn}}}", front)
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

    def test_conjugated_verb_highlights_full_surface(self) -> None:
        cloze, plain = build_satori_cloze_sentence(
            "ある小鳥の夫婦が、木に巣を作りました。", "作る", "つくる"
        )
        self.assertIn('<span class="cloze-target">作</span>', cloze)
        self.assertIn('<span class="cloze-inflection">りました</span>', cloze)
        self.assertNotIn("cloze-blank", cloze)
        self.assertEqual(plain, "ある小鳥の夫婦が、木に巣を作りました。")

    def test_okurigana_noun_highlights_full_word(self) -> None:
        cloze, _ = build_satori_cloze_sentence(
            "しかし、最後の１羽は怖がりで、なかなか飛び出すことができませんでした",
            "怖がり",
            "こわがり",
        )
        self.assertIn('<span class="cloze-target">怖がり</span>', cloze)
        self.assertNotIn("cloze-inflection", cloze)
        self.assertNotIn(">怖<", cloze)

    def test_conjugated_adjective_two_tone_core_and_inflection(self) -> None:
        cloze, _ = build_satori_cloze_sentence(
            "空は青くて、木々の緑がきれいでした。",
            "青い",
            "あおい",
        )
        self.assertIn('<span class="cloze-target">青</span>', cloze)
        self.assertIn('<span class="cloze-inflection">くて</span>', cloze)
        self.assertNotIn(">青くて<", cloze)

    def test_all_kanji_noun_does_not_swallow_following_kana(self) -> None:
        cloze, _ = build_satori_cloze_sentence(
            "日本ではありません。", "日本", "にほん"
        )
        self.assertIn('<span class="cloze-target">日本</span>', cloze)
        self.assertIn("ではありません", cloze)
        self.assertNotIn("日本ではありません</span>", cloze)

    def test_desu_negative_aru_form_is_not_forced_cloze(self) -> None:
        # ではありません is で+は+ありません (ある), not a transparent です form.
        cloze, plain = build_satori_cloze_sentence(
            "日本ではありません。", "です", "です"
        )
        self.assertEqual(plain, "日本ではありません。")
        self.assertNotIn("cloze-blank", cloze)
        self.assertNotIn("cloze-target", cloze)
        from satori_decks import should_skip_copula_cloze

        self.assertTrue(
            should_skip_copula_cloze("です", "です", "日本ではありません。")
        )
        self.assertFalse(should_skip_copula_cloze("です", "です", "彼は学生です。"))
        self.assertFalse(should_skip_copula_cloze("日本", "にほん", "日本ではありません。"))

    def test_desu_transparent_past_is_blanked(self) -> None:
        cloze, _ = build_satori_cloze_sentence("彼は学生でした。", "です", "です")
        self.assertIn("cloze-blank", cloze)
        self.assertIn("学生", cloze)

    def test_conjugated_adjective_like_verb_highlights_surface(self) -> None:
        cloze, _ = build_satori_cloze_sentence(
            "お母さん鳥は喜んで、ひなと一緒に飛びました。",
            "喜ぶ",
            "よろこぶ",
        )
        self.assertIn('<span class="cloze-target">喜</span>', cloze)
        self.assertIn('<span class="cloze-inflection">んで</span>', cloze)

    def test_compound_verb_highlights_full_surface(self) -> None:
        cloze, _ = build_satori_cloze_sentence(
            "暖かい春がやって来ました。",
            "やって来る",
            "やってくる",
        )
        self.assertIn('<span class="cloze-target">やって来</span>', cloze)
        self.assertIn('<span class="cloze-inflection">ました</span>', cloze)
        self.assertNotIn(">来<", cloze)

    def test_explicit_surface_is_expanded(self) -> None:
        cloze, _ = build_satori_cloze_sentence(
            "暖かい春がやって来ました。",
            "やって来る",
            "やってくる",
            surface="来ました",
        )
        self.assertIn('<span class="cloze-target">やって来</span>', cloze)
        self.assertIn('<span class="cloze-inflection">ました</span>', cloze)

    def test_all_kanji_noun_highlighted_whole(self) -> None:
        cloze, _ = build_satori_cloze_sentence(
            "ある小鳥の夫婦が、木に巣を作りました。", "小鳥", "ことり"
        )
        self.assertIn('<span class="cloze-target">小鳥</span>', cloze)
        self.assertNotIn("cloze-blank", cloze)

    def test_surface_span_text_matches_highlighted_span(self) -> None:
        from satori_decks import surface_span_text

        self.assertEqual(
            surface_span_text(
                "暖かい春がやって来ました。", "やって来る", "やってくる"
            ),
            "やって来ました",
        )
        self.assertEqual(
            surface_span_text(
                "お母さん鳥は喜んで、ひなと一緒に飛びました。",
                "喜ぶ",
                "よろこぶ",
            ),
            "喜んで",
        )

    def test_hiragana_only_word_is_blanked(self) -> None:
        cloze, _ = build_satori_cloze_sentence("これはとても綺麗だ。", "とても", "とても")
        self.assertIn("cloze-blank", cloze)
        self.assertNotIn("cloze-target", cloze)
        self.assertNotIn("とても", cloze)


if __name__ == "__main__":
    unittest.main()
