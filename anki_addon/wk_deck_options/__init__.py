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
    try:
        from anki.collection import SchedulerVersion
    except ImportError:
        return "Could not import SchedulerVersion; enable FSRS manually in Preferences → Review."

    if not hasattr(col, "sched_ver") or not hasattr(col, "set_scheduler"):
        return "This Anki build does not expose scheduler APIs; enable FSRS manually in Preferences → Review."

    try:
        if col.sched_ver() != SchedulerVersion.V2:
            col.set_scheduler(SchedulerVersion.V2)
            return "Enabled FSRS scheduler for the collection."
    except Exception as exc:  # noqa: BLE001
        return f"Could not enable FSRS automatically ({exc}); enable it in Preferences → Review."
    return None


def upsert_preset(col: Any, preset: dict) -> DeckConfigId:
    name = str(preset.get("name") or "WK FSRS")
    conf_id: Optional[DeckConfigId] = None
    for cid in col.decks.all_config():
        conf = col.decks.get_config(cid)
        if conf.name == name:
            conf_id = cid
            break
    if conf_id is None:
        conf_id = col.decks.add_config(name)

    conf = col.decks.get_config(conf_id)
    conf.desired_retention = float(preset.get("desired_retention", 0.9))
    conf.new_per_day = int(preset.get("new_per_day", 15))
    conf.reviews_per_day = int(preset.get("reviews_per_day", 200))
    col.decks.update_config(conf)
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
        deck_id = col.decks.id(str(deck_name), default=False)
        if not deck_id:
            missing += 1
            lines.append(f"missing deck: {deck_name}")
            continue
        col.decks.set_deck_config_id(DeckId(deck_id), conf_id)
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
