"""Tests for WaniKani conjugation generation in wk_decks.py."""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import (
    ConjugationFixture,
    conjugate_from_fixture,
    conjugate_godan,
    conjugate_ichidan,
    conjugate_i_adjective,
    conjugate_na_adjective,
    conjugate_suru,
    adjective_drill_class,
    assignment_by_subject_id,
    conjugation_build_html,
    conjugation_build_steps,
    conjugation_fixtures_path,
    conjugation_issues_for_vocab,
    conjugation_word_class,
    collect_adjective_type_items,
    collect_conjugation_drills,
    collect_verb_type_items,
    load_conjugation_fixtures,
    mock_vocab_for_conjugation,
    parse_args,
    run_conjugation_fixture_checks,
    scan_conjugation_vocab_issues,
    split_word_stems,
    verb_drill_class,
    verb_type_drill_answer,
    vocab_subjects,
    CONJUGATION_WORD_CLASS_POS,
)


class ConjugationFixtureTests(unittest.TestCase):
    def test_fixture_file_loads(self) -> None:
        fixtures = load_conjugation_fixtures()
        self.assertGreaterEqual(len(fixtures), 40)
        payload = json.loads(conjugation_fixtures_path().read_text(encoding="utf-8"))
        self.assertIn("fixtures", payload)

    def test_all_curated_fixtures_pass(self) -> None:
        failures = run_conjugation_fixture_checks()
        self.assertEqual(failures, [], "\n".join(failures))

    def test_fixture_round_trip_via_mock_vocab(self) -> None:
        for fixture in load_conjugation_fixtures():
            parts = CONJUGATION_WORD_CLASS_POS[fixture.word_class]
            vocab = mock_vocab_for_conjugation(fixture.expr, fixture.reading, parts)
            self.assertEqual(conjugation_word_class(vocab), fixture.word_class)
            result = conjugate_from_fixture(fixture)
            self.assertEqual(
                result,
                (fixture.conj_expr, fixture.conj_reading),
                f"{fixture.expr} {fixture.form_key}",
            )


class ConjugationStemTests(unittest.TestCase):
    def test_split_ichidan_stem(self) -> None:
        self.assertEqual(split_word_stems("食べる", "たべる"), ("食べ", "たべ", "る"))

    def test_split_godan_kanji_ru(self) -> None:
        self.assertEqual(split_word_stems("入る", "はいる"), ("入", "はい", "る"))

    def test_split_godan_su(self) -> None:
        self.assertEqual(split_word_stems("話す", "はなす"), ("話", "はな", "す"))

    def test_split_suru_compound(self) -> None:
        self.assertEqual(
            split_word_stems("勉強する", "べんきょうする"),
            ("勉強", "べんきょう", "する"),
        )


class ConjugationGodanEndingTests(unittest.TestCase):
    def test_each_godan_ending_te_form(self) -> None:
        cases = [
            ("買う", "かう", "買って", "かって"),
            ("書く", "かく", "書いて", "かいて"),
            ("泳ぐ", "およぐ", "泳いで", "およいで"),
            ("話す", "はなす", "話して", "はなして"),
            ("立つ", "たつ", "立って", "たって"),
            ("死ぬ", "しぬ", "死んで", "しんで"),
            ("飛ぶ", "とぶ", "飛んで", "とんで"),
            ("読む", "よむ", "読んで", "よんで"),
            ("帰る", "かえる", "帰って", "かえって"),
        ]
        for expr, reading, exp_expr, exp_reading in cases:
            result = conjugate_godan(expr, reading, "te_form")
            self.assertEqual(result, (exp_expr, exp_reading), expr)


class ConjugationIssueDetectionTests(unittest.TestCase):
    def test_healthy_vocab_has_no_issues(self) -> None:
        vocab = mock_vocab_for_conjugation("食べる", "たべる", ["ichidan verb"])
        self.assertEqual(conjugation_issues_for_vocab(vocab), [])

    def test_missing_reading_is_flagged(self) -> None:
        vocab = mock_vocab_for_conjugation("食べる", "", ["ichidan verb"])
        self.assertIn("missing reading", conjugation_issues_for_vocab(vocab))

    def test_collect_skips_unchanged_forms(self) -> None:
        class Args:
            max_cards = 100

        vocab = mock_vocab_for_conjugation("食べる", "たべる", ["ichidan verb"])
        drills = collect_conjugation_drills([vocab], {}, Args(), min_srs=0)
        self.assertGreater(len(drills), 0)
        for drill in drills:
            self.assertNotEqual((drill.dict_expr, drill.dict_reading), (drill.conj_expr, drill.conj_reading))

    def test_scan_flags_only_problem_vocab(self) -> None:
        good = mock_vocab_for_conjugation("食べる", "たべる", ["ichidan verb"], vocab_id=1)
        bad = mock_vocab_for_conjugation("食べる", "", ["ichidan verb"], vocab_id=2)
        flagged = scan_conjugation_vocab_issues([good, bad])
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0].vocab["id"], 2)


