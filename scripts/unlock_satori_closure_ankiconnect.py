#!/usr/bin/env python3
"""Unsuspend the Satori immersion closure in a running Anki via AnkiConnect.

The ``wk_adaptive_new`` add-on now unsuspends the immersion closure (mined
``satori-mining`` subjects + their prerequisite closure) automatically on the
next collection load / "Adjust new options" run. This script applies the same
unlock immediately to an already-open collection, so mined vocab/kanji become
eligible new cards without waiting for a restart.

It reuses the add-on's own logic helpers, so its selection can never drift from
what the add-on ships.

Usage:
    python3 scripts/unlock_satori_closure_ankiconnect.py [--dry-run]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
LOGIC_PATH = REPO_ROOT / "anki_addon" / "wk_adaptive_new" / "logic.py"

ANKICONNECT_URL = "http://localhost:8765"
ANKICONNECT_VERSION = 6
CORE_NOTE_SCOPE = "tag:wk-core"


def _load_logic():
    spec = importlib.util.spec_from_file_location("wk_adaptive_new_logic_unlock", LOGIC_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wk_adaptive_new_logic_unlock"] = module
    spec.loader.exec_module(module)
    return module


logic = _load_logic()
expand_immersion_closure = logic.expand_immersion_closure
immersion_cards_to_unsuspend = logic.immersion_cards_to_unsuspend
parse_subject_ids = logic.parse_subject_ids
DEFAULT_IMMERSION_TAG = logic.DEFAULT_IMMERSION_TAG


def anki_connect(action: str, **params: Any) -> Any:
    payload = json.dumps({"action": action, "version": ANKICONNECT_VERSION, "params": params}).encode()
    request = urllib.request.Request(ANKICONNECT_URL, data=payload)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode())
    if body.get("error"):
        raise RuntimeError(f"AnkiConnect '{action}' failed: {body['error']}")
    return body["result"]


def _field(container: Dict[str, Any], name: str) -> str:
    field = container.get("fields", {}).get(name)
    return (field or {}).get("value", "") if field else ""


def _subject_id(container: Dict[str, Any]) -> Optional[int]:
    text = _field(container, "WkSubjectId").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def collect_immersion_seed_ids(immersion_tag: str) -> Set[int]:
    seed: Set[int] = set()
    note_ids = anki_connect("findNotes", query=f"tag:{immersion_tag}")
    for info in anki_connect("notesInfo", notes=note_ids):
        subject_id = _subject_id(info)
        if subject_id is not None:
            seed.add(subject_id)
        seed.update(parse_subject_ids(_field(info, "PrerequisiteIds")))
    return seed


def build_core_prereq_map() -> Dict[int, List[int]]:
    prereq_map: Dict[int, List[int]] = {}
    note_ids = anki_connect("findNotes", query=CORE_NOTE_SCOPE)
    for info in anki_connect("notesInfo", notes=note_ids):
        subject_id = _subject_id(info)
        if subject_id is None:
            continue
        prereq_map[subject_id] = parse_subject_ids(_field(info, "PrerequisiteIds"))
    return prereq_map


def suspended_new_core_entries() -> List[Tuple[Optional[int], int]]:
    card_ids = anki_connect("findCards", query=f"{CORE_NOTE_SCOPE} is:new is:suspended")
    if not card_ids:
        return []
    entries: List[Tuple[Optional[int], int]] = []
    for info in anki_connect("cardsInfo", cards=card_ids):
        card_id = info.get("cardId")
        if card_id is None:
            continue
        entries.append((_subject_id(info), int(card_id)))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=DEFAULT_IMMERSION_TAG, help="Immersion note tag (default: satori-mining)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be unsuspended, change nothing")
    args = parser.parse_args()

    seed = collect_immersion_seed_ids(args.tag)
    if not seed:
        print(f"No immersion notes found for tag:{args.tag}; nothing to unlock.")
        return 0
    closure = expand_immersion_closure(seed, build_core_prereq_map())
    print(f"Immersion closure: {len(seed)} mined seed subjects → {len(closure)} subjects incl. prerequisites.")

    entries = suspended_new_core_entries()
    to_unsuspend = immersion_cards_to_unsuspend(entries, closure)
    print(f"Suspended new core cards in closure: {len(to_unsuspend)} (of {len(entries)} suspended new core cards).")

    if not to_unsuspend:
        print("Nothing to unsuspend — closure is already unlocked.")
        return 0
    if args.dry_run:
        print("Dry run: no changes made. Re-run without --dry-run to unsuspend.")
        return 0

    anki_connect("unsuspend", cards=to_unsuspend)
    print(f"Unsuspended {len(to_unsuspend)} card(s).")
    print(
        "Restart Anki (or run WK → Adjust new options) so the add-on repositions "
        "these to the front of the new queue."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
