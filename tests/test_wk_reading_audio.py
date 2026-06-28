"""Tests for wk_reading_audio.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_reading_audio import (
    reading_audio_basename,
    reading_tts_text,
    select_pronunciation_audio,
)


def mock_vocab(vocab_id: int = 42, reading: str = "がくせい") -> dict:
    return {
        "id": vocab_id,
        "object": "vocabulary",
        "data": {
            "characters": "学生",
            "pronunciation_audios": [
                {
                    "url": "https://example.com/student.mp3",
                    "content_type": "audio/mpeg",
                    "metadata": {"voice_actor_name": "Kyoko", "pronunciation": reading},
                }
            ],
            "readings": [{"reading": reading, "primary": True}],
        },
    }


def mock_kanji(reading: str = "おも") -> dict:
    return {
        "id": 637,
        "object": "kanji",
        "data": {
            "characters": "思",
            "readings": [{"reading": reading, "primary": True}],
        },
    }


class WkReadingAudioTests(unittest.TestCase):
    def test_reading_tts_text_uses_primary_reading(self) -> None:
        self.assertEqual(reading_tts_text(mock_kanji()), "おも")

    def test_reading_audio_basename_includes_subject_kind(self) -> None:
        self.assertEqual(
            reading_audio_basename(mock_vocab(), "Kyoko", "mp3"),
            "wk_reading_vocabulary_42_kyoko.mp3",
        )

    def test_prepare_reading_audio_field_vocab(self) -> None:
        from wk_reading_audio import prepare_reading_audio_field

        media_dir = REPO_ROOT / "out" / "test_reading_media"
        with mock.patch("wk_reading_audio.ensure_pronunciation_audio_file", return_value=(True, True)):
            field, path = prepare_reading_audio_field(mock_vocab(), media_dir)
        self.assertEqual(field, "[sound:wk_reading_vocabulary_42_kyoko.mp3]")
        self.assertTrue(path)

    def test_prepare_reading_audio_field_kanji_uses_tts(self) -> None:
        from wk_reading_audio import prepare_reading_audio_field

        media_dir = REPO_ROOT / "out" / "test_reading_media_kanji"
        with mock.patch("wk_reading_audio.ensure_sentence_audio_file", return_value=(True, False)):
            field, path = prepare_reading_audio_field(mock_kanji(), media_dir)
        self.assertEqual(field, "[sound:wk_reading_kanji_637_kyoko.mp3]")
        self.assertTrue(path)

    def test_select_pronunciation_audio_prefers_kyoko(self) -> None:
        entry = select_pronunciation_audio(mock_vocab(), voice_actor="Kyoko")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["metadata"]["voice_actor_name"], "Kyoko")


if __name__ == "__main__":
    unittest.main()
