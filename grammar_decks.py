"""
grammar_decks.py

Build Japanese grammar context cloze decks from Hanabira open grammar data
(https://github.com/tristcoil/hanabira.org, CC-licensed content).

Cards: production cloze on example sentences (type the missing grammar chunk).
Ordered by Tae Kim section (3 Basic → 6 Advanced), then JLPT N5 → N1.
Optional cap via --grammar-max-tae-kim-section to match your reading progress.
Early Tae Kim lessons (e.g. state-of-being) also use curated fixtures in
tae_kim_grammar_fixtures.json when Hanabira has no matching grammar points,
plus WaniKani context sentences matched by lesson patterns in the same file.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

import genanki
import html

from tae_kim_mapping import (
    TaeKimLesson,
    TaeKimSection,
    map_grammar_point_to_tae_kim_lesson,
    map_grammar_point_to_tae_kim_section,
    parse_tae_kim_lesson_cap,
    tae_kim_card_tags,
    tae_kim_lesson,
    tae_kim_lesson_by_slug,
    tae_kim_lesson_within_cap,
    tae_kim_section_by_slug,
    tae_kim_section_within_cap,
)
from wk_decks import (
    CLOZE_BLANK_DISPLAY,
    CACHE_DIR,
    COMMON_CSS,
    DECK_NAMES,
    DEFAULT_SENTENCE_AUDIO_VOICE,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WkModel,
    apply_wk_paren_readings,
    ensure_sentence_audio_file,
    load_cache_items_only,
    require_edge_tts,
    stable_guid,
    strip_html,
    versioned_css,
    write_apkg,
)

HANABIRA_GRAMMAR_CACHE_DIR = CACHE_DIR / "hanabira_grammar"
GRAMMAR_MEDIA_SUBDIR = "media/grammar_cloze"
HANABIRA_GRAMMAR_RAW_BASE = (
    "https://raw.githubusercontent.com/tristcoil/hanabira.org/main/backend/express/json_data"
)
HANABIRA_GRAMMAR_COMMIT = "main"
JLPT_LEVELS = ("N5", "N4", "N3", "N2", "N1")
JLPT_RANK = {"N5": 5, "N4": 4, "N3": 3, "N2": 2, "N1": 1}
GRAMMAR_DEFAULT_MAX_JLPT = "N2"
GRAMMAR_DEFAULT_EXAMPLES_PER_POINT = 2
GRAMMAR_DEFAULT_MAX_UNKNOWN_KANJI = 5
GRAMMAR_DEFAULT_MAX_TAE_KIM_SECTION = 6
GRAMMAR_DECK_ID = 2059400125
GRAMMAR_MODEL_ID = 1865429023
GRAMMAR_DECK_NAME = DECK_NAMES["grammar"]
GRAMMAR_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["grammar_cloze"]
GRAMMAR_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["grammar_cloze"]
GRAMMAR_MODEL_TEMPLATE_KEY = "grammar_cloze"

# Skip English/Latin tokens scraped from formation lines.
_FORMATION_SKIP_RE = re.compile(r"^[A-Za-z0-9+\-/\\]+$")
_JP_RUN_RE = re.compile(r"[ぁ-んァ-ン一-龯々ー]+")
TAE_KIM_GRAMMAR_FIXTURES_FILENAME = "tae_kim_grammar_fixtures.json"
TAE_KIM_SUPPLEMENT_POINT_PREFIX = "tk-fixture"
WK_GRAMMAR_SUPPLEMENT_POINT_PREFIX = "wk-grammar"
_STATE_OF_BEING_TOPIC_MARKERS = frozenset("はがも")
_PRODUCTION_HINT_SUBJECT_RE = re.compile(
    r"^(?:I|you|he|she|it|we|they|this|that|there|here|my|your|his|her|its|our|their|"
    r"the\s+[\w'-]+(?:\s+[\w'-]+){0,3})\s+(.+)$",
    re.IGNORECASE,
)


class GrammarCardItem(NamedTuple):
    point_id: str
    jlpt: str
    order: int
    title: str
    short_explanation: str
    formation: str
    cloze_sentence: str
    full_sentence: str
    sentence_en: str
    type_expression: str
    hint: str
    tae_kim_section: TaeKimSection
    tae_kim_lesson: Optional[TaeKimLesson]


def hanabira_grammar_cache_path(jlpt: str) -> Path:
    return HANABIRA_GRAMMAR_CACHE_DIR / f"grammar_ja_JLPT_{jlpt}_0001.json"


def fetch_hanabira_grammar_level(jlpt: str, *, refresh: bool = False) -> List[dict]:
    cache_path = hanabira_grammar_cache_path(jlpt)
    if cache_path.is_file() and not refresh:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    url = f"{HANABIRA_GRAMMAR_RAW_BASE}/grammar_ja_JLPT_{jlpt}_0001.json"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        if cache_path.is_file():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        raise RuntimeError(
            f"Could not download Hanabira grammar for JLPT {jlpt} ({url}). "
            "Check network or use --refresh-cache after a successful download."
        ) from exc

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_hanabira_grammar_points(*, refresh: bool = False) -> List[dict]:
    points: List[dict] = []
    batch = 0
    for jlpt in JLPT_LEVELS:
        for entry in fetch_hanabira_grammar_level(jlpt, refresh=refresh):
            enriched = dict(entry)
            enriched["_jlpt"] = jlpt
            enriched["_batch"] = batch
            batch += 1
            points.append(enriched)
    return points


def grammar_point_id(point: dict, example_index: int) -> str:
    jlpt = point.get("_jlpt") or point.get("p_tag", "").replace("JLPT_", "") or "?"
    order = int(point.get("s_tag") or 0)
    batch = int(point.get("_batch") or 0)
    title = (point.get("title") or "").strip()
    title_key = hashlib.sha1(title.encode("utf-8")).hexdigest()[:10]
    return f"{jlpt}-{order:03d}-{title_key}-{batch}-{example_index}"


def grammar_audio_basename(point_id: str) -> str:
    safe = hashlib.sha1(point_id.encode("utf-8")).hexdigest()[:16]
    return f"wk_grammar_{safe}.mp3"


def prepare_grammar_sentence_for_tts(sentence: str) -> str:
    return apply_wk_paren_readings(sentence.strip())


def grammar_blank_tokens(point: dict) -> List[str]:
    tokens: Set[str] = set()
    for field in ("formation", "title", "short_explanation"):
        text = point.get(field) or ""
        for match in _JP_RUN_RE.finditer(text):
            token = match.group(0)
            if len(token) < 2:
                continue
            if _FORMATION_SKIP_RE.match(token):
                continue
            if token in {"形容詞", "動詞", "名詞", "副詞"}:
                continue
            tokens.add(token)
    return sorted(tokens, key=len, reverse=True)


def blank_grammar_in_sentence(sentence: str, tokens: Sequence[str]) -> Optional[Tuple[str, str]]:
    plain = sentence.strip()
    if not plain:
        return None
    for token in tokens:
        idx = plain.find(token)
        if idx >= 0:
            cloze = plain[:idx] + CLOZE_BLANK_DISPLAY + plain[idx + len(token):]
            return cloze, token
    return None


def sentence_unknown_kanji(sentence: str, known_kanji: Set[str]) -> int:
    if not known_kanji:
        return 0
    return sum(1 for char in sentence if "\u4e00" <= char <= "\u9fff" and char not in known_kanji)


def known_kanji_from_subjects(vocab_items: Sequence[dict], kanji_items: Sequence[dict]) -> Set[str]:
    chars: Set[str] = set()
    for subject in (*vocab_items, *kanji_items):
        text = (subject.get("data") or {}).get("characters") or ""
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                chars.add(char)
    return chars


def jlpt_within_cap(jlpt: str, max_jlpt: str) -> bool:
    return JLPT_RANK.get(jlpt, 0) >= JLPT_RANK.get(max_jlpt, 0)


def tae_kim_grammar_fixtures_path() -> Path:
    return Path(__file__).resolve().parent / TAE_KIM_GRAMMAR_FIXTURES_FILENAME


def load_tae_kim_grammar_fixtures_payload() -> dict:
    path = tae_kim_grammar_fixtures_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return payload


def load_tae_kim_grammar_fixtures() -> List[dict]:
    fixtures = load_tae_kim_grammar_fixtures_payload().get("fixtures") or []
    if not isinstance(fixtures, list):
        raise ValueError(f"{TAE_KIM_GRAMMAR_FIXTURES_FILENAME} must contain a top-level 'fixtures' list.")
    return fixtures


def load_wk_lesson_supplement_specs() -> List[dict]:
    specs = load_tae_kim_grammar_fixtures_payload().get("wk_lesson_supplements") or []
    if not isinstance(specs, list):
        raise ValueError(
            f"{TAE_KIM_GRAMMAR_FIXTURES_FILENAME} must contain a top-level 'wk_lesson_supplements' list."
        )
    return specs


def load_cached_wk_vocab_items() -> List[dict]:
    """Offline WK vocabulary for grammar supplements when the full generator was run before."""
    items = load_cache_items_only("subjects", "vocabulary_kanji_radical")
    if not items:
        return []
    return [item for item in items if item.get("object") == "vocabulary"]


def blank_regex_in_sentence(sentence: str, pattern: re.Pattern[str]) -> Optional[Tuple[str, str]]:
    match = pattern.search(sentence)
    if not match:
        return None
    if match.lastindex and match.lastindex >= 1:
        start, end = match.span(1)
        chunk = match.group(1)
    else:
        start, end = match.span()
        chunk = match.group(0)
    if not chunk:
        return None
    cloze = sentence[:start] + CLOZE_BLANK_DISPLAY + sentence[end:]
    return cloze, chunk


_FORM_HINT_TRAILING_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")
_FORM_HINT_LEADING_JP_DASH_RE = re.compile(
    r"^[\s　]*(?:[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff/・\s]+)\s*[—–\-]\s*",
    re.UNICODE,
)
_FORM_HINT_HAS_LATIN_RE = re.compile(r"[A-Za-z]")
_FORM_HINT_JP_CHAR_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]")


def _form_hint_label_is_safe(label: str) -> bool:
    """Skip labels that are mostly Japanese — they often contain the answer chunk."""
    if not label or not _FORM_HINT_HAS_LATIN_RE.search(label):
        return False
    return _FORM_HINT_JP_CHAR_RE.search(label) is None


def grammar_form_hint(title: str) -> str:
    """Register/form label for the card front (e.g. 'casual positive'), without answer morphemes."""
    plain = (title or "").strip()
    if not plain:
        return ""
    plain = _FORM_HINT_TRAILING_PARENS_RE.sub("", plain).strip()
    if ": " in plain:
        plain = plain.split(": ", 1)[1].strip()
        plain = _FORM_HINT_TRAILING_PARENS_RE.sub("", plain).strip()
    elif " · " in plain:
        parts = [part.strip() for part in plain.split(" · ")]
        if len(parts) >= 2:
            candidate = parts[-1]
            if _form_hint_label_is_safe(candidate):
                return candidate
    plain = _FORM_HINT_LEADING_JP_DASH_RE.sub("", plain).strip()
    if _form_hint_label_is_safe(plain):
        return plain
    return ""


def production_hint_from_english(sentence_en: str) -> str:
    """Drop the English subject so the hint reads like 'am a student', 'like cats'."""
    plain = strip_html(sentence_en).strip().rstrip(".!?")
    if not plain:
        return ""
    match = _PRODUCTION_HINT_SUBJECT_RE.match(plain)
    if match:
        return match.group(1).strip()
    return plain


def predicate_span_before_copula(sentence: str, copula_start: int) -> Tuple[int, int]:
    """Return (blank_start, type_start) for the predicate before a copula match."""
    for index in range(copula_start - 1, -1, -1):
        if sentence[index] in _STATE_OF_BEING_TOPIC_MARKERS:
            blank_start = index + 1
            type_start = blank_start
            while type_start < copula_start and sentence[type_start] in "、， ":
                type_start += 1
            return blank_start, type_start
    return 0, 0


def blank_state_of_being_predicate(
    sentence: str,
    copula_start: int,
    copula_end: int,
    sentence_en: str,
) -> Optional[Tuple[str, str, str]]:
    """Blank noun/adjective + copula; type the full predicate from a meaning hint."""
    blank_start, type_start = predicate_span_before_copula(sentence, copula_start)
    type_expression = sentence[type_start:copula_end].strip()
    if not type_expression:
        type_expression = sentence[copula_start:copula_end].strip()
        blank_start = copula_start
    if not type_expression:
        return None
    cloze = sentence[:blank_start] + CLOZE_BLANK_DISPLAY + sentence[copula_end:]
    hint = production_hint_from_english(sentence_en)
    return cloze, type_expression, hint


def blank_state_of_being_from_pattern(
    sentence: str,
    pattern: re.Pattern[str],
    sentence_en: str,
) -> Optional[Tuple[str, str, str]]:
    match = pattern.search(sentence)
    if not match:
        return None
    if match.lastindex and match.lastindex >= 1:
        copula_start, copula_end = match.span(1)
    else:
        copula_start, copula_end = match.span()
    return blank_state_of_being_predicate(sentence, copula_start, copula_end, sentence_en)


def wk_grammar_point_id(
    *,
    lesson_slug: str,
    pattern_id: str,
    vocab_id: int,
    sentence: str,
) -> str:
    sentence_key = hashlib.sha1(sentence.encode("utf-8")).hexdigest()[:10]
    return f"{WK_GRAMMAR_SUPPLEMENT_POINT_PREFIX}-{lesson_slug}-{pattern_id}-{vocab_id}-{sentence_key}"


def collect_wk_grammar_supplement_cards(
    vocab_items: Sequence[dict],
    *,
    max_jlpt: str,
    max_tae_kim_section: int,
    lesson_cap: Optional[Tuple[str, int]],
    known_kanji: Set[str],
    max_unknown_kanji: int,
    max_examples_per_point: int,
    existing_sentences: Set[str],
) -> List[GrammarCardItem]:
    """Build grammar cloze cards from WaniKani context sentences for Tae Kim lesson gaps."""
    if not vocab_items:
        return []

    basic_section = tae_kim_section_by_slug("basic-grammar")
    if basic_section is None or not tae_kim_section_within_cap(basic_section.num, max_tae_kim_section):
        return []

    cards: List[GrammarCardItem] = []
    seen_sentences: Set[str] = set(existing_sentences)
    pattern_counts: Dict[str, int] = {}

    for spec in load_wk_lesson_supplement_specs():
        jlpt = str(spec.get("jlpt") or "N5")
        if not jlpt_within_cap(jlpt, max_jlpt):
            continue
        lesson_slug = str(spec.get("lesson") or "").strip()
        lesson = tae_kim_lesson_by_slug("basic", lesson_slug)
        if lesson is None:
            continue
        if lesson_cap is not None:
            chapter, max_lesson_num = lesson_cap
            if not tae_kim_lesson_within_cap(
                lesson,
                basic_section,
                max_chapter=chapter,
                max_lesson_num=max_lesson_num,
            ):
                continue

        compiled_patterns: List[Tuple[dict, re.Pattern[str]]] = []
        for row in spec.get("patterns") or []:
            regex = str(row.get("regex") or "").strip()
            pattern_id = str(row.get("id") or "").strip()
            if not regex or not pattern_id:
                continue
            compiled_patterns.append((row, re.compile(regex)))

        if not compiled_patterns:
            continue

        for vocab in vocab_items:
            if vocab.get("object") != "vocabulary":
                continue
            vocab_id = int(vocab.get("id") or 0)
            for sentence in vocab["data"].get("context_sentences") or []:
                jp = strip_html(sentence.get("ja") or "")
                en = strip_html(sentence.get("en") or "")
                if not jp or not en:
                    continue
                if jp in seen_sentences:
                    continue
                if known_kanji and sentence_unknown_kanji(jp, known_kanji) > max_unknown_kanji:
                    continue

                matched_row: Optional[dict] = None
                blanked: Optional[Tuple[str, str, str]] = None
                for row, pattern in compiled_patterns:
                    pattern_id = str(row.get("id") or "")
                    if pattern_counts.get(pattern_id, 0) >= max_examples_per_point:
                        continue
                    candidate = blank_state_of_being_from_pattern(jp, pattern, en)
                    if candidate:
                        matched_row = row
                        blanked = candidate
                        break
                if not matched_row or not blanked:
                    continue

                cloze, type_expression, hint = blanked
                pattern_id = str(matched_row.get("id") or "")
                pattern_counts[pattern_id] = pattern_counts.get(pattern_id, 0) + 1
                seen_sentences.add(jp)
                cards.append(
                    GrammarCardItem(
                        point_id=wk_grammar_point_id(
                            lesson_slug=lesson_slug,
                            pattern_id=pattern_id,
                            vocab_id=vocab_id,
                            sentence=jp,
                        ),
                        jlpt=jlpt,
                        order=int(matched_row.get("order") or spec.get("order") or 0),
                        title=str(matched_row.get("title") or spec.get("title") or "").strip(),
                        short_explanation=str(
                            matched_row.get("short_explanation") or spec.get("short_explanation") or ""
                        ).strip(),
                        formation=str(matched_row.get("formation") or spec.get("formation") or "").strip(),
                        cloze_sentence=cloze,
                        full_sentence=jp,
                        sentence_en=en,
                        type_expression=type_expression,
                        hint=hint,
                        tae_kim_section=basic_section,
                        tae_kim_lesson=lesson,
                    )
                )

    return cards


def collect_tae_kim_supplement_cards(
    *,
    max_jlpt: str,
    max_tae_kim_section: int,
    lesson_cap: Optional[Tuple[str, int]],
    known_kanji: Set[str],
    max_unknown_kanji: int,
) -> List[GrammarCardItem]:
    """Curated cards aligned to Tae Kim lessons when Hanabira has no matching points."""
    basic_section = tae_kim_section_by_slug("basic-grammar")
    if basic_section is None or not tae_kim_section_within_cap(basic_section.num, max_tae_kim_section):
        return []

    cards: List[GrammarCardItem] = []
    for row in load_tae_kim_grammar_fixtures():
        jlpt = str(row.get("jlpt") or "N5")
        if not jlpt_within_cap(jlpt, max_jlpt):
            continue
        lesson_slug = str(row.get("lesson") or "").strip()
        lesson = tae_kim_lesson_by_slug("basic", lesson_slug)
        if lesson is None:
            continue
        if lesson_cap is not None:
            chapter, max_lesson_num = lesson_cap
            if not tae_kim_lesson_within_cap(
                lesson,
                basic_section,
                max_chapter=chapter,
                max_lesson_num=max_lesson_num,
            ):
                continue
        full_sentence = str(row.get("full_sentence") or "").strip()
        if known_kanji and sentence_unknown_kanji(full_sentence, known_kanji) > max_unknown_kanji:
            continue
        fixture_id = str(row.get("id") or "").strip()
        if not fixture_id:
            continue
        sentence_en = str(row.get("sentence_en") or "").strip()
        hint = str(row.get("hint") or "").strip() or production_hint_from_english(sentence_en)
        cards.append(
            GrammarCardItem(
                point_id=f"{TAE_KIM_SUPPLEMENT_POINT_PREFIX}-{fixture_id}",
                jlpt=jlpt,
                order=int(row.get("order") or 0),
                title=str(row.get("title") or "").strip(),
                short_explanation=str(row.get("short_explanation") or "").strip(),
                formation=str(row.get("formation") or "").strip(),
                cloze_sentence=str(row.get("cloze_sentence") or "").strip(),
                full_sentence=full_sentence,
                sentence_en=sentence_en,
                type_expression=str(row.get("type_expression") or "").strip(),
                hint=hint,
                tae_kim_section=basic_section,
                tae_kim_lesson=lesson,
            )
        )
    return cards


def collect_grammar_cards(
    *,
    max_jlpt: str = GRAMMAR_DEFAULT_MAX_JLPT,
    max_tae_kim_section: int = GRAMMAR_DEFAULT_MAX_TAE_KIM_SECTION,
    max_tae_kim_lesson: Optional[str] = None,
    max_examples_per_point: int = GRAMMAR_DEFAULT_EXAMPLES_PER_POINT,
    max_unknown_kanji: int = GRAMMAR_DEFAULT_MAX_UNKNOWN_KANJI,
    known_kanji: Optional[Set[str]] = None,
    vocab_items: Optional[Sequence[dict]] = None,
    wk_supplements: bool = True,
    refresh: bool = False,
) -> List[GrammarCardItem]:
    cards: List[GrammarCardItem] = []
    kanji_filter = known_kanji or set()
    lesson_cap: Optional[Tuple[str, int]] = None
    if max_tae_kim_lesson:
        lesson_cap = parse_tae_kim_lesson_cap(max_tae_kim_lesson)
    for point in load_hanabira_grammar_points(refresh=refresh):
        jlpt = point.get("_jlpt") or "N1"
        if not jlpt_within_cap(jlpt, max_jlpt):
            continue
        tae_kim = map_grammar_point_to_tae_kim_section(point)
        if not tae_kim_section_within_cap(tae_kim.num, max_tae_kim_section):
            continue
        lesson = map_grammar_point_to_tae_kim_lesson(point, section=tae_kim)
        if lesson_cap is not None:
            chapter, max_lesson_num = lesson_cap
            if not tae_kim_lesson_within_cap(
                lesson,
                tae_kim,
                max_chapter=chapter,
                max_lesson_num=max_lesson_num,
            ):
                continue
        tokens = grammar_blank_tokens(point)
        if not tokens:
            continue
        order = int(point.get("s_tag") or 0)
        title = (point.get("title") or "").strip()
        short = (point.get("short_explanation") or "").strip()
        formation = (point.get("formation") or "").strip()
        added = 0
        for example_index, example in enumerate(point.get("examples") or []):
            if added >= max_examples_per_point:
                break
            jp = (example.get("jp") or "").strip()
            en = (example.get("en") or "").strip()
            if not jp or not en:
                continue
            if kanji_filter and sentence_unknown_kanji(jp, kanji_filter) > max_unknown_kanji:
                continue
            blanked = blank_grammar_in_sentence(jp, tokens)
            if not blanked:
                continue
            cloze, chunk = blanked
            cards.append(
                GrammarCardItem(
                    point_id=grammar_point_id(point, example_index),
                    jlpt=jlpt,
                    order=order,
                    title=title,
                    short_explanation=short,
                    formation=formation,
                    cloze_sentence=cloze,
                    full_sentence=jp,
                    sentence_en=en,
                    type_expression=chunk,
                    hint=short,
                    tae_kim_section=tae_kim,
                    tae_kim_lesson=lesson,
                )
            )
            added += 1
    cards.extend(
        collect_tae_kim_supplement_cards(
            max_jlpt=max_jlpt,
            max_tae_kim_section=max_tae_kim_section,
            lesson_cap=lesson_cap,
            known_kanji=kanji_filter,
            max_unknown_kanji=max_unknown_kanji,
        )
    )
    if wk_supplements:
        wk_vocab = list(vocab_items) if vocab_items is not None else load_cached_wk_vocab_items()
        cards.extend(
            collect_wk_grammar_supplement_cards(
                wk_vocab,
                max_jlpt=max_jlpt,
                max_tae_kim_section=max_tae_kim_section,
                lesson_cap=lesson_cap,
                known_kanji=kanji_filter,
                max_unknown_kanji=max_unknown_kanji,
                max_examples_per_point=max_examples_per_point,
                existing_sentences={card.full_sentence for card in cards},
            )
        )
    cards.sort(
        key=lambda item: (
            item.tae_kim_section.num,
            item.tae_kim_lesson.num if item.tae_kim_lesson else 999,
            -JLPT_RANK[item.jlpt],
            item.order,
            item.title,
            item.point_id,
        )
    )
    return cards


def make_grammar_model() -> WkModel:
    return WkModel(
        GRAMMAR_MODEL_ID,
        GRAMMAR_NOTE_TYPE_NAME,
        template_key=GRAMMAR_MODEL_TEMPLATE_KEY,
        fields=[
            {"name": "GuidKey"},
            {"name": "ClozeSentence"},
            {"name": "Hint"},
            {"name": "FormHint"},
            {"name": "Formation"},
            {"name": "Title"},
            {"name": "TypeExpression"},
            {"name": "FullSentence"},
            {"name": "SentenceEnglish"},
            {"name": "SentenceAudio"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Grammar cloze",
                "qfmt": """
                <div class="prompt">Type the missing phrase</div>
                <div class="jp cloze">{{ClozeSentence}}</div>
                <div class="meaning hint">{{Hint}}</div>
                {{#FormHint}}<div class="form-hint">{{FormHint}}</div>{{/FormHint}}
                <div class="type-answer">{{type:TypeExpression}}</div>
                <div class="meta">{{Meta}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="title answer">{{Title}}</div>
                <div class="formation">{{Formation}}</div>
                <div class="context">
                  <div class="jp">{{FullSentence}}</div>
                  {{#SentenceAudio}}<div class="sentence-audio">{{SentenceAudio}}</div>{{/SentenceAudio}}
                  <div class="meaning">{{SentenceEnglish}}</div>
                </div>
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.cloze { font-size: 32px; line-height: 1.55; }
.hint { font-size: 16px; margin-top: 10px; color: #bbb; font-style: italic; }
.form-hint { font-size: 15px; margin-top: 6px; color: #c8c8c8; font-weight: 600; letter-spacing: 0.02em; }
.formation { font-size: 14px; color: #999; margin: 8px 0; }
.type-answer { margin: 16px auto; max-width: 520px; font-size: 26px; }
.title.answer { font-size: 20px; color: #ccc; margin: 8px 0; }
.sentence-audio { margin-top: 10px; margin-bottom: 4px; }
""",
            GRAMMAR_MODEL_TEMPLATE_KEY,
        ),
    )


def build_grammar_deck(
    cards: Sequence[GrammarCardItem],
    output_dir: Path,
    *,
    sentence_audio: bool = True,
    sentence_audio_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh_sentence_audio: bool = False,
) -> Tuple[Path, genanki.Deck, List[str]]:
    deck = genanki.Deck(GRAMMAR_DECK_ID, GRAMMAR_DECK_NAME)
    model = make_grammar_model()
    template_label = GRAMMAR_TEMPLATE_VERSION
    media_dir = output_dir / GRAMMAR_MEDIA_SUBDIR
    media_files: List[str] = []
    audio_ok = 0
    audio_cached = 0
    audio_new = 0
    if sentence_audio:
        require_edge_tts()
        print(f"Grammar sentence audio (voice={sentence_audio_voice})...")
    for item in cards:
        guid = stable_guid("grammar", item.point_id)
        tk = item.tae_kim_section
        lesson = item.tae_kim_lesson
        if lesson is not None:
            source = (
                "WaniKani"
                if item.point_id.startswith(f"{WK_GRAMMAR_SUPPLEMENT_POINT_PREFIX}-")
                else "Tae Kim fixture"
                if item.point_id.startswith(f"{TAE_KIM_SUPPLEMENT_POINT_PREFIX}-")
                else "Hanabira"
            )
            meta = (
                f"Tae Kim {lesson.chapter_name} · {lesson.num:02d} {lesson.name} · "
                f"JLPT {item.jlpt} · {source} · template {template_label}"
            )
        else:
            meta = (
                f"Tae Kim §{tk.num} {tk.name} · JLPT {item.jlpt} · order {item.order} · "
                f"Hanabira · template {template_label}"
            )
        sentence_audio_field = ""
        if sentence_audio:
            basename = grammar_audio_basename(item.point_id)
            dest = media_dir / basename
            tts_text = prepare_grammar_sentence_for_tts(item.full_sentence)
            ok, was_cached = ensure_sentence_audio_file(
                tts_text,
                sentence_audio_voice,
                dest,
                refresh=refresh_sentence_audio,
            )
            if ok:
                sentence_audio_field = f"[sound:{basename}]"
                media_files.append(str(dest.resolve()))
                audio_ok += 1
                if was_cached:
                    audio_cached += 1
                else:
                    audio_new += 1
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                html.escape(item.cloze_sentence),
                html.escape(item.hint),
                html.escape(grammar_form_hint(item.title)),
                html.escape(item.formation),
                html.escape(item.title),
                html.escape(item.type_expression),
                html.escape(item.full_sentence),
                html.escape(item.sentence_en),
                sentence_audio_field,
                html.escape(meta),
            ],
            tags=[
                "grammar",
                *(
                    ["wanikani"]
                    if item.point_id.startswith(f"{WK_GRAMMAR_SUPPLEMENT_POINT_PREFIX}-")
                    else ["hanabira"]
                ),
                f"jlpt-{item.jlpt.lower()}",
                f"grammar-order-{item.order:03d}",
                "priority-medium",
                *tae_kim_card_tags(tk, lesson),
            ],
            guid=guid,
        )
        deck.add_note(note)
    if sentence_audio:
        print(
            f"Grammar sentence audio: {audio_ok}/{len(cards)} cards "
            f"({audio_new} new, {audio_cached} cached)"
        )
        if cards and audio_ok == 0:
            print(
                "  Warning: no grammar sentence audio was generated. "
                "Install edge-tts, check network, or pass --no-grammar-sentence-audio to skip.",
                file=sys.stderr,
            )
    deck.wk_media_files = media_files
    out = output_dir / "wk_grammar.apkg"
    write_apkg(deck, out, media_files=media_files or None)
    return out, deck, media_files
