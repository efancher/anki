"""Build Anki ``漢字[かんじ]`` furigana markup from a surface + full-kana reading."""

from __future__ import annotations

import re
from typing import Optional

_KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# Exclude ヶ/ケ — counter prefix in ヶ月, aligned with the following kanji reading.
_KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30f5\u30f7-\u30faー]")
_KANJI_EXTEND = frozenset("ヶケ")


def katakana_to_hiragana(text: str) -> str:
    chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            chars.append(chr(code - 0x60))
        else:
            chars.append(ch)
    return "".join(chars)


def _is_kanji(ch: str) -> bool:
    return bool(_KANJI_RE.fullmatch(ch)) or ch in _KANJI_EXTEND


def _is_kana(ch: str) -> bool:
    return bool(_KANA_RE.fullmatch(ch)) and ch not in _KANJI_EXTEND


def word_furigana_brackets(expression: str, reading: str) -> str:
    """``電車[でんしゃ]`` when expression has kanji; else empty (plain Reading is enough)."""
    expr = (expression or "").strip()
    kana = katakana_to_hiragana((reading or "").strip())
    if not expr or not kana:
        return ""
    if not any(_is_kanji(ch) for ch in expr):
        return ""
    # Whole-word reading when expression is all kanji, or mixed with okurigana.
    aligned = anki_furigana_brackets(expr, kana)
    return aligned if aligned and "[" in aligned else f"{expr}[{kana}]"


def anki_furigana_brackets(surface: str, reading: str) -> str:
    """Align ``surface`` (mixed script) with a full hiragana/katakana ``reading``.

    Returns Anki bracket markup, or ``\"\"`` when alignment fails (caller should
    fall back to plain surface). Punctuation and latin/digits must match on both
    sides or appear only on the surface with no reading consumption.
    """
    surface = (surface or "").strip()
    reading = katakana_to_hiragana((reading or "").strip())
    if not surface or not reading:
        return ""
    # Identical scripts — nothing to ruby.
    if katakana_to_hiragana(surface) == reading:
        return surface

    out: list[str] = []
    i = 0  # surface
    j = 0  # reading
    n = len(surface)
    m = len(reading)

    while i < n:
        ch = surface[i]
        if _is_kanji(ch):
            start = i
            while i < n and _is_kanji(surface[i]):
                i += 1
            kanji_run = surface[start:i]
            # Reading for this run ends where the next surface kana/punct matches.
            reading_end = _reading_span_end(surface, i, reading, j)
            if reading_end is None or reading_end <= j:
                return ""
            ruby = reading[j:reading_end]
            if not ruby:
                return ""
            out.append(f"{kanji_run}[{ruby}]")
            j = reading_end
            continue

        if _is_kana(ch):
            folded = katakana_to_hiragana(ch)
            if j >= m or reading[j] != folded:
                return ""
            out.append(ch)
            i += 1
            j += 1
            continue

        # Punctuation / digits / latin / spaces: require same char in reading when
        # present, otherwise keep surface-only (e.g. rare ASR mismatch).
        if j < m and reading[j] == ch:
            out.append(ch)
            i += 1
            j += 1
        else:
            out.append(ch)
            i += 1

    if j != m:
        # Leftover reading — alignment drifted.
        return ""
    return "".join(out)


def _reading_span_end(
    surface: str, next_surface_i: int, reading: str, reading_j: int
) -> Optional[int]:
    """Index in ``reading`` where the kanji-run reading ends (exclusive)."""
    m = len(reading)
    if next_surface_i >= len(surface):
        return m if reading_j < m else None

    k = next_surface_i
    # Skip surface-only punctuation that is absent from the reading.
    while k < len(surface) and not _is_kana(surface[k]) and not _is_kanji(surface[k]):
        ch = surface[k]
        if reading_j < m and reading[reading_j] == ch:
            break
        if ch in reading[reading_j:]:
            break
        k += 1

    if k >= len(surface):
        return m if reading_j < m else None

    ch = surface[k]
    if _is_kana(ch):
        # Match the whole following kana run (じゃ not just じ) so readings like
        # きんじょじゃん don't bind the じ inside じょ.
        kana_run_chars: list[str] = []
        while k < len(surface) and _is_kana(surface[k]):
            kana_run_chars.append(katakana_to_hiragana(surface[k]))
            k += 1
        kana_run = "".join(kana_run_chars)
        idx = reading.find(kana_run, reading_j)
        if idx == reading_j:
            idx = reading.find(kana_run, reading_j + 1)
        if idx < 0:
            return None
        return idx

    if _is_kanji(ch):
        return None

    # Punctuation / digit shared with reading.
    idx = reading.find(ch, reading_j)
    if idx == reading_j:
        idx = reading.find(ch, reading_j + 1)
    if idx < 0:
        return None
    return idx
