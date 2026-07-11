#!/usr/bin/env python3
from __future__ import annotations

import unittest

from satori_gloss import (
    GlossSentence,
    format_worksheet,
    gloss_from_anki_fields,
    ichi_moe_url,
    strip_anki_html,
)


class SatoriGlossTests(unittest.TestCase):
    def test_strip_anki_html(self) -> None:
        self.assertEqual(
            strip_anki_html("<div>暖かい<br>春</div>"),
            "暖かい\n春",
        )

    def test_gloss_from_fields_prefers_sentence(self) -> None:
        item = gloss_from_anki_fields(
            {
                "Sentence": {"value": "暖かい春がやって来ました。"},
                "ClozeSentence": {"value": "{{c1::暖かい}}春がやって来ました。"},
                "Translation": {"value": "The warm spring came along."},
                "Expression": {"value": "暖かい"},
                "Reading": {"value": "あたたかい"},
            },
            note_id=42,
        )
        assert item is not None
        self.assertEqual(item.japanese, "暖かい春がやって来ました。")
        self.assertEqual(item.english, "The warm spring came along.")
        self.assertEqual(item.expression, "暖かい")
        self.assertEqual(item.note_id, 42)

    def test_gloss_unwraps_cloze_when_sentence_missing(self) -> None:
        item = gloss_from_anki_fields(
            {"ClozeSentence": {"value": "{{c1::です}}。"}},
        )
        assert item is not None
        self.assertEqual(item.japanese, "です。")

    def test_ichi_moe_url_requests_kana(self) -> None:
        url = ichi_moe_url("日本ではありません。")
        self.assertIn("r=kana", url)
        self.assertTrue(url.startswith("https://ichi.moe/cl/qr/?"))

    def test_worksheet_keeps_english_and_blanks(self) -> None:
        text = format_worksheet(
            GlossSentence(
                japanese="暖かい春がやって来ました。",
                english="The warm spring came along.",
                expression="暖かい",
                reading="あたたかい",
                note_id=1,
            )
        )
        self.assertIn("JP:    暖かい春がやって来ました。", text)
        self.assertIn("CHUNK:", text)
        self.assertIn("ROLE:", text)
        self.assertIn("LIT:", text)
        self.assertIn("EN:    The warm spring came along.", text)
        self.assertIn("Target word: 暖かい (あたたかい)", text)
        self.assertIn(ichi_moe_url("暖かい春がやって来ました。"), text)
        self.assertNotIn("warm spring", text.split("EN:", 1)[0])


if __name__ == "__main__":
    unittest.main()
