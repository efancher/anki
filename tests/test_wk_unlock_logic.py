"""Tests for wk_unlock pure logic (no Anki runtime)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WK_UNLOCK_DIR = REPO_ROOT / "anki_addon" / "wk_unlock"
if str(WK_UNLOCK_DIR) not in sys.path:
    sys.path.insert(0, str(WK_UNLOCK_DIR))

from logic import (  # noqa: E402
    ANKI_QUEUE_SUSPENDED,
    CardState,
    NoteUnlockState,
    WkUnlockConfig,
    build_mature_subject_ids,
    card_meets_maturity,
    parse_prerequisite_ids,
    prerequisites_met,
    subject_is_mature,
    unlock_actions_for_notes,
)


class WkUnlockLogicTests(unittest.TestCase):
    def test_parse_prerequisite_ids(self) -> None:
        self.assertEqual(parse_prerequisite_ids("1, 2,3"), (1, 2, 3))
        self.assertEqual(parse_prerequisite_ids(""), ())
        self.assertEqual(parse_prerequisite_ids(None), ())

    def test_card_meets_maturity_at_threshold(self) -> None:
        config = WkUnlockConfig(mature_min_interval_days=21)
        self.assertTrue(card_meets_maturity(CardState(ivl=21, queue=2), config=config))
        self.assertFalse(card_meets_maturity(CardState(ivl=20, queue=2), config=config))
        self.assertFalse(card_meets_maturity(CardState(ivl=30, queue=ANKI_QUEUE_SUSPENDED), config=config))

    def test_mature_requires_both_card_types(self) -> None:
        config = WkUnlockConfig(mature_min_interval_days=21, mature_require_all_card_types=True)
        cards = (CardState(ivl=30, queue=2), CardState(ivl=5, queue=2))
        self.assertFalse(subject_is_mature(cards, config=config))
        cards_mature = (CardState(ivl=30, queue=2), CardState(ivl=25, queue=2))
        self.assertTrue(subject_is_mature(cards_mature, config=config))

    def test_mature_any_card_when_not_require_all(self) -> None:
        config = WkUnlockConfig(mature_min_interval_days=21, mature_require_all_card_types=False)
        cards = (CardState(ivl=30, queue=2), CardState(ivl=5, queue=2))
        self.assertTrue(subject_is_mature(cards, config=config))

    def test_unlock_unsuspend_when_deps_met(self) -> None:
        radical = NoteUnlockState(
            note_id=1,
            wk_subject_id=10,
            prerequisite_ids=(),
            tags=("wk-core", "wk-mature"),
            cards=(CardState(ivl=30, queue=2),),
        )
        kanji = NoteUnlockState(
            note_id=2,
            wk_subject_id=20,
            prerequisite_ids=(10,),
            tags=("wk-core", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED), CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED)),
        )
        mature_ids = build_mature_subject_ids([radical, kanji], config=WkUnlockConfig())
        self.assertEqual(mature_ids, {10})
        self.assertTrue(prerequisites_met((10,), mature_ids))

        actions = unlock_actions_for_notes([radical, kanji], config=WkUnlockConfig(), mature_subject_ids=mature_ids)
        kanji_action = next(action for action in actions if action.note_id == 2)
        self.assertTrue(kanji_action.unsuspend)
        self.assertIn("wk-deps-met", kanji_action.add_tags)
        self.assertIn("wk-locked", kanji_action.remove_tags)

    def test_root_radical_unlock_without_wk_locked_tag(self) -> None:
        radical = NoteUnlockState(
            note_id=1,
            wk_subject_id=10,
            prerequisite_ids=(),
            tags=("wk-core",),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = unlock_actions_for_notes([radical], config=WkUnlockConfig(), mature_subject_ids=set())
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].unsuspend)
        self.assertIn("wk-deps-met", actions[0].add_tags)

    def test_no_unlock_when_prereq_not_mature(self) -> None:
        kanji = NoteUnlockState(
            note_id=2,
            wk_subject_id=20,
            prerequisite_ids=(10,),
            tags=("wk-core", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = unlock_actions_for_notes([kanji], config=WkUnlockConfig(), mature_subject_ids=set())
        self.assertEqual(actions, [])

    def test_supplementary_unlock_when_linked_vocab_mature(self) -> None:
        from logic import supplementary_unlock_actions_for_notes

        cloze = NoteUnlockState(
            note_id=3,
            wk_subject_id=100,
            prerequisite_ids=(),
            tags=("wanikani", "vocab-cloze", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = supplementary_unlock_actions_for_notes([cloze], mature_subject_ids={100})
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].unsuspend)
        self.assertIn("wk-deps-met", actions[0].add_tags)
        self.assertIn("wk-locked", actions[0].remove_tags)

    def test_supplementary_no_unlock_when_vocab_not_mature(self) -> None:
        from logic import supplementary_unlock_actions_for_notes

        cloze = NoteUnlockState(
            note_id=3,
            wk_subject_id=100,
            prerequisite_ids=(),
            tags=("wanikani", "vocab-cloze", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = supplementary_unlock_actions_for_notes([cloze], mature_subject_ids=set())
        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
