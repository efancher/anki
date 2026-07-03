"""Tests for .apkg note mod patching (re-import field updates)."""

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

import genanki

from core_decks import make_core_radical_model
from wk_decks import (
    NOTE_CONTENT_MOD_FLOOR,
    export_note_mod_timestamp,
    package_write_timestamp,
    patch_apkg_note_mods,
    write_apkg,
)


def _note_mods_from_apkg(apkg_path: Path) -> list[int]:
    with zipfile.ZipFile(apkg_path, "r") as archive:
        db_bytes = archive.read("collection.anki2")
    with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as tmp_db:
        tmp_db.write(db_bytes)
        tmp_path = tmp_db.name
    try:
        conn = sqlite3.connect(tmp_path)
        mods = [row[0] for row in conn.execute("SELECT mod FROM notes ORDER BY id")]
        conn.close()
        return mods
    finally:
        Path(tmp_path).unlink(missing_ok=True)


class ApkgNoteModsPatchTest(unittest.TestCase):
    def test_export_note_mod_timestamp_uses_floor_for_small_models(self) -> None:
        model = make_core_radical_model()
        self.assertGreater(export_note_mod_timestamp([model]), package_write_timestamp([model]))
        self.assertGreaterEqual(export_note_mod_timestamp([model]), NOTE_CONTENT_MOD_FLOOR)

    def test_write_apkg_sets_note_mods_to_export_timestamp(self) -> None:
        model = make_core_radical_model()
        deck = genanki.Deck(2059400999, "Note Mod Patch Test")
        deck.add_note(
            genanki.Note(
                model=model,
                fields=["guid-a", "一", "one", "1", "100", "", "desc a"],
                guid="guid-a",
            )
        )
        expected_mod = export_note_mod_timestamp([model])

        with tempfile.TemporaryDirectory() as tmpdir:
            apkg_path = Path(tmpdir) / "test.apkg"
            write_apkg(deck, apkg_path)
            self.assertEqual(_note_mods_from_apkg(apkg_path), [expected_mod])

    def test_patch_apkg_note_mods_sets_all_notes(self) -> None:
        model = make_core_radical_model()
        deck = genanki.Deck(2059400998, "Raw Note Mod Test")
        deck.add_note(
            genanki.Note(
                model=model,
                fields=["guid-a", "一", "one", "1", "100", "", "desc a"],
                guid="guid-a",
            )
        )
        deck.add_note(
            genanki.Note(
                model=model,
                fields=["guid-b", "二", "two", "1", "101", "", "desc b"],
                guid="guid-b",
            )
        )
        target_mod = NOTE_CONTENT_MOD_FLOOR + 42

        with tempfile.TemporaryDirectory() as tmpdir:
            apkg_path = Path(tmpdir) / "test.apkg"
            genanki.Package(deck).write_to_file(
                str(apkg_path),
                timestamp=package_write_timestamp([model]),
            )
            patch_apkg_note_mods(apkg_path, target_mod)
            self.assertEqual(_note_mods_from_apkg(apkg_path), [target_mod, target_mod])


if __name__ == "__main__":
    unittest.main()
