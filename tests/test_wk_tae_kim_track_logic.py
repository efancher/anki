"""Tests for anki_addon/wk_tae_kim_track/logic.py (no Anki runtime)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGIC_PATH = REPO_ROOT / "anki_addon" / "wk_tae_kim_track" / "logic.py"


def _load_logic_module():
    spec = importlib.util.spec_from_file_location("wk_tae_kim_track_logic", LOGIC_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wk_tae_kim_track_logic"] = module
    spec.loader.exec_module(module)
    return module


logic = _load_logic_module()

TK_GRAMMAR_PREREQ_TAG = logic.TK_GRAMMAR_PREREQ_TAG
TK_GRAMMAR_VOCAB_TAG = logic.TK_GRAMMAR_VOCAB_TAG
CoreNoteTrackState = logic.CoreNoteTrackState
TaeKimTrackConfig = logic.TaeKimTrackConfig
active_and_ahead_lesson_slugs = logic.active_and_ahead_lesson_slugs
bump_lesson_slug = logic.bump_lesson_slug
current_lesson_filtered_searches = logic.current_lesson_filtered_searches
grammar_role_for_subject = logic.grammar_role_for_subject
parse_track_config = logic.parse_track_config
track_tag_actions_for_notes = logic.track_tag_actions_for_notes


def _track_map() -> dict:
    return {
        "reading_lessons": ["lesson-a", "lesson-b", "lesson-c"],
        "lessons": {
            "lesson-a": {
                "order": 30001,
                "direct_subject_ids": [10],
                "prereq_subject_ids": [100],
            },
            "lesson-b": {
                "order": 30002,
                "direct_subject_ids": [20],
                "prereq_subject_ids": [200],
            },
            "lesson-c": {
                "order": 30003,
                "direct_subject_ids": [30],
                "prereq_subject_ids": [300],
            },
        },
    }


class TaeKimTrackLogicTests(unittest.TestCase):
    def test_parse_track_config_requires_lesson_cap(self) -> None:
        self.assertIsNone(parse_track_config({}))
        self.assertIsNone(parse_track_config({"max_tae_kim_lesson": ""}))
        config = parse_track_config({"max_tae_kim_lesson": "lesson-a"})
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.max_tae_kim_lesson, "lesson-a")
        self.assertEqual(config.ahead_prereq_lessons, 1)

    def test_active_and_ahead_lesson_slugs(self) -> None:
        config = TaeKimTrackConfig(max_tae_kim_lesson="lesson-b", ahead_prereq_lessons=1)
        active, ahead = active_and_ahead_lesson_slugs(_track_map(), config)
        self.assertEqual(active, ["lesson-a", "lesson-b"])
        self.assertEqual(ahead, ["lesson-c"])

    def test_grammar_role_direct_beats_prereq(self) -> None:
        track_map = {
            "reading_lessons": ["lesson-a"],
            "lessons": {
                "lesson-a": {
                    "direct_subject_ids": [10],
                    "prereq_subject_ids": [10, 100],
                },
            },
        }
        is_vocab, is_prereq = grammar_role_for_subject(
            10,
            track_map,
            ["lesson-a"],
            [],
        )
        self.assertTrue(is_vocab)
        self.assertFalse(is_prereq)

    def test_ahead_lesson_prereq_only(self) -> None:
        is_vocab, is_prereq = grammar_role_for_subject(
            300,
            _track_map(),
            ["lesson-a", "lesson-b"],
            ["lesson-c"],
        )
        self.assertFalse(is_vocab)
        self.assertTrue(is_prereq)

    def test_track_tag_actions_add_and_remove(self) -> None:
        config = TaeKimTrackConfig(max_tae_kim_lesson="lesson-a", ahead_prereq_lessons=0)
        notes = [
            CoreNoteTrackState(
                note_id=1,
                wk_subject_id=10,
                tags=("wk-core", "kanji"),
            ),
            CoreNoteTrackState(
                note_id=2,
                wk_subject_id=100,
                tags=("wk-core", "radical", TK_GRAMMAR_VOCAB_TAG),
            ),
            CoreNoteTrackState(
                note_id=3,
                wk_subject_id=999,
                tags=("wk-core", "vocabulary"),
            ),
        ]
        actions = track_tag_actions_for_notes(notes, _track_map(), config)
        by_id = {action.note_id: action for action in actions}
        self.assertIn(TK_GRAMMAR_VOCAB_TAG, by_id[1].add_tags)
        self.assertIn(TK_GRAMMAR_PREREQ_TAG, by_id[2].add_tags)
        self.assertIn(TK_GRAMMAR_VOCAB_TAG, by_id[2].remove_tags)
        self.assertNotIn(3, by_id)

    def test_bump_lesson_slug(self) -> None:
        self.assertEqual(bump_lesson_slug(_track_map(), "lesson-a"), "lesson-b")
        self.assertIsNone(bump_lesson_slug(_track_map(), "lesson-c"))
        self.assertIsNone(bump_lesson_slug(_track_map(), "missing"))

    def test_current_lesson_filtered_searches(self) -> None:
        searches = current_lesson_filtered_searches("introduction-to-particles")
        self.assertIn("WK::Grammar · Current Tae Kim lesson", searches)
        self.assertIn("tag:tk-lesson-basic-introduction-to-particles", searches["WK::Grammar · Current Tae Kim lesson"])


if __name__ == "__main__":
    unittest.main()
