"""Read-only validation: SQLite integrity check + Collection-API counts.

Deliberately does not call Collection.fix_integrity() as part of normal
validation — that's Anki's "Check Database" repair operation and can
rewrite the file. It's exposed separately (run_check_database) for
explicit, opt-in use only.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from anki.collection import Collection

from . import paths

TRACKED_TAGS: Tuple[str, ...] = ("wk-core", "wk-locked")


def _unicase(a: str, b: str) -> int:
    a, b = a.casefold(), b.casefold()
    return 0 if a == b else (-1 if a < b else 1)


def sqlite_integrity_check(collection_path: Path) -> Tuple[bool, str]:
    uri = f"file:{collection_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    # Anki's Rust backend registers a "unicase" collation (case-insensitive
    # ordering) that some indexes are built with; without it, integrity_check
    # fails immediately with "no such collation sequence" before it can check
    # anything. This casefold-based approximation is only used for this
    # read-only structural check, never for writes — a real class of
    # unicase-ordering-specific corruption could in theory slip past a
    # non-identical collation, so treat this as a strong signal, not proof;
    # a clean Collection-API open (done right after) is the stronger check.
    conn.create_collation("unicase", _unicase)
    try:
        rows = conn.execute("PRAGMA integrity_check;").fetchall()
    finally:
        conn.close()
    messages = [row[0] for row in rows]
    ok = messages == ["ok"]
    return ok, "; ".join(messages)


@dataclass
class CollectionSnapshot:
    deck_count: int
    note_count: int
    card_count: int
    suspended_count: int
    sqlite_integrity_ok: bool
    sqlite_integrity_report: str
    counts_by_tag: Dict[str, int] = field(default_factory=dict)


def snapshot(profile_dir: Path) -> CollectionSnapshot:
    col_path = paths.collection_path(profile_dir)
    integrity_ok, integrity_report = sqlite_integrity_check(col_path)

    col = Collection(str(col_path))
    try:
        counts_by_tag = {tag: len(col.find_notes(f"tag:{tag}")) for tag in TRACKED_TAGS}
        return CollectionSnapshot(
            deck_count=len(col.decks.all_names_and_ids()),
            note_count=col.note_count(),
            card_count=col.card_count(),
            suspended_count=len(col.find_cards("is:suspended")),
            sqlite_integrity_ok=integrity_ok,
            sqlite_integrity_report=integrity_report,
            counts_by_tag=counts_by_tag,
        )
    finally:
        col.close()


def diff(before: CollectionSnapshot, after: CollectionSnapshot) -> List[str]:
    lines: List[str] = []
    for label, b, a in (
        ("decks", before.deck_count, after.deck_count),
        ("notes", before.note_count, after.note_count),
        ("cards", before.card_count, after.card_count),
        ("suspended", before.suspended_count, after.suspended_count),
    ):
        if b != a:
            lines.append(f"{label}: {b} -> {a} ({a - b:+d})")
    for tag in TRACKED_TAGS:
        b = before.counts_by_tag.get(tag, 0)
        a = after.counts_by_tag.get(tag, 0)
        if b != a:
            lines.append(f"tag:{tag}: {b} -> {a} ({a - b:+d})")
    if not lines:
        lines.append("no count changes")
    return lines


def run_check_database(profile_dir: Path) -> Tuple[str, bool]:
    """Anki's own repair pass (Tools -> Check Database equivalent).

    Opt-in only — can rewrite the collection file. Call explicitly, never
    as part of routine validation.
    """
    col = Collection(str(paths.collection_path(profile_dir)))
    try:
        return col.fix_integrity()
    finally:
        col.close()
