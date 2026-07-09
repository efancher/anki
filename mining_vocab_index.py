"""
mining_vocab_index.py

Compact WK vocabulary lookup for Yomitan mining enrichment (post-mine add-on).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

MINING_VOCAB_INDEX_FILENAME = "wk_mining_vocab_index.json"


def _normalize_key(text: str) -> str:
    return (text or "").strip()


def build_mining_vocab_index(vocab_items: Sequence[dict]) -> dict:
    by_expression: Dict[str, dict] = {}
    by_reading: Dict[str, List[int]] = {}
    for vocab in vocab_items:
        if vocab.get("object") != "vocabulary":
            continue
        data = vocab.get("data") or {}
        expr = _normalize_key(data.get("characters") or "")
        reading = _normalize_key(
            next(
                (
                    item.get("reading")
                    for item in (data.get("readings") or [])
                    if item.get("reading")
                ),
                "",
            )
        )
        meanings = [
            str(item.get("meaning") or "").strip()
            for item in (data.get("meanings") or [])
            if item.get("meaning")
        ]
        component_ids = data.get("component_subject_ids") or []
        entry = {
            "id": int(vocab["id"]),
            "expression": expr,
            "reading": reading,
            "meaning": "; ".join(meanings[:3]),
            "prerequisite_ids": ",".join(str(component_id) for component_id in component_ids),
        }
        if expr:
            by_expression[expr] = entry
        if reading:
            by_reading.setdefault(reading, [])
            if entry["id"] not in by_reading[reading]:
                by_reading[reading].append(entry["id"])
    return {"by_expression": by_expression, "by_reading": by_reading}


def write_mining_vocab_index(vocab_items: Sequence[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / MINING_VOCAB_INDEX_FILENAME
    payload = build_mining_vocab_index(vocab_items)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_mining_vocab_index(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def lookup_wk_vocab(
    expression: str,
    reading: str,
    index: dict,
) -> Optional[dict]:
    expr = _normalize_key(expression)
    read = _normalize_key(reading)
    by_expression = index.get("by_expression") or {}
    if expr and expr in by_expression:
        return dict(by_expression[expr])
    by_reading = index.get("by_reading") or {}
    if read and read in by_reading:
        for vocab_id in by_reading[read]:
            for entry in by_expression.values():
                if entry.get("id") == vocab_id:
                    return dict(entry)
    return None
