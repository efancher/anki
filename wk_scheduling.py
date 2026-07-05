"""
wk_scheduling.py

One-time WaniKani assignment → Anki card scheduling bootstrap for core SRS decks.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

SECONDS_PER_DAY = 86400
DEFAULT_SUPPLEMENTARY_MATURE_MIN_SRS_STAGE = 5  # WaniKani Guru I (first Guru)
DEFAULT_SUPPLEMENTARY_MATURE_MIN_INTERVAL_DAYS = 7  # WK srs_stage 5 interval in WK_SRS_STAGE_INTERVAL_DAYS
WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME = "spaced_repetition_systems.json"

# WaniKani assignment srs_stage → approximate interval (days). Fallback when SRS API cache missing.
WK_SRS_STAGE_INTERVAL_DAYS: Dict[int, int] = {
    0: 0,
    1: 0,
    2: 1,
    3: 1,
    4: 2,
    5: 7,
    6: 14,
    7: 30,
    8: 120,
    9: 365,
}

# Anki card.type
ANKI_CARD_TYPE_NEW = 0
ANKI_CARD_TYPE_LEARN = 1
ANKI_CARD_TYPE_REVIEW = 2
ANKI_CARD_TYPE_RELEARNING = 3

# Anki card.queue
ANKI_QUEUE_SUSPENDED = -1
ANKI_QUEUE_NEW = 0
ANKI_QUEUE_LEARN = 1
ANKI_QUEUE_REVIEW = 2
ANKI_QUEUE_DAY_LEARN = 3

WK_SCHEDULE_BOOTSTRAPPED_TAG = "wk-schedule-bootstrapped"
WK_LOCKED_TAG = "wk-locked"

DEFAULT_BURNED_INTERVAL_DAYS = 365


@dataclass(frozen=True)
class WkCardScheduleSpec:
    """Scheduling intent for one note (applied to all sibling cards)."""

    guid: str
    srs_stage: int
    available_at: Optional[str] = None
    suspended: bool = False


def interval_seconds_to_days(interval: Optional[int], *, interval_unit: Optional[str] = None) -> int:
    if interval is None:
        return 0
    unit = (interval_unit or "seconds").lower()
    if unit == "seconds":
        return max(0, int(interval) // SECONDS_PER_DAY)
    if unit in {"hours", "hour"}:
        return max(0, int(interval) // 24)
    if unit in {"days", "day"}:
        return max(0, int(interval))
    return max(0, int(interval) // SECONDS_PER_DAY)


def parse_spaced_repetition_system_stages(system: dict) -> Dict[int, int]:
    """Map WK srs_stage position → interval in days from one spaced_repetition_system object."""
    data = system.get("data") or {}
    stages = data.get("stages") or []
    burned_position = int(data.get("burning_stage_position") or 9)
    intervals: Dict[int, int] = {}
    for stage in stages:
        position = int(stage.get("position") or 0)
        if position == burned_position:
            intervals[position] = DEFAULT_BURNED_INTERVAL_DAYS
            continue
        intervals[position] = interval_seconds_to_days(
            stage.get("interval"),
            interval_unit=stage.get("interval_unit"),
        )
    return intervals


def merge_srs_stage_interval_maps(*maps: Mapping[int, int]) -> Dict[int, int]:
    merged = dict(WK_SRS_STAGE_INTERVAL_DAYS)
    for interval_map in maps:
        merged.update({int(stage): int(days) for stage, days in interval_map.items()})
    return merged


def load_srs_stage_interval_days(cache_path: Optional[Path] = None) -> Dict[int, int]:
    """
    Load stage → interval (days) from .wk_cache/spaced_repetition_systems.json.
    Falls back to WK_SRS_STAGE_INTERVAL_DAYS when cache is missing or invalid.
    """
    path = cache_path
    if path is None:
        path = Path(".wk_cache") / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME
    if not path.is_file():
        return dict(WK_SRS_STAGE_INTERVAL_DAYS)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(WK_SRS_STAGE_INTERVAL_DAYS)

    systems: Sequence[dict]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        systems = payload["items"]
    elif isinstance(payload, list):
        systems = payload
    elif isinstance(payload, dict) and payload.get("object") == "spaced_repetition_system":
        systems = [payload]
    else:
        return dict(WK_SRS_STAGE_INTERVAL_DAYS)

    merged = merge_srs_stage_interval_maps(
        *(parse_spaced_repetition_system_stages(system) for system in systems if isinstance(system, dict))
    )
    merged[9] = DEFAULT_BURNED_INTERVAL_DAYS
    return merged


def srs_stage_interval_days(
    srs_stage: int,
    *,
    interval_map: Optional[Mapping[int, int]] = None,
    burned_interval_days: int = DEFAULT_BURNED_INTERVAL_DAYS,
) -> int:
    if srs_stage >= 9:
        return burned_interval_days
    stage_map = interval_map or WK_SRS_STAGE_INTERVAL_DAYS
    return int(stage_map.get(max(0, srs_stage), WK_SRS_STAGE_INTERVAL_DAYS.get(max(0, srs_stage), 0)))


def wk_subject_mature_at_import(
    srs_stage: int,
    *,
    interval_map: Optional[Mapping[int, int]] = None,
    min_srs_stage: int = DEFAULT_SUPPLEMENTARY_MATURE_MIN_SRS_STAGE,
    mature_interval_days: int = DEFAULT_SUPPLEMENTARY_MATURE_MIN_INTERVAL_DAYS,
    burned_interval_days: int = DEFAULT_BURNED_INTERVAL_DAYS,
) -> bool:
    """True when linked vocab is WK-mature at bootstrap (Guru I+ stage or interval ≥ threshold)."""
    if srs_stage >= min_srs_stage:
        return True
    if srs_stage <= 0:
        return False
    interval_days = srs_stage_interval_days(
        srs_stage,
        interval_map=interval_map,
        burned_interval_days=burned_interval_days,
    )
    return interval_days >= mature_interval_days


def parse_wk_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def available_at_to_due_day(available_at: Optional[str], collection_crt_seconds: int) -> Optional[int]:
    """Convert WK available_at to Anki review due (days since collection creation)."""
    target = parse_wk_timestamp(available_at)
    if target is None:
        return None
    crt = datetime.fromtimestamp(collection_crt_seconds, tz=timezone.utc)
    crt_day = datetime(crt.year, crt.month, crt.day, tzinfo=timezone.utc)
    target_day = datetime(target.year, target.month, target.day, tzinfo=timezone.utc)
    return max(0, (target_day - crt_day).days)


def core_note_suspended(
    assignment: Optional[dict],
    *,
    suspend_unstarted: bool = True,
    suspend_locked: bool = True,
) -> bool:
    if assignment is None:
        return True
    data = assignment.get("data") or {}
    if suspend_locked and not data.get("unlocked_at"):
        return True
    if suspend_unstarted and not data.get("started_at"):
        return True
    return False


def schedule_spec_for_assignment(
    guid: str,
    assignment: Optional[dict],
    *,
    suspend_unstarted: bool = True,
    suspend_locked: bool = True,
) -> WkCardScheduleSpec:
    if core_note_suspended(
        assignment,
        suspend_unstarted=suspend_unstarted,
        suspend_locked=suspend_locked,
    ):
        return WkCardScheduleSpec(guid=guid, srs_stage=0, available_at=None, suspended=True)
    data = (assignment or {}).get("data") or {}
    return WkCardScheduleSpec(
        guid=guid,
        srs_stage=int(data.get("srs_stage") or 0),
        available_at=str(data.get("available_at") or "") or None,
        suspended=False,
    )


def _card_scheduling_values(
    spec: WkCardScheduleSpec,
    collection_crt_seconds: int,
    *,
    interval_map: Optional[Mapping[int, int]] = None,
    burned_interval_days: int = DEFAULT_BURNED_INTERVAL_DAYS,
) -> Tuple[int, int, int, int]:
    """Return (type, queue, ivl, due) for a review card."""
    if spec.suspended:
        return ANKI_CARD_TYPE_NEW, ANKI_QUEUE_SUSPENDED, 0, 0

    ivl = srs_stage_interval_days(
        spec.srs_stage,
        interval_map=interval_map,
        burned_interval_days=burned_interval_days,
    )
    due = available_at_to_due_day(spec.available_at, collection_crt_seconds)
    if due is None:
        due = ivl

    if spec.srs_stage <= 0:
        return ANKI_CARD_TYPE_NEW, ANKI_QUEUE_NEW, 0, 0

    return ANKI_CARD_TYPE_REVIEW, ANKI_QUEUE_REVIEW, max(1, ivl), max(0, due)


def _merge_tags(existing: str, add: Sequence[str]) -> str:
    parts = [part for part in (existing or "").split() if part]
    seen = set(parts)
    for tag in add:
        if tag and tag not in seen:
            parts.append(tag)
            seen.add(tag)
    return " ".join(parts)


def patch_apkg_supplementary_suspend(apkg_path: Path) -> int:
    """
    Suspend cards for notes tagged wk-locked (supplementary gating at import).
    Returns count of notes whose cards were suspended.
    """
    apkg_path = Path(apkg_path)
    if not apkg_path.is_file():
        return 0

    with zipfile.ZipFile(apkg_path, "r") as archive:
        if "collection.anki2" not in archive.namelist():
            return 0
        db_bytes = archive.read("collection.anki2")
        other_entries = {
            name: archive.read(name)
            for name in archive.namelist()
            if name != "collection.anki2"
        }

    with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as tmp_db:
        tmp_db.write(db_bytes)
        tmp_db_path = tmp_db.name

    updated_notes = 0
    try:
        conn = sqlite3.connect(tmp_db_path)
        locked_nids = [
            row[0]
            for row in conn.execute("SELECT id, tags FROM notes").fetchall()
            if WK_LOCKED_TAG in (row[1] or "")
        ]
        for nid in locked_nids:
            conn.execute(
                "UPDATE cards SET queue = ?, type = ?, ivl = 0, due = 0, odue = 0, odid = 0 WHERE nid = ? AND queue != ?",
                (ANKI_QUEUE_SUSPENDED, ANKI_CARD_TYPE_NEW, nid, ANKI_QUEUE_SUSPENDED),
            )
            updated_notes += 1
        conn.commit()
        conn.close()

        patched_bytes = Path(tmp_db_path).read_bytes()
        tmp_apkg = apkg_path.with_suffix(".supplementary.apkg")
        with zipfile.ZipFile(tmp_apkg, "w", compression=zipfile.ZIP_DEFLATED) as outzip:
            outzip.writestr("collection.anki2", patched_bytes)
            for name, payload in other_entries.items():
                outzip.writestr(name, payload)
        tmp_apkg.replace(apkg_path)
    finally:
        Path(tmp_db_path).unlink(missing_ok=True)

    return updated_notes


def patch_apkg_suspend_notes_with_tag(apkg_path: Path, tag: str) -> int:
    """Suspend cards for notes carrying tag (e.g. setup placeholder)."""
    apkg_path = Path(apkg_path)
    if not apkg_path.is_file() or not tag:
        return 0

    with zipfile.ZipFile(apkg_path, "r") as archive:
        if "collection.anki2" not in archive.namelist():
            return 0
        db_bytes = archive.read("collection.anki2")
        other_entries = {
            name: archive.read(name)
            for name in archive.namelist()
            if name != "collection.anki2"
        }

    with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as tmp_db:
        tmp_db.write(db_bytes)
        tmp_db_path = tmp_db.name

    updated_notes = 0
    try:
        conn = sqlite3.connect(tmp_db_path)
        tagged_nids = [
            row[0]
            for row in conn.execute("SELECT id, tags FROM notes").fetchall()
            if tag in (row[1] or "").split()
        ]
        for nid in tagged_nids:
            conn.execute(
                "UPDATE cards SET queue = ?, type = ?, ivl = 0, due = 0, odue = 0, odid = 0 WHERE nid = ? AND queue != ?",
                (ANKI_QUEUE_SUSPENDED, ANKI_CARD_TYPE_NEW, nid, ANKI_QUEUE_SUSPENDED),
            )
            updated_notes += 1
        conn.commit()
        conn.close()

        patched_bytes = Path(tmp_db_path).read_bytes()
        tmp_apkg = apkg_path.with_suffix(".tag_suspend.apkg")
        with zipfile.ZipFile(tmp_apkg, "w", compression=zipfile.ZIP_DEFLATED) as outzip:
            outzip.writestr("collection.anki2", patched_bytes)
            for name, payload in other_entries.items():
                outzip.writestr(name, payload)
        tmp_apkg.replace(apkg_path)
    finally:
        Path(tmp_db_path).unlink(missing_ok=True)

    return updated_notes


def patch_apkg_wk_scheduling(
    apkg_path: Path,
    schedule_by_guid: Mapping[str, WkCardScheduleSpec],
    *,
    interval_map: Optional[Mapping[int, int]] = None,
    burned_interval_days: int = DEFAULT_BURNED_INTERVAL_DAYS,
) -> int:
    """
    Patch cards in an .apkg from WkCardScheduleSpec entries keyed by note guid.
    Returns count of notes updated.
    """
    apkg_path = Path(apkg_path)
    if not schedule_by_guid or not apkg_path.is_file():
        return 0

    with zipfile.ZipFile(apkg_path, "r") as archive:
        if "collection.anki2" not in archive.namelist():
            return 0
        db_bytes = archive.read("collection.anki2")
        other_entries = {
            name: archive.read(name)
            for name in archive.namelist()
            if name != "collection.anki2"
        }

    with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as tmp_db:
        tmp_db.write(db_bytes)
        tmp_db_path = tmp_db.name

    updated_notes = 0
    try:
        conn = sqlite3.connect(tmp_db_path)
        crt_seconds = int(conn.execute("SELECT crt FROM col").fetchone()[0])
        guid_rows = conn.execute("SELECT id, guid, tags FROM notes").fetchall()
        guid_to_nid = {row[1]: row[0] for row in guid_rows}

        for guid, spec in schedule_by_guid.items():
            nid = guid_to_nid.get(guid)
            if nid is None:
                continue
            if WK_SCHEDULE_BOOTSTRAPPED_TAG in (conn.execute(
                "SELECT tags FROM notes WHERE id = ?", (nid,)
            ).fetchone()[0] or ""):
                continue

            card_type, queue, ivl, due = _card_scheduling_values(
                spec,
                crt_seconds,
                interval_map=interval_map,
                burned_interval_days=burned_interval_days,
            )
            conn.execute(
                "UPDATE cards SET type = ?, queue = ?, ivl = ?, due = ?, odue = 0, odid = 0, factor = 2500 WHERE nid = ?",
                (card_type, queue, ivl, due, nid),
            )

            existing_tags = conn.execute("SELECT tags FROM notes WHERE id = ?", (nid,)).fetchone()[0] or ""
            add_tags = [WK_SCHEDULE_BOOTSTRAPPED_TAG]
            if spec.suspended:
                add_tags.append(WK_LOCKED_TAG)
            conn.execute(
                "UPDATE notes SET tags = ? WHERE id = ?",
                (_merge_tags(existing_tags, add_tags), nid),
            )
            updated_notes += 1

        conn.commit()
        conn.close()

        patched_bytes = Path(tmp_db_path).read_bytes()
        tmp_apkg = apkg_path.with_suffix(".scheduling.apkg")
        with zipfile.ZipFile(tmp_apkg, "w", compression=zipfile.ZIP_DEFLATED) as outzip:
            outzip.writestr("collection.anki2", patched_bytes)
            for name, payload in other_entries.items():
                outzip.writestr(name, payload)
        tmp_apkg.replace(apkg_path)
    finally:
        Path(tmp_db_path).unlink(missing_ok=True)

    return updated_notes


def merge_schedule_specs(specs: Iterable[WkCardScheduleSpec]) -> Dict[str, WkCardScheduleSpec]:
    merged: Dict[str, WkCardScheduleSpec] = {}
    for spec in specs:
        merged[spec.guid] = spec
    return merged
