#!/usr/bin/env python3
"""
Configure Migaku → Anki field maps for WK Migaku Immersion.

AnkiConnect cannot write Migaku's add-on config. Use either:

  • Anki open: Tools → WK Configure Migaku Field Map  (recommended)
  • Anki quit:  python3 scripts/configure_migaku_field_map.py --offline

The offline mode patches ~/Library/Application Support/Anki2/addons21/<migaku>/meta.json
and reads model/deck ids from your collection.anki2.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
IMMERSION_DIR = REPO_ROOT / "anki_addon" / "wk_immersion"
if str(IMMERSION_DIR) not in sys.path:
    sys.path.insert(0, str(IMMERSION_DIR))

from migaku_field_map import (  # noqa: E402
    MINING_DECK_NAME,
    MINING_NOTE_TYPE,
    build_field_map,
)

ANKI_CONNECT_URL = "http://127.0.0.1:8765"
DEFAULT_MIGAKU_ADDON_ID = "1846879528"


def anki_connect(action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        ANKI_CONNECT_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("error"):
        raise RuntimeError(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def anki_connect_reachable() -> bool:
    try:
        anki_connect("version")
        return True
    except (urllib.error.URLError, RuntimeError, TimeoutError):
        return False


def default_anki_base() -> Path:
    return Path.home() / "Library" / "Application Support" / "Anki2"


def find_collection_path(profile: str | None) -> Path:
    base = default_anki_base()
    if profile:
        path = base / profile / "collection.anki2"
        if path.is_file():
            return path
        raise SystemExit(f"Collection not found: {path}")
    for path in sorted(base.glob("*/collection.anki2")):
        return path
    raise SystemExit(f"No collection.anki2 under {base}")


def load_models(collection_path: Path) -> dict:
    conn = sqlite3.connect(collection_path)
    try:
        return json.loads(conn.execute("SELECT models FROM col").fetchone()[0])
    finally:
        conn.close()


def load_decks(collection_path: Path) -> dict:
    conn = sqlite3.connect(collection_path)
    try:
        return json.loads(conn.execute("SELECT decks FROM col").fetchone()[0])
    finally:
        conn.close()


def model_id_by_name(models: dict, name: str) -> int | None:
    for mid, model in models.items():
        if model.get("name") == name:
            return int(mid)
    return None


def deck_id_by_name(decks: dict, name: str) -> int | None:
    for did, deck in decks.items():
        if deck.get("name") == name:
            return int(did)
    return None


def configure_offline(profile: str | None, migaku_addon_id: str) -> None:
    collection_path = find_collection_path(profile)
    models = load_models(collection_path)
    decks = load_decks(collection_path)

    primary_id = model_id_by_name(models, MINING_NOTE_TYPE)
    deck_id = deck_id_by_name(decks, MINING_DECK_NAME)
    if primary_id is None:
        raise SystemExit(f"Note type {MINING_NOTE_TYPE!r} not in {collection_path}")
    if deck_id is None:
        raise SystemExit(f"Deck {MINING_DECK_NAME!r} not in {collection_path}")

    migaku_fields: dict[str, dict[str, str]] = {}
    configured: list[str] = []
    for note_type_name in note_types_to_configure_names(models):
        for mid, model in models.items():
            if model.get("name") != note_type_name:
                continue
            field_names = [field["name"] for field in model["flds"]]
            migaku_fields[str(mid)] = build_field_map(field_names)
            configured.append(note_type_name)

    meta_path = default_anki_base() / "addons21" / migaku_addon_id / "meta.json"
    if not meta_path.is_file():
        raise SystemExit(f"Migaku add-on meta not found: {meta_path}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    config = dict(meta.get("config") or {})
    config["migakuFields"] = migaku_fields
    config["migakuNotetypeId"] = primary_id
    config["migakuDeckId"] = deck_id
    meta["config"] = config
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"Patched {meta_path}")
    print(f"  Deck: {MINING_DECK_NAME} (id {deck_id})")
    print(f"  Note type: {MINING_NOTE_TYPE} (id {primary_id})")
    print(f"  Mapped: {', '.join(configured)}")
    print("\nStart Anki and mine a test card.")


def note_types_to_configure_names(models: dict) -> list[str]:
    names = [MINING_NOTE_TYPE]
    if any(model.get("name") == f"{MINING_NOTE_TYPE}+" for model in models.values()):
        names.append(f"{MINING_NOTE_TYPE}+")
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Patch Migaku meta.json while Anki is quit (collection must not be locked)",
    )
    parser.add_argument("--profile", help="Anki profile folder name (default: first profile)")
    parser.add_argument(
        "--migaku-addon-id",
        default=DEFAULT_MIGAKU_ADDON_ID,
        help=f"Migaku add-on folder id (default {DEFAULT_MIGAKU_ADDON_ID})",
    )
    args = parser.parse_args()

    if args.offline:
        configure_offline(args.profile, args.migaku_addon_id)
        return

    if anki_connect_reachable():
        print(
            "Anki is running. AnkiConnect cannot write Migaku's field-map config.\n\n"
            "In Anki: Tools → WK Configure Migaku Field Map\n\n"
            "Or quit Anki and run:\n"
            "  python3 scripts/configure_migaku_field_map.py --offline"
        )
        # Still verify model/deck exist via AnkiConnect
        names = anki_connect("modelNames")
        decks = anki_connect("deckNames")
        if MINING_NOTE_TYPE not in names:
            print(f"\nWarning: {MINING_NOTE_TYPE!r} not in Anki — import out/wk_migaku.apkg")
        if MINING_DECK_NAME not in decks:
            print(f"Warning: {MINING_DECK_NAME!r} not in Anki — import out/wk_migaku.apkg")
        raise SystemExit(0)

    configure_offline(args.profile, args.migaku_addon_id)


if __name__ == "__main__":
    main()
