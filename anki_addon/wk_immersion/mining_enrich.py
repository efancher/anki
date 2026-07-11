"""
Post-mine enrichment for WK Migaku Immersion notes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from .mining_logic import enrich_mining_note_fields

MINING_VOCAB_INDEX_FILENAME = "wk_mining_vocab_index.json"

FIELD_EXPRESSION = "Expression"
FIELD_READING = "Reading"
FIELD_SENTENCE = "Sentence"
FIELD_SENTENCE_FURIGANA = "SentenceFurigana"
FIELD_GLOSSARY = "Glossary"
FIELD_TRANSLATION = "Translation"
FIELD_DUPLICATE_KEY = "DuplicateKey"

ENRICHMENT_FIELD_MAP = {
    "Expression": "expression",
    "Reading": "reading",
    "Sentence": "sentence",
    "ClozeSentence": "cloze_sentence",
    "WkSubjectId": "wk_subject_id",
    "PrerequisiteIds": "prerequisite_ids",
    "WkMeaning": "wk_meaning",
    "HintGlossary": "hint_glossary",
    "HintStage": "hint_stage",
    "ShowEnglish": "show_english",
    "ShowKana": "show_kana",
    "ShowJjBack": "show_jj_back",
    "SentenceKana": "sentence_kana",
    "DictLinksJa": "dict_links_ja",
    "DictLinksEn": "dict_links_en",
}


def candidate_vocab_index_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("WK_MINING_VOCAB_INDEX")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.extend(
        [
            Path.home() / "anki" / "out" / MINING_VOCAB_INDEX_FILENAME,
            Path.cwd() / "out" / MINING_VOCAB_INDEX_FILENAME,
            Path.cwd() / MINING_VOCAB_INDEX_FILENAME,
        ]
    )
    seen = set()
    unique: List[Path] = []
    for path in paths:
        key = str(path.expanduser())
        if key not in seen:
            seen.add(key)
            unique.append(path.expanduser())
    return unique


def load_vocab_index() -> Optional[dict]:
    for path in candidate_vocab_index_paths():
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    return None


def lookup_wk_vocab(expression: str, reading: str, index: dict) -> Optional[dict]:
    expr = (expression or "").strip()
    read = (reading or "").strip()
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


def apply_mining_enrichment(note, *, field_map: Dict[str, int]) -> bool:
    def field_value(name: str) -> str:
        ord_index = field_map.get(name)
        if ord_index is None:
            return ""
        return note.fields[ord_index] or ""

    expression = field_value(FIELD_EXPRESSION)
    reading = field_value(FIELD_READING)
    sentence = field_value(FIELD_SENTENCE)
    if not expression and not reading:
        return False

    index = load_vocab_index()
    wk_entry = lookup_wk_vocab(expression, reading, index) if index else None
    enrichment = enrich_mining_note_fields(
        expression=expression,
        reading=reading,
        sentence=sentence,
        sentence_furigana=field_value(FIELD_SENTENCE_FURIGANA),
        glossary=field_value(FIELD_GLOSSARY),
        translation=field_value(FIELD_TRANSLATION),
        wk_entry=wk_entry,
    )

    changed = False
    duplicate_key = field_value(FIELD_DUPLICATE_KEY).strip()
    if not duplicate_key:
        duplicate_key = (
            f"{enrichment.expression}|{enrichment.sentence}"
            if enrichment.sentence
            else enrichment.expression
        )
        dup_index = field_map.get(FIELD_DUPLICATE_KEY)
        if dup_index is not None and note.fields[dup_index] != duplicate_key:
            note.fields[dup_index] = duplicate_key
            changed = True
    for field_name, attr in ENRICHMENT_FIELD_MAP.items():
        ord_index = field_map.get(field_name)
        if ord_index is None:
            continue
        value = getattr(enrichment, attr)
        if note.fields[ord_index] != value:
            note.fields[ord_index] = value
            changed = True
    return changed
