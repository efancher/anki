"""Morphology-aware WaniKani matching for Shadowing project sentences.

Uses fugashi/UniDic when available; otherwise falls back to longest-match against
the WK expression index (with kanji-stem matching for conjugated forms).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from mining_vocab_index import lookup_wk_vocab

# CJK unified + extension A + compatibility ideographs.
_KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KATAKANA_WORD_RE = re.compile(r"[\u30a0-\u30ff\u31f0-\u31ffー]{2,}")
_KANJI_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{1,}")
_HIRAGANA_CHAR_RE = re.compile(r"[\u3041-\u3096]")
_KATAKANA_CHAR_RE = re.compile(r"[\u30A1-\u30F6]")

# UniDic coarse POS prefixes treated as content words for candidate generation.
_CONTENT_POS_PREFIXES = (
    "名詞",
    "動詞",
    "形容詞",
    "形状詞",
    "副詞",
)

_EXCLUDED_POS_PREFIXES = (
    "助詞",
    "助動詞",
    "記号",
    "補助記号",
    "連体詞",
    "感動詞",
    "接続詞",
    "接頭辞",
    "接尾辞",
)

# Very common function / filler forms to drop from candidates even if POS slips.
_STOPWORDS = frozenset(
    {
        "する",
        "なる",
        "ある",
        "いる",
        "ない",
        "れる",
        "られる",
        "せる",
        "させる",
        "です",
        "ます",
        "だ",
        "である",
        "こと",
        "もの",
        "ため",
        "よう",
        "そう",
        "これ",
        "それ",
        "あれ",
        "どれ",
        "ここ",
        "そこ",
        "あそこ",
        "どこ",
        "なに",
        "何",
        "誰",
        "いつ",
        "どう",
        "こんな",
        "そんな",
        "あんな",
        "という",
        "と思う",
        "てる",
        "ちゃう",
        "じゃ",
        "じゃあ",
        "えっ",
        "あの",
        "えっと",
        "うん",
        "はい",
        "いいえ",
    }
)

# Short kana-only WK expressions are matchable, but only as whole tokens when
# fugashi is available; longest-match still requires exact substring.
_MIN_KANA_EXPR_LEN = 2


@dataclass(frozen=True)
class TokenSpan:
    surface: str
    lemma: str
    reading: str
    pos: str
    start: int
    end: int


@dataclass(frozen=True)
class WkMatch:
    expression: str
    reading: str
    surface: str
    start: int
    end: int
    wk_entry: dict
    match_key: str  # surface or lemma used for lookup


@dataclass(frozen=True)
class CandidateLemma:
    lemma: str
    reading: str
    surface: str
    pos: str
    start: int
    end: int


def kanji_stem(text: str) -> str:
    indices = [index for index, ch in enumerate(text) if _KANJI_RE.match(ch)]
    if not indices:
        return ""
    return text[indices[0] : indices[-1] + 1]


def _fugashi_tagger():
    try:
        import fugashi  # type: ignore
    except ImportError:
        return None
    try:
        return fugashi.Tagger()
    except Exception:  # noqa: BLE001 — missing UniDic dicdir, etc.
        return None


def tokenize_japanese(text: str) -> List[TokenSpan]:
    """Tokenize Japanese; empty list when fugashi is unavailable."""
    tagger = _fugashi_tagger()
    if tagger is None or not (text or "").strip():
        return []
    tokens: List[TokenSpan] = []
    cursor = 0
    for word in tagger(text):
        surface = str(getattr(word, "surface", "") or "")
        if not surface:
            continue
        idx = text.find(surface, cursor)
        if idx < 0:
            idx = cursor
        feature = getattr(word, "feature", None)
        lemma = surface
        reading = ""
        pos = ""
        if feature is not None:
            lemma = str(getattr(feature, "lemma", None) or surface)
            # UniDic may use '-' joined lemma; keep the head.
            if "-" in lemma:
                lemma = lemma.split("-", 1)[0]
            reading = str(
                getattr(feature, "kana", None)
                or getattr(feature, "pron", None)
                or getattr(feature, "orthBase", None)
                or ""
            )
            pos = str(getattr(feature, "pos1", None) or getattr(feature, "pos", None) or "")
        tokens.append(
            TokenSpan(
                surface=surface,
                lemma=lemma or surface,
                reading=reading,
                pos=pos,
                start=idx,
                end=idx + len(surface),
            )
        )
        cursor = idx + len(surface)
    return tokens


def _entry_from_expression(index: dict, expression: str) -> Optional[dict]:
    by_expression = index.get("by_expression") or {}
    entry = by_expression.get(expression)
    return dict(entry) if entry else None


def _lookup_candidates(expression: str, reading: str, index: dict) -> Optional[dict]:
    return lookup_wk_vocab(expression, reading, index)


def match_wk_vocab_in_sentence(
    sentence: str,
    index: dict,
    *,
    sentence_reading: str = "",
) -> List[WkMatch]:
    """Return unique WK vocabulary matches in sentence order.

    Prefers fugashi token lemma/surface lookups; falls back to longest-match on
    WK expressions (and kanji stems for conjugated forms).
    """
    plain = (sentence or "").strip()
    if not plain:
        return []
    by_expression: Dict[str, dict] = index.get("by_expression") or {}
    if not by_expression:
        return []

    tokens = tokenize_japanese(plain)
    if tokens:
        return _match_with_tokens(plain, tokens, index)
    return _match_longest(plain, by_expression, sentence_reading=sentence_reading)


def _match_with_tokens(
    sentence: str, tokens: Sequence[TokenSpan], index: dict
) -> List[WkMatch]:
    matches: List[WkMatch] = []
    seen_ids: Set[int] = set()
    for token in tokens:
        for key, reading in (
            (token.surface, token.reading),
            (token.lemma, token.reading),
        ):
            if not key:
                continue
            if all(not _KANJI_RE.match(ch) for ch in key) and len(key) < _MIN_KANA_EXPR_LEN:
                continue
            entry = _lookup_candidates(key, reading, index)
            if entry is None:
                continue
            subject_id = int(entry["id"])
            if subject_id in seen_ids:
                break
            seen_ids.add(subject_id)
            matches.append(
                WkMatch(
                    expression=str(entry.get("expression") or key),
                    reading=str(entry.get("reading") or reading or ""),
                    surface=token.surface,
                    start=token.start,
                    end=token.end,
                    wk_entry=entry,
                    match_key=key,
                )
            )
            break
    matches.sort(key=lambda item: (item.start, item.end))
    return matches


def _match_longest(
    sentence: str,
    by_expression: Dict[str, dict],
    *,
    sentence_reading: str = "",
) -> List[WkMatch]:
    # Build search keys: full expression + kanji stem when useful.
    keys: List[Tuple[str, dict, str]] = []
    for expr, entry in by_expression.items():
        if not expr:
            continue
        keys.append((expr, entry, expr))
        stem = kanji_stem(expr)
        if stem and stem != expr and len(stem) >= 1:
            keys.append((stem, entry, expr))
    keys.sort(key=lambda item: len(item[0]), reverse=True)

    occupied = [False] * len(sentence)
    matches: List[WkMatch] = []
    seen_ids: Set[int] = set()

    for key, entry, canonical_expr in keys:
        if all(not _KANJI_RE.match(ch) for ch in key) and len(key) < _MIN_KANA_EXPR_LEN:
            continue
        start = 0
        while True:
            idx = sentence.find(key, start)
            if idx < 0:
                break
            end = idx + len(key)
            if any(occupied[idx:end]):
                start = idx + 1
                continue
            subject_id = int(entry["id"])
            if subject_id in seen_ids:
                break
            for pos in range(idx, end):
                occupied[pos] = True
            seen_ids.add(subject_id)
            matches.append(
                WkMatch(
                    expression=str(entry.get("expression") or canonical_expr),
                    reading=str(entry.get("reading") or ""),
                    surface=sentence[idx:end],
                    start=idx,
                    end=end,
                    wk_entry=dict(entry),
                    match_key=key,
                )
            )
            break
    matches.sort(key=lambda item: (item.start, item.end))
    return matches


def _is_content_pos(pos: str) -> bool:
    if not pos:
        return False
    if any(pos.startswith(prefix) for prefix in _EXCLUDED_POS_PREFIXES):
        return False
    return any(pos.startswith(prefix) for prefix in _CONTENT_POS_PREFIXES)


def _is_likely_name(lemma: str, pos: str) -> bool:
    if "固有名詞" in (pos or ""):
        return True
    # All-katakana short words often loanwords — keep them; long person-like
    # kanji+suffix heuristics are too noisy for v1.
    return False


def katakana_to_hiragana(text: str) -> str:
    """Map full-width katakana to hiragana (readings for type-in)."""
    out: List[str] = []
    for ch in text or "":
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:  # ァ–ヶ
            out.append(chr(code - 0x60))
        elif ch == "ヴ":
            out.append("ゔ")
        else:
            out.append(ch)
    return "".join(out)


def normalize_ja_reading(reading: str) -> str:
    """Normalize a dictionary/token reading to hiragana type-in form."""
    text = (reading or "").strip()
    if not text:
        return ""
    # UniDic sometimes returns "センパイ" or "センパイ-センパイ"
    if "-" in text:
        text = text.split("-", 1)[0]
    return katakana_to_hiragana(text)


def reading_for_candidate_lemma(lemma: str, reading: str = "") -> str:
    """Best-effort hiragana reading for candidate type-in."""
    normalized = normalize_ja_reading(reading)
    if normalized:
        return normalized
    text = (lemma or "").strip()
    if not text:
        return ""
    if all(_HIRAGANA_CHAR_RE.match(ch) or ch in "ーゝゞ" for ch in text):
        return text
    if all(_KATAKANA_CHAR_RE.match(ch) or ch in "ーヴ" for ch in text):
        return katakana_to_hiragana(text)
    return ""


def reading_for_surface_in_sentence(sentence: str, surface: str) -> str:
    """Join fugashi token readings covering ``surface`` in ``sentence`` (hiragana)."""
    plain = (sentence or "").strip()
    surf = (surface or "").strip()
    if not plain or not surf:
        return ""
    idx = plain.find(surf)
    if idx < 0:
        return reading_for_candidate_lemma(surf)
    end = idx + len(surf)
    parts: List[str] = []
    for token in tokenize_japanese(plain):
        if token.end <= idx or token.start >= end:
            continue
        piece = normalize_ja_reading(token.reading)
        if not piece:
            piece = reading_for_candidate_lemma(token.surface, token.reading)
        if piece:
            parts.append(piece)
    if parts:
        return "".join(parts)
    return reading_for_candidate_lemma(surf)


def candidate_lemmas_in_sentence(
    sentence: str,
    index: dict,
    *,
    wk_matched_ids: Optional[Set[int]] = None,
    wk_matched_expressions: Optional[Iterable[str]] = None,
) -> List[CandidateLemma]:
    """Content-word lemmas not present in the WK vocabulary index."""
    plain = (sentence or "").strip()
    if not plain:
        return []
    by_expression = index.get("by_expression") or {}
    excluded_expr = {expr for expr in (wk_matched_expressions or []) if expr}
    excluded_expr.update(by_expression.keys())

    tokens = tokenize_japanese(plain)
    if tokens:
        return _candidates_from_tokens(tokens, excluded_expr, by_expression)
    return _candidates_fallback(plain, excluded_expr, by_expression)


def _candidates_from_tokens(
    tokens: Sequence[TokenSpan],
    excluded_expr: Set[str],
    by_expression: Dict[str, dict],
) -> List[CandidateLemma]:
    out: List[CandidateLemma] = []
    seen: Set[str] = set()
    for token in tokens:
        lemma = (token.lemma or token.surface or "").strip()
        if not lemma or lemma in _STOPWORDS or lemma in excluded_expr:
            continue
        if lemma in by_expression or token.surface in by_expression:
            continue
        if not _is_content_pos(token.pos):
            continue
        if _is_likely_name(lemma, token.pos):
            continue
        if all(not _KANJI_RE.match(ch) for ch in lemma) and len(lemma) < 2:
            continue
        if lemma in seen:
            continue
        seen.add(lemma)
        out.append(
            CandidateLemma(
                lemma=lemma,
                reading=reading_for_candidate_lemma(lemma, token.reading),
                surface=token.surface,
                pos=token.pos,
                start=token.start,
                end=token.end,
            )
        )
    return out


def _candidates_fallback(
    sentence: str,
    excluded_expr: Set[str],
    by_expression: Dict[str, dict],
) -> List[CandidateLemma]:
    """Without fugashi: kanji runs and katakana words not in WK."""
    out: List[CandidateLemma] = []
    seen: Set[str] = set()
    for pattern in (_KANJI_RUN_RE, _KATAKANA_WORD_RE):
        for match in pattern.finditer(sentence):
            lemma = match.group(0)
            if lemma in _STOPWORDS or lemma in excluded_expr or lemma in by_expression:
                continue
            if lemma in seen:
                continue
            # Skip single-kanji candidates that are almost always WK radicals/kanji noise.
            if pattern is _KANJI_RUN_RE and len(lemma) < 2:
                continue
            seen.add(lemma)
            out.append(
                CandidateLemma(
                    lemma=lemma,
                    reading=reading_for_candidate_lemma(lemma),
                    surface=lemma,
                    pos="unknown",
                    start=match.start(),
                    end=match.end(),
                )
            )
    out.sort(key=lambda item: (item.start, item.end))
    return out