class ConjugationAdjectiveTests(unittest.TestCase):
    def test_i_adjective_polite_past(self) -> None:
        self.assertEqual(
            conjugate_i_adjective("大きい", "おおきい", "polite_past"),
            ("大きかったです", "おおきかったです"),
        )

    def test_na_adjective_polite_negative(self) -> None:
        self.assertEqual(
            conjugate_na_adjective("元気", "げんき", "polite_negative"),
            ("元気じゃないです", "げんきじゃないです"),
        )


class ConjugationSuruTests(unittest.TestCase):
    def test_suru_compound_polite_present(self) -> None:
        self.assertEqual(
            conjugate_suru("勉強する", "べんきょうする", "polite_present"),
            ("勉強します", "べんきょうします"),
        )


class WordClassDrillTests(unittest.TestCase):
    def test_verb_drill_classes(self) -> None:
        godan = mock_vocab_for_conjugation("入る", "はいる", ["godan verb"], vocab_id=1)
        ichidan = mock_vocab_for_conjugation("食べる", "たべる", ["ichidan verb"], vocab_id=2)
        suru = mock_vocab_for_conjugation("勉強する", "べんきょうする", ["する verb"], vocab_id=3)
        kuru = mock_vocab_for_conjugation("来る", "くる", ["intransitive verb"], vocab_id=4)

        self.assertEqual(verb_drill_class(godan), "godan")
        self.assertEqual(verb_drill_class(ichidan), "ichidan")
        self.assertEqual(verb_drill_class(suru), "irregular")
        self.assertEqual(verb_drill_class(kuru), "irregular")
        self.assertIn("来る", verb_type_drill_answer(kuru, "irregular"))
        self.assertIn("する", verb_type_drill_answer(suru, "irregular"))

    def test_adjective_drill_classes(self) -> None:
        i_adj = mock_vocab_for_conjugation("大きい", "おおきい", ["い adjective"], vocab_id=5)
        na_adj = mock_vocab_for_conjugation("大人", "おとな", ["な adjective"], vocab_id=6)
        noun = mock_vocab_for_conjugation("本", "ほん", ["noun"], vocab_id=7)

        self.assertEqual(adjective_drill_class(i_adj), "i_adjective")
        self.assertEqual(adjective_drill_class(na_adj), "na_adjective")
        self.assertIsNone(adjective_drill_class(noun))

    def test_collect_type_items_from_cache_vocab(self) -> None:
        cache = Path(".wk_cache")
        subjects_path = cache / "subjects_vocabulary_kanji_radical.json"
        if not subjects_path.exists():
            self.skipTest("no WK cache")
        subjects = json.loads(subjects_path.read_text(encoding="utf-8"))["items"]
        assignment_files = list(cache.glob("assignments_*.json"))
        if not assignment_files:
            self.skipTest("no assignment cache")
        assignments = json.loads(assignment_files[0].read_text(encoding="utf-8"))["items"]
        args = argparse.Namespace(
            only_started=True,
            max_cards=5000,
            max_level=60,
            only_unlocked=False,
            only_burned=False,
            min_srs=1,
        )
        vocab = vocab_subjects(subjects, assignment_by_subject_id(assignments), args)
        verbs = collect_verb_type_items(vocab, args)
        adjs = collect_adjective_type_items(vocab, args)
        self.assertGreater(len(verbs), 0)
        self.assertGreater(len(adjs), 0)


class ConjugationBuildTests(unittest.TestCase):
    def test_ichidan_polite_stacks_masu(self) -> None:
        steps = conjugation_build_steps(
            "ichidan", "polite_present", "食べる", "たべる", "食べます", "たべます"
        )
        surfaces = [step.surface for step in steps]
        self.assertEqual(surfaces[:3], ["食べる", "食べ", "食べます"])
        html = conjugation_build_html(
            "ichidan", "polite_present", "食べる", "たべる", "食べます", "たべます"
        )
        self.assertIn("drop る", html)
        self.assertIn("食べます", html)
        self.assertIn("Ichidan", html)

    def test_godan_polite_shows_i_row_shift(self) -> None:
        steps = conjugation_build_steps(
            "godan", "polite_present", "話す", "はなす", "話します", "はなします"
        )
        surfaces = [step.surface for step in steps]
        self.assertIn("話", surfaces)
        self.assertIn("話し", surfaces)
        self.assertIn("話します", surfaces)

    def test_i_adjective_negative_stacks_ku_nai(self) -> None:
        steps = conjugation_build_steps(
            "i_adjective", "plain_negative", "高い", "たかい", "高くない", "たかくない"
        )
        surfaces = [step.surface for step in steps]
        self.assertEqual(surfaces, ["高い", "高", "高く", "高くない"])

    def test_na_adjective_polite_adds_desu(self) -> None:
        steps = conjugation_build_steps(
            "na_adjective", "polite", "静か", "しずか", "静かです", "しずかです"
        )
        self.assertEqual([s.surface for s in steps], ["静か", "静かです"])


if __name__ == "__main__":
    unittest.main()
