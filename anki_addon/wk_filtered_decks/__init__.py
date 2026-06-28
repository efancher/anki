"""
WK Filtered Deck Setup

Creates or rebuilds filtered decks defined in anki_filtered_decks.json from wk_decks.py.

Install: copy this folder to Anki's add-ons directory, then restart Anki.
Tools → WK Setup Filtered Decks
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Optional, Sequence

from anki.decks import DeckId, FilteredDeckConfig
from aqt import gui_hooks, mw
from aqt.qt import QAction, QFileDialog
from aqt.utils import showInfo, showWarning, tooltip

ADDON_NAME = "WK Filtered Deck Setup"
DEFAULT_JSON_NAME = "anki_filtered_decks.json"


def candidate_json_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("WK_FILTERED_DECKS_JSON")
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
        resolved = str(path.expanduser().resolve()) if path.exists() else str(path.expanduser())
        if resolved not in seen:
            seen.add(resolved)
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
        "Select anki_filtered_decks.json",
        start_dir,
        "JSON Files (*.json)",
    )
    if not selected:
        return None
    return Path(selected)


def load_definitions(path: Path) -> List[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    decks = payload.get("decks")
    if not isinstance(decks, list):
        raise ValueError(f"{path.name} must contain a top-level 'decks' list.")
    return decks


def _deck_id_for_name(decks: Any, name: str) -> Optional[int]:
    if hasattr(decks, "id_for_name"):
        deck_id = decks.id_for_name(name)
        return int(deck_id) if deck_id else None
    deck_id = decks.id(name, default=False)
    return int(deck_id) if deck_id else None


def apply_search_terms(deck_config: Any, spec: dict) -> None:
    del deck_config.search_terms[:]
    term = FilteredDeckConfig.SearchTerm(
        search=str(spec["search"]),
        limit=int(spec.get("limit", 20)),
        order=int(spec.get("order", 10)),
    )
    deck_config.search_terms.append(term)


def upsert_filtered_deck(spec: dict) -> tuple[str, int]:
    col = mw.col
    name = str(spec["name"])
    existing_id = _deck_id_for_name(col.decks, name)
    if existing_id:
        deck = col.sched.get_or_create_filtered_deck(DeckId(existing_id))
        action = "rebuilt"
    else:
        deck = col.sched.get_or_create_filtered_deck(DeckId(0))
        deck.name = name
        action = "created"

    deck.allow_empty = True
    deck.config.reschedule = bool(spec.get("reschedule", True))
    apply_search_terms(deck.config, spec)

    changes = col.sched.add_or_update_filtered_deck(deck)
    col.sched.rebuild_filtered_deck(DeckId(changes.id))
    return action, int(changes.id)


def setup_filtered_decks() -> None:
    path = pick_json_path()
    if path is None:
        showWarning("No anki_filtered_decks.json selected.")
        return

    try:
        definitions = load_definitions(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        showWarning(f"Could not read {path}:\n{exc}")
        return

    created = 0
    rebuilt = 0
    lines: List[str] = []
    for spec in definitions:
        try:
            action, deck_id = upsert_filtered_deck(spec)
        except Exception as exc:  # noqa: BLE001 - show user-facing Anki errors
            lines.append(f"FAILED {spec.get('name', '?')}: {exc}")
            continue
        if action == "created":
            created += 1
        else:
            rebuilt += 1
        lines.append(f"{action}: {spec.get('name')} (id {deck_id})")

    mw.reset()
    summary = f"WK filtered decks from {path.name}: {created} created, {rebuilt} rebuilt."
    tooltip(summary, period=8000)
    if lines:
        showInfo(summary + "\n\n" + "\n".join(lines))
    else:
        showWarning("No filtered decks were configured.")


def add_menu_action() -> None:
    action = QAction("WK Setup Filtered Decks", mw)
    action.triggered.connect(setup_filtered_decks)
    mw.form.menuTools.addAction(action)


gui_hooks.main_window_did_init.append(add_menu_action)
