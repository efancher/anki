"""
WK Tae Kim Track — sync grammar vocab/prereq tags from profile lesson cap.

Install: copy this folder to Anki's add-ons directory, then restart Anki.
Tools → WK Sync Tae Kim Track
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from anki.decks import DeckId, FilteredDeckConfig
from aqt import gui_hooks, mw
from aqt.qt import QAction, QFileDialog
from aqt.utils import showInfo, showWarning, tooltip

from .logic import (
    TaeKimTrackConfig,
    TrackTagAction,
    bump_lesson_slug,
    current_lesson_filtered_searches,
    parse_track_config,
    track_tag_actions_for_notes,
)

ADDON_NAME = "WK Tae Kim Track"
TRACK_MAP_FILENAME = "wk_tae_kim_track_map.json"
TRACK_CONFIG_FILENAME = "wk_tae_kim_track.json"
TEMPLATE_CONFIG_FILENAME = "wk_tae_kim_track_config.json"
FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS = 10


def profile_config_path() -> Path:
    return Path(mw.pm.profileFolder()) / TRACK_CONFIG_FILENAME


def profile_map_pointer_path() -> Path:
    return Path(mw.pm.profileFolder()) / "wk_tae_kim_track_map_path.txt"


def profile_template_pointer_path() -> Path:
    return Path(mw.pm.profileFolder()) / "wk_tae_kim_track_config_path.txt"


def _read_saved_path(pointer_path: Path) -> Optional[Path]:
    if not pointer_path.is_file():
        return None
    text = pointer_path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return Path(text).expanduser()


def _save_path_pointer(pointer_path: Path, target: Path) -> None:
    pointer_path.write_text(str(target.expanduser().resolve()), encoding="utf-8")


def candidate_map_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("WK_TAE_KIM_TRACK_MAP")
    if env_path:
        paths.append(Path(env_path).expanduser())
    saved = _read_saved_path(profile_map_pointer_path())
    if saved is not None:
        paths.append(saved)
    paths.extend(
        [
            Path(mw.pm.profileFolder()) / TRACK_MAP_FILENAME,
            Path.home() / "anki" / "out" / TRACK_MAP_FILENAME,
            Path.cwd() / "out" / TRACK_MAP_FILENAME,
            Path.cwd() / TRACK_MAP_FILENAME,
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


def candidate_template_config_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("WK_TAE_KIM_TRACK_CONFIG")
    if env_path:
        paths.append(Path(env_path).expanduser())
    saved = _read_saved_path(profile_template_pointer_path())
    if saved is not None:
        paths.append(saved)
    paths.extend(
        [
            Path(mw.pm.profileFolder()) / TEMPLATE_CONFIG_FILENAME,
            Path.home() / "anki" / "out" / TEMPLATE_CONFIG_FILENAME,
            Path.cwd() / "out" / TEMPLATE_CONFIG_FILENAME,
            Path.cwd() / TEMPLATE_CONFIG_FILENAME,
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


def pick_track_map_path(*, prompt: bool = True) -> Optional[Path]:
    for path in candidate_map_paths():
        if path.is_file():
            return path

    if not prompt:
        return None

    start_dir = str(Path.home() / "anki" / "out")
    if not Path(start_dir).exists():
        start_dir = str(Path.home())

    selected, _ = QFileDialog.getOpenFileName(
        mw,
        f"Select {TRACK_MAP_FILENAME}",
        start_dir,
        "JSON Files (*.json)",
    )
    if not selected:
        return None
    chosen = Path(selected)
    if chosen.is_file():
        _save_path_pointer(profile_map_pointer_path(), chosen)
    return chosen


def load_track_map(*, prompt: bool = True) -> Optional[dict]:
    path = pick_track_map_path(prompt=prompt)
    if path is None or not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def load_track_config(*, create_from_template: bool = True) -> Optional[TaeKimTrackConfig]:
    profile_path = profile_config_path()
    if profile_path.is_file():
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return parse_track_config(payload)

    if not create_from_template:
        return None

    for path in candidate_template_config_paths():
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        config = parse_track_config(payload)
        if config is None:
            continue
        profile_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return config

    start_dir = str(Path.home() / "anki" / "out")
    if not Path(start_dir).exists():
        start_dir = str(Path.home())
    selected, _ = QFileDialog.getOpenFileName(
        mw,
        f"Select {TEMPLATE_CONFIG_FILENAME}",
        start_dir,
        "JSON Files (*.json)",
    )
    if not selected:
        return None
    chosen = Path(selected)
    if not chosen.is_file():
        return None
    _save_path_pointer(profile_template_pointer_path(), chosen)
    payload = json.loads(chosen.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    config = parse_track_config(payload)
    if config is None:
        return None
    profile_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def save_track_config(config: TaeKimTrackConfig) -> None:
    payload = {
        "max_tae_kim_lesson": config.max_tae_kim_lesson,
        "ahead_prereq_lessons": config.ahead_prereq_lessons,
        "auto_run_on_load": config.auto_run_on_load,
        "auto_update_filtered_decks": config.auto_update_filtered_decks,
    }
    profile_config_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _wk_subject_id_from_note(note) -> Optional[int]:
    model = note.note_type()
    name_to_ord = {field["name"]: index for index, field in enumerate(model["flds"])}
    ord_index = name_to_ord.get("WkSubjectId")
    if ord_index is None:
        return None
    text = (note.fields[ord_index] or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def gather_core_note_states(col) -> List:
    from .logic import CoreNoteTrackState

    notes: List[CoreNoteTrackState] = []
    for note_id in col.find_notes("tag:wk-core"):
        note = col.get_note(note_id)
        notes.append(
            CoreNoteTrackState(
                note_id=int(note.id),
                wk_subject_id=_wk_subject_id_from_note(note),
                tags=tuple(str(tag) for tag in note.tags),
            )
        )
    return notes


def apply_track_actions(col, actions: List[TrackTagAction]) -> int:
    changed = 0
    for action in actions:
        note = col.get_note(action.note_id)
        tag_set = set(note.tags)
        for tag in action.remove_tags:
            tag_set.discard(tag)
        for tag in action.add_tags:
            tag_set.add(tag)
        new_tags = sorted(tag_set)
        if list(note.tags) != new_tags:
            note.tags = new_tags
            col.update_note(note)
            changed += 1
    return changed


def _deck_id_for_name(decks, name: str) -> Optional[int]:
    if hasattr(decks, "id_for_name"):
        deck_id = decks.id_for_name(name)
        return int(deck_id) if deck_id else None
    deck_id = decks.id(name, default=False)
    return int(deck_id) if deck_id else None


def update_current_lesson_filtered_decks(config: TaeKimTrackConfig) -> List[str]:
    col = mw.col
    searches = current_lesson_filtered_searches(config.max_tae_kim_lesson)
    lines: List[str] = []
    for deck_name, search in searches.items():
        existing_id = _deck_id_for_name(col.decks, deck_name)
        if existing_id:
            deck = col.sched.get_or_create_filtered_deck(DeckId(existing_id))
        else:
            deck = col.sched.get_or_create_filtered_deck(DeckId(0))
            deck.name = deck_name
        deck.allow_empty = True
        deck.config.reschedule = True
        del deck.config.search_terms[:]
        deck.config.search_terms.append(
            FilteredDeckConfig.SearchTerm(
                search=search,
                limit=20,
                order=FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
            )
        )
        changes = col.sched.add_or_update_filtered_deck(deck)
        col.sched.rebuild_filtered_deck(DeckId(changes.id))
        lines.append(f"{deck_name}: {search}")
    return lines


def run_tae_kim_track_sync(*, quiet: bool = False, update_filtered: Optional[bool] = None) -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return

    track_map = load_track_map()
    if track_map is None:
        showWarning(
            f"Could not find {TRACK_MAP_FILENAME}. "
            "Run python wk_decks.py --from-config first."
        )
        return

    config = load_track_config(create_from_template=True)
    if config is None:
        showWarning(
            f"Set max_tae_kim_lesson in {profile_config_path()} "
            f"or copy {TEMPLATE_CONFIG_FILENAME} from out/."
        )
        return

    notes = gather_core_note_states(mw.col)
    actions = track_tag_actions_for_notes(notes, track_map, config)
    changed = apply_track_actions(mw.col, actions)

    filtered_lines: List[str] = []
    should_update_filtered = (
        config.auto_update_filtered_decks if update_filtered is None else update_filtered
    )
    if should_update_filtered:
        filtered_lines = update_current_lesson_filtered_decks(config)

    summary = (
        f"Tae Kim track: {config.max_tae_kim_lesson} "
        f"(+{config.ahead_prereq_lessons} ahead prereq) — "
        f"{changed} notes updated, {len(actions)} tag actions."
    )
    if quiet:
        tooltip(summary, period=6000)
        return

    detail = [summary]
    if filtered_lines:
        detail.append("")
        detail.append("Filtered decks updated:")
        detail.extend(filtered_lines)
    showInfo("\n".join(detail), title=ADDON_NAME)


def bump_tae_kim_lesson() -> None:
    track_map = load_track_map()
    if track_map is None:
        showWarning(f"Missing {TRACK_MAP_FILENAME}. Regenerate decks first.")
        return
    config = load_track_config(create_from_template=True)
    if config is None:
        showWarning("No Tae Kim track config found.")
        return
    next_slug = bump_lesson_slug(track_map, config.max_tae_kim_lesson)
    if next_slug is None:
        showInfo("Already at the last reading lesson in the track map.", title=ADDON_NAME)
        return
    config = TaeKimTrackConfig(
        max_tae_kim_lesson=next_slug,
        ahead_prereq_lessons=config.ahead_prereq_lessons,
        auto_run_on_load=config.auto_run_on_load,
        auto_update_filtered_decks=config.auto_update_filtered_decks,
    )
    save_track_config(config)
    run_tae_kim_track_sync(quiet=False, update_filtered=True)


def on_collection_did_load(col) -> None:
    config = load_track_config(create_from_template=False)
    if config is None or not config.auto_run_on_load:
        return
    if load_track_map(prompt=False) is None:
        return
    run_tae_kim_track_sync(quiet=True)


def add_menu_actions() -> None:
    sync_action = QAction("WK Sync Tae Kim Track", mw)
    sync_action.triggered.connect(lambda: run_tae_kim_track_sync(quiet=False))
    mw.form.menuTools.addAction(sync_action)

    bump_action = QAction("WK Bump Tae Kim Lesson", mw)
    bump_action.triggered.connect(bump_tae_kim_lesson)
    mw.form.menuTools.addAction(bump_action)


gui_hooks.main_window_did_init.append(add_menu_actions)
gui_hooks.collection_did_load.append(on_collection_did_load)
