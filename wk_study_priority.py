"""
Study priority for core kanji and vocabulary.

Lower priority_score → introduced earlier in the new-card queue.
Combines approximate JLPT band (from WK level) with earliest Tae Kim lesson match.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from grammar_decks import GrammarCardItem, JLPT_LEVELS

STUDY_PRIORITY_JSON = "wk_study_priority.json"
TAE_KIM_TRACK_MAP_JSON = "wk_tae_kim_track_map.json"
TAE_KIM_TRACK_CONFIG_JSON = "wk_tae_kim_track_config.json"

JLPT_WEIGHT = 10000
WK_LEVEL_WEIGHT = 100
TAE_KIM_BONUS = 50000
TAE_KIM_ORDER_SCALE = 10000

WK_LEVEL_JLPT_THRESHOLDS: Tuple[Tuple[int, str], ...] = (
    (10, "N5"),
    (20, "N4"),
    (35, "N3"),
    (45, "N2"),
    (60, "N1"),
)

KANJI_IN_TEXT_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
JP_TOKEN_BOUNDARY_RE = re.compile(
    r"[\s。、，．,.!?！？「」『』（）()\[\]{}・：；;…―ー\-—~～/\\|'" + r'"]'
)


def _is_token_boundary(text: str, index: int) -> bool:
    if index < 0 or index >= len(text):
        return True
    return bool(JP_TOKEN_BOUNDARY_RE.match(text[index]))


def expression_in_text(expression: str, text: str) -> bool:
    """True when expression appears as its own token (not inside a longer word)."""
    if not expression or not text:
        return False
    start = 0
    while True:
        idx = text.find(expression, start)
        if idx < 0:
            return False
        before_ok = _is_token_boundary(text, idx - 1)
        after_ok = _is_token_boundary(text, idx + len(expression))
        rest = text[idx + len(expression) :]
        if before_ok and (
            after_ok or rest.startswith(("だ", "です", "じゃ", "では", "だった", "でした"))
        ):
            return True
        start = idx + 1


def _reading_in_text(reading: str, text: str) -> bool:
    if not reading or not text:
        return False
    start = 0
    while True:
        idx = text.find(reading, start)
        if idx < 0:
            return False
        after_pos = idx + len(reading)
        if after_pos >= len(text):
            return True
        rest = text[after_pos:]
        if rest.startswith(("です", "だ", "。", "、", "！", "？", "!", "?")):
            return True
        if _is_token_boundary(text, after_pos):
            return True
        start = idx + 1


def _primary_readings(subject: dict) -> List[str]:
    readings = subject.get("data", {}).get("readings") or []
    return [str(item.get("reading") or "") for item in readings if item.get("reading")]


TK_GRAMMAR_VOCAB_TAG = "tk-grammar-vocab"
TK_GRAMMAR_PREREQ_TAG = "tk-grammar-prereq"
JLPT_N5_VOCAB_TAG = "jlpt-n5-vocab"
JLPT_N5_PREREQ_TAG = "jlpt-n5-prereq"
JLPT_N5_FOCUS_BAND = "N5"


@dataclass(frozen=True)
class SubjectPriority:
    subject_id: int
    wk_level: int
    jlpt: str
    priority_score: int
    tae_kim_order: Optional[int] = None
    tae_kim_direct: bool = False
    n5_direct: bool = False
    n5_prereq: bool = False


def jlpt_sort_rank(jlpt: str) -> int:
    try:
        return JLPT_LEVELS.index(jlpt)
    except ValueError:
        return len(JLPT_LEVELS)


def wk_level_to_jlpt(level: int) -> str:
    for threshold, jlpt in WK_LEVEL_JLPT_THRESHOLDS:
        if level <= threshold:
            return jlpt
    return "N1"


def lesson_sort_key(section_num: int, lesson_num: int) -> int:
    return section_num * TAE_KIM_ORDER_SCALE + lesson_num


def priority_score_for(
    jlpt: str,
    wk_level: int,
    *,
    tae_kim_order: Optional[int] = None,
) -> int:
    score = jlpt_sort_rank(jlpt) * JLPT_WEIGHT + wk_level * WK_LEVEL_WEIGHT
    if tae_kim_order is not None:
        score -= TAE_KIM_BONUS
        score -= max(0, TAE_KIM_ORDER_SCALE - min(tae_kim_order, TAE_KIM_ORDER_SCALE - 1))
    return score


def priority_tags(
    entry: SubjectPriority,
    *,
    subject_object: str = "",
    include_grammar_role_tags: bool = True,
) -> List[str]:
    tags = [f"priority-jlpt-{entry.jlpt}"]
    if entry.tae_kim_order is not None:
        tags.append(f"tk-priority-{entry.tae_kim_order:04d}")
        if include_grammar_role_tags:
            if entry.tae_kim_direct and subject_object in ("kanji", "vocabulary"):
                tags.append(TK_GRAMMAR_VOCAB_TAG)
            elif not entry.tae_kim_direct:
                tags.append(TK_GRAMMAR_PREREQ_TAG)
    if entry.n5_direct and subject_object in ("kanji", "vocabulary"):
        tags.append(JLPT_N5_VOCAB_TAG)
    if entry.n5_prereq:
        tags.append(JLPT_N5_PREREQ_TAG)
    return tags


def extract_kanji(text: str) -> Set[str]:
    return set(KANJI_IN_TEXT_RE.findall(text or ""))


def _min_reading_length_for_vocab_match(characters: str) -> int:
    """Kanji vocab with a one-mora reading (e.g. 葉→は) must not match particles in text."""
    if characters and KANJI_IN_TEXT_RE.search(characters):
        return 2
    return 1


def _subject_matches_text(subject: dict, text: str) -> bool:
    if not text:
        return False
    data = subject.get("data") or {}
    characters = str(data.get("characters") or "")
    if characters and expression_in_text(characters, text):
        return True
    min_reading_len = _min_reading_length_for_vocab_match(characters)
    for reading in _primary_readings(subject):
        if not reading or len(reading) < min_reading_len:
            continue
        if _reading_in_text(reading, text):
            return True
    return False


def _kanji_matches_text(subject: dict, text: str) -> bool:
    """Match kanji only as a standalone token, not as part of a compound (e.g. 背 in 背景)."""
    characters = str((subject.get("data") or {}).get("characters") or "")
    if not characters:
        return False
    return expression_in_text(characters, text)


def _text_entries_from_grammar_cards(cards: Sequence[GrammarCardItem]) -> List[Tuple[int, str]]:
    """Use each exercise's production answer only, not surrounding sentence context."""
    entries: List[Tuple[int, str]] = []
    for card in cards:
        lesson = card.tae_kim_lesson
        order = lesson_sort_key(
            card.tae_kim_section.num,
            lesson.num if lesson is not None else 999,
        )
        production = (card.type_expression or "").strip()
        if production:
            entries.append((order, production))
    return entries


