"""Filesystem layout for headless Anki sync.

Deliberately kept outside the git repo (~/anki-data, ~/.config/anki-headless)
since it holds real collection data and auth material, neither of which
belongs in version control.
"""
from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ROOT = Path(os.environ.get("ANKI_HEADLESS_DATA_DIR", "~/anki-data")).expanduser()
PROFILE_DIR = WORKSPACE_ROOT / "profile"
WORKING_DIR = WORKSPACE_ROOT / "working"
BACKUPS_DIR = WORKSPACE_ROOT / "backups"
OUTGOING_DIR = WORKSPACE_ROOT / "outgoing"

CONFIG_DIR = Path(os.environ.get("ANKI_HEADLESS_CONFIG_DIR", "~/.config/anki-headless")).expanduser()
AUTH_FILE = CONFIG_DIR / "auth.json"

COLLECTION_FILENAME = "collection.anki2"
MEDIA_DIRNAME = "collection.media"


def collection_path(profile_dir: Path) -> Path:
    return profile_dir / COLLECTION_FILENAME


def media_dir(profile_dir: Path) -> Path:
    return profile_dir / MEDIA_DIRNAME


def ensure_workspace() -> None:
    for path in (PROFILE_DIR, WORKING_DIR, BACKUPS_DIR, OUTGOING_DIR, CONFIG_DIR):
        path.mkdir(parents=True, exist_ok=True)
