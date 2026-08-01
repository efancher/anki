#!/usr/bin/env python3
"""Add missing Shadowing Immersion notes to Anki from project directories.

Unlike File → Import of ``out/wk_shadowing.apkg`` (which overwrites when you build
a second project, and can duplicate or blank media), this walks one or more
shadowing projects, builds the same fields the package uses, and ``addNote``s
only when ``DuplicateKey`` is not already in the collection. Existing notes —
including Target/Reading TTS — are left alone.

Usage (Anki open with AnkiConnect):

  python3 scripts/live_import_shadowing_ankiconnect.py ~/shadowing/cli/projects/FkX4A-ZLBrc
  python3 scripts/live_import_shadowing_ankiconnect.py ~/shadowing/cli/projects/*
  python3 scripts/live_import_shadowing_ankiconnect.py ~/shadowing/cli/projects --dry-run
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from immersion_pitch import (  # noqa: E402
    load_immersion_pitch_index,
    resolve_pitch_dict_path,
)
from mining_vocab_index import lookup_wk_vocab  # noqa: E402
from shadowing_decks import (  # noqa: E402
    SHADOWING_DECK_NAME,
    SHADOWING_FIELD_NAMES,
    SHADOWING_NOTE_TYPE_NAME,
    ShadowingProject,
    load_default_wk_index,
    load_shadowing_input,
    shadowing_note_fields,
    stage_clip_media,
    validate_selected_vocabulary,
)
from satori_decks import should_skip_copula_cloze  # noqa: E402
from shadowing_match import match_wk_vocab_in_sentence  # noqa: E402

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
ANKI_CONNECT_TIMEOUT_SECONDS = 180
NOTES_INFO_BATCH = 250


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=ANKI_CONNECT_TIMEOUT_SECONDS) as response:
        payload = json.load(response)
    if payload.get("error"):
        raise RuntimeError(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def field_value(fields: dict, name: str) -> str:
    return ((fields.get(name) or {}).get("value") or "").strip()


def existing_duplicate_keys(base_url: str, model_name: str) -> Set[str]:
    note_ids = list(anki_connect(base_url, "findNotes", query=f'note:"{model_name}"') or [])
    keys: Set[str] = set()
    for start in range(0, len(note_ids), NOTES_INFO_BATCH):
        batch = note_ids[start : start + NOTES_INFO_BATCH]
        for info in anki_connect(base_url, "notesInfo", notes=batch) or []:
            key = field_value(info.get("fields") or {}, "DuplicateKey")
            if key:
                keys.add(key)
    return keys


def store_media_if_needed(base_url: str, path: Optional[Path], dry_run: bool) -> None:
    if path is None or not path.is_file():
        return
    if dry_run:
        return
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    anki_connect(base_url, "storeMediaFile", filename=path.name, data=data)


def resolve_projects(paths: Sequence[Path]) -> List[Path]:
    found: List[Path] = []
    seen: Set[Path] = set()
    for raw in paths:
        path = raw.expanduser().resolve()
        candidates: List[Path] = []
        if path.is_file() and path.suffix.lower() in {".zip", ".mining.zip"} or path.name.endswith(
            ".mining.zip"
        ):
            candidates = [path]
        elif path.is_dir():
            if (path / "sentences.json").is_file() or (path / "source.json").is_file():
                candidates = [path]
            else:
                candidates = sorted(
                    child
                    for child in path.iterdir()
                    if child.is_dir() and (child / "sentences.json").is_file()
                )
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
    return found


def iter_wk_note_payloads(
    project: ShadowingProject,
    *,
    index: dict,
    pitch_index: Optional[dict],
    media_dir: Path,
    include_auto_caption: bool,
) -> Iterable[Tuple[Dict[str, str], List[str], Optional[Path]]]:
    """Yield (fields_by_name, tags, media_path) for each WK cloze note."""
    use_curated = project.curated or any(
        sentence.selected_vocabulary for sentence in project.sentences
    )
    for sentence in project.sentences:
        if not include_auto_caption and sentence.transcript_status == "auto-caption":
            continue
        audio_name, media_path = stage_clip_media(project, sentence, media_dir)

        if use_curated:
            if not sentence.selected_vocabulary:
                continue
            for selection in sentence.selected_vocabulary:
                validate_selected_vocabulary(
                    sentence.japanese,
                    selection,
                    sentence_id=sentence.sentence_id,
                )
                wk_entry = lookup_wk_vocab(
                    selection.expression, selection.reading, index
                )
                if not wk_entry:
                    continue
                if should_skip_copula_cloze(
                    selection.expression,
                    selection.reading or str(wk_entry.get("reading") or ""),
                    sentence.japanese,
                    surface=selection.surface,
                ):
                    continue
                values = shadowing_note_fields(
                    source=project.source,
                    sentence=sentence,
                    expression=selection.expression,
                    reading=selection.reading or str(wk_entry.get("reading") or ""),
                    wk_entry=wk_entry,
                    audio_filename=audio_name,
                    transcript_tag=sentence.transcript_status,
                    surface=selection.surface,
                    pitch_index=pitch_index,
                )
                fields = dict(zip(SHADOWING_FIELD_NAMES, values))
                tags = [
                    "immersion",
                    "shadowing-mining",
                    f"shadowing-{sentence.transcript_status}",
                    "shadowing-curated",
                ]
                yield fields, tags, media_path
            continue

        for match in match_wk_vocab_in_sentence(
            sentence.japanese,
            index,
            sentence_reading=sentence.reading,
        ):
            if should_skip_copula_cloze(
                match.expression,
                match.reading,
                sentence.japanese,
                surface=match.surface,
            ):
                continue
            values = shadowing_note_fields(
                source=project.source,
                sentence=sentence,
                expression=match.expression,
                reading=match.reading,
                wk_entry=match.wk_entry,
                audio_filename=audio_name,
                transcript_tag=sentence.transcript_status,
                surface=match.surface,
                pitch_index=pitch_index,
            )
            fields = dict(zip(SHADOWING_FIELD_NAMES, values))
            tags = [
                "immersion",
                "shadowing-mining",
                f"shadowing-{sentence.transcript_status}",
            ]
            yield fields, tags, media_path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "projects",
        nargs="+",
        type=Path,
        help="Shadowing project dir(s), parent dir, or .mining.zip",
    )
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument(
        "--wk-index",
        type=Path,
        default=REPO_ROOT / "out" / "wk_mining_vocab_index.json",
    )
    parser.add_argument("--pitch-dict", type=Path, default=None)
    parser.add_argument("--no-pitch", action="store_true")
    parser.add_argument("--skip-auto-caption", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    project_paths = resolve_projects(args.projects)
    if not project_paths:
        raise SystemExit("No shadowing projects found.")

    try:
        models = set(anki_connect(args.anki_connect, "modelNames") or [])
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {args.anki_connect}. Is Anki open?\n{exc}"
        ) from exc
    if SHADOWING_NOTE_TYPE_NAME not in models:
        raise SystemExit(
            f"Note type {SHADOWING_NOTE_TYPE_NAME!r} missing — import an .apkg once first."
        )

    decks = set(anki_connect(args.anki_connect, "deckNames") or [])
    if SHADOWING_DECK_NAME not in decks:
        anki_connect(args.anki_connect, "createDeck", deck=SHADOWING_DECK_NAME)

    index = load_default_wk_index(args.wk_index if args.wk_index.is_file() else None)
    pitch_index = None
    if not args.no_pitch:
        pitch_path = resolve_pitch_dict_path(
            args.pitch_dict.expanduser().resolve() if args.pitch_dict else None
        )
        if pitch_path is not None:
            print(f"Loading pitch dictionary: {pitch_path}")
            pitch_index = load_immersion_pitch_index(pitch_path)

    existing = existing_duplicate_keys(args.anki_connect, SHADOWING_NOTE_TYPE_NAME)
    print(f"Existing {SHADOWING_NOTE_TYPE_NAME} DuplicateKeys: {len(existing)}")

    media_dir = REPO_ROOT / "out" / "media" / "shadowing"
    media_dir.mkdir(parents=True, exist_ok=True)

    added = 0
    skipped = 0
    for project_path in project_paths:
        project = load_shadowing_input(project_path)
        print(f"\nProject: {project.source.title} ({project.source.source_id})")
        for fields, tags, media_path in iter_wk_note_payloads(
            project,
            index=index,
            pitch_index=pitch_index,
            media_dir=media_dir,
            include_auto_caption=not args.skip_auto_caption,
        ):
            key = fields.get("DuplicateKey") or ""
            if not key or key in existing:
                skipped += 1
                continue
            print(
                f"  add {fields.get('Expression')} ({fields.get('Reading')}) "
                f"← {fields.get('Sentence', '')[:40]}"
            )
            if args.dry_run:
                added += 1
                existing.add(key)
                continue
            store_media_if_needed(args.anki_connect, media_path, dry_run=False)
            anki_connect(
                args.anki_connect,
                "addNote",
                note={
                    "deckName": SHADOWING_DECK_NAME,
                    "modelName": SHADOWING_NOTE_TYPE_NAME,
                    "fields": fields,
                    "tags": tags,
                    "options": {"allowDuplicate": True, "duplicateScope": "deck"},
                },
            )
            existing.add(key)
            added += 1

    print(
        f"\n{'Would add' if args.dry_run else 'Added'} {added} notes; "
        f"skipped {skipped} already present"
        + (" (dry-run)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
