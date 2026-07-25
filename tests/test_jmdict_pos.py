"""Tests for offline JMDict POS lookup."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jmdict_pos import (
    build_jmdict_pos_index,
    jmdict_tags_to_word_class,
    load_jmdict_pos_index,
    lookup_jmdict_word_class,
    pos_string_to_word_class,
    write_jmdict_pos_index,
)


SAMPLE_WORDS = [
    {
        "id": "1",
        "kanji": [{"text": "食べる"}],
        "kana": [{"text": "たべる"}],
        "sense": [{"partOfSpeech": ["v1"], "gloss": [{"text": "to eat"}]}],
    },
    {
        "id": "2",
        "kanji": [{"text": "話す"}],
        "kana": [{"text": "はなす"}],
        "sense": [{"partOfSpeech": ["v5s"], "gloss": [{"text": "to speak"}]}],
    },
    {
        "id": "3",
        "kanji": [{"text": "勉強"}],
        "kana": [{"text": "べんきょう"}],
        "sense": [{"partOfSpeech": ["n", "vs"], "gloss": [{"text": "study"}]}],
    },
    {
        "id": "4",
        "kanji": [{"text": "大きい"}],
        "kana": [{"text": "おおきい"}],
        "sense": [{"partOfSpeech": ["adj-i"], "gloss": [{"text": "big"}]}],
    },
    {
        "id": "5",
        "kanji": [],
        "kana": [{"text": "きれい"}],
        "sense": [{"partOfSpeech": ["adj-na"], "gloss": [{"text": "pretty"}]}],
    },
    {
        "id": "6",
        "kanji": [{"text": "机"}],
        "kana": [{"text": "つくえ"}],
        "sense": [{"partOfSpeech": ["n"], "gloss": [{"text": "desk"}]}],
    },
    {
        "id": "7",
        "kanji": [{"text": "来る"}],
        "kana": [{"text": "くる"}],
        "sense": [{"partOfSpeech": ["vk"], "gloss": [{"text": "to come"}]}],
    },
]


class JmdictPosTests(unittest.TestCase):
    def test_pos_string_mapping(self) -> None:
        self.assertEqual(pos_string_to_word_class("adj-i"), "i_adjective")
        self.assertEqual(pos_string_to_word_class("v5r"), "godan")
        self.assertEqual(jmdict_tags_to_word_class(["n", "vs"]), "suru_verb")
        self.assertIsNone(jmdict_tags_to_word_class(["n"]))

    def test_build_index_and_lookup(self) -> None:
        index = build_jmdict_pos_index(SAMPLE_WORDS)
        self.assertEqual(lookup_jmdict_word_class("食べる", "たべる", index), "ichidan")
        self.assertEqual(lookup_jmdict_word_class("話す", "はなす", index), "godan")
        self.assertEqual(lookup_jmdict_word_class("勉強", "べんきょう", index), "suru_verb")
        self.assertEqual(
            lookup_jmdict_word_class("勉強する", "べんきょうする", index), "suru_verb"
        )
        self.assertEqual(lookup_jmdict_word_class("大きい", "おおきい", index), "i_adjective")
        self.assertEqual(lookup_jmdict_word_class("きれい", "きれい", index), "na_adjective")
        self.assertEqual(lookup_jmdict_word_class("来る", "くる", index), "irregular_verb")
        self.assertIsNone(lookup_jmdict_word_class("机", "つくえ", index))

    def test_round_trip_index_file(self) -> None:
        index = build_jmdict_pos_index(SAMPLE_WORDS)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            write_jmdict_pos_index(index, path)
            loaded = load_jmdict_pos_index(path)
        self.assertEqual(loaded["食べる|たべる"], "ichidan")


if __name__ == "__main__":
    unittest.main()
