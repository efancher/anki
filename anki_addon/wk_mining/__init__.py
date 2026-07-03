"""
WK Mining — link Yomitan-mined notes to WK subjects and apply unlock gating.

Tools → WK Link Mining Notes
Tools → WK Mining Duplicate Report
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from aqt import gui_hooks, mw
from aqt.qt import QAction
from aqt.utils import showInfo, showWarning, tooltip

from .logic import (
    ANKI_QUEUE_SUSPENDED,
    CardState,
    MINING_NOTE_TYPE,
    MINING_TAG,
    NoteUnlockState,
    WK_LOCKED_TAG,
    build_mature_subject_ids,
    duplicate_sentence_keys,
    link_mining_note_fields,
    load_vocab_lookup,
)

ADDON_NAME = "WK Mining"


def _field_map(note) -> Dict[str, int]:
    return {field["name"]: index for index, field in enumerate(note.note_type()["flds"])}


def _note_fields(note) -> Dict[str, str]:
    names = [field["name"] for field in note.note_type()["flds"]]
    return {name: note.fields[index] or "" for index, name in enumerate(names)}


def _core_mature_subject_ids() -> Set[int]:
    notes: List[NoteUnlockState] = []
    for note_id in mw.col.find_notes("tag:wk-core"):
        note = mw.col.get_note(note_id)
        model = note.note_type()
        name_to_ord = {field["name"]: index for index, field in enumerate(model["flds"])}
        if "WkSubjectId" not in name_to_ord:
            continue
        raw_id = note.fields[name_to_ord["WkSubjectId"]].strip()
        if not raw_id.isdigit():
            continue
        cards = []
        for card_id in note.card_ids():
            card = mw.col.get_card(card_id)
            cards.append(CardState(ivl=int(card.ivl or 0), queue=int(card.queue)))
        notes.append(
            NoteUnlockState(
                note_id=int(note_id),
                wk_subject_id=int(raw_id),
                tags=tuple(note.tags),
                cards=tuple(cards),
            )
        )
    return build_mature_subject_ids(notes)


def _lookup_path_override() -> Optional[Path]:
    env_path = os.environ.get("WK_VOCAB_LOOKUP")
    if env_path:
        return Path(env_path).expanduser()
    return None


def link_mining_notes(*, silent: bool = False) -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    lookup = load_vocab_lookup(_lookup_path_override())
    if not lookup:
        showWarning(
            "wk_vocab_lookup.json not found. Run wk_decks.py --from-config first "
            "(writes out/wk_vocab_lookup.json)."
        )
        return

    mature_ids = _core_mature_subject_ids()
    note_ids = mw.col.find_notes(f'note:"{MINING_NOTE_TYPE}"')
    linked = 0
    locked = 0
    unlocked = 0

    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        fields = _note_fields(note)
        updates, add_tags, remove_tags = link_mining_note_fields(fields, lookup, mature_ids)
        changed = False
        field_map = _field_map(note)
        for name, value in updates.items():
            ord_index = field_map.get(name)
            if ord_index is None:
                continue
            if note.fields[ord_index] != value:
                note.fields[ord_index] = value
                changed = True
                linked += 1
        tag_set = set(note.tags)
        for tag in add_tags:
            if tag not in tag_set:
                note.add_tag(tag)
                changed = True
                if tag == WK_LOCKED_TAG:
                    locked += 1
        for tag in remove_tags:
            if tag in tag_set:
                note.remove_tag(tag)
                changed = True
                if tag == WK_LOCKED_TAG:
                    unlocked += 1
        if MINING_TAG not in tag_set:
            note.add_tag(MINING_TAG)
            changed = True
        if changed:
            mw.col.update_note(note)
            for card_id in note.card_ids():
                card = mw.col.get_card(card_id)
                if WK_LOCKED_TAG in note.tags and card.queue != ANKI_QUEUE_SUSPENDED:
                    card.queue = ANKI_QUEUE_SUSPENDED
                    card.type = 0
                    card.ivl = 0
                    card.due = 0
                    card.flush()
                elif WK_LOCKED_TAG not in note.tags and card.queue == ANKI_QUEUE_SUSPENDED:
                    card.queue = 0
                    card.type = 0
                    card.due = 0
                    card.flush()

    mw.col.save()
    message = (
        f"Linked {linked} WkSubjectId field(s); "
        f"locked {locked}, unlocked {unlocked} (of {len(note_ids)} mining notes)."
    )
    if silent:
        tooltip(message)
    else:
        showInfo(message)


def mining_duplicate_report() -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    note_ids = mw.col.find_notes(f'note:"{MINING_NOTE_TYPE}"')
    field_rows = [_note_fields(mw.col.get_note(note_id)) for note_id in note_ids]
    dupes = duplicate_sentence_keys(field_rows)
    if not dupes:
        showInfo(f"No duplicate sentences among {len(note_ids)} mining notes.")
        return
    lines = [f"Duplicate sentences in mining deck ({len(dupes)} groups):"]
    for sentence, keys in sorted(dupes.items(), key=lambda item: len(item[1]), reverse=True)[:20]:
        preview = sentence if len(sentence) <= 40 else f"{sentence[:40]}…"
        lines.append(f"  · {preview} ({len(keys)} notes)")
    if len(dupes) > 20:
        lines.append(f"  … and {len(dupes) - 20} more groups")
    showInfo("\n".join(lines))


def on_cards_added(cards) -> None:
    note_ids = {int(card.nid) for card in cards}
    mining_ids = []
    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        if note.note_type()["name"] == MINING_NOTE_TYPE:
            mining_ids.append(note_id)
    if mining_ids:
        link_mining_notes(silent=True)


def setup_menu() -> None:
    action_link = QAction("WK Link Mining Notes", mw)
    action_link.triggered.connect(lambda: link_mining_notes(silent=False))
    mw.form.menuTools.addAction(action_link)

    action_dupes = QAction("WK Mining Duplicate Report", mw)
    action_dupes.triggered.connect(mining_duplicate_report)
    mw.form.menuTools.addAction(action_dupes)


gui_hooks.add_cards.append(on_cards_added)
setup_menu()
