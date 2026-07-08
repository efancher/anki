"""Tests for wk_reading_audio.py."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_reading_audio import (
    format_progress_line,
    kanji_tts_readings,
    reading_audio_basename,
    reading_filename_slug,
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


def mock_kanji(*readings: str) -> dict:
    return {
        "id": 637,
        "object": "kanji",
        "data": {
            "characters": "思",
            "readings": [{"reading": r, "primary": True} for r in readings],
        },
    }


class WkReadingAudioTests(unittest.TestCase):
    def test_reading_tts_text_uses_primary_reading(self) -> None:
        self.assertEqual(reading_tts_text(mock_kanji("おも")), "おも")

    def test_kanji_tts_readings_deduplicates(self) -> None:
        self.assertEqual(kanji_tts_readings(mock_kanji("せい", "しょう")), ["せい", "しょう"])

    def test_reading_audio_basename_vocab(self) -> None:
        self.assertEqual(
            reading_audio_basename(mock_vocab(), "Kyoko", "mp3"),
            "wk_reading_vocabulary_42_kyoko.mp3",
        )

    def test_reading_audio_basename_kanji_includes_reading_slug(self) -> None:
        reading = "おも"
        self.assertEqual(
            reading_audio_basename(mock_kanji(reading), "Kyoko", "mp3", reading=reading),
            f"wk_reading_kanji_637_{reading_filename_slug(reading)}_kyoko.mp3",
        )

    def test_prepare_reading_audio_field_vocab(self) -> None:
        from wk_reading_audio import prepare_reading_audio_field

        media_dir = REPO_ROOT / "out" / "test_reading_media"
        vocab = mock_vocab()
        with mock.patch("wk_reading_audio.ensure_pronunciation_audio_file", return_value=(True, True)):
            field, paths = prepare_reading_audio_field(vocab, media_dir)
        expected = reading_audio_basename(vocab, "Kyoko", "mp3", reading="がくせい")
        self.assertEqual(field, f"[sound:{expected}]")
        self.assertEqual(len(paths), 1)

    def test_select_pronunciation_audio_matches_primary_reading(self) -> None:
        vocab = {
            "id": 2760,
            "object": "vocabulary",
            "data": {
                "characters": "毎年",
                "readings": [{"reading": "まいとし", "primary": True}],
                "pronunciation_audios": [
                    {
                        "url": "https://example.com/mainen.mp3",
                        "content_type": "audio/mpeg",
                        "metadata": {"voice_actor_name": "Kyoko", "pronunciation": "まいねん"},
                    },
                    {
                        "url": "https://example.com/maitoshi.mp3",
                        "content_type": "audio/mpeg",
                        "metadata": {"voice_actor_name": "Kyoko", "pronunciation": "まいとし"},
                    },
                ],
            },
        }
        entry = select_pronunciation_audio(vocab, voice_actor="Kyoko")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["metadata"]["pronunciation"], "まいとし")

    def test_prepare_reading_audio_field_kanji_single_reading(self) -> None:
        from wk_reading_audio import prepare_reading_audio_field

        media_dir = REPO_ROOT / "out" / "test_reading_media_kanji"
        reading = "おも"
        with mock.patch("wk_reading_audio.ensure_kanji_reading_audio_file", return_value=(True, False)) as mock_tts:
            with mock.patch(
                "wk_reading_audio.tts_audio_basename_for_config",
                return_value="wk_tts_abc123.mp3",
            ):
                field, paths = prepare_reading_audio_field(mock_kanji(reading), media_dir)
        mock_tts.assert_called_once()
        self.assertEqual(field, "[sound:wk_tts_abc123.mp3]")
        self.assertEqual(len(paths), 1)

    def test_prepare_reading_audio_field_kanji_multiple_readings(self) -> None:
        from wk_reading_audio import prepare_reading_audio_field

        media_dir = REPO_ROOT / "out" / "test_reading_media_kanji_multi"
        kanji = mock_kanji("せい", "しょう")
        with mock.patch("wk_reading_audio.ensure_kanji_reading_audio_file", return_value=(True, False)) as mock_tts:
            field, paths = prepare_reading_audio_field(kanji, media_dir)
        self.assertEqual(mock_tts.call_count, 2)
        self.assertEqual(len(paths), 2)
        self.assertEqual(field.count("[sound:"), 2)

    def test_select_pronunciation_audio_prefers_kyoko(self) -> None:
        entry = select_pronunciation_audio(mock_vocab(), voice_actor="Kyoko")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["metadata"]["voice_actor_name"], "Kyoko")

    def test_format_progress_line_shows_counts(self) -> None:
        line = format_progress_line(5, 10, label="Reading audio")
        self.assertIn("Reading audio:", line)
        self.assertIn("5/10", line)
        self.assertIn("(50%)", line)
        self.assertIn("[", line)

    def test_progress_bar_finish_non_tty(self) -> None:
        from io import StringIO

        from wk_reading_audio import ReadingAudioProgressBar

        stream = StringIO()
        bar = ReadingAudioProgressBar(3, label="Reading audio", stream=stream, enabled=True)
        bar._is_tty = False
        bar.advance()
        bar.advance()
        bar.finish(ok_count=2)
        output = stream.getvalue()
        self.assertIn("Reading audio:", output)
        self.assertIn("2 with audio", output)

    def test_prepare_kana_reading_audio_field_empty_reading(self) -> None:
        from wk_reading_audio import prepare_kana_reading_audio_field

        with tempfile.TemporaryDirectory() as tmpdir:
            field, paths = prepare_kana_reading_audio_field("", Path(tmpdir))
        self.assertEqual(field, "")
        self.assertEqual(paths, [])


if __name__ == "__main__":
    unittest.main()
