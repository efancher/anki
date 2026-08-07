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
# Shadowing ASR / scripts put stage directions in square brackets; Migaku readings
# use the same delimiters. Strip them before matching so 息/音 inside [息をのむ音]
# cannot become cards for the spoken line that follows.
_BRACKET_NOTE_RE = re.compile(r"\[(?!sound:)[^\]]*\]")
# Colloquial compounds that contain WK pieces but are one phonological word.
# (中怖い = ちゅうこわい, not 中/なか + 怖い/こわい.)
_ATOMIC_COMPOUNDS: Tuple[Tuple[str, str], ...] = (
    ("中怖い", "ちゅうこわい"),
)
ATOMIC_COMPOUND_READINGS: Dict[str, str] = {
    surface: reading for surface, reading in _ATOMIC_COMPOUNDS
}


def study_sentence_text(sentence: str) -> str:
    """Spoken line only — drop [stage directions] / Migaku reading brackets."""
    text = _BRACKET_NOTE_RE.sub("", sentence or "")
    return re.sub(r"  +", " ", text).strip()


def has_spoken_japanese(sentence: str) -> bool:
    """False for music/SFX cues like ``[音楽]`` after bracket stripping."""
    return bool(study_sentence_text(sentence))


# WK writes counters and suffixes with a leading tilde placeholder (〜歳, 〜君).
_PLACEHOLDER_TILDES = "〜～"

# Godan te/ta forms mutate the final kana out of its row (使って, 担いで, 読んで).
_EUPHONIC_INFLECTION_KANA = frozenset("っんい")

# An i-adjective whose whole okurigana is い inflects into the か row instead of
# its own (良かった, 良く, 良ければ, 良さ). Longer okurigana already starts in the
# right row (暖かい → 暖かく), so only the bare-い case needs this.
_I_ADJECTIVE_CONTINUATIONS = frozenset("かきくけこさそ")

# わ rides with the あ row: the negative stem of a う-verb is わ (使わない).
_GOJUON_ROWS = (
    "あいうえおわ",
    "かきくけこ",
    "がぎぐげご",
    "さしすせそ",
    "ざじずぜぞ",
    "たちつてと",
    "だぢづでど",
    "なにぬねの",
    "はひふへほ",
    "ばびぶべぼ",
    "ぱぴぷぺぽ",
    "まみむめも",
    "やゆよ",
    "らりるれろ",
)

# Resolved on first use: the conjugator callable, or False when unavailable.
_CONJUGATOR = None

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


def conjugation_match_key(expression: str) -> str:
    """Search key for an inflected occurrence: expression minus trailing okurigana.

    Only trailing kana is dropped, because that is what inflection changes. Any
    leading kana is kept (お知らせ → お知), so a bare kanji cannot claim a word
    whose prefix is absent from the sentence — 知らなかった is 知る, not お知らせ,
    and the 年 of 同い年 is not ２０１１年. A WK placeholder tilde is dropped so
    〜歳 can still match after a number (22歳).
    """
    text = (expression or "").lstrip(_PLACEHOLDER_TILDES)
    indices = [index for index, ch in enumerate(text) if _KANJI_RE.match(ch)]
    if not indices:
        return ""
    return text[: indices[-1] + 1]


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


def _atomic_compound_hits(sentence: str) -> List[Tuple[int, int, str, str]]:
    """Non-overlapping ``(start, end, surface, reading)`` for known compounds."""
    hits: List[Tuple[int, int, str, str]] = []
    for surface, reading in sorted(_ATOMIC_COMPOUNDS, key=lambda item: -len(item[0])):
        start = 0
        while True:
            idx = sentence.find(surface, start)
            if idx < 0:
                break
            end = idx + len(surface)
            if not any(_spans_overlap(idx, end, kept[0], kept[1]) for kept in hits):
                hits.append((idx, end, surface, reading))
            start = idx + 1
    hits.sort(key=lambda item: item[0])
    return hits


def _drop_matches_inside_atomic_compounds(
    sentence: str, matches: Sequence[WkMatch]
) -> List[WkMatch]:
    compounds = _atomic_compound_hits(sentence)
    if not compounds:
        return list(matches)
    return [
        match
        for match in matches
        if not any(
            _spans_overlap(match.start, match.end, start, end)
            for start, end, _surface, _reading in compounds
        )
    ]


def _atomic_compound_candidates(sentence: str) -> List[CandidateLemma]:
    return [
        CandidateLemma(
            lemma=surface,
            reading=reading,
            surface=surface,
            pos="colloquial-compound",
            start=start,
            end=end,
        )
        for start, end, surface, reading in _atomic_compound_hits(sentence)
    ]


