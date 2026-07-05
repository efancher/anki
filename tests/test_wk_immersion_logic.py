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

    spec = importlib.util.spec_from_file_location("wk_immersion_logic", LOGIC_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_logic = _load_logic_module()
ImmersionTtsConfig = _logic.ImmersionTtsConfig
ruby_html_to_plain = _logic.ruby_html_to_plain
sentence_media_basename = _logic.sentence_media_basename
sentence_plain_text = _logic.sentence_plain_text
sentence_text_for_tts = _logic.sentence_text_for_tts
should_synthesize_note = _logic.should_synthesize_note
sound_field_value = _logic.sound_field_value
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

    def test_should_synthesize_when_sentence_present(self) -> None:
        self.assertTrue(
            should_synthesize_note(
                note_type_name="WK Yomitan Immersion",
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
