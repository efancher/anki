"""
rendaku_decks.py

WaniKani vocabulary where the second kanji voices in compound (連濁).
Card: morpheme readings in isolation → type the full compound reading.
"""

from __future__ import annotations

import html
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import genanki

from wk_decks import (
    CACHE_DIR,
    COMMON_CSS,
    DECK_NAMES,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME,
    WkModel,
    first_reading,
    load_srs_stage_interval_days,
    primary_meanings,
    srs_stage,
    stable_guid,
    supplementary_import_tags,
    versioned_css,
    write_apkg,
)

# Voicing map for compound-initial consonants (rendaku / sequential voicing).
_RENDAKU_VOICE_MAP: Dict[str, str] = {
    "か": "が",
    "き": "ぎ",
    "く": "ぐ",
    "け": "げ",
    "こ": "ご",
    "さ": "ざ",
    "し": "じ",
    "す": "ず",
    "せ": "ぜ",
    "そ": "ぞ",
    "た": "だ",
    "ち": "ぢ",
    "つ": "づ",
    "て": "で",
    "と": "ど",
    "は": "ば",
    "ひ": "び",
    "ふ": "ぶ",
    "へ": "べ",
    "ほ": "ぼ",
    "ぱ": "ば",
    "ぴ": "び",
    "ぷ": "ぶ",
    "ぺ": "べ",
    "ぽ": "ぼ",
}

RENDAKU_DEFAULT_MIN_SRS = 7
RENDAKU_DECK_ID = 2059400131
RENDAKU_MODEL_ID = 1865429027
RENDAKU_DECK_NAME = DECK_NAMES["rendaku"]
RENDAKU_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["rendaku"]
RENDAKU_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["rendaku"]
RENDAKU_MODEL_TEMPLATE_KEY = "rendaku"
KANJI_READING_CANDIDATE_LIMIT = 8


class RendakuItem(NamedTuple):
    vocab: dict
    expression: str
    meaning: str
    reading: str
    first_reading: str
    second_base_reading: str
    second_voiced_reading: str
    second_kanji_char: str
    morpheme_hint: str
    rendaku_note: str


def voice_rendaku(reading: str) -> Optional[str]:
    if not reading:
        return None
    voiced_initial = _RENDAKU_VOICE_MAP.get(reading[0])
    if not voiced_initial:
        return None
    return voiced_initial + reading[1:]


def is_kanji_only(chars: str) -> bool:
    return bool(chars) and all("\u4e00" <= char <= "\u9fff" for char in chars)


def kanji_reading_candidates(kanji: dict) -> List[str]:
    data = kanji.get("data") or {}
    readings = data.get("readings") or []
    primary = [item["reading"] for item in readings if item.get("primary") or item.get("accepted_answer")]
    kunyomi = [item["reading"] for item in readings if item.get("type") == "kunyomi"]
    onyomi = [item["reading"] for item in readings if item.get("type") == "onyomi"]
    ordered: List[str] = []
    for group in (primary, kunyomi, onyomi):
        for reading in group:
            if reading and reading not in ordered:
                ordered.append(reading)
    return ordered[:KANJI_READING_CANDIDATE_LIMIT]


def rendaku_note_text(second_char: str, base: str, voiced: str) -> str:
    if not base or not voiced or base == voiced:
        return ""
    if base[0] != voiced[0]:
        return f"{second_char}: {base[0]} → {voiced[0]} (rendaku)"
    return f"{second_char}: {base} → {voiced}"


def analyze_two_kanji_rendaku(
    vocab: dict,
    kanji_by_id: Dict[int, dict],
) -> Optional[Tuple[str, str, str, str, str]]:
    """
    Return (first_reading, second_base, second_voiced, second_char, compound_reading)
    when only the voiced second morpheme matches the vocab reading.
    """
    data = vocab.get("data") or {}
    chars = str(data.get("characters") or "")
    if len(chars) != 2 or not is_kanji_only(chars):
        return None

    component_ids = data.get("component_subject_ids") or []
    if len(component_ids) != 2:
        return None

    first_kanji = kanji_by_id.get(component_ids[0])
    second_kanji = kanji_by_id.get(component_ids[1])
    if not first_kanji or not second_kanji:
        return None

    compound_reading = first_reading(vocab)
    if not compound_reading:
        return None

    plain_match = False
    voiced_match: Optional[Tuple[str, str, str]] = None
    for r1 in kanji_reading_candidates(first_kanji):
        for r2 in kanji_reading_candidates(second_kanji):
            if compound_reading == r1 + r2:
                plain_match = True
            voiced_r2 = voice_rendaku(r2)
            if voiced_r2 and compound_reading == r1 + voiced_r2:
                voiced_match = (r1, r2, voiced_r2)

    if plain_match or voiced_match is None:
        return None
    r1, r2, voiced_r2 = voiced_match
    return r1, r2, voiced_r2, chars[1], compound_reading


