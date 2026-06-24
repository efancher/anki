"""Tests for WaniKani vocabulary context cloze generation in wk_decks.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import (
    CLOZE_BLANK_DISPLAY,
    VOCAB_CLOZE_DEFAULT_MIN_SRS,
    WK_SRS_STAGE_GURU_1,
    WK_SRS_STAGE_MASTER,
    apply_wk_paren_readings,
    blank_target_in_sentence,
    collect_vocab_cloze_items,
    ensure_sentence_audio_file,
    prepare_sentence_for_tts,
    select_vocab_cloze_sentence,
    sentence_audio_cache_key,
    sentence_audio_cache_path,
    vocab_cloze_audio_basename,
    vocab_cloze_blank_targets,
)


def mock_vocab(
    *,
    vocab_id: int,
    expr: str,
    reading: str,
    sentences: list[dict[str, str]],
    level: int = 5,
) -> dict:
    return {
        "id": vocab_id,
        "object": "vocabulary",
        "data": {
            "characters": expr,
            "level": level,
            "meanings": [{"meaning": "book", "primary": True}],
            "readings": [{"reading": reading, "primary": True}],
            "context_sentences": sentences,
        },
    }


class VocabClozeTests(unittest.TestCase):
    def test_default_min_srs_is_master(self) -> None:
        self.assertEqual(VOCAB_CLOZE_DEFAULT_MIN_SRS, WK_SRS_STAGE_MASTER)

    def test_blank_target_in_sentence_matches_expression(self) -> None:
        result = blank_target_in_sentence("私は毎日本を読みます。", ["本"])
        self.assertIsNotNone(result)
        cloze, full = result
        self.assertEqual(full, "私は毎日本を読みます。")
        self.assertEqual(cloze, f"私は毎日{CLOZE_BLANK_DISPLAY}を読みます。")

    def test_blank_target_strips_html(self) -> None:
        result = blank_target_in_sentence("<span>本</span>を読む", ["本"])
        self.assertIsNotNone(result)
        cloze, full = result
        self.assertEqual(full, "本を読む")
        self.assertIn(CLOZE_BLANK_DISPLAY, cloze)

    def test_suru_verb_matches_noun_stem(self) -> None:
        vocab = mock_vocab(
            vocab_id=1,
            expr="勉強する",
            reading="べんきょうする",
            sentences=[{"ja": "毎日勉強しています。", "en": "I study every day."}],
        )
        targets = vocab_cloze_blank_targets(vocab)
        self.assertIn("勉強する", targets)
        self.assertIn("勉強", targets)
        selected = select_vocab_cloze_sentence(vocab)
        self.assertIsNotNone(selected)
        _, cloze, full = selected
        self.assertEqual(full, "毎日勉強しています。")
        self.assertIn(CLOZE_BLANK_DISPLAY, cloze)

    def test_select_skips_when_no_match(self) -> None:
        vocab = mock_vocab(
            vocab_id=2,
            expr="猫",
            reading="ねこ",
            sentences=[{"ja": "犬が好きです。", "en": "I like dogs."}],
        )
        self.assertIsNone(select_vocab_cloze_sentence(vocab))

    def test_collect_respects_min_srs(self) -> None:
        vocab = mock_vocab(
            vocab_id=3,
            expr="本",
            reading="ほん",
            sentences=[{"ja": "本を読みます。", "en": "I read a book."}],
        )
        assignment_index = {
            3: {"data": {"subject_id": 3, "srs_stage": WK_SRS_STAGE_GURU_1}},
        }
        self.assertEqual(
            collect_vocab_cloze_items([vocab], assignment_index, min_srs=WK_SRS_STAGE_MASTER),
            [],
        )
        assignment_index[3]["data"]["srs_stage"] = WK_SRS_STAGE_MASTER
        items = collect_vocab_cloze_items([vocab], assignment_index, min_srs=WK_SRS_STAGE_MASTER)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].full_sentence, "本を読みます。")

    def test_collect_uses_first_blankable_sentence(self) -> None:
        vocab = mock_vocab(
            vocab_id=4,
            expr="本",
            reading="ほん",
            sentences=[
                {"ja": "犬が好きです。", "en": "I like dogs."},
                {"ja": "本を読みます。", "en": "I read a book."},
            ],
        )
        assignment_index = {4: {"data": {"subject_id": 4, "srs_stage": WK_SRS_STAGE_MASTER}}}
        items = collect_vocab_cloze_items([vocab], assignment_index, min_srs=WK_SRS_STAGE_MASTER)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].full_sentence, "本を読みます。")

    def test_sentence_audio_cache_key_is_stable(self) -> None:
        self.assertEqual(
            sentence_audio_cache_key("本を読みます。", "ja-JP-NanamiNeural"),
            sentence_audio_cache_key("本を読みます。", "ja-JP-NanamiNeural"),
        )
        self.assertNotEqual(
            sentence_audio_cache_key("本を読みます。", "ja-JP-NanamiNeural"),
            sentence_audio_cache_key("猫が好きです。", "ja-JP-NanamiNeural"),
        )

    def test_vocab_cloze_audio_basename(self) -> None:
        self.assertEqual(vocab_cloze_audio_basename(2467), "wk_vocab_cloze_2467.mp3")

    def test_apply_wk_paren_readings(self) -> None:
        self.assertEqual(
            apply_wk_paren_readings("あっ、富士山（ふじさん）だ！"),
            "あっ、ふじさんだ！",
        )

    def test_prepare_sentence_for_tts_uses_vocab_reading(self) -> None:
        vocab = mock_vocab(
            vocab_id=10,
            expr="富士山",
            reading="ふじさん",
            sentences=[{"ja": "あっ、富士山だ！", "en": "Ah, it's Mt. Fuji!"}],
        )
        self.assertEqual(
            prepare_sentence_for_tts("あっ、富士山だ！", vocab, source_ja="あっ、富士山だ！"),
            "あっ、ふじさんだ！",
        )

    def test_ensure_sentence_audio_file_uses_cache(self) -> None:
        with mock.patch("wk_decks.generate_sentence_audio_cache") as generate:
            cache_path = sentence_audio_cache_path("本を読みます。", "ja-JP-NanamiNeural")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(b"fake-mp3")
            dest = Path("/tmp/wk_vocab_cloze_test/wk_vocab_cloze_99.mp3")
            if dest.exists():
                dest.unlink()
            ok = ensure_sentence_audio_file("本を読みます。", "ja-JP-NanamiNeural", dest)
            self.assertEqual(ok, (True, True))
            self.assertTrue(dest.is_file())
            generate.assert_not_called()
            dest.unlink()
            dest.parent.rmdir()


if __name__ == "__main__":
    unittest.main()
