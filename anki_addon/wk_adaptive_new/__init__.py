"""
WK Adaptive New — scale daily new-card limits from review load.

Priority: radicals → kanji → vocabulary → supplementary.

Install: copy this folder to Anki's add-ons directory, then restart Anki.
Tools → WK Adjust New Limits
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from anki.decks import DeckConfigId
from aqt import gui_hooks, mw
from aqt.qt import QAction
from aqt.utils import showInfo, showWarning, tooltip

from .logic import (
    CORE_KANJI_DECK,
    CORE_RADICALS_DECK,
    CORE_VOCABULARY_DECK,
    DEFAULT_BASE_PRESET_NAME,
    TierAvailability,
    WkAdaptiveNewConfig,
    build_tier_plan,
    preset_name_for_suffix,
)

ADDON_NAME = "WK Adaptive New"
DEFAULT_CONFIG_NAME = "wk_adaptive_new_config.json"
DEFAULT_DECK_OPTIONS_JSON = "anki_deck_options.json"
SUPPLEMENTARY_PRESET_SUFFIX = "Supplementary"

TIER_SUFFIX_BY_DECK = {
    CORE_RADICALS_DECK: "Radicals",
    CORE_KANJI_DECK: "Kanji",
    CORE_VOCABULARY_DECK: "Vocabulary",
}


def candidate_config_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("WK_ADAPTIVE_NEW_CONFIG")
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


def candidate_deck_options_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("WK_DECK_OPTIONS_JSON")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.extend(
        [
            Path.home() / "anki" / "out" / DEFAULT_DECK_OPTIONS_JSON,
            Path.cwd() / "out" / DEFAULT_DECK_OPTIONS_JSON,
            Path.cwd() / DEFAULT_DECK_OPTIONS_JSON,
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


def load_adaptive_config() -> WkAdaptiveNewConfig:
    for path in candidate_config_paths():
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        core_tiers = payload.get("core_tiers")
        if core_tiers is not None and not isinstance(core_tiers, list):
            core_tiers = None
        return WkAdaptiveNewConfig(
            daily_workload_target=int(payload.get("daily_workload_target", 200)),
            max_new_total=int(payload.get("max_new_total", 15)),
            supplementary_max_new=int(payload.get("supplementary_max_new", 5)),
            base_preset_name=str(payload.get("base_preset_name", DEFAULT_BASE_PRESET_NAME)),
            review_count_scope=str(payload.get("review_count_scope", "tag:wk-core")),
            core_tiers=tuple(core_tiers) if core_tiers else WkAdaptiveNewConfig().core_tiers,
            auto_run_on_load=bool(payload.get("auto_run_on_load", True)),
        )
    return WkAdaptiveNewConfig()


def load_supplementary_deck_names() -> List[str]:
    for path in candidate_deck_options_paths():
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        deck_names = payload.get("deck_names") or []
        if not isinstance(deck_names, list):
            continue
        core = set(TIER_SUFFIX_BY_DECK)
        return sorted(str(name) for name in deck_names if str(name) not in core)
    return []


def _deck_id_for_name(decks: Any, name: str) -> Optional[int]:
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


def _find_config_id(decks: Any, name: str) -> Optional[DeckConfigId]:
    for entry in decks.all_config():
        if _config_entry_name(entry, decks) == name:
            return _config_id_from_entry(entry)
    return None


def _clone_config(base_conf: Any, new_name: str) -> Any:
    if isinstance(base_conf, dict):
        cloned = json.loads(json.dumps(base_conf))
        cloned["name"] = new_name
        cloned["id"] = 0
        return cloned
    raise TypeError("Unsupported deck config type")


def _set_new_per_day(conf: Any, value: int) -> None:
    if isinstance(conf, dict):
        conf.setdefault("new", {})["perDay"] = int(value)
        return
    conf.new_per_day = int(value)


def _assign_deck_config(decks: Any, deck_id: int, conf_id: DeckConfigId) -> None:
    if hasattr(decks, "set_config_id_for_deck_dict"):
        deck = decks.get(deck_id)
        decks.set_config_id_for_deck_dict(deck, conf_id)
        return
    from anki.decks import DeckId

    decks.set_deck_config_id(DeckId(deck_id), conf_id)


def ensure_tier_preset(decks: Any, base_conf: Any, suffix: str) -> DeckConfigId:
    preset_name = preset_name_for_suffix(
        base_conf.get("name") if isinstance(base_conf, dict) else getattr(base_conf, "name", DEFAULT_BASE_PRESET_NAME),
        suffix,
    )
    existing = _find_config_id(decks, preset_name)
    if existing is not None:
        return existing
    cloned = _clone_config(base_conf, preset_name)
    created = decks.add_config(preset_name)
    conf_id = DeckConfigId(created["id"]) if isinstance(created, dict) else DeckConfigId(created)
    conf = decks.get_config(conf_id)
    if isinstance(conf, dict):
        conf.update({key: value for key, value in cloned.items() if key != "id"})
        conf["name"] = preset_name
    _set_new_per_day(conf, 0)
    decks.update_config(conf)
    return conf_id


def count_review_load(col: Any, scope: str) -> int:
    """Due reviews + learning waiting today (excludes unserved new cards)."""
    return len(col.find_cards(f"{scope} is:due"))


def count_available_new(col: Any, deck_name: str) -> int:
    return len(col.find_cards(f'deck:"{deck_name}" is:new -is:suspended'))


def build_tier_availability(col: Any, config: WkAdaptiveNewConfig) -> List[TierAvailability]:
    tiers: List[TierAvailability] = []
    for deck_name in config.core_tiers:
        suffix = TIER_SUFFIX_BY_DECK.get(deck_name)
        if suffix is None:
            continue
        tiers.append(
            TierAvailability(
                deck_name=deck_name,
                preset_suffix=suffix,
                available_new=count_available_new(col, deck_name),
            )
        )

    supplementary_decks = load_supplementary_deck_names()
    if supplementary_decks:
        available = sum(count_available_new(col, deck_name) for deck_name in supplementary_decks)
        tiers.append(
            TierAvailability(
                deck_name="__supplementary__",
                preset_suffix=SUPPLEMENTARY_PRESET_SUFFIX,
                available_new=available,
            )
        )
    return tiers


def apply_allocations(
    col: Any,
    config: WkAdaptiveNewConfig,
    allocations: Mapping[str, int],
    supplementary_decks: Sequence[str],
) -> List[str]:
    decks = col.decks
    base_conf_id = _find_config_id(decks, config.base_preset_name)
    if base_conf_id is None:
        raise RuntimeError(f"Deck options preset not found: {config.base_preset_name}")
    base_conf = decks.get_config(base_conf_id)
    lines: List[str] = []

    for deck_name in config.core_tiers:
        suffix = TIER_SUFFIX_BY_DECK.get(deck_name)
        if suffix is None:
            continue
        deck_id = _deck_id_for_name(decks, deck_name)
        if not deck_id:
            continue
        conf_id = ensure_tier_preset(decks, base_conf, suffix)
        conf = decks.get_config(conf_id)
        new_limit = int(allocations.get(deck_name, 0))
        _set_new_per_day(conf, new_limit)
        decks.update_config(conf)
        _assign_deck_config(decks, deck_id, conf_id)
        lines.append(f"{deck_name}: new/day={new_limit}")

    if supplementary_decks and "__supplementary__" in allocations:
        conf_id = ensure_tier_preset(decks, base_conf, SUPPLEMENTARY_PRESET_SUFFIX)
        conf = decks.get_config(conf_id)
        new_limit = int(allocations["__supplementary__"])
        _set_new_per_day(conf, new_limit)
        decks.update_config(conf)
        for deck_name in supplementary_decks:
            deck_id = _deck_id_for_name(decks, deck_name)
            if not deck_id:
                continue
            _assign_deck_config(decks, deck_id, conf_id)
        lines.append(f"Supplementary ({len(supplementary_decks)} decks): new/day={new_limit}")

    return lines


def adjust_new_limits(*, quiet: bool = False) -> Tuple[int, List[str]]:
    if mw is None or mw.col is None:
        return 0, []

    config = load_adaptive_config()
    col = mw.col
    review_load = count_review_load(col, config.review_count_scope)
    tiers = build_tier_availability(col, config)
    budget, allocations = build_tier_plan(review_load, tiers, config=config)
    supplementary_decks = load_supplementary_deck_names()
    lines = apply_allocations(col, config, allocations, supplementary_decks)
    summary_lines = [
        f"Review load ({config.review_count_scope}): {review_load}",
        f"New budget: {budget}",
        *lines,
    ]
    if not quiet:
        tooltip(f"WK adaptive new: budget {budget} (reviews {review_load})", period=6000)
    return budget, summary_lines


def on_collection_did_load(col) -> None:
    if col is None:
        return
    config = load_adaptive_config()
    if not config.auto_run_on_load:
        return
    try:
        adjust_new_limits(quiet=True)
    except Exception as exc:  # noqa: BLE001 — do not block collection open
        print(f"WK adaptive new: skipped on load ({exc})")


def setup_menu() -> None:
    action = QAction("WK Adjust New Limits", mw)
    action.triggered.connect(_menu_adjust)
    mw.form.menuTools.addAction(action)


def _menu_adjust() -> None:
    if mw is None or mw.col is None:
        showWarning("Open a collection first.")
        return
    try:
        budget, lines = adjust_new_limits(quiet=True)
    except RuntimeError as exc:
        showWarning(str(exc))
        return
    showInfo("WK adaptive new limits updated.\n\n" + "\n".join(lines))


gui_hooks.collection_did_load.append(on_collection_did_load)
gui_hooks.main_window_did_init.append(setup_menu)
