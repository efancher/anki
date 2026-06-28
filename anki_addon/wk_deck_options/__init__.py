"""
WK Deck Options Setup

Assigns the WK FSRS deck-options preset to every WaniKani deck listed in
anki_deck_options.json from wk_decks.py output.

Install: copy this folder to Anki's add-ons directory, then restart Anki.
Tools → WK Apply Deck Options
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Optional

from anki.decks import DeckConfigId, DeckId
from aqt import gui_hooks, mw
from aqt.qt import QAction, QFileDialog
from aqt.utils import showInfo, showWarning, tooltip

ADDON_NAME = "WK Deck Options Setup"
DEFAULT_JSON_NAME = "anki_deck_options.json"


def candidate_json_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("WK_DECK_OPTIONS_JSON")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.extend(
        [
            Path.home() / "anki" / "out" / DEFAULT_JSON_NAME,
            Path.cwd() / "out" / DEFAULT_JSON_NAME,
            Path.cwd() / DEFAULT_JSON_NAME,
        ]
    )
    seen = set()
    unique: List[Path] = []
    for path in paths:
        key = str(path.expanduser().resolve()) if path.exists() else str(path.expanduser())
        if key not in seen:
            seen.add(key)
            unique.append(path.expanduser())
    return unique


def pick_json_path() -> Optional[Path]:
    for path in candidate_json_paths():
        if path.exists():
            return path

    start_dir = str(Path.home() / "anki" / "out")
    if not Path(start_dir).exists():
        start_dir = str(Path.home())

    selected, _ = QFileDialog.getOpenFileName(
        mw,
        "Select anki_deck_options.json",
        start_dir,
        "JSON Files (*.json)",
    )
    if not selected:
        return None
    return Path(selected)


def load_definitions(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return payload


def try_enable_fsrs(col: Any) -> Optional[str]:
    """Enable FSRS when possible; return a user-facing note if manual setup is needed."""
    try:
        if hasattr(col, "v3_scheduler") and hasattr(col, "set_v3_scheduler"):
            if col.v3_scheduler():
                return None
            if hasattr(col, "sched_ver") and col.sched_ver() != 2:
                if hasattr(col, "upgrade_to_v2_scheduler"):
                    col.upgrade_to_v2_scheduler()
                else:
                    return "Enable FSRS manually in Preferences → Review."
            col.set_v3_scheduler(True)
            return "Enabled FSRS scheduler for the collection."
    except Exception as exc:  # noqa: BLE001
        return f"Could not enable FSRS automatically ({exc}); enable it in Preferences → Review."

    if hasattr(col, "sched_ver") and hasattr(col, "set_scheduler"):
        try:
            from anki.collection import SchedulerVersion
        except ImportError:
            return None
        try:
            if col.sched_ver() != SchedulerVersion.V2:
                col.set_scheduler(SchedulerVersion.V2)
                return "Enabled FSRS scheduler for the collection."
        except Exception as exc:  # noqa: BLE001
            return f"Could not enable FSRS automatically ({exc}); enable it in Preferences → Review."
    return None


def _deck_id_for_name(decks: Any, name: str) -> Optional[int]:
    """Return deck id if it exists; do not create a new deck."""
    if hasattr(decks, "id_for_name"):
        deck_id = decks.id_for_name(name)
        return int(deck_id) if deck_id else None
    deck_id = decks.id(name, default=False)
    return int(deck_id) if deck_id else None


def _config_entry_name(entry: Any, decks: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("name") or "")
    conf = decks.get_config(entry)
    if isinstance(conf, dict):
        return str(conf.get("name") or "")
    return str(getattr(conf, "name", "") or "")


def _config_id_from_entry(entry: Any) -> DeckConfigId:
    if isinstance(entry, dict):
        return DeckConfigId(entry["id"])
    return DeckConfigId(entry)


def _apply_preset_fields(conf: Any, preset: dict) -> None:
    desired_retention = float(preset.get("desired_retention", 0.9))
    new_per_day = int(preset.get("new_per_day", 15))
    reviews_per_day = int(preset.get("reviews_per_day", 200))
    if isinstance(conf, dict):
        conf["desiredRetention"] = desired_retention
        conf.setdefault("new", {})["perDay"] = new_per_day
        conf.setdefault("rev", {})["perDay"] = reviews_per_day
        return
    conf.desired_retention = desired_retention
    conf.new_per_day = new_per_day
    conf.reviews_per_day = reviews_per_day


def _add_config_id(decks: Any, name: str) -> DeckConfigId:
    created = decks.add_config(name)
    if isinstance(created, dict):
        return DeckConfigId(created["id"])
    return DeckConfigId(created)


def _assign_deck_config(decks: Any, deck_id: int, conf_id: DeckConfigId) -> None:
    if hasattr(decks, "set_config_id_for_deck_dict"):
        deck = decks.get(deck_id)
        decks.set_config_id_for_deck_dict(deck, conf_id)
        return
    decks.set_deck_config_id(DeckId(deck_id), conf_id)


def upsert_preset(col: Any, preset: dict) -> DeckConfigId:
    name = str(preset.get("name") or "WK FSRS")
    decks = col.decks
    conf_id: Optional[DeckConfigId] = None
    for entry in decks.all_config():
        if _config_entry_name(entry, decks) == name:
            conf_id = _config_id_from_entry(entry)
            break
    if conf_id is None:
        conf_id = _add_config_id(decks, name)

    conf = decks.get_config(conf_id)
    _apply_preset_fields(conf, preset)
    decks.update_config(conf)
    return conf_id


def apply_deck_options() -> None:
    path = pick_json_path()
    if path is None:
        showWarning("No anki_deck_options.json selected.")
        return

    try:
        payload = load_definitions(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        showWarning(f"Could not read {path}:\n{exc}")
        return

    preset = payload.get("preset") or {}
    deck_names = payload.get("deck_names") or []
    if not isinstance(deck_names, list):
        showWarning(f"{path.name} must contain a 'deck_names' list.")
        return

    col = mw.col
    fsrs_note = try_enable_fsrs(col)
    conf_id = upsert_preset(col, preset)

    assigned = 0
    missing = 0
    lines: List[str] = []
    for deck_name in deck_names:
        deck_id = _deck_id_for_name(col.decks, str(deck_name))
        if not deck_id:
            missing += 1
            lines.append(f"missing deck: {deck_name}")
            continue
        _assign_deck_config(col.decks, deck_id, conf_id)
        assigned += 1
        lines.append(f"preset applied: {deck_name}")

    mw.reset()
    summary = (
        f"WK deck options from {path.name}: "
        f"{assigned} deck(s) assigned to {preset.get('name', 'WK FSRS')}."
    )
    if missing:
        summary += f" {missing} deck name(s) not found in this profile."
    if fsrs_note:
        summary += f"\n\n{fsrs_note}"
    tooltip(summary, period=8000)
    if lines:
        showInfo(summary + "\n\n" + "\n".join(lines))
    else:
        showWarning("No deck names were configured.")


def add_menu_action() -> None:
    action = QAction("WK Apply Deck Options", mw)
    action.triggered.connect(apply_deck_options)
    mw.form.menuTools.addAction(action)


gui_hooks.main_window_did_init.append(add_menu_action)
