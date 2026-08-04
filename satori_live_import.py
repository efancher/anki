"""
Live Satori import via AnkiConnect (no .apkg / default importer).

Adds new Immersion · Satori notes and updates existing ones by DuplicateKey /
Satori CardID, while preserving audio fields that the CSV leaves empty.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from satori_decks import (
    SATORI_DECK_NAME,
    SATORI_FIELD_NAMES,
    SATORI_NOTE_TYPE_NAME,
    SatoriCard,
    make_satori_model,
    should_skip_copula_cloze,
    satori_note_field_map,
    satori_note_tags,
)

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
NOTES_INFO_BATCH = 50

# CSV / deck build always ships these empty — never wipe live TTS/clips on update.
SATORI_AUDIO_PRESERVE_FIELDS: Tuple[str, ...] = (
    "Audio",
    "ReadingAudio",
    "SentenceAudio",
    "SentenceAudioEasy",
    "VoicevoxAudio",
    "VoicevoxSpeakerId",
)
# Keep previously backfilled pitch when a later CSV row has no dictionary hit.
SATORI_PITCH_PRESERVE_IF_EMPTY_FIELDS: Tuple[str, ...] = (
    "PitchAccents",
    "PitchPositions",
    "PitchGraphs",
    "SentencePitchGraphs",
)


@dataclass
class SatoriLiveImportResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_copula: int = 0
    note_ids_added: List[int] = field(default_factory=list)
    note_ids_updated: List[int] = field(default_factory=list)


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach AnkiConnect at {base_url}. "
            f"Is Anki open with AnkiConnect installed?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise RuntimeError(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def anki_reachable(base_url: str) -> bool:
    try:
        anki_connect(base_url, "version")
        return True
    except (RuntimeError, TimeoutError, json.JSONDecodeError):
        return False


def merge_satori_fields_for_update(
    new_fields: Mapping[str, str],
    existing_fields: Mapping[str, str],
) -> Dict[str, str]:
    """Prefer new content, but keep non-empty live audio / pitch when new is blank."""
    merged = dict(new_fields)
    for name in SATORI_AUDIO_PRESERVE_FIELDS:
        old = (existing_fields.get(name) or "").strip()
        if old:
            merged[name] = existing_fields[name]
    for name in SATORI_PITCH_PRESERVE_IF_EMPTY_FIELDS:
        if not (merged.get(name) or "").strip():
            old = (existing_fields.get(name) or "").strip()
            if old:
                merged[name] = existing_fields[name]
    return merged


def fields_need_update(
    desired: Mapping[str, str],
    existing: Mapping[str, str],
    *,
    model_fields: Sequence[str],
) -> bool:
    for name in model_fields:
        if name not in desired:
            continue
        if (desired.get(name) or "") != (existing.get(name) or ""):
            return True
    return False


def _note_field_values(note: Mapping[str, object]) -> Dict[str, str]:
    raw = note.get("fields") or {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for name, payload in raw.items():
        if isinstance(payload, dict):
            out[str(name)] = str(payload.get("value") or "")
        else:
            out[str(name)] = str(payload or "")
    return out


def _duplicate_key_card_id(duplicate_key: str) -> str:
    return (duplicate_key or "").split("|", 1)[0]


def build_satori_note_index(
    notes: Sequence[Mapping[str, object]],
) -> Tuple[Dict[str, int], Dict[str, List[int]]]:
    """Indexes: full DuplicateKey → noteId, and CardID prefix → noteIds."""
    by_key: Dict[str, int] = {}
    by_card_id: Dict[str, List[int]] = {}
    for note in notes:
        note_id = int(note.get("noteId") or 0)
        if not note_id:
            continue
        fields = _note_field_values(note)
        duplicate_key = fields.get("DuplicateKey") or ""
        if duplicate_key:
            by_key[duplicate_key] = note_id
            card_id = _duplicate_key_card_id(duplicate_key)
            if card_id:
                by_card_id.setdefault(card_id, []).append(note_id)
    return by_key, by_card_id


def resolve_existing_note_id(
    card: SatoriCard,
    fields: Mapping[str, str],
    *,
    by_key: Mapping[str, int],
    by_card_id: Mapping[str, Sequence[int]],
    notes_by_id: Mapping[int, Mapping[str, object]],
) -> Optional[int]:
    duplicate_key = fields.get("DuplicateKey") or ""
    if duplicate_key and duplicate_key in by_key:
        return by_key[duplicate_key]

    card_id = (card.card_id or "").strip()
    candidates = list(by_card_id.get(card_id) or [])
    if not candidates:
        # DuplicateKey stores html-escaped card_id; try that prefix too.
        escaped_id = _duplicate_key_card_id(duplicate_key)
        if escaped_id and escaped_id != card_id:
            candidates = list(by_card_id.get(escaped_id) or [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        expression = fields.get("Expression") or ""
        sentence = fields.get("Sentence") or ""
        for note_id in candidates:
            existing = _note_field_values(notes_by_id.get(note_id) or {})
            if existing.get("Expression") == expression and existing.get("Sentence") == sentence:
                return note_id
    return None


def ensure_satori_deck(base_url: str, deck_name: str = SATORI_DECK_NAME) -> None:
    anki_connect(base_url, "createDeck", deck=deck_name)


def ensure_satori_model(base_url: str, model_name: str = SATORI_NOTE_TYPE_NAME) -> List[str]:
    """Create note type if missing; add any missing fields (no reorder/fork)."""
    models = set(anki_connect(base_url, "modelNames") or [])
    model = make_satori_model()
    tmpl = model.templates[0]
    if model_name not in models:
        anki_connect(
            base_url,
            "createModel",
            modelName=model_name,
            inOrderFields=list(SATORI_FIELD_NAMES),
            css=model.css,
            isCloze=False,
            cardTemplates=[
                {
                    "Name": tmpl["name"],
                    "Front": tmpl["qfmt"],
                    "Back": tmpl["afmt"],
                }
            ],
        )
        print(f"Created note type {model_name!r}")
    else:
        # Keep templates current without touching field order.
        anki_connect(
            base_url,
            "updateModelTemplates",
            model={
                "name": model_name,
                "templates": {
                    tmpl["name"]: {"Front": tmpl["qfmt"], "Back": tmpl["afmt"]},
                },
            },
        )
        anki_connect(
            base_url,
            "updateModelStyling",
            model={"name": model_name, "css": model.css},
        )

    fields = list(anki_connect(base_url, "modelFieldNames", modelName=model_name) or [])
    for name in SATORI_FIELD_NAMES:
        if name in fields:
            continue
        anki_connect(
            base_url,
            "modelFieldAdd",
            modelName=model_name,
            fieldName=name,
            index=len(fields),
        )
        fields.append(name)
        print(f"  added field {name!r} to {model_name}")
    return fields


def _load_all_satori_notes(
    base_url: str,
    model_name: str,
) -> Dict[int, Mapping[str, object]]:
    note_ids = list(anki_connect(base_url, "findNotes", query=f'note:"{model_name}"') or [])
    notes_by_id: Dict[int, Mapping[str, object]] = {}
    for start in range(0, len(note_ids), NOTES_INFO_BATCH):
        batch = note_ids[start : start + NOTES_INFO_BATCH]
        infos = anki_connect(base_url, "notesInfo", notes=batch) or []
        for info in infos:
            if isinstance(info, dict) and info.get("noteId") is not None:
                notes_by_id[int(info["noteId"])] = info
    return notes_by_id


def import_satori_cards_to_anki(
    cards: Sequence[SatoriCard],
    *,
    base_url: str = DEFAULT_ANKI_CONNECT,
    wk_index: Optional[dict] = None,
    pitch_index: Optional[dict] = None,
    deck_name: str = SATORI_DECK_NAME,
    model_name: str = SATORI_NOTE_TYPE_NAME,
    dry_run: bool = False,
) -> SatoriLiveImportResult:
    """Add/update Satori cloze notes in the live collection."""
    ensure_satori_deck(base_url, deck_name)
    model_fields = ensure_satori_model(base_url, model_name)
    model_field_set: Set[str] = set(model_fields)

    notes_by_id = _load_all_satori_notes(base_url, model_name)
    by_key, by_card_id = build_satori_note_index(list(notes_by_id.values()))

    by_expression = (wk_index or {}).get("by_expression") or {}
    result = SatoriLiveImportResult()

    for card in cards:
        if should_skip_copula_cloze(card.expression, card.reading, card.sentence):
            result.skipped_copula += 1
            continue

        wk_entry = by_expression.get(card.expression)
        desired_all = satori_note_field_map(
            card, wk_entry=wk_entry, pitch_index=pitch_index
        )
        desired = {name: desired_all[name] for name in desired_all if name in model_field_set}
        tags = satori_note_tags(card)

        existing_id = resolve_existing_note_id(
            card,
            desired,
            by_key=by_key,
            by_card_id=by_card_id,
            notes_by_id=notes_by_id,
        )

        if existing_id is None:
            if dry_run:
                result.added += 1
                continue
            note_id = anki_connect(
                base_url,
                "addNote",
                note={
                    "deckName": deck_name,
                    "modelName": model_name,
                    "fields": desired,
                    "tags": tags,
                    "options": {
                        "allowDuplicate": True,
                        "duplicateScope": "deck",
                    },
                },
            )
            note_id_int = int(note_id)
            result.added += 1
            result.note_ids_added.append(note_id_int)
            # Keep index current for later rows in the same CSV.
            by_key[desired.get("DuplicateKey") or ""] = note_id_int
            card_id = _duplicate_key_card_id(desired.get("DuplicateKey") or "")
            if card_id:
                by_card_id.setdefault(card_id, []).append(note_id_int)
            continue

        existing_note = notes_by_id.get(existing_id) or {}
        existing_fields = _note_field_values(existing_note)
        merged = merge_satori_fields_for_update(desired, existing_fields)
        existing_tags = {
            str(tag) for tag in (existing_note.get("tags") or []) if tag is not None
        }
        tags_changed = not set(tags).issubset(existing_tags)

        if not fields_need_update(merged, existing_fields, model_fields=model_fields) and not tags_changed:
            result.unchanged += 1
            continue

        if dry_run:
            result.updated += 1
            result.note_ids_updated.append(existing_id)
            continue

        anki_connect(
            base_url,
            "updateNote",
            note={
                "id": existing_id,
                "fields": merged,
                "tags": sorted(existing_tags | set(tags)),
            },
        )
        result.updated += 1
        result.note_ids_updated.append(existing_id)
        # Refresh cached fields for subsequent matches.
        notes_by_id[existing_id] = {
            **existing_note,
            "fields": {name: {"value": merged.get(name, "")} for name in model_fields},
            "tags": sorted(existing_tags | set(tags)),
        }
        by_key[merged.get("DuplicateKey") or desired.get("DuplicateKey") or ""] = existing_id

    return result


def format_live_import_summary(result: SatoriLiveImportResult) -> str:
    parts = [
        f"added {result.added}",
        f"updated {result.updated}",
        f"unchanged {result.unchanged}",
    ]
    if result.skipped_copula:
        parts.append(f"skipped copula {result.skipped_copula}")
    return ", ".join(parts)
