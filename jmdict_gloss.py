"""
Offline JMDict gloss lookup for Shadowing candidate enrichment.

Builds a compact expression/reading → English gloss index from the same
jmdict-simplified cache used by ``jmdict_pos`` (``out/jmdict-eng.json``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from jmdict_pos import (
    DEFAULT_JMDICT_DIR,
    default_jmdict_json_path,
    ensure_jmdict_json,
    lemma_key,
    load_jmdict_words,
)

DEFAULT_JMDICT_GLOSS_INDEX_NAME = "jmdict_gloss_index.json"


def _normalize(text: str) -> str:
    return (text or "").strip()


def _entry_kanji_texts(entry: dict) -> List[str]:
    texts: List[str] = []
    for item in entry.get("kanji") or []:
        text = _normalize(item.get("text") or "")
        if text:
            texts.append(text)
    return texts


def _entry_kana_texts(entry: dict) -> List[str]:
    texts: List[str] = []
    for item in entry.get("kana") or []:
        text = _normalize(item.get("text") or "")
        if text:
            texts.append(text)
    return texts


def _entry_pos_tags(entry: dict) -> List[str]:
    tags: List[str] = []
    seen = set()
    for sense in entry.get("sense") or []:
        for tag in sense.get("partOfSpeech") or []:
            text = _normalize(str(tag))
            if text and text not in seen:
                seen.add(text)
                tags.append(text)
    return tags

# Sense POS tags that are never useful as candidate study words.
_SKIP_POS_ONLY = frozenset(
    {
        "prt",
        "aux",
        "aux-v",
        "aux-adj",
        "conj",
        "cop",
        "int",
        "pn",
        "pref",
        "suf",
        "unc",
    }
)

_KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KATAKANA_ONLY_RE = re.compile(r"^[\u30a0-\u30ff\u31f0-\u31ffー]+$")
_HIRAGANA_ONLY_RE = re.compile(r"^[\u3040-\u309fー]+$")


@dataclass(frozen=True)
class JmdictGlossHit:
    expression: str
    reading: str
    gloss: str
    pos: str
    common: bool = False


def default_jmdict_gloss_index_path(cache_dir: Optional[Path] = None) -> Path:
    return (cache_dir or DEFAULT_JMDICT_DIR) / DEFAULT_JMDICT_GLOSS_INDEX_NAME


def _first_english_gloss(entry: dict) -> str:
    for sense in entry.get("sense") or []:
        for gloss in sense.get("gloss") or []:
            if not isinstance(gloss, dict):
                continue
            if gloss.get("lang") not in (None, "", "eng"):
                continue
            text = _normalize(str(gloss.get("text") or ""))
            if text:
                return text
    return ""


def _entry_is_skippable(tags: Sequence[str]) -> bool:
    """True when every POS tag is function-word / uninformative."""
    cleaned = [_normalize(str(tag)).lower() for tag in tags if _normalize(str(tag))]
    if not cleaned:
        return True
    return all(tag in _SKIP_POS_ONLY for tag in cleaned)


def _entry_is_common(entry: dict) -> bool:
    for item in entry.get("kanji") or []:
        if item.get("common"):
            return True
    for item in entry.get("kana") or []:
        if item.get("common"):
            return True
    return False


def _pos_label(tags: Sequence[str]) -> str:
    return ";".join(_normalize(str(tag)) for tag in tags if _normalize(str(tag)))


def build_jmdict_gloss_index(words: Iterable[dict]) -> Dict[str, dict]:
    """Build compact indexes: ``by_key`` and ``by_expression``.

    Values are ``{"g": gloss, "r": reading, "p": pos, "c": 1|0}``.
    Prefer common entries when the same key appears more than once.
    """
    by_key: Dict[str, dict] = {}
    by_expression: Dict[str, List[dict]] = {}

    def _prefer(existing: Optional[dict], candidate: dict) -> dict:
        if existing is None:
            return candidate
        if int(candidate.get("c") or 0) > int(existing.get("c") or 0):
            return candidate
        return existing

    for entry in words:
        tags = _entry_pos_tags(entry)
        if _entry_is_skippable(tags):
            continue
        gloss = _first_english_gloss(entry)
        if not gloss:
            continue
        kana_texts = _entry_kana_texts(entry)
        if not kana_texts:
            continue
        kanji_texts = _entry_kanji_texts(entry)
        surfaces = list(kanji_texts) if kanji_texts else list(kana_texts)
        common = 1 if _entry_is_common(entry) else 0
        pos = _pos_label(tags)
        primary_reading = kana_texts[0]

        for surface in surfaces:
            for kana in kana_texts:
                payload = {"g": gloss, "r": kana, "p": pos, "c": common}
                key = lemma_key(surface, kana)
                by_key[key] = _prefer(by_key.get(key), payload)
            # Surface-only: prefer common + first kana.
            expr_payload = {
                "g": gloss,
                "r": primary_reading,
                "p": pos,
                "c": common,
            }
            bucket = by_expression.setdefault(surface, [])
            # Keep one payload per reading; upgrade to common when seen.
            replaced = False
            for idx, existing in enumerate(bucket):
                if existing.get("r") == primary_reading:
                    bucket[idx] = _prefer(existing, expr_payload)
                    replaced = True
                    break
            if not replaced:
                bucket.append(expr_payload)

        for kana in kana_texts:
            payload = {"g": gloss, "r": kana, "p": pos, "c": common}
            key = lemma_key(kana, kana)
            by_key[key] = _prefer(by_key.get(key), payload)

    # Sort expression buckets: common first, then shorter gloss.
    for surface, bucket in by_expression.items():
        bucket.sort(key=lambda item: (-int(item.get("c") or 0), len(str(item.get("g") or ""))))
        by_expression[surface] = bucket[:4]

    return {"by_key": by_key, "by_expression": by_expression}


def write_jmdict_gloss_index(index: Dict[str, dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return path


def load_jmdict_gloss_index(path: Path) -> Dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected JMDict gloss index shape in {path}")
    by_key = payload.get("by_key")
    by_expression = payload.get("by_expression")
    if not isinstance(by_key, dict) or not isinstance(by_expression, dict):
        raise ValueError(f"Unexpected JMDict gloss index shape in {path}")
    return {"by_key": by_key, "by_expression": by_expression}


def build_and_save_jmdict_gloss_index(
    json_path: Optional[Path] = None,
    index_path: Optional[Path] = None,
    *,
    download: bool = True,
) -> Tuple[Path, Dict[str, dict]]:
    jmdict_path = ensure_jmdict_json(json_path, download=download)
    index = build_jmdict_gloss_index(load_jmdict_words(jmdict_path))
    out = write_jmdict_gloss_index(
        index, index_path or default_jmdict_gloss_index_path()
    )
    return out, index


def load_or_build_jmdict_gloss_index(
    index_path: Optional[Path] = None,
    json_path: Optional[Path] = None,
    *,
    download: bool = True,
    rebuild: bool = False,
) -> Dict[str, dict]:
    dest = index_path or default_jmdict_gloss_index_path()
    if dest.is_file() and not rebuild:
        return load_jmdict_gloss_index(dest)
    _path, index = build_and_save_jmdict_gloss_index(
        json_path=json_path,
        index_path=dest,
        download=download,
    )
    return index


def _hit_from_payload(expression: str, payload: dict) -> JmdictGlossHit:
    return JmdictGlossHit(
        expression=_normalize(expression),
        reading=_normalize(str(payload.get("r") or "")),
        gloss=_normalize(str(payload.get("g") or "")),
        pos=_normalize(str(payload.get("p") or "")),
        common=bool(int(payload.get("c") or 0)),
    )


def lookup_jmdict_gloss(
    expression: str,
    reading: str = "",
    index: Optional[Dict[str, dict]] = None,
) -> Optional[JmdictGlossHit]:
    """Look up a lemma; prefer exact expression|reading, then expression-only."""
    if not index:
        return None
    expr = _normalize(expression)
    read = _normalize(reading)
    if not expr:
        return None
    by_key = index.get("by_key") or {}
    by_expression = index.get("by_expression") or {}

    if read:
        for key in (lemma_key(expr, read), lemma_key(read, read)):
            payload = by_key.get(key)
            if isinstance(payload, dict) and payload.get("g"):
                return _hit_from_payload(expr, payload)

    bucket = by_expression.get(expr) or []
    if isinstance(bucket, list) and bucket:
        payload = bucket[0]
        if isinstance(payload, dict) and payload.get("g"):
            return _hit_from_payload(expr, payload)

    # Kana-only lemma: try reading as expression.
    if read and read != expr:
        bucket = by_expression.get(read) or []
        if isinstance(bucket, list) and bucket:
            payload = bucket[0]
            if isinstance(payload, dict) and payload.get("g"):
                return _hit_from_payload(expr, payload)
    return None


def lemma_has_kanji(lemma: str) -> bool:
    return bool(_KANJI_RE.search(lemma or ""))


def lemma_is_katakana(lemma: str) -> bool:
    text = (lemma or "").strip()
    return bool(text) and bool(_KATAKANA_ONLY_RE.match(text))


def lemma_is_hiragana(lemma: str) -> bool:
    text = (lemma or "").strip()
    return bool(text) and bool(_HIRAGANA_ONLY_RE.match(text))


@dataclass(frozen=True)
class CandidateDictEnrichment:
    """Result of vetting/enriching a Shadowing candidate against JMDict."""

    keep: bool
    reading: str
    hint_glossary: str
    glossary: str
    hit: Optional[JmdictGlossHit] = None


def enrich_shadowing_candidate(
    *,
    lemma: str,
    reading: str = "",
    pos: str = "",
    gloss_index: Optional[Dict[str, dict]] = None,
    atomic_readings: Optional[Dict[str, str]] = None,
    require_dict_for_kanji: bool = True,
) -> CandidateDictEnrichment:
    """Vet and enrich a non-WK candidate.

    - Atomic curated compounds always keep (reading from allowlist if needed).
    - Katakana lemmas keep even without a dict hit (often names).
    - Kanji lemmas without a JMDict hit are dropped when ``require_dict_for_kanji``.
    - Hiragana-only without a hit are dropped (too noisy otherwise).
    """
    lemma_n = _normalize(lemma)
    reading_n = _normalize(reading)
    atomic = atomic_readings or {}
    if lemma_n in atomic:
        hit = lookup_jmdict_gloss(lemma_n, reading_n or atomic[lemma_n], gloss_index)
        final_reading = reading_n or atomic[lemma_n] or (hit.reading if hit else "")
        gloss = hit.gloss if hit else ""
        hint = gloss
        notes = []
        if gloss:
            notes.append(gloss)
        if pos:
            notes.append(f"POS: {pos}")
        elif hit and hit.pos:
            notes.append(f"POS: {hit.pos}")
        else:
            notes.append("curated compound")
        return CandidateDictEnrichment(
            keep=True,
            reading=final_reading,
            hint_glossary=hint,
            glossary=" · ".join(notes),
            hit=hit,
        )

    hit = lookup_jmdict_gloss(lemma_n, reading_n, gloss_index)
    if hit:
        final_reading = reading_n or hit.reading
        # Prefer dictionary reading when candidate reading is empty/truncated-looking.
        if not reading_n or reading_n.endswith(("っ", "ッ")):
            final_reading = hit.reading or reading_n
        notes = [hit.gloss]
        if pos:
            notes.append(f"POS: {pos}")
        elif hit.pos:
            notes.append(f"POS: {hit.pos}")
        return CandidateDictEnrichment(
            keep=True,
            reading=final_reading,
            hint_glossary=hit.gloss,
            glossary=" · ".join(notes),
            hit=hit,
        )

    # No dictionary hit.
    if lemma_is_katakana(lemma_n):
        notes = [f"POS: {pos}"] if pos else ["katakana (no JMDict hit)"]
        return CandidateDictEnrichment(
            keep=True,
            reading=reading_n,
            hint_glossary="",
            glossary=" · ".join(notes),
            hit=None,
        )

    if require_dict_for_kanji and (lemma_has_kanji(lemma_n) or lemma_is_hiragana(lemma_n)):
        return CandidateDictEnrichment(
            keep=False,
            reading=reading_n,
            hint_glossary="",
            glossary="",
            hit=None,
        )

    notes = [f"POS: {pos}"] if pos else ["non-WK candidate"]
    return CandidateDictEnrichment(
        keep=True,
        reading=reading_n,
        hint_glossary="",
        glossary=" · ".join(notes),
        hit=None,
    )
