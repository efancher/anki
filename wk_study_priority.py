"""
Study priority for core kanji and vocabulary.

Lower priority_score → introduced earlier in the new-card queue.
Uses approximate JLPT band from WK level.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from grammar_decks import JLPT_LEVELS

STUDY_PRIORITY_JSON = "wk_study_priority.json"

JLPT_WEIGHT = 10000
WK_LEVEL_WEIGHT = 100

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

JLPT_N5_VOCAB_TAG = "jlpt-n5-vocab"
JLPT_N5_PREREQ_TAG = "jlpt-n5-prereq"
JLPT_N5_FOCUS_BAND = "N5"


@dataclass(frozen=True)
class SubjectPriority:
    subject_id: int
    wk_level: int
    jlpt: str
    priority_score: int
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


def priority_score_for(jlpt: str, wk_level: int) -> int:
    return jlpt_sort_rank(jlpt) * JLPT_WEIGHT + wk_level * WK_LEVEL_WEIGHT


def priority_tags(
    entry: SubjectPriority,
    *,
    subject_object: str = "",
    include_grammar_role_tags: bool = True,
) -> List[str]:
    del include_grammar_role_tags
    tags = [f"priority-jlpt-{entry.jlpt}"]
    if entry.n5_direct and subject_object in ("kanji", "vocabulary"):
        tags.append(JLPT_N5_VOCAB_TAG)
    if entry.n5_prereq:
        tags.append(JLPT_N5_PREREQ_TAG)
    return tags


def _component_subject_ids(subject: dict) -> Tuple[int, ...]:
    ids = (subject.get("data") or {}).get("component_subject_ids") or []
    return tuple(int(component_id) for component_id in ids)


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
) -> Dict[int, SubjectPriority]:
    """Build JLPT-based priority scores for core subjects."""
    subjects_by_id = {
        int(subject["id"]): subject
        for subject in (*radical_items, *kanji_items, *vocab_items)
    }
    n5_direct_ids = build_jlpt_direct_ids(kanji_items, vocab_items, JLPT_N5_FOCUS_BAND)
    n5_closure = propagate_jlpt_prerequisite_ids(n5_direct_ids, subjects_by_id)

    index: Dict[int, SubjectPriority] = {}
    for subject in (*radical_items, *kanji_items, *vocab_items):
        subject_id = int(subject["id"])
        wk_level = int((subject.get("data") or {}).get("level") or 60)
        jlpt = wk_level_to_jlpt(wk_level)
        score = priority_score_for(jlpt, wk_level)
        index[subject_id] = SubjectPriority(
            subject_id=subject_id,
            wk_level=wk_level,
            jlpt=jlpt,
            priority_score=score,
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
                "n5_direct": entry.n5_direct,
                "n5_prereq": entry.n5_prereq,
            }
            for subject_id, entry in sorted(index.items())
        }
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