def build_tae_kim_subject_orders(
    kanji_items: Sequence[dict],
    vocab_items: Sequence[dict],
    text_entries: Sequence[Tuple[int, str]],
) -> Dict[int, int]:
    """Map WkSubjectId → earliest Tae Kim lesson order index."""
    orders: Dict[int, int] = {}
    for order, text in text_entries:
        for subject in kanji_items:
            if _kanji_matches_text(subject, text):
                subject_id = int(subject["id"])
                orders[subject_id] = min(orders.get(subject_id, order), order)
        for subject in vocab_items:
            if _subject_matches_text(subject, text):
                subject_id = int(subject["id"])
                orders[subject_id] = min(orders.get(subject_id, order), order)
    return orders


def _component_subject_ids(subject: dict) -> Tuple[int, ...]:
    ids = (subject.get("data") or {}).get("component_subject_ids") or []
    return tuple(int(component_id) for component_id in ids)


def propagate_tae_kim_prerequisite_orders(
    direct_orders: Mapping[int, int],
    subjects_by_id: Mapping[int, dict],
) -> Dict[int, int]:
    """Boost prerequisites (radicals, kanji) to the earliest Tae Kim lesson of dependents."""
    merged: Dict[int, int] = dict(direct_orders)
    if not merged:
        return merged
    for _ in range(max(1, len(subjects_by_id))):
        changed = False
        for subject_id, order in list(merged.items()):
            subject = subjects_by_id.get(subject_id)
            if subject is None:
                continue
            for prereq_id in _component_subject_ids(subject):
                if prereq_id not in subjects_by_id:
                    continue
                if prereq_id not in merged or merged[prereq_id] > order:
                    merged[prereq_id] = order
                    changed = True
        if not changed:
            break
    return merged


def build_jlpt_direct_ids(
    kanji_items: Sequence[dict],
    vocab_items: Sequence[dict],
    jlpt_band: str,
) -> Set[int]:
    """Kanji/vocab whose WK level maps to the given JLPT band."""
    direct: Set[int] = set()
    for subject in (*kanji_items, *vocab_items):
        level = int((subject.get("data") or {}).get("level") or 60)
        if wk_level_to_jlpt(level) == jlpt_band:
            direct.add(int(subject["id"]))
    return direct


def propagate_jlpt_prerequisite_ids(
    direct_ids: Set[int],
    subjects_by_id: Mapping[int, dict],
) -> Set[int]:
    """All subjects in the prerequisite closure of direct kanji/vocab."""
    closure = set(direct_ids)
    if not closure:
        return closure
    for _ in range(max(1, len(subjects_by_id))):
        changed = False
        for subject_id in list(closure):
            subject = subjects_by_id.get(subject_id)
            if subject is None:
                continue
            for prereq_id in _component_subject_ids(subject):
                if prereq_id in subjects_by_id and prereq_id not in closure:
                    closure.add(prereq_id)
                    changed = True
        if not changed:
            break
    return closure


