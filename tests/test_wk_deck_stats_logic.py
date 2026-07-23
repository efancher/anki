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
CORE_VOCABULARY_DECK = logic.CORE_VOCABULARY_DECK
CardRow = logic.CardRow
NoteRow = logic.NoteRow
WK_LOCKED_TAG = logic.WK_LOCKED_TAG
build_deck_stats_report = logic.build_deck_stats_report
build_immersion_core_progress = logic.build_immersion_core_progress
classify_immersion_core_note = logic.classify_immersion_core_note
classify_wk_note = logic.classify_wk_note
collect_immersion_subject_ids = logic.collect_immersion_subject_ids
format_deck_stats_report = logic.format_deck_stats_report
sort_deck_names = logic.sort_deck_names


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


def _new_card(**kwargs) -> CardRow:
    defaults = {
        "card_type": ANKI_CARD_TYPE_NEW,
        "queue": 0,
        "ivl": 0,
        "reps": 0,
    }
    defaults.update(kwargs)
    return _card(**defaults)


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
            classify_wk_note(_note(cards=(_new_card(),))),
            "new",
        )
        self.assertEqual(
            classify_wk_note(_note(cards=(_card(card_type=ANKI_CARD_TYPE_LEARN, queue=1, ivl=0, reps=1),))),
            "reviewed",
        )
        self.assertEqual(
            classify_wk_note(_note(cards=(_card(ivl=2, reps=3),))),
            "reviewed",
        )
        # WK-seeded review with reps=0 counts as reviewed (not new).
        self.assertEqual(
            classify_wk_note(_note(cards=(_card(ivl=119, reps=0),))),
            "reviewed",
        )
        self.assertEqual(
            classify_wk_note(_note(tags=(WK_LOCKED_TAG,), cards=(_new_card(),))),
            "locked",
        )
        self.assertEqual(
            classify_wk_note(
                _note(cards=(_card(queue=ANKI_QUEUE_SUSPENDED, ivl=30, reps=4),))
            ),
            "locked",
        )

    def test_classify_immersion_core_note_buckets(self) -> None:
        self.assertEqual(
            classify_immersion_core_note(_note(cards=(_new_card(),))),
            "new",
        )
        self.assertEqual(
            classify_immersion_core_note(_note(cards=(_card(ivl=2, reps=3),))),
            "reviewed",
        )
        self.assertEqual(
            classify_immersion_core_note(
                _note(tags=(WK_LOCKED_TAG,), cards=(_new_card(),))
            ),
            "locked",
        )

    def test_core_deck_report_aggregates_notes(self) -> None:
        notes = [
            _note(note_id=1, cards=(_new_card(card_id=1, note_id=1),)),
            _note(note_id=2, cards=(_card(card_id=2, note_id=2, ivl=2, reps=2),)),
            _note(note_id=3, cards=(_card(card_id=3, note_id=3, ivl=10, reps=5),)),
            _note(
                note_id=4,
                deck_name=CORE_VOCABULARY_DECK,
                tags=(WK_LOCKED_TAG, "wk-core"),
                cards=(
                    _new_card(card_id=4, note_id=4, deck_name=CORE_VOCABULARY_DECK),
                ),
            ),
        ]
        cards = [card for note in notes for card in note.cards]
        report = build_deck_stats_report(
            cards=cards,
            notes=notes,
            generated_at="2026-07-05 12:00 UTC",
        )
        kanji = next(row for row in report.wk_rows if row.deck_name == CORE_KANJI_DECK)
        self.assertEqual(kanji.new_count, 1)
        self.assertEqual(kanji.reviewed_count, 2)
        self.assertEqual(kanji.locked_count, 0)
        self.assertEqual(kanji.total_notes, 3)
        vocab = next(row for row in report.wk_rows if row.deck_name == CORE_VOCABULARY_DECK)
        self.assertEqual(vocab.locked_count, 1)

    def test_standard_deck_uses_card_counts(self) -> None:
        mining = "Immersion · Yomitan Mining"
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
            ["Immersion · Yomitan Mining", CORE_KANJI_DECK, "Japanese Grammar Context"]
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
        self.assertIn("New", text)
        self.assertIn("Reviewed", text)
        self.assertNotIn("Appr", text)
        self.assertNotIn("Guru", text)
        self.assertIn(CORE_KANJI_DECK, text)
        self.assertIn("Core total", text)

    def test_collect_immersion_subject_ids(self) -> None:
        immersion_notes = [
            NoteRow(
                note_id=1,
                deck_name="Immersion · Satori",
                tags=("satori-mining",),
                cards=(),
                wk_subject_id=200,
                prerequisite_ids=(10, 11),
            ),
            NoteRow(
                note_id=2,
                deck_name="Immersion · Shadowing",
                tags=("shadowing-mining",),
                cards=(),
                wk_subject_id=201,
                prerequisite_ids=(11,),
            ),
        ]
        self.assertEqual(collect_immersion_subject_ids(immersion_notes), {200, 201, 10, 11})

    def test_immersion_core_progress_filters_linked_subjects(self) -> None:
        notes = [
            _note(
                note_id=1,
                wk_subject_id=10,
                cards=(_new_card(card_id=1, note_id=1),),
            ),
            _note(
                note_id=2,
                wk_subject_id=11,
                tags=(WK_LOCKED_TAG, "wk-core", "kanji"),
                cards=(
                    _new_card(
                        card_id=2,
                        note_id=2,
                        queue=ANKI_QUEUE_SUSPENDED,
                    ),
                ),
            ),
            _note(
                note_id=3,
                wk_subject_id=99,
                cards=(_card(card_id=3, note_id=3, ivl=10, reps=4),),
            ),
            _note(
                note_id=4,
                deck_name=CORE_VOCABULARY_DECK,
                wk_subject_id=200,
                tags=("wk-core", "vocabulary"),
                is_kanji=False,
                is_vocabulary=True,
                cards=(
                    _card(
                        card_id=4,
                        note_id=4,
                        deck_name=CORE_VOCABULARY_DECK,
                        ivl=5,
                        reps=2,
                    ),
                ),
            ),
            _note(
                note_id=5,
                deck_name=CORE_VOCABULARY_DECK,
                wk_subject_id=201,
                tags=("wk-core", "vocabulary"),
                is_kanji=False,
                is_vocabulary=True,
                cards=(
                    _new_card(
                        card_id=5,
                        note_id=5,
                        deck_name=CORE_VOCABULARY_DECK,
                    ),
                ),
            ),
        ]
        immersion_ids = {10, 11, 200}
        kanji = build_immersion_core_progress(
            notes,
            immersion_subject_ids=immersion_ids,
            subject_kind="kanji",
        )
        assert kanji is not None
        self.assertEqual(kanji.new_count, 1)
        self.assertEqual(kanji.locked_count, 1)
        self.assertEqual(kanji.reviewed_count, 0)
        self.assertEqual(kanji.total_notes, 2)

        vocab = build_immersion_core_progress(
            notes,
            immersion_subject_ids=immersion_ids,
            subject_kind="vocabulary",
        )
        assert vocab is not None
        self.assertEqual(vocab.reviewed_count, 1)
        self.assertEqual(vocab.new_count, 0)
        self.assertEqual(vocab.total_notes, 1)

    def test_report_includes_immersion_core_progress(self) -> None:
        notes = [
            _note(
                note_id=1,
                wk_subject_id=10,
                cards=(_new_card(card_id=1, note_id=1),),
            ),
            _note(
                note_id=2,
                deck_name=CORE_VOCABULARY_DECK,
                wk_subject_id=200,
                tags=("wk-core", "vocabulary"),
                is_kanji=False,
                is_vocabulary=True,
                cards=(
                    _card(
                        card_id=2,
                        note_id=2,
                        deck_name=CORE_VOCABULARY_DECK,
                        ivl=8,
                        reps=3,
                    ),
                ),
            ),
        ]
        cards = [card for note in notes for card in note.cards]
        report = build_deck_stats_report(
            cards=cards,
            notes=notes,
            immersion_subject_ids={10, 200},
            generated_at="t",
        )
        assert report.immersion_kanji is not None
        assert report.immersion_vocab is not None
        self.assertEqual(report.immersion_kanji.new_count, 1)
        self.assertEqual(report.immersion_vocab.reviewed_count, 1)
        text = format_deck_stats_report(report)
        self.assertIn("WK Core Kanji (in Satori or Shadowing)", text)
        self.assertIn("WK Core Vocabulary (in Satori or Shadowing)", text)
        self.assertNotIn("JLPT breakdown", text)
        self.assertNotIn("Vocabulary locked by unmet kanji prerequisites", text)


if __name__ == "__main__":
    unittest.main()
