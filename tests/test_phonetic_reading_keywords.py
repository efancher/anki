"""Tests for WK reading-keyword selection used by phonetic family cards."""

from __future__ import annotations

import unittest

from wk_decks import (
    best_reading_keyword_by_kana,
    format_reading_keyword_display,
    is_useful_reading_keyword,
    phonetic_component_readings_label,
    phonetic_family_focus_html,
    phonetic_family_reading_stats,
    phonetic_reading_stats,
)


def _subject(object_type: str, mnemonic: str) -> dict:
    return {
        "object": object_type,
        "data": {
            "characters": "寺",
            "reading_mnemonic": mnemonic,
            "readings": [
                {
                    "reading": "じ",
                    "primary": True,
                    "accepted_answer": True,
                    "type": "onyomi",
                }
            ],
        },
    }


def _kanji(subject_id: int, char: str, readings: list, *, level: int = 1) -> dict:
    return {
        "id": subject_id,
        "object": "kanji",
        "data": {
            "characters": char,
            "level": level,
            "readings": [
                {
                    "reading": reading,
                    "primary": index == 0,
                    "accepted_answer": index == 0,
                    "type": "onyomi",
                }
                for index, reading in enumerate(readings)
            ],
        },
    }


class ReadingKeywordPhoneticTests(unittest.TestCase):
    def test_format_reading_keyword_display_title_cases(self) -> None:
        self.assertEqual(format_reading_keyword_display("jesus"), "Jesus")
        self.assertEqual(format_reading_keyword_display("sheep"), "Sheep")

    def test_is_useful_reading_keyword_rejects_kana_echoes(self) -> None:
        self.assertTrue(is_useful_reading_keyword("じ", "jesus"))
        self.assertFalse(is_useful_reading_keyword("こう", "こう"))
        self.assertFalse(is_useful_reading_keyword("し", ""))

    def test_best_reading_keyword_by_kana_picks_most_used(self) -> None:
        subjects = [
            _subject("kanji", "Remember <reading>Jesus</reading> (じ)."),
            _subject("kanji", "Again <reading>Jesus</reading> (じ)."),
            _subject("vocabulary", "Oddball <reading>cheese</reading> (じ)."),
            _subject("kanji", "The <reading>sheep</reading> (し) story."),
        ]
        by_kana = best_reading_keyword_by_kana(subjects)
        self.assertEqual(by_kana["じ"], "Jesus")
        self.assertEqual(by_kana["し"], "Sheep")

    def test_phonetic_component_readings_label_appends_keywords(self) -> None:
        keisei = {"寺": {"readings": ["じ", "し"]}}
        label = phonetic_component_readings_label(
            "寺",
            keisei,
            keyword_by_kana={"じ": "Jesus", "し": "Sheep"},
        )
        self.assertEqual(label, "じ - Jesus、し - Sheep")

    def test_phonetic_component_readings_label_without_map(self) -> None:
        keisei = {"寺": {"readings": ["じ"]}}
        self.assertEqual(phonetic_component_readings_label("寺", keisei), "じ")

    def test_phonetic_reading_stats_orders_by_total(self) -> None:
        members = [
            _kanji(1, "書", ["しょ"]),
            _kanji(2, "暑", ["しょ"]),
            _kanji(3, "諸", ["しょ"]),
            _kanji(4, "都", ["と"]),
            _kanji(5, "煮", ["しゃ"]),
        ]
        stats = phonetic_reading_stats(
            ["しゃ", "しょ", "と"],
            members,
            started_kanji_ids={1, 2, 4},
            keisei_kanji={},
        )
        self.assertEqual(
            stats,
            [
                ("しょ", 2, 3),
                ("と", 1, 1),
                ("しゃ", 0, 1),
            ],
        )

    def test_phonetic_family_reading_stats_are_disjoint(self) -> None:
        """Footer-friendly: each kanji counted under exactly one primary on'yomi."""
        members = [
            _kanji(670, "組", ["そ"]),
            _kanji(680, "助", ["じょ"]),
            _kanji(1130, "査", ["さ"]),
            _kanji(1489, "祖", ["そ"]),
            _kanji(1673, "狙", ["そ", "しょ"]),
            _kanji(1972, "阻", ["そ"]),
            _kanji(1960, "租", ["そ"]),
            _kanji(2281, "粗", ["そ"]),
        ]
        stats = phonetic_family_reading_stats(
            members,
            started_kanji_ids={670, 680},
            keisei_kanji={},
        )
        self.assertEqual(
            stats,
            [
                ("そ", 1, 6),
                ("じょ", 1, 1),
                ("さ", 0, 1),
            ],
        )
        self.assertEqual(sum(total for _r, _s, total in stats), len(members))
        self.assertEqual(sum(started for _r, started, _t in stats), 2)

    def test_phonetic_component_readings_label_frequency_order(self) -> None:
        keisei_phonetic = {"者": {"readings": ["しゃ", "しょ", "と"]}}
        members = [
            _kanji(1, "書", ["しょ"]),
            _kanji(2, "暑", ["しょ"]),
            _kanji(3, "都", ["と"]),
        ]
        label = phonetic_component_readings_label(
            "者",
            keisei_phonetic,
            keyword_by_kana={"しょ": "Show", "と": "Toe", "しゃ": "Shaman"},
            members=members,
            started_kanji_ids={1},
            keisei_kanji={},
        )
        self.assertEqual(label, "しょ - Show、と - Toe、しゃ - Shaman")

    def test_phonetic_family_focus_html_table(self) -> None:
        members = [
            _kanji(1, "書", ["しょ"]),
            _kanji(2, "都", ["と"]),
            _kanji(3, "助", ["じょ"]),
        ]
        html_out = phonetic_family_focus_html(
            "者",
            members,
            current_kanji_id=1,
            started_kanji_ids={1, 3},
            all_kanji_by_char={"者": _kanji(99, "者", ["しゃ"])},
            keisei_phonetic={"者": {"readings": ["しょ", "と", "しゃ"]}},
            keisei_kanji={},
            keyword_by_kana={"しょ": "Show"},
        )
        self.assertIn("phonetic-focus-table", html_out)
        self.assertIn("Started", html_out)
        self.assertIn("しょ", html_out)
        self.assertIn("Show", html_out)
        self.assertIn("じょ", html_out)
        self.assertIn("<tbody>", html_out)
        body = html_out.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        self.assertNotIn("しゃ", body)  # unused Keisei signal omitted from table rows
        # Footer matches row sums: started 2, total 3
        self.assertIn(
            "<td>All family kanji</td><td class='num'>2</td><td class='num'>3</td>",
            html_out,
        )


if __name__ == "__main__":
    unittest.main()
