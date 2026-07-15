"""Tests for Yomitan immersion deck note type."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mining_decks import (
    MINING_EXPORT_FILENAME,
    MINING_FIELD_NAMES,
    MINING_NOTE_TYPE_NAME,
    MINING_SENTENCE_TTS,
    MINING_SETUP_TAG,
    MINING_TAG,
    MINING_TEMPLATE_VERSION,
    build_mining_deck,
    make_mining_model,
)
from wk_scheduling import ANKI_QUEUE_SUSPENDED


class MiningDeckTests(unittest.TestCase):
    def test_first_field_is_duplicate_key(self) -> None:
        fields = [field["name"] for field in make_mining_model().fields]
        self.assertEqual(fields[0], "DuplicateKey")

    def test_yomitan_identity(self) -> None:
        self.assertEqual(MINING_NOTE_TYPE_NAME, "WK Yomitan Immersion")
        self.assertEqual(MINING_TAG, "yomitan-mining")
        self.assertEqual(MINING_EXPORT_FILENAME, "wk_mining.apkg")

    def test_media_and_pitch_fields_exist(self) -> None:
        fields = [field["name"] for field in make_mining_model().fields]
        for name in (
            "Image",
            "Translation",
            "SentenceAudio",
            "PitchAccents",
            "PitchPositions",
            "PitchGraphs",
            "Audio",
        ):
            self.assertIn(name, fields)

    def test_mining_cloze_fields_exist(self) -> None:
        fields = [field["name"] for field in make_mining_model().fields]
        for name in (
            "ClozeSentence",
            "WkSubjectId",
            "PrerequisiteIds",
            "HintStage",
            "ShowEnglish",
            "ShowKana",
            "ShowJjBack",
            "SentenceKana",
            "DictLinksJa",
            "DictLinksEn",
        ):
            self.assertIn(name, fields)

    def test_front_shows_cloze_and_type(self) -> None:
        template = make_mining_model().templates[0]
        self.assertIn("cloze-sentence", template["qfmt"])
        self.assertIn("type:Reading", template["qfmt"])
        self.assertIn("Translation", template["qfmt"])
        self.assertNotIn("word-block", template["qfmt"])

    def test_shadow_card_template(self) -> None:
        templates = make_mining_model().templates
        self.assertEqual(len(templates), 2)
        shadow = templates[1]
        self.assertEqual(shadow["name"], "Shadow → pitch")
        self.assertIn("shadow-card", shadow["qfmt"])
        self.assertIn("{{SentenceAudio}}", shadow["qfmt"])
        self.assertIn("{{PitchAccents}}", shadow["afmt"])
        self.assertIn("{{PitchGraphs}}", shadow["afmt"])
        self.assertIn("{{SentenceKana}}", shadow["afmt"])

    def test_back_shows_image_and_audio(self) -> None:
        template = make_mining_model().templates[0]
        afmt = template["afmt"]
        self.assertIn("{{Image}}", afmt)
        self.assertIn("{{SentenceAudio}}", afmt)
        self.assertIn(MINING_SENTENCE_TTS, afmt)

    def test_jj_defs_hidden_until_show_jj_back(self) -> None:
        template = make_mining_model().templates[0]
        afmt = template["afmt"]
        self.assertIn("{{#ShowJjBack}}", afmt)
        self.assertIn("{{#Glossary}}", afmt)
        show_pos = afmt.index("{{#ShowJjBack}}")
        glossary_pos = afmt.index("{{#Glossary}}")
        self.assertLess(show_pos, glossary_pos)

    def test_mining_template_version(self) -> None:
        self.assertEqual(MINING_TEMPLATE_VERSION, "v14")
        self.assertEqual(len(MINING_FIELD_NAMES), len(make_mining_model().fields))

    def test_build_exports_suspended_setup_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            path, _deck = build_mining_deck(out_dir)
            self.assertEqual(path.name, MINING_EXPORT_FILENAME)
            self.assertTrue(path.is_file())
            with zipfile.ZipFile(path) as archive:
                archive.extract("collection.anki2", path=tmp)
            conn = sqlite3.connect(Path(tmp) / "collection.anki2")
            try:
                row = conn.execute(
                    "SELECT queue FROM cards LIMIT 1"
                ).fetchone()
                self.assertEqual(row[0], ANKI_QUEUE_SUSPENDED)
                tags = conn.execute("SELECT tags FROM notes LIMIT 1").fetchone()[0]
                self.assertIn(MINING_SETUP_TAG, tags)
                self.assertIn(MINING_TAG, tags)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
