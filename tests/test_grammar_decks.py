"""Tests for Hanabira grammar deck generation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from grammar_decks import (
    GrammarCardItem,
    blank_grammar_in_sentence,
    blank_regex_in_sentence,
    blank_state_of_being_from_pattern,
    blank_state_of_being_predicate,
    build_grammar_deck,
    collect_grammar_cards,
    grammar_audio_basename,
    grammar_blank_tokens,
    grammar_form_hint,
    grammar_point_id,
    hanabira_grammar_cache_path,
    jlpt_within_cap,
    make_grammar_model,
    prepare_grammar_sentence_for_tts,
    production_hint_from_english,
    sentence_unknown_kanji,
)


SAMPLE_GRAMMAR_CARD = GrammarCardItem(
    point_id="sample-n5-state-being",
    jlpt="N5",
    order=1,
    title="だ — casual state-of-being",
    short_explanation="Attach だ to nouns and na-adjectives.",
    formation="Noun/na-adj + だ",
    cloze_sentence="私は＿＿＿。",
    full_sentence="私は学生だ。",
    sentence_en="I am a student.",
    type_expression="学生だ",
    hint="am a student",
)

SAMPLE_POINT = {
    "_jlpt": "N5",
    "title": "A。けれども、～B。 (A. Keredomo, ~B.)",
    "short_explanation": "Express contrast; 'but', 'however'.",
    "formation": "Statement A + けれども、+ Statement B",
    "s_tag": "25",
    "examples": [
        {
            "jp": "今日は晴れている。けれども、寒いです。",
            "en": "It is sunny today. However, it is cold.",
        }
    ],
}


class GrammarDeckTests(unittest.TestCase):
    def test_jlpt_within_cap(self) -> None:
        self.assertTrue(jlpt_within_cap("N5", "N2"))
        self.assertTrue(jlpt_within_cap("N2", "N2"))
        self.assertFalse(jlpt_within_cap("N1", "N2"))

    def test_grammar_blank_tokens_extracts_japanese(self) -> None:
        tokens = grammar_blank_tokens(SAMPLE_POINT)
        self.assertIn("けれども", tokens)

    def test_blank_grammar_in_sentence(self) -> None:
        tokens = grammar_blank_tokens(SAMPLE_POINT)
        result = blank_grammar_in_sentence(SAMPLE_POINT["examples"][0]["jp"], tokens)
        self.assertIsNotNone(result)
        cloze, chunk = result
        self.assertIn("＿", cloze)
        self.assertEqual(chunk, "けれども")

    def test_sentence_unknown_kanji(self) -> None:
        self.assertEqual(sentence_unknown_kanji("今日は寒い", {"今", "日"}), 1)
        self.assertEqual(sentence_unknown_kanji("今日は寒い", {"今", "日", "寒"}), 0)

    def test_collect_from_cached_hanabira(self) -> None:
        cache_path = hanabira_grammar_cache_path("N5")
        if not cache_path.is_file():
            self.skipTest("Hanabira cache not present; run wk_decks.py --deck grammar once")
        cards = collect_grammar_cards(
            max_jlpt="N5",
            max_examples_per_point=1,
            max_unknown_kanji=99,
            known_kanji=set(),
            refresh=False,
        )
        self.assertGreater(len(cards), 50)
        self.assertTrue(all(card.jlpt == "N5" for card in cards))

    def test_grammar_point_id_is_stable(self) -> None:
        first = grammar_point_id(SAMPLE_POINT, 0)
        second = grammar_point_id(SAMPLE_POINT, 0)
        self.assertEqual(first, second)

    def test_blank_regex_in_sentence(self) -> None:
        import re

        pattern = re.compile(r"(です)(?=。|$)")
        cloze, chunk = blank_regex_in_sentence("これは本です。", pattern)
        self.assertEqual(chunk, "です")
        self.assertIn("＿", cloze)

    def test_blank_state_of_being_predicate(self) -> None:
        cloze, chunk, hint = blank_state_of_being_predicate(
            "私は学生だ。",
            copula_start=4,
            copula_end=5,
            sentence_en="I am a student.",
        )
        self.assertEqual(cloze, "私は＿＿＿。")
        self.assertEqual(chunk, "学生だ")
        self.assertEqual(hint, "am a student")

    def test_blank_state_of_being_suki(self) -> None:
        cloze, chunk, hint = blank_state_of_being_predicate(
            "私は猫が好きです。",
            copula_start=6,
            copula_end=8,
            sentence_en="I like cats.",
        )
        self.assertEqual(cloze, "私は猫が＿＿＿。")
        self.assertEqual(chunk, "好きです")
        self.assertEqual(hint, "like cats")

    def test_production_hint_from_english(self) -> None:
        self.assertEqual(production_hint_from_english("She is not a student."), "is not a student")
        self.assertEqual(production_hint_from_english("He was a student."), "was a student")

    def test_grammar_form_hint_strips_answer_morphemes(self) -> None:
        self.assertEqual(
            grammar_form_hint("State-of-being: casual positive (だ)"),
            "casual positive",
        )
        self.assertEqual(
            grammar_form_hint("State-of-being: polite negative (じゃないです / ではありません)"),
            "polite negative",
        )
        self.assertEqual(grammar_form_hint("だ — casual state-of-being"), "casual state-of-being")
        self.assertEqual(
            grammar_form_hint("Expressing State-of-Being · student · casual positive"),
            "casual positive",
        )
        self.assertEqual(grammar_form_hint("A。けれども、～B。 (A. Keredomo, ~B.)"), "")

    def test_predicate_skips_comma_after_topic(self) -> None:
        import re

        pattern = re.compile(r"(じゃないです)(?=。|$)")
        cloze, chunk, _hint = blank_state_of_being_from_pattern(
            "足がいっぱいある虫は、すきじゃないです。",
            pattern,
            "I am not a fan of bugs with a lot of legs.",
        )
        self.assertIsNotNone(cloze)
        self.assertEqual(chunk, "すきじゃないです")
        self.assertEqual(cloze, "足がいっぱいある虫は＿＿＿。")

    def test_wk_blank_from_pattern(self) -> None:
        import re

        pattern = re.compile(r"(です)(?=。|$)")
        result = blank_state_of_being_from_pattern(
            "レベル一です。",
            pattern,
            "It's level one.",
        )
        self.assertIsNotNone(result)
        cloze, chunk, hint = result
        self.assertEqual(cloze, "＿＿＿。")
        self.assertEqual(chunk, "レベル一です")
        self.assertEqual(hint, "It's level one")

    def test_prepare_grammar_sentence_for_tts(self) -> None:
        self.assertEqual(
            prepare_grammar_sentence_for_tts("  私は学生だ。 "),
            "私は学生だ。",
        )
        self.assertEqual(
            prepare_grammar_sentence_for_tts("あっ、富士山（ふじさん）だ！"),
            "あっ、ふじさんだ！",
        )

    def test_tts_audio_basename_dedupes_by_sentence(self) -> None:
        from wk_decks import DEFAULT_SENTENCE_AUDIO_VOICE, tts_audio_basename

        sentence = "私は学生だ。"
        first = tts_audio_basename(sentence, DEFAULT_SENTENCE_AUDIO_VOICE)
        second = tts_audio_basename(sentence, DEFAULT_SENTENCE_AUDIO_VOICE)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("wk_tts_"))
        self.assertTrue(first.endswith(".mp3"))

    def test_grammar_audio_basename_is_stable(self) -> None:
        first = grammar_audio_basename("sample-n5-state-being")
        second = grammar_audio_basename("sample-n5-state-being")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("wk_grammar_"))
        self.assertTrue(first.endswith(".mp3"))

    def test_make_grammar_model_audio_on_back_only(self) -> None:
        model = make_grammar_model()
        template = model.templates[0]
        self.assertNotIn("SentenceAudio", template["qfmt"])
        self.assertIn("FormHint", template["qfmt"])
        self.assertNotIn("Formation", template["qfmt"])
        self.assertIn("{{FullSentence}}", template["afmt"])
        self.assertIn("{{#SentenceAudio}}", template["afmt"])

    def test_build_grammar_deck_sentence_audio_default_on(self) -> None:
        def fake_ensure(text: str, voice: str, dest: Path, *, refresh: bool = False):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"fake-mp3")
            return True, True

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch("grammar_decks.ensure_sentence_audio_file", side_effect=fake_ensure):
                with mock.patch("grammar_decks.require_edge_tts"):
                    _path, deck, media = build_grammar_deck([SAMPLE_GRAMMAR_CARD], output_dir)
            note = deck.notes[0]
            self.assertEqual(note.fields[3], "casual state-of-being")
            from wk_decks import DEFAULT_SENTENCE_AUDIO_VOICE, tts_audio_basename

            expected_sound = tts_audio_basename(
                SAMPLE_GRAMMAR_CARD.full_sentence,
                DEFAULT_SENTENCE_AUDIO_VOICE,
            )
            self.assertEqual(note.fields[9], f"[sound:{expected_sound}]")
            self.assertEqual(len(media), 1)

    def test_build_grammar_deck_sentence_audio_can_disable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch("grammar_decks.ensure_sentence_audio_file") as ensure:
                _path, deck, media = build_grammar_deck(
                    [SAMPLE_GRAMMAR_CARD],
                    output_dir,
                    sentence_audio=False,
                )
            ensure.assert_not_called()
            note = deck.notes[0]
            self.assertEqual(note.fields[9], "")
            self.assertEqual(media, [])

    def test_build_grammar_deck_standalone_apkg_bundles_sentence_audio(self) -> None:
        def fake_ensure(text: str, voice: str, dest: Path, *, refresh: bool = False):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"fake-mp3")
            return True, False

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch("grammar_decks.ensure_sentence_audio_file", side_effect=fake_ensure):
                with mock.patch("grammar_decks.require_edge_tts"):
                    apkg_path, deck, media = build_grammar_deck([SAMPLE_GRAMMAR_CARD], output_dir)
            self.assertEqual(apkg_path.name, "wk_grammar.apkg")
            with zipfile.ZipFile(apkg_path) as zf:
                bundled_media = json.loads(zf.read("media"))
            self.assertEqual(len(bundled_media), 1)
            self.assertEqual(getattr(deck, "wk_media_files", []), media)
            note = deck.notes[0]
            self.assertIn("[sound:", note.fields[9])

    def test_build_grammar_deck_bundles_sentence_audio_media(self) -> None:
        from wk_decks import BUNDLE_FILENAME, write_bundled_apkg

        def fake_ensure(text: str, voice: str, dest: Path, *, refresh: bool = False):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"fake-mp3")
            return True, False

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch("grammar_decks.ensure_sentence_audio_file", side_effect=fake_ensure):
                with mock.patch("grammar_decks.require_edge_tts"):
                    _path, deck, media = build_grammar_deck([SAMPLE_GRAMMAR_CARD], output_dir)
            bundle_path = output_dir / BUNDLE_FILENAME
            write_bundled_apkg([deck], bundle_path, media_files=media or None)
            with zipfile.ZipFile(bundle_path) as zf:
                bundled_media = json.loads(zf.read("media"))
            self.assertEqual(len(bundled_media), 1)
            self.assertEqual(getattr(deck, "wk_media_files", []), media)


if __name__ == "__main__":
    unittest.main()
