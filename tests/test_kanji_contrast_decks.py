"""Tests for curated kanji contrast deck generation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kanji_contrast_decks import (
    MAX_KANJI_CONTRAST_GROUP_SIZE,
    MIN_KANJI_CONTRAST_GROUP_SIZE,
    KanjiContrastGroup,
    group_display_title,
    group_note_guid,
    group_stable_key,
    load_kanji_contrast_groups,
    make_kanji_contrast_model,
    resolve_kanji_contrast_groups,
)
from wk_decks import export_note_mod_timestamp, write_apkg


def mock_kanji(char: str, subject_id: int, level: int = 8) -> dict:
    return {
        "id": subject_id,
        "object": "kanji",
        "data": {
            "characters": char,
            "level": level,
            "meanings": [{"meaning": f"Meaning-{char}", "primary": True}],
            "readings": [{"reading": "じ", "primary": True, "accepted_answer": True}],
            "component_subject_ids": [],
        },
    }


class KanjiContrastDecksTests(unittest.TestCase):
    def test_load_default_groups_file(self) -> None:
        groups = load_kanji_contrast_groups()
        self.assertGreaterEqual(len(groups), 1)
        next_vs_lack = next(
            (group for group in groups if "次" in group.kanji_chars and "欠" in group.kanji_chars),
            None,
        )
        self.assertIsNotNone(next_vs_lack)
        assert next_vs_lack is not None
        self.assertEqual(len(next_vs_lack.kanji_chars), 2)

    def test_rejects_too_few_or_too_many_kanji(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "groups.json"
            path.write_text(
                json.dumps({"groups": [{"kanji": ["次"]}]}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_kanji_contrast_groups(path)

            many = ["一", "二", "三", "四", "五", "六", "七"]
            path.write_text(
                json.dumps({"groups": [{"kanji": many}]}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_kanji_contrast_groups(path)

    def test_accepts_six_kanji_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "groups.json"
            chars = ["一", "二", "三", "四", "五", "六"]
            path.write_text(json.dumps({"groups": [{"kanji": chars}]}), encoding="utf-8")
            groups = load_kanji_contrast_groups(path)
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0].kanji_chars), MAX_KANJI_CONTRAST_GROUP_SIZE)

    def test_resolve_skips_missing_kanji_with_warning(self) -> None:
        groups = [KanjiContrastGroup(kanji_chars=("次", "欠", "無"))]
        by_char = {
            "次": mock_kanji("次", 616),
            "欠": mock_kanji("欠", 646),
        }
        resolved, warnings = resolve_kanji_contrast_groups(groups, by_char)
        self.assertEqual(resolved, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("無", warnings[0])

    def test_resolve_keeps_valid_groups(self) -> None:
        group = KanjiContrastGroup(
            kanji_chars=("次", "欠"),
            title="Next vs Lack",
            note="ice + lack",
        )
        by_char = {
            "次": mock_kanji("次", 616),
            "欠": mock_kanji("欠", 646, level=7),
        }
        resolved, warnings = resolve_kanji_contrast_groups([group], by_char)
        self.assertEqual(warnings, [])
        self.assertEqual(len(resolved), 1)
        self.assertEqual(group_display_title(group, resolved[0][1]), "Next vs Lack")
        self.assertEqual(
            [item["data"]["characters"] for item in resolved[0][1]],
            ["次", "欠"],
        )

    def test_group_note_guid_stable_when_kanji_list_changes(self) -> None:
        group = KanjiContrastGroup(
            kanji_chars=("未", "末", "夫", "禾"),
            title="Not yet vs end",
            group_id="not-yet-vs-end",
        )
        members_two = [mock_kanji("未", 1), mock_kanji("末", 2)]
        members_four = members_two + [mock_kanji("夫", 3), mock_kanji("禾", 4)]
        self.assertEqual(group_note_guid(group, members_two), group_note_guid(group, members_four))
        self.assertEqual(group_stable_key(group), "not-yet-vs-end")

    def test_load_default_groups_have_stable_ids(self) -> None:
        groups = load_kanji_contrast_groups()
        not_yet = next(g for g in groups if g.group_id == "not-yet-vs-end")
        self.assertEqual(not_yet.kanji_chars, ("未", "末", "夫", "禾"))

    def test_group_size_constants(self) -> None:
        self.assertEqual(MIN_KANJI_CONTRAST_GROUP_SIZE, 2)
        self.assertEqual(MAX_KANJI_CONTRAST_GROUP_SIZE, 6)

    def test_write_apkg_sets_note_mod_from_model_template(self) -> None:
        import sqlite3
        import zipfile

        import genanki

        model = make_kanji_contrast_model()
        deck = genanki.Deck(2059400133, "Kanji Contrast Mod Test")
        deck.add_note(
            genanki.Note(
                model=model,
                fields=["guid", "Title", "Prompt", "front", "back", "", "meta"],
                guid="kanji-contrast-mod-test",
            )
        )
        expected_mod = export_note_mod_timestamp([model])
        self.assertGreater(expected_mod, 1_921_500_000)

        with tempfile.TemporaryDirectory() as tmpdir:
            apkg_path = Path(tmpdir) / "test.apkg"
            write_apkg(deck, apkg_path)
            with zipfile.ZipFile(apkg_path) as archive:
                db_bytes = archive.read("collection.anki2")
            db_path = Path(tmpdir) / "collection.anki2"
            db_path.write_bytes(db_bytes)
            conn = sqlite3.connect(db_path)
            mods = [row[0] for row in conn.execute("SELECT mod FROM notes")]
            conn.close()
            self.assertEqual(mods, [expected_mod])


if __name__ == "__main__":
    unittest.main()
