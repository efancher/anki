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

    def test_user_notes_field_exists(self) -> None:
        fields = [field["name"] for field in make_mining_model().fields]
        self.assertIn("UserNotes", fields)

    def test_front_shows_word_and_reading(self) -> None:
        template = make_mining_model().templates[0]
        self.assertIn("{{Furigana}}", template["qfmt"])
        self.assertIn("{{Reading}}", template["qfmt"])
        self.assertNotIn("{{Sentence}}", template["qfmt"])
        self.assertNotIn("type:", template["qfmt"])

    def test_pitch_fields_on_back(self) -> None:
        template = make_mining_model().templates[0]
        self.assertIn("{{PitchAccents}}", template["afmt"])
        self.assertIn("pitch-graphs", template["afmt"])

    def test_sentence_furigana_on_back(self) -> None:
        template = make_mining_model().templates[0]
        self.assertIn("{{SentenceFurigana}}", template["afmt"])
        self.assertIn("context-furigana", template["afmt"])

    def test_user_notes_on_back_when_present(self) -> None:
        template = make_mining_model().templates[0]
        self.assertIn("{{#UserNotes}}", template["afmt"])
        self.assertIn("{{UserNotes}}", template["afmt"])
        self.assertIn("user-notes", template["afmt"])

    def test_note_type_name(self) -> None:
        model = make_mining_model()
        self.assertEqual(model.name, MINING_NOTE_TYPE_NAME)

    def test_sentence_tts_on_back_when_no_audio(self) -> None:
        template = make_mining_model().templates[0]
        self.assertNotIn(MINING_SENTENCE_TTS, template["qfmt"])
        self.assertIn(MINING_SENTENCE_TTS, template["afmt"])
        self.assertIn("sentence-tts", template["afmt"])

    def test_mining_template_version(self) -> None:
        self.assertEqual(MINING_TEMPLATE_VERSION, "v9")

    def test_word_def_fields_exist(self) -> None:
        fields = [field["name"] for field in make_mining_model().fields]
        self.assertIn("Glossary", fields)
        self.assertIn("Synonyms", fields)
        self.assertIn("Antonyms", fields)
        glossary_idx = fields.index("Glossary")
        self.assertEqual(fields[glossary_idx + 1], "Synonyms")
        self.assertEqual(fields[glossary_idx + 2], "Antonyms")

    def test_word_defs_on_card_back(self) -> None:
        template = make_mining_model().templates[0]
        afmt = template["afmt"]
        self.assertIn("{{#Glossary}}", afmt)
        self.assertIn("{{#Synonyms}}", afmt)
        self.assertIn("{{#Antonyms}}", afmt)
        self.assertIn("word-def-glossary", afmt)
        self.assertLess(afmt.index("word-def-glossary"), afmt.index("word-audio-block"))
        self.assertLess(afmt.index("word-audio-block"), afmt.index("{{#Sentence}}"))

    def test_separate_word_and_sentence_audio_on_back(self) -> None:
        template = make_mining_model().templates[0]
        afmt = template["afmt"]
        self.assertIn("word-audio-block", afmt)
        self.assertIn("sentence-audio-block", afmt)
        self.assertIn("{{Audio}}", afmt)
        self.assertLess(afmt.index("word-audio-block"), afmt.index("sentence-audio-block"))
        self.assertNotIn("mined-audio", afmt)

    def test_sentence_audio_field_exists(self) -> None:
        fields = [field["name"] for field in make_mining_model().fields]
        self.assertIn("SentenceAudio", fields)

    def test_sentence_audio_preferred_on_back(self) -> None:
        template = make_mining_model().templates[0]
        self.assertIn("{{SentenceAudio}}", template["afmt"])
        self.assertLess(template["afmt"].index("SentenceAudio"), template["afmt"].index("VoicevoxAudio"))

    def test_voicevox_audio_fields_exist(self) -> None:
        fields = [field["name"] for field in make_mining_model().fields]
        self.assertIn("VoicevoxAudio", fields)
        self.assertIn("VoicevoxSpeakerId", fields)

    def test_voicevox_audio_preferred_on_back(self) -> None:
        template = make_mining_model().templates[0]
        self.assertIn("{{VoicevoxAudio}}", template["afmt"])
        self.assertIn("voicevox-audio", template["afmt"])
        self.assertLess(
            template["afmt"].index("VoicevoxAudio"),
            template["afmt"].index(MINING_SENTENCE_TTS),
        )

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
