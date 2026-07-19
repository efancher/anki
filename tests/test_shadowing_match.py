"""Tests for Shadowing WK morphology matching and candidate filtering."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shadowing_match import (  # noqa: E402
    candidate_lemmas_in_sentence,
    kanji_stem,
    match_wk_vocab_in_sentence,
)


def _index(*entries: dict) -> dict:
    by_expression = {}
    by_reading = {}
    for entry in entries:
        expr = entry["expression"]
        by_expression[expr] = entry
        reading = entry.get("reading") or ""
        if reading:
            by_reading.setdefault(reading, []).append(entry["id"])
    return {"by_expression": by_expression, "by_reading": by_reading}


class KanjiStemTests(unittest.TestCase):
    def test_stem_from_first_to_last_kanji(self) -> None:
        self.assertEqual(kanji_stem("食べる"), "食")
        self.assertEqual(kanji_stem("分かります"), "分")
        self.assertEqual(kanji_stem("友達"), "友達")
        self.assertEqual(kanji_stem("ありがとう"), "")


class MatchWkVocabTests(unittest.TestCase):
    def test_exact_expression_match(self) -> None:
        index = _index(
            {
                "id": 1,
                "expression": "友達",
                "reading": "ともだち",
                "meaning": "friend",
                "prerequisite_ids": "10,20",
            }
        )
        matches = match_wk_vocab_in_sentence("友達が来ました。", index)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].expression, "友達")
        self.assertEqual(matches[0].wk_entry["id"], 1)

    def test_conjugated_kanji_verb_matches_stem(self) -> None:
        index = _index(
            {
                "id": 2,
                "expression": "食べる",
                "reading": "たべる",
                "meaning": "to eat",
                "prerequisite_ids": "30",
            }
        )
        matches = match_wk_vocab_in_sentence("昨日すしを食べました。", index)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].expression, "食べる")
        self.assertEqual(matches[0].surface, "食")

    def test_multiple_matches_one_per_subject(self) -> None:
        index = _index(
            {
                "id": 3,
                "expression": "今日",
                "reading": "きょう",
                "meaning": "today",
                "prerequisite_ids": "",
            },
            {
                "id": 4,
                "expression": "行く",
                "reading": "いく",
                "meaning": "to go",
                "prerequisite_ids": "",
            },
        )
        matches = match_wk_vocab_in_sentence("今日どこへ行きますか。", index)
        self.assertEqual({m.expression for m in matches}, {"今日", "行く"})
        self.assertEqual(len(matches), 2)

    def test_kana_only_word(self) -> None:
        index = _index(
            {
                "id": 5,
                "expression": "です",
                "reading": "です",
                "meaning": "to be",
                "prerequisite_ids": "",
            }
        )
        matches = match_wk_vocab_in_sentence("日本です。", index)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].expression, "です")


class CandidateLemmaTests(unittest.TestCase):
    def test_excludes_wk_expression(self) -> None:
        index = _index(
            {
                "id": 6,
                "expression": "電車",
                "reading": "でんしゃ",
                "meaning": "train",
                "prerequisite_ids": "",
            }
        )
        candidates = candidate_lemmas_in_sentence("電車と新幹線が速い。", index)
        lemmas = {c.lemma for c in candidates}
        self.assertNotIn("電車", lemmas)
        self.assertIn("新幹線", lemmas)

    def test_excludes_stopwords_and_particles_when_tokenized_or_fallback(self) -> None:
        index = _index()
        candidates = candidate_lemmas_in_sentence("これはテストです。", index)
        lemmas = {c.lemma for c in candidates}
        self.assertNotIn("これ", lemmas)
        self.assertNotIn("です", lemmas)


if __name__ == "__main__":
    unittest.main()
