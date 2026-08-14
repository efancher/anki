"""Copy/backup operations between profile/, working/, backups/, outgoing/.

profile/ is the only directory that represents "synced with AnkiWeb" state.
working/ is always disposable and re-derived from profile/ — never treat it
as a source of truth. Nothing here ever deletes a backup or outgoing
snapshot; each call creates a new timestamped directory.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from . import paths


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _copy_profile_dir(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    src_col = paths.collection_path(src)
    if src_col.is_file():
        shutil.copy2(src_col, paths.collection_path(dst))
    src_media = paths.media_dir(src)
    if src_media.is_dir():
        dst_media = paths.media_dir(dst)
        if dst_media.exists():
            shutil.rmtree(dst_media)
        shutil.copytree(src_media, dst_media)


def backup_profile(label: str) -> Path:
    """Snapshot profile/ into backups/<timestamp>-<label>/. Never overwrites
    an existing backup directory."""
    dest = paths.BACKUPS_DIR / f"{_timestamp()}-{label}"
    if dest.exists():
        raise FileExistsError(f"backup destination already exists: {dest}")
    _copy_profile_dir(paths.PROFILE_DIR, dest)
    return dest


def refresh_working_copy() -> Path:
    """Recreate working/ from the current profile/, discarding any prior
    working/ contents (working/ is disposable by design)."""
    if paths.WORKING_DIR.exists():
        shutil.rmtree(paths.WORKING_DIR)
    _copy_profile_dir(paths.PROFILE_DIR, paths.WORKING_DIR)
    return paths.WORKING_DIR


def stage_outgoing(label: str, summary_lines: List[str]) -> Path:
    """Copy working/ into a new timestamped outgoing/ dir with a summary.
    Does not touch profile/."""
    dest = paths.OUTGOING_DIR / f"{_timestamp()}-{label}"
    if dest.exists():
        raise FileExistsError(f"outgoing destination already exists: {dest}")
    _copy_profile_dir(paths.WORKING_DIR, dest)
    (dest / "SUMMARY.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return dest


def promote_working_to_profile(*, backup_label: str = "pre-promote") -> Path:
    """Back up profile/, then replace it with working/'s contents. The only
    function that mutates profile/ in place — call only after validation."""
    backup_path = backup_profile(backup_label)
    _copy_profile_dir(paths.WORKING_DIR, paths.PROFILE_DIR)
    return backup_path
