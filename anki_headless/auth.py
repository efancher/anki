"""AnkiWeb credential handling.

We never persist the AnkiWeb password. `login()` exchanges it once for a
sync auth token (`hkey`) via Anki's own sync_login backend call, and only
that token is written to disk (0600). If the token is later rejected
(expired/revoked), re-run `scripts/anki_headless_login`.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from getpass import getpass
from typing import Optional

from anki.collection import Collection
from anki.errors import SyncError
from anki.sync import SyncAuth

from . import paths


@dataclass
class StoredAuth:
    hkey: str
    endpoint: Optional[str]


def load_auth() -> Optional[StoredAuth]:
    if not paths.AUTH_FILE.is_file():
        return None
    payload = json.loads(paths.AUTH_FILE.read_text(encoding="utf-8"))
    hkey = payload.get("hkey")
    if not hkey:
        return None
    return StoredAuth(hkey=hkey, endpoint=payload.get("endpoint") or None)


def save_auth(auth: StoredAuth) -> None:
    paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"hkey": auth.hkey, "endpoint": auth.endpoint}
    paths.AUTH_FILE.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(paths.AUTH_FILE, stat.S_IRUSR | stat.S_IWUSR)


def to_sync_auth(stored: StoredAuth) -> SyncAuth:
    return SyncAuth(hkey=stored.hkey, endpoint=stored.endpoint)


def interactive_login(*, scratch_collection_path: str) -> StoredAuth:
    """Prompt for AnkiWeb credentials on the controlling TTY and exchange
    them for a sync token. The password is held only in local variables for
    the duration of this call and is never written anywhere.
    """
    username = input("AnkiWeb email/username: ").strip()
    password = getpass("AnkiWeb password (not stored, not echoed): ")

    # sync_login needs an open Collection to call the backend through, but
    # doesn't touch its data — a throwaway scratch collection is fine.
    col = Collection(scratch_collection_path)
    try:
        try:
            auth = col.sync_login(username, password, None)
        except SyncError as exc:
            raise SystemExit(f"AnkiWeb login failed: {exc}") from exc
    finally:
        col.close()

    stored = StoredAuth(hkey=auth.hkey, endpoint=auth.endpoint or None)
    save_auth(stored)
    return stored


def require_auth() -> StoredAuth:
    stored = load_auth()
    if stored is None:
        raise SystemExit(
            "No AnkiWeb auth token found. Run scripts/anki_headless_login first."
        )
    return stored
