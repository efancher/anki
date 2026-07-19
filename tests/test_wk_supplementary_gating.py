"""Tests for supplementary deck import-time gating (Phase 2)."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import (
    FILTERED_DECK_DEFINITIONS,
    WK_SRS_STAGE_GURU_1,
    all_vocab_subjects,
    passes_progress_filter,
    supplementary_import_tags,
    vocab_supplementary_import_tags,
    vocab_kanji_prerequisite_ids,
    supplementary_min_srs,
)
from wk_scheduling import (
    DEFAULT_SUPPLEMENTARY_MATURE_MIN_INTERVAL_DAYS,
    DEFAULT_SUPPLEMENTARY_MATURE_MIN_SRS_STAGE,
    load_srs_stage_interval_days,
    parse_spaced_repetition_system_stages,
    wk_subject_mature_at_import,
)


def mock_vocab(vocab_id: int, *, level: int = 5, component_ids: list | None = None) -> dict:
    return {
        "id": vocab_id,
        "object": "vocabulary",
        "data": {
            "characters": "本",
            "level": level,
            "component_subject_ids": component_ids if component_ids is not None else [10, 11],
        },
    }


class WkSupplementaryGatingTests(unittest.TestCase):
    def test_wk_subject_mature_at_import_by_stage(self) -> None:
        self.assertTrue(
            wk_subject_mature_at_import(
                WK_SRS_STAGE_GURU_1,
                min_srs_stage=DEFAULT_SUPPLEMENTARY_MATURE_MIN_SRS_STAGE,
            )
        )
        self.assertFalse(
            wk_subject_mature_at_import(
                WK_SRS_STAGE_GURU_1 - 1,
                min_srs_stage=DEFAULT_SUPPLEMENTARY_MATURE_MIN_SRS_STAGE,
                interval_map={4: 6},
                mature_interval_days=DEFAULT_SUPPLEMENTARY_MATURE_MIN_INTERVAL_DAYS,
            )
        )

    def test_wk_subject_mature_at_import_by_interval(self) -> None:
        self.assertTrue(
            wk_subject_mature_at_import(
                WK_SRS_STAGE_GURU_1,
                interval_map={5: DEFAULT_SUPPLEMENTARY_MATURE_MIN_INTERVAL_DAYS},
                mature_interval_days=DEFAULT_SUPPLEMENTARY_MATURE_MIN_INTERVAL_DAYS,
            )
        )

    def test_supplementary_import_tags_adds_locked_when_not_mature(self) -> None:
        vocab = mock_vocab(42)
        assignment_index = {42: {"data": {"subject_id": 42, "srs_stage": 1}}}
        tags = supplementary_import_tags(vocab, assignment_index)
        self.assertIn("wk-locked", tags)

    def test_vocab_supplementary_import_tags_locks_when_kanji_prereqs(self) -> None:
        vocab = mock_vocab(42, component_ids=[10, 11])
        self.assertEqual(vocab_kanji_prerequisite_ids(vocab), "10,11")
        self.assertIn("wk-locked", vocab_supplementary_import_tags(vocab))

    def test_vocab_supplementary_import_tags_unlocked_for_kana_only_vocab(self) -> None:
        vocab = mock_vocab(42, component_ids=[])
        self.assertEqual(vocab_supplementary_import_tags(vocab), [])

    def test_supplementary_import_tags_omits_locked_when_mature(self) -> None:
        vocab = mock_vocab(42)
        assignment_index = {42: {"data": {"subject_id": 42, "srs_stage": WK_SRS_STAGE_GURU_1}}}
        tags = supplementary_import_tags(vocab, assignment_index)
        self.assertNotIn("wk-locked", tags)

    def test_passes_progress_filter_skips_started_when_no_wk_progress_filter(self) -> None:
        args = argparse.Namespace(
            max_level=60,
            only_unlocked=False,
            only_started=True,
            only_burned=False,
            min_srs=7,
            no_wk_progress_filter=True,
        )
        subject = mock_vocab(1)
        self.assertTrue(passes_progress_filter(subject, {}, args))

    def test_supplementary_min_srs_zero_when_no_filter(self) -> None:
        args = argparse.Namespace(no_wk_progress_filter=True)
        self.assertEqual(supplementary_min_srs(args, 7), 0)
        args.no_wk_progress_filter = False
        self.assertEqual(supplementary_min_srs(args, 7), 7)

    def test_all_vocab_subjects_respects_max_level(self) -> None:
        args = argparse.Namespace(max_level=5)
        subjects = [mock_vocab(1, level=4), mock_vocab(2, level=6)]
        self.assertEqual(len(all_vocab_subjects(subjects, args)), 1)

    def test_load_srs_stage_interval_days_from_cache(self) -> None:
        system = {
            "object": "spaced_repetition_system",
            "data": {
                "burning_stage_position": 9,
                "stages": [
                    {"position": 0, "interval": None, "interval_unit": None},
                    {"position": 5, "interval": 601200, "interval_unit": "seconds"},
                    {"position": 7, "interval": 2588400, "interval_unit": "seconds"},
                    {"position": 9, "interval": None, "interval_unit": None},
                ],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "spaced_repetition_systems.json"
            cache_path.write_text(json.dumps({"items": [system]}), encoding="utf-8")
            intervals = load_srs_stage_interval_days(cache_path)
        self.assertEqual(intervals[5], 6)
        self.assertEqual(intervals[7], 29)
        self.assertEqual(intervals[9], 365)

    def test_parse_spaced_repetition_system_stages(self) -> None:
        intervals = parse_spaced_repetition_system_stages(
            {
                "data": {
                    "burning_stage_position": 9,
                    "stages": [{"position": 2, "interval": 86400, "interval_unit": "seconds"}],
                }
            }
        )
        self.assertEqual(intervals[2], 1)

    def test_filtered_decks_are_retired(self) -> None:
        self.assertEqual(FILTERED_DECK_DEFINITIONS, [])

if __name__ == "__main__":
    unittest.main()
