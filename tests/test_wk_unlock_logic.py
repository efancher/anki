"""Tests for wk_unlock pure logic (no Anki runtime)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGIC_PATH = REPO_ROOT / "anki_addon" / "wk_unlock" / "logic.py"


def _load_logic_module():
    spec = importlib.util.spec_from_file_location("wk_unlock_logic", LOGIC_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wk_unlock_logic"] = module
    spec.loader.exec_module(module)
    return module


logic = _load_logic_module()
ANKI_QUEUE_SUSPENDED = logic.ANKI_QUEUE_SUSPENDED
CardState = logic.CardState
NoteUnlockState = logic.NoteUnlockState
WkUnlockConfig = logic.WkUnlockConfig
build_mature_subject_ids = logic.build_mature_subject_ids
card_meets_maturity = logic.card_meets_maturity
parse_prerequisite_ids = logic.parse_prerequisite_ids
prerequisites_met = logic.prerequisites_met
subject_is_mature = logic.subject_is_mature
unlock_actions_for_notes = logic.unlock_actions_for_notes
supplementary_unlock_actions_for_notes = logic.supplementary_unlock_actions_for_notes

# Classic radical→kanji→vocab maturity path (retire mode off).
CLASSIC_UNLOCK = WkUnlockConfig(retire_kanji_radical_phonetic_study=False)


class WkUnlockLogicTests(unittest.TestCase):
    def test_parse_prerequisite_ids(self) -> None:
        self.assertEqual(parse_prerequisite_ids("1, 2,3"), (1, 2, 3))
        self.assertEqual(parse_prerequisite_ids(""), ())
        self.assertEqual(parse_prerequisite_ids(None), ())

    def test_card_meets_maturity_at_threshold(self) -> None:
        config = WkUnlockConfig(mature_min_interval_days=7)
        self.assertTrue(card_meets_maturity(CardState(ivl=7, queue=2), config=config))
        self.assertFalse(card_meets_maturity(CardState(ivl=6, queue=2), config=config))
        self.assertFalse(card_meets_maturity(CardState(ivl=30, queue=ANKI_QUEUE_SUSPENDED), config=config))

    def test_mature_requires_both_card_types(self) -> None:
        config = WkUnlockConfig(mature_min_interval_days=7, mature_require_all_card_types=True)
        cards = (CardState(ivl=30, queue=2), CardState(ivl=5, queue=2))
        self.assertFalse(subject_is_mature(cards, config=config))
        cards_mature = (CardState(ivl=30, queue=2), CardState(ivl=8, queue=2))
        self.assertTrue(subject_is_mature(cards_mature, config=config))

    def test_mature_any_card_when_not_require_all(self) -> None:
        config = WkUnlockConfig(mature_min_interval_days=7, mature_require_all_card_types=False)
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
        mature_ids = build_mature_subject_ids([radical, kanji], config=CLASSIC_UNLOCK)
        self.assertEqual(mature_ids, {10})
        self.assertTrue(prerequisites_met((10,), mature_ids))

        actions = unlock_actions_for_notes(
            [radical, kanji], config=CLASSIC_UNLOCK, mature_subject_ids=mature_ids
        )
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
        actions = unlock_actions_for_notes(
            [radical], config=CLASSIC_UNLOCK, mature_subject_ids=set()
        )
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
        actions = unlock_actions_for_notes(
            [kanji], config=CLASSIC_UNLOCK, mature_subject_ids=set()
        )
        self.assertEqual(actions, [])

    def test_retire_mode_unlocks_vocab_without_kanji_maturity(self) -> None:
        vocab = NoteUnlockState(
            note_id=3,
            wk_subject_id=900,
            prerequisite_ids=(20,),
            tags=("wk-core", "vocabulary", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        config = WkUnlockConfig(retire_kanji_radical_phonetic_study=True)
        actions = unlock_actions_for_notes(
            [vocab], config=config, mature_subject_ids=set()
        )
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].unsuspend)
        self.assertIn("wk-locked", actions[0].remove_tags)
        self.assertIn("wk-deps-met", actions[0].add_tags)

    def test_retire_mode_does_not_unlock_kanji_or_radicals(self) -> None:
        radical = NoteUnlockState(
            note_id=1,
            wk_subject_id=10,
            prerequisite_ids=(),
            tags=("wk-core", "radical"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        kanji = NoteUnlockState(
            note_id=2,
            wk_subject_id=20,
            prerequisite_ids=(10,),
            tags=("wk-core", "kanji", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        config = WkUnlockConfig(retire_kanji_radical_phonetic_study=True)
        actions = unlock_actions_for_notes(
            [radical, kanji], config=config, mature_subject_ids={10}
        )
        self.assertEqual(actions, [])

    def test_supplementary_unlock_when_kanji_meaning_prereqs_mature(self) -> None:
        cloze = NoteUnlockState(
            note_id=3,
            wk_subject_id=100,
            prerequisite_ids=(10, 20),
            tags=("wanikani", "vocab-cloze", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = supplementary_unlock_actions_for_notes(
            [cloze],
            core_mature_subject_ids=set(),
            kanji_meaning_mature_subject_ids={10, 20},
        )
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].unsuspend)
        self.assertIn("wk-deps-met", actions[0].add_tags)
        self.assertIn("wk-locked", actions[0].remove_tags)

    def test_supplementary_no_unlock_when_kanji_meaning_prereqs_not_mature(self) -> None:
        cloze = NoteUnlockState(
            note_id=3,
            wk_subject_id=100,
            prerequisite_ids=(10, 20),
            tags=("wanikani", "vocab-cloze", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = supplementary_unlock_actions_for_notes(
            [cloze],
            core_mature_subject_ids={100},
            kanji_meaning_mature_subject_ids={10},
        )
        self.assertEqual(actions, [])

    def test_conjugation_unlocks_from_core_vocab_not_kanji_meaning(self) -> None:
        conjugation = NoteUnlockState(
            note_id=3,
            wk_subject_id=100,
            prerequisite_ids=(10, 20),
            tags=("wanikani", "conjugation-verb", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        # Kanji meaning mature alone is not enough.
        actions = supplementary_unlock_actions_for_notes(
            [conjugation],
            core_mature_subject_ids=set(),
            kanji_meaning_mature_subject_ids={10, 20},
        )
        self.assertEqual(actions, [])
        # Linked Core Vocabulary Guru unlocks even if kanji meaning is empty.
        actions = supplementary_unlock_actions_for_notes(
            [conjugation],
            core_mature_subject_ids={100},
            kanji_meaning_mature_subject_ids=set(),
        )
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].unsuspend)

    def test_verb_type_unlocks_from_core_vocab(self) -> None:
        verb_type = NoteUnlockState(
            note_id=4,
            wk_subject_id=100,
            prerequisite_ids=(10,),
            tags=("wanikani", "verb-type", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = supplementary_unlock_actions_for_notes(
            [verb_type],
            core_mature_subject_ids={100},
            kanji_meaning_mature_subject_ids=set(),
        )
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].unsuspend)

    def test_supplementary_unlock_when_linked_vocab_mature_in_core_without_prereqs(self) -> None:
        conjugation = NoteUnlockState(
            note_id=3,
            wk_subject_id=100,
            prerequisite_ids=(),
            tags=("wanikani", "conjugation-verb", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = supplementary_unlock_actions_for_notes(
            [conjugation],
            core_mature_subject_ids={100},
            kanji_meaning_mature_subject_ids=set(),
        )
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].unsuspend)

    def test_supplementary_no_unlock_when_vocab_not_mature_and_no_prereqs(self) -> None:
        conjugation = NoteUnlockState(
            note_id=3,
            wk_subject_id=100,
            prerequisite_ids=(),
            tags=("wanikani", "conjugation-verb", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = supplementary_unlock_actions_for_notes(
            [conjugation],
            core_mature_subject_ids=set(),
            kanji_meaning_mature_subject_ids=set(),
        )
        self.assertEqual(actions, [])

    def test_phonetic_family_unlocks_when_any_family_kanji_reviewed_once(self) -> None:
        phonetic = NoteUnlockState(
            note_id=4,
            wk_subject_id=200,
            prerequisite_ids=(10, 20, 30),
            tags=("wanikani", "phonetic-family", "phonetic-drill", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = supplementary_unlock_actions_for_notes(
            [phonetic],
            core_mature_subject_ids=set(),
            kanji_meaning_mature_subject_ids=set(),
            core_reviewed_once_subject_ids={20},
        )
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].unsuspend)

    def test_phonetic_family_stays_locked_until_family_kanji_reviewed_once(self) -> None:
        phonetic = NoteUnlockState(
            note_id=4,
            wk_subject_id=200,
            prerequisite_ids=(10, 20),
            tags=("wanikani", "phonetic-family", "wk-locked"),
            cards=(CardState(ivl=0, queue=ANKI_QUEUE_SUSPENDED),),
        )
        actions = supplementary_unlock_actions_for_notes(
            [phonetic],
            core_mature_subject_ids={200},
            kanji_meaning_mature_subject_ids={10, 20},
            core_reviewed_once_subject_ids=set(),
        )
        self.assertEqual(actions, [])

    def test_build_reviewed_once_subject_ids(self) -> None:
        seen = NoteUnlockState(
            note_id=1,
            wk_subject_id=10,
            prerequisite_ids=(),
            tags=("wk-core", "kanji"),
            cards=(CardState(ivl=0, queue=1, reps=1),),
        )
        unseen = NoteUnlockState(
            note_id=2,
            wk_subject_id=20,
            prerequisite_ids=(),
            tags=("wk-core", "kanji"),
            cards=(CardState(ivl=0, queue=0, reps=0),),
        )
        self.assertEqual(logic.build_reviewed_once_subject_ids([seen, unseen]), {10})

    def test_mining_hint_stage_one_when_kanji_mature(self) -> None:
        note = logic.MiningHintState(
            note_id=1,
            wk_subject_id=100,
            prerequisite_ids=(10, 11),
            hint_stage=0,
        )
        updates = logic.mining_hint_updates_for_notes(
            [note],
            kanji_meaning_mature_subject_ids={10, 11},
            core_mature_subject_ids=set(),
        )
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].hint_stage, "1")
        self.assertEqual(updates[0].show_kana, "1")
        self.assertEqual(updates[0].show_english, "")

    def test_mining_hint_stage_two_when_vocab_mature(self) -> None:
        note = logic.MiningHintState(
            note_id=2,
            wk_subject_id=100,
            prerequisite_ids=(10,),
            hint_stage=1,
        )
        updates = logic.mining_hint_updates_for_notes(
            [note],
            kanji_meaning_mature_subject_ids={10},
            core_mature_subject_ids={100},
        )
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].hint_stage, "2")
        self.assertEqual(updates[0].show_jj_back, "1")
        self.assertEqual(updates[0].show_kana, "")


if __name__ == "__main__":
    unittest.main()
