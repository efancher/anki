"""
Cure Dolly–style gloss worksheets for Satori immersion sentences.

Not an SRS card — a practice sheet: Japanese → chunk/role/literal blanks →
Satori English kept separate so you map Japanese order before fluent English.

Answer-key LIT is Japanese-order sticky English: content words are translated,
particles/engines stay as sticky suffixes (as-for, が, POLITE.PAST, …).
MT runs on each full chunk (e.g. 空は), not the bare stem (空), so context
particles/engines pick the right sense (sky-as-for, not empty-as-for).
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

DEFAULT_NOTE_TYPE = "WK Satori Immersion"
DEFAULT_DECK = "Immersion · Satori"
ICHI_MOE_BASE = "https://ichi.moe/cl/qr/"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
ROLE_HINT = "Aが / engine / を・に・で car / time / topic は / …"
LIT_HINT = "Japanese-order sticky English (not fluent EN)"
CHUNK_HINT = "space particles / て links / clause boundaries"
ANSWER_KEY_BANNER = (
    "ANSWER KEY (heuristic CHUNK/ROLE; LIT = Japanese-order sticky English via MT)"
)

# Longer matches first so から/まで win over か/で.
_PARTICLE_TOKENS: Tuple[str, ...] = (
    "から",
    "まで",
    "より",
    "ほど",
    "だけ",
    "しか",
    "など",
    "とか",
    "って",
    "ては",
    "ても",
    "では",
    "には",
    "へは",
    "とは",
    "のも",
    "でも",
    "のは",
    "のが",
    "のを",
    "ので",
    "のに",
    "たら",
    "たり",
    "なら",
    "が",
    "を",
    "に",
    "で",
    "て",
    "へ",
    "と",
    "や",
    "も",
    "は",
    "の",
)

# Only cut on these at the very end of a clause (before punctuation / EOS).
# Matching mid-string shreds words (ひな, なる, 静か, …).
_SENTENCE_FINAL_PARTICLES: frozenset[str] = frozenset({"な", "ね", "よ", "か", "ぞ", "わ", "さ"})

_CLAUSE_END_CHARS = frozenset("。．！？!?、，,」』）)…‥〟\"'")

# Don't treat these particle starts as cuts when they begin a longer grammar form.
_PARTICLE_LOOKAHEAD_BLOCK: Dict[str, Tuple[str, ...]] = {
    "で": (
        "です",
        "でした",
        "である",
        "であり",
        "でき",
        "出来る",
        "できます",
        "できない",
        "できません",
        "できた",
        "出来",
    ),
    "て": ("ている", "ています", "てる", "てしまう", "ておく", "てみる"),
}

# て／で links that continue into ～てくる／～て来る.
_TE_KURU_CONTINUATIONS: Tuple[str, ...] = (
    "来",
    "くる",
    "きます",
    "きました",
    "きた",
    "きて",
    "こない",
    "こなかった",
)

# Adverbs peeled into their own CHUNK when stuck to the following phrase.
_STANDALONE_ADVERBS: Tuple[str, ...] = (
    "しばらくすると",
    "なんとか",
    "とっても",
    "そして",
    "しかし",
)

# Whole words that end in a particle character but are not cuts.
_LEXICAL_PARTICLE_LOOKALIKE: frozenset[str] = frozenset(_STANDALONE_ADVERBS) | frozenset(
    {
        "すごく",
    }
)

_ENGINE_SUFFIXES: Tuple[str, ...] = (
    "ありませんでした",
    "ありません",
    "でした",
    "です",
    "ました",
    "ません",
    "ます",
    "だった",
    "じゃない",
    "ではない",
    "ない",
    "たい",
    "れる",
    "られる",
    "させる",
    "た",
    "だ",
    "て",
    "で",
)

_PARTICLE_ROLE: Dict[str, str] = {
    "が": "Aが",
    "は": "topic は",
    "を": "を-car",
    "に": "に-car",
    "で": "で-car",
    "て": "て-car",
    "んで": "て-car",
    "いで": "て-car",
    "へ": "へ-car",
    "と": "と-car",
    "や": "や-car",
    "も": "も-car",
    "の": "の-car",
    "から": "から-car",
    "まで": "まで-car",
    "より": "より-car",
    "では": "で-car + topic は",
    "には": "に-car + topic は",
    "へは": "へ-car + topic は",
    "とは": "と-car + topic は",
    "ので": "ので (because)",
    "のに": "のに (although)",
    "のは": "nominalizer + topic は",
    "のが": "nominalizer + Aが",
    "のを": "nominalizer + を-car",
}

# Dolly-style sticky suffixes for the LIT line (English order follows Japanese).
_PARTICLE_STICKY: Dict[str, str] = {
    "が": "が",
    "は": "as-for",
    "を": "を",
    "に": "at",
    "で": "at/with",
    "て": "and",
    "んで": "and",
    "いで": "and",
    "へ": "toward",
    "と": "with/and",
    "や": "and/or",
    "も": "also",
    "の": "'s",
    "から": "from",
    "まで": "until",
    "より": "than",
    "では": "at-as-for",
    "には": "at-as-for",
    "へは": "toward-as-for",
    "とは": "with-as-for",
    "ては": "if/when",
    "ので": "because",
    "のに": "although",
    "のは": "nom-as-for",
    "のが": "nom-が",
    "のを": "nom-を",
    "って": "って",
    "ても": "even-if",
    "でも": "even/but",
}

_ENGINE_STICKY: Dict[str, str] = {
    "です": "is.POLITE",
    "でした": "was.POLITE",
    "ます": "POLITE",
    "ました": "POLITE.PAST",
    "ません": "POLITE.NEG",
    "ありません": "exist-not.POLITE",
    "ありませんでした": "exist-not.POLITE.PAST",
    "ない": "not",
    "だった": "was",
    "じゃない": "is-not",
    "ではない": "is-not",
    "た": "PAST",
    "だ": "COP",
    "て": "and/ing",
    "で": "and/ing",
    "たい": "want-to",
}

Translator = Callable[[str], str]
_TRANSLATE_CACHE: Dict[str, str] = {}


@dataclass(frozen=True)
class GlossSentence:
    """One sentence to practice mapping Japanese → English."""

    japanese: str
    english: str = ""
    expression: str = ""
    reading: str = ""
    note_id: Optional[int] = None
    source: str = ""


@dataclass(frozen=True)
class GlossAnswer:
    """Heuristic fill for CHUNK / ROLE / LIT."""

    chunk: str
    role: str
    lit: str


# Bump when chunking / role / LIT heuristics change so stale answers are dropped.
GLOSS_ANSWER_CACHE_VERSION = 1
GLOSS_ANSWER_CACHE_SUBDIR = "satori_gloss"
GLOSS_ANSWER_CACHE_FILENAME = "answers.json"


def gloss_answer_cache_key(item: "GlossSentence") -> str:
    """Stable key for one exercise: normalized sentence + English hint.

    The LIT line depends on the card's English, so both feed the key.
    """
    sentence = normalize_sentence_key(item.japanese)
    english = re.sub(r"\s+", " ", (item.english or "").strip()).lower()
    raw = f"{GLOSS_ANSWER_CACHE_VERSION}\x1f{sentence}\x1f{english}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load_gloss_answer_cache(path: Path) -> Dict[str, dict]:
    """Load cached answers; return {} on missing/corrupt/version-mismatch."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("version") != GLOSS_ANSWER_CACHE_VERSION:
        return {}
    answers = payload.get("answers")
    return answers if isinstance(answers, dict) else {}


