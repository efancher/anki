"""Tests for Migaku field map configuration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

IMMERSION_DIR = Path(__file__).resolve().parent.parent / "anki_addon" / "wk_immersion"
if str(IMMERSION_DIR) not in sys.path:
    sys.path.insert(0, str(IMMERSION_DIR))

from migaku_field_map import MIGAKU_TYPE_BY_FIELD, build_field_map
from mining_logic import strip_migaku_syntax


class MigakuFieldMapTests(unittest.TestCase):
    def test_expression_maps_to_target_word_no_syntax(self) -> None:
        mapping = build_field_map(["Expression", "Sentence"])
        self.assertEqual(mapping["Expression"], "targetWordNoSyntax")
        self.assertEqual(mapping["Sentence"], "sentenceNoSyntax")

    def test_core_migaku_media_fields(self) -> None:
        for field, expected in (
            ("Image", "firstImage"),
            ("SentenceAudio", "sentenceAudio"),
            ("Glossary", "definitions"),
            ("Translation", "translation"),
        ):
            self.assertEqual(MIGAKU_TYPE_BY_FIELD[field], expected)

    def test_strip_migaku_syntax_example(self) -> None:
        raw = (
            "皆[みな;n2]さん と 一緒[いっしょ;h] に{、}"
            "日本語[にほんご;h]の 勉強[べんきょう;h] を 頑張[がんば;k3]りましょう"
        )
        self.assertEqual(
            strip_migaku_syntax(raw),
            "皆さんと一緒に、日本語の勉強を頑張りましょう",
        )


if __name__ == "__main__":
    unittest.main()
