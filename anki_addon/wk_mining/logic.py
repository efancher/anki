"""
Pure logic for wk_mining (testable without Anki runtime).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

WK_LOCKED_TAG = "wk-locked"
WK_CORE_TAG = "wk-core"
MINING_TAG = "yomitan-mining"
MINING_NOTE_TYPE = "WK Update-Safe Yomitan Mining"
DEFAULT_MATURE_MIN_INTERVAL_DAYS = 7
DEFAULT_BURNED_INTERVAL_DAYS = 365
ANKI_QUEUE_SUSPENDED = -1

_KANA_TO_ASCII = str.maketrans(
    "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロワヲンー",
    "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろわをんー",
)


@dataclass(frozen=True)
class CardState:
    ivl: int
    queue: int


@dataclass(frozen=True)
class NoteUnlockState:
    note_id: int
    wk_subject_id: Optional[int]
    tags: Tuple[str, ...]
    cards: Tuple[CardState, ...]


def candidate_vocab_lookup_paths() -> List[Path]:
    paths = [
        Path.home() / "anki" / "out" / "wk_vocab_lookup.json",
        Path.cwd() / "out" / "wk_vocab_lookup.json",
        Path.cwd() / "wk_vocab_lookup.json",
    ]
    seen: Set[str] = set()
    unique: List[Path] = []
    for path in paths:
        key = str(path.expanduser())
        if key not in seen:
            seen.add(key)
            unique.append(path.expanduser())
    return unique


def load_vocab_lookup(path: Optional[Path] = None) -> Dict[str, List[dict]]:
    if path is None:
        for candidate in candidate_vocab_lookup_paths():
            if candidate.is_file():
                path = candidate
                break
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries, dict):
        return {}
    return {str(key): list(value) for key, value in entries.items()}


def normalize_mining_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text.strip())
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def normalize_mining_reading(reading: str) -> str:
    if not reading:
        return ""
    return normalize_mining_text(reading).translate(_KANA_TO_ASCII)


def match_wk_vocab_id(
    expression: str,
    reading: str,
    lookup: Mapping[str, Sequence[dict]],
) -> Optional[int]:
    key = normalize_mining_text(expression)
    if not key:
        return None
    candidates = list(lookup.get(key) or [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return int(candidates[0]["id"])
    norm_reading = normalize_mining_reading(reading)
    if norm_reading:
        reading_matches = [
            entry for entry in candidates if norm_reading in (entry.get("readings") or [])
        ]
        if len(reading_matches) == 1:
            return int(reading_matches[0]["id"])
        if reading_matches:
            return int(reading_matches[0]["id"])
    levels = {entry["level"] for entry in candidates}
    if len(levels) == 1:
        return int(candidates[0]["id"])
    return None


def card_meets_maturity(card: CardState, *, mature_min_interval_days: int, burned_interval_days: int) -> bool:
    if card.queue == ANKI_QUEUE_SUSPENDED:
        return False
    if card.ivl >= burned_interval_days:
        return True
    return card.ivl >= mature_min_interval_days


def build_mature_subject_ids(
    notes: Sequence[NoteUnlockState],
    *,
    mature_min_interval_days: int = DEFAULT_MATURE_MIN_INTERVAL_DAYS,
    burned_interval_days: int = DEFAULT_BURNED_INTERVAL_DAYS,
) -> Set[int]:
    mature: Set[int] = set()
    for note in notes:
        if note.wk_subject_id is None:
            continue
        active = [card for card in note.cards if card.queue != ANKI_QUEUE_SUSPENDED]
        if not active:
            continue
        if all(
            card_meets_maturity(
                card,
                mature_min_interval_days=mature_min_interval_days,
                burned_interval_days=burned_interval_days,
            )
            for card in active
        ):
            mature.add(note.wk_subject_id)
    return mature


def link_mining_note_fields(
    fields: Mapping[str, str],
    lookup: Mapping[str, Sequence[dict]],
    mature_subject_ids: Set[int],
) -> Tuple[Dict[str, str], List[str], List[str]]:
    expression = fields.get("Expression") or ""
    reading = fields.get("Reading") or ""
    current_id = (fields.get("WkSubjectId") or "").strip()
    updates: Dict[str, str] = {}
    add_tags: List[str] = []
    remove_tags: List[str] = []

    matched_id = match_wk_vocab_id(expression, reading, lookup)
    if matched_id is not None and str(matched_id) != current_id:
        updates["WkSubjectId"] = str(matched_id)

    subject_id = matched_id
    if subject_id is None and current_id.isdigit():
        subject_id = int(current_id)

    if subject_id is not None and subject_id not in mature_subject_ids:
        add_tags.append(WK_LOCKED_TAG)
    elif subject_id is not None and subject_id in mature_subject_ids:
        remove_tags.append(WK_LOCKED_TAG)

    return updates, add_tags, remove_tags


def duplicate_sentence_keys(notes: Iterable[Mapping[str, str]]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for fields in notes:
        sentence = normalize_mining_text(fields.get("Sentence") or "")
        duplicate_key = fields.get("DuplicateKey") or ""
        if not sentence or not duplicate_key:
            continue
        groups.setdefault(sentence, []).append(duplicate_key)
    return {key: keys for key, keys in groups.items() if len(keys) > 1}
