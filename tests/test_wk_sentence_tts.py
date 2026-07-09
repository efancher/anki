"""Tests for shared sentence TTS (VOICEVOX + edge-tts fallback)."""

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

from wk_sentence_tts import (
    SentenceTtsConfig,
    engines_to_try,
    sentence_audio_cache_key,
    sentence_audio_cache_path,
    synthesize_voicevox_wav,
    tts_audio_basename,
    voicevox_engine_reachable,
)


class WkSentenceTtsTests(unittest.TestCase):
    def test_sentence_audio_cache_key_includes_engine(self) -> None:
        config = SentenceTtsConfig()
        edge_key = sentence_audio_cache_key("本を読みます。", config, engine="edge")
        voicevox_key = sentence_audio_cache_key("本を読みます。", config, engine="voicevox")
        self.assertNotEqual(edge_key, voicevox_key)

    def test_engines_to_try_auto(self) -> None:
        self.assertEqual(engines_to_try(SentenceTtsConfig(engine="auto")), ("voicevox", "edge"))

    def test_engines_to_try_edge_only(self) -> None:
        self.assertEqual(engines_to_try(SentenceTtsConfig(engine="edge")), ("edge",))

    def test_voicevox_engine_reachable_true(self) -> None:
        response = mock.Mock()
        response.status = 200
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        with mock.patch("urllib.request.urlopen", return_value=response):
            self.assertTrue(voicevox_engine_reachable("http://127.0.0.1:50021"))

    def test_voicevox_engine_reachable_false_on_error(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            self.assertFalse(voicevox_engine_reachable("http://127.0.0.1:50021"))

    def test_synthesize_voicevox_wav_success(self) -> None:
        audio_query = {"speedScale": 1.0}
        query_resp = mock.Mock()
        query_resp.read.return_value = json.dumps(audio_query).encode("utf-8")
        query_resp.__enter__ = mock.Mock(return_value=query_resp)
        query_resp.__exit__ = mock.Mock(return_value=False)
        synth_resp = mock.Mock()
        synth_resp.read.return_value = b"RIFF....wav"
        synth_resp.__enter__ = mock.Mock(return_value=synth_resp)
        synth_resp.__exit__ = mock.Mock(return_value=False)

        with mock.patch("urllib.request.urlopen", side_effect=[query_resp, synth_resp]):
            wav = synthesize_voicevox_wav(
                "私は学生です。",
                engine_url="http://127.0.0.1:50021",
                speaker_id=3,
            )
        self.assertEqual(wav, b"RIFF....wav")

    def test_synthesize_voicevox_wav_returns_none_on_failure(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(
                synthesize_voicevox_wav(
                    "私は学生です。",
                    engine_url="http://127.0.0.1:50021",
                    speaker_id=3,
                )
            )

    def test_apply_voicevox_volume(self) -> None:
        from wk_sentence_tts import apply_voicevox_volume

        query = {"speedScale": 1.0, "volumeScale": 1.0}
        boosted = apply_voicevox_volume(query, 1.5)
        self.assertEqual(boosted["volumeScale"], 1.5)
        self.assertEqual(apply_voicevox_volume(query, 1.0), query)

    def test_sentence_audio_cache_key_includes_volume(self) -> None:
        config = SentenceTtsConfig(voicevox_volume_scale=1.5)
        quiet = sentence_audio_cache_key("本を読みます。", config, engine="voicevox")
        loud = sentence_audio_cache_key(
            "本を読みます。",
            SentenceTtsConfig(voicevox_volume_scale=2.0),
            engine="voicevox",
        )
        self.assertNotEqual(quiet, loud)

    def test_format_sentence_tts_label_auto_voicevox(self) -> None:
        config = SentenceTtsConfig(engine="auto", voicevox_speaker_id=2)
        with mock.patch("wk_sentence_tts.voicevox_engine_reachable", return_value=True):
            from wk_sentence_tts import format_sentence_tts_label

            label = format_sentence_tts_label(config)
        self.assertIn("VOICEVOX speaker 2", label)
        self.assertIn("edge fallback", label)

    def test_format_sentence_tts_label_auto_edge_only(self) -> None:
        config = SentenceTtsConfig(engine="auto")
        with mock.patch("wk_sentence_tts.voicevox_engine_reachable", return_value=False):
            from wk_sentence_tts import format_sentence_tts_label

            label = format_sentence_tts_label(config)
        self.assertIn("edge-tts", label)
        self.assertIn("unreachable", label)

    def test_tts_audio_basename_resolves_cached_engine(self) -> None:
        config = SentenceTtsConfig(engine="auto")
        text = "私は学生です。"
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            voicevox_path = sentence_audio_cache_path(text, config, engine="voicevox", cache_dir=cache_dir)
            voicevox_path.write_bytes(b"wav")
            basename = tts_audio_basename(text, config, cache_dir=cache_dir)
            self.assertEqual(basename, f"wk_tts_{voicevox_path.name}")
            self.assertTrue(basename.endswith(".wav"))

    def test_tts_audio_basename_edge_only_string_voice(self) -> None:
        basename = tts_audio_basename("本を読みます。", "ja-JP-NanamiNeural")
        self.assertTrue(basename.startswith("wk_tts_"))
        self.assertTrue(basename.endswith(".mp3"))


if __name__ == "__main__":
    unittest.main()
