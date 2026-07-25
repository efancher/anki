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
        self.assertIn("{{Audio}}", back)
        self.assertIn("{{ReadingAudio}}", back)
        self.assertIn("Target", back)
        self.assertIn("Reading", back)
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

    def test_exact_lemma_does_not_swallow_following_clause(self) -> None:
        from satori_decks import surface_span_text

        sentence = "ああ、年は同じかもしれないけど、俺バイトでは先輩だよ。"
        self.assertEqual(surface_span_text(sentence, "同じ", "おなじ"), "同じ")
        cloze, _ = build_satori_cloze_sentence(sentence, "同じ", "おなじ")
        self.assertIn('<span class="cloze-target">同じ</span>', cloze)
        self.assertIn("かもしれない", cloze)
        self.assertNotIn("cloze-inflection", cloze)

    def test_conjugation_growth_stops_before_katakana(self) -> None:
        from satori_decks import surface_span_text

        sentence = "授業来ないでアルバイトしてたこともあるよ。"
        self.assertEqual(surface_span_text(sentence, "来る", "くる"), "来ないで")
        cloze, _ = build_satori_cloze_sentence(sentence, "来る", "くる")
        self.assertIn('<span class="cloze-target">来</span>', cloze)
        self.assertIn('<span class="cloze-inflection">ないで</span>', cloze)
        self.assertIn("アルバイト", cloze)

    def test_conjugation_growth_stops_before_kudasai(self) -> None:
        from satori_decks import surface_span_text

        self.assertEqual(
            surface_span_text("いいから教えてくださいよ。", "教える", "おしえる"),
            "教えて",
        )

    def test_stem_does_not_match_inside_kanji_compound(self) -> None:
        from satori_decks import surface_span_text

        # 任す must not latch onto 任 inside 担任
        self.assertEqual(
            surface_span_text(
                "同じだ。俺の担任もひ先生だったんだよ。", "任す", "まかす"
            ),
            "",
        )

    def test_senpai_highlights_only_lemma(self) -> None:
        cloze, _ = build_satori_cloze_sentence(
            "あの、し吾先輩っておいくつなんですか?", "先輩", "せんぱい"
        )
        self.assertIn('<span class="cloze-target">先輩</span>', cloze)
        self.assertIn("っておいくつ", cloze)
        self.assertNotIn("cloze-inflection", cloze)

    def test_kanji_lemma_with_kana_surface_is_blanked(self) -> None:
        """達 appears as たち in the sentence — blank, don't highlight the kana."""
        sentence = "巣から、３羽のひなたちが顔を出しました。"
        cloze, _ = build_satori_cloze_sentence(sentence, "達", "たち")
        self.assertIn("cloze-blank", cloze)
        self.assertNotIn("cloze-target", cloze)
        self.assertIn("ひな", cloze)
        self.assertNotIn("たち", cloze)

    def test_hiragana_only_word_is_blanked(self) -> None:
        cloze, _ = build_satori_cloze_sentence("これはとても綺麗だ。", "とても", "とても")
        self.assertIn("cloze-blank", cloze)
        self.assertNotIn("cloze-target", cloze)
        self.assertNotIn("とても", cloze)

    def test_kana_lemma_does_not_swallow_pluralizer(self) -> None:
        from satori_decks import surface_span_text

        sentence = "巣から、３羽のひなたちが顔を出しました。"
        self.assertEqual(surface_span_text(sentence, "ひな", "ひな"), "ひな")
        cloze, _ = build_satori_cloze_sentence(sentence, "ひな", "ひな")
        self.assertIn("cloze-blank", cloze)
        self.assertIn("たち", cloze)
        self.assertNotIn("ひな", cloze)

    def test_kana_particle_does_not_swallow_following_word(self) -> None:
        from satori_decks import surface_span_text

        sentence = "ひなたちは大きな声でピーピーと鳴いて、口を大きく開けました。"
        self.assertEqual(surface_span_text(sentence, "で", "で"), "で")
        cloze, _ = build_satori_cloze_sentence(sentence, "で", "で")
        self.assertIn("ピーピー", cloze)

    def test_okurigana_noun_does_not_mark_pluralizer_as_inflection(self) -> None:
        cloze, _ = build_satori_cloze_sentence(
            "子どもたちが遊んだ。", "子ども", "こども"
        )
        self.assertIn('<span class="cloze-target">子ども</span>', cloze)
        self.assertNotIn("cloze-inflection", cloze)
        self.assertIn("たち", cloze)


