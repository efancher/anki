"""Shared mining note-type / tag names (Yomitan primary, Migaku/Satori secondary)."""

from __future__ import annotations

from typing import FrozenSet

# Primary generator / docs target.
MINING_NOTE_TYPE = "WK Yomitan Immersion"
MINING_DECK_NAME = "Immersion · Yomitan Mining"
MINING_TAG = "yomitan-mining"
MINING_EXPORT_FILENAME = "wk_mining.apkg"

# Legacy Migaku notes still enrich / unlock / synthesize.
LEGACY_MIGAKU_NOTE_TYPE = "WK Migaku Immersion"
LEGACY_MIGAKU_NOTE_TYPE_PLUS = "WK Migaku Immersion+"
LEGACY_MIGAKU_TAG = "migaku-mining"

# Satori Reader import — TTS + unlock hints; keep its own card templates.
SATORI_NOTE_TYPE = "WK Satori Immersion"
SATORI_TAG = "satori-mining"

MINING_NOTE_TYPES: FrozenSet[str] = frozenset(
    {
        MINING_NOTE_TYPE,
        LEGACY_MIGAKU_NOTE_TYPE,
        LEGACY_MIGAKU_NOTE_TYPE_PLUS,
        SATORI_NOTE_TYPE,
    }
)

# Yomitan/Migaku cloze + shadow template upgrades only (not Satori's CSV layout).
MINING_TEMPLATE_UPGRADE_NOTE_TYPES: FrozenSet[str] = frozenset(
    {
        MINING_NOTE_TYPE,
        LEGACY_MIGAKU_NOTE_TYPE,
        LEGACY_MIGAKU_NOTE_TYPE_PLUS,
    }
)

MINING_HINT_TAGS_QUERY = (
    "(tag:yomitan-mining OR tag:migaku-mining OR tag:satori-mining) -tag:mining-setup"
)


def is_mining_note_type(name: str) -> bool:
    return name in MINING_NOTE_TYPES


def is_mining_template_upgrade_note_type(name: str) -> bool:
    return name in MINING_TEMPLATE_UPGRADE_NOTE_TYPES
