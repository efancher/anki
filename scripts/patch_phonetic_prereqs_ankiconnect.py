#!/usr/bin/env python3
"""Patch PrerequisiteIds onto phonetic-family notes via AnkiConnect.

Standalone wk_phonetic_families.apkg often fails to import because collection
notes live on a renamed note type (e.g. WK Update-Safe Phonetic Drill++) while
the .apkg targets the base model name/id. This script copies PrerequisiteIds
from the generated .apkg onto existing notes instead.

Usage:
  python wk_decks.py --from-config --deck phonetic-families --no-bundle
  python scripts/patch_phonetic_prereqs_ankiconnect.py

Requires Anki open with AnkiConnect. Default model: WK Update-Safe Phonetic Drill++
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_APKG = REPO_ROOT / "out" / "wk_phonetic_families.apkg"
DEFAULT_MODEL = "WK Update-Safe Phonetic Drill++"
ANKI_CONNECT_URL = "http://localhost:8765"
BATCH_SIZE = 50


def anki_connect(action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        ANKI_CONNECT_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            "Could not reach AnkiConnect at "
            f"{ANKI_CONNECT_URL}. Is Anki open with AnkiConnect installed?\n"
            f"{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action} failed: {payload['error']}")
    return payload["result"]


def load_prereq_map(apkg_path: Path) -> dict[tuple[str, str], str]:
    with zipfile.ZipFile(apkg_path) as archive:
        db_bytes = archive.read("collection.anki2")
    db_path = Path(tempfile.gettempdir()) / "wk_phonetic_prereq_patch.db"
    db_path.write_bytes(db_bytes)
    conn = sqlite3.connect(db_path)
    models = json.loads(conn.execute("SELECT models FROM col").fetchone()[0])
    field_names: list[str] | None = None
    for model in models.values():
        if str(model.get("name", "")).startswith("WK Update-Safe Phonetic Drill"):
            field_names = [field["name"] for field in model["flds"]]
            break
    if field_names is None:
        raise SystemExit(f"No phonetic drill model found in {apkg_path}")
    index = {name: position for position, name in enumerate(field_names)}
    for required in ("WkSubjectId", "PhoneticPiece", "PrerequisiteIds"):
        if required not in index:
            raise SystemExit(f"{apkg_path} model is missing field {required!r}")
    mapping: dict[tuple[str, str], str] = {}
    for _guid, flds in conn.execute("SELECT guid, flds FROM notes"):
        parts = flds.split("\x1f")
        key = (parts[index["WkSubjectId"]], parts[index["PhoneticPiece"]])
        mapping[key] = parts[index["PrerequisiteIds"]]
    conn.close()
    return mapping


def resolve_model_name(preferred: str) -> str:
  names = anki_connect("modelNames")
  if preferred in names:
    return preferred
  candidates = [name for name in names if name.startswith("WK Update-Safe Phonetic Drill")]
  if not candidates:
    raise SystemExit("No WK Update-Safe Phonetic Drill note type found in Anki.")
  # Prefer the longest ++ suffix — that's where live phonetic notes usually are.
  return max(candidates, key=len)


def main() -> None:
    apkg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_APKG
    if not apkg_path.is_file():
        raise SystemExit(f"Missing {apkg_path}. Run phonetic-families deck generation first.")

    prereq_map = load_prereq_map(apkg_path)
    model_name = resolve_model_name(DEFAULT_MODEL)
    print(f"Using note type: {model_name}")
    print(f"Loaded {len(prereq_map)} prereq rows from {apkg_path.name}")

    fields = anki_connect("modelFieldNames", modelName=model_name)
    if "PrerequisiteIds" not in fields:
        meta_index = fields.index("Meta") if "Meta" in fields else len(fields)
        anki_connect(
            "modelFieldAdd",
            modelName=model_name,
            fieldName="PrerequisiteIds",
            index=meta_index,
        )
        print("Added PrerequisiteIds field before Meta")
        fields = anki_connect("modelFieldNames", modelName=model_name)

    note_ids = anki_connect(
        "findNotes",
        query=f'deck:"WaniKani Phonetic Families" note:"{model_name}"',
    )
    if not note_ids:
      note_ids = anki_connect("findNotes", query='deck:"WaniKani Phonetic Families"')
    print(f"Found {len(note_ids)} phonetic notes in Anki")

    updated = 0
    missing = 0
    for start in range(0, len(note_ids), BATCH_SIZE):
        chunk = note_ids[start : start + BATCH_SIZE]
        for info in anki_connect("notesInfo", notes=chunk):
            field_values = info["fields"]
            key = (
                field_values["WkSubjectId"]["value"],
                field_values["PhoneticPiece"]["value"],
            )
            prereq = prereq_map.get(key)
            if prereq is None:
                missing += 1
                continue
            current = field_values.get("PrerequisiteIds", {}).get("value", "")
            if current == prereq:
                continue
            anki_connect(
                "updateNoteFields",
                note={"id": info["noteId"], "fields": {"PrerequisiteIds": prereq}},
            )
            updated += 1

    print(f"Patched PrerequisiteIds on {updated} notes ({missing} without apkg mapping).")
    print("Run Tools → WK Run Unlock Pass in Anki (after syncing wk_unlock add-on).")


if __name__ == "__main__":
    main()
