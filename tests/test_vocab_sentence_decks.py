"""Tests for WK context-sentence vocabulary decks."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vocab_sentence_decks import (
    VocabSentenceItem,
    build_vocab_sentence_meaning_deck,
    build_vocab_sentence_reading_deck,
    collect_vocab_sentence_items,
    highlight_target_in_sentence,
    make_vocab_sentence_meaning_model,
    make_vocab_sentence_reading_model,
    select_vocab_sentence_highlight,
)
from wk_decks import WK_SRS_STAGE_MASTER


def mock_vocab(
    vocab_id: int,
    *,
    characters: str = "学生",
    reading: str = "がくせい",
    meanings: list | None = None,
    component_ids: list | None = None,
    sentences: list | None = None,
) -> dict:
    return {
        "id": vocab_id,
        "object": "vocabulary",
        "data": {
            "characters": characters,
            "level": 5,
            "meanings": meanings
            or [{"meaning": "Student", "primary": True}],
            "readings": [{"reading": reading, "type": "onyomi", "primary": True}],
            "component_subject_ids": component_ids if component_ids is not None else [10, 11],
            "context_sentences": sentences
            or [
                {
                    "ja": "私は学生です。",
                    "en": "I am a student.",
                }
            ],
        },
    }


class VocabSentenceDeckTests(unittest.TestCase):
    def test_highlight_target_in_sentence(self) -> None:
        result = highlight_target_in_sentence("私は学生です。", ["学生"])
        self.assertIsNotNone(result)
        highlighted, plain = result
        self.assertEqual(plain, "私は学生です。")
        self.assertIn('<span class="target">学生</span>', highlighted)

    def test_select_vocab_sentence_highlight(self) -> None:
        vocab = mock_vocab(1)
        selected = select_vocab_sentence_highlight(vocab)
        self.assertIsNotNone(selected)
        sentence, highlighted, full = selected
        self.assertEqual(full, "私は学生です。")
        self.assertIn("target", highlighted)
        self.assertEqual(sentence.get("en"), "I am a student.")

    def test_collect_respects_min_srs(self) -> None:
        vocab = mock_vocab(42)
        assignment_index = {42: {"data": {"subject_id": 42, "srs_stage": 1}}}
        self.assertEqual(
            collect_vocab_sentence_items([vocab], assignment_index, min_srs=WK_SRS_STAGE_MASTER),
            [],
        )
        assignment_index[42]["data"]["srs_stage"] = WK_SRS_STAGE_MASTER
        items = collect_vocab_sentence_items([vocab], assignment_index, min_srs=WK_SRS_STAGE_MASTER)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].expression, "学生")

    def test_meaning_model_front_has_no_answer(self) -> None:
        model = make_vocab_sentence_meaning_model()
        qfmt = model.templates[0]["qfmt"]
        self.assertIn("{{HighlightedSentence}}", qfmt)
        self.assertNotIn("{{Meaning}}", qfmt)

    def test_reading_model_types_reading(self) -> None:
        model = make_vocab_sentence_reading_model()
        qfmt = model.templates[0]["qfmt"]
        self.assertIn("{{type:Reading}}", qfmt)
        self.assertIn("{{HighlightedSentence}}", qfmt)

    def test_build_meaning_deck_sets_prereqs_and_lock(self) -> None:
        vocab = mock_vocab(99, component_ids=[10, 11])
        selected = select_vocab_sentence_highlight(vocab)
        assert selected is not None
        _, highlighted, full = selected
        item = VocabSentenceItem(
            vocab=vocab,
            highlighted_sentence=highlighted,
            full_sentence=full,
            sentence_en="I am a student.",
            source_ja="私は学生です。",
            expression="学生",
            reading="がくせい",
            meaning="Student",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path, deck, _ = build_vocab_sentence_meaning_deck(
                [item],
                Path(tmp),
                {},
                sentence_audio=False,
            )
            self.assertEqual(path.name, "wk_vocab_sentence_meaning.apkg")
            note = deck.notes[0]
            self.assertEqual(note.fields[2], "10,11")
            self.assertIn("wk-locked", note.tags)
            self.assertIn("vocab-sentence-meaning", note.tags)

    def test_build_reading_deck_without_kanji_prereqs_is_unlocked(self) -> None:
        vocab = mock_vocab(100, component_ids=[])
        selected = select_vocab_sentence_highlight(vocab)
        assert selected is not None
        _, highlighted, full = selected
        item = VocabSentenceItem(
            vocab=vocab,
            highlighted_sentence=highlighted,
            full_sentence=full,
            sentence_en="I am a student.",
            source_ja="私は学生です。",
            expression="学生",
            reading="がくせい",
            meaning="Student",
        )
        with tempfile.TemporaryDirectory() as tmp:
            _, deck, _ = build_vocab_sentence_reading_deck(
                [item],
                Path(tmp),
                {},
                sentence_audio=False,
            )
            note = deck.notes[0]
            self.assertEqual(note.fields[2], "")
            self.assertNotIn("wk-locked", note.tags)


if __name__ == "__main__":
    unittest.main()
