"""
mining_logic.py

Shared helpers for Yomitan sentence mining: duplicate keys and WK vocab lookup.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Mapping, Optional, Sequence

MINING_DUPLICATE_KEY_SEP = "|"
_KANA_TO_ASCII = str.maketrans(
    "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロワヲンー",
    "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろわをんー",
)


def normalize_mining_text(text: str) -> str:
    """Normalize text for duplicate-key comparison."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text.strip())
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def normalize_mining_reading(reading: str) -> str:
    if not reading:
        return ""
    return normalize_mining_text(reading).translate(_KANA_TO_ASCII)


def mining_duplicate_key(expression: str, sentence: str = "") -> str:
    """
    Anki first-field duplicate key for mined cards.

    Same expression in different sentences → different keys.
    Empty sentence → expression-only key (term mining).
    """
    expr = normalize_mining_text(expression)
    sent = normalize_mining_text(sentence)
    if not sent:
        return expr
    return f"{expr}{MINING_DUPLICATE_KEY_SEP}{sent}"


def build_vocab_lookup(vocab_items: Sequence[dict]) -> Dict[str, List[dict]]:
    """Map surface form → WK vocabulary entries (may be ambiguous)."""
    lookup: Dict[str, List[dict]] = {}
    for subject in vocab_items:
        if subject.get("object") != "vocabulary":
            continue
        data = subject.get("data") or {}
        characters = data.get("characters")
        if not characters:
            continue
        key = normalize_mining_text(str(characters))
        readings: List[str] = []
        for item in data.get("readings") or []:
            reading = item.get("reading")
            if reading:
                readings.append(normalize_mining_reading(str(reading)))
        entry = {
            "id": int(subject["id"]),
            "level": int(data.get("level") or 0),
            "readings": sorted(set(readings)),
        }
        lookup.setdefault(key, []).append(entry)
    for entries in lookup.values():
        entries.sort(key=lambda item: (item["level"], item["id"]))
    return lookup


def match_wk_vocab_id(
    expression: str,
    reading: str,
    lookup: Mapping[str, Sequence[dict]],
) -> Optional[int]:
    """Pick a WK vocabulary id for a mined term, or None if unknown/ambiguous."""
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
        if len(reading_matches) > 1:
            return int(reading_matches[0]["id"])

    levels = {entry["level"] for entry in candidates}
    if len(levels) == 1:
        return int(candidates[0]["id"])
    return None


def sentence_already_in_set(sentence: str, known_sentences: Mapping[str, object]) -> bool:
    """True when a normalized sentence matches an existing note or WK cloze."""
    key = normalize_mining_text(sentence)
    if not key:
        return False
    return key in known_sentences
