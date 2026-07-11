"""Tests for wk_deck_stats pure logic."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGIC_PATH = REPO_ROOT / "anki_addon" / "wk_deck_stats" / "logic.py"


def _load_logic_module():
    spec = importlib.util.spec_from_file_location("wk_deck_stats_logic", LOGIC_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wk_deck_stats_logic"] = module
    spec.loader.exec_module(module)
    return module


logic = _load_logic_module()
ANKI_CARD_TYPE_LEARN = logic.ANKI_CARD_TYPE_LEARN
ANKI_CARD_TYPE_NEW = logic.ANKI_CARD_TYPE_NEW
ANKI_CARD_TYPE_REVIEW = logic.ANKI_CARD_TYPE_REVIEW
ANKI_QUEUE_SUSPENDED = logic.ANKI_QUEUE_SUSPENDED
CORE_KANJI_DECK = logic.CORE_KANJI_DECK
CORE_RADICALS_DECK = logic.CORE_RADICALS_DECK
CORE_VOCABULARY_DECK = logic.CORE_VOCABULARY_DECK
CardRow = logic.CardRow
NoteRow = logic.NoteRow
WK_LOCKED_TAG = logic.WK_LOCKED_TAG
build_deck_stats_report = logic.build_deck_stats_report
build_jlpt_bucket_rows = logic.build_jlpt_bucket_rows
build_mature_subject_ids = logic.build_mature_subject_ids
build_vocab_locked_by_wk_level = logic.build_vocab_locked_by_wk_level
classify_wk_note = logic.classify_wk_note
format_deck_stats_report = logic.format_deck_stats_report
is_vocab_locked_by_kanji_prereq = logic.is_vocab_locked_by_kanji_prereq
sort_deck_names = logic.sort_deck_names
wk_level_to_jlpt = logic.wk_level_to_jlpt


def _card(**kwargs) -> CardRow:
    defaults = {
        "card_id": 1,
        "note_id": 10,
        "deck_name": CORE_KANJI_DECK,
        "card_type": ANKI_CARD_TYPE_REVIEW,
        "queue": 2,
        "ivl": 10,
        "reps": 5,
    }
    defaults.update(kwargs)
    return CardRow(**defaults)


def _note(**kwargs) -> NoteRow:
    defaults = {
        "note_id": 10,
        "deck_name": CORE_KANJI_DECK,
        "tags": ("wk-core", "kanji", "wk-level-5"),
        "cards": (_card(),),
        "wk_subject_id": 10,
        "prerequisite_ids": (),
        "wk_level": 5,
        "is_kanji": True,
        "is_vocabulary": False,
        "is_radical": False,
    }
    defaults.update(kwargs)
    return NoteRow(**defaults)


class WkDeckStatsLogicTests(unittest.TestCase):
    def test_classify_wk_note_buckets(self) -> None:
        self.assertEqual(
            classify_wk_note(_note(cards=(_card(ivl=0, reps=0),))),
            "unseen",
        )
        self.assertEqual(
            classify_wk_note(_note(cards=(_card(ivl=2, reps=3),))),
            "apprentice",
        )
        self.assertEqual(classify_wk_note(_note(cards=(_card(ivl=7, reps=4),))), "guru")
        self.assertEqual(classify_wk_note(_note(cards=(_card(ivl=29, reps=4),))), "guru")
        self.assertEqual(classify_wk_note(_note(cards=(_card(ivl=30, reps=4),))), "master")
        self.assertEqual(
            classify_wk_note(_note(tags=(WK_LOCKED_TAG,), cards=(_card(ivl=30, reps=4),))),
            "locked",
        )
        self.assertEqual(
            classify_wk_note(_note(cards=(_card(queue=ANKI_QUEUE_SUSPENDED, ivl=30, reps=4),))),
            "locked",
        )

    def test_core_deck_report_aggregates_notes(self) -> None:
        notes = [
            _note(note_id=1, cards=(_card(card_id=1, note_id=1, ivl=0, reps=0),)),
            _note(note_id=2, cards=(_card(card_id=2, note_id=2, ivl=2, reps=2),)),
            _note(note_id=3, cards=(_card(card_id=3, note_id=3, ivl=10, reps=5),)),
            _note(note_id=4, cards=(_card(card_id=4, note_id=4, ivl=40, reps=8),)),
            _note(
                note_id=5,
                deck_name=CORE_VOCABULARY_DECK,
                tags=(WK_LOCKED_TAG, "wk-core"),
                cards=(_card(card_id=5, note_id=5, deck_name=CORE_VOCABULARY_DECK, ivl=0, reps=0),),
            ),
        ]
        cards = [card for note in notes for card in note.cards]
        report = build_deck_stats_report(
            cards=cards,
            notes=notes,
            generated_at="2026-07-05 12:00 UTC",
        )
        kanji = next(row for row in report.wk_rows if row.deck_name == CORE_KANJI_DECK)
        self.assertEqual(kanji.unseen_count, 1)
        self.assertEqual(kanji.apprentice_count, 1)
        self.assertEqual(kanji.guru_count, 1)
        self.assertEqual(kanji.master_count, 1)
        self.assertEqual(kanji.total_notes, 4)
        vocab = next(row for row in report.wk_rows if row.deck_name == CORE_VOCABULARY_DECK)
        self.assertEqual(vocab.locked_count, 1)

    def test_standard_deck_uses_card_counts(self) -> None:
        mining = "Immersion · Migaku Mining"
        cards = [
            _card(
                card_id=1,
                note_id=1,
                deck_name=mining,
                card_type=ANKI_CARD_TYPE_NEW,
                ivl=0,
                reps=0,
            ),
            _card(
                card_id=2,
                note_id=2,
                deck_name=mining,
                card_type=ANKI_CARD_TYPE_LEARN,
                ivl=1,
                reps=1,
            ),
            _card(
                card_id=3,
                note_id=3,
                deck_name=mining,
                card_type=ANKI_CARD_TYPE_REVIEW,
                ivl=4,
                reps=3,
            ),
            _card(
                card_id=4,
                note_id=4,
                deck_name=mining,
                queue=ANKI_QUEUE_SUSPENDED,
                ivl=0,
                reps=0,
            ),
        ]
        report = build_deck_stats_report(cards=cards, notes=(), generated_at="t")
        row = report.standard_rows[0]
        self.assertEqual(row.deck_name, mining)
        self.assertEqual(row.new_count, 1)
        self.assertEqual(row.learning_count, 1)
        self.assertEqual(row.review_count, 1)
        self.assertEqual(row.suspended_count, 1)
        self.assertEqual(row.total_cards, 4)

    def test_sort_deck_names_core_first(self) -> None:
        names = sort_deck_names(
            ["Immersion · Migaku Mining", CORE_KANJI_DECK, "Japanese Grammar Context"]
        )
        self.assertEqual(names[0], CORE_KANJI_DECK)
        self.assertIn("Japanese Grammar Context", names)

    def test_format_report_includes_sections(self) -> None:
        report = build_deck_stats_report(
            cards=[_card()],
            notes=[_note()],
            generated_at="2026-07-05 12:00 UTC",
        )
        text = format_deck_stats_report(report)
        self.assertIn("WaniKani core", text)
        self.assertIn("Unseen", text)
        self.assertIn(CORE_KANJI_DECK, text)
        self.assertIn("Core total", text)

    def test_wk_level_to_jlpt_thresholds(self) -> None:
        self.assertEqual(wk_level_to_jlpt(3), "N5")
        self.assertEqual(wk_level_to_jlpt(15), "N4")
        self.assertEqual(wk_level_to_jlpt(50), "N1")

    def test_vocab_locked_by_kanji_prereq_requires_unmet_kanji(self) -> None:
        mature_kanji = _note(
            note_id=20,
            wk_subject_id=100,
            cards=(_card(card_id=20, note_id=20, ivl=10, reps=4),),
        )
        mature_ids = build_mature_subject_ids([mature_kanji])
        locked_vocab = _note(
            note_id=30,
            deck_name=CORE_VOCABULARY_DECK,
            tags=(WK_LOCKED_TAG, "wk-core", "vocabulary", "wk-level-3"),
            wk_subject_id=200,
            prerequisite_ids=(999,),
            wk_level=3,
            is_kanji=False,
            is_vocabulary=True,
            cards=(
                _card(
                    card_id=30,
                    note_id=30,
                    deck_name=CORE_VOCABULARY_DECK,
                    queue=ANKI_QUEUE_SUSPENDED,
                    ivl=0,
                    reps=0,
                ),
            ),
        )
        self.assertTrue(
            is_vocab_locked_by_kanji_prereq(locked_vocab, mature_subject_ids=mature_ids)
        )

        locked_vocab_met = _note(
            note_id=31,
            deck_name=CORE_VOCABULARY_DECK,
            tags=(WK_LOCKED_TAG, "wk-core", "vocabulary", "wk-level-3"),
            wk_subject_id=201,
            prerequisite_ids=(100,),
            wk_level=3,
            is_kanji=False,
            is_vocabulary=True,
            cards=(
                _card(
                    card_id=31,
                    note_id=31,
                    deck_name=CORE_VOCABULARY_DECK,
                    queue=ANKI_QUEUE_SUSPENDED,
                    ivl=0,
                    reps=0,
                ),
            ),
        )
        self.assertFalse(
            is_vocab_locked_by_kanji_prereq(
                locked_vocab_met,
                mature_subject_ids=mature_ids,
            )
        )

        locked_no_prereq = _note(
            note_id=32,
            deck_name=CORE_VOCABULARY_DECK,
            tags=(WK_LOCKED_TAG, "wk-core", "vocabulary", "wk-level-3"),
            wk_subject_id=202,
            prerequisite_ids=(),
            wk_level=3,
            is_kanji=False,
            is_vocabulary=True,
            cards=(
                _card(
                    card_id=32,
                    note_id=32,
                    deck_name=CORE_VOCABULARY_DECK,
                    queue=ANKI_QUEUE_SUSPENDED,
                    ivl=0,
                    reps=0,
                ),
            ),
        )
        self.assertFalse(
            is_vocab_locked_by_kanji_prereq(locked_no_prereq, mature_subject_ids=set())
        )

    def test_vocab_locked_by_wk_level_groups_counts(self) -> None:
        mature_kanji = _note(note_id=20, wk_subject_id=100, cards=(_card(card_id=20, note_id=20, ivl=10, reps=4),))
        mature_ids = build_mature_subject_ids([mature_kanji])
        notes = [
            _note(
                note_id=30,
                deck_name=CORE_VOCABULARY_DECK,
                tags=(WK_LOCKED_TAG, "wk-core", "vocabulary", "wk-level-3"),
                wk_subject_id=200,
                prerequisite_ids=(999,),
                wk_level=3,
                is_vocabulary=True,
                is_kanji=False,
                cards=(
                    _card(
                        card_id=30,
                        note_id=30,
                        deck_name=CORE_VOCABULARY_DECK,
                        queue=ANKI_QUEUE_SUSPENDED,
                        ivl=0,
                        reps=0,
                    ),
                ),
            ),
            _note(
                note_id=31,
                deck_name=CORE_VOCABULARY_DECK,
                tags=(WK_LOCKED_TAG, "wk-core", "vocabulary", "wk-level-5"),
                wk_subject_id=201,
                prerequisite_ids=(999,),
                wk_level=5,
                is_vocabulary=True,
                is_kanji=False,
                cards=(
                    _card(
                        card_id=31,
                        note_id=31,
                        deck_name=CORE_VOCABULARY_DECK,
                        queue=ANKI_QUEUE_SUSPENDED,
                        ivl=0,
                        reps=0,
                    ),
                ),
            ),
            _note(
                note_id=32,
                deck_name=CORE_VOCABULARY_DECK,
                tags=(WK_LOCKED_TAG, "wk-core", "vocabulary", "wk-level-5"),
                wk_subject_id=202,
                prerequisite_ids=(999,),
                wk_level=5,
                is_vocabulary=True,
                is_kanji=False,
                cards=(
                    _card(
                        card_id=32,
                        note_id=32,
                        deck_name=CORE_VOCABULARY_DECK,
                        queue=ANKI_QUEUE_SUSPENDED,
                        ivl=0,
                        reps=0,
                    ),
                ),
            ),
        ]
        rows = build_vocab_locked_by_wk_level(notes, mature_subject_ids=mature_ids)
        self.assertEqual(rows, (
            logic.VocabLockedByLevelRow(wk_level=3, locked_count=1),
            logic.VocabLockedByLevelRow(wk_level=5, locked_count=2),
        ))

    def test_jlpt_bucket_rows_for_kanji_and_vocab(self) -> None:
        notes = [
            _note(
                note_id=1,
                wk_level=3,
                tags=("wk-core", "kanji", "wk-level-3"),
                cards=(_card(card_id=1, note_id=1, ivl=0, reps=0),),
            ),
            _note(
                note_id=2,
                wk_level=3,
                tags=(WK_LOCKED_TAG, "wk-core", "kanji", "wk-level-3"),
                cards=(_card(card_id=2, note_id=2, queue=ANKI_QUEUE_SUSPENDED, ivl=0, reps=0),),
            ),
            _note(
                note_id=3,
                deck_name=CORE_VOCABULARY_DECK,
                wk_level=15,
                tags=("wk-core", "vocabulary", "wk-level-15"),
                is_kanji=False,
                is_vocabulary=True,
                cards=(_card(card_id=3, note_id=3, deck_name=CORE_VOCABULARY_DECK, ivl=10, reps=3),),
            ),
        ]
        kanji_rows = build_jlpt_bucket_rows(notes, subject_kind="kanji")
        self.assertEqual(len(kanji_rows), 1)
        self.assertEqual(kanji_rows[0].jlpt, "N5")
        self.assertEqual(kanji_rows[0].unseen_count, 1)
        self.assertEqual(kanji_rows[0].locked_count, 1)
        self.assertEqual(kanji_rows[0].total_notes, 2)

        vocab_rows = build_jlpt_bucket_rows(notes, subject_kind="vocabulary")
        self.assertEqual(len(vocab_rows), 1)
        self.assertEqual(vocab_rows[0].jlpt, "N4")
        self.assertEqual(vocab_rows[0].guru_count, 1)

    def test_report_includes_enhanced_stats(self) -> None:
        mature_kanji = _note(note_id=20, wk_subject_id=100, cards=(_card(card_id=20, note_id=20, ivl=10, reps=4),))
        locked_vocab = _note(
            note_id=30,
            deck_name=CORE_VOCABULARY_DECK,
            tags=(WK_LOCKED_TAG, "wk-core", "vocabulary", "wk-level-3"),
            wk_subject_id=200,
            prerequisite_ids=(999,),
            wk_level=3,
            is_vocabulary=True,
            is_kanji=False,
            cards=(
                _card(
                    card_id=30,
                    note_id=30,
                    deck_name=CORE_VOCABULARY_DECK,
                    queue=ANKI_QUEUE_SUSPENDED,
                    ivl=0,
                    reps=0,
                ),
            ),
        )
        notes = [mature_kanji, locked_vocab]
        cards = [card for note in notes for card in note.cards]
        report = build_deck_stats_report(cards=cards, notes=notes, generated_at="t")
        self.assertEqual(len(report.vocab_locked_by_wk_level), 1)
        self.assertEqual(report.vocab_locked_by_wk_level[0].wk_level, 3)
        self.assertEqual(report.jlpt_kanji_rows[0].jlpt, "N5")
        self.assertEqual(report.jlpt_vocab_rows[0].locked_count, 1)
        text = format_deck_stats_report(report)
        self.assertIn("Vocabulary locked by unmet kanji prerequisites", text)
        self.assertIn("JLPT breakdown", text)


if __name__ == "__main__":
    unittest.main()
