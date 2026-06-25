"""
grammar_decks.py

Build Japanese grammar context cloze decks from Hanabira open grammar data
(https://github.com/tristcoil/hanabira.org, CC-licensed content).

Cards: production cloze on example sentences (type the missing grammar chunk).
Ordered JLPT N5 → N1; default cap at N2. Optional WK kanji readiness filter.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

import genanki
import html

from wk_decks import (
    CLOZE_BLANK_DISPLAY,
    CACHE_DIR,
    COMMON_CSS,
    DECK_NAMES,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WkModel,
    stable_guid,
    versioned_css,
    write_apkg,
)

HANABIRA_GRAMMAR_CACHE_DIR = CACHE_DIR / "hanabira_grammar"
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

# Skip English/Latin tokens scraped from formation lines.
_FORMATION_SKIP_RE = re.compile(r"^[A-Za-z0-9+\-/\\]+$")
_JP_RUN_RE = re.compile(r"[ぁ-んァ-ン一-龯々ー]+")


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
    for jlpt in JLPT_LEVELS:
        for entry in fetch_hanabira_grammar_level(jlpt, refresh=refresh):
            enriched = dict(entry)
            enriched["_jlpt"] = jlpt
            points.append(enriched)
    return points


def grammar_point_id(point: dict, example_index: int) -> str:
    jlpt = point.get("_jlpt") or point.get("p_tag", "").replace("JLPT_", "") or "?"
    order = int(point.get("s_tag") or 0)
    slug = re.sub(r"[^a-z0-9]+", "-", (point.get("title") or "point").lower()).strip("-")[:40]
    return f"{jlpt}-{order:03d}-{slug}-{example_index}"


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
                )
            )
            added += 1
    cards.sort(key=lambda item: (-JLPT_RANK[item.jlpt], item.order, item.title, item.point_id))
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
            {"name": "Formation"},
            {"name": "Title"},
            {"name": "TypeExpression"},
            {"name": "FullSentence"},
            {"name": "SentenceEnglish"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Grammar cloze",
                "qfmt": """
                <div class="prompt">Type the missing grammar</div>
                <div class="jp cloze">{{ClozeSentence}}</div>
                <div class="meaning hint">{{Hint}}</div>
                <div class="formation">{{Formation}}</div>
                <div class="type-answer">{{type:TypeExpression}}</div>
                <div class="meta">{{Meta}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="title answer">{{Title}}</div>
                <div class="context">
                  <div class="jp">{{FullSentence}}</div>
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
.formation { font-size: 14px; color: #999; margin: 8px 0; }
.type-answer { margin: 16px auto; max-width: 520px; font-size: 26px; }
.title.answer { font-size: 20px; color: #ccc; margin: 8px 0; }
""",
            GRAMMAR_MODEL_TEMPLATE_KEY,
        ),
    )


def build_grammar_deck(
    cards: Sequence[GrammarCardItem],
    output_dir: Path,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(GRAMMAR_DECK_ID, GRAMMAR_DECK_NAME)
    model = make_grammar_model()
    template_label = GRAMMAR_TEMPLATE_VERSION
    for item in cards:
        guid = stable_guid("grammar", item.point_id)
        meta = f"JLPT {item.jlpt} · order {item.order} · Hanabira · template {template_label}"
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                html.escape(item.cloze_sentence),
                html.escape(item.short_explanation),
                html.escape(item.formation),
                html.escape(item.title),
                html.escape(item.type_expression),
                html.escape(item.full_sentence),
                html.escape(item.sentence_en),
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
    out = output_dir / "wk_grammar.apkg"
    write_apkg(deck, out)
    return out, deck
