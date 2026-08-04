"""Tests for immersion pitch accent formatting / lookup."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from immersion_pitch import (
    downstep_reading,
    format_immersion_pitch,
    pitch_pattern_label,
    resolve_pitch_dict_path,
    sentence_pitch_graphs_html,
    split_morae,
)


class ImmersionPitchTests(unittest.TestCase):
    def test_split_morae_small_kana(self) -> None:
        self.assertEqual(split_morae("きゃく"), ["きゃ", "く"])
        self.assertEqual(split_morae("あおい"), ["あ", "お", "い"])

    def test_pattern_labels(self) -> None:
        self.assertEqual(pitch_pattern_label(0, 3), "平板")
        self.assertEqual(pitch_pattern_label(1, 3), "頭高")
        self.assertEqual(pitch_pattern_label(2, 3), "中高")
        self.assertEqual(pitch_pattern_label(3, 3), "尾高")

    def test_downstep_reading(self) -> None:
        morae = split_morae("あおい")
        self.assertEqual(downstep_reading(morae, 0), "あおい￣")
        self.assertEqual(downstep_reading(morae, 2), "あお↓い")

    def test_format_from_index(self) -> None:
        index = {
            ("青い", "あおい"): {
                "reading": "あおい",
                "pitch": "2",
                "positions": [2],
                "source": "yomitan",
            }
        }
        fields = format_immersion_pitch("青い", "あおい", index)
        self.assertEqual(fields.positions, "2")
        self.assertIn("あお↓い", fields.accents)
        self.assertIn("中高", fields.accents)
        self.assertIn("pitch-mora", fields.graphs)

    def test_sentence_pitch_graphs_from_voicevox_phrases(self) -> None:
        html = sentence_pitch_graphs_html(
            [{"moras": [{"text": "ハ"}, {"text": "ジ"}, {"text": "メ"}], "accent": 0}]
        )
        self.assertIn(">は<", html)
        self.assertIn(">じ<", html)
        self.assertIn(">め<", html)
        self.assertIn("pitch-graph", html)

    def test_resolve_default_kanjium_if_present(self) -> None:
        path = resolve_pitch_dict_path()
        downloads = Path.home() / "Downloads" / "kanjium_pitch_accents.zip"
        if downloads.is_file():
            self.assertEqual(path, downloads.resolve())


if __name__ == "__main__":
    unittest.main()
