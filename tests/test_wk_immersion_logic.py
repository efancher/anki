"""Tests for wk_immersion sentence TTS logic."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGIC_PATH = REPO_ROOT / "anki_addon" / "wk_immersion" / "logic.py"


def _load_logic_module():
    import importlib.util

    addon_dir = LOGIC_PATH.parent
    if str(addon_dir) not in sys.path:
        sys.path.insert(0, str(addon_dir))
    spec = importlib.util.spec_from_file_location("wk_immersion_logic", LOGIC_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_logic = _load_logic_module()
ImmersionTtsConfig = _logic.ImmersionTtsConfig
immersion_audio_cache_path = _logic.immersion_audio_cache_path
kanji_plain_from_furigana_html = _logic.kanji_plain_from_furigana_html
ruby_html_to_plain = _logic.ruby_html_to_plain
sentence_media_basename = _logic.sentence_media_basename
sentence_plain_text = _logic.sentence_plain_text
sentence_text_for_tts = _logic.sentence_text_for_tts
should_synthesize_note = _logic.should_synthesize_note
sound_field_value = _logic.sound_field_value
audio_field_value = _logic.audio_field_value
sentence_audio_autoplay = _logic.sentence_audio_autoplay
sentence_audio_fields_needing_synth = _logic.sentence_audio_fields_needing_synth
unwrap_sound_tag = _logic.unwrap_sound_tag
uses_native_sentence_clip = _logic.uses_native_sentence_clip
synthesize_sentence_audio = _logic.synthesize_sentence_audio
synthesize_voicevox_wav = _logic.synthesize_voicevox_wav


class ImmersionTtsLogicTests(unittest.TestCase):
    def test_sentence_plain_text_strips_html(self) -> None:
        self.assertEqual(sentence_plain_text("学生<b>が</b>"), "学生が")

    def test_ruby_html_to_plain_uses_readings(self) -> None:
        html = '<ruby>今日<rt>きょう</rt></ruby>は<ruby>少<rt>すこ</rt></ruby>し<ruby>頭痛<rt>ずつう</rt></ruby>がする'
        self.assertEqual(ruby_html_to_plain(html), "きょうはすこしずつうがする")

    def test_sentence_text_for_tts_prefers_kanji_when_same_line(self) -> None:
        short = "頭痛がします。"
        furigana_html = (
            '<span class="term"><ruby>頭痛<rt>ずつう</rt></ruby></span>'
            '<span class="term">がします</span><span class="term">。</span>'
        )
        self.assertEqual(sentence_text_for_tts(short, furigana_html), "頭痛がします。")

    def test_sentence_text_for_tts_prefers_longer_furigana_kanji(self) -> None:
        short = "頭痛がします。"
        long_html = (
            '<ruby>今日<rt>きょう</rt></ruby>は<ruby>少<rt>すこ</rt></ruby>し'
            '<ruby>頭痛<rt>ずつう</rt></ruby>がする'
        )
        self.assertEqual(
            sentence_text_for_tts(short, long_html),
            "今日は少し頭痛がする",
        )

    def test_sentence_text_for_tts_falls_back_to_sentence(self) -> None:
        self.assertEqual(sentence_text_for_tts("今日は少し頭痛がする。", ""), "今日は少し頭痛がする。")

    def test_sentence_text_for_tts_strips_anki_bracket_furigana(self) -> None:
        sentence = "親鳥がえさを運んできました。"
        furigana = "親鳥[おやどり]がえさを運[はこ]んで来[き]ました。"
        self.assertEqual(sentence_text_for_tts(sentence, furigana), sentence)

    def test_sentence_text_for_tts_satori_spaced_brackets(self) -> None:
        sentence = "暖かい春がやって来ました。"
        furigana = " 暖[あたた]かい 春[はる]がやって 来[き]ました。"
        self.assertEqual(sentence_text_for_tts(sentence, furigana), sentence)

    def test_kanji_plain_from_anki_brackets(self) -> None:
        self.assertEqual(
            kanji_plain_from_furigana_html("親鳥[おやどり]がえさを運[はこ]んで来[き]ました。"),
            "親鳥がえさを運んで来ました。",
        )

    def test_should_synthesize_when_sentence_present(self) -> None:
        for note_type in (
            "WK Yomitan Immersion",
            "WK Migaku Immersion",
            "WK Satori Immersion",
        ):
            with self.subTest(note_type=note_type):
                self.assertTrue(
                    should_synthesize_note(
                        note_type_name=note_type,
                        sentence="頭が痛い。",
                        sentence_audio="",
                        config=ImmersionTtsConfig(),
                        on_mine=True,
                    )
                )

    def test_should_not_resynthesize_existing_audio(self) -> None:
        self.assertFalse(
            should_synthesize_note(
                note_type_name="WK Yomitan Immersion",
                sentence="頭が痛い。",
                sentence_audio="[sound:foo.wav]",
                sentence_audio_easy="[sound:bar.wav]",
                config=ImmersionTtsConfig(),
                on_mine=True,
            )
        )

    def test_media_basename_differs_by_speed(self) -> None:
        normal = sentence_media_basename(
            "テスト", engine="voicevox", speaker_id=3, speed_scale=1.0, ext=".wav"
        )
        easy = sentence_media_basename(
            "テスト", engine="voicevox", speaker_id=3, speed_scale=0.75, ext=".wav"
        )
        self.assertNotEqual(normal, easy)

    def test_should_not_synthesize_shadowing_sentence_audio(self) -> None:
        for note_type in ("WK Shadowing Immersion", "WK Shadowing Candidate"):
            with self.subTest(note_type=note_type):
                self.assertTrue(uses_native_sentence_clip(note_type))
                self.assertFalse(
                    should_synthesize_note(
                        note_type_name=note_type,
                        sentence="頭が痛い。",
                        sentence_audio="",
                        config=ImmersionTtsConfig(),
                        on_mine=True,
                    )
                )
                self.assertEqual(
                    sentence_audio_fields_needing_synth(
                        sentence_audio="",
                        sentence_audio_easy="",
                        force=True,
                        note_type_name=note_type,
                    ),
                    (),
                )

    def test_force_does_not_replace_native_shadowing_clip(self) -> None:
        needed = sentence_audio_fields_needing_synth(
            sentence_audio="[sound:wk_shadowing_source-demo_sentence-001.m4a]",
            sentence_audio_easy="",
            force=True,
            note_type_name="WK Yomitan Immersion",
        )
        self.assertNotIn("SentenceAudio", needed)
        self.assertNotIn("SentenceAudioEasy", needed)

    def test_should_synthesize_when_easy_missing(self) -> None:
        self.assertTrue(
            should_synthesize_note(
                note_type_name="WK Satori Immersion",
                sentence="頭が痛い。",
                sentence_audio="[sound:foo.wav]",
                sentence_audio_easy="",
                config=ImmersionTtsConfig(),
                on_mine=True,
            )
        )

    def test_should_not_resynthesize_when_both_audio_set(self) -> None:
        self.assertFalse(
            should_synthesize_note(
                note_type_name="WK Satori Immersion",
                sentence="頭が痛い。",
                sentence_audio="[sound:foo.wav]",
                sentence_audio_easy="[sound:bar.wav]",
                config=ImmersionTtsConfig(),
                on_mine=True,
            )
        )

    def test_media_basename_is_stable(self) -> None:
        a = sentence_media_basename("テスト", engine="voicevox", speaker_id=3, ext=".wav")
        b = sentence_media_basename("テスト", engine="voicevox", speaker_id=3, ext=".wav")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("wk_immersion_sent_"))

    def test_sound_field_value(self) -> None:
        self.assertEqual(sound_field_value("foo.wav"), "[sound:foo.wav]")

    def test_audio_field_value_autoplay_and_manual(self) -> None:
        self.assertEqual(audio_field_value("foo.wav", autoplay=True), "[sound:foo.wav]")
        self.assertEqual(audio_field_value("foo.wav", autoplay=False), "[sound:foo.wav]")
        self.assertEqual(
            audio_field_value("[sound:foo.wav]", autoplay=False), "[sound:foo.wav]"
        )
        self.assertEqual(unwrap_sound_tag("[sound:bar.mp3]"), "bar.mp3")

    def test_satori_normal_does_not_autoplay(self) -> None:
        self.assertFalse(
            sentence_audio_autoplay(
                note_type_name="WK Satori Immersion", field_name="SentenceAudio"
            )
        )
        self.assertTrue(
            sentence_audio_autoplay(
                note_type_name="WK Satori Immersion", field_name="SentenceAudioEasy"
            )
        )
        self.assertTrue(
            sentence_audio_autoplay(
                note_type_name="WK Yomitan Immersion", field_name="SentenceAudio"
            )
        )

    def test_shadowing_sentence_audio_autoplays(self) -> None:
        self.assertTrue(
            sentence_audio_autoplay(
                note_type_name="WK Shadowing Immersion", field_name="SentenceAudio"
            )
        )
        self.assertTrue(
            sentence_audio_autoplay(
                note_type_name="WK Shadowing Candidate", field_name="SentenceAudio"
            )
        )
        self.assertFalse(
            sentence_audio_autoplay(
                note_type_name="WK Shadowing Immersion", field_name="Audio"
            )
        )
        self.assertFalse(
            sentence_audio_autoplay(
                note_type_name="WK Satori Immersion", field_name="Audio"
            )
        )
        self.assertFalse(
            sentence_audio_autoplay(
                note_type_name="WK Shadowing Candidate", field_name="ReadingAudio"
            )
        )
        self.assertFalse(
            sentence_audio_autoplay(
                note_type_name="WK Satori Immersion", field_name="ReadingAudio"
            )
        )

    def test_synthesize_uses_disk_cache(self) -> None:
        import tempfile
        import unittest.mock
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            config = ImmersionTtsConfig(engine="voicevox", cache_enabled=True)
            cache_path = immersion_audio_cache_path(
                "頭が痛い。",
                engine="voicevox",
                speaker_id=config.voicevox_speaker_id,
                volume_scale=config.voicevox_volume_scale,
                speed_scale=1.0,
                ext=".wav",
                cache_dir=cache_dir,
            )
            cache_dir.mkdir(parents=True)
            cache_path.write_bytes(b"RIFF-CACHED")

            with unittest.mock.patch.object(_logic, "synthesize_voicevox_wav") as synth:
                audio, ext, engine = synthesize_sentence_audio(
                    "頭が痛い。",
                    config=config,
                    temp_dir=Path(tmp),
                    edge_tts_script=Path(tmp) / "missing.py",
                    speed_scale=1.0,
                    force=False,
                    cache_dir=cache_dir,
                )
            synth.assert_not_called()
            self.assertEqual(audio, b"RIFF-CACHED")
            self.assertEqual(ext, ".wav")
            self.assertEqual(engine, "voicevox")

    def test_synthesize_force_bypasses_cache(self) -> None:
        import tempfile
        import unittest.mock
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            config = ImmersionTtsConfig(engine="voicevox", cache_enabled=True)
            cache_path = immersion_audio_cache_path(
                "頭が痛い。",
                engine="voicevox",
                speaker_id=config.voicevox_speaker_id,
                volume_scale=config.voicevox_volume_scale,
                speed_scale=1.0,
                ext=".wav",
                cache_dir=cache_dir,
            )
            cache_dir.mkdir(parents=True)
            cache_path.write_bytes(b"RIFF-OLD")

            with unittest.mock.patch.object(
                _logic, "synthesize_voicevox_wav", return_value=b"RIFF-NEW"
            ) as synth:
                audio, ext, engine = synthesize_sentence_audio(
                    "頭が痛い。",
                    config=config,
                    temp_dir=Path(tmp),
                    edge_tts_script=Path(tmp) / "missing.py",
                    speed_scale=1.0,
                    force=True,
                    cache_dir=cache_dir,
                )
            synth.assert_called_once()
            self.assertEqual(audio, b"RIFF-NEW")
            self.assertEqual(cache_path.read_bytes(), b"RIFF-NEW")

    def test_synthesize_voicevox_wav(self) -> None:
        import unittest.mock

        def _response(payload: bytes):
            mock_resp = unittest.mock.Mock()
            mock_resp.read.return_value = payload
            mock_resp.__enter__ = unittest.mock.Mock(return_value=mock_resp)
            mock_resp.__exit__ = unittest.mock.Mock(return_value=False)
            return mock_resp

        responses = [
            _response(b'{"accent_phrases":[]}'),
            _response(b"RIFF"),
        ]
        with unittest.mock.patch.object(_logic.urllib.request, "urlopen", side_effect=responses):
            wav = synthesize_voicevox_wav("頭が痛い。", engine_url="http://127.0.0.1:50021", speaker_id=3)
        self.assertEqual(wav, b"RIFF")


if __name__ == "__main__":
    unittest.main()
