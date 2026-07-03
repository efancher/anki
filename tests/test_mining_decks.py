"""Tests for Yomitan mining deck note type."""

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
    MINING_NOTE_TYPE_NAME,
    MINING_SENTENCE_TTS,
    MINING_SETUP_TAG,
    MINING_TEMPLATE_VERSION,
    build_mining_deck,
    make_mining_model,
)
from wk_scheduling import ANKI_QUEUE_SUSPENDED


class MiningDeckTests(unittest.TestCase):
    def test_first_field_is_duplicate_key(self) -> None:
        fields = [field["name"] for field in make_mining_model().fields]
        self.assertEqual(fields[0], "DuplicateKey")

    def test_note_type_name(self) -> None:
        model = make_mining_model()
        self.assertEqual(model.name, MINING_NOTE_TYPE_NAME)

    def test_sentence_tts_on_back_only(self) -> None:
        template = make_mining_model().templates[0]
        self.assertNotIn(MINING_SENTENCE_TTS, template["qfmt"])
        self.assertIn(MINING_SENTENCE_TTS, template["afmt"])
        self.assertIn("sentence-tts", template["afmt"])

    def test_mining_template_version(self) -> None:
        self.assertEqual(MINING_TEMPLATE_VERSION, "v2")

    def test_build_mining_deck_includes_suspended_setup_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            apkg_path, _deck = build_mining_deck(Path(tmp))
            with zipfile.ZipFile(apkg_path) as archive:
                db_path = Path(tmp) / "collection.anki2"
                archive.extract("collection.anki2", tmp)
            conn = sqlite3.connect(db_path)
            note_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            card_count = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            suspended = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE queue = ?",
                (ANKI_QUEUE_SUSPENDED,),
            ).fetchone()[0]
            tags = conn.execute("SELECT tags FROM notes").fetchone()[0]
            conn.close()
            self.assertEqual(note_count, 1)
            self.assertEqual(card_count, 1)
            self.assertEqual(suspended, 1)
            self.assertIn(MINING_SETUP_TAG, tags)


if __name__ == "__main__":
    unittest.main()
