"""Tests for Tae Kim exercise deck generation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tae_kim_exercise_decks import (
    collect_tae_kim_exercise_cards,
    collect_tae_kim_section_vocabulary_entries,
    exercise_audio_basename,
    exercise_page_within_cap,
    exercise_point_id,
    fetch_tae_kim_exercise_html,
    load_tae_kim_exercise_page_specs,
    parse_tae_kim_exercise_page,
    parse_tae_kim_vocabulary_section,
    vocabulary_term_from_list_item,
)
from tae_kim_mapping import tae_kim_lesson_by_slug

COPULA_EXERCISE2_SNIPPET = """
<h2 id="part3">Conjugation Exercise 2</h2>
<div id="exercise2">
<table class="large" border="0" cellspacing="8">
<tr>
	<td>1. Is college.</td>
	<td>＝</td>
	<td class="answerline"><span class="hide">大学だ。</span></td>
</tr>
<tr>
	<td>2. Is not high school.</td>
	<td>＝</td>
	<td class="answerline"><span class="hide">高校じゃない。</span></td>
</tr>
</table>
</div>
<div class="botmenu"></div>
"""

COPULA_EXERCISE1_SNIPPET = """
<h2 id="part2">Conjugation Exercise 1</h2>
<div id="exercise1">
<table class="large" border="0" cellspacing="8">
<tr>
	<td colspan="3">1. <b>学生</b></td>
</tr>
<tr>
	<td>declarative</td>
	<td>=</td>
	<td class="answerline"><span class="hide">学生だ</span></td>
</tr>
<tr>
	<td>negative</td>
	<td>=</td>
	<td class="answerline"><span class="hide">学生じゃない</span></td>
</tr>
</table>
</div>
<div class="botmenu"></div>
"""

COPULA_QA_SNIPPET = """
<h2 id="part4">Question Answer Exercise</h2>
<div id="exercise4">
<table class="large" border="0" cellspacing="8">
<tr>
	<td>Ｑ１）　友達？</td>
</tr>
<tr>
	<td>Ａ１）　うん、<span class="answerline"><span class="hide">友達</span></span>。 <span style="font-size:.7em;">(female)</span></td>
</tr>
<tr><td /></tr>
<tr>
	<td>Ｑ２）　学校？</td>
</tr>
<tr>
	<td>Ａ２）　ううん、<span class="answerline"><span class="hide">学校じゃない</span></span>。</td>
