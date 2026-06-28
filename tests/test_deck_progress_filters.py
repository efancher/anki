"""Tests for per-deck SRS floors and radical preview level selection."""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import (
    PHONETIC_FAMILIES_MIN_SRS,
    WK_SRS_STAGE_APPRENTICE_1,
    WK_SRS_STAGE_GURU_1,
    WK_SRS_STAGE_MASTER,
    RadicalPreviewLevels,
    kanji_subjects,
    radical_level_status,
    selected_radical_levels,
)


def mock_kanji(vocab_id: int, *, srs_stage: int, level: int = 5) -> dict:
    return {
        "id": vocab_id,
        "object": "kanji",
        "data": {
            "characters": "本",
            "level": level,
            "readings": [{"reading": "ほん", "primary": True}],
        },
        "_assignment": {"data": {"srs_stage": srs_stage, "started_at": "2020-01-01T00:00:00Z"}},
    }


class DeckProgressFilterTests(unittest.TestCase):
    def test_phonetic_families_min_srs_is_apprentice(self) -> None:
        self.assertEqual(PHONETIC_FAMILIES_MIN_SRS, WK_SRS_STAGE_APPRENTICE_1)

    def test_kanji_subjects_can_override_min_srs(self) -> None:
        subjects = [mock_kanji(1, srs_stage=WK_SRS_STAGE_GURU_1)]
        assignment_index = {1: subjects[0]["_assignment"]}
        args = argparse.Namespace(
            max_level=60,
            only_unlocked=False,
            only_started=True,
            only_burned=False,
            min_srs=WK_SRS_STAGE_MASTER,
        )
        self.assertEqual(kanji_subjects(subjects, assignment_index, args), [])
        self.assertEqual(
            kanji_subjects(subjects, assignment_index, args, min_srs=PHONETIC_FAMILIES_MIN_SRS),
            subjects,
        )

    def test_selected_radical_levels_includes_locked_next(self) -> None:
        args = argparse.Namespace(radical_current_level=12)
        user = {"level": 99}
        levels = selected_radical_levels(user, [], {}, args)
        self.assertEqual(levels, RadicalPreviewLevels(12, 13, 14))
        self.assertEqual(levels.level_set(), set(range(1, 13)) | {13, 14})

    def test_radical_level_status_labels_locked_next(self) -> None:
        levels = RadicalPreviewLevels(10, 11, 12)
        self.assertEqual(radical_level_status(10, levels), "current-level")
        self.assertEqual(radical_level_status(11, levels), "next-level")
        self.assertEqual(radical_level_status(12, levels), "locked-next-level")
        self.assertEqual(radical_level_status(5, levels), "previous-level")


if __name__ == "__main__":
    unittest.main()
