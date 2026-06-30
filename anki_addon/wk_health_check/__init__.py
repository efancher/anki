"""
WK Health Check — sanity checks and scheduling stats for WK Anki collections.

Install: copy this folder to Anki's add-ons directory, then restart Anki.
Tools → WK Health Check
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from aqt import gui_hooks, mw
from aqt.qt import QAction
from aqt.utils import showText, showWarning

from .logic import (
    CORE_DECK_NAMES,
    CardSnapshot,
    DeckPresetInfo,
    FilteredDeckInfo,
    NoteSnapshot,
    build_health_report,
    format_health_report,
    snapshot_payload,
)

ADDON_NAME = "WK Health Check"
SNAPSHOT_FILENAME = "wk_health_snapshot.json"
STUDY_PRIORITY_JSON = "wk_study_priority.json"


def profile_snapshot_path() -> Path:
    return Path(mw.pm.profileFolder()) / SNAPSHOT_FILENAME


def candidate_study_priority_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("WK_STUDY_PRIORITY_JSON")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.extend(
        [
            Path.home() / "anki" / "out" / STUDY_PRIORITY_JSON,
            Path.cwd() / "out" / STUDY_PRIORITY_JSON,
            Path.cwd() / STUDY_PRIORITY_JSON,
        ]
    )
    seen = set()
    unique: List[Path] = []
    for path in paths:
        key = str(path.expanduser())
        if key not in seen:
            seen.add(key)
            unique.append(path.expanduser())
    return unique


def load_study_priority_info() -> tuple[Optional[str], int]:
    for path in candidate_study_priority_paths():
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        subjects = payload.get("subjects") or {}
        count = len(subjects) if isinstance(subjects, dict) else 0
        return str(path), count
    return None, 0


def load_previous_snapshot() -> Optional[dict]:
    path = profile_snapshot_path()
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def save_snapshot(payload: dict) -> None:
    path = profile_snapshot_path()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _home_deck_id(card) -> int:
    odid = int(getattr(card, "odid", 0) or 0)
    return odid if odid else int(card.did)


def _deck_name_for_card(col, card) -> str:
    return col.decks.name(_home_deck_id(card))


def _note_field_map(note) -> Dict[str, int]:
    model = note.note_type()
    return {field["name"]: index for index, field in enumerate(model["flds"])}


def _wk_subject_id_from_note(note) -> Optional[int]:
    field_map = _note_field_map(note)
    ord_index = field_map.get("WkSubjectId")
    if ord_index is None:
        return None
    text = (note.fields[ord_index] or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def gather_card_snapshots(col) -> List[CardSnapshot]:
    snapshots: List[CardSnapshot] = []
    scopes = [f'deck:"{name}"' for name in CORE_DECK_NAMES]
    scopes.append("tag:wk-core")
    seen: set[int] = set()
    for scope in scopes:
        for card_id in col.find_cards(scope):
            card_id = int(card_id)
            if card_id in seen:
                continue
            seen.add(card_id)
            card = col.get_card(card_id)
            home_id = _home_deck_id(card)
            queue_id = int(card.did)
            filtered_queue_name = None
            if home_id != queue_id:
                filtered_queue_name = col.decks.name(queue_id)
            snapshots.append(
                CardSnapshot(
                    card_id=card_id,
                    note_id=int(card.nid),
                    deck_name=_deck_name_for_card(col, card),
                    card_type=int(card.type),
                    queue=int(card.queue),
                    due=int(card.due),
                    ivl=int(card.ivl),
                    reps=int(card.reps),
                    lapses=int(card.lapses),
                    filtered_queue_deck_name=filtered_queue_name,
                )
            )
    return snapshots


def _card_ids_of_note(col, note_id: int) -> List[int]:
    if hasattr(col, "card_ids_of_note"):
        return [int(card_id) for card_id in col.card_ids_of_note(note_id)]
    return [int(card_id) for card_id in col.cards_of_note(note_id)]


def gather_core_note_snapshots(col) -> List[NoteSnapshot]:
    notes: List[NoteSnapshot] = []
    for note_id in col.find_notes("tag:wk-core"):
        note = col.get_note(note_id)
        card_ids = _card_ids_of_note(col, int(note.id))
        deck_name = ""
        if card_ids:
            deck_name = _deck_name_for_card(col, col.get_card(card_ids[0]))
        notes.append(
            NoteSnapshot(
                note_id=int(note.id),
                guid=str(note.guid),
                deck_name=deck_name,
                tags=tuple(str(tag) for tag in note.tags),
                wk_subject_id=_wk_subject_id_from_note(note),
            )
        )
    return notes


def gather_locked_note_count(col) -> int:
    return len(col.find_notes("tag:wk-locked"))


def gather_deck_presets(col) -> List[DeckPresetInfo]:
    presets: List[DeckPresetInfo] = []
    for deck_name in CORE_DECK_NAMES:
        deck_id = col.decks.id_for_name(deck_name)
        if not deck_id:
            continue
        deck = col.decks.get(deck_id)
        conf = col.decks.get_config(deck["conf"])
        presets.append(
            DeckPresetInfo(
                deck_name=deck_name,
                preset_name=str(conf.get("name") or ""),
            )
        )
    return presets


def gather_filtered_decks(col) -> List[FilteredDeckInfo]:
    decks: List[FilteredDeckInfo] = []
    for deck in col.decks.all_names_and_ids():
        name = str(deck.name)
        if not name.startswith("WK::"):
            continue
        deck_obj = col.decks.get(deck.id)
        if not deck_obj.get("dyn"):
            continue
        filtered = col.sched.get_or_create_filtered_deck(deck.id)
        card_count = len(col.find_cards(f'deck:"{name}"'))
        decks.append(
            FilteredDeckInfo(
                name=name,
                reschedule=bool(filtered.config.reschedule),
                card_count=card_count,
            )
        )
    return sorted(decks, key=lambda item: item.name)


def run_health_check(*, save_after: bool = True) -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return

    col = mw.col
    cards = gather_card_snapshots(col)
    notes = gather_core_note_snapshots(col)
    priority_path, priority_count = load_study_priority_info()
    previous = load_previous_snapshot()

    report = build_health_report(
        cards=cards,
        notes=notes,
        deck_presets=gather_deck_presets(col),
        filtered_decks=gather_filtered_decks(col),
        study_priority_path=priority_path,
        study_priority_subject_count=priority_count,
        collection_mod=int(col.mod) if col.mod is not None else None,
        locked_note_count=gather_locked_note_count(col),
        previous_snapshot=previous,
    )

    if save_after and report.metrics is not None:
        save_snapshot(snapshot_payload(report.metrics, generated_at=report.generated_at))

    showText(format_health_report(report), title=ADDON_NAME)


def add_menu_action() -> None:
    action = QAction("WK Health Check", mw)
    action.triggered.connect(lambda: run_health_check(save_after=True))
    mw.form.menuTools.addAction(action)


gui_hooks.main_window_did_init.append(add_menu_action)
