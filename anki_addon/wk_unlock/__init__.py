"""
WK Unlock — unsuspend core and supplementary cards when prerequisites mature.

Install: copy this folder to Anki's add-ons directory, then restart Anki.
Tools → WK Run Unlock Pass
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from anki.notes import NoteId
from aqt import gui_hooks, mw
from aqt.qt import QAction
from aqt.utils import showInfo, showWarning, tooltip

from .logic import (
    ANKI_QUEUE_SUSPENDED,
    CardState,
    MiningHintState,
    MiningHintUpdate,
    NoteUnlockState,
    UnlockAction,
    WkUnlockConfig,
    build_mature_subject_ids,
    build_reviewed_once_subject_ids,
    mining_hint_updates_for_notes,
    parse_prerequisite_ids,
    supplementary_unlock_actions_for_notes,
    unlock_actions_for_notes,
)

ADDON_NAME = "WK Unlock"
DEFAULT_CONFIG_NAME = "wk_unlock_config.json"


def candidate_config_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("WK_UNLOCK_CONFIG")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.extend(
        [
            Path.home() / "anki" / "out" / DEFAULT_CONFIG_NAME,
            Path.cwd() / "out" / DEFAULT_CONFIG_NAME,
            Path.cwd() / DEFAULT_CONFIG_NAME,
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


def load_unlock_config() -> WkUnlockConfig:
    for path in candidate_config_paths():
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        return WkUnlockConfig(
            mature_min_interval_days=int(payload.get("mature_min_interval_days", 7)),
            mature_require_all_card_types=bool(payload.get("mature_require_all_card_types", True)),
            burned_interval_days=int(payload.get("burned_interval_days", 365)),
        )
    return WkUnlockConfig()


def _note_unlock_state(note) -> Optional[NoteUnlockState]:
    model = note.note_type()
    field_names = model["flds"]
    name_to_ord = {field["name"]: index for index, field in enumerate(field_names)}
    if "WkSubjectId" not in name_to_ord:
        return None

    def field_value(name: str) -> str:
        ord_index = name_to_ord.get(name)
        if ord_index is None:
            return ""
        return note.fields[ord_index] or ""

    subject_text = field_value("WkSubjectId").strip()
    if not subject_text:
        return None
    try:
        subject_id = int(subject_text)
    except ValueError:
        return None

    prereq_ids = parse_prerequisite_ids(field_value("PrerequisiteIds"))
    cards: List[CardState] = []
    for card_id in note.card_ids():
        card = mw.col.get_card(card_id)
        cards.append(
            CardState(
                ivl=int(card.ivl or 0),
                queue=int(card.queue),
                reps=int(card.reps or 0),
            )
        )

    return NoteUnlockState(
        note_id=int(note.id),
        wk_subject_id=subject_id,
        prerequisite_ids=prereq_ids,
        tags=tuple(note.tags),
        cards=tuple(cards),
    )


def collect_core_unlock_notes() -> List[NoteUnlockState]:
    notes: List[NoteUnlockState] = []
    for note in mw.col.find_notes("tag:wk-core"):
        model_note = mw.col.get_note(note)
        state = _note_unlock_state(model_note)
        if state is not None:
            notes.append(state)
    return notes


def collect_core_kanji_unlock_notes() -> List[NoteUnlockState]:
    notes: List[NoteUnlockState] = []
    for note in mw.col.find_notes("tag:wk-core tag:kanji"):
        model_note = mw.col.get_note(note)
        state = _note_unlock_state(model_note)
        if state is not None:
            notes.append(state)
    return notes


def collect_kanji_meaning_unlock_notes() -> List[NoteUnlockState]:
    notes: List[NoteUnlockState] = []
    for note in mw.col.find_notes("tag:kanji-meaning"):
        model_note = mw.col.get_note(note)
        state = _note_unlock_state(model_note)
        if state is not None:
            notes.append(state)
    return notes


MINING_NOTE_TYPE = "WK Yomitan Immersion"
FIELD_HINT_STAGE = "HintStage"
FIELD_SHOW_ENGLISH = "ShowEnglish"
FIELD_SHOW_KANA = "ShowKana"
FIELD_SHOW_JJ_BACK = "ShowJjBack"
FIELD_WK_SUBJECT_ID = "WkSubjectId"
FIELD_PREREQUISITE_IDS = "PrerequisiteIds"


def _mining_hint_state(note) -> Optional[MiningHintState]:
    model = note.note_type()
    if model["name"] != MINING_NOTE_TYPE:
        return None
    name_to_ord = {field["name"]: index for index, field in enumerate(model["flds"])}
    if FIELD_HINT_STAGE not in name_to_ord:
        return None

    def field_value(name: str) -> str:
        ord_index = name_to_ord.get(name)
        if ord_index is None:
            return ""
        return note.fields[ord_index] or ""

    subject_text = field_value(FIELD_WK_SUBJECT_ID).strip()
    subject_id: Optional[int] = None
    if subject_text:
        try:
            subject_id = int(subject_text)
        except ValueError:
            subject_id = None
    hint_text = field_value(FIELD_HINT_STAGE).strip()
    try:
        hint_stage = int(hint_text) if hint_text else 0
    except ValueError:
        hint_stage = 0
    return MiningHintState(
        note_id=int(note.id),
        wk_subject_id=subject_id,
        prerequisite_ids=parse_prerequisite_ids(field_value(FIELD_PREREQUISITE_IDS)),
        hint_stage=hint_stage,
    )


def collect_mining_hint_notes() -> List[MiningHintState]:
    notes: List[MiningHintState] = []
    for note_id in mw.col.find_notes("tag:yomitan-mining -tag:mining-setup"):
        model_note = mw.col.get_note(note_id)
        state = _mining_hint_state(model_note)
        if state is not None:
            notes.append(state)
    return notes


def apply_mining_hint_update(action: MiningHintUpdate) -> None:
    note = mw.col.get_note(NoteId(action.note_id))
    name_to_ord = {field["name"]: index for index, field in enumerate(note.note_type()["flds"])}
    updates = {
        FIELD_HINT_STAGE: action.hint_stage,
        FIELD_SHOW_ENGLISH: action.show_english,
        FIELD_SHOW_KANA: action.show_kana,
        FIELD_SHOW_JJ_BACK: action.show_jj_back,
    }
    changed = False
    for name, value in updates.items():
        ord_index = name_to_ord.get(name)
        if ord_index is None:
            continue
        if note.fields[ord_index] != value:
            note.fields[ord_index] = value
            changed = True
    if changed:
        mw.col.update_note(note)


def collect_supplementary_unlock_notes() -> List[NoteUnlockState]:
    notes: List[NoteUnlockState] = []
    for note in mw.col.find_notes("tag:wk-locked -tag:wk-core"):
        model_note = mw.col.get_note(note)
        state = _note_unlock_state(model_note)
        if state is not None:
            notes.append(state)
    return notes


def collect_unlock_notes() -> List[NoteUnlockState]:
    return collect_core_unlock_notes()


def apply_unlock_action(action: UnlockAction) -> None:
    note = mw.col.get_note(NoteId(action.note_id))
    tag_set = set(note.tags)
    for tag in action.remove_tags:
        tag_set.discard(tag)
    for tag in action.add_tags:
        tag_set.add(tag)
    note.tags = sorted(tag_set)
    mw.col.update_note(note)

    if not action.unsuspend:
        return
    for card_id in note.card_ids():
        card = mw.col.get_card(card_id)
        if card.queue == ANKI_QUEUE_SUSPENDED:
            card.queue = 0
            mw.col.update_card(card)


def run_unlock_pass(*, quiet: bool = False) -> Tuple[int, int]:
    if mw is None or mw.col is None:
        return 0, 0

    config = load_unlock_config()
    core_notes = collect_core_unlock_notes()
    core_kanji_notes = collect_core_kanji_unlock_notes()
    kanji_meaning_notes = collect_kanji_meaning_unlock_notes()
    supplementary_notes = collect_supplementary_unlock_notes()
    mature_ids = build_mature_subject_ids(core_notes, config=config)
    kanji_meaning_mature_ids = build_mature_subject_ids(kanji_meaning_notes, config=config)
    reviewed_once_ids = build_reviewed_once_subject_ids(core_kanji_notes) | build_reviewed_once_subject_ids(
        kanji_meaning_notes
    )
    actions = unlock_actions_for_notes(core_notes, config=config, mature_subject_ids=mature_ids)
    actions.extend(
        supplementary_unlock_actions_for_notes(
            supplementary_notes,
            core_mature_subject_ids=mature_ids,
            kanji_meaning_mature_subject_ids=kanji_meaning_mature_ids,
            core_reviewed_once_subject_ids=reviewed_once_ids,
        )
    )
    mining_notes = collect_mining_hint_notes()
    hint_updates = mining_hint_updates_for_notes(
        mining_notes,
        kanji_meaning_mature_subject_ids=kanji_meaning_mature_ids,
        core_mature_subject_ids=mature_ids,
    )
    unlocked = 0
    for action in actions:
        apply_unlock_action(action)
        if action.unsuspend:
            unlocked += 1
    hints_updated = 0
    for hint_update in hint_updates:
        apply_mining_hint_update(hint_update)
        hints_updated += 1
    if actions or hint_updates:
        mw.col.reset()
    if not quiet:
        if actions or hint_updates:
            tooltip(
                f"WK unlock: {unlocked} unsuspended, {len(actions)} notes updated; "
                f"{hints_updated} mining hint stages refreshed."
            )
        else:
            tooltip("WK unlock: no changes.")
    return unlocked, len(actions) + hints_updated


def on_collection_did_load(col) -> None:
    if col is None:
        return
    run_unlock_pass(quiet=True)


def on_reviewer_will_end(*_args) -> None:
    """Anki 25.09 calls reviewer_will_end hooks with no arguments."""
    run_unlock_pass(quiet=True)


def _register_reviewer_end_hook() -> None:
    if hasattr(gui_hooks, "reviewer_will_end"):
        gui_hooks.reviewer_will_end.append(on_reviewer_will_end)
    elif hasattr(gui_hooks, "reviewer_did_end"):
        gui_hooks.reviewer_did_end.append(lambda: run_unlock_pass(quiet=True))


def setup_menu() -> None:
    action = QAction("WK Run Unlock Pass", mw)
    action.triggered.connect(lambda: _menu_unlock_pass())
    mw.form.menuTools.addAction(action)


def _menu_unlock_pass() -> None:
    if mw is None or mw.col is None:
        showWarning("Open a collection first.")
        return
    unlocked, updated = run_unlock_pass(quiet=True)
    showInfo(f"WK unlock pass complete.\nUnsuspended: {unlocked}\nNotes updated: {updated}")


gui_hooks.collection_did_load.append(on_collection_did_load)
_register_reviewer_end_hook()
gui_hooks.main_window_did_init.append(setup_menu)