def match_wk_vocab_in_sentence(
    sentence: str,
    index: dict,
    *,
    sentence_reading: str = "",
) -> List[WkMatch]:
    """Return unique WK vocabulary matches in sentence order.

    Prefers fugashi token lemma/surface lookups, then fills remaining gaps with
    longest-match on WK expressions (and okurigana-stripped stems). Tokenization
    alone is not enough: UniDic often emits a compound lemma that is not itself
    a WK entry (``同い年``), while the stem of ``同じ`` still sits inside it.

    Matching runs on the spoken line only (``[stage directions]`` stripped), so
    indices align with the Sentence field the cloze builder stores.
    """
    plain = study_sentence_text(sentence)
    if not plain:
        return []
    by_expression: Dict[str, dict] = index.get("by_expression") or {}
    if not by_expression:
        return []

    tokens = tokenize_japanese(plain)
    token_matches = _match_with_tokens(plain, tokens, index) if tokens else []
    longest_matches = _match_longest(
        plain, by_expression, sentence_reading=sentence_reading
    )
    merged = _merge_wk_matches(token_matches, longest_matches)
    return _drop_matches_inside_atomic_compounds(plain, merged)


def _spans_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def _merge_wk_matches(
    preferred: Sequence[WkMatch], extras: Sequence[WkMatch]
) -> List[WkMatch]:
    """Greedy by span length so お姉さん beats 姉 and 急に beats 急."""
    candidates = list(preferred) + list(extras)
    candidates.sort(key=lambda match: (-(match.end - match.start), match.start))
    merged: List[WkMatch] = []
    seen_ids: Set[int] = set()
    for match in candidates:
        subject_id = int(match.wk_entry["id"])
        if subject_id in seen_ids:
            continue
        if any(
            _spans_overlap(match.start, match.end, kept.start, kept.end)
            for kept in merged
        ):
            continue
        seen_ids.add(subject_id)
        merged.append(match)
    merged.sort(key=lambda item: (item.start, item.end))
    return merged


