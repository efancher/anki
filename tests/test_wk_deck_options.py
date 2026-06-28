"""Tests for wk_deck_options Anki 25 deck-config helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "anki_addon" / "wk_deck_options"


def _load_wk_deck_options_module():
    if "aqt" not in sys.modules:
        aqt = types.ModuleType("aqt")
        aqt.gui_hooks = types.SimpleNamespace(main_window_did_init=[])
        aqt.mw = MagicMock()
        sys.modules["aqt"] = aqt
    if "aqt.qt" not in sys.modules:
        qt = types.ModuleType("aqt.qt")
        qt.QAction = MagicMock
        qt.QFileDialog = MagicMock()
        sys.modules["aqt.qt"] = qt
    if "aqt.utils" not in sys.modules:
        utils = types.ModuleType("aqt.utils")
        utils.showInfo = MagicMock()
        utils.showWarning = MagicMock()
        utils.tooltip = MagicMock()
        sys.modules["aqt.utils"] = utils

    anki_decks = types.ModuleType("anki.decks")
    anki_decks.DeckConfigId = int
    anki_decks.DeckId = int
    sys.modules["anki.decks"] = anki_decks

    spec = importlib.util.spec_from_file_location("wk_deck_options", ADDON_DIR / "__init__.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wk_deck_options = _load_wk_deck_options_module()


class MockDecks:
    def __init__(self, configs: list[dict[str, Any]]) -> None:
        self._configs = configs
        self.updated: list[dict[str, Any]] = []
        self.assigned: list[tuple[dict[str, Any], int]] = []

    def all_config(self) -> list[dict[str, Any]]:
        return list(self._configs)

    def get_config(self, conf_id: int) -> dict[str, Any]:
        for conf in self._configs:
            if conf["id"] == conf_id:
                return conf
        raise KeyError(conf_id)

    def add_config(self, name: str) -> dict[str, Any]:
        conf = {
            "id": max((c["id"] for c in self._configs), default=0) + 1,
            "name": name,
            "desiredRetention": 0.9,
            "new": {"perDay": 20},
            "rev": {"perDay": 200},
        }
        self._configs.append(conf)
        return conf

    def update_config(self, conf: dict[str, Any]) -> None:
        self.updated.append(conf)

    def get(self, deck_id: int) -> dict[str, Any]:
        return {"id": deck_id, "name": f"Deck {deck_id}", "conf": 1}

    def set_config_id_for_deck_dict(self, deck: dict[str, Any], conf_id: int) -> None:
        deck["conf"] = conf_id
        self.assigned.append((deck, conf_id))


class WkDeckOptionsTests(unittest.TestCase):
    def test_upsert_preset_updates_existing_config_dict(self) -> None:
        decks = MockDecks(
            [
                {
                    "id": 2059400100,
                    "name": "WK FSRS",
                    "desiredRetention": 0.85,
                    "new": {"perDay": 10},
                    "rev": {"perDay": 100},
                }
            ]
        )
        col = types.SimpleNamespace(decks=decks)
        preset = {
            "name": "WK FSRS",
            "desired_retention": 0.9,
            "new_per_day": 15,
            "reviews_per_day": 200,
        }

        conf_id = wk_deck_options.upsert_preset(col, preset)

        self.assertEqual(conf_id, 2059400100)
        self.assertEqual(len(decks.updated), 1)
        updated = decks.updated[0]
        self.assertEqual(updated["desiredRetention"], 0.9)
        self.assertEqual(updated["new"]["perDay"], 15)
        self.assertEqual(updated["rev"]["perDay"], 200)

    def test_upsert_preset_creates_config_when_missing(self) -> None:
        decks = MockDecks([{"id": 1, "name": "Default", "new": {"perDay": 20}, "rev": {"perDay": 200}}])
        col = types.SimpleNamespace(decks=decks)
        preset = {"name": "WK FSRS", "desired_retention": 0.9, "new_per_day": 15, "reviews_per_day": 200}

        conf_id = wk_deck_options.upsert_preset(col, preset)

        self.assertEqual(conf_id, 2)
        self.assertEqual(decks.get_config(conf_id)["name"], "WK FSRS")

    def test_assign_deck_config_uses_set_config_id_for_deck_dict(self) -> None:
        decks = MockDecks([])
        deck = {"id": 42, "name": "WK::Vocab", "conf": 1}
        decks.get = MagicMock(return_value=deck)

        wk_deck_options._assign_deck_config(decks, 42, 2059400100)

        decks.get.assert_called_once_with(42)
        self.assertEqual(deck["conf"], 2059400100)
        self.assertEqual(decks.assigned, [(deck, 2059400100)])

    def test_deck_id_for_name_prefers_id_for_name(self) -> None:
        decks = MagicMock()
        decks.id_for_name.return_value = 99
        self.assertEqual(wk_deck_options._deck_id_for_name(decks, "WK::Vocab"), 99)
        decks.id_for_name.assert_called_once_with("WK::Vocab")
        decks.id.assert_not_called()

    def test_deck_id_for_name_falls_back_to_legacy_default_kwarg(self) -> None:
        class LegacyDecks:
            def id(self, name: str, *, default: bool = True) -> int:
                self.last_call = (name, default)
                return 55

        decks = LegacyDecks()
        self.assertEqual(wk_deck_options._deck_id_for_name(decks, "WK::Vocab"), 55)
        self.assertEqual(decks.last_call, ("WK::Vocab", False))


if __name__ == "__main__":
    unittest.main()
