"""Smoke tests against Anki 25's bundled Python + collection APIs.

Run from repo root with Anki's venv (no GUI required):

  scripts/test_with_anki_python.sh

Or manually:

  ANKI_PYTHON="$HOME/Library/Application Support/AnkiProgramFiles/.venv/bin/python3.13"
  "$ANKI_PYTHON" -m pytest tests/test_anki25_collection_compat.py -q
"""

from __future__ import annotations

import inspect
import os
import shutil
import tempfile
import unittest

from anki.collection import Collection
from anki.decks import DeckConfigId, DeckManager


class Anki25CollectionCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.col = Collection(os.path.join(self._tmpdir, "test"))

    def tearDown(self) -> None:
        self.col.close()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_deck_id_lookup_uses_create_false_not_default(self) -> None:
        sig = inspect.signature(DeckManager.id)
        self.assertIn("create", sig.parameters)
        self.assertNotIn("default", sig.parameters)

        created = self.col.decks.id("WK::Smoke", create=True)
        self.assertIsNotNone(created)

        found = self.col.decks.id_for_name("WK::Smoke")
        self.assertEqual(int(found), int(created))

        missing = self.col.decks.id("WK::Missing", create=False)
        self.assertIsNone(missing)

    def test_all_config_returns_dicts(self) -> None:
        configs = self.col.decks.all_config()
        self.assertTrue(configs)
        self.assertIsInstance(configs[0], dict)
        self.assertIn("name", configs[0])

    def test_upsert_preset_flow_against_real_collection(self) -> None:
        import importlib.util
        import sys
        import types
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        addon_path = repo_root / "anki_addon" / "wk_deck_options" / "__init__.py"

        if "aqt" not in sys.modules:
            aqt = types.ModuleType("aqt")
            aqt.gui_hooks = types.SimpleNamespace(main_window_did_init=[])
            aqt.mw = None
            sys.modules["aqt"] = aqt
        for mod_name, attrs in (
            ("aqt.qt", {"QAction": object, "QFileDialog": object()}),
            ("aqt.utils", {"showInfo": lambda *a, **k: None, "showWarning": lambda *a, **k: None, "tooltip": lambda *a, **k: None}),
        ):
            if mod_name not in sys.modules:
                stub = types.ModuleType(mod_name.split(".")[-1] if "." in mod_name else mod_name)
                for key, val in attrs.items():
                    setattr(stub, key, val)
                sys.modules[mod_name] = stub

        spec = importlib.util.spec_from_file_location("wk_deck_options", addon_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        preset = {
            "name": "WK FSRS Smoke",
            "desired_retention": 0.91,
            "new_per_day": 12,
            "reviews_per_day": 180,
        }
        conf_id = module.upsert_preset(self.col, preset)
        conf = self.col.decks.get_config(DeckConfigId(int(conf_id)))
        assert conf is not None
        self.assertEqual(conf["name"], "WK FSRS Smoke")
        self.assertEqual(conf["desiredRetention"], 0.91)
        self.assertEqual(conf["new"]["perDay"], 12)
        self.assertEqual(conf["rev"]["perDay"], 180)

        self.col.decks.id("WK::Assign Target", create=True)
        deck_id = module._deck_id_for_name(self.col.decks, "WK::Assign Target")
        self.assertIsNotNone(deck_id)
        module._assign_deck_config(self.col.decks, int(deck_id), DeckConfigId(int(conf_id)))
        deck = self.col.decks.get(int(deck_id))
        self.assertEqual(int(deck["conf"]), int(conf_id))

    def test_try_enable_fsrs_on_anki25_does_not_warn_when_already_enabled(self) -> None:
        import importlib.util
        import sys
        import types
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        addon_path = repo_root / "anki_addon" / "wk_deck_options" / "__init__.py"

        if "aqt" not in sys.modules:
            aqt = types.ModuleType("aqt")
            aqt.gui_hooks = types.SimpleNamespace(main_window_did_init=[])
            aqt.mw = None
            sys.modules["aqt"] = aqt
        for mod_name, attrs in (
            ("aqt.qt", {"QAction": object, "QFileDialog": object()}),
            ("aqt.utils", {"showInfo": lambda *a, **k: None, "showWarning": lambda *a, **k: None, "tooltip": lambda *a, **k: None}),
        ):
            if mod_name not in sys.modules:
                stub = types.ModuleType(mod_name.split(".")[-1])
                for key, val in attrs.items():
                    setattr(stub, key, val)
                sys.modules[mod_name] = stub

        spec = importlib.util.spec_from_file_location("wk_deck_options", addon_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(self.col.v3_scheduler())
        self.assertIsNone(module.try_enable_fsrs(self.col))


if __name__ == "__main__":
    unittest.main()