def build_core_priority_index(
    radical_items: Sequence[dict],
    kanji_items: Sequence[dict],
    vocab_items: Sequence[dict],
    *,
    tae_kim_priority_entries: Sequence[Tuple[int, str]] = (),
    tae_kim_exercise_cards: Sequence[GrammarCardItem] = (),
) -> Dict[int, SubjectPriority]:
    """Build priority tags from Tae Kim practice-page vocabulary lists (part1 on *_ex.html pages)."""
    if tae_kim_priority_entries:
        text_entries = list(tae_kim_priority_entries)
    else:
        text_entries = _text_entries_from_grammar_cards(tuple(tae_kim_exercise_cards))
    direct_orders = build_tae_kim_subject_orders(kanji_items, vocab_items, text_entries)
    subjects_by_id = {
        int(subject["id"]): subject
        for subject in (*radical_items, *kanji_items, *vocab_items)
    }
    tae_kim_orders = propagate_tae_kim_prerequisite_orders(direct_orders, subjects_by_id)
    direct_ids = set(direct_orders.keys())

    n5_direct_ids = build_jlpt_direct_ids(kanji_items, vocab_items, JLPT_N5_FOCUS_BAND)
    n5_closure = propagate_jlpt_prerequisite_ids(n5_direct_ids, subjects_by_id)

    index: Dict[int, SubjectPriority] = {}
    for subject in (*radical_items, *kanji_items, *vocab_items):
        subject_id = int(subject["id"])
        wk_level = int((subject.get("data") or {}).get("level") or 60)
        jlpt = wk_level_to_jlpt(wk_level)
        tk_order = tae_kim_orders.get(subject_id)
        score = priority_score_for(jlpt, wk_level, tae_kim_order=tk_order)
        index[subject_id] = SubjectPriority(
            subject_id=subject_id,
            wk_level=wk_level,
            jlpt=jlpt,
            priority_score=score,
            tae_kim_order=tk_order,
            tae_kim_direct=subject_id in direct_ids,
            n5_direct=subject_id in n5_direct_ids,
            n5_prereq=subject_id in n5_closure and subject_id not in n5_direct_ids,
        )
    return index


def write_study_priority_json(output_dir: Path, index: Mapping[int, SubjectPriority]) -> Path:
    path = output_dir / STUDY_PRIORITY_JSON
    payload = {
        "subjects": {
            str(subject_id): {
                "wk_level": entry.wk_level,
                "jlpt": entry.jlpt,
                "priority_score": entry.priority_score,
                "tae_kim_order": entry.tae_kim_order,
                "tae_kim_direct": entry.tae_kim_direct,
                "n5_direct": entry.n5_direct,
                "n5_prereq": entry.n5_prereq,
            }
            for subject_id, entry in sorted(index.items())
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_tae_kim_track_map(
    radical_items: Sequence[dict],
    kanji_items: Sequence[dict],
    vocab_items: Sequence[dict],
    vocabulary_by_lesson: Mapping[str, Sequence[Tuple[int, str]]],
    *,
    reading_lesson_order: Sequence[str],
) -> dict:
    """Per-lesson direct/prereq subject ids for runtime Tae Kim track sync."""
    subjects_by_id = {
        int(subject["id"]): subject
        for subject in (*radical_items, *kanji_items, *vocab_items)
    }
    lessons: Dict[str, dict] = {}
    for slug in reading_lesson_order:
        entries = vocabulary_by_lesson.get(slug) or ()
        if not entries:
            continue
        direct_orders = build_tae_kim_subject_orders(kanji_items, vocab_items, entries)
        all_orders = propagate_tae_kim_prerequisite_orders(direct_orders, subjects_by_id)
        direct_ids = sorted(direct_orders.keys())
        prereq_ids = sorted(subject_id for subject_id in all_orders if subject_id not in direct_orders)
        lesson_order = min(order for order, _ in entries)
        lessons[slug] = {
            "order": lesson_order,
            "direct_subject_ids": direct_ids,
            "prereq_subject_ids": prereq_ids,
        }
    return {
        "reading_lessons": [slug for slug in reading_lesson_order if slug in lessons],
        "lessons": lessons,
    }


def write_tae_kim_track_map(output_dir: Path, payload: Mapping[str, object]) -> Path:
    path = output_dir / TAE_KIM_TRACK_MAP_JSON
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_tae_kim_track_config_template(
    output_dir: Path,
    *,
    max_tae_kim_lesson: Optional[str],
    ahead_prereq_lessons: int = 1,
) -> Path:
    path = output_dir / TAE_KIM_TRACK_CONFIG_JSON
    payload = {
        "max_tae_kim_lesson": max_tae_kim_lesson,
        "ahead_prereq_lessons": ahead_prereq_lessons,
        "auto_run_on_load": True,
        "auto_update_filtered_decks": True,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_study_priority_json(path: Path) -> Dict[int, int]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    subjects = payload.get("subjects") or {}
    scores: Dict[int, int] = {}
    for key, entry in subjects.items():
        if not isinstance(entry, dict):
            continue
        try:
            subject_id = int(key)
        except ValueError:
            continue
        scores[subject_id] = int(entry.get("priority_score", 0))
    return scores
