"""Tests for Shadowing WK morphology matching and candidate filtering."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shadowing_match import (  # noqa: E402
    candidate_lemmas_in_sentence,
    conjugation_match_key,
    has_spoken_japanese,
    kanji_stem,
    katakana_to_hiragana,
    match_wk_vocab_in_sentence,
    reading_for_candidate_lemma,
    tokenize_japanese,
)


def _index(*entries: dict) -> dict:
    by_expression = {}
    by_reading = {}
    for entry in entries:
        expr = entry["expression"]
        by_expression[expr] = entry
        reading = entry.get("reading") or ""
        if reading:
            by_reading.setdefault(reading, []).append(entry["id"])
    return {"by_expression": by_expression, "by_reading": by_reading}


class KanjiStemTests(unittest.TestCase):
    def test_stem_from_first_to_last_kanji(self) -> None:
        self.assertEqual(kanji_stem("食べる"), "食")
        self.assertEqual(kanji_stem("分かります"), "分")
        self.assertEqual(kanji_stem("友達"), "友達")
        self.assertEqual(kanji_stem("ありがとう"), "")


class ConjugationMatchKeyTests(unittest.TestCase):
    def test_drops_only_trailing_okurigana(self) -> None:
        self.assertEqual(conjugation_match_key("食べる"), "食")
        self.assertEqual(conjugation_match_key("やって来る"), "やって来")
        self.assertEqual(conjugation_match_key("お知らせ"), "お知")
        self.assertEqual(conjugation_match_key("お姉さん"), "お姉")
        self.assertEqual(conjugation_match_key("友達"), "友達")
        self.assertEqual(conjugation_match_key("ありがとう"), "")

    def test_keeps_numeric_prefix_but_drops_placeholder_tilde(self) -> None:
        self.assertEqual(conjugation_match_key("２０１１年"), "２０１１年")
        self.assertEqual(conjugation_match_key("〜歳"), "歳")
        self.assertEqual(conjugation_match_key("〜君"), "君")


class ReadingNormalizeTests(unittest.TestCase):
    def test_katakana_lemma_becomes_hiragana_reading(self) -> None:
        self.assertEqual(katakana_to_hiragana("センパイ"), "せんぱい")
        self.assertEqual(reading_for_candidate_lemma("バイト"), "ばいと")
        self.assertEqual(reading_for_candidate_lemma("マジ"), "まじ")
        self.assertEqual(reading_for_candidate_lemma("先輩", "センパイ"), "せんぱい")
        self.assertEqual(reading_for_candidate_lemma("吾先輩"), "")

    def test_shogo_asr_name_uses_shogo_not_ware(self) -> None:
        from shadowing_match import reading_for_surface_in_sentence

        sentence = "あの、し吾先輩っておいくつなんですか?"
        self.assertEqual(
            reading_for_surface_in_sentence(sentence, "吾先輩"),
            "しょごせんぱい",
        )
        self.assertEqual(
            reading_for_surface_in_sentence(sentence, "し吾先輩"),
            "しょごせんぱい",
        )


class MatchWkVocabTests(unittest.TestCase):
    def test_exact_expression_match(self) -> None:
        index = _index(
            {
                "id": 1,
                "expression": "友達",
                "reading": "ともだち",
                "meaning": "friend",
                "prerequisite_ids": "10,20",
            }
        )
        matches = match_wk_vocab_in_sentence("友達が来ました。", index)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].expression, "友達")
        self.assertEqual(matches[0].wk_entry["id"], 1)

    def test_conjugated_kanji_verb_matches_stem(self) -> None:
        index = _index(
            {
                "id": 2,
                "expression": "食べる",
                "reading": "たべる",
                "meaning": "to eat",
                "prerequisite_ids": "30",
            }
        )
        matches = match_wk_vocab_in_sentence("昨日すしを食べました。", index)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].expression, "食べる")
        # Fugashi surface is the written stem 食べ; longest-match stem is 食.
        self.assertIn(matches[0].surface, {"食", "食べ"})

    def test_multiple_matches_one_per_subject(self) -> None:
        index = _index(
            {
                "id": 3,
                "expression": "今日",
                "reading": "きょう",
                "meaning": "today",
                "prerequisite_ids": "",
            },
            {
                "id": 4,
                "expression": "行く",
                "reading": "いく",
                "meaning": "to go",
                "prerequisite_ids": "",
            },
        )
        matches = match_wk_vocab_in_sentence("今日どこへ行きますか。", index)
        self.assertEqual({m.expression for m in matches}, {"今日", "行く"})
        self.assertEqual(len(matches), 2)

    def test_compound_token_still_matches_wk_stem_inside(self) -> None:
        """UniDic may emit 同い年 as one token; 同じ must still match via stem."""
        index = _index(
            {
                "id": 2662,
                "expression": "２０１１年",
                "reading": "にせんじゅういちねん",
                "meaning": "Year 2011",
                "prerequisite_ids": "546",
            },
            {
                "id": 2747,
                "expression": "同じ",
                "reading": "おなじ",
                "meaning": "same",
                "prerequisite_ids": "568",
            },
            {
                "id": 3413,
                "expression": "年",
                "reading": "とし",
                "meaning": "year",
                "prerequisite_ids": "",
            },
        )
        matches = match_wk_vocab_in_sentence("え、同い年じゃないですか?", index)
        expressions = [m.expression for m in matches]
        self.assertIn("同じ", expressions)
        self.assertNotIn("２０１１年", expressions)

    def test_chuukowai_compound_not_split_into_naka_and_kowai(self) -> None:
        """バイト中怖い is ちゅうこわい, not WK 中/なか + 怖い."""
        index = _index(
            {
                "id": 2520,
                "expression": "中",
                "reading": "なか",
                "meaning": "Inside; In",
                "prerequisite_ids": "",
            },
            {
                "id": 5233,
                "expression": "怖い",
                "reading": "こわい",
                "meaning": "Scary",
                "prerequisite_ids": "",
            },
            {
                "id": 3005,
                "expression": "君",
                "reading": "きみ",
                "meaning": "you",
                "prerequisite_ids": "",
            },
        )
        sentence = "だってし吾君バイト中怖いからレイカずっと怖がってたんだよ。"
        matches = match_wk_vocab_in_sentence(sentence, index)
        expressions = [m.expression for m in matches]
        self.assertIn("君", expressions)
        self.assertNotIn("中", expressions)
        self.assertNotIn("怖い", expressions)
        candidates = candidate_lemmas_in_sentence(sentence, index)
        compounds = [c for c in candidates if c.lemma == "中怖い"]
        self.assertEqual(len(compounds), 1)
        self.assertEqual(compounds[0].reading, "ちゅうこわい")
        self.assertEqual(compounds[0].surface, "中怖い")

    def test_longer_expression_beats_shorter_overlap(self) -> None:
        """お姉さん must win over 姉; 急に must win over 急."""
        index = _index(
            {
                "id": 2893,
                "expression": "お姉さん",
                "reading": "おねえさん",
                "meaning": "older sister",
                "prerequisite_ids": "",
            },
            {
                "id": 7526,
                "expression": "姉",
                "reading": "あね",
                "meaning": "older sister",
                "prerequisite_ids": "",
            },
            {
                "id": 3839,
                "expression": "急に",
                "reading": "きゅうに",
                "meaning": "suddenly",
                "prerequisite_ids": "",
            },
            {
                "id": 2470,
                "expression": "急",
                "reading": "きゅう",
                "meaning": "urgent",
                "prerequisite_ids": "",
            },
        )
        self.assertEqual(
            [m.expression for m in match_wk_vocab_in_sentence("お姉さんいるの?", index)],
            ["お姉さん"],
        )
        self.assertEqual(
            [m.expression for m in match_wk_vocab_in_sentence("急に敬語?", index)],
            ["急に"],
        )

    def test_stage_directions_in_brackets_are_ignored(self) -> None:
        index = _index(
            {
                "id": 3072,
                "expression": "音楽",
                "reading": "おんがく",
                "meaning": "Music",
                "prerequisite_ids": "",
            },
            {
                "id": 1,
                "expression": "息",
                "reading": "いき",
                "meaning": "breath",
                "prerequisite_ids": "",
            },
        )
        self.assertEqual(match_wk_vocab_in_sentence("[音楽]", index), [])
        self.assertFalse(has_spoken_japanese("[音楽]"))
        self.assertTrue(has_spoken_japanese("音楽が好きです。"))

        index = _index(
            {
                "id": 3323,
                "expression": "息",
                "reading": "いき",
                "meaning": "breath",
                "prerequisite_ids": "",
            },
            {
                "id": 2804,
                "expression": "音",
                "reading": "おと",
                "meaning": "sound",
                "prerequisite_ids": "",
            },
            {
                "id": 3714,
                "expression": "私",
                "reading": "わたし",
                "meaning": "I",
                "prerequisite_ids": "",
            },
        )
        matches = match_wk_vocab_in_sentence(
            "[息をのむ音]私の時はスナックか寄ってました。", index
        )
        self.assertEqual([m.expression for m in matches], ["私"])

    def test_unidic_lemma_must_match_written_surface(self) -> None:
        """いや is not 否; 吾 in し吾 is not 我 — reject lemma-only WK hits."""
        if not tokenize_japanese("いや"):
            self.skipTest("fugashi unavailable")
        index = _index(
            {
                "id": 1,
                "expression": "否",
                "reading": "いな",
                "meaning": "no",
                "prerequisite_ids": "",
            },
            {
                "id": 2,
                "expression": "我",
                "reading": "われ",
                "meaning": "I",
                "prerequisite_ids": "",
            },
            {
                "id": 3,
                "expression": "先輩",
                "reading": "せんぱい",
                "meaning": "senior",
                "prerequisite_ids": "",
            },
            {
                "id": 4,
                "expression": "食べる",
                "reading": "たべる",
                "meaning": "to eat",
                "prerequisite_ids": "",
            },
        )
        self.assertEqual(match_wk_vocab_in_sentence("いや、私は", index), [])
        self.assertEqual(
            [m.expression for m in match_wk_vocab_in_sentence(
                "あの、し吾先輩っておいくつなんですか?", index
            )],
            ["先輩"],
        )
        # Real inflection still matches via lemma (食べ → 食べる).
        self.assertEqual(
            [m.expression for m in match_wk_vocab_in_sentence("寿司を食べました。", index)],
            ["食べる"],
        )

    def test_numeric_vocab_does_not_claim_bare_counter_kanji(self) -> None:
        """The 年 of 同い年 is not ２０１１年 — front sentence must match the answer."""
        index = _index(
            {
                "id": 2662,
                "expression": "２０１１年",
                "reading": "にせんじゅういちねん",
                "meaning": "Year 2011",
                "prerequisite_ids": "546",
            },
            {
                "id": 2747,
                "expression": "同じ",
                "reading": "おなじ",
                "meaning": "same",
                "prerequisite_ids": "568",
            },
        )
        matches = match_wk_vocab_in_sentence("え、同い年じゃないですか?", index)
        self.assertEqual([m.expression for m in matches], ["同じ"])

    def test_honorific_prefix_vocab_does_not_claim_bare_kanji(self) -> None:
        """知らなかった is 知る, not お知らせ; 姉 alone is not お姉さん."""
        index = _index(
            {
                "id": 1,
                "expression": "お知らせ",
                "reading": "おしらせ",
                "meaning": "notice",
                "prerequisite_ids": "",
            },
            {
                "id": 2,
                "expression": "お姉さん",
                "reading": "おねえさん",
                "meaning": "older sister",
                "prerequisite_ids": "",
            },
        )
        self.assertEqual(match_wk_vocab_in_sentence("知らなかったですね。", index), [])
        self.assertEqual(match_wk_vocab_in_sentence("私の姉がよく合うそうです。", index), [])

    def test_stem_inside_unrelated_compound_is_rejected(self) -> None:
        """担任 is neither 担ぐ nor 任す; 年生 is not 生まれる."""
        index = _index(
            {
                "id": 4668,
                "expression": "担ぐ",
                "reading": "かつぐ",
                "meaning": "to carry",
                "prerequisite_ids": "",
            },
            {
                "id": 9045,
                "expression": "任す",
                "reading": "まかす",
                "meaning": "to entrust",
                "prerequisite_ids": "",
            },
            {
                "id": 2576,
                "expression": "生まれる",
                "reading": "うまれる",
                "meaning": "to be born",
                "prerequisite_ids": "",
            },
        )
        self.assertEqual(match_wk_vocab_in_sentence("俺の担任もひ先生だった。", index), [])
        self.assertEqual(match_wk_vocab_in_sentence("高校3年生の時の担任は。", index), [])

    def test_inflected_stem_after_kanji_is_kept(self) -> None:
        """No spaces in Japanese: 敬語使って and 私怒らせ are real inflections."""
        index = _index(
            {
                "id": 3088,
                "expression": "使う",
                "reading": "つかう",
                "meaning": "to use",
                "prerequisite_ids": "",
            },
            {
                "id": 5018,
                "expression": "怒る",
                "reading": "おこる",
                "meaning": "to get angry",
                "prerequisite_ids": "",
            },
            {
                "id": 2824,
                "expression": "来る",
                "reading": "くる",
                "meaning": "to come",
                "prerequisite_ids": "",
            },
        )
        # 使って is emitted by the conjugator; 怒らせ (causative) is not, so it
        # relies on the gojūon row rule; 来ない is an irregular the row rule misses.
        self.assertEqual(
            [m.expression for m in match_wk_vocab_in_sentence("敬語使ってないしね。", index)],
            ["使う"],
        )
        self.assertEqual(
            [m.expression for m in match_wk_vocab_in_sentence("私怒らせちゃったのかな?", index)],
            ["怒る"],
        )
        self.assertEqual(
            [m.expression for m in match_wk_vocab_in_sentence("授業来ないでバイトした。", index)],
            ["来る"],
        )

    def test_counter_suffix_still_matches_after_a_number(self) -> None:
        index = _index(
            {
                "id": 3,
                "expression": "〜歳",
                "reading": "さい",
                "meaning": "years old",
                "prerequisite_ids": "",
            }
        )
        matches = match_wk_vocab_in_sentence("22歳だよ。", index)
        self.assertEqual([m.expression for m in matches], ["〜歳"])

    def test_kana_prefixed_verb_matches_when_prefix_present(self) -> None:
        index = _index(
            {
                "id": 4,
                "expression": "やって来る",
                "reading": "やってくる",
                "meaning": "to come",
                "prerequisite_ids": "",
            }
        )
        sentence = "暖かい春がやって来ました。"
        if tokenize_japanese(sentence):
            self.skipTest("fugashi present — exercises the token path, not longest-match")
        matches = match_wk_vocab_in_sentence(sentence, index)
        self.assertEqual([m.expression for m in matches], ["やって来る"])

    def test_kana_only_word(self) -> None:
        index = _index(
            {
                "id": 5,
                "expression": "です",
                "reading": "です",
                "meaning": "to be",
                "prerequisite_ids": "",
            }
        )
        matches = match_wk_vocab_in_sentence("日本です。", index)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].expression, "です")


class CandidateLemmaTests(unittest.TestCase):
    def test_excludes_wk_expression(self) -> None:
        index = _index(
            {
                "id": 6,
                "expression": "電車",
                "reading": "でんしゃ",
                "meaning": "train",
                "prerequisite_ids": "",
            }
        )
        candidates = candidate_lemmas_in_sentence("電車と新幹線が速い。", index)
        lemmas = {c.lemma for c in candidates}
        self.assertNotIn("電車", lemmas)
        # Fallback keeps the full kanji run; UniDic may split 新幹線 → 幹線.
        self.assertTrue(
            lemmas & {"新幹線", "幹線"},
            f"expected a non-WK train word in {lemmas}",
        )

    def test_excludes_stopwords_and_particles_when_tokenized_or_fallback(self) -> None:
        index = _index()
        candidates = candidate_lemmas_in_sentence("これはテストです。", index)
        lemmas = {c.lemma for c in candidates}
        self.assertNotIn("これ", lemmas)
        self.assertNotIn("です", lemmas)

    def test_fallback_does_not_glue_wk_verb_onto_keigo(self) -> None:
        """Without fugashi, 敬語使って must not become candidate 敬語使 / けいごつかっ."""
        index = _index(
            {
                "id": 5647,
                "expression": "敬語",
                "reading": "けいご",
                "meaning": "keigo",
                "prerequisite_ids": "",
            },
            {
                "id": 3088,
                "expression": "使う",
                "reading": "つかう",
                "meaning": "to use",
                "prerequisite_ids": "",
            },
        )
        sentence = "私たちだって敬語使ってないしね。"
        matches = match_wk_vocab_in_sentence(sentence, index)
        candidates = candidate_lemmas_in_sentence(
            sentence,
            index,
            wk_matched_expressions={m.expression for m in matches},
            wk_matched_spans={(m.start, m.end) for m in matches},
        )
        lemmas = {c.lemma for c in candidates}
        self.assertNotIn("敬語使", lemmas)
        self.assertNotIn("敬語", lemmas)
        self.assertTrue(
            all(not c.reading.endswith("っ") for c in candidates),
            candidates,
        )

    def test_reading_join_ignores_partial_token_overlap(self) -> None:
        from shadowing_match import reading_for_surface_in_sentence, tokenize_japanese

        sentence = "敬語使ってない"
        if not tokenize_japanese(sentence):
            self.skipTest("fugashi unavailable")
        # Surface cut before っ must not absorb 使っ's reading つかっ.
        self.assertNotEqual(
            reading_for_surface_in_sentence(sentence, "敬語使"),
            "けいごつかっ",
        )


if __name__ == "__main__":
    unittest.main()