def collect_rendaku_items(
    vocab_items: Sequence[dict],
    kanji_items: Sequence[dict],
    assignment_index: Dict[int, dict],
    *,
    min_srs: int,
    max_level: int = 60,
) -> List[RendakuItem]:
    kanji_by_id = {item["id"]: item for item in kanji_items}
    items: List[RendakuItem] = []
    seen_vocab_ids: set[int] = set()

    for vocab in sorted(
        vocab_items,
        key=lambda item: (item["data"].get("level", 999), item["data"].get("characters") or ""),
    ):
        if vocab["id"] in seen_vocab_ids:
            continue
        data = vocab.get("data") or {}
        if int(data.get("level") or 999) > max_level:
            continue
        if srs_stage(vocab, assignment_index) < min_srs:
            continue

        analyzed = analyze_two_kanji_rendaku(vocab, kanji_by_id)
        if not analyzed:
            continue

        r1, r2_base, r2_voiced, second_char, compound_reading = analyzed
        expression = str(data.get("characters") or "")
        meaning = "; ".join(primary_meanings(vocab))
        items.append(
            RendakuItem(
                vocab=vocab,
                expression=expression,
                meaning=meaning,
                reading=compound_reading,
                first_reading=r1,
                second_base_reading=r2_base,
                second_voiced_reading=r2_voiced,
                second_kanji_char=second_char,
                morpheme_hint=f"{r1} + {r2_base}",
                rendaku_note=rendaku_note_text(second_char, r2_base, r2_voiced),
            )
        )
        seen_vocab_ids.add(vocab["id"])

    return items


def make_rendaku_model() -> WkModel:
    return WkModel(
        RENDAKU_MODEL_ID,
        RENDAKU_NOTE_TYPE_NAME,
        template_key=RENDAKU_MODEL_TEMPLATE_KEY,
        fields=[
            {"name": "GuidKey"},
            {"name": "WkSubjectId"},
            {"name": "Expression"},
            {"name": "Meaning"},
            {"name": "MorphemeHint"},
            {"name": "TypeReading"},
            {"name": "RendakuNote"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Compound reading (rendaku)",
                "qfmt": """
                <div class="prompt">Type the compound reading (rendaku on the second part)</div>
                <div class="jp">{{Expression}}</div>
                <div class="meaning">{{Meaning}}</div>
                <div class="morpheme-hint">{{MorphemeHint}}</div>
                <div class="type-answer">{{type:TypeReading}}</div>
                <div class="meta">{{Meta}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="reading answer">{{TypeReading}}</div>
                <div class="rendaku-note">{{RendakuNote}}</div>
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.jp { font-size: 42px; margin: 12px 0; }
.meaning { font-size: 18px; color: #bbb; margin-bottom: 8px; }
.morpheme-hint {
  font-size: 20px;
  color: #9ab;
  margin: 10px 0 16px;
  font-family: monospace;
}
.type-answer { margin: 16px auto; max-width: 520px; font-size: 30px; }
.reading.answer { font-size: 34px; color: #ddd; }
.rendaku-note { font-size: 18px; color: #c9a; margin-top: 8px; }
""",
            RENDAKU_MODEL_TEMPLATE_KEY,
        ),
    )


def build_rendaku_deck(
    items: Sequence[RendakuItem],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    interval_map=None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(RENDAKU_DECK_ID, RENDAKU_DECK_NAME)
    model = make_rendaku_model()
    template_label = RENDAKU_TEMPLATE_VERSION
    stage_interval_map = interval_map or load_srs_stage_interval_days(
        CACHE_DIR / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME
    )

    for item in items:
        vocab = item.vocab
        level = vocab["data"].get("level", "?")
        srs = srs_stage(vocab, assignment_index)
        guid = stable_guid("rendaku", vocab["id"])
        meta = f"WK L{level} · SRS {srs} · rendaku · template {template_label}"
        note_tags = [
            "wanikani",
            "rendaku",
            f"wk-level-{level}",
            f"rendaku-char-{item.second_kanji_char}",
        ]
        note_tags.extend(
            supplementary_import_tags(vocab, assignment_index, interval_map=stage_interval_map)
        )
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                str(vocab["id"]),
                html.escape(item.expression),
                html.escape(item.meaning),
                html.escape(item.morpheme_hint),
                html.escape(item.reading),
                html.escape(item.rendaku_note),
                html.escape(meta),
            ],
            tags=note_tags,
            guid=guid,
        )
        deck.add_note(note)

    out = output_dir / "wk_rendaku.apkg"
    write_apkg(deck, out)
    return out, deck
