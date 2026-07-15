#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from satori_gloss import (
    GLOSS_ANSWER_CACHE_VERSION,
    GlossSentence,
    _TRANSLATE_CACHE,
    analyze_gloss_sentence,
    chunk_japanese_sentence,
    dedupe_gloss_items,
    format_answer_worksheet,
    format_worksheet,
    format_worksheets,
    gloss_answer_cache_key,
    gloss_from_anki_fields,
    ichi_moe_url,
    load_gloss_answer_cache,
    save_gloss_answer_cache,
    strip_anki_html,
)


def _fake_translate(japanese: str) -> str:
    """Phrase-level fakes (production MT uses full chunks, not bare stems)."""
    mapping = {
        "空は": "the sky is",
        "青くて": "it's blue",
        "木々の": "of the trees",
        "緑が": "green",
        "きれいでした": "it was pretty",
        "日本では": "in japan",
        "ありません": "does not exist",
        "ある小鳥": "a small bird",
        "夫婦": "couple",
        "木": "tree",
        "巣": "nest",
        "作り": "make",
    }
    return mapping.get(japanese, japanese)


class SatoriGlossTests(unittest.TestCase):
    def setUp(self) -> None:
        _TRANSLATE_CACHE.clear()

    def test_strip_anki_html(self) -> None:
        self.assertEqual(
            strip_anki_html("<div>暖かい<br>春</div>"),
            "暖かい\n春",
        )

    def test_gloss_from_fields_prefers_sentence(self) -> None:
        item = gloss_from_anki_fields(
            {
                "Sentence": {"value": "暖かい春がやって来ました。"},
                "ClozeSentence": {"value": "{{c1::暖かい}}春がやって来ました。"},
                "Translation": {"value": "The warm spring came along."},
                "Expression": {"value": "暖かい"},
                "Reading": {"value": "あたたかい"},
            },
            note_id=42,
        )
        assert item is not None
        self.assertEqual(item.japanese, "暖かい春がやって来ました。")
        self.assertEqual(item.english, "The warm spring came along.")
        self.assertEqual(item.expression, "暖かい")
        self.assertEqual(item.note_id, 42)

    def test_gloss_unwraps_cloze_when_sentence_missing(self) -> None:
        item = gloss_from_anki_fields(
            {"ClozeSentence": {"value": "{{c1::です}}。"}},
        )
        assert item is not None
        self.assertEqual(item.japanese, "です。")

    def test_ichi_moe_url_requests_kana(self) -> None:
        url = ichi_moe_url("日本ではありません。")
        self.assertIn("r=kana", url)
        self.assertTrue(url.startswith("https://ichi.moe/cl/qr/?"))

    def test_worksheet_keeps_english_and_blanks(self) -> None:
        text = format_worksheet(
            GlossSentence(
                japanese="暖かい春がやって来ました。",
                english="The warm spring came along.",
                expression="暖かい",
                reading="あたたかい",
                note_id=1,
            )
        )
        self.assertIn("JP:    暖かい春がやって来ました。", text)
        self.assertIn("CHUNK:", text)
        self.assertIn("ROLE:", text)
        self.assertIn("LIT:", text)
        self.assertIn("EN:    The warm spring came along.", text)
        self.assertIn("Target word: 暖かい (あたたかい)", text)
        self.assertIn(ichi_moe_url("暖かい春がやって来ました。"), text)
        self.assertNotIn("warm spring", text.split("EN:", 1)[0])

    def test_dedupe_merges_target_words(self) -> None:
        items = dedupe_gloss_items(
            [
                GlossSentence(
                    japanese="暖かい春がやって来ました。",
                    english="The warm spring came along.",
                    expression="暖かい",
                    reading="あたたかい",
                    note_id=1,
                ),
                GlossSentence(
                    japanese="暖かい春がやって来ました。",
                    english="The warm spring came along.",
                    expression="春",
                    reading="はる",
                    note_id=2,
                ),
            ]
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].expression, "暖かい · 春")
        self.assertEqual(items[0].reading, "あたたかい · はる")
        self.assertEqual(items[0].note_id, 1)

    def test_deshita_not_split_on_de_particle(self) -> None:
        chunks = chunk_japanese_sentence("空は青くて、木々の緑がきれいでした。")
        self.assertTrue(any("きれいでした" in chunk for chunk in chunks))
        self.assertFalse(any(chunk in {"した", "した。"} for chunk in chunks))

    def test_lit_is_japanese_order_sticky_english(self) -> None:
        item = GlossSentence(
            japanese="空は青くて、木々の緑がきれいでした。",
            english="The sky was blue and the green of the trees was pretty.",
        )
        answer = analyze_gloss_sentence(item, translator=_fake_translate)
        self.assertIn("sky-as-for", answer.lit)
        self.assertIn("blue-and", answer.lit)
        self.assertIn("trees-'s", answer.lit)
        self.assertIn("green-が", answer.lit)
        self.assertIn("pretty-was.POLITE", answer.lit)
        self.assertNotIn("空は", answer.lit)
        self.assertNotIn("きれい", answer.lit)

    def test_lit_translates_full_chunk_not_bare_stem(self) -> None:
        """Isolated 空/きれい MT picks empty/clean; chunk MT picks sky/beautiful."""
        calls: list[str] = []

        def translator(japanese: str) -> str:
            calls.append(japanese)
            mapping = {
                "空": "empty",
                "空は": "the sky is",
                "青く": "blue",
                "青くて": "it's blue",
                "木々": "trees",
                "木々の": "of the trees",
                "緑": "green",
                "緑が": "green",
                "きれい": "clean",
                "きれいでした": "it was beautiful",
            }
            return mapping.get(japanese, japanese)

        item = GlossSentence(japanese="空は青くて、木々の緑がきれいでした。")
        answer = analyze_gloss_sentence(item, translator=translator)
        self.assertIn("空は", calls)
        self.assertIn("きれいでした", calls)
        self.assertIn("sky-as-for", answer.lit)
        self.assertIn("beautiful-was.POLITE", answer.lit)
        self.assertNotIn("empty", answer.lit)
        self.assertNotIn("clean", answer.lit)

    def test_na_inside_words_is_not_a_particle_cut(self) -> None:
        """ひな / なる contain な; only clause-final な may cut."""
        chunks = chunk_japanese_sentence("ひなたちは、毎日少しずつ大きくなりました。")
        self.assertEqual(
            chunks,
            ["ひなたちは、", "毎日少しずつ大きくなりました。"],
        )
        self.assertFalse(any(chunk == "ひな" for chunk in chunks))
        self.assertFalse(any("大きくな" == chunk.rstrip("。．") for chunk in chunks))

        item = GlossSentence(
            japanese="ひなたちは、毎日少しずつ大きくなりました。",
            english="Every day, the chicks got bigger, little by little.",
        )

        def translator(japanese: str) -> str:
            mapping = {
                "ひなたちは": "the ducks are",
                "ひなたち": "chicks",
                "毎日少しずつ大きくなりました": "it grew little by little every day",
                "毎日少しずつ大きくなり": "grew little by little every day",
            }
            return mapping.get(japanese, japanese)

        answer = analyze_gloss_sentence(item, translator=translator)
        self.assertIn("topic", answer.role)
        self.assertIn("engine", answer.role)
        self.assertNotIn("な-car", answer.role)
        self.assertIn("chicks-as-for", answer.lit)
        self.assertNotIn("ducks", answer.lit)
        self.assertIn("POLITE.PAST", answer.lit)
        self.assertNotIn("netherlands", answer.lit.lower())
        self.assertNotIn("18292", answer.lit)

    def test_chunking_guards_common_false_cuts(self) -> None:
        cases = {
            "親鳥がえさを運んで来ました。": [
                "親鳥が",
                "えさを",
                "運んで来ました。",
            ],
            "とっても可愛いひなたちでした。": [
                "とっても",
                "可愛いひなたちでした。",
            ],
            "そして、小鳥の奥さんは、卵を３つ産みました。": [
                "そして、",
                "小鳥の",
                "奥さんは、",
                "卵を",
                "３つ産みました。",
            ],
            "ひなは必死に羽ばたいて、なんとか飛ぶことができました。": [
                "ひなは",
                "必死に",
                "羽ばたいて、",
                "なんとか",
                "飛ぶことが",
                "できました。",
            ],
            "しかし、最後の１羽は怖がりで、なかなか飛び出すことができませんでした。": [
                "しかし、",
                "最後の",
                "１羽は",
                "怖がりで、",
                "なかなか飛び出すことが",
                "できませんでした。",
            ],
            "暖かい春がやって来ました。": ["暖かい春が", "やって来ました。"],
            "お母さん鳥は喜んで、ひなと一緒に飛びました。": [
                "お母さん鳥は",
                "喜んで、",
                "ひなと",
                "一緒に",
                "飛びました。",
            ],
        }
        for japanese, expected in cases.items():
            with self.subTest(japanese=japanese):
                self.assertEqual(chunk_japanese_sentence(japanese), expected)

    def test_answer_fills_chunk_role_for_dewa_arimasen(self) -> None:
        item = GlossSentence(
            japanese="日本ではありません。",
            english="It’s not Japan.",
            expression="です",
        )
        answer = analyze_gloss_sentence(item, translator=_fake_translate)
        self.assertIn("日本では", answer.chunk)
        self.assertIn("ありません", answer.chunk)
        self.assertIn("topic", answer.role)
        self.assertIn("engine", answer.role)
        self.assertIn("japan-at-as-for", answer.lit)
        self.assertIn("exist-not.POLITE", answer.lit)
        filled = format_answer_worksheet(item, translator=_fake_translate)
        self.assertIn("CHUNK: ", filled)

    def test_worksheets_append_answer_key(self) -> None:
        items = [
            GlossSentence(japanese="日本ではありません。", english="It’s not Japan."),
        ]
        text = format_worksheets(items, include_answers=True, translator=_fake_translate)
        self.assertIn("ANSWER KEY", text)
        self.assertIn("Satori gloss answers", text)
        blank, answers = text.split("ANSWER KEY", 1)
        self.assertIn("CHUNK:\n", blank)
        self.assertIn("CHUNK: ", answers)


class SatoriGlossCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        _TRANSLATE_CACHE.clear()

    def test_answer_cache_reused_without_retranslating(self) -> None:
        item = GlossSentence(japanese="日本ではありません。", english="It’s not Japan.")
        calls: list[str] = []

        def translator(japanese: str) -> str:
            calls.append(japanese)
            return _fake_translate(japanese)

        cache: dict = {}
        first = analyze_gloss_sentence(item, translator=translator, answer_cache=cache)
        self.assertTrue(calls)
        self.assertEqual(len(cache), 1)

        calls.clear()
        _TRANSLATE_CACHE.clear()
        second = analyze_gloss_sentence(item, translator=translator, answer_cache=cache)
        self.assertEqual(calls, [])  # served from cache, no MT
        self.assertEqual(first, second)

    def test_cache_key_depends_on_sentence_and_english(self) -> None:
        base = GlossSentence(japanese="日本ではありません。", english="It’s not Japan.")
        same = GlossSentence(japanese="日本では ありません。", english="It’s   not Japan.")
        other_en = GlossSentence(japanese="日本ではありません。", english="Different.")
        self.assertEqual(gloss_answer_cache_key(base), gloss_answer_cache_key(same))
        self.assertNotEqual(gloss_answer_cache_key(base), gloss_answer_cache_key(other_en))

    def test_cache_round_trips_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "answers.json"
            answers = {"abc123": {"chunk": "c", "role": "r", "lit": "l"}}
            save_gloss_answer_cache(path, answers)
            self.assertTrue(path.is_file())
            self.assertEqual(load_gloss_answer_cache(path), answers)

    def test_cache_version_mismatch_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "answers.json"
            path.write_text(
                '{"version": %d, "answers": {"k": {"chunk": "c"}}}'
                % (GLOSS_ANSWER_CACHE_VERSION + 1),
                encoding="utf-8",
            )
            self.assertEqual(load_gloss_answer_cache(path), {})

    def test_missing_cache_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_gloss_answer_cache(Path(tmp) / "nope.json"), {})


if __name__ == "__main__":
    unittest.main()
