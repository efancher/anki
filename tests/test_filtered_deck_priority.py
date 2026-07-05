"""Regression tests for N5 filtered-deck priority tagging."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from typing import Iterable, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import FILTERED_DECK_DEFINITIONS
from wk_study_priority import (
    JLPT_N5_PREREQ_TAG,
    JLPT_N5_VOCAB_TAG,
    build_core_priority_index,
    priority_tags,
)

FIXTURES_PATH = REPO_ROOT / "filtered_deck_priority_fixtures.json"

PRIORITY_FILTERED_DECK_NAMES = frozenset(
    {
        "WK::N5 · Kanji",
        "WK::N5 · Vocabulary",
        "WK::N5 · Prereq Kanji",
        "WK::N5 · Prereq Radicals",
    }
)

_TAG_REQUIRED_RE = re.compile(r"(?<!\-)(?:^|\s)tag:(\S+)")
_TAG_EXCLUDED_RE = re.compile(r"-tag:(\S+)")


def load_fixtures() -> dict:
    return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


def required_and_excluded_tags(search: str) -> Tuple[Set[str], Set[str]]:
    required = set(_TAG_REQUIRED_RE.findall(search))
    excluded = set(_TAG_EXCLUDED_RE.findall(search))
    return required, excluded


def matches_tag_search(note_tags: Iterable[str], search: str) -> bool:
    tags = set(note_tags)
    required, excluded = required_and_excluded_tags(search)
    if not required.issubset(tags):
        return False
    return not (tags & excluded)


def filtered_deck_by_name(name: str) -> dict:
    for deck in FILTERED_DECK_DEFINITIONS:
        if deck["name"] == name:
            return deck
    raise KeyError(name)


class FilteredDeckPriorityTests(unittest.TestCase):
    def test_n5_filtered_decks_exist(self) -> None:
        names = {deck["name"] for deck in FILTERED_DECK_DEFINITIONS}
        for name in PRIORITY_FILTERED_DECK_NAMES:
            self.assertIn(name, names)

    def test_n5_kanji_deck_requires_vocab_and_kanji_tags(self) -> None:
        search = filtered_deck_by_name("WK::N5 · Kanji")["search"]
        required, _ = required_and_excluded_tags(search)
        self.assertIn("jlpt-n5-vocab", required)
        self.assertIn("kanji", required)

    def test_n5_prereq_tags_from_priority_index(self) -> None:
        radical = {
            "id": 200,
            "object": "radical",
            "data": {"characters": "一", "level": 1},
        }
        kanji = {
            "id": 20,
            "object": "kanji",
            "data": {"characters": "一", "level": 5, "component_subject_ids": [200]},
        }
        index = build_core_priority_index([radical], [kanji], [])
        self.assertIn(JLPT_N5_VOCAB_TAG, priority_tags(index[20], subject_object="kanji"))
        self.assertIn(JLPT_N5_PREREQ_TAG, priority_tags(index[200], subject_object="radical"))

    def test_fixture_cases_match_n5_decks_only(self) -> None:
        fixtures = load_fixtures()
        for case in fixtures.get("cases") or []:
            if case.get("exclude_from_decks"):
                continue
            note_tags = list(case.get("note_tags") or [])
            for deck_name in case.get("include_in_decks") or []:
                if deck_name not in PRIORITY_FILTERED_DECK_NAMES:
                    continue
                search = filtered_deck_by_name(deck_name)["search"]
                self.assertTrue(
                    matches_tag_search(note_tags, search),
                    msg=f"{case.get('name')} should match {deck_name}",
                )


if __name__ == "__main__":
    unittest.main()
