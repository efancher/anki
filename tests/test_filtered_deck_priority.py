"""Regression tests for Tae Kim / N5 filtered-deck priority tagging."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from grammar_decks import GrammarCardItem
from tae_kim_exercise_decks import collect_tae_kim_section_vocabulary_entries
from tae_kim_mapping import TaeKimLesson, TaeKimSection
from wk_decks import FILTERED_DECK_DEFINITIONS
from wk_study_priority import (
    TK_GRAMMAR_PREREQ_TAG,
    TK_GRAMMAR_VOCAB_TAG,
    build_core_priority_index,
    build_tae_kim_subject_orders,
    priority_tags,
)

FIXTURES_PATH = REPO_ROOT / "filtered_deck_priority_fixtures.json"
WK_SUBJECTS_CACHE = REPO_ROOT / ".wk_cache" / "subjects_vocabulary_kanji_radical.json"

PARTICLES_EXERCISE_SNIPPET = """
<h2 id="part2">Basic Particle Exercise with 「は」</h2>
<div id="exercise2">
<table class="large" border="0" cellspacing="8">
<tr><td>２．ジムは大学生だ。でも、私<span class="answerline"><span class="hide">　は　</span></span>大学生じゃない。</td></tr>
<tr><td>４．これはボールペンだ。でも、それ<span class="answerline"><span class="hide">　は　</span></span>ボールペンじゃない。</td></tr>
</table>
</div>
<div id="exercise4">
<table class="large" border="0" cellspacing="8">
<tr><td>アリス） これ<span class="answerline"><span class="hide">　は　</span></span>何？</td></tr>
<tr><td>ボブ） それ<span class="answerline"><span class="hide">　は　</span></span>鉛筆。</td></tr>
<tr><td>アリス） 図書館<span class="answerline"><span class="hide">　は　</span></span>どこ？</td></tr>
</table>
</div>
<div class="botmenu"></div>
"""

PRIORITY_FILTERED_DECK_NAMES = frozenset(
    {
        "WK::Tae Kim · Grammar Vocab",
        "WK::Tae Kim · Grammar Prereq Kanji",
        "WK::Tae Kim · Grammar Prereq Radicals",
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


def priority_filtered_decks() -> List[dict]:
    return [
        deck
        for deck in FILTERED_DECK_DEFINITIONS
        if deck["name"] in PRIORITY_FILTERED_DECK_NAMES
    ]


def _section() -> TaeKimSection:
    return TaeKimSection(num=3, slug="basic-grammar", name="Basic Grammar", guide_url="")


def _lesson(num: int) -> TaeKimLesson:
    return TaeKimLesson(
        chapter_slug="basic",
        chapter_name="Basic Grammar",
        num=num,
        slug=f"lesson-{num}",
        name=f"Lesson {num}",
        has_cards=True,
        section_num=3,
    )


def _stub_kanji(stub: Mapping[str, object]) -> dict:
    return {
        "id": stub["id"],
        "object": "kanji",
        "data": {
            "characters": stub["characters"],
            "level": stub.get("level", 10),
            "component_subject_ids": list(stub.get("component_subject_ids") or []),
        },
    }


def _stub_vocab(stub: Mapping[str, object]) -> dict:
    reading = str(stub.get("reading") or "")
    return {
        "id": stub["id"],
        "object": "vocabulary",
        "data": {
            "characters": stub["characters"],
            "level": stub.get("level", 10),
            "component_subject_ids": list(stub.get("component_subject_ids") or []),
            "readings": [{"reading": reading, "primary": True}] if reading else [],
        },
    }


def _grammar_cards_from_sentences(
    sentences: Sequence[str],
    *,
    lesson_num: int = 3,
    production_answers: Optional[Sequence[str]] = None,
) -> List[GrammarCardItem]:
    cards: List[GrammarCardItem] = []
    for index, sentence in enumerate(sentences):
        production = (
            production_answers[index]
            if production_answers is not None and index < len(production_answers)
            else sentence
        )
        cards.append(
            GrammarCardItem(
                point_id=f"fixture-{index}",
                jlpt="N5",
                order=lesson_num,
                title="fixture",
                short_explanation="",
                formation="",
                cloze_sentence=sentence,
                full_sentence=sentence,
                sentence_en="",
                type_expression=production,
                hint="",
                tae_kim_section=_section(),
                tae_kim_lesson=_lesson(lesson_num),
            )
        )
    return cards


def _grammar_card_from_production_case(case: Mapping[str, object]) -> GrammarCardItem:
    return GrammarCardItem(
        point_id=f"fixture-{case['id']}",
        jlpt="N5",
        order=3,
        title="fixture",
        short_explanation="",
        formation="",
        cloze_sentence=str(case["context_sentence"]),
        full_sentence=str(case["context_sentence"]),
        sentence_en="",
        type_expression=str(case["production_answer"]),
        hint="",
        tae_kim_section=_section(),
        tae_kim_lesson=_lesson(3),
    )


def _core_note_tags(subject: dict, index: Mapping[int, object]) -> Set[str]:
    subject_id = int(subject["id"])
    entry = index[subject_id]
    obj = str(subject.get("object") or "")
    tags = set(priority_tags(entry, subject_object=obj, include_grammar_role_tags=False))
    tags.add("wk-core")
    if obj == "kanji":
        tags.add("kanji")
    elif obj == "radical":
        tags.add("radical")
    elif obj == "vocabulary":
        tags.add("vocabulary")
    return tags


def _matching_priority_decks(note_tags: Set[str]) -> List[str]:
    matched: List[str] = []
    for deck in priority_filtered_decks():
        if matches_tag_search(note_tags, deck["search"]):
            matched.append(deck["name"])
    return matched


def _load_wk_subjects_from_cache() -> Optional[List[dict]]:
    if not WK_SUBJECTS_CACHE.is_file():
        return None
    payload = json.loads(WK_SUBJECTS_CACHE.read_text(encoding="utf-8"))
    return payload.get("items") or []


class FilteredDeckSearchTests(unittest.TestCase):
    def test_priority_decks_use_expected_tags(self) -> None:
        tk_vocab = filtered_deck_by_name("WK::Tae Kim · Grammar Vocab")
        required, _ = required_and_excluded_tags(tk_vocab["search"])
        self.assertIn("wk-core", required)
        self.assertIn(TK_GRAMMAR_VOCAB_TAG, required)

        tk_kanji = filtered_deck_by_name("WK::Tae Kim · Grammar Prereq Kanji")
        required, _ = required_and_excluded_tags(tk_kanji["search"])
        self.assertIn(TK_GRAMMAR_PREREQ_TAG, required)
        self.assertIn("kanji", required)

    def test_tag_search_respects_exclusions(self) -> None:
        tags = {"wk-core", TK_GRAMMAR_VOCAB_TAG, "vocabulary"}
        search = "tag:wk-core tag:tk-grammar-vocab -tag:kanji -is:suspended"
        self.assertTrue(matches_tag_search(tags, search))
        tags.add("kanji")
        self.assertFalse(matches_tag_search(tags, search))


class ParticleHomographRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = load_fixtures()

    def test_particle_homograph_fixtures(self) -> None:
        lesson_order = int(self.fixtures["default_lesson_order"])
        for case in self.fixtures["particle_homograph_cases"]:
            with self.subTest(case=case["id"]):
                kanji_items: List[dict] = []
                vocab_items: List[dict] = []
                if "kanji" in case:
                    kanji_items.append(_stub_kanji(case["kanji"]))
                if "vocabulary" in case:
                    vocab_items.append(_stub_vocab(case["vocabulary"]))

                text_entries = [(lesson_order, sentence) for sentence in case["sentences"]]
                orders = build_tae_kim_subject_orders(kanji_items, vocab_items, text_entries)

                for subject in (*kanji_items, *vocab_items):
                    self.assertNotIn(
                        int(subject["id"]),
                        orders,
                        msg=f"{case['description']}: matched {subject['data'].get('characters')}",
                    )

    def test_particle_homographs_excluded_from_named_decks(self) -> None:
        lesson_order = int(self.fixtures["default_lesson_order"])
        for case in self.fixtures["particle_homograph_cases"]:
            with self.subTest(case=case["id"]):
                kanji_items = [_stub_kanji(case["kanji"])] if "kanji" in case else []
                vocab_items = [_stub_vocab(case["vocabulary"])] if "vocabulary" in case else []
                cards = _grammar_cards_from_sentences(
                    case["sentences"],
                    production_answers=case.get("production_answers"),
                )
                index = build_core_priority_index(
                    [],
                    kanji_items,
                    vocab_items,
                    tae_kim_exercise_cards=cards,
                )
                excluded = set(case.get("exclude_from_decks") or [])
                for subject in (*kanji_items, *vocab_items):
                    note_tags = _core_note_tags(subject, index)
                    matched = _matching_priority_decks(note_tags)
                    for deck_name in excluded:
                        self.assertNotIn(
                            deck_name,
                            matched,
                            msg=f"{case['id']} subject {subject['id']} matched {deck_name}",
                        )


class ContextVsProductionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = load_fixtures()

    def test_context_sentence_does_not_tag_when_answer_is_particle(self) -> None:
        for case in self.fixtures.get("context_vs_production_cases", []):
            with self.subTest(case=case["id"]):
                kanji_items = [_stub_kanji(case["kanji"])] if "kanji" in case else []
                vocab_items = [_stub_vocab(case["vocabulary"])] if "vocabulary" in case else []
                card = _grammar_card_from_production_case(case)
                index = build_core_priority_index(
                    [],
                    kanji_items,
                    vocab_items,
                    tae_kim_exercise_cards=[card],
                )
                excluded = set(case.get("exclude_from_decks") or [])
                for subject in (*kanji_items, *vocab_items):
                    note_tags = _core_note_tags(subject, index)
                    matched = _matching_priority_decks(note_tags)
                    for deck_name in excluded:
                        self.assertNotIn(
                            deck_name,
                            matched,
                            msg=f"{case['id']} subject {subject['id']} matched {deck_name}",
                        )


class CompoundKanjiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = load_fixtures()

    def test_compound_kanji_fixtures(self) -> None:
        lesson_order = int(self.fixtures["default_lesson_order"])
        for case in self.fixtures["compound_kanji_cases"]:
            with self.subTest(case=case["id"]):
                kanji = _stub_kanji(case["kanji"])
                text_entries = [(lesson_order, sentence) for sentence in case["sentences"]]
                orders = build_tae_kim_subject_orders([kanji], [], text_entries)
                self.assertNotIn(int(kanji["id"]), orders, msg=case["description"])


class LessonCapRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = load_fixtures()

    def test_introduction_to_particles_cap_excludes_late_kanji(self) -> None:
        cap = self.fixtures["lesson_cap"]["max_tae_kim_lesson"]
        subjects = _load_wk_subjects_from_cache()
        if subjects is None:
            self.skipTest("WK subjects cache unavailable")

        radicals = [s for s in subjects if s.get("object") == "radical"]
        kanji = [s for s in subjects if s.get("object") == "kanji"]
        vocab = [s for s in subjects if s.get("object") == "vocabulary"]

        try:
            entries = collect_tae_kim_section_vocabulary_entries(max_tae_kim_lesson=cap)
        except RuntimeError as exc:
            self.skipTest(f"Tae Kim exercise cache unavailable: {exc}")
        if not entries:
            self.skipTest("No vocabulary entries under lesson cap")

        index = build_core_priority_index(
            radicals,
            kanji,
            vocab,
            tae_kim_priority_entries=entries,
        )

        for stub in self.fixtures["lesson_cap"]["late_kanji_not_in_exercises"]:
            subject = next(
                (s for s in kanji if (s.get("data") or {}).get("characters") == stub["characters"]),
                None,
            )
            self.assertIsNotNone(subject, msg=f"kanji {stub['characters']} missing from cache")
            assert subject is not None
            note_tags = _core_note_tags(subject, index)
            for deck_name in (
                "WK::Tae Kim · Grammar Vocab",
                "WK::Tae Kim · Grammar Prereq Kanji",
            ):
                self.assertNotIn(
                    deck_name,
                    _matching_priority_decks(note_tags),
                    msg=f"{stub['characters']} should not appear in {deck_name} under cap {cap}",
                )


class ParsedParticlesExerciseRegressionTests(unittest.TestCase):
    def test_parsed_particles_exercise_does_not_tag_ha_leaf(self) -> None:
        from tae_kim_exercise_decks import parse_tae_kim_exercise_page

        kanji_ha = _stub_kanji({"id": 750, "characters": "葉", "level": 10})
        vocab_ha = _stub_vocab(
            {
                "id": 7629,
                "characters": "葉",
                "reading": "は",
                "level": 10,
                "component_subject_ids": [750],
            }
        )
        parsed = parse_tae_kim_exercise_page(
            PARTICLES_EXERCISE_SNIPPET,
            page="particles_ex.html",
            formation="Particles",
        )
        cards = _grammar_cards_from_sentences(
            [
                " ".join(part for part in (item.cloze_sentence, item.full_sentence) if part)
                for item in parsed
            ],
            production_answers=[item.type_expression for item in parsed],
        )
        index = build_core_priority_index([], [kanji_ha], [vocab_ha], tae_kim_exercise_cards=cards)

        for subject in (kanji_ha, vocab_ha):
            note_tags = _core_note_tags(subject, index)
            self.assertNotIn(TK_GRAMMAR_VOCAB_TAG, note_tags)
            self.assertNotIn(TK_GRAMMAR_PREREQ_TAG, note_tags)


class RealVocabularySectionIntegrationTests(unittest.TestCase):
    def test_section_vocabulary_lists_exclude_homographs_and_late_kanji(self) -> None:
        subjects = _load_wk_subjects_from_cache()
        if subjects is None:
            self.skipTest("WK subjects cache unavailable")

        try:
            entries = collect_tae_kim_section_vocabulary_entries(
                max_tae_kim_lesson="introduction-to-particles",
            )
        except RuntimeError as exc:
            self.skipTest(f"Tae Kim exercise cache unavailable: {exc}")
        if not entries:
            self.skipTest("No vocabulary entries under lesson cap")

        radicals = [s for s in subjects if s.get("object") == "radical"]
        kanji = [s for s in subjects if s.get("object") == "kanji"]
        vocab = [s for s in subjects if s.get("object") == "vocabulary"]
        index = build_core_priority_index(
            radicals,
            kanji,
            vocab,
            tae_kim_priority_entries=entries,
        )

        homograph_vocab_ids = {7629, 2473, 8734, 8646, 9004, 3991}
        homograph_kanji_chars = {"葉", "底"}
        grammar_decks = (
            "WK::Tae Kim · Grammar Vocab",
            "WK::Tae Kim · Grammar Prereq Kanji",
            "WK::Tae Kim · Grammar Prereq Radicals",
        )

        for subject in (*kanji, *vocab):
            subject_id = int(subject["id"])
            chars = (subject.get("data") or {}).get("characters") or ""
            if subject_id not in homograph_vocab_ids and chars not in homograph_kanji_chars:
                continue
            note_tags = _core_note_tags(subject, index)
            matched = _matching_priority_decks(note_tags)
            for deck_name in grammar_decks:
                self.assertNotIn(
                    deck_name,
                    matched,
                    msg=f"subject {subject_id} ({chars}) incorrectly in {deck_name}",
                )

    def test_copula_vocabulary_list_includes_student(self) -> None:
        subjects = _load_wk_subjects_from_cache()
        if subjects is None:
            self.skipTest("WK subjects cache unavailable")
        try:
            entries = collect_tae_kim_section_vocabulary_entries(
                max_tae_kim_lesson="expressing-state-of-being",
            )
        except RuntimeError as exc:
            self.skipTest(f"Tae Kim exercise cache unavailable: {exc}")

        term_text = " ".join(term for _, term in entries)
        self.assertIn("学生", term_text)

        kanji = [s for s in subjects if s.get("object") == "kanji"]
        vocab = [s for s in subjects if s.get("object") == "vocabulary"]
        gaku = next((s for s in kanji if (s.get("data") or {}).get("characters") == "学"), None)
        self.assertIsNotNone(gaku)
        assert gaku is not None
        index = build_core_priority_index([], kanji, vocab, tae_kim_priority_entries=entries)
        entry = index.get(int(gaku["id"]))
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertIsNotNone(entry.tae_kim_order)


if __name__ == "__main__":
    unittest.main()
