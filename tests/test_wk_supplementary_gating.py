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
    CORE_FILTERED_DECK_CARD_LIMIT,
    FILTERED_DECK_DEFINITIONS,
    FILTERED_DECK_SEARCH_DUE_OR_NEW,
    FILTERED_DECK_SEARCH_NOT_MATURE,
    WK_SRS_STAGE_GURU_1,
    all_vocab_subjects,
    daily_filtered_deck_search,
    effective_filtered_deck_definitions,
    prereq_filtered_deck_search,
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

    def test_filtered_deck_searches_scope_daily_workload(self) -> None:
        prereq_names = {
            "WK::N5 · Prereq Radicals",
        }
        for spec in FILTERED_DECK_DEFINITIONS:
            self.assertIn(
                FILTERED_DECK_SEARCH_DUE_OR_NEW,
                spec["search"],
                msg=f"Missing due/new scope in {spec['name']}",
            )
            self.assertIn(
                "-is:suspended",
                spec["search"],
                msg=f"Missing -is:suspended in {spec['name']}",
            )
            if spec["name"] in prereq_names:
                self.assertIn(
                    FILTERED_DECK_SEARCH_NOT_MATURE,
                    spec["search"],
                    msg=f"Missing wk-mature exclusion in {spec['name']}",
                )
            else:
                self.assertNotIn(
                    FILTERED_DECK_SEARCH_NOT_MATURE,
                    spec["search"],
                    msg=f"Unexpected wk-mature exclusion in {spec['name']}",
                )
        for spec in effective_filtered_deck_definitions():
            self.assertIn(FILTERED_DECK_SEARCH_DUE_OR_NEW, spec["search"])

    def test_prereq_filtered_deck_search_helper(self) -> None:
        search = prereq_filtered_deck_search("tag:wk-core tag:jlpt-n5-prereq tag:kanji")
        self.assertIn(FILTERED_DECK_SEARCH_DUE_OR_NEW, search)
        self.assertIn(FILTERED_DECK_SEARCH_NOT_MATURE, search)
        self.assertIn("-is:suspended", search)

    def test_daily_filtered_deck_search_helper(self) -> None:
        search = daily_filtered_deck_search('deck:"WaniKani Core · Kanji"')
        self.assertIn(FILTERED_DECK_SEARCH_DUE_OR_NEW, search)
        self.assertNotIn(FILTERED_DECK_SEARCH_NOT_MATURE, search)

    def test_conjugation_filtered_decks_use_batch_limit(self) -> None:
        conjugation_names = {
            "WK::Conjugations · Verbs",
            "WK::Conjugations · Adjectives",
            "WK::Conjugations · Reverse",
            "WK::Conjugations · Verb Types",
            "WK::Conjugations · Adjective Types",
        }
        by_name = {spec["name"]: spec for spec in FILTERED_DECK_DEFINITIONS}
        for name in conjugation_names:
            self.assertIn(name, by_name)
            self.assertEqual(by_name[name]["limit"], CORE_FILTERED_DECK_CARD_LIMIT)
            self.assertIn(
                FILTERED_DECK_SEARCH_DUE_OR_NEW,
                by_name[name]["search"],
            )

    def test_core_dual_review_filtered_decks_retired(self) -> None:
        by_name = {spec["name"]: spec for spec in FILTERED_DECK_DEFINITIONS}
        self.assertNotIn("WK::Core Kanji", by_name)
        self.assertNotIn("WK::Core Vocabulary", by_name)
        self.assertNotIn("WK::N5 · Kanji", by_name)
        self.assertNotIn("WK::N5 · Vocabulary", by_name)
        self.assertIn("WK::Kanji Meaning", by_name)
        self.assertIn("WK::Immersion · Satori", by_name)
        self.assertNotIn("WK::Vocab Context", by_name)
        self.assertNotIn("WK::Vocab Sentence Meaning", by_name)
        self.assertNotIn("WK::Vocab Sentence Reading", by_name)
        self.assertNotIn("WK::Dictation", by_name)
        self.assertIn('deck:"Immersion · Satori"', by_name["WK::Immersion · Satori"]["search"])


if __name__ == "__main__":
    unittest.main()
