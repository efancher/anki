"""Tests for wk_immersion model upgrade template snippets."""

from __future__ import annotations

import unittest
from pathlib import Path

UPGRADE_PATH = Path(__file__).resolve().parent.parent / "anki_addon" / "wk_immersion" / "model_upgrade.py"


class ModelUpgradeTests(unittest.TestCase):
    def test_upgrade_module_defines_legacy_and_v6_blocks(self) -> None:
        source = UPGRADE_PATH.read_text(encoding="utf-8")
        self.assertIn("_LEGACY_CONTEXT_AUDIO", source)
        self.assertIn("_V7_SENTENCE_SECTION", source)

    def test_context_section_needs_repair_when_nested(self) -> None:
        source = UPGRADE_PATH.read_text(encoding="utf-8")
        self.assertIn("_context_section_needs_repair", source)
        self.assertIn('back.count("{{#SentenceAudio}}") > 1', source)

    def test_legacy_block_upgrades_to_sentence_audio_wrapper(self) -> None:
        legacy = (
            "  {{#VoicevoxAudio}}<div class=\"sentence-audio voicevox-audio\">{{VoicevoxAudio}}</div>"
            "{{/VoicevoxAudio}}\n"
            "  {{^VoicevoxAudio}}\n"
            "  {{#Audio}}<div class=\"sentence-audio mined-audio\">{{Audio}}</div>{{/Audio}}\n"
            "  {{^Audio}}<div class=\"sentence-tts\">{{tts ja_JP:Sentence}}</div>{{/Audio}}\n"
            "  {{/VoicevoxAudio}}\n"
        )
        upgraded = legacy.replace(
            legacy,
            "  {{#SentenceAudio}}<div class=\"sentence-audio sentence-tts-file\">{{SentenceAudio}}</div>"
            "{{/SentenceAudio}}\n  {{^SentenceAudio}}\n" + legacy + "  {{/SentenceAudio}}\n",
        )
        self.assertIn("{{#SentenceAudio}}", upgraded)


if __name__ == "__main__":
    unittest.main()
