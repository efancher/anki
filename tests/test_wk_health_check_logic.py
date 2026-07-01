"""Tests for wk_health_check pure logic."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGIC_PATH = REPO_ROOT / "anki_addon" / "wk_health_check" / "logic.py"


def _load_logic_module():
    spec = importlib.util.spec_from_file_location("wk_health_check_logic", LOGIC_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wk_health_check_logic"] = module
    spec.loader.exec_module(module)
    return module


logic = _load_logic_module()
ANKI_CARD_TYPE_NEW = logic.ANKI_CARD_TYPE_NEW
ANKI_CARD_TYPE_REVIEW = logic.ANKI_CARD_TYPE_REVIEW
ANKI_QUEUE_SUSPENDED = logic.ANKI_QUEUE_SUSPENDED
CORE_KANJI_DECK = logic.CORE_KANJI_DECK
CardSnapshot = logic.CardSnapshot
NoteSnapshot = logic.NoteSnapshot
build_collection_metrics = logic.build_collection_metrics
build_health_report = logic.build_health_report
compare_metric_snapshots = logic.compare_metric_snapshots
count_core_cards_in_filtered_queues = logic.count_core_cards_in_filtered_queues
find_duplicate_wk_subject_ids = logic.find_duplicate_wk_subject_ids
find_suspicious_scheduling_cards = logic.find_suspicious_scheduling_cards
is_core_card = logic.is_core_card
snapshot_payload = logic.snapshot_payload


def _card(**kwargs) -> CardSnapshot:
    defaults = {
        "card_id": 1,
        "note_id": 10,
        "deck_name": CORE_KANJI_DECK,
        "card_type": ANKI_CARD_TYPE_REVIEW,
        "queue": 2,
        "due": 100,
        "ivl": 10,
        "reps": 5,
        "lapses": 0,
    }
    defaults.update(kwargs)
    return CardSnapshot(**defaults)


class WkHealthCheckLogicTests(unittest.TestCase):
    def test_detects_suspicious_new_with_reps(self) -> None:
        cards = [_card(card_type=ANKI_CARD_TYPE_NEW, reps=3)]
        self.assertEqual(len(find_suspicious_scheduling_cards(cards)), 1)

    def test_healthy_review_card_not_flagged(self) -> None:
        cards = [_card(card_type=ANKI_CARD_TYPE_REVIEW, ivl=12, reps=8)]
        self.assertEqual(find_suspicious_scheduling_cards(cards), [])

    def test_duplicate_wk_subject_ids(self) -> None:
        notes = [
            NoteSnapshot(1, "a", CORE_KANJI_DECK, ("wk-core",), 100),
            NoteSnapshot(2, "b", CORE_KANJI_DECK, ("wk-core",), 100),
        ]
        self.assertEqual(find_duplicate_wk_subject_ids(notes)[100], [1, 2])

    def test_metrics_and_snapshot(self) -> None:
        cards = [
            _card(card_id=1, ivl=10, reps=4),
            _card(card_id=2, card_type=ANKI_CARD_TYPE_NEW, ivl=0, reps=0),
            _card(card_id=3, queue=ANKI_QUEUE_SUSPENDED, ivl=20, reps=9),
        ]
        metrics = build_collection_metrics(cards)
        self.assertEqual(metrics.core_review_cards, 1)
        self.assertEqual(metrics.core_new, 1)
        self.assertEqual(metrics.core_mature, 1)
        self.assertEqual(metrics.core_reps_total, 4)
        payload = snapshot_payload(metrics)
        self.assertIn("core_reps_total", payload["metrics"])

    def test_compare_snapshot_warns_on_rep_drop(self) -> None:
        lines = compare_metric_snapshots(
            {"core_reps_total": 100, "core_review_cards": 50},
            {"core_reps_total": 80, "core_review_cards": 45},
        )
        severities = {line.message.split(":")[0]: line.severity for line in lines}
        self.assertEqual(severities["Core total reps"], "warn")

    def test_build_health_report_warns_when_no_review_history(self) -> None:
        report = build_health_report(
            cards=[_card(reps=0, card_type=ANKI_CARD_TYPE_NEW, ivl=0)],
            notes=[NoteSnapshot(1, "a", CORE_KANJI_DECK, ("wk-core",), 1)],
            deck_presets=[],
            filtered_decks=[],
            study_priority_path=None,
            study_priority_subject_count=0,
            collection_mod=None,
        )
        messages = [line.message for line in report.lines]
        self.assertTrue(any("reps > 0" in message for message in messages))

    def test_core_metrics_use_home_deck_not_filtered_queue(self) -> None:
        home = _card(card_id=1, deck_name=CORE_KANJI_DECK, reps=5, ivl=10)
        in_queue = _card(
            card_id=2,
            deck_name=CORE_KANJI_DECK,
            filtered_queue_deck_name="WK::Core Kanji",
            reps=3,
            ivl=8,
        )
        misclassified = _card(
            card_id=3,
            deck_name="WK::Core Kanji",
            reps=3,
            ivl=8,
        )
        metrics = build_collection_metrics([home, in_queue, misclassified])
        self.assertEqual(metrics.core_reps_total, 8)
        self.assertEqual(metrics.core_review_cards, 2)
        self.assertTrue(is_core_card(in_queue))
        self.assertFalse(is_core_card(misclassified))
        self.assertEqual(count_core_cards_in_filtered_queues([home, in_queue]), 1)

    def test_health_report_notes_filtered_queue_cards(self) -> None:
        cards = [
            _card(
                deck_name=CORE_KANJI_DECK,
                filtered_queue_deck_name="WK::Core Kanji",
            )
        ]
        report = build_health_report(
            cards=cards,
            notes=[NoteSnapshot(1, "a", CORE_KANJI_DECK, ("wk-core",), 1)],
            deck_presets=[],
            filtered_decks=[],
            study_priority_path=None,
            study_priority_subject_count=0,
            collection_mod=None,
        )
        messages = [line.message for line in report.lines]
        self.assertTrue(any("filtered queues" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
