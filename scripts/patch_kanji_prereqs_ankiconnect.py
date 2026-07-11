#!/usr/bin/env python3
"""Patch PrerequisiteIds onto live WK notes via AnkiConnect.

Anki often keeps notes on renamed note types (Conjugation+++, Dictation++, …)
while genanki .apkg files still target the base model id/name. Field-schema
mismatches then show up as thousands of "notes could not be imported."

This script reads PrerequisiteIds from generated .apkg files (by WkSubjectId)
and writes them onto matching notes in the open collection, adding the field
when missing.

Usage (Anki open with AnkiConnect):
  python3 scripts/patch_kanji_prereqs_ankiconnect.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
OUT_DIR = REPO_ROOT / "out"
ANKI_CONNECT_URL = "http://127.0.0.1:8765"
BATCH_SIZE = 40

DEFAULT_APKGS: Tuple[Path, ...] = (
    OUT_DIR / "wk_dictation.apkg",
    OUT_DIR / "wk_conjugations_verbs.apkg",
    OUT_DIR / "wk_conjugations_adjectives.apkg",
    OUT_DIR / "wk_conjugations_reverse.apkg",
    OUT_DIR / "wk_verb_types.apkg",
    OUT_DIR / "wk_adjective_types.apkg",
)

TARGET_NOTE_TYPES: Tuple[str, ...] = (
    "WK Update-Safe Dictation++",
    "WK Update-Safe Dictation+++",
    "WK Update-Safe Conjugation+++",
    "WK Update-Safe Conjugation++++",
    "WK Update-Safe Conjugation Reverse++++",
    "WK Update-Safe Conjugation Reverse+++++",
    "WK Update-Safe Word Class++",
    "WK Update-Safe Word Class+++",
)


def anki_connect(action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        ANKI_CONNECT_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {ANKI_CONNECT_URL}. "
            f"Is Anki open with AnkiConnect installed?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"{action}: {payload['error']}")
    return payload["result"]


def anki_multi(actions: Sequence[dict]) -> list:
    return anki_connect("multi", actions=list(actions))  # type: ignore[arg-type]


def load_prereq_map_from_apkg(apkg_path: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(apkg_path) as archive:
            archive.extractall(tmp)
        db_path = Path(tmp) / "collection.anki21"
        if not db_path.exists():
            db_path = Path(tmp) / "collection.anki2"
        con = sqlite3.connect(db_path)
        models = json.loads(con.execute("select models from col").fetchone()[0])
        field_index_by_mid: Dict[int, Dict[str, int]] = {}
        for mid_str, model in models.items():
            names = [field["name"] for field in model["flds"]]
            if "WkSubjectId" not in names or "PrerequisiteIds" not in names:
                continue
            field_index_by_mid[int(mid_str)] = {
                "WkSubjectId": names.index("WkSubjectId"),
                "PrerequisiteIds": names.index("PrerequisiteIds"),
            }
        for mid, flds in con.execute("select mid, flds from notes"):
            indexes = field_index_by_mid.get(int(mid))
            if not indexes:
                continue
            parts = flds.split("\x1f")
            subject_id = parts[indexes["WkSubjectId"]].strip()
            prereq = parts[indexes["PrerequisiteIds"]].strip()
            if subject_id and prereq:
                mapping[subject_id] = prereq
        con.close()
    return mapping


def ensure_prerequisite_field(model_name: str) -> bool:
    fields = anki_connect("modelFieldNames", modelName=model_name)
    assert isinstance(fields, list)
    if "PrerequisiteIds" in fields:
        return False
    index = fields.index("Meta") if "Meta" in fields else len(fields)
    anki_connect(
        "modelFieldAdd",
        modelName=model_name,
        fieldName="PrerequisiteIds",
        index=index,
    )
    print(f"  added PrerequisiteIds field to {model_name}")
    return True


def patch_note_type(model_name: str, prereq_by_subject: Dict[str, str]) -> Tuple[int, int]:
    note_ids = anki_connect("findNotes", query=f'note:"{model_name}"') or []
    assert isinstance(note_ids, list)
    if not note_ids:
        return 0, 0
    ensure_prerequisite_field(model_name)
    updated = 0
    missing = 0
    total = len(note_ids)
    for start in range(0, total, BATCH_SIZE):
        batch = note_ids[start : start + BATCH_SIZE]
        infos = anki_connect("notesInfo", notes=batch)
        assert isinstance(infos, list)
        actions = []
        for info in infos:
            fields = info["fields"]
            subject = (fields.get("WkSubjectId") or {}).get("value", "").strip()
            prereq = prereq_by_subject.get(subject, "")
            if not prereq:
                missing += 1
                continue
            current = (fields.get("PrerequisiteIds") or {}).get("value", "")
            if current == prereq:
                continue
            actions.append(
                {
                    "action": "updateNoteFields",
                    "params": {
                        "note": {
                            "id": info["noteId"],
                            "fields": {"PrerequisiteIds": prereq},
                        }
                    },
                }
            )
        if actions:
            anki_multi(actions)
            updated += len(actions)
        done = min(start + BATCH_SIZE, total)
        print(f"  {model_name}: {done}/{total} scanned, {updated} updated", flush=True)
    return updated, missing


def existing_target_models(candidates: Sequence[str]) -> List[str]:
    names = set(anki_connect("modelNames") or [])
    return [name for name in candidates if name in names]


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apkg",
        type=Path,
        action="append",
        default=None,
        help="Source .apkg (repeatable). Default: dictation + conjugation/type apkgs.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    apkg_paths = [path.expanduser().resolve() for path in (args.apkg or DEFAULT_APKGS)]
    prereq_by_subject: Dict[str, str] = {}
    for apkg_path in apkg_paths:
        if not apkg_path.is_file():
            print(f"skip missing {apkg_path.name}")
            continue
        print(f"Reading {apkg_path.name}...", flush=True)
        chunk = load_prereq_map_from_apkg(apkg_path)
        prereq_by_subject.update(chunk)
        print(f"  +{len(chunk)} subject ids (map size {len(prereq_by_subject)})", flush=True)

    if not prereq_by_subject:
        raise SystemExit("No PrerequisiteIds found in source apkgs.")

    print("Checking AnkiConnect...", flush=True)
    anki_connect("version")
    targets = existing_target_models(TARGET_NOTE_TYPES)
    if not targets:
        raise SystemExit("No target note types found in the collection.")
    print(f"Target note types: {', '.join(targets)}", flush=True)

    total_updated = 0
    for model_name in targets:
        updated, missing = patch_note_type(model_name, prereq_by_subject)
        print(f"{model_name}: updated {updated}, missing map {missing}", flush=True)
        total_updated += updated

    print(f"Done. Patched PrerequisiteIds on {total_updated} notes.")
    print("Run Tools → WK Run Unlock Pass so conjugations/types unlock via Kanji Meaning Anchor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