def save_gloss_answer_cache(path: Path, answers: Dict[str, dict]) -> None:
    """Atomically write the answer cache next to other .wk_cache data."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": GLOSS_ANSWER_CACHE_VERSION, "answers": answers}
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=0)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def strip_anki_html(value: str) -> str:
    """Turn Anki field HTML into plain text for worksheets."""
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?div[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_sentence_key(japanese: str) -> str:
    """Normalize JP text for duplicate detection."""
    text = strip_anki_html(japanese)
    text = re.sub(r"\s+", "", text)
    return text


def ichi_moe_url(japanese: str) -> str:
    return f"{ICHI_MOE_BASE}?q={quote(japanese, safe='')}&r=kana"


def dedupe_gloss_items(items: Sequence[GlossSentence]) -> List[GlossSentence]:
    """Keep first note per unique sentence; merge target words onto that row."""
    by_key: Dict[str, GlossSentence] = {}
    order: List[str] = []
    for item in items:
        key = normalize_sentence_key(item.japanese)
        if not key:
            continue
        if key not in by_key:
            by_key[key] = item
            order.append(key)
            continue
        existing = by_key[key]
        expressions = [
            part.strip()
            for part in existing.expression.split(" · ")
            if part.strip()
        ]
        if item.expression and item.expression not in expressions:
            expressions.append(item.expression)
        readings = [
            part.strip()
            for part in existing.reading.split(" · ")
            if part.strip()
        ]
        if item.reading and item.reading not in readings:
            readings.append(item.reading)
        by_key[key] = replace(
            existing,
            expression=" · ".join(expressions),
            reading=" · ".join(readings),
            english=existing.english or item.english,
            source=existing.source or item.source,
        )
    return [by_key[key] for key in order]


def _split_trailing_particle(chunk: str) -> Tuple[str, str]:
    for lookalike in _LEXICAL_PARTICLE_LOOKALIKE:
        if chunk == lookalike or chunk.startswith(lookalike):
            return chunk, ""
    for particle in _PARTICLE_TOKENS:
        if chunk.endswith(particle) and len(chunk) > len(particle):
            # Avoid cutting です/でした into …で + す/した.
            blocked = _PARTICLE_LOOKAHEAD_BLOCK.get(particle, ())
            tail = chunk[len(chunk) - len(particle) :]
            if any(chunk.endswith(form) for form in blocked):
                continue
            if any(tail.startswith(form) for form in blocked):
                continue
            # Keep ～てくる together for sticky glossing / engine split.
            if particle in {"て", "で", "って"} and any(
                chunk.endswith(particle + form) for form in _TE_KURU_CONTINUATIONS
            ):
                continue
            if particle == "と" and chunk.endswith("こと"):
                continue
            if particle == "が" and chunk.endswith("がり"):
                continue
            return chunk[: -len(particle)], particle
    return chunk, ""


def _split_trailing_engine(chunk: str) -> Tuple[str, str]:
    for lookalike in _LEXICAL_PARTICLE_LOOKALIKE:
        if chunk == lookalike or chunk.startswith(lookalike):
            return chunk, ""
    for suffix in _ENGINE_SUFFIXES:
        if chunk == suffix:
            return "", suffix
        if chunk.endswith(suffix) and len(chunk) > len(suffix):
            return chunk[: -len(suffix)], suffix
    return chunk, ""


def _particle_at(text: str, index: int) -> Optional[str]:
    if index <= 0:
        return None
    for particle in _PARTICLE_TOKENS + tuple(_SENTENCE_FINAL_PARTICLES):
        if not text.startswith(particle, index):
            continue
        rest = text[index:]
        blocked = _PARTICLE_LOOKAHEAD_BLOCK.get(particle, ())
        if any(rest.startswith(form) for form in blocked):
            continue
        if particle in _SENTENCE_FINAL_PARTICLES:
            after = text[index + len(particle) :]
            if after and not all(char in _CLAUSE_END_CHARS for char in after):
                continue
        # なんとか — don't cut on とか／と／か inside the adverb.
        if particle in {"とか", "と", "か"} and (
            (index >= 2 and text.startswith("なんとか", index - 2))
            or (index >= 1 and text.startswith("なんとか", index - 1))
            or text.startswith("なんとか", index)
        ):
            continue
        # Nominalizer こと — don't cut on the と.
        if particle == "と" and index >= 1 and text[index - 1 : index + 1] == "こと":
            continue
        # ～がり (怖がり) — が is part of the stem, not Aが.
        if particle == "が" and text.startswith("がり", index):
            continue
        # とっても — don't cut on って／ても／て／も inside the adverb.
        if particle in {"って", "ても", "て", "も"} and (
            (index >= 1 and text.startswith("とっても", index - 1))
            or (index >= 2 and text.startswith("とっても", index - 2))
            or (index >= 3 and text.startswith("とっても", index - 3))
            or text.startswith("とっても", index)
        ):
            continue
        # そして — て is part of the conjunction.
        if particle == "て" and index >= 3 and text[index - 3 : index + 1] == "そして":
            continue
        # ～てくる／～て来る — keep the auxiliary with the て-link.
        # Includes んで／いで て-forms (運んで来た, 急いで来た).
        after_particle = text[index + len(particle) :]
        if particle in {"て", "で", "って"} and any(
            after_particle.startswith(form) for form in _TE_KURU_CONTINUATIONS
        ):
            continue
        return particle
    return None


def chunk_japanese_sentence(japanese: str) -> List[str]:
    """Heuristic bunsetsu-ish split on particles (longer tokens first)."""
    text = re.sub(r"\s+", "", strip_anki_html(japanese))
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    index = 0
    while index < len(text):
        particle = _particle_at(text, index) if index > start else None
        if particle:
            end = index + len(particle)
            chunks.append(text[start:end])
            start = end
            index = end
            continue
        index += 1
    if start < len(text):
        chunks.append(text[start:])

    cleaned: List[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        if cleaned and chunk in {"。", "．", "！", "？", "!", "?", "、", "，", ","}:
            cleaned[-1] += chunk
            continue
        if cleaned and chunk[0] in "、，,":
            cleaned[-1] += chunk[0]
            chunk = chunk[1:]
            if not chunk:
                continue
        cleaned.append(chunk)
    return _peel_leading_adverbs(cleaned) or [text]


def _peel_leading_adverbs(chunks: List[str]) -> List[str]:
    """Split known adverbs glued onto the next phrase (なんとか飛ぶ…)."""
    peeled: List[str] = []
    for chunk in chunks:
        remainder = chunk
        while remainder:
            matched = False
            for adverb in _STANDALONE_ADVERBS:
                if not remainder.startswith(adverb) or len(remainder) <= len(adverb):
                    continue
                rest = remainder[len(adverb) :]
                if rest and rest[0] in _CLAUSE_END_CHARS:
                    peeled.append(adverb + rest[0])
                    remainder = rest[1:]
                else:
                    peeled.append(adverb)
                    remainder = rest
                matched = True
                break
            if not matched:
                peeled.append(remainder)
                break
    return peeled


# Function words from phrase MT (空は → "The sky is") — sticky suffixes carry these.
_CONTENT_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "by",
        "for",
        "from",
        "he",
        "her",
        "him",
        "his",
        "i",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "she",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "these",
        "they",
        "this",
        "those",
        "to",
        "us",
        "was",
        "we",
        "were",
        "with",
        "you",
        "your",
    }
)


def translate_ja_to_en(text: str, *, translator: Optional[Translator] = None) -> str:
    """Translate a short JA fragment to English (cached). Falls back to JA offline."""
    key = text.strip()
    if not key:
        return ""
    if key in _TRANSLATE_CACHE:
        return _TRANSLATE_CACHE[key]
    if translator is not None:
        value = translator(key).strip() or key
        _TRANSLATE_CACHE[key] = value
        return value
    try:
        url = f"{MYMEMORY_URL}?q={quote(key)}&langpair=ja|en"
        request = urllib.request.Request(url, headers={"User-Agent": "anki-satori-gloss/1.0"})
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.load(response)
        value = str((payload.get("responseData") or {}).get("translatedText") or "").strip()
        if not value or value.lower() == key.lower():
            value = key
        _TRANSLATE_CACHE[key] = value
        return value
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError):
        _TRANSLATE_CACHE[key] = key
        return key


def _normalize_mt_english(raw: str) -> str:
    """Drop MyMemory dictionary dumps like ``[きれい] /clean (an)/``."""
    text = re.sub(r"\[[^\]]*\]", " ", raw)
    text = re.sub(r"/([^/]+)/", r" \1 ", text)
    text = text.replace("(", " ").replace(")", " ")
    return text


def _is_content_mt_word(part: str) -> bool:
    if len(part) <= 1 or part in _CONTENT_STOPWORDS:
        return False
    if part.isdigit():
        return False
    # Skip function contractions (it's, don't) but keep content possessives.
    if "'" in part:
        left = part.split("'", 1)[0]
        if left in _CONTENT_STOPWORDS or left in {"it", "that", "what", "who", "there", "here"}:
            return False
    return True


_MT_REJECT_RE = re.compile(
    r"\b(fuck|fucking|shit|bullshit|damn|asshole|blah)\b",
    re.IGNORECASE,
)


def _content_words_from_mt(raw: str) -> List[str]:
    if _MT_REJECT_RE.search(raw or ""):
        return []
    text = _normalize_mt_english(raw)
    parts = [part.lower() for part in re.findall(r"[A-Za-z0-9']+", text)]
    content = [part for part in parts if _is_content_mt_word(part)]
    if content:
        return content
    return [part for part in parts if part not in _CONTENT_STOPWORDS] or parts


def _english_hint_words(english: str) -> set[str]:
    return {
        part.lower()
        for part in re.findall(r"[A-Za-z0-9']+", english or "")
        if _is_content_mt_word(part.lower())
    }


def _sticky_content_english(
    japanese: str,
    *,
    translator: Optional[Translator] = None,
    english_hint: str = "",
    also_try: Sequence[str] = (),
) -> str:
    """Turn a JA chunk/phrase into hyphenated sticky English content words.

    Tries the full chunk first, then optional shorter stems. When the card EN
    line is available, prefer MT words that also appear there (ひなたちは→ducks
    vs ひなたち→chicks + EN “chicks”).
    """
    phrases: List[str] = []
    for phrase in (japanese, *also_try):
        cleaned = phrase.strip()
        if cleaned and cleaned not in phrases:
            phrases.append(cleaned)
    if not phrases:
        return japanese

    # Satori EN often glosses ひな as chick(s); bare MT leaves "hina".
    hint = _english_hint_words(english_hint)
    if japanese.startswith("ひな") and "chicks" in hint:
        return "chicks"
    if japanese.startswith("ひな") and "chick" in hint:
        return "chick"

    phrase_contents = [
        _content_words_from_mt(translate_ja_to_en(phrase, translator=translator))
        for phrase in phrases
    ]
    if hint:
        primary = phrase_contents[0]
        primary_hits = [word for word in primary if word in hint]
        # Enough overlap with the card EN → keep full MT phrase (incl. verbs).
        if primary_hits and len(primary_hits) >= min(2, len(primary)):
            return "-".join(primary[:4])
        # Otherwise try shorter stems for sense (ひなたちは→ducks vs ひなたち→chicks).
        for content in phrase_contents[1:]:
            hits = [word for word in content if word in hint]
            if hits:
                return "-".join(hits[:4])
        if primary_hits:
            return "-".join(primary_hits[:4])

    content = phrase_contents[0]
    if not content:
        return japanese
    return "-".join(content[:4])


def _normalize_te_form_particle(bare: str, stem: str, particle: str) -> Tuple[str, str]:
    """Map で in んで／いで て-forms to a て-link particle."""
    if particle == "で" and bare.endswith("んで"):
        return bare[:-2], "んで"
    if particle == "で" and bare.endswith("いで"):
        return bare[:-2], "いで"
    return stem, particle


def _role_for_chunk(chunk: str, *, is_final: bool) -> str:
    bare = chunk.strip("。．！？!?、，,」』）)「『（( \t")
    stem, particle = _split_trailing_particle(bare)
    stem, particle = _normalize_te_form_particle(bare, stem, particle)
    if particle:
        return _PARTICLE_ROLE.get(particle, f"{particle}-car")
    _stem, engine = _split_trailing_engine(bare)
    if engine or is_final:
        return "engine"
    if bare:
        return "modifier/content"
    return "chunk"


def _lit_for_chunk(
    chunk: str,
    role: str,
    *,
    translator: Optional[Translator] = None,
    english_hint: str = "",
) -> str:
    """Japanese-order sticky English for one chunk."""
    bare = chunk.strip("。．！？!?、，,」』）)「『（( \t")
    if not bare:
        return ""

    stem, particle = _split_trailing_particle(bare)
    stem, particle = _normalize_te_form_particle(bare, stem, particle)
    if particle:
        sticky = _PARTICLE_STICKY.get(particle, particle)
        if not stem:
            return sticky
        # Full chunk for sense (空は→sky); stem as fallback (ひなたち→chicks).
        content = _sticky_content_english(
            bare,
            translator=translator,
            english_hint=english_hint,
            also_try=(stem,),
        )
        return f"{content}-{sticky}"

    stem, engine = _split_trailing_engine(bare)
    if engine:
        sticky = _ENGINE_STICKY.get(engine, engine)
        if not stem:
            return sticky
        content = _sticky_content_english(
            bare,
            translator=translator,
            english_hint=english_hint,
            also_try=(stem,),
        )
        return f"{content}-{sticky}"

    if role == "engine":
        sticky = _ENGINE_STICKY.get(bare)
        if sticky:
            return sticky
    return _sticky_content_english(
        bare,
        translator=translator,
        english_hint=english_hint,
    )


def analyze_gloss_sentence(
    item: GlossSentence,
    *,
    translator: Optional[Translator] = None,
    answer_cache: Optional[Dict[str, dict]] = None,
) -> GlossAnswer:
    """Build a checkable heuristic answer for one worksheet.

    When ``answer_cache`` is provided, a previously generated answer for the
    same sentence + English is reused (avoids re-running MT); new answers are
    written back into the dict so the caller can persist it.
    """
    key = ""
    if answer_cache is not None:
        key = gloss_answer_cache_key(item)
        cached = answer_cache.get(key)
        if isinstance(cached, dict):
            return GlossAnswer(
                chunk=str(cached.get("chunk", "")),
                role=str(cached.get("role", "")),
                lit=str(cached.get("lit", "")),
            )
    chunks = chunk_japanese_sentence(item.japanese)
    roles = [
        _role_for_chunk(chunk, is_final=(index == len(chunks) - 1))
        for index, chunk in enumerate(chunks)
    ]
    lits = [
        _lit_for_chunk(
            chunk,
            role,
            translator=translator,
            english_hint=item.english,
        )
        for chunk, role in zip(chunks, roles)
    ]
    answer = GlossAnswer(
        chunk="  ".join(chunks),
        role="  |  ".join(roles),
        lit=" · ".join(part for part in lits if part),
    )
    if answer_cache is not None:
        answer_cache[key] = {"chunk": answer.chunk, "role": answer.role, "lit": answer.lit}
    return answer


def _worksheet_header(item: GlossSentence, *, index: Optional[int], kind: str) -> List[str]:
    header_bits: List[str] = [kind]
    if index is not None:
        header_bits.append(f"#{index}")
    if item.note_id is not None:
        header_bits.append(f"note {item.note_id}")
    lines = ["═" * 64, " · ".join(header_bits)]
    if item.expression:
        target = item.expression
        if item.reading:
            target = f"{item.expression} ({item.reading})"
        lines.append(f"Target word: {target}")
    if item.source:
        lines.append(f"Source: {item.source}")
    return lines


def format_worksheet(item: GlossSentence, *, index: Optional[int] = None) -> str:
    """Render one worksheet block with blank CHUNK / ROLE / LIT lines."""
    english = item.english or "(no English on this note — fill after you check Satori)"
    lines = _worksheet_header(item, index=index, kind="Satori gloss worksheet")
    lines.extend(
        [
            "",
            f"JP:    {item.japanese}",
            "",
            f"# CHUNK — {CHUNK_HINT}",
            "CHUNK:",
            "",
            f"# ROLE — {ROLE_HINT}",
            "ROLE:",
            "",
            f"# LIT — {LIT_HINT}",
            "LIT:",
            "",
            f"EN:    {english}",
            "",
            f"ichi.moe: {ichi_moe_url(item.japanese)}",
            "═" * 64,
        ]
    )
    return "\n".join(lines)


def format_answer_worksheet(
    item: GlossSentence,
    *,
    index: Optional[int] = None,
    translator: Optional[Translator] = None,
    answer_cache: Optional[Dict[str, dict]] = None,
) -> str:
    """Same structure as the blank worksheet, filled with a heuristic answer."""
    answer = analyze_gloss_sentence(item, translator=translator, answer_cache=answer_cache)
    english = item.english or "(no English on this note)"
    lines = _worksheet_header(item, index=index, kind="Satori gloss answers")
    lines.extend(
        [
            "",
            f"JP:    {item.japanese}",
            "",
            f"# CHUNK — {CHUNK_HINT}",
            f"CHUNK: {answer.chunk}",
            "",
            f"# ROLE — {ROLE_HINT}",
            f"ROLE:  {answer.role}",
            "",
            f"# LIT — {LIT_HINT}",
            f"LIT:   {answer.lit}",
            "",
            f"EN:    {english}",
            "",
            f"ichi.moe: {ichi_moe_url(item.japanese)}",
            "═" * 64,
        ]
    )
    return "\n".join(lines)


def format_worksheets(
    items: Sequence[GlossSentence],
    *,
    include_answers: bool = False,
    translator: Optional[Translator] = None,
    answer_cache: Optional[Dict[str, dict]] = None,
) -> str:
    blank_blocks = [
        format_worksheet(item, index=i if len(items) > 1 else None)
        for i, item in enumerate(items, start=1)
    ]
    text = "\n\n".join(blank_blocks)
    if not include_answers or not items:
        return text
    answer_blocks = [
        format_answer_worksheet(
            item,
            index=i if len(items) > 1 else None,
            translator=translator,
            answer_cache=answer_cache,
        )
        for i, item in enumerate(items, start=1)
    ]
    answers = "\n\n".join(answer_blocks)
    return (
        f"{text}\n\n"
        f"{'─' * 64}\n"
        f"{ANSWER_KEY_BANNER}\n"
        f"{'─' * 64}\n\n"
        f"{answers}"
    )


def format_answer_key(
    items: Sequence[GlossSentence],
    *,
    translator: Optional[Translator] = None,
    answer_cache: Optional[Dict[str, dict]] = None,
) -> str:
    blocks = [
        format_answer_worksheet(
            item,
            index=i if len(items) > 1 else None,
            translator=translator,
            answer_cache=answer_cache,
        )
        for i, item in enumerate(items, start=1)
    ]
    return "\n\n".join(blocks)


def gloss_from_anki_fields(
    fields: dict,
    *,
    note_id: Optional[int] = None,
) -> Optional[GlossSentence]:
    """Build a worksheet item from AnkiConnect notesInfo field map."""

    def field(name: str) -> str:
        raw = fields.get(name)
        if isinstance(raw, dict):
            return strip_anki_html(str(raw.get("value", "")))
        return strip_anki_html(str(raw or ""))

    japanese = field("Sentence") or field("ClozeSentence")
    if not japanese:
        return None
    # Cloze markup like {{c1::暖かい}} → 暖かい for the JP line.
    japanese = re.sub(r"\{\{c\d+::([^}]+)\}\}", r"\1", japanese)
    return GlossSentence(
        japanese=japanese,
        english=field("Translation"),
        expression=field("Expression"),
        reading=field("Reading"),
        note_id=note_id,
        source=field("SourceTitle") or field("SourceUrl"),
    )


def gloss_items_from_notes(notes: Iterable[dict]) -> List[GlossSentence]:
    items: List[GlossSentence] = []
    for note in notes:
        note_id = note.get("noteId")
        fields = note.get("fields") or {}
        item = gloss_from_anki_fields(fields, note_id=int(note_id) if note_id is not None else None)
        if item is not None:
            items.append(item)
    return items
