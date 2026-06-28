"""Tests for wk_scheduling.py — WK assignment → Anki scheduling bootstrap."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_scheduling import (
    ANKI_CARD_TYPE_REVIEW,
    ANKI_QUEUE_REVIEW,
    ANKI_QUEUE_SUSPENDED,
    WK_LOCKED_TAG,
    WK_SCHEDULE_BOOTSTRAPPED_TAG,
    WK_SRS_STAGE_INTERVAL_DAYS,
    available_at_to_due_day,
    core_note_suspended,
    schedule_spec_for_assignment,
    srs_stage_interval_days,
)


class WkSchedulingTests(unittest.TestCase):
    def test_srs_stage_interval_days_mapping(self) -> None:
        self.assertEqual(srs_stage_interval_days(1), 0)
        self.assertEqual(srs_stage_interval_days(2), 1)
        self.assertEqual(srs_stage_interval_days(5), 7)
        self.assertEqual(srs_stage_interval_days(9), 365)
        self.assertEqual(WK_SRS_STAGE_INTERVAL_DAYS[7], 30)

    def test_core_note_suspended_when_unstarted(self) -> None:
        assignment = {
            "data": {
                "unlocked_at": "2020-01-01T00:00:00Z",
                "started_at": None,
                "srs_stage": 1,
            }
        }
        self.assertTrue(core_note_suspended(assignment))
        self.assertFalse(core_note_suspended(assignment, suspend_unstarted=False))

    def test_core_note_suspended_when_locked(self) -> None:
        assignment = {
            "data": {
                "unlocked_at": None,
                "started_at": "2020-01-01T00:00:00Z",
                "srs_stage": 1,
            }
        }
        self.assertTrue(core_note_suspended(assignment))

    def test_schedule_spec_for_started_assignment(self) -> None:
        assignment = {
            "data": {
                "unlocked_at": "2020-01-01T00:00:00Z",
                "started_at": "2020-01-02T00:00:00Z",
                "srs_stage": 5,
                "available_at": "2020-01-10T00:00:00Z",
            }
        }
        spec = schedule_spec_for_assignment("abc", assignment)
        self.assertFalse(spec.suspended)
        self.assertEqual(spec.srs_stage, 5)
        self.assertEqual(spec.available_at, "2020-01-10T00:00:00Z")

    def test_bootstrap_sets_due_from_available_at(self) -> None:
        crt = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
        due = available_at_to_due_day("2020-01-10T00:00:00Z", crt)
        self.assertEqual(due, 9)

    def test_schedule_spec_suspended_adds_locked_state(self) -> None:
        spec = schedule_spec_for_assignment("abc", None)
        self.assertTrue(spec.suspended)
        self.assertEqual(spec.srs_stage, 0)

    def test_review_card_constants(self) -> None:
        self.assertEqual(ANKI_CARD_TYPE_REVIEW, 2)
        self.assertEqual(ANKI_QUEUE_REVIEW, 2)
        self.assertEqual(ANKI_QUEUE_SUSPENDED, -1)

    def test_bootstrap_tag_constants(self) -> None:
        self.assertEqual(WK_SCHEDULE_BOOTSTRAPPED_TAG, "wk-schedule-bootstrapped")
        self.assertEqual(WK_LOCKED_TAG, "wk-locked")


if __name__ == "__main__":
    unittest.main()
