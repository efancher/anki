"""
WK Adaptive New — scale daily new-card limits from review load.

Priority: radicals → kanji → vocabulary → supplementary.

Install: copy this folder to Anki's add-ons directory, then restart Anki.
Tools → WK Adjust New Limits
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from anki.decks import DeckConfigId
from aqt import gui_hooks, mw
from aqt.qt import QAction
from aqt.utils import showInfo, showWarning, tooltip

from .logic import (
    CORE_KANJI_DECK,
    CORE_RADICALS_DECK,
    CORE_VOCABULARY_DECK,
    DEFAULT_BASE_PRESET_NAME,
    DEFAULT_IMMERSION_PRIORITY_ENABLED,
    DEFAULT_IMMERSION_TAG,
    DEFAULT_IMMERSION_TAGS,
    DEFAULT_IMMERSION_UNSUSPEND_ENABLED,
    IMMERSION_CORE_FILTERED_DECKS,
    IMMERSION_CORE_FILTERED_LIMIT,
    IMMERSION_CORE_SOURCE_SPECS,
    IMMERSION_CORE_TAG_CANDIDATES,
    IMMERSION_CORE_TAG_SATORI,
    IMMERSION_CORE_TAG_SHADOWING,
    IMMERSION_CORE_TAGS,
    SHADOWING_CANDIDATE_TAG,
    SUBJECT_KIND_KANJI,
    SUBJECT_KIND_RADICAL,
    SUBJECT_KIND_VOCABULARY,
    TierAvailability,
    UNRANKED_BASELINE_SCORE,
    WkAdaptiveNewConfig,
    build_tier_plan,
    candidate_linked_subject_ids,
    effective_immersion_tags,
    immersion_cards_to_unsuspend,
    filtered_deck_has_learning_queues,
    graduated_but_new_card_ids,
    immersion_core_filtered_search,
    immersion_core_tag_sync_actions,
    parse_subject_ids,
    preset_name_for_suffix,
    ranked_immersion_closure,
    sorted_new_card_ids,
    wk_linked_immersion_core_ids,
)

ADDON_NAME = "WK Adaptive New"
DEFAULT_CONFIG_NAME = "wk_adaptive_new_config.json"
DEFAULT_DECK_OPTIONS_JSON = "anki_deck_options.json"
ANKI_CARD_TYPE_NEW = 0
ANKI_QUEUE_NEW = 0
ANKI_QUEUE_SUSPENDED = -1
STUDY_PRIORITY_JSON = "wk_study_priority.json"
SUPPLEMENTARY_PRESET_SUFFIX = "Supplementary"
CORE_NOTE_SCOPE = "tag:wk-core"

# Debounce auto-refresh triggered by note-changing ops (imports) so a single
# import that emits several operations only repositions once.
AUTO_REFRESH_MIN_INTERVAL_SECONDS = 3.0

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
            immersion_priority_enabled=bool(
                payload.get("immersion_priority_enabled", DEFAULT_IMMERSION_PRIORITY_ENABLED)
            ),
            immersion_tag=str(payload.get("immersion_tag", DEFAULT_IMMERSION_TAG)),
            immersion_tags=_parse_immersion_tags(payload),
            immersion_unsuspend=bool(
                payload.get("immersion_unsuspend", DEFAULT_IMMERSION_UNSUSPEND_ENABLED)
            ),
        )
    return WkAdaptiveNewConfig()


def _parse_immersion_tags(payload: Mapping[str, Any]) -> Tuple[str, ...]:
    raw = payload.get("immersion_tags")
    if isinstance(raw, list):
        tags = tuple(str(tag).strip() for tag in raw if str(tag).strip())
        if tags:
            return tags
    legacy = str(payload.get("immersion_tag", "")).strip()
    if legacy:
        return (legacy,)
    return DEFAULT_IMMERSION_TAGS


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


def load_priority_scores() -> Dict[int, int]:
    for path in candidate_study_priority_paths():
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        subjects = payload.get("subjects") or {}
        scores: Dict[int, int] = {}
        for key, entry in subjects.items():
            if not isinstance(entry, dict):
                continue
            try:
                subject_id = int(key)
            except ValueError:
                continue
            scores[subject_id] = int(entry.get("priority_score", 0))
        return scores
    return {}


def _note_field_value(note: Any, field_name: str) -> str:
    model = note.note_type()
    name_to_ord = {field["name"]: index for index, field in enumerate(model["flds"])}
    ord_index = name_to_ord.get(field_name)
    if ord_index is None:
        return ""
    return (note.fields[ord_index] or "").strip()


def _wk_subject_id_from_note(note: Any) -> Optional[int]:
    text = _note_field_value(note, "WkSubjectId")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def collect_immersion_seed_ids(col: Any, immersion_tags: Sequence[str]) -> Set[int]:
    """WkSubjectId + PrerequisiteIds from every immersion note (Satori, Shadowing, …).

    Read live from the collection, so re-imported or newly mined immersion cards
    are always reflected on the next refresh.
    """
    seed: Set[int] = set()
    tags = [str(tag).strip() for tag in immersion_tags if str(tag).strip()]
    if not tags:
        return seed
    if len(tags) == 1:
        query = f"tag:{tags[0]}"
    else:
        query = " OR ".join(f"tag:{tag}" for tag in tags)
        query = f"({query})"
    for note_id in col.find_notes(query):
        note = col.get_note(note_id)
        subject_id = _wk_subject_id_from_note(note)
        if subject_id is not None:
            seed.add(subject_id)
        seed.update(parse_subject_ids(_note_field_value(note, "PrerequisiteIds")))
    return seed


def build_core_prereq_map(col: Any) -> Dict[int, List[int]]:
    """Map each core subject id → its direct PrerequisiteIds (kanji→radicals, vocab→kanji)."""
    prereq_map: Dict[int, List[int]] = {}
    for note_id in col.find_notes(CORE_NOTE_SCOPE):
        note = col.get_note(note_id)
        subject_id = _wk_subject_id_from_note(note)
        if subject_id is None:
            continue
        prereq_map[subject_id] = parse_subject_ids(_note_field_value(note, "PrerequisiteIds"))
    return prereq_map


def build_immersion_priority_ids(col: Any, config: WkAdaptiveNewConfig) -> Set[int]:
    """Immersion-mined subjects plus their full prerequisite closure."""
    return set(build_immersion_priority_ranks(col, config))


def build_immersion_priority_ranks(
    col: Any,
    config: WkAdaptiveNewConfig,
) -> Dict[int, int]:
    """Map immersion subjects and prerequisites to their source priority rank."""
    if not config.immersion_priority_enabled:
        return {}
    tags = effective_immersion_tags(config)
    seeds_by_tag = {
        tag: collect_immersion_seed_ids(col, (tag,))
        for tag in tags
    }
    return ranked_immersion_closure(
        seeds_by_tag,
        build_core_prereq_map(col),
        tags,
    )


def _core_subject_kind_from_note(note: Any, deck_name: str = "") -> Optional[str]:
    if _note_field_value(note, "IsVocabulary").strip() == "1":
        return SUBJECT_KIND_VOCABULARY
    if _note_field_value(note, "IsKanji").strip() == "1":
        return SUBJECT_KIND_KANJI
    tags = {str(tag) for tag in note.tags}
    if SUBJECT_KIND_VOCABULARY in tags or deck_name == CORE_VOCABULARY_DECK:
        return SUBJECT_KIND_VOCABULARY
    if SUBJECT_KIND_KANJI in tags or deck_name == CORE_KANJI_DECK:
        return SUBJECT_KIND_KANJI
    if SUBJECT_KIND_RADICAL in tags or deck_name == CORE_RADICALS_DECK:
        return SUBJECT_KIND_RADICAL
    return None


def _home_deck_name_for_note(col: Any, note_id: int) -> str:
    if hasattr(col, "card_ids_of_note"):
        card_ids = list(col.card_ids_of_note(note_id))
    else:
        card_ids = list(col.cards_of_note(note_id))
    if not card_ids:
        return ""
    card = col.get_card(int(card_ids[0]))
    odid = int(getattr(card, "odid", 0) or 0)
    deck_id = odid if odid else int(card.did)
    return col.decks.name(deck_id)


def gather_core_subject_indexes(
    col: Any,
) -> Tuple[Dict[int, str], Dict[str, int], Dict[str, int], Dict[int, List[int]]]:
    """Return kind_by_id, vocab Expression→id, kanji Expression→id, prereq_map."""
    kind_by_id: Dict[int, str] = {}
    vocab_expr_to_id: Dict[str, int] = {}
    kanji_char_to_id: Dict[str, int] = {}
    prereq_map: Dict[int, List[int]] = {}
    for note_id in col.find_notes(CORE_NOTE_SCOPE):
        note = col.get_note(int(note_id))
        subject_id = _wk_subject_id_from_note(note)
        if subject_id is None:
            continue
        deck_name = _home_deck_name_for_note(col, int(note_id))
        kind = _core_subject_kind_from_note(note, deck_name)
        if kind is None:
            continue
        kind_by_id[subject_id] = kind
        prereq_map[subject_id] = parse_subject_ids(_note_field_value(note, "PrerequisiteIds"))
        expression = _note_field_value(note, "Expression")
        if not expression:
            continue
        if kind == SUBJECT_KIND_VOCABULARY:
            vocab_expr_to_id.setdefault(expression, subject_id)
        elif kind == SUBJECT_KIND_KANJI:
            kanji_char_to_id.setdefault(expression, subject_id)
    return kind_by_id, vocab_expr_to_id, kanji_char_to_id, prereq_map


def collect_candidate_expressions(col: Any) -> List[str]:
    expressions: List[str] = []
    for note_id in col.find_notes(f"tag:{SHADOWING_CANDIDATE_TAG}"):
        note = col.get_note(int(note_id))
        expression = _note_field_value(note, "Expression")
        if expression:
            expressions.append(expression)
    return expressions


def build_immersion_core_subject_ids_by_tag(col: Any) -> Dict[str, Set[int]]:
    """Per immersion-core::* tag: kanji/vocab subject ids linked from that source."""
    kind_by_id, vocab_expr_to_id, kanji_char_to_id, prereq_map = gather_core_subject_indexes(
        col
    )
    by_tag: Dict[str, Set[int]] = {tag: set() for tag in IMMERSION_CORE_TAGS}

    for _source_key, immersion_tag, core_tag in IMMERSION_CORE_SOURCE_SPECS:
        if immersion_tag == SHADOWING_CANDIDATE_TAG:
            by_tag[core_tag] = candidate_linked_subject_ids(
                collect_candidate_expressions(col),
                vocab_expr_to_id,
                kanji_char_to_id,
                prereq_map=prereq_map,
                kind_by_id=kind_by_id,
            )
            continue
        seeds = collect_immersion_seed_ids(col, (immersion_tag,))
        by_tag[core_tag] = wk_linked_immersion_core_ids(seeds, prereq_map, kind_by_id)
    return by_tag


def sync_immersion_core_tags(col: Any) -> Tuple[int, Dict[str, Set[int]]]:
    """Add/remove immersion-core::* tags on core notes. Returns (changed, ids_by_tag)."""
    subject_ids_by_tag = build_immersion_core_subject_ids_by_tag(col)
    notes: List[Tuple[int, Optional[int], Sequence[str]]] = []
    for note_id in col.find_notes(CORE_NOTE_SCOPE):
        note = col.get_note(int(note_id))
        notes.append(
            (
                int(note_id),
                _wk_subject_id_from_note(note),
                tuple(str(tag) for tag in note.tags),
            )
        )
    actions = immersion_core_tag_sync_actions(notes, subject_ids_by_tag)
    for action in actions:
        note = col.get_note(action.note_id)
        tag_set = set(str(tag) for tag in note.tags)
        for tag in action.remove_tags:
            tag_set.discard(tag)
        for tag in action.add_tags:
            tag_set.add(tag)
        note.tags = sorted(tag_set)
        col.update_note(note)
    return len(actions), subject_ids_by_tag


def _filtered_deck_id_by_name(col: Any, name: str) -> Optional[int]:
    deck_id = _deck_id_for_name(col.decks, name)
    if not deck_id:
        return None
    deck_obj = col.decks.get(deck_id)
    if not deck_obj or not deck_obj.get("dyn"):
        return None
    return int(deck_id)


def _set_filtered_deck_search(
    filtered: Any,
    *,
    name: str,
    search: str,
    limit: int = IMMERSION_CORE_FILTERED_LIMIT,
) -> None:
    from anki.decks import FilteredDeckConfig

    filtered.name = name
    # Always create/keep the deck even when no cards match yet (e.g. still
    # suspended, or already introduced). Rebuild fills it later.
    if hasattr(filtered, "allow_empty"):
        filtered.allow_empty = True
    config = filtered.config
    # Must stay on: off = preview mode (answers log but home scheduling unchanged).
    config.reschedule = True
    terms = [
        FilteredDeckConfig.SearchTerm(
            search=search,
            limit=int(limit),
            order=0,  # oldest seen first
        )
    ]
    del config.search_terms[:]
    config.search_terms.extend(terms)


def _filtered_deck_card_queues(col: Any, deck_id: int) -> List[int]:
    rows = col.db.all("select queue from cards where did = ?", deck_id)
    return [int(row[0]) for row in rows]


def _salvage_graduated_new_cards_in_filtered_deck(col: Any, deck_id: int) -> int:
    """Reintroduce new cards that already graduated (filtered rebuild casualty)."""
    rows = col.db.all("select id, type from cards where did = ?", deck_id)
    if not rows:
        return 0
    types_by_id = {int(card_id): int(card_type) for card_id, card_type in rows}
    last_ivl_by_id: Dict[int, int] = {}
    for card_id in types_by_id:
        ivl_row = col.db.first(
            "select ivl from revlog where cid = ? order by id desc limit 1",
            card_id,
        )
        if ivl_row is not None:
            last_ivl_by_id[card_id] = int(ivl_row[0])
    salvage_ids = graduated_but_new_card_ids(types_by_id, last_ivl_by_id)
    if not salvage_ids:
        return 0
    # Converts new → review due today (same as Browse → Cards → Set Due Date → 0).
    col.set_due_date(salvage_ids, "0")
    return len(salvage_ids)


def ensure_immersion_core_filtered_deck(
    col: Any,
    *,
    name: str,
    home_deck: str,
    immersion_core_tag: str,
) -> Tuple[int, str]:
    """Create or update one Immersion Core filtered deck.

    Returns ``(deck_id, status)`` where status is a short human note about
    salvage / skipped rebuild / rebuilt.
    """
    from anki.decks import DeckId

    search = immersion_core_filtered_search(home_deck, immersion_core_tag)
    existing_id = _filtered_deck_id_by_name(col, name)
    status_bits: List[str] = []

    if existing_id is not None:
        salvaged = _salvage_graduated_new_cards_in_filtered_deck(col, existing_id)
        if salvaged:
            status_bits.append(f"salvaged {salvaged} graduated-new")
        queues = _filtered_deck_card_queues(col, existing_id)
        if filtered_deck_has_learning_queues(queues):
            # Updating/rebuilding empties the deck; Anki turns learning cards
            # back into new. Leave in-progress study alone.
            status_bits.append("skipped rebuild (learning cards present)")
            return existing_id, "; ".join(status_bits)

    if existing_id is not None:
        filtered = col.sched.get_or_create_filtered_deck(DeckId(existing_id))
    else:
        filtered = col.sched.get_or_create_filtered_deck(DeckId(0))
    _set_filtered_deck_search(filtered, name=name, search=search)
    result = col.sched.add_or_update_filtered_deck(filtered)
    deck_id = int(getattr(result, "id", 0) or 0)
    if not deck_id and existing_id is not None:
        deck_id = existing_id
    if not deck_id:
        # Fallback: resolve by name after create (some Anki builds omit id).
        deck_id = _filtered_deck_id_by_name(col, name) or 0
    if deck_id:
        try:
            col.sched.rebuild_filtered_deck(DeckId(deck_id))
            status_bits.append("rebuilt")
        except Exception:
            # Empty rebuild can still raise on older builds; deck exists.
            status_bits.append("rebuild skipped (anki error)")
    return deck_id, "; ".join(status_bits) or "ok"


def rebuild_immersion_core_filtered_decks(col: Any) -> List[str]:
    """Ensure all six Immersion Core filtered decks exist and are rebuilt."""
    lines: List[str] = []
    errors: List[str] = []
    for name, home_deck, core_tag in IMMERSION_CORE_FILTERED_DECKS:
        try:
            deck_id, status = ensure_immersion_core_filtered_deck(
                col,
                name=name,
                home_deck=home_deck,
                immersion_core_tag=core_tag,
            )
            card_count = len(col.find_cards(f'deck:"{name}"')) if deck_id else 0
            if deck_id:
                detail = f"{card_count} card(s)"
                if status:
                    detail = f"{detail}; {status}"
                lines.append(f"{name}: {detail}")
            else:
                errors.append(f"{name}: create returned no deck id")
        except Exception as exc:  # noqa: BLE001 — report per-deck failures
            errors.append(f"{name}: {exc}")
    if errors:
        lines.append("Errors:")
        lines.extend(f"  - {err}" for err in errors)
    return lines


def refresh_immersion_core_study_queues(col: Any) -> List[str]:
    """Sync immersion-core tags and rebuild the six filtered decks."""
    changed, subject_ids_by_tag = sync_immersion_core_tags(col)
    lines = [
        f"Immersion core tags: updated {changed} note(s) "
        f"(satori={len(subject_ids_by_tag.get(IMMERSION_CORE_TAG_SATORI, ()))}, "
        f"shadowing={len(subject_ids_by_tag.get(IMMERSION_CORE_TAG_SHADOWING, ()))}, "
        f"candidates={len(subject_ids_by_tag.get(IMMERSION_CORE_TAG_CANDIDATES, ()))})"
    ]
    lines.extend(rebuild_immersion_core_filtered_decks(col))
    return lines


def unsuspend_immersion_cards(col: Any, immersion_ids: Set[int]) -> int:
    """Unsuspend suspended new core cards in the immersion closure.

    Mirrors wk_unlock (queue → new); wk_unlock only ever unsuspends, so the two
    add-ons do not fight. Daily new/day limits still pace how many are served.
    """
    if not immersion_ids:
        return 0
    card_ids = col.find_cards(f"{CORE_NOTE_SCOPE} is:new is:suspended")
    if not card_ids:
        return 0
    entries: List[Tuple[Optional[int], int]] = []
    for card_id in card_ids:
        card = col.get_card(card_id)
        note = col.get_note(card.nid)
        entries.append((_wk_subject_id_from_note(note), int(card_id)))
    to_unsuspend = immersion_cards_to_unsuspend(entries, immersion_ids)
    for card_id in to_unsuspend:
        card = col.get_card(card_id)
        if int(card.queue) == ANKI_QUEUE_SUSPENDED:
            card.queue = ANKI_QUEUE_NEW
            col.update_card(card)
    return len(to_unsuspend)


def reposition_new_cards_by_priority(
    col: Any,
    deck_name: str,
    priority_scores: Mapping[int, int],
    immersion_priority: Optional[Mapping[int, int]] = None,
) -> int:
    immersion = immersion_priority or {}
    card_ids = col.find_cards(f'deck:"{deck_name}" is:new -is:suspended')
    if not card_ids:
        return 0
    entries: List[Tuple[Optional[int], int, int]] = []
    for card_id in card_ids:
        card = col.get_card(card_id)
        note = col.get_note(card.nid)
        subject_id = _wk_subject_id_from_note(note)
        score = priority_scores.get(subject_id, UNRANKED_BASELINE_SCORE) if subject_id is not None else UNRANKED_BASELINE_SCORE
        entries.append((subject_id, score, int(card_id)))
    ordered_card_ids = sorted_new_card_ids(entries, immersion)
    for position, card_id in enumerate(ordered_card_ids, start=1):
        card = col.get_card(card_id)
        if int(card.type) != ANKI_CARD_TYPE_NEW:
            continue
        card.due = position
        col.update_card(card)
    return len(entries)


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
    priority_scores = load_priority_scores()
    immersion_priority = build_immersion_priority_ranks(col, config)
    immersion_ids = set(immersion_priority)
    if immersion_ids:
        tag_label = ", ".join(effective_immersion_tags(config)) or config.immersion_tag
        lines.append(
            f"Immersion priority: {len(immersion_ids)} subjects (mined {tag_label} + prereqs)"
        )
        if config.immersion_unsuspend:
            unsuspended = unsuspend_immersion_cards(col, immersion_ids)
            if unsuspended:
                lines.append(f"Immersion unlock: unsuspended {unsuspended} new card(s)")
    if priority_scores or immersion_ids:
        order_label = "immersion-first" if immersion_ids else "JLPT priority"
        for deck_name in (CORE_RADICALS_DECK, CORE_KANJI_DECK, CORE_VOCABULARY_DECK):
            reordered = reposition_new_cards_by_priority(
                col, deck_name, priority_scores, immersion_priority
            )
            if reordered:
                lines.append(f"{deck_name}: reordered {reordered} new ({order_label})")
    try:
        lines.extend(refresh_immersion_core_study_queues(col))
    except Exception as exc:  # noqa: BLE001 — filtered decks must not block new limits
        print(f"WK adaptive new: immersion core filtered decks skipped ({exc})")
        lines.append(f"Immersion core filtered decks: skipped ({exc})")
    summary_lines = [
        f"Review load ({config.review_count_scope}): {review_load}",
        f"New budget: {budget}",
        *lines,
    ]
    if mw is not None:
        mw.reset()
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


# Guard against the reposition/reset ops re-triggering our own auto-refresh, and
# debounce bursts of operations emitted by a single import.
_auto_refresh_running = False
_last_auto_refresh_monotonic = 0.0


def _maybe_auto_refresh(reason: str) -> None:
    global _auto_refresh_running, _last_auto_refresh_monotonic
    if _auto_refresh_running or mw is None or mw.col is None:
        return
    config = load_adaptive_config()
    if not config.auto_run_on_load:
        return
    now = time.monotonic()
    if now - _last_auto_refresh_monotonic < AUTO_REFRESH_MIN_INTERVAL_SECONDS:
        return
    _auto_refresh_running = True
    try:
        adjust_new_limits(quiet=True)
        _last_auto_refresh_monotonic = time.monotonic()
    except Exception as exc:  # noqa: BLE001 — never block the triggering op
        print(f"WK adaptive new: auto refresh skipped after {reason} ({exc})")
    finally:
        _auto_refresh_running = False


def on_operation_did_execute(changes, handler) -> None:
    # Only react to note-changing ops (apkg import updates note types + notes).
    # Reviews change cards/study_queues but not notes/note types, and our own
    # repositioning changes cards/deck configs — so neither re-triggers a refresh.
    if not (getattr(changes, "notetype", False) or getattr(changes, "note", False)):
        return
    _maybe_auto_refresh("import")


def on_sync_did_finish() -> None:
    _maybe_auto_refresh("sync")


def setup_menu() -> None:
    action = QAction("WK Adjust New Limits", mw)
    action.triggered.connect(_menu_adjust)
    mw.form.menuTools.addAction(action)
    immersion_action = QAction("WK Rebuild Immersion Core Decks", mw)
    immersion_action.triggered.connect(_menu_rebuild_immersion_core)
    mw.form.menuTools.addAction(immersion_action)


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


def _menu_rebuild_immersion_core() -> None:
    if mw is None or mw.col is None:
        showWarning("Open a collection first.")
        return
    try:
        lines = refresh_immersion_core_study_queues(mw.col)
    except Exception as exc:  # noqa: BLE001
        showWarning(str(exc))
        return
    if mw is not None:
        mw.reset()
    showInfo("Immersion Core filtered decks rebuilt.\n\n" + "\n".join(lines))


gui_hooks.collection_did_load.append(on_collection_did_load)
gui_hooks.main_window_did_init.append(setup_menu)
gui_hooks.operation_did_execute.append(on_operation_did_execute)
gui_hooks.sync_did_finish.append(on_sync_did_finish)
