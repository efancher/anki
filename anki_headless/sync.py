"""Incremental AnkiWeb sync for the headless profile.

Deliberately refuses full uploads/downloads by default: if AnkiWeb reports
the local and remote collections have diverged enough to need a one-way
replace, that is exactly the "guess which copy wins" situation the whole
point of this tooling is to avoid. Callers must pass an explicit
allow_full_sync direction to proceed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from anki import sync_pb2
from anki.collection import Collection
from anki.errors import SyncError

from . import paths
from .auth import StoredAuth, to_sync_auth

_Required = sync_pb2.SyncCollectionResponse

_REQUIRED_NAMES = {
    _Required.NO_CHANGES: "NO_CHANGES",
    _Required.NORMAL_SYNC: "NORMAL_SYNC",
    _Required.FULL_SYNC: "FULL_SYNC",
    _Required.FULL_DOWNLOAD: "FULL_DOWNLOAD",
    _Required.FULL_UPLOAD: "FULL_UPLOAD",
}
_SAFE_REQUIRED = {_Required.NO_CHANGES, _Required.NORMAL_SYNC}


class FullSyncRequired(RuntimeError):
    def __init__(self, required_name: str):
        self.required_name = required_name
        super().__init__(
            f"AnkiWeb requires a full sync ({required_name}) instead of an "
            "incremental one — the local and AnkiWeb collections have diverged. "
            "Refusing to guess a direction. See docs/anki_headless_sync.md "
            "'What happens on divergence' before using --allow-full-sync."
        )


@dataclass
class SyncResult:
    required: str
    server_message: str
    updated_auth: Optional[StoredAuth] = None


def open_profile_collection(profile_dir: Path) -> Collection:
    profile_dir.mkdir(parents=True, exist_ok=True)
    return Collection(str(paths.collection_path(profile_dir)))


def _follow_endpoint_redirect(sync_auth, stored: StoredAuth, response):
    """AnkiWeb shards accounts across hosts; a sync_collection/sync_status
    response can carry a `new_endpoint` telling the client where to send
    subsequent requests (in particular the actual data transfer in
    full_upload_or_download). Not following it produces confusing
    unrelated-looking errors (e.g. "missing original size") because the
    request lands on a host with no matching session state.
    Returns (sync_auth_to_use, updated_StoredAuth_or_None).
    """
    if not response.HasField("new_endpoint") or not response.new_endpoint:
        return sync_auth, None
    updated = StoredAuth(hkey=stored.hkey, endpoint=response.new_endpoint)
    return to_sync_auth(updated), updated


def sync_collection(
    profile_dir: Path,
    auth: StoredAuth,
    *,
    sync_media: bool = False,
    allow_full_sync: Optional[str] = None,
) -> SyncResult:
    """allow_full_sync: None (refuse), "upload", or "download"."""
    if allow_full_sync not in (None, "upload", "download"):
        raise ValueError("allow_full_sync must be None, 'upload', or 'download'")

    col = open_profile_collection(profile_dir)
    sync_auth = to_sync_auth(auth)
    try:
        try:
            output = col.sync_collection(sync_auth, sync_media)
        except SyncError as exc:
            raise SystemExit(f"AnkiWeb sync failed: {exc}") from exc

        sync_auth, updated_auth = _follow_endpoint_redirect(sync_auth, auth, output)

        required = output.required
        required_name = _REQUIRED_NAMES.get(required, str(required))

        if required in _SAFE_REQUIRED:
            return SyncResult(
                required=required_name,
                server_message=output.server_message,
                updated_auth=updated_auth,
            )

        if allow_full_sync is None:
            raise FullSyncRequired(required_name)

        upload = allow_full_sync == "upload"
        # server_media_usn from the preceding sync_collection() response must
        # be threaded through here — omitting it (e.g. passing None) makes
        # AnkiWeb reject the request with "missing original size".
        col.close_for_full_sync()
        col.full_upload_or_download(
            auth=sync_auth, server_usn=output.server_media_usn, upload=upload
        )
        col.reopen(after_full_sync=True)
        return SyncResult(
            required=f"{required_name} ({allow_full_sync})",
            server_message=output.server_message,
            updated_auth=updated_auth,
        )
    finally:
        col.close()


def sync_media(profile_dir: Path, auth: StoredAuth) -> None:
    col = open_profile_collection(profile_dir)
    try:
        col.sync_media(to_sync_auth(auth))
    finally:
        col.close()
