#!/usr/bin/env python3
"""Patch Kanji Meaning Anchor notes when .apkg import rejects field-schema changes.

Anki often keeps notes on the old note type and creates an empty
`WK Update-Safe Kanji Meaning+` with the new fields, then reports all notes
"could not be imported."

This script upgrades the live note type (fields + templates + CSS), stores
radical media, and fills RadicalsHtml / MeaningMnemonic from out/wk_kanji_meaning.apkg.

Usage (Anki open with AnkiConnect):
  python3 scripts/patch_kanji_meaning_ankiconnect.py
"""

from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kanji_meaning_decks import make_kanji_meaning_model  # noqa: E402

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
DEFAULT_APKG = REPO_ROOT / "out" / "wk_kanji_meaning.apkg"
DEFAULT_MODEL = "WK Update-Safe Kanji Meaning"
DESIRED_FIELDS: Tuple[str, ...] = (
    "GuidKey",
    "WkSubjectId",
    "Expression",
    "Meaning",
    "RadicalsHtml",
    "MeaningMnemonic",
    "Meta",
)
BATCH_SIZE = 50


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {base_url}. "
            f"Is Anki open with AnkiConnect installed?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def ensure_fields(base_url: str, model_name: str) -> None:
    fields: List[str] = list(anki_connect(base_url, "modelFieldNames", modelName=model_name))
    print(f"before fields: {fields}")
    for name in ("RadicalsHtml", "MeaningMnemonic"):
        if name in fields:
            continue
        index = fields.index("Meta") if "Meta" in fields else len(fields)
        anki_connect(
            base_url,
            "modelFieldAdd",
            modelName=model_name,
            fieldName=name,
            index=index,
        )
        fields = list(anki_connect(base_url, "modelFieldNames", modelName=model_name))
        print(f"  added {name} -> {fields}")
    for index, name in enumerate(DESIRED_FIELDS):
        fields = list(anki_connect(base_url, "modelFieldNames", modelName=model_name))
        if name not in fields:
            continue
        current = fields.index(name)
        if current != index:
            anki_connect(
                base_url,
                "modelFieldReposition",
                modelName=model_name,
                fieldName=name,
                index=index,
            )
    print(f"after fields: {anki_connect(base_url, 'modelFieldNames', modelName=model_name)}")


def update_templates(base_url: str, model_name: str) -> None:
    model = make_kanji_meaning_model()
    tmpl = model.templates[0]
    anki_connect(
        base_url,
        "updateModelTemplates",
        model={
            "name": model_name,
            "templates": {tmpl["name"]: {"Front": tmpl["qfmt"], "Back": tmpl["afmt"]}},
        },
    )
    anki_connect(
        base_url,
        "updateModelStyling",
        model={"name": model_name, "css": model.css},
    )
    print("updated templates + css")


def load_apkg_payload(
    apkg: Path,
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, str]], Dict[str, bytes]]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(apkg) as zf:
            zf.extractall(tmp_path)
        db = next(tmp_path.glob("*.anki2"), None) or next(tmp_path.glob("*.anki21"))
        con = sqlite3.connect(db)
        by_guid: Dict[str, Dict[str, str]] = {}
        by_wkid: Dict[str, Dict[str, str]] = {}
        for _guid, flds in con.execute("select guid, flds from notes"):
            parts = flds.split("\x1f")
            payload = {
                "RadicalsHtml": parts[4] if len(parts) > 4 else "",
                "MeaningMnemonic": parts[5] if len(parts) > 5 else "",
            }
            by_guid[parts[0]] = payload
            by_wkid[parts[1]] = payload
        media_map: Dict[str, bytes] = {}
        media_json = tmp_path / "media"
        if media_json.is_file():
            mapping = json.loads(media_json.read_text(encoding="utf-8"))
            for idx, name in mapping.items():
                media_map[name] = (tmp_path / str(idx)).read_bytes()
        return by_guid, by_wkid, media_map


def store_media(base_url: str, media_map: Dict[str, bytes]) -> int:
    stored = 0
    for name, data in media_map.items():
        anki_connect(
            base_url,
            "storeMediaFile",
            filename=name,
            data=base64.b64encode(data).decode("ascii"),
        )
        stored += 1
        if stored % 25 == 0:
            print(f"  media {stored}/{len(media_map)}")
    return stored


def patch_notes(
    base_url: str,
    model_name: str,
    by_guid: Dict[str, Dict[str, str]],
    by_wkid: Dict[str, Dict[str, str]],
) -> Tuple[int, int]:
    note_ids: List[int] = list(
        anki_connect(base_url, "findNotes", query=f'note:"{model_name}"') or []
    )
    updated = 0
    missing = 0
    for start in range(0, len(note_ids), BATCH_SIZE):
        batch = note_ids[start : start + BATCH_SIZE]
        notes = anki_connect(base_url, "notesInfo", notes=batch) or []
        actions: List[dict] = []
        for note in notes:
            fields = note["fields"]
            guid = fields.get("GuidKey", {}).get("value", "")
            wkid = fields.get("WkSubjectId", {}).get("value", "")
            payload = by_guid.get(guid) or by_wkid.get(wkid)
            if not payload:
                missing += 1
                continue
            cur_r = fields.get("RadicalsHtml", {}).get("value", "")
            cur_m = fields.get("MeaningMnemonic", {}).get("value", "")
            if cur_r == payload["RadicalsHtml"] and cur_m == payload["MeaningMnemonic"]:
                continue
            actions.append(
                {
                    "action": "updateNoteFields",
                    "params": {
                        "note": {
                            "id": note["noteId"],
                            "fields": {
                                "RadicalsHtml": payload["RadicalsHtml"],
                                "MeaningMnemonic": payload["MeaningMnemonic"],
                            },
                        }
                    },
                }
            )
        if actions:
            anki_connect(base_url, "multi", actions=actions)
            updated += len(actions)
        print(
            f"  notes {min(start + BATCH_SIZE, len(note_ids))}/{len(note_ids)} "
            f"(updated total {updated})"
        )
    return updated, missing


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument("--apkg", type=Path, default=DEFAULT_APKG)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.apkg.is_file():
        raise SystemExit(f"Missing apkg: {args.apkg} (build with wk_decks.py first)")
    ensure_fields(args.anki_connect, args.model)
    update_templates(args.anki_connect, args.model)
    print(f"Loading {args.apkg}…")
    by_guid, by_wkid, media_map = load_apkg_payload(args.apkg)
    print(f"apkg notes={len(by_guid)} media={len(media_map)}")
    if media_map:
        print("Storing media…")
        print(f"stored {store_media(args.anki_connect, media_map)}")
    print("Patching notes…")
    updated, missing = patch_notes(args.anki_connect, args.model, by_guid, by_wkid)
    print(f"Done. updated={updated} missing={missing}")
    print(
        "Optional cleanup: Tools → Manage Note Types → delete empty "
        "'WK Update-Safe Kanji Meaning+' if present."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
