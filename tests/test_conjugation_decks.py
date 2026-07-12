"""Tests for conjugation deck filtering and FSRS apkg patching."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import genanki

from wk_decks import (
    ADJECTIVE_CONJUGATION_WORD_CLASSES,
    CONJUGATION_DEFAULT_MIN_SRS,
    VERB_CONJUGATION_WORD_CLASSES,
    WK_FSRS_DECK_CONFIG_ID,
    WK_FSRS_PRESET_NAME,
    WK_SRS_STAGE_MASTER,
    collect_conjugation_drills,
    make_conjugation_model,
    make_conjugation_reverse_model,
    make_word_class_model,
    mock_vocab_for_conjugation,
    patch_apkg_deck_options,
    write_apkg,
)


class ConjugationMinSrsTest(unittest.TestCase):
    def test_default_min_srs_is_master(self) -> None:
        self.assertEqual(CONJUGATION_DEFAULT_MIN_SRS, WK_SRS_STAGE_MASTER)

    def test_conjugation_models_include_kanji_prerequisite_ids(self) -> None:
        for model in (
            make_conjugation_model(),
            make_conjugation_reverse_model(),
            make_word_class_model(),
        ):
            names = [field["name"] for field in model.fields]
            self.assertIn("PrerequisiteIds", names)
            self.assertLess(names.index("PrerequisiteIds"), names.index("Meta"))

    def test_conjugation_models_include_build_html_on_back(self) -> None:
        for model in (make_conjugation_model(), make_conjugation_reverse_model()):
            names = [field["name"] for field in model.fields]
            self.assertIn("BuildHtml", names)
            self.assertIn("{{BuildHtml}}", model.templates[0]["afmt"])
            self.assertNotIn("{{BuildHtml}}", model.templates[0]["qfmt"])

    def test_collect_respects_min_srs(self) -> None:
        vocab = mock_vocab_for_conjugation("食べる", "たべる", ["ichidan verb"], vocab_id=42)
        assignment_index = {
            42: {"data": {"subject_id": 42, "srs_stage": 5}},
        }
        args = argparse.Namespace(max_cards=100)
        guru_drills = collect_conjugation_drills(
            [vocab],
            assignment_index,
            args,
            min_srs=WK_SRS_STAGE_MASTER,
            word_classes=VERB_CONJUGATION_WORD_CLASSES,
        )
        master_drills = collect_conjugation_drills(
            [vocab],
            assignment_index | {42: {"data": {"subject_id": 42, "srs_stage": WK_SRS_STAGE_MASTER}}},
            args,
            min_srs=WK_SRS_STAGE_MASTER,
            word_classes=VERB_CONJUGATION_WORD_CLASSES,
        )
        self.assertEqual(guru_drills, [])
        self.assertGreater(len(master_drills), 0)

    def test_word_class_filter_splits_verbs_and_adjectives(self) -> None:
        verb = mock_vocab_for_conjugation("食べる", "たべる", ["ichidan verb"], vocab_id=1)
        adj = mock_vocab_for_conjugation("大きい", "おおきい", ["い adjective"], vocab_id=2)
        assignment_index = {
            1: {"data": {"subject_id": 1, "srs_stage": WK_SRS_STAGE_MASTER}},
            2: {"data": {"subject_id": 2, "srs_stage": WK_SRS_STAGE_MASTER}},
        }
        args = argparse.Namespace(max_cards=100)
        verb_drills = collect_conjugation_drills(
            [verb, adj],
            assignment_index,
            args,
            min_srs=0,
            word_classes=VERB_CONJUGATION_WORD_CLASSES,
        )
        adj_drills = collect_conjugation_drills(
            [verb, adj],
            assignment_index,
            args,
            min_srs=0,
            word_classes=ADJECTIVE_CONJUGATION_WORD_CLASSES,
        )
        self.assertTrue(all(d.word_class in VERB_CONJUGATION_WORD_CLASSES for d in verb_drills))
        self.assertTrue(all(d.word_class in ADJECTIVE_CONJUGATION_WORD_CLASSES for d in adj_drills))

class ConjugationAudioTemplateTests(unittest.TestCase):
    def test_conjugation_model_places_prompt_audio_on_front_and_answer_on_back(self) -> None:
        model = make_conjugation_model()
        field_names = [field["name"] for field in model.fields]
        self.assertIn("PromptAudio", field_names)
        self.assertIn("AnswerAudio", field_names)
        qfmt = model.templates[0]["qfmt"]
        afmt = model.templates[0]["afmt"]
        self.assertIn("PromptAudio", qfmt)
        self.assertNotIn("AnswerAudio", qfmt)
        self.assertIn("AnswerAudio", afmt)

    def test_conjugation_reverse_model_places_conjugated_audio_on_front(self) -> None:
        model = make_conjugation_reverse_model()
        qfmt = model.templates[0]["qfmt"]
        afmt = model.templates[0]["afmt"]
        self.assertIn("PromptAudio", qfmt)
        self.assertIn("AnswerAudio", afmt)
        self.assertNotIn("AnswerAudio", qfmt)

    def test_word_class_model_places_reading_audio_on_front_and_back(self) -> None:
        model = make_word_class_model()
        qfmt = model.templates[0]["qfmt"]
        afmt = model.templates[0]["afmt"]
        self.assertIn("PromptAudio", qfmt)
        self.assertIn("AnswerAudio", afmt)
        self.assertNotIn("AnswerAudio", qfmt)


class ApkgDeckOptionsPatchTest(unittest.TestCase):
    def test_patch_assigns_wk_fsrs_preset(self) -> None:
        deck = genanki.Deck(2059400998, "Patch Test Deck")
        with tempfile.TemporaryDirectory() as tmpdir:
            apkg_path = Path(tmpdir) / "test.apkg"
            write_apkg(deck, apkg_path)

            with zipfile.ZipFile(apkg_path, "r") as archive:
                db_bytes = archive.read("collection.anki2")
            db_path = Path(tmpdir) / "collection.anki2"
            db_path.write_bytes(db_bytes)
            conn = sqlite3.connect(db_path)
            decks = json.loads(conn.execute("SELECT decks FROM col").fetchone()[0])
            dconf = json.loads(conn.execute("SELECT dconf FROM col").fetchone()[0])
            conn.close()

            self.assertEqual(decks["2059400998"]["conf"], WK_FSRS_DECK_CONFIG_ID)
            self.assertEqual(dconf[str(WK_FSRS_DECK_CONFIG_ID)]["name"], WK_FSRS_PRESET_NAME)
            self.assertIn("desiredRetention", dconf[str(WK_FSRS_DECK_CONFIG_ID)])


if __name__ == "__main__":
    unittest.main()
