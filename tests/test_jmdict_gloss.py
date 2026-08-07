"""Tests for offline JMDict gloss lookup used by Shadowing candidates."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jmdict_gloss import (
    build_jmdict_gloss_index,
    enrich_shadowing_candidate,
    load_jmdict_gloss_index,
    lookup_jmdict_gloss,
    write_jmdict_gloss_index,
)


SAMPLE_WORDS = [
    {
        "id": "1",
        "kanji": [{"text": "新幹線", "common": True}],
        "kana": [{"text": "しんかんせん", "common": True}],
        "sense": [
            {
                "partOfSpeech": ["n"],
                "gloss": [{"text": "Shinkansen", "lang": "eng"}],
            }
        ],
    },
    {
        "id": "2",
        "kanji": [],
        "kana": [{"text": "バイト", "common": True}],
        "sense": [
            {
                "partOfSpeech": ["n", "vs"],
                "gloss": [{"text": "part-time job", "lang": "eng"}],
            }
        ],
    },
    {
        "id": "3",
        "kanji": [],
        "kana": [{"text": "しか"}],
        "sense": [
            {
                "partOfSpeech": ["prt"],
                "gloss": [{"text": "only", "lang": "eng"}],
            }
        ],
    },
    {
        "id": "4",
        "kanji": [{"text": "机"}],
        "kana": [{"text": "つくえ"}],
        "sense": [
            {
                "partOfSpeech": ["n"],
                "gloss": [{"text": "desk", "lang": "eng"}],
            }
        ],
    },
]


class JmdictGlossTests(unittest.TestCase):
    def test_build_skips_particles_and_looks_up(self) -> None:
        index = build_jmdict_gloss_index(SAMPLE_WORDS)
        self.assertIsNone(lookup_jmdict_gloss("しか", "しか", index))
        hit = lookup_jmdict_gloss("新幹線", "しんかんせん", index)
        assert hit is not None
        self.assertEqual(hit.gloss, "Shinkansen")
        self.assertEqual(hit.reading, "しんかんせん")
        self.assertTrue(hit.common)
        hit2 = lookup_jmdict_gloss("バイト", "", index)
        assert hit2 is not None
        self.assertEqual(hit2.gloss, "part-time job")

    def test_round_trip_index_file(self) -> None:
        index = build_jmdict_gloss_index(SAMPLE_WORDS)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gloss.json"
            write_jmdict_gloss_index(index, path)
            loaded = load_jmdict_gloss_index(path)
        self.assertEqual(
            lookup_jmdict_gloss("机", "つくえ", loaded).gloss,  # type: ignore[union-attr]
            "desk",
        )

    def test_enrich_keeps_dict_hit_and_atomic(self) -> None:
        index = build_jmdict_gloss_index(SAMPLE_WORDS)
        kept = enrich_shadowing_candidate(
            lemma="新幹線",
            reading="",
            pos="名詞",
            gloss_index=index,
        )
        self.assertTrue(kept.keep)
        self.assertEqual(kept.reading, "しんかんせん")
        self.assertEqual(kept.hint_glossary, "Shinkansen")
        self.assertIn("Shinkansen", kept.glossary)

        atomic = enrich_shadowing_candidate(
            lemma="中怖い",
            reading="",
            pos="colloquial-compound",
            gloss_index=index,
            atomic_readings={"中怖い": "ちゅうこわい"},
        )
        self.assertTrue(atomic.keep)
        self.assertEqual(atomic.reading, "ちゅうこわい")
        self.assertIn("colloquial-compound", atomic.glossary)

    def test_enrich_vets_unknown_kanji_keeps_katakana(self) -> None:
        index = build_jmdict_gloss_index(SAMPLE_WORDS)
        dropped = enrich_shadowing_candidate(
            lemma="吾先輩",
            reading="ごせんぱい",
            gloss_index=index,
            require_dict_for_kanji=True,
        )
        self.assertFalse(dropped.keep)

        katakana = enrich_shadowing_candidate(
            lemma="レイカ",
            reading="れいか",
            gloss_index=index,
            require_dict_for_kanji=True,
        )
        self.assertTrue(katakana.keep)
        self.assertEqual(katakana.hint_glossary, "")


if __name__ == "__main__":
    unittest.main()