class ConjugatedSurfaceMatchTests(unittest.TestCase):
    """Lemmas that only ever appear conjugated in the sentence."""

    def surface(self, sentence: str, expression: str, reading: str) -> str:
        from satori_decks import surface_span_text

        return surface_span_text(sentence, expression, reading)

    def test_suru_matches_polite_past(self) -> None:
        sentence = "親鳥たちは、毎日、一生懸命にひなたちの世話をしました。"
        self.assertEqual(self.surface(sentence, "する", "する"), "しました")
        cloze, _ = build_satori_cloze_sentence(sentence, "する", "する")
        self.assertIn("cloze-blank", cloze)
        self.assertIn("世話を", cloze)
        self.assertNotIn("しました", cloze)

    def test_kana_godan_verb_matches_polite_past(self) -> None:
        self.assertEqual(
            self.surface("とためらいました。", "ためらう", "ためらう"),
            "ためらいました",
        )
        self.assertEqual(
            self.surface("大きくなりました。", "なる", "なる"), "なりました"
        )

    def test_kana_ichidan_verb_matches_polite_past_negative(self) -> None:
        self.assertEqual(
            self.surface("飛び出すことができませんでした。", "できる", "できる"),
            "できませんでした",
        )

    def test_longest_form_wins_over_nested_shorter_form(self) -> None:
        """できました must not be clipped to できた/きた."""
        self.assertEqual(
            self.surface("なんとか飛ぶことができました。", "できる", "できる"),
            "できました",
        )

    def test_i_adjective_adverbial_and_evidential(self) -> None:
        self.assertEqual(
            self.surface("飛ぶのって、すごく楽しいね！", "すごい", "すごい"), "すごく"
        )
        self.assertEqual(
            self.surface("おいしそうにえさを食べました。", "おいしい", "おいしい"),
            "おいしそう",
        )

    def test_two_kana_adjective_does_not_generate_colliding_forms(self) -> None:
        """いい must not reach 行く through a bogus いく form."""
        self.assertEqual(self.surface("今から飲み行くの?", "いい", "いい"), "")

    def test_short_kanji_adjective_matches_evidential(self) -> None:
        sentence = "なんか仕事中偉そうな態度を取ってしまってすいません。"
        self.assertEqual(self.surface(sentence, "偉い", "えらい"), "偉そう")

    def test_kanji_lemma_matches_kana_spelling(self) -> None:
        """来る is written き in 飛んできました."""
        sentence = "タカが飛んできました。"
        self.assertEqual(self.surface(sentence, "来る", "くる"), "きました")
        cloze, _ = build_satori_cloze_sentence(sentence, "来る", "くる")
        self.assertIn("cloze-blank", cloze)
        self.assertIn("飛んで", cloze)

    def test_kana_lemma_matches_katakana_spelling(self) -> None:
        sentence = "外の世界には、怖いワシやタカもいるの。"
        self.assertEqual(self.surface(sentence, "わし", "わし"), "ワシ")
        cloze, _ = build_satori_cloze_sentence(sentence, "わし", "わし")
        self.assertIn("cloze-blank", cloze)
        self.assertIn("タカ", cloze)
        self.assertNotIn("ワシ", cloze)

    def test_suru_does_not_claim_the_tail_of_a_compound_verb(self) -> None:
        """電話しました belongs to 電話する, and した must not be cut out of it."""
        self.assertEqual(self.surface("電話しました。", "する", "する"), "")

    def test_suru_does_not_match_an_unrelated_verbs_stem(self) -> None:
        self.assertEqual(self.surface("彼は話した。", "する", "する"), "")

    def test_potential_form_is_not_matched_as_suru(self) -> None:
        """できる is する's potential but has its own card — don't steal it."""
        self.assertEqual(self.surface("それができる。", "する", "する"), "")

    def test_conjugated_match_does_not_displace_an_exact_hit(self) -> None:
        sentence = "親鳥たちは、毎日、一生懸命にひなたちの世話をしました。"
        cloze, _ = build_satori_cloze_sentence(sentence, "世話", "せわ")
        self.assertIn('<span class="cloze-target">世話</span>', cloze)
        self.assertIn("しました", cloze)


if __name__ == "__main__":
    unittest.main()