</tr>
</table>
</div>
<div class="botmenu"></div>
"""

PARTICLE_INLINE_SNIPPET = """
<h2 id="part2">Basic Particle Exercise with 「は」</h2>
<div id="exercise2">
<table class="large" border="0" cellspacing="8">
<tr><td>
１．今日は雨だ。昨日<span class="answerline"><span class="hide">　も　</span></span>雨だった。
</td></tr>
</table>
</div>
<div class="botmenu"></div>
"""

COPULA_VOCABULARY_SNIPPET = """
<h2 id="part1">Vocabulary used in this section</h2>
<div class="sumbox">
<ol>
<li><a href="#">人</a> - person</li>
<li>友達 【ともだち】 - friend</li>
<li>学生 【がくせい】 - student</li>
</ol>
</div>
<h2 id="part2">Conjugation Exercise 1</h2>
"""


class TaeKimExerciseDeckTests(unittest.TestCase):
    def test_load_registry_includes_copula_page(self) -> None:
        pages = load_tae_kim_exercise_page_specs()
        copula = [spec for spec in pages if spec.page == "copula_ex.html"]
        self.assertEqual(len(copula), 1)
        self.assertEqual(copula[0].parent_lesson, "expressing-state-of-being")

    def test_parse_en_to_jp_rows(self) -> None:
        items = parse_tae_kim_exercise_page(
            COPULA_EXERCISE2_SNIPPET,
            page="copula_ex.html",
            formation="Noun + だ",
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].type_expression, "大学だ。")
        self.assertEqual(items[0].hint, "Is college")
        self.assertEqual(items[1].type_expression, "高校じゃない。")

    def test_parse_conjugation_noun_block(self) -> None:
        items = parse_tae_kim_exercise_page(
            COPULA_EXERCISE1_SNIPPET,
            page="copula_ex.html",
            formation="Noun + だ",
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].cloze_sentence, "＿＿＿")
        self.assertEqual(items[0].type_expression, "学生だ")
        self.assertEqual(items[1].type_expression, "学生じゃない")

    def test_parse_qa_pairs(self) -> None:
        items = parse_tae_kim_exercise_page(
            COPULA_QA_SNIPPET,
            page="copula_ex.html",
            formation="Noun + だ",
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].hint, "友達？")
        self.assertEqual(items[0].cloze_sentence, "うん、＿＿＿。")
        self.assertEqual(items[0].full_sentence, "うん、友達。")
        self.assertEqual(items[1].cloze_sentence, "ううん、＿＿＿。")

    def test_parse_inline_particle_cloze(self) -> None:
        items = parse_tae_kim_exercise_page(
            PARTICLE_INLINE_SNIPPET,
            page="particles_ex.html",
            formation="Particles",
        )
        self.assertEqual(len(items), 1)
        self.assertIn("＿＿＿", items[0].cloze_sentence)
        self.assertEqual(items[0].type_expression, "も")

    def test_parse_vocabulary_section_terms(self) -> None:
        self.assertEqual(vocabulary_term_from_list_item("人 - person"), "人")
        self.assertEqual(
            vocabulary_term_from_list_item("友達 【ともだち】 - friend"),
            "友達",
        )
        terms = parse_tae_kim_vocabulary_section(COPULA_VOCABULARY_SNIPPET)
        self.assertEqual(terms, ["人", "友達", "学生"])

    def test_collect_section_vocabulary_respects_lesson_cap(self) -> None:
        cache_path = REPO_ROOT / ".wk_cache" / "tae_kim_exercises" / "copula_ex.json"
        if not cache_path.is_file():
            try:
                fetch_tae_kim_exercise_html("copula_ex.html", refresh=True)
            except RuntimeError:
                self.skipTest("copula_ex cache unavailable and network fetch failed")
        lesson_one = collect_tae_kim_section_vocabulary_entries(
            max_tae_kim_lesson="expressing-state-of-being",
        )
        through_particles = collect_tae_kim_section_vocabulary_entries(
            max_tae_kim_lesson="introduction-to-particles",
        )
        self.assertGreater(len(lesson_one), 0)
        self.assertGreater(len(through_particles), len(lesson_one))
        term_text = " ".join(term for _, term in through_particles)
        self.assertNotIn("底", term_text)

    def test_exercise_page_within_lesson_cap(self) -> None:
        copula = next(spec for spec in load_tae_kim_exercise_page_specs() if spec.page == "copula_ex.html")
        particles = next(spec for spec in load_tae_kim_exercise_page_specs() if spec.page == "particles_ex.html")
        self.assertTrue(
            exercise_page_within_cap(
                copula,
                max_tae_kim_section=3,
                lesson_cap=("basic", 1),
            )
        )
        self.assertFalse(
            exercise_page_within_cap(
                particles,
                max_tae_kim_section=3,
                lesson_cap=("basic", 1),
            )
        )

    def test_exercise_point_id_is_stable(self) -> None:
        first = exercise_point_id("copula_ex.html", "exercise2-0")
        second = exercise_point_id("copula_ex.html", "exercise2-0")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("tk-ex-"))

    def test_exercise_audio_basename_is_stable(self) -> None:
        point_id = exercise_point_id("copula_ex.html", "exercise2-0")
        first = exercise_audio_basename(point_id)
        second = exercise_audio_basename(point_id)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("wk_tk_ex_"))

    def test_collect_respects_lesson_cap_offline_cache(self) -> None:
        cache_path = REPO_ROOT / ".wk_cache" / "tae_kim_exercises" / "copula_ex.json"
        if not cache_path.is_file():
            try:
                fetch_tae_kim_exercise_html("copula_ex.html", refresh=True)
            except RuntimeError:
                self.skipTest("copula_ex cache unavailable and network fetch failed")
        lesson_one = collect_tae_kim_exercise_cards(
            max_tae_kim_lesson="expressing-state-of-being",
        )
        through_particles = collect_tae_kim_exercise_cards(
            max_tae_kim_lesson="introduction-to-particles",
        )
        self.assertGreater(len(lesson_one), 0)
        self.assertGreater(len(through_particles), len(lesson_one))
        parent = tae_kim_lesson_by_slug("basic", "expressing-state-of-being")
        self.assertIsNotNone(parent)
        for card in lesson_one:
            self.assertEqual(card.tae_kim_lesson.slug, "expressing-state-of-being")

    def test_build_exercise_deck_bundles_audio(self) -> None:
        from tae_kim_exercise_decks import build_tae_kim_exercise_deck

        cards = collect_tae_kim_exercise_cards(max_tae_kim_lesson="expressing-state-of-being")
        if not cards:
            self.skipTest("No exercise cards available")
        card = cards[0]

        def fake_ensure(_text, _voice, dest, refresh=False):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"fake")
            return True, False

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch("tae_kim_exercise_decks.ensure_sentence_audio_file", side_effect=fake_ensure):
                with mock.patch("tae_kim_exercise_decks.require_edge_tts"):
                    apkg_path, deck, media = build_tae_kim_exercise_deck([card], output_dir)
            self.assertEqual(apkg_path.name, "wk_tae_kim_exercises.apkg")
            self.assertEqual(len(deck.notes), 1)
            self.assertEqual(len(media), 1)
            self.assertTrue(deck.notes[0].fields[9].startswith("[sound:wk_tts_"))


if __name__ == "__main__":
    unittest.main()
