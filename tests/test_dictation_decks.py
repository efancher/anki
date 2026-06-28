"""Tests for WaniKani native-audio dictation decks."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dictation_decks import (
    collect_vocab_dictation_items,
    dictation_expression,
    select_pronunciation_audio,
)
from wk_decks import mock_vocab_for_conjugation, srs_stage


def mock_vocab_with_audio(
    expr: str,
    reading: str,
    *,
    vocab_id: int = 1,
    level: int = 5,
) -> dict:
    vocab = mock_vocab_for_conjugation(expr, reading, ["noun"], vocab_id=vocab_id)
    vocab["data"]["level"] = level
    vocab["data"]["pronunciation_audios"] = [
        {
            "url": f"https://files.wanikani.com/test-{vocab_id}.mp3",
            "content_type": "audio/mpeg",
            "metadata": {
                "voice_actor_name": "Kyoko",
                "pronunciation": reading,
            },
        },
        {
            "url": f"https://files.wanikani.com/test-{vocab_id}.webm",
            "content_type": "audio/webm",
            "metadata": {
                "voice_actor_name": "Kenichi",
                "pronunciation": reading,
            },
        },
    ]
    return vocab


class DictationDeckTests(unittest.TestCase):
    def test_select_pronunciation_audio_prefers_kyoko_mpeg(self) -> None:
        vocab = mock_vocab_with_audio("学生", "がくせい")
        entry = select_pronunciation_audio(vocab, voice_actor="Kyoko")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertIn("mpeg", entry["content_type"])

    def test_dictation_expression_is_wk_characters(self) -> None:
        vocab = mock_vocab_with_audio("食べる", "たべる")
        self.assertEqual(dictation_expression(vocab), "食べる")

    def test_collect_uses_reading_for_type_answer(self) -> None:
        vocab = mock_vocab_with_audio("食べる", "たべる", vocab_id=42)
        assignment_index = {42: {"data": {"subject_id": 42, "srs_stage": 7}}}
        items = collect_vocab_dictation_items([vocab], assignment_index, min_srs=7)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].expression, "食べる")
        self.assertEqual(items[0].reading, "たべる")

    def test_collect_respects_min_srs(self) -> None:
        vocab = mock_vocab_with_audio("学生", "がくせい", vocab_id=42)
        assignment_index = {
            42: {"data": {"subject_id": 42, "srs_stage": 5}},
        }
        self.assertEqual(
            collect_vocab_dictation_items([vocab], assignment_index, min_srs=7),
            [],
        )
        assignment_index[42]["data"]["srs_stage"] = 7
        items = collect_vocab_dictation_items([vocab], assignment_index, min_srs=7)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].expression, "学生")
        self.assertEqual(items[0].reading, "がくせい")

    def test_build_dictation_deck_bundles_audio(self) -> None:
        from dictation_decks import DictationItem, build_dictation_deck

        vocab = mock_vocab_with_audio("猫", "ねこ", vocab_id=99)
        item = DictationItem(
            vocab=vocab,
            expression="猫",
            reading="ねこ",
            meaning="cat",
        )
        assignment_index = {99: {"data": {"subject_id": 99, "srs_stage": 7}}}

        def fake_ensure(_vocab, *, voice_actor, dest_path, refresh=False):
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"fake-audio")
            return True, False

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch("dictation_decks.ensure_pronunciation_audio_file", side_effect=fake_ensure):
                apkg_path, deck, media = build_dictation_deck(
                    [item],
                    output_dir,
                    assignment_index,
                    voice_actor="Kyoko",
                )
            self.assertEqual(apkg_path.name, "wk_dictation.apkg")
            self.assertEqual(len(deck.notes), 1)
            self.assertEqual(len(media), 1)
            note = deck.notes[0]
            self.assertEqual(note.fields[1], "99")
            self.assertTrue(note.fields[2].startswith("[sound:wk_dictation_"))
            self.assertEqual(note.fields[3], "猫")
            self.assertEqual(note.fields[4], "ねこ")

    def test_cached_wk_vocab_has_pronunciation_audio(self) -> None:
        cache_path = REPO_ROOT / ".wk_cache" / "subjects_vocabulary_kanji_radical.json"
        if not cache_path.is_file():
            self.skipTest("WK subject cache not present")
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        vocab = next(
            item
            for item in payload["items"]
            if item.get("object") == "vocabulary" and item["data"].get("pronunciation_audios")
        )
        self.assertIsNotNone(select_pronunciation_audio(vocab))


if __name__ == "__main__":
    unittest.main()