def _surface_supports_wk_entry(surface: str, expression: str, reading: str) -> bool:
    """True when the written token is a plausible form of this WK entry.

    UniDic lemmas are dictionary forms, not spellings. Colloquial いや is lemmatized
    as 否, and the 吾 in し吾 as 我 — both are real lemmas, but neither spelling is
    what appears in the sentence. Require the surface to share the expression's
    writing, its okurigana-stripped stem, its reading, or a conjugated variant.
    """
    surf = (surface or "").strip()
    expr = (expression or "").lstrip(_PLACEHOLDER_TILDES).strip()
    if not surf or not expr:
        return False
    if surf == expr or expr in surf or surf in expr:
        return True
    stem = conjugation_match_key(expr)
    if stem and (stem in surf or surf in stem):
        return True
    surf_h = normalize_ja_reading(surf)
    read_h = normalize_ja_reading(reading)
    if surf_h and read_h and surf_h == read_h:
        return True
    if not any(_KANJI_RE.match(ch) for ch in surf) and len(surf) < _MIN_KANA_EXPR_LEN:
        return False
    for variant in _conjugated_surface_variants(expr, reading):
        if not variant:
            continue
        if surf == variant or variant.startswith(surf) or surf.startswith(variant):
            return True
    return False


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
            expression = str(entry.get("expression") or key)
            entry_reading = str(entry.get("reading") or reading or "")
            if not _surface_supports_wk_entry(token.surface, expression, entry_reading):
                continue
            subject_id = int(entry["id"])
            if subject_id in seen_ids:
                break
            seen_ids.add(subject_id)
            matches.append(
                WkMatch(
                    expression=expression,
                    reading=entry_reading,
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


def _conjugated_surface_variants(expression: str, reading: str) -> Sequence[str]:
    """satori_decks' conjugator, imported lazily to avoid an import cycle.

    satori_decks → immersion_pitch → shadowing_match, so this module cannot
    import it at load time.
    """
    global _CONJUGATOR
    if _CONJUGATOR is None:
        try:
            from satori_decks import conjugated_surface_variants
        except ImportError:  # genanki or WK deps missing — fall back to kana rules
            _CONJUGATOR = False
        else:
            _CONJUGATOR = conjugated_surface_variants
    if not _CONJUGATOR:
        return ()
    return _CONJUGATOR(expression, reading)


def _okurigana(expression: str) -> str:
    """Trailing kana of an expression — what inflection rewrites (怒る → る)."""
    text = (expression or "").lstrip(_PLACEHOLDER_TILDES)
    indices = [index for index, ch in enumerate(text) if _KANJI_RE.match(ch)]
    if not indices:
        return ""
    return text[indices[-1] + 1 :]


def _inflection_continuations(okurigana: str) -> Set[str]:
    """Kana that may follow a stem when its okurigana inflects.

    An inflected okurigana stays in its own gojūon row (任す → 任し/任さ), so a
    kana from another row means the stem is part of an unrelated word: the 任 of
    「担任も」 is not 任す, and the 察 of 「警察やってる」 is not 察する.
    """
    if not okurigana:
        return set()
    allowed = set(_EUPHONIC_INFLECTION_KANA)
    if okurigana == "い":
        allowed |= _I_ADJECTIVE_CONTINUATIONS
    for row in _GOJUON_ROWS:
        if okurigana[0] in row:
            return allowed | set(row)
    return set()


def _stem_match_is_plausible_inflection(
    sentence: str,
    key: str,
    expression: str,
    reading: str,
    start: int,
    end: int,
) -> bool:
    """Whether an okurigana-stripped key really landed on an inflected occurrence.

    A stem stands in for an inflected form, so what follows it decides:
    kanji means the stem is inside another compound (the 担 of 担任 is not 担ぐ,
    the 生 of 年生 is not 生まれる). Otherwise a real conjugated surface at this
    position settles it, including irregulars the row rule cannot model (来ない).
    The row rule is the fallback for forms the conjugator does not emit, such as
    the causative 怒らせ.
    """
    following = sentence[end] if end < len(sentence) else ""
    if following and _KANJI_RE.match(following):
        return False
    okurigana = _okurigana(expression)
    if not okurigana:
        # Counters and suffixes (〜歳, 〜ヶ月) have nothing to inflect.
        return True
    if any(
        sentence.startswith(variant, start)
        for variant in _conjugated_surface_variants(expression, reading)
    ):
        return True
    return following in _inflection_continuations(okurigana)


def _match_longest(
    sentence: str,
    by_expression: Dict[str, dict],
    *,
    sentence_reading: str = "",
) -> List[WkMatch]:
    # Build search keys: full expression + okurigana-stripped stem when useful.
    keys: List[Tuple[str, dict, str]] = []
    for expr, entry in by_expression.items():
        if not expr:
            continue
        keys.append((expr, entry, expr))
        stem = conjugation_match_key(expr)
        if stem and stem != expr:
            keys.append((stem, entry, expr))
    keys.sort(key=lambda item: len(item[0]), reverse=True)

    occupied = [False] * len(sentence)
    matches: List[WkMatch] = []
    seen_ids: Set[int] = set()

    for key, entry, canonical_expr in keys:
        if all(not _KANJI_RE.match(ch) for ch in key) and len(key) < _MIN_KANA_EXPR_LEN:
            continue
        is_stem_key = key != canonical_expr
        start = 0
        while True:
            idx = sentence.find(key, start)
            if idx < 0:
                break
            end = idx + len(key)
            if any(occupied[idx:end]):
                start = idx + 1
                continue
            if is_stem_key and not _stem_match_is_plausible_inflection(
                sentence,
                key,
                canonical_expr,
                str(entry.get("reading") or ""),
                idx,
                end,
            ):
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


# Shadowing ASR often splits names like し吾 (Shogo) into し + 吾(われ).
# Override dictionary pronoun readings when these surfaces appear.
_SURFACE_READING_OVERRIDES: Dict[str, str] = {
    "し吾": "しょご",
    "し吾先輩": "しょごせんぱい",
    "し吾君": "しょごくん",
}


def name_surface_for_shogo(sentence: str, surface: str) -> str:
    """Expand 吾先輩/吾君 to し吾… when the sentence has the ASR name form."""
    surf = (surface or "").strip()
    plain = (sentence or "").strip()
    if surf == "吾先輩" and "し吾先輩" in plain:
        return "し吾先輩"
    if surf == "吾君" and "し吾君" in plain:
        return "し吾君"
    return surf


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
    surf = name_surface_for_shogo(plain, surface)
    if not plain or not surf:
        return ""
    override = _SURFACE_READING_OVERRIDES.get(surf)
    if override:
        return override
    idx = plain.find(surf)
    if idx < 0:
        return reading_for_candidate_lemma(surf)
    end = idx + len(surf)
    parts: List[str] = []
    for token in tokenize_japanese(plain):
        # Require the token to lie fully inside the surface — partial overlap
        # (e.g. surface 敬語使 vs token 使っ) glues a trailing っ onto the reading.
        if token.start < idx or token.end > end:
            continue
        tok_override = _SURFACE_READING_OVERRIDES.get(token.surface)
        if tok_override:
            parts.append(tok_override)
            continue
        piece = normalize_ja_reading(token.reading)
        if not piece:
            piece = reading_for_candidate_lemma(token.surface, token.reading)
        if piece:
            parts.append(piece)
    if parts:
        return "".join(parts)
    return reading_for_candidate_lemma(surf)


def candidate_reading_looks_truncated(reading: str) -> bool:
    """True when a type-in reading ends in っ — not a normal dictionary form."""
    text = (reading or "").strip()
    return bool(text) and text[-1] in "っッ"


def candidate_lemmas_in_sentence(
    sentence: str,
    index: dict,
    *,
    wk_matched_ids: Optional[Set[int]] = None,
    wk_matched_expressions: Optional[Iterable[str]] = None,
    wk_matched_spans: Optional[Iterable[Tuple[int, int]]] = None,
) -> List[CandidateLemma]:
    """Content-word lemmas not present in the WK vocabulary index."""
    plain = study_sentence_text(sentence)
    if not plain:
        return []
    by_expression = index.get("by_expression") or {}
    excluded_expr = {expr for expr in (wk_matched_expressions or []) if expr}
    excluded_expr.update(by_expression.keys())

    occupied = [(int(start), int(end)) for start, end in (wk_matched_spans or [])]
    if not occupied and by_expression:
        for match in match_wk_vocab_in_sentence(plain, index):
            occupied.append((match.start, match.end))

    tokens = tokenize_japanese(plain)
    if tokens:
        candidates = _candidates_from_tokens(tokens, excluded_expr, by_expression)
    else:
        candidates = _candidates_fallback(plain, excluded_expr, by_expression, occupied)
    # Known colloquial compounds (中怖い) even when WK would claim the pieces.
    seen = {(item.lemma, item.start) for item in candidates}
    for compound in _atomic_compound_candidates(plain):
        key = (compound.lemma, compound.start)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(compound)
    candidates.sort(key=lambda item: (item.start, item.end))
    return candidates


def _subtract_occupied_spans(
    start: int, end: int, occupied: Sequence[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """Return sub-intervals of ``[start, end)`` not covered by ``occupied``."""
    pieces: List[Tuple[int, int]] = [(start, end)]
    for o_start, o_end in sorted(occupied):
        if o_end <= o_start:
            continue
        next_pieces: List[Tuple[int, int]] = []
        for a, b in pieces:
            if o_end <= a or o_start >= b:
                next_pieces.append((a, b))
                continue
            if a < o_start:
                next_pieces.append((a, o_start))
            if o_end < b:
                next_pieces.append((o_end, b))
        pieces = next_pieces
    return pieces


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
        reading = reading_for_candidate_lemma(lemma, token.reading)
        if candidate_reading_looks_truncated(reading):
            continue
        if lemma in seen:
            continue
        seen.add(lemma)
        out.append(
            CandidateLemma(
                lemma=lemma,
                reading=reading,
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
    occupied: Sequence[Tuple[int, int]] = (),
) -> List[CandidateLemma]:
    """Without fugashi: kanji runs and katakana words not in WK.

    Kanji runs are carved by WK match spans so conjugated compounds like
    ``敬語使って`` do not become a fake lemma ``敬語使``.
    """
    out: List[CandidateLemma] = []
    seen: Set[str] = set()
    for pattern in (_KANJI_RUN_RE, _KATAKANA_WORD_RE):
        for match in pattern.finditer(sentence):
            spans = (
                _subtract_occupied_spans(match.start(), match.end(), occupied)
                if pattern is _KANJI_RUN_RE
                else [(match.start(), match.end())]
            )
            for start, end in spans:
                lemma = sentence[start:end]
                if lemma in _STOPWORDS or lemma in excluded_expr or lemma in by_expression:
                    continue
                if lemma in seen:
                    continue
                # Skip single-kanji candidates that are almost always WK radicals/kanji noise.
                if pattern is _KANJI_RUN_RE and len(lemma) < 2:
                    continue
                reading = reading_for_candidate_lemma(lemma)
                if candidate_reading_looks_truncated(reading):
                    continue
                # Cut mid-conjugation: kanji run ends immediately before っ of て/た-form.
                if end < len(sentence) and sentence[end] == "っ" and _KANJI_RE.match(lemma[-1]):
                    continue
                seen.add(lemma)
                out.append(
                    CandidateLemma(
                        lemma=lemma,
                        reading=reading,
                        surface=lemma,
                        pos="unknown",
                        start=start,
                        end=end,
                    )
                )
    out.sort(key=lambda item: (item.start, item.end))
    return out
