"""
grammar_decks.py

Build Japanese grammar context cloze decks from Hanabira open grammar data
(https://github.com/tristcoil/hanabira.org, CC-licensed content).

Cards: production cloze on example sentences (type the missing grammar chunk).
Ordered by JLPT N5 → N1, then Hanabira point order within each level.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Set, Tuple

import genanki
import html

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
    stable_guid,
    tts_audio_basename_for_config,
    WK_SHARED_MEDIA_SUBDIR,
    strip_html,
    versioned_css,
    write_apkg,
)
from wk_sentence_tts import SentenceTtsConfig, require_sentence_tts

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
GRAMMAR_DECK_ID = 2059400125
GRAMMAR_MODEL_ID = 1865429023
GRAMMAR_DECK_NAME = DECK_NAMES["grammar"]
GRAMMAR_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["grammar_cloze"]
GRAMMAR_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["grammar_cloze"]
GRAMMAR_MODEL_TEMPLATE_KEY = "grammar_cloze"

_FORMATION_SKIP_RE = re.compile(r"^[A-Za-z0-9+\-/\\]+$")
_JP_RUN_RE = re.compile(r"[ぁ-んァ-ン一-龯々ー]+")
_STATE_OF_BEING_TOPIC_MARKERS = frozenset("はがも")
_PRODUCTION_HINT_SUBJECT_RE = re.compile(
    r"^(?:I|you|he|she|it|we|they|this|that|there|here|my|your|his|her|its|our|their|"
    r"the\s+[\w'-]+(?:\s+[\w'-]+){0,3})\s+(.+)$",
    re.IGNORECASE,
)
_FORM_HINT_TRAILING_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")
_FORM_HINT_LEADING_JP_DASH_RE = re.compile(
    r"^[\s　]*(?:[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff/・\s]+)\s*[—–\-]\s*",
    re.UNICODE,
)
_FORM_HINT_HAS_LATIN_RE = re.compile(r"[A-Za-z]")
_FORM_HINT_JP_CHAR_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]")


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
    """Deprecated: use tts_audio_basename(sentence, voice) for packaged media."""
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


def _form_hint_label_is_safe(label: str) -> bool:
    if not label or not _FORM_HINT_HAS_LATIN_RE.search(label):
        return False
    return _FORM_HINT_JP_CHAR_RE.search(label) is None


def grammar_form_hint(title: str) -> str:
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
    plain = strip_html(sentence_en).strip().rstrip(".!?")
    if not plain:
        return ""
    match = _PRODUCTION_HINT_SUBJECT_RE.match(plain)
    if match:
        return match.group(1).strip()
    return plain


def predicate_span_before_copula(sentence: str, copula_start: int) -> Tuple[int, int]:
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


def collect_grammar_cards(
    *,
    max_jlpt: str = GRAMMAR_DEFAULT_MAX_JLPT,
    max_examples_per_point: int = GRAMMAR_DEFAULT_EXAMPLES_PER_POINT,
    max_unknown_kanji: int = GRAMMAR_DEFAULT_MAX_UNKNOWN_KANJI,
    known_kanji: Optional[Set[str]] = None,
    refresh: bool = False,
) -> List[GrammarCardItem]:
    cards: List[GrammarCardItem] = []
    kanji_filter = known_kanji or set()
    for point in load_hanabira_grammar_points(refresh=refresh):
        jlpt = point.get("_jlpt") or "N1"
        if not jlpt_within_cap(jlpt, max_jlpt):
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
                )
            )
            added += 1
    cards.sort(
        key=lambda item: (
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
    sentence_tts_config: Optional[SentenceTtsConfig] = None,
    sentence_audio_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh_sentence_audio: bool = False,
) -> Tuple[Path, genanki.Deck, List[str]]:
    tts_config = sentence_tts_config or SentenceTtsConfig.edge_only(sentence_audio_voice)
    deck = genanki.Deck(GRAMMAR_DECK_ID, GRAMMAR_DECK_NAME)
    model = make_grammar_model()
    template_label = GRAMMAR_TEMPLATE_VERSION
    media_dir = output_dir / WK_SHARED_MEDIA_SUBDIR
    media_files: List[str] = []
    audio_ok = 0
    audio_cached = 0
    audio_new = 0
    if sentence_audio:
        require_sentence_tts(tts_config)
        print(f"Grammar sentence audio (engine={tts_config.engine})...")
    for item in cards:
        guid = stable_guid("grammar", item.point_id)
        meta = (
            f"JLPT {item.jlpt} · order {item.order} · "
            f"Hanabira · template {template_label}"
        )
        sentence_audio_field = ""
        if sentence_audio:
            tts_text = prepare_grammar_sentence_for_tts(item.full_sentence)
            basename = tts_audio_basename_for_config(tts_text, tts_config)
            if basename:
                dest = media_dir / basename
                ok, was_cached = ensure_sentence_audio_file(
                    tts_text,
                    tts_config,
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
                "hanabira",
                f"jlpt-{item.jlpt.lower()}",
                f"grammar-order-{item.order:03d}",
                "priority-medium",
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
                "Install edge-tts, start VOICEVOX, check network, or pass --no-grammar-sentence-audio to skip.",
                file=sys.stderr,
            )
    deck.wk_media_files = media_files
    out = output_dir / "wk_grammar.apkg"
    write_apkg(deck, out, media_files=media_files or None)
    return out, deck, media_files
