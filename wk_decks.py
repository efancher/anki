#!/usr/bin/env python3
"""
wk_decks.py

Generate update-safe Anki decks from your WaniKani account.

Decks:
  - leeches: items you repeatedly miss in WaniKani
  - verb-pairs: transitive/intransitive and related contrast pairs
  - confusables: vocabulary sharing kanji/readings that are easy to mix up
  - phonetic-families: kanji grouped by repeated reading-bearing components
  - pitch-leeches: leeches with pitch data, if pitch data is supplied
  - radicals: current-level and next-level radicals
  - all: all of the above

Install:
  pip install requests genanki

Basic use:
  export WANIKANI_API_TOKEN="your_token_here"
  python wk_decks.py --deck all --only-started

With pitch CSV:
  python wk_decks.py --deck all --only-started --pitch-csv pitch.csv

Preview without writing decks:
  python wk_decks.py --deck all --only-started --dry-run

Recommended weekly import (one file, all decks):
  python wk_decks.py --deck all --only-started
  # then import out/wk_all.apkg into Anki

With Yomitan pitch dictionary zip/folder:
  python wk_decks.py --deck all --only-started --yomitan-dict ~/japanese-dicts/kanjium_pitch_accents.zip
"""

from __future__ import annotations

VERSION = "2.8.0"
BUILD_DATE = "2026-06-11"

import warnings

warnings.filterwarnings(
    "ignore",
    message="urllib3 v2 only supports OpenSSL",
)

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import genanki
import requests

WK_API_BASE = "https://api.wanikani.com/v2"
WK_REVISION = "20170710"
CACHE_DIR = Path(".wk_cache")
CACHE_MAX_AGE_HOURS = 24
OUTPUT_DIR = Path("out")

# Leech scoring weights
LEECH_RECENCY_BOOST_DAYS = 3
LEECH_RECENCY_MID_DAYS = 14
LEECH_RECENCY_STALE_DAYS = 60
LEECH_RECENCY_BOOST = 1.5
LEECH_RECENCY_MID = 1.2
LEECH_RECENCY_STALE = 0.85
LEECH_STREAK_PENALTY_MAX = 5
LEECH_STREAK_PENALTY_STEP = 0.2
LEECH_WEAK_SIDE_MIN_INCORRECT = 2
CONTEXT_SENTENCE_LIMIT = 3
SECONDS_PER_DAY = 86400
REVIEW_STATS_BATCH_SIZE = 100

# Keep stable after first import.
DECK_IDS = {
    "leeches": 2059400111,
    "verb-pairs": 2059400112,
    "confusables": 2059400113,
    "phonetic-families": 2059400114,
    "pitch-leeches": 2059400115,
    "radicals": 2059400116,
}

MODEL_IDS = {
    "item": 1865429012,
    "pair": 1865429013,
    "family": 1865429014,
    "radical": 1865429015,
}

ITEM_MODEL_TEMPLATE_VERSION = "v4"

# Stable Anki note type names — do not embed version numbers here.
# Template/schema version lives in ITEM_MODEL_TEMPLATE_VERSION and card Meta fields.
NOTE_TYPE_NAMES = {
    "item": "WK Update-Safe Item",
    "pair": "WK Update-Safe Verb Pair",
    "family": "WK Update-Safe Family",
    "radical": "WK Update-Safe Radical",
}

BUNDLE_FILENAME = "wk_all.apkg"
FILTERED_DECKS_JSON = "anki_filtered_decks.json"

# anki.decks.Deck.Filtered.SearchTerm.Order.RELATIVE_OVERDUENESS
FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS = 10

FILTERED_DECK_DEFINITIONS = [
    {
        "name": "WK::Daily Priority",
        "search": '(tag:priority-high) AND (deck:"WaniKani Leech Fixes" OR deck:"WaniKani Verb Pair Contrasts")',
        "limit": 30,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Verb Contrasts",
        "search": 'deck:"WaniKani Verb Pair Contrasts" AND (tag:priority-high OR tag:priority-medium)',
        "limit": 30,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Leeches",
        "search": 'deck:"WaniKani Leech Fixes"',
        "limit": 50,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Meaning Leeches",
        "search": 'deck:"WaniKani Leech Fixes" AND tag:leech-meaning',
        "limit": 30,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Reading Leeches",
        "search": 'deck:"WaniKani Leech Fixes" AND tag:leech-reading',
        "limit": 30,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Radicals Preview",
        "search": 'deck:"WaniKani Current and Next Radicals"',
        "limit": 20,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Confusables Light",
        "search": 'deck:"WaniKani Confusable Vocabulary" AND tag:priority-high',
        "limit": 20,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
]

DECK_NAMES = {
    "leeches": "WaniKani Leech Fixes",
    "verb-pairs": "WaniKani Verb Pair Contrasts",
    "confusables": "WaniKani Confusable Vocabulary",
    "phonetic-families": "WaniKani Phonetic Families",
    "pitch-leeches": "WaniKani Pitch Leeches",
    "radicals": "WaniKani Current and Next Radicals",
}

PAIR_RULES = [
    ("がる", "げる"),
    ("まる", "める"),
    ("かる", "ける"),
    ("わる", "える"),
    ("つ", "てる"),
    ("れる", "す"),
    ("える", "やす"),
    ("く", "ける"),
]

CURATED_READING_PAIRS = {
    "あく": "あける",
    "しまる": "しめる",
    "つく": "つける",
    "でる": "だす",
    "みえる": "みる",
    "みせる": "みる",
    "きこえる": "きく",
    "きかせる": "きく",
}

PHONETIC_COMPONENTS = [
    "青", "工", "寺", "方", "可", "反", "皮", "良", "亡", "包", "生", "令", "吾", "羊",
    "各", "交", "台", "成", "易", "曷", "爰", "央", "申", "肖", "昔", "票", "咸", "兼",
    "喿", "倉", "莫", "馬", "半", "白", "主", "且", "奇", "其", "求", "朱", "占", "少",
    "氏", "司", "者", "采", "甫", "孚", "戔", "夬", "圭", "奚", "果", "奏", "曼", "雚",
]

COMMON_CSS = """
.card {
  font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", "Noto Sans JP", sans-serif;
  font-size: 20px;
  text-align: center;
  line-height: 1.45;
}
.jp { font-size: 42px; margin-top: 12px; }
.reading { font-size: 26px; margin-top: 4px; color: #d8d8d8; font-weight: 500; }
.meaning { font-size: 19px; color: #cfcfcf; margin-bottom: 8px; }
.meta { font-size: 14px; color: #aaa; }
.prompt { font-weight: bold; margin-bottom: 16px; }
.pitch { font-size: 18px; margin: 6px; }
.synonyms { font-size: 15px; color: #555; }
.leech { font-size: 14px; color: #900; font-weight: bold; }
.notes { text-align: left; margin: 12px auto; max-width: 760px; }
.pair-line { font-size: 36px; margin: 12px; }
.family-title { font-size: 36px; margin: 12px; }
.family-members { text-align: left; margin: 0 auto; max-width: 820px; }
.member { margin: 8px 0; border-bottom: 1px solid #ddd; padding-bottom: 8px; }
.front-members { margin: 12px auto; max-width: 760px; }
.front-member { display: inline-block; margin: 6px 10px; font-size: 32px; }
.front-reading { display: block; font-size: 18px; color: #d8d8d8; font-weight: 500; }

.pair-front-item { margin: 10px auto; }
.relationship-question { font-size: 16px; color: #bbb; margin-bottom: 10px; }
.relationship { font-size: 22px; margin: 12px; font-weight: bold; }
.pair-arrow { font-size: 28px; margin: 4px; }
.pair-back-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
@media (max-width: 700px) { .pair-back-grid { display: block; } }

/* Anki desktop/mobile night mode readability */
.nightMode .reading,
.card.nightMode .reading,
.night_mode .reading {
  color: #f0f0f0;
  font-weight: 600;
}

.nightMode .front-reading,
.card.nightMode .front-reading,
.night_mode .front-reading {
  color: #eeeeee;
  font-weight: 600;
}

.nightMode .meaning,
.card.nightMode .meaning,
.night_mode .meaning {
  color: #dddddd;
}

.nightMode .meta,
.card.nightMode .meta,
.night_mode .meta,
.nightMode .relationship-question,
.card.nightMode .relationship-question,
.night_mode .relationship-question {
  color: #c8c8c8;
}

.answer { font-weight: 600; margin-top: 8px; }
.reading.answer { font-size: 34px; }
.meaning.answer { font-size: 24px; }
.reading-detail { font-size: 16px; color: #aaa; margin-top: 6px; }
.nightMode .reading-detail,
.card.nightMode .reading-detail,
.night_mode .reading-detail {
  color: #cccccc;
}
.context { text-align: left; margin: 10px auto; max-width: 760px; padding: 8px 0; border-top: 1px solid #ddd; }
.context .jp { font-size: 22px; margin-top: 0; }
.weak-side { font-size: 14px; color: #900; font-weight: bold; margin-bottom: 8px; }

"""


def cache_path(collection: str, params_key: str = "all") -> Path:
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", params_key)
    return CACHE_DIR / f"{collection}_{safe_key}.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_cache_envelope(raw: Any) -> dict:
    if isinstance(raw, list):
        return {"synced_at": None, "items": raw}
    if isinstance(raw, dict) and "items" in raw:
        return raw
    raise ValueError("Unexpected cache format")


def merge_records(existing: Sequence[dict], updates: Sequence[dict]) -> List[dict]:
    by_id = {item["id"]: item for item in existing}
    for item in updates:
        by_id[item["id"]] = item
    return list(by_id.values())


def load_json_cache(path: Path, max_age_hours: int, refresh: bool = False) -> Optional[Any]:
    if refresh or not path.exists():
        return None
    if time.time() - path.stat().st_mtime > max_age_hours * 3600:
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_cache_envelope(path: Path, max_age_hours: int, refresh: bool = False) -> Tuple[Optional[dict], bool]:
    """Return (envelope, is_stale). envelope is None when a full download is required."""
    if refresh or not path.exists():
        return None, False
    age_seconds = time.time() - path.stat().st_mtime
    is_stale = age_seconds > max_age_hours * 3600
    with path.open("r", encoding="utf-8") as f:
        return normalize_cache_envelope(json.load(f)), is_stale


def save_cache_envelope(path: Path, items: Sequence[dict], synced_at: Optional[str] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"synced_at": synced_at or utc_now_iso(), "items": list(items)}
    with path.open("w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)


def save_json_cache(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def wk_headers() -> dict:
    token = os.environ.get("WANIKANI_API_TOKEN")
    if not token:
        raise RuntimeError("Set WANIKANI_API_TOKEN first.")
    return {"Authorization": f"Bearer {token}", "Wanikani-Revision": WK_REVISION}


def wk_get_resource(resource: str) -> dict:
    response = requests.get(f"{WK_API_BASE}/{resource}", headers=wk_headers(), timeout=45)
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", "5"))
        print(f"Rate limited by WaniKani. Waiting {retry_after}s...")
        time.sleep(retry_after)
        return wk_get_resource(resource)
    response.raise_for_status()
    return response.json()


def wk_get_all(collection: str, params: Optional[dict] = None) -> List[dict]:
    url = f"{WK_API_BASE}/{collection}"
    out: List[dict] = []
    while url:
        response = requests.get(url, headers=wk_headers(), params=params, timeout=45)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "5"))
            print(f"Rate limited by WaniKani. Waiting {retry_after}s...")
            time.sleep(retry_after)
            continue
        response.raise_for_status()
        payload = response.json()
        out.extend(payload.get("data", []))
        url = payload.get("pages", {}).get("next_url")
        params = None
    return out


def batched(values: Sequence[int], size: int) -> Iterable[List[int]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def assignment_params_key(params: dict) -> str:
    parts = []
    for key in sorted(params):
        value = params[key]
        if isinstance(value, list):
            parts.append(f"{key}={'-'.join(str(v) for v in value)}")
        else:
            parts.append(f"{key}={value}")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", "_".join(parts)) if parts else "all"


def build_assignment_params(args: argparse.Namespace) -> dict:
    params: dict = {"subject_types": "radical,kanji,vocabulary"}
    if args.max_level < 60:
        params["levels"] = ",".join(str(level) for level in range(1, args.max_level + 1))
    if args.only_started:
        params["started"] = "true"
    if args.only_unlocked:
        params["unlocked"] = "true"
    if args.only_burned:
        params["burned"] = "true"
    if args.min_srs > 0:
        params["srs_stages"] = ",".join(str(stage) for stage in range(args.min_srs, 10))
    return params


def get_cached_user(refresh: bool = False) -> dict:
    path = CACHE_DIR / "user.json"
    cached = load_json_cache(path, CACHE_MAX_AGE_HOURS, refresh=refresh)
    if cached is not None:
        print(f"Using cached user: {path}")
        return cached
    print("Downloading WaniKani user...")
    payload = wk_get_resource("user")
    user = payload["data"]
    save_json_cache(path, user)
    print(f"Saved user cache: {path}")
    return user


def get_cached_collection(
    collection: str,
    *,
    params: Optional[dict] = None,
    params_key: str = "all",
    refresh: bool = False,
) -> List[dict]:
    path = cache_path(collection, params_key)
    envelope, is_stale = load_cache_envelope(path, CACHE_MAX_AGE_HOURS, refresh=refresh)

    if envelope is not None and not is_stale and not refresh:
        print(f"Using cached {collection}: {path} ({len(envelope['items'])} items)")
        return envelope["items"]

    if envelope is not None and is_stale and envelope.get("synced_at") and not refresh:
        print(f"Incremental sync for {collection} since {envelope['synced_at']}...")
        sync_params = dict(params or {})
        sync_params["updated_after"] = envelope["synced_at"]
        delta = wk_get_all(collection, params=sync_params)
        items = merge_records(envelope["items"], delta)
        save_cache_envelope(path, items)
        print(f"Updated {collection} cache: {path} (+{len(delta)} changed, {len(items)} total)")
        return items

    print(f"Downloading WaniKani {collection}...")
    items = wk_get_all(collection, params=params)
    save_cache_envelope(path, items)
    print(f"Saved {collection} cache: {path} ({len(items)} items)")
    return items


def fetch_review_statistics(
    subject_ids: Sequence[int],
    *,
    updated_after: Optional[str] = None,
) -> List[dict]:
    if updated_after:
        return wk_get_all(
            "review_statistics",
            params={
                "subject_types": "kanji,vocabulary",
                "updated_after": updated_after,
            },
        )

    if not subject_ids:
        return wk_get_all(
            "review_statistics",
            params={"subject_types": "kanji,vocabulary"},
        )

    out: List[dict] = []
    for batch in batched(list(subject_ids), REVIEW_STATS_BATCH_SIZE):
        out.extend(
            wk_get_all(
                "review_statistics",
                params={
                    "subject_ids": ",".join(str(subject_id) for subject_id in batch),
                    "subject_types": "kanji,vocabulary",
                },
            )
        )
    return merge_records([], out)


def get_cached_review_statistics(
    subject_ids: Sequence[int],
    *,
    params_key: str = "all",
    refresh: bool = False,
) -> List[dict]:
    path = cache_path("review_statistics", params_key)
    envelope, is_stale = load_cache_envelope(path, CACHE_MAX_AGE_HOURS, refresh=refresh)

    if envelope is not None and not is_stale and not refresh:
        print(f"Using cached review_statistics: {path} ({len(envelope['items'])} items)")
        return envelope["items"]

    if envelope is not None and is_stale and envelope.get("synced_at") and not refresh:
        print(f"Incremental sync for review_statistics since {envelope['synced_at']}...")
        delta = fetch_review_statistics(subject_ids, updated_after=envelope["synced_at"])
        items = merge_records(envelope["items"], delta)
        save_cache_envelope(path, items)
        print(f"Updated review_statistics cache: {path} (+{len(delta)} changed, {len(items)} total)")
        return items

    print("Downloading WaniKani review_statistics...")
    items = fetch_review_statistics(subject_ids)
    save_cache_envelope(path, items)
    print(f"Saved review_statistics cache: {path} ({len(items)} items)")
    return items


def write_apkg(deck: genanki.Deck, path: Path) -> None:
    genanki.Package(deck).write_to_file(str(path))


def write_bundled_apkg(decks: Sequence[genanki.Deck], path: Path) -> None:
    if not decks:
        return
    package = genanki.Package(decks[0])
    package.decks = list(decks)
    package.write_to_file(str(path))


def primary_meanings(subject: dict) -> List[str]:
    meanings = subject["data"].get("meanings", [])
    primary = [m["meaning"] for m in meanings if m.get("primary") or m.get("accepted_answer")]
    return primary or [m["meaning"] for m in meanings]


def primary_readings(subject: dict) -> List[str]:
    readings = subject["data"].get("readings", [])
    primary = [r["reading"] for r in readings if r.get("primary") or r.get("accepted_answer")]
    return primary or [r["reading"] for r in readings]


def first_reading(subject: dict) -> str:
    rs = primary_readings(subject)
    return rs[0] if rs else ""


def strip_html(value: Optional[str]) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def index_by_subject_id(items: Iterable[dict]) -> Dict[int, dict]:
    return {i["data"]["subject_id"]: i for i in items}


def assignment_by_subject_id(assignments: Iterable[dict]) -> Dict[int, dict]:
    return index_by_subject_id(assignments)


def review_stats_by_subject_id(review_statistics: Iterable[dict]) -> Dict[int, dict]:
    return index_by_subject_id(review_statistics)


def study_materials_by_subject_id(study_materials: Iterable[dict]) -> Dict[int, dict]:
    return index_by_subject_id(study_materials)


def srs_stage(subject: dict, assignment_index: Dict[int, dict]) -> int:
    assignment = assignment_index.get(subject["id"])
    return int(assignment["data"].get("srs_stage") or 0) if assignment else 0


def is_unlocked(subject: dict, assignment_index: Dict[int, dict]) -> bool:
    assignment = assignment_index.get(subject["id"])
    return bool(assignment and assignment["data"].get("unlocked_at"))


def is_started(subject: dict, assignment_index: Dict[int, dict]) -> bool:
    assignment = assignment_index.get(subject["id"])
    return bool(assignment and assignment["data"].get("started_at"))


def is_burned(subject: dict, assignment_index: Dict[int, dict]) -> bool:
    assignment = assignment_index.get(subject["id"])
    return bool(assignment and assignment["data"].get("burned_at"))


def passes_progress_filter(subject: dict, assignment_index: Dict[int, dict], args: argparse.Namespace) -> bool:
    if subject["data"].get("level", 999) > args.max_level:
        return False
    if args.only_unlocked and not is_unlocked(subject, assignment_index):
        return False
    if args.only_started and not is_started(subject, assignment_index):
        return False
    if args.only_burned and not is_burned(subject, assignment_index):
        return False
    return srs_stage(subject, assignment_index) >= args.min_srs


def review_stats_data(subject: dict, review_index: Dict[int, dict]) -> dict:
    stats = review_index.get(subject["id"])
    return stats["data"] if stats else {}


def meaning_incorrect(subject: dict, review_index: Dict[int, dict]) -> int:
    return int(review_stats_data(subject, review_index).get("meaning_incorrect") or 0)


def reading_incorrect(subject: dict, review_index: Dict[int, dict]) -> int:
    return int(review_stats_data(subject, review_index).get("reading_incorrect") or 0)


def meaning_streak(subject: dict, review_index: Dict[int, dict]) -> int:
    return int(review_stats_data(subject, review_index).get("meaning_current_streak") or 0)


def reading_streak(subject: dict, review_index: Dict[int, dict]) -> int:
    return int(review_stats_data(subject, review_index).get("reading_current_streak") or 0)


def incorrect_total(subject: dict, review_index: Dict[int, dict]) -> int:
    return meaning_incorrect(subject, review_index) + reading_incorrect(subject, review_index)


def current_streak_min(subject: dict, review_index: Dict[int, dict]) -> int:
    stats = review_index.get(subject["id"])
    if not stats:
        return 999
    return min(meaning_streak(subject, review_index), reading_streak(subject, review_index))


def parse_wk_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def recency_weight(updated_at: Optional[str]) -> float:
    reviewed_at = parse_wk_timestamp(updated_at)
    if reviewed_at is None:
        return 1.0
    age_days = (datetime.now(timezone.utc) - reviewed_at).total_seconds() / SECONDS_PER_DAY
    if age_days <= LEECH_RECENCY_BOOST_DAYS:
        return LEECH_RECENCY_BOOST
    if age_days <= LEECH_RECENCY_MID_DAYS:
        return LEECH_RECENCY_MID
    if age_days <= LEECH_RECENCY_STALE_DAYS:
        return 1.0
    return LEECH_RECENCY_STALE


def streak_penalty(streak_min: int) -> float:
    return 1.0 + max(0, LEECH_STREAK_PENALTY_MAX - streak_min) * LEECH_STREAK_PENALTY_STEP


def error_rate_factor(subject: dict, review_index: Dict[int, dict]) -> float:
    data = review_stats_data(subject, review_index)
    pct_correct = data.get("percentage_correct")
    if pct_correct is not None:
        return max(0.05, (100.0 - float(pct_correct)) / 100.0)
    incorrect = incorrect_total(subject, review_index)
    attempts = incorrect + max(current_streak_min(subject, review_index), 1)
    return max(0.05, incorrect / attempts)


def leech_score(subject: dict, review_index: Dict[int, dict]) -> float:
    incorrect = incorrect_total(subject, review_index)
    if incorrect <= 0:
        return 0.0
    data = review_stats_data(subject, review_index)
    return incorrect * error_rate_factor(subject, review_index) * streak_penalty(current_streak_min(subject, review_index)) * recency_weight(data.get("updated_at"))


def is_leech(subject: dict, review_index: Dict[int, dict], args: argparse.Namespace) -> bool:
    if incorrect_total(subject, review_index) < args.leech_incorrect_min:
        return False
    if current_streak_min(subject, review_index) > args.leech_streak_max:
        return False
    return leech_score(subject, review_index) >= args.leech_score_min


def leech_weakness_tags(subject: dict, review_index: Dict[int, dict]) -> List[str]:
    tags: List[str] = []
    m_wrong = meaning_incorrect(subject, review_index)
    r_wrong = reading_incorrect(subject, review_index)
    m_streak = meaning_streak(subject, review_index)
    r_streak = reading_streak(subject, review_index)

    if m_wrong >= LEECH_WEAK_SIDE_MIN_INCORRECT and (m_wrong > r_wrong or m_streak < r_streak):
        tags.append("leech-meaning")
    if r_wrong >= LEECH_WEAK_SIDE_MIN_INCORRECT and (r_wrong > m_wrong or r_streak < m_streak):
        tags.append("leech-reading")
    return tags


def leech_label(subject: dict, review_index: Dict[int, dict]) -> str:
    total = incorrect_total(subject, review_index)
    if not total:
        return ""
    score = leech_score(subject, review_index)
    pct = review_stats_data(subject, review_index).get("percentage_correct")
    pct_text = f", accuracy={pct}%" if pct is not None else ""
    return (
        f"score={score:.1f}{pct_text}, "
        f"meaning misses={meaning_incorrect(subject, review_index)} (streak={meaning_streak(subject, review_index)}), "
        f"reading misses={reading_incorrect(subject, review_index)} (streak={reading_streak(subject, review_index)})"
    )


def subject_type_label(subject: dict) -> str:
    kind = subject.get("object") or ""
    if kind == "kanji":
        return "Kanji"
    if kind == "vocabulary":
        return "Vocabulary"
    return kind.replace("_", " ").title()


def reading_mnemonic(subject: dict) -> str:
    return strip_html(subject["data"].get("reading_mnemonic"))


def readings_by_type(subject: dict) -> Dict[str, List[str]]:
    grouped: DefaultDict[str, List[str]] = defaultdict(list)
    for reading in subject["data"].get("readings") or []:
        reading_type = reading.get("type") or "reading"
        if reading.get("primary") or reading.get("accepted_answer"):
            grouped[reading_type].append(reading["reading"])
    if not grouped:
        for reading in subject["data"].get("readings") or []:
            grouped[reading.get("type") or "reading"].append(reading["reading"])
    return dict(grouped)


def readings_detail_html(subject: dict) -> str:
    if subject.get("object") != "kanji":
        return ""
    grouped = readings_by_type(subject)
    if not grouped:
        return ""
    labels = {
        "onyomi": "On'yomi",
        "kunyomi": "Kun'yomi",
        "nanori": "Nanori",
    }
    parts = []
    for reading_type, values in grouped.items():
        label = labels.get(reading_type, reading_type.title())
        parts.append(f"{label}: {html.escape('、'.join(values))}")
    return "<br>".join(parts)


def meta_html(subject: dict, assignment_index: Dict[int, dict]) -> str:
    data = subject["data"]
    return html.escape(
        f"WK Level {data.get('level', '?')} · SRS {srs_stage(subject, assignment_index)} · template {ITEM_MODEL_TEMPLATE_VERSION}"
    )


def context_sentences_html(subject: dict) -> str:
    if subject.get("object") != "vocabulary":
        return ""
    sentences = subject["data"].get("context_sentences") or []
    if not sentences:
        return ""
    parts = []
    for sentence in sentences[:CONTEXT_SENTENCE_LIMIT]:
        ja = html.escape(strip_html(sentence.get("ja")))
        en = html.escape(strip_html(sentence.get("en")))
        if ja:
            parts.append(f'<div class="context"><div class="jp">{ja}</div><div class="meaning">{en}</div></div>')
    return "".join(parts)


def meaning_synonyms(subject: dict, study_index: Dict[int, dict]) -> List[str]:
    sm = study_index.get(subject["id"])
    return sm["data"].get("meaning_synonyms") or [] if sm else []


def is_probably_verb(vocab: dict) -> bool:
    chars = vocab["data"].get("characters") or ""
    meanings = " / ".join(primary_meanings(vocab)).lower()
    return chars.endswith("る") or any(p in meanings for p in ["to ", "to be ", "to become ", "to make ", "to raise ", "to lower ", "to open ", "to close ", "to see ", "to hear "])


def candidate_pair_from_reading(reading: str) -> Optional[Tuple[str, str]]:
    if reading in CURATED_READING_PAIRS:
        return reading, CURATED_READING_PAIRS[reading]
    for intr_end, trans_end in PAIR_RULES:
        if reading.endswith(intr_end):
            return reading, reading[: -len(intr_end)] + trans_end
        if reading.endswith(trans_end):
            return reading[: -len(trans_end)] + intr_end, reading
    return None


def load_pitch_csv(path: Optional[str]) -> Dict[Tuple[str, str], dict]:
    if not path:
        return {}
    pitch: Dict[Tuple[str, str], dict] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"expression", "reading"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Pitch CSV missing required columns: {sorted(missing)}")
        for row in reader:
            expression = (row.get("expression") or "").strip()
            reading = (row.get("reading") or "").strip()
            if expression and reading:
                pitch[(expression, reading)] = {"pitch": (row.get("pitch") or "").strip(), "pattern": (row.get("pattern") or "").strip(), "source": "csv"}
    return pitch


def iter_yomitan_meta_files(path: str) -> Iterable[Tuple[str, Any]]:
    p = Path(path).expanduser()
    if p.is_dir():
        for f in sorted(p.glob("term_meta_bank_*.json")):
            yield f.name, json.loads(f.read_text(encoding="utf-8"))
    elif p.is_file() and p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as zf:
            for name in sorted(zf.namelist()):
                if Path(name).name.startswith("term_meta_bank_") and name.endswith(".json"):
                    with zf.open(name) as f:
                        yield name, json.loads(f.read().decode("utf-8"))
    else:
        raise ValueError(f"Not a Yomitan dictionary folder or zip: {path}")


def normalize_yomitan_pitch_payload(payload: Any) -> List[dict]:
    out = []
    if isinstance(payload, dict):
        reading = str(payload.get("reading") or "")
        pitches = payload.get("pitches") or []
        if isinstance(pitches, list):
            for p in pitches:
                if isinstance(p, dict):
                    position = p.get("position")
                    out.append({"reading": reading, "pitch": str(position), "pattern": f"accent={position}", "source": "yomitan"})
    elif isinstance(payload, list):
        for item in payload:
            out.extend(normalize_yomitan_pitch_payload(item))
    return out


def load_yomitan_pitch(path: Optional[str]) -> Dict[Tuple[str, str], dict]:
    if not path:
        return {}
    pitch: Dict[Tuple[str, str], dict] = {}
    rows = 0
    for _, data in iter_yomitan_meta_files(path):
        if not isinstance(data, list):
            continue
        for row in data:
            rows += 1
            if not isinstance(row, list) or len(row) < 3:
                continue
            term, meta_type, payload = str(row[0]), row[1], row[2]
            if meta_type != "pitch":
                continue
            for entry in normalize_yomitan_pitch_payload(payload):
                reading = entry.get("reading") or ""
                if term and reading:
                    pitch[(term, reading)] = entry
    print(f"Scanned Yomitan pitch rows: {rows}; usable pitch entries: {len(pitch)}")
    return pitch


def merge_pitch_indexes(*indexes: Dict[Tuple[str, str], dict]) -> Dict[Tuple[str, str], dict]:
    merged: Dict[Tuple[str, str], dict] = {}
    for idx in indexes:
        merged.update(idx)
    return merged


def pitch_for(subject: dict, pitch_index: Dict[Tuple[str, str], dict]) -> dict:
    expr = subject["data"].get("characters") or ""
    for reading in primary_readings(subject):
        found = pitch_index.get((expr, reading))
        if found:
            return found
    return {"pitch": "", "pattern": "", "source": ""}


def stable_guid(kind: str, *parts: object) -> str:
    raw = "wk-decks-v2:" + kind + ":" + ":".join(str(x) for x in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def item_html(subject: dict, assignment_index: Dict[int, dict], review_index: Dict[int, dict], study_index: Dict[int, dict], pitch_index: Dict[Tuple[str, str], dict]) -> str:
    data = subject["data"]
    chars = html.escape(data.get("characters") or "")
    readings = html.escape("、".join(primary_readings(subject)))
    meanings = html.escape("; ".join(primary_meanings(subject)))
    pitch = pitch_for(subject, pitch_index)
    pitch_value = html.escape(str(pitch.get("pitch") or ""))
    pitch_pattern = html.escape(str(pitch.get("pattern") or ""))
    source = html.escape(str(pitch.get("source") or ""))
    syns = html.escape("; ".join(meaning_synonyms(subject, study_index)))
    leech = html.escape(leech_label(subject, review_index))
    pitch_block = f'<div class="pitch"><b>Pitch:</b> {pitch_value} <span>{pitch_pattern}</span> <small>{source}</small></div>' if pitch_value or pitch_pattern else ""
    syn_block = f'<div class="synonyms"><b>Your synonyms:</b> {syns}</div>' if syns else ""
    leech_block = f'<div class="leech">{leech}</div>' if leech else ""
    return f"""
    <div class="item">
      <div class="jp">{chars}</div>
      <div class="reading">{readings}</div>
      <div class="meaning">{meanings}</div>
      {pitch_block}{syn_block}
      <div class="meta">WK Level {data.get('level', '?')} · SRS {srs_stage(subject, assignment_index)}</div>
      {leech_block}
    </div>
    """



def make_radical_model() -> genanki.Model:
    return genanki.Model(
        MODEL_IDS["radical"],
        NOTE_TYPE_NAMES["radical"],
        fields=[
            {"name": "GuidKey"},
            {"name": "Radical"},
            {"name": "Meaning"},
            {"name": "Level"},
            {"name": "Status"},
            {"name": "KanjiPreview"},
            {"name": "Notes"},
        ],
        templates=[
            {
                "name": "Radical Meaning",
                "qfmt": """
                <div class='prompt'>Radical meaning?</div>
                <div class='jp'>{{Radical}}</div>
                <div class='meta'>{{Status}} · WK Level {{Level}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class='meaning'>{{Meaning}}</div>
                <h3>Used in / upcoming kanji</h3>
                <div class='family-members'>{{KanjiPreview}}</div>
                <div class='notes'>{{Notes}}</div>
                """,
            }
        ],
        css=COMMON_CSS,
    )



def make_item_model() -> genanki.Model:
    return genanki.Model(
        MODEL_IDS["item"],
        NOTE_TYPE_NAMES["item"],
        fields=[
            {"name": "GuidKey"},
            {"name": "Expression"},
            {"name": "Reading"},
            {"name": "Meaning"},
            {"name": "ItemHtml"},
            {"name": "Mnemonic"},
            {"name": "Confusables"},
            {"name": "Pitch"},
            {"name": "PitchPattern"},
            {"name": "Notes"},
            {"name": "ReadingMnemonic"},
            {"name": "SubjectType"},
            {"name": "ReadingsDetail"},
            {"name": "Meta"},
            {"name": "LeechStats"},
            {"name": "Synonyms"},
            {"name": "ContextSentences"},
            {"name": "MeaningWeak"},
            {"name": "ReadingWeak"},
        ],
        templates=[
            {
                "name": "Meaning",
                "qfmt": """
                <div class="prompt">{{SubjectType}} meaning?</div>
                {{#MeaningWeak}}<div class="weak-side">Meaning side needs work</div>{{/MeaningWeak}}
                <div class="jp">{{Expression}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="meaning answer">{{Meaning}}</div>
                {{#Synonyms}}<div class="synonyms"><b>Your synonyms:</b> {{Synonyms}}</div>{{/Synonyms}}
                {{#Mnemonic}}<h3>Meaning mnemonic</h3><div class="notes">{{Mnemonic}}</div>{{/Mnemonic}}
                {{#Confusables}}<h3>Confusables</h3><div class="notes">{{Confusables}}</div>{{/Confusables}}
                <div class="meta">{{Meta}}</div>
                {{#LeechStats}}<div class="leech">{{LeechStats}}</div>{{/LeechStats}}
                """,
            },
            {
                "name": "Reading",
                "qfmt": """
                <div class="prompt">{{SubjectType}} reading?</div>
                {{#ReadingWeak}}<div class="weak-side">Reading side needs work</div>{{/ReadingWeak}}
                <div class="jp">{{Expression}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="reading answer">{{Reading}}</div>
                {{#ReadingsDetail}}<div class="reading-detail">{{ReadingsDetail}}</div>{{/ReadingsDetail}}
                {{#ReadingMnemonic}}<h3>Reading mnemonic</h3><div class="notes">{{ReadingMnemonic}}</div>{{/ReadingMnemonic}}
                {{#ContextSentences}}<h3>Context</h3>{{ContextSentences}}{{/ContextSentences}}
                {{#Pitch}}<div class="pitch"><b>Pitch:</b> {{Pitch}} <span>{{PitchPattern}}</span></div>{{/Pitch}}
                <div class="meta">{{Meta}}</div>
                {{#LeechStats}}<div class="leech">{{LeechStats}}</div>{{/LeechStats}}
                """,
            },
            {
                "name": "Pitch",
                "qfmt": "{{#Pitch}}<div class='prompt'>Pitch accent?</div><div class='jp'>{{Expression}}</div><div class='reading'>{{Reading}}</div>{{/Pitch}}",
                "afmt": "{{FrontSide}}<hr><div class='pitch-answer'>{{Pitch}} {{PitchPattern}}</div>{{ItemHtml}}",
            },
        ],
        css=COMMON_CSS,
    )



def verb_type(subject: dict) -> str:
    """Best-effort learner-facing Japanese verb class label."""
    expr = subject["data"].get("characters") or ""
    reading = first_reading(subject)

    if expr in {"する", "来る", "くる"} or reading in {"する", "くる"}:
        return "Irregular"

    if reading.endswith("る") and len(reading) >= 2:
        prev = reading[-2]
        if prev in "いきしちにひみりえけせてねへめれげぜでべぺ":
            return "Likely Ichidan"

    if expr:
        return "Likely Godan"
    return ""


PAIR_METADATA = {
    ("上がる", "上げる"): {
        "relationship": "INTRANSITIVE ↔ TRANSITIVE",
        "left_role": "goes up / rises by itself",
        "right_role": "raise / lift something",
        "examples": "温度が上がる — The temperature rises.<br>手を上げる — Raise your hand.",
    },
    ("下がる", "下げる"): {
        "relationship": "INTRANSITIVE ↔ TRANSITIVE",
        "left_role": "goes down / falls by itself",
        "right_role": "lower something",
        "examples": "値段が下がる — The price falls.<br>音量を下げる — Lower the volume.",
    },
    ("始まる", "始める"): {
        "relationship": "INTRANSITIVE ↔ TRANSITIVE",
        "left_role": "begins / starts by itself",
        "right_role": "start something",
        "examples": "授業が始まる — Class begins.<br>勉強を始める — Start studying.",
    },
    ("閉まる", "閉める"): {
        "relationship": "INTRANSITIVE ↔ TRANSITIVE",
        "left_role": "closes / is closed",
        "right_role": "close something",
        "examples": "ドアが閉まる — The door closes.<br>ドアを閉める — Close the door.",
    },
    ("開く", "開ける"): {
        "relationship": "INTRANSITIVE ↔ TRANSITIVE",
        "left_role": "opens / is open",
        "right_role": "open something",
        "examples": "ドアが開く — The door opens.<br>ドアを開ける — Open the door.",
    },
    ("集まる", "集める"): {
        "relationship": "INTRANSITIVE ↔ TRANSITIVE",
        "left_role": "gathers / assembles",
        "right_role": "gather / collect something",
        "examples": "人が集まる — People gather.<br>切手を集める — Collect stamps.",
    },
    ("決まる", "決める"): {
        "relationship": "INTRANSITIVE ↔ TRANSITIVE",
        "left_role": "is decided / gets decided",
        "right_role": "decide something",
        "examples": "予定が決まる — The plan is decided.<br>予定を決める — Decide the plan.",
    },
    ("変わる", "変える"): {
        "relationship": "INTRANSITIVE ↔ TRANSITIVE",
        "left_role": "changes by itself",
        "right_role": "change something",
        "examples": "天気が変わる — The weather changes.<br>予定を変える — Change the plan.",
    },
    ("見る", "見せる"): {
        "relationship": "BASE ↔ CAUSATIVE-LIKE",
        "left_role": "see / look / watch",
        "right_role": "show / make visible to someone",
        "examples": "テレビを見る — Watch TV.<br>写真を見せる — Show a photo.",
    },
    ("見せる", "見る"): {
        "relationship": "CAUSATIVE-LIKE ↔ BASE",
        "left_role": "show / make visible to someone",
        "right_role": "see / look / watch",
        "examples": "写真を見せる — Show a photo.<br>テレビを見る — Watch TV.",
    },
    ("見る", "見える"): {
        "relationship": "BASE ↔ POTENTIAL / PERCEPTION",
        "left_role": "see / look / watch",
        "right_role": "can be seen / is visible",
        "examples": "テレビを見る — Watch TV.<br>山が見える — The mountain is visible.",
    },
    ("聞く", "聞こえる"): {
        "relationship": "BASE ↔ POTENTIAL / PERCEPTION",
        "left_role": "listen / ask",
        "right_role": "can be heard / is audible",
        "examples": "音楽を聞く — Listen to music.<br>音が聞こえる — A sound can be heard.",
    },
    ("聞く", "聞かせる"): {
        "relationship": "BASE ↔ CAUSATIVE",
        "left_role": "listen / ask",
        "right_role": "let/make someone hear",
        "examples": "音楽を聞く — Listen to music.<br>子供に話を聞かせる — Tell a child a story.",
    },
    ("出る", "出す"): {
        "relationship": "MOVE ↔ CAUSE TO MOVE",
        "left_role": "go out / come out",
        "right_role": "take out / put out",
        "examples": "部屋を出る — Leave the room.<br>本を出す — Take out a book.",
    },
    ("入る", "入れる"): {
        "relationship": "MOVE ↔ CAUSE TO MOVE",
        "left_role": "enter / go in",
        "right_role": "put in / insert",
        "examples": "部屋に入る — Enter the room.<br>かばんに本を入れる — Put a book in the bag.",
    },
    ("付く", "付ける"): {
        "relationship": "INTRANSITIVE ↔ TRANSITIVE",
        "left_role": "attaches / turns on",
        "right_role": "attach / turn on",
        "examples": "電気が付く — The light turns on.<br>電気を付ける — Turn on the light.",
    },
}


def infer_pair_metadata(left: dict, right: dict) -> dict:
    left_expr = left["data"].get("characters") or ""
    right_expr = right["data"].get("characters") or ""

    direct = PAIR_METADATA.get((left_expr, right_expr))
    if direct:
        return direct

    left_reading = first_reading(left)
    right_reading = first_reading(right)

    relationship = "RELATED VERB CONTRAST"
    left_role = "first form"
    right_role = "contrasting form"

    if left_reading.endswith("がる") and right_reading.endswith("げる"):
        relationship = "INTRANSITIVE ↔ TRANSITIVE"
        left_role = "happens by itself"
        right_role = "someone causes it"
    elif left_reading.endswith("まる") and right_reading.endswith("める"):
        relationship = "INTRANSITIVE ↔ TRANSITIVE"
        left_role = "happens by itself"
        right_role = "someone causes it"
    elif left_reading.endswith("れる") and right_reading.endswith("す"):
        relationship = "INTRANSITIVE ↔ TRANSITIVE"
        left_role = "happens by itself"
        right_role = "someone causes it"
    elif right_reading.endswith("せる") or right_reading.endswith("かせる"):
        relationship = "BASE ↔ CAUSATIVE / CAUSATIVE-LIKE"
        left_role = "base verb"
        right_role = "cause/let/show version"
    elif right_reading.endswith("える") and left_reading != right_reading:
        relationship = "BASE ↔ POTENTIAL / RELATED FORM"
        left_role = "base or source verb"
        right_role = "potential/perception or related form"

    return {
        "relationship": relationship,
        "left_role": left_role,
        "right_role": right_role,
        "examples": "",
    }


def compact_pair_front(subject: dict) -> str:
    expr = html.escape(subject["data"].get("characters") or "")
    reading = html.escape(first_reading(subject))
    return f"""
    <div class="pair-front-item">
      <div class="jp">{expr}</div>
      <div class="reading">{reading}</div>
    </div>
    """


def detailed_pair_back(subject: dict, assignment_index: Dict[int, dict], review_index: Dict[int, dict], study_index: Dict[int, dict], pitch_index: Dict[Tuple[str, str], dict], role: str = "") -> str:
    vt = verb_type(subject)
    role_html = f"<div><b>Role:</b> {html.escape(role)}</div>" if role else ""
    vt_html = f"<div><b>Verb type:</b> {html.escape(vt)}</div>" if vt else ""
    return f"""
    {item_html(subject, assignment_index, review_index, study_index, pitch_index)}
    <div class="notes">
      {role_html}
      {vt_html}
    </div>
    """

def make_pair_model() -> genanki.Model:
    return genanki.Model(
        MODEL_IDS["pair"],
        NOTE_TYPE_NAMES["pair"],
        fields=[
            {"name": "GuidKey"},
            {"name": "LeftFrontHtml"},
            {"name": "RightFrontHtml"},
            {"name": "LeftBackHtml"},
            {"name": "RightBackHtml"},
            {"name": "LeftExpression"},
            {"name": "RightExpression"},
            {"name": "LeftReading"},
            {"name": "RightReading"},
            {"name": "LeftPitch"},
            {"name": "RightPitch"},
            {"name": "RelationshipType"},
            {"name": "Examples"},
            {"name": "Explanation"},
        ],
        templates=[
            {
                "name": "Recognize Contrast",
                "qfmt": """
                <div class='prompt'>Explain the contrast.</div>
                <div class='relationship-question'>Relationship type?</div>
                {{LeftFrontHtml}}
                <div class='pair-arrow'>↔</div>
                {{RightFrontHtml}}
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class='relationship'><b>Relationship:</b> {{RelationshipType}}</div>
                <div class='pair-back-grid'>
                  <div>{{LeftBackHtml}}</div>
                  <div>{{RightBackHtml}}</div>
                </div>
                <h3>Examples</h3>
                <div class='notes'>{{Examples}}</div>
                <h3>Notes</h3>
                <div class='notes'>{{Explanation}}</div>
                """,
            },
            {
                "name": "Produce Right",
                "qfmt": """
                <div class='prompt'>What is the contrasting form?</div>
                <div class='relationship-question'>{{RelationshipType}}</div>
                {{LeftFrontHtml}}
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                {{RightBackHtml}}
                <div class='notes'>{{Explanation}}</div>
                """,
            },
            {
                "name": "Pitch Contrast",
                "qfmt": "{{#LeftPitch}}<div class='prompt'>Compare pitch accent.</div><div class='pair-line'>{{LeftExpression}} / {{RightExpression}}</div>{{/LeftPitch}}",
                "afmt": "{{FrontSide}}<hr><b>{{LeftExpression}}</b>: {{LeftPitch}}<br><b>{{RightExpression}}</b>: {{RightPitch}}",
            },
        ],
        css=COMMON_CSS,
    )


def make_family_model() -> genanki.Model:
    return genanki.Model(
        MODEL_IDS["family"],
        NOTE_TYPE_NAMES["family"],
        fields=[
            {"name": "GuidKey"},
            {"name": "FamilyTitle"},
            {"name": "Prompt"},
            {"name": "MembersFrontHtml"},
            {"name": "MembersHtml"},
            {"name": "Explanation"},
        ],
        templates=[
            {
                "name": "Family Recognition",
                "qfmt": "<div class='prompt'>{{Prompt}}</div><div class='family-title'>{{FamilyTitle}}</div>{{MembersFrontHtml}}",
                "afmt": "{{FrontSide}}<hr>{{MembersHtml}}<div class='notes'>{{Explanation}}</div>",
            }
        ],
        css=COMMON_CSS,
    )



def radical_subjects(subjects: Sequence[dict], args: argparse.Namespace) -> List[dict]:
    max_level = min(args.max_level, 60)
    return [
        s for s in subjects
        if s.get("object") == "radical"
        and int(s["data"].get("level", 999)) <= max_level
    ]


def index_subjects_by_id(subjects: Iterable[dict]) -> Dict[int, dict]:
    return {s["id"]: s for s in subjects}


def current_wk_level(user: dict, subjects: Sequence[dict], assignment_index: Dict[int, dict]) -> int:
    level = int(user.get("level") or 0)
    if level > 0:
        return level
    levels = []
    for subject in subjects:
        assignment = assignment_index.get(subject["id"])
        if assignment and assignment["data"].get("unlocked_at"):
            levels.append(int(subject["data"].get("level") or 0))
    return max(levels) if levels else 1


def selected_radical_levels(user: dict, subjects: Sequence[dict], assignment_index: Dict[int, dict], args: argparse.Namespace) -> Tuple[int, int]:
    if args.radical_current_level:
        current = args.radical_current_level
    else:
        current = current_wk_level(user, subjects, assignment_index)
    next_level = min(current + 1, 60)
    return current, next_level


def kanji_using_radical(kanji_items: Sequence[dict], radical: dict, max_level: int = 60, limit: int = 12) -> List[dict]:
    radical_id = radical["id"]
    matches = []
    for kanji in kanji_items:
        component_ids = kanji["data"].get("component_subject_ids") or []
        if radical_id in component_ids and int(kanji["data"].get("level") or 999) <= max_level:
            matches.append(kanji)
    return sorted(matches, key=lambda k: (k["data"].get("level", 999), k["data"].get("characters") or ""))[:limit]


def radical_is_learned(radical: dict, assignment_index: Dict[int, dict]) -> bool:
    assignment = assignment_index.get(radical["id"])
    return bool(assignment and assignment["data"].get("started_at"))


def radical_priority(radical: dict, current_level: int, next_level: int) -> str:
    level = int(radical["data"].get("level") or 999)
    if level == current_level or level == next_level:
        return "priority-high"
    return "priority-medium"


def radical_display(radical: dict) -> str:
    chars = radical["data"].get("characters")
    if chars:
        return chars
    # Some WK radicals are images rather than Unicode characters.
    return radical["data"].get("slug") or "radical"


def vocab_subjects(subjects: Sequence[dict], assignment_index: Dict[int, dict], args: argparse.Namespace) -> List[dict]:
    return [s for s in subjects if s.get("object") == "vocabulary" and passes_progress_filter(s, assignment_index, args)]


def kanji_subjects(subjects: Sequence[dict], assignment_index: Dict[int, dict], args: argparse.Namespace) -> List[dict]:
    return [s for s in subjects if s.get("object") == "kanji" and passes_progress_filter(s, assignment_index, args)]


def find_leeches(subjects: Sequence[dict], assignment_index: Dict[int, dict], review_index: Dict[int, dict], args: argparse.Namespace) -> List[dict]:
    candidates = [s for s in subjects if s.get("object") in {"vocabulary", "kanji"} and passes_progress_filter(s, assignment_index, args) and is_leech(s, review_index, args)]
    return sorted(
        candidates,
        key=lambda s: (
            -leech_score(s, review_index),
            -incorrect_total(s, review_index),
            s["data"].get("level", 999),
            s["data"].get("characters") or "",
        ),
    )[: args.max_cards]


def best_item(items: List[dict]) -> dict:
    return sorted(items, key=lambda x: (len(x["data"].get("characters") or ""), x["data"].get("level", 999)))[0]


def find_verb_pairs(vocab_items: Sequence[dict], args: argparse.Namespace) -> List[Tuple[dict, dict]]:
    by_reading: DefaultDict[str, List[dict]] = defaultdict(list)
    for item in vocab_items:
        if is_probably_verb(item):
            for reading in primary_readings(item):
                by_reading[reading].append(item)
    pairs: List[Tuple[dict, dict]] = []
    seen: Set[Tuple[str, str]] = set()
    for reading in list(by_reading):
        candidate = candidate_pair_from_reading(reading)
        if not candidate:
            continue
        left, right = candidate
        if left in by_reading and right in by_reading and (left, right) not in seen:
            seen.add((left, right))
            pairs.append((best_item(by_reading[left]), best_item(by_reading[right])))
    return sorted(pairs, key=lambda p: (max(p[0]["data"].get("level", 999), p[1]["data"].get("level", 999)), p[0]["data"].get("characters") or ""))[: args.max_cards]


def shared_kanji_key(expr: str) -> str:
    return "".join(ch for ch in expr if "\u4e00" <= ch <= "\u9fff")


def component_group_key(item: dict) -> Optional[Tuple[int, ...]]:
    components = item["data"].get("component_subject_ids") or []
    if not components:
        return None
    return tuple(sorted(components))


def confusable_group_title(group: List[dict], subject_index: Dict[int, dict]) -> str:
    components = group[0]["data"].get("component_subject_ids") or []
    if components:
        kanji_chars = "".join(
            subject_index[component_id]["data"].get("characters") or "?"
            for component_id in sorted(components)
            if component_id in subject_index
        )
        if kanji_chars:
            return kanji_chars
    return shared_kanji_key(group[0]["data"].get("characters") or "")


def finalize_confusable_group(items: List[dict], args: argparse.Namespace) -> Optional[List[dict]]:
    unique = sorted(items, key=lambda x: (x["data"].get("level", 999), x["data"].get("characters") or ""))
    if len(unique) < 2 or len(unique) > args.max_confusable_group_size:
        return None
    readings = {first_reading(x) for x in unique}
    if len(readings) >= 2 or len(unique) >= 3:
        return unique
    return None


def find_confusable_groups(
    vocab_items: Sequence[dict],
    args: argparse.Namespace,
) -> List[List[dict]]:
    by_components: DefaultDict[Tuple[int, ...], List[dict]] = defaultdict(list)
    by_kanji: DefaultDict[str, List[dict]] = defaultdict(list)

    for item in vocab_items:
        component_key = component_group_key(item)
        if component_key:
            by_components[component_key].append(item)
        kanji_key = shared_kanji_key(item["data"].get("characters") or "")
        if kanji_key:
            by_kanji[kanji_key].append(item)

    seen_group_ids: Set[Tuple[int, ...]] = set()
    out: List[List[dict]] = []
    for grouped_items in list(by_components.values()) + list(by_kanji.values()):
        group = finalize_confusable_group(grouped_items, args)
        if not group:
            continue
        group_ids = tuple(item["id"] for item in group)
        if group_ids in seen_group_ids:
            continue
        seen_group_ids.add(group_ids)
        out.append(group)

    return sorted(
        out,
        key=lambda g: (min(x["data"].get("level", 999) for x in g), g[0]["data"].get("characters") or ""),
    )[: args.max_cards]


def onyomi_readings(kanji: dict) -> List[str]:
    readings = kanji["data"].get("readings", [])
    vals = [r["reading"] for r in readings if r.get("type") == "onyomi" and (r.get("primary") or r.get("accepted_answer"))]
    return vals or [r["reading"] for r in readings if r.get("type") == "onyomi"]


def find_phonetic_families(kanji_items: Sequence[dict], args: argparse.Namespace) -> List[Tuple[str, str, List[dict]]]:
    component_groups: DefaultDict[Tuple[str, str], List[dict]] = defaultdict(list)
    for k in kanji_items:
        char = k["data"].get("characters") or ""
        for comp in PHONETIC_COMPONENTS:
            if comp != char and comp in char:
                for reading in onyomi_readings(k):
                    component_groups[(comp, reading)].append(k)
    families = []
    for (comp, reading), members in component_groups.items():
        unique = sorted({m["id"]: m for m in members}.values(), key=lambda x: x["data"].get("level", 999))
        if len(unique) >= args.min_family_size:
            families.append((comp, reading, unique[: args.max_family_members]))
    return sorted(families, key=lambda f: (f[1], f[0]))[: args.max_cards]


def write_pitch_template(vocab_items: Sequence[dict], path: str) -> None:
    seen = set()
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["expression", "reading", "pitch", "pattern"])
        writer.writeheader()
        for item in vocab_items:
            expr = item["data"].get("characters") or ""
            for reading in primary_readings(item):
                key = (expr, reading)
                if key not in seen:
                    seen.add(key)
                    writer.writerow({"expression": expr, "reading": reading, "pitch": "", "pattern": ""})
    print(f"Wrote pitch CSV template: {path}")



def priority_for_item(subject: dict, review_index: Dict[int, dict], kind: str) -> str:
    """Return priority-high/medium/low tag for single-item cards."""
    score = leech_score(subject, review_index)
    streak = current_streak_min(subject, review_index)

    if kind in {"leech", "pitch-leech"}:
        if score >= 12 or streak <= 1:
            return "priority-high"
        if score >= 6:
            return "priority-medium"
        return "priority-low"

    return "priority-medium"


def priority_for_pair(left: dict, right: dict, relationship: str, review_index: Dict[int, dict]) -> str:
    """Return priority-high/medium/low tag for contrast cards."""
    total = incorrect_total(left, review_index) + incorrect_total(right, review_index)
    rel = relationship.lower()

    if any(x in rel for x in ["intransitive", "causative", "potential", "move"]):
        if total >= 3:
            return "priority-high"
        return "priority-medium"

    if total >= 6:
        return "priority-high"
    if total >= 2:
        return "priority-medium"
    return "priority-low"


def priority_for_confusable_group(group: List[dict], review_index: Dict[int, dict]) -> str:
    total = sum(incorrect_total(i, review_index) for i in group)
    if total >= 8:
        return "priority-high"
    if total >= 3:
        return "priority-medium"
    return "priority-low"



def add_item_note(deck, model, subject, indexes, pitch_index, kind: str, confusables_html: str = "") -> None:
    data = subject["data"]
    expr = data.get("characters") or ""
    reading = "、".join(primary_readings(subject)) or first_reading(subject)
    pitch = pitch_for(subject, pitch_index)
    guid = stable_guid(kind, subject["id"])
    syns = meaning_synonyms(subject, indexes["studies"])
    weakness_tags = leech_weakness_tags(subject, indexes["reviews"])
    note = genanki.Note(
        model=model,
        fields=[
            guid,
            html.escape(expr),
            html.escape(reading),
            html.escape("; ".join(primary_meanings(subject))),
            item_html(subject, indexes["assignments"], indexes["reviews"], indexes["studies"], pitch_index),
            html.escape(strip_html(data.get("meaning_mnemonic"))),
            confusables_html,
            html.escape(str(pitch.get("pitch") or "")),
            html.escape(str(pitch.get("pattern") or "")),
            "",
            html.escape(reading_mnemonic(subject)),
            html.escape(subject_type_label(subject)),
            readings_detail_html(subject),
            meta_html(subject, indexes["assignments"]),
            html.escape(leech_label(subject, indexes["reviews"])),
            html.escape("; ".join(syns)),
            context_sentences_html(subject),
            "1" if "leech-meaning" in weakness_tags else "",
            "1" if "leech-reading" in weakness_tags else "",
        ],
        tags=[
            "wanikani",
            kind,
            priority_for_item(subject, indexes["reviews"], kind),
            f"wk-level-{data.get('level', 0)}",
            *weakness_tags,
        ],
        guid=guid,
    )
    deck.add_note(note)



def build_radical_deck(
    radicals: List[dict],
    kanji_items: List[dict],
    indexes: dict,
    args: argparse.Namespace,
    output_dir: Path,
    current_level: int,
    next_level: int,
) -> Tuple[Path, genanki.Deck]:
    selected = [
        r for r in radicals
        if int(r["data"].get("level") or 999) in {current_level, next_level}
    ]

    deck = genanki.Deck(DECK_IDS["radicals"], DECK_NAMES["radicals"])
    model = make_radical_model()

    for radical in sorted(selected, key=lambda r: (r["data"].get("level", 999), radical_display(r))):
        data = radical["data"]
        level = int(data.get("level") or 0)
        status = "current-level" if level == current_level else "next-level"
        if radical_is_learned(radical, indexes["assignments"]):
            status += " · started"

        meanings = html.escape("; ".join(primary_meanings(radical)))
        radical_text = html.escape(radical_display(radical))
        preview_kanji = kanji_using_radical(kanji_items, radical, max_level=min(level + 3, 60), limit=12)
        if preview_kanji:
            kanji_html = "".join(
                f"<div class='member'><span class='jp'>{html.escape(k['data'].get('characters') or '')}</span> "
                f"<span class='reading'>{html.escape('、'.join(primary_readings(k)))}</span> "
                f"<span class='meaning'>{html.escape('; '.join(primary_meanings(k)))}</span> "
                f"<span class='meta'>WK Level {k['data'].get('level', '?')}</span></div>"
                for k in preview_kanji
            )
        else:
            kanji_html = "<div class='meta'>No kanji preview found in current cached WaniKani subjects.</div>"

        note = genanki.Note(
            model=model,
            fields=[
                stable_guid("radical", radical["id"], current_level, next_level),
                radical_text,
                meanings,
                str(level),
                html.escape(status),
                kanji_html,
                "Preview deck for current and next WaniKani level radicals.",
            ],
            tags=[
                "wanikani",
                "radical",
                status.split()[0],
                radical_priority(radical, current_level, next_level),
                f"wk-level-{level}",
            ],
            guid=stable_guid("radical", radical["id"], current_level, next_level),
        )
        deck.add_note(note)

    out = output_dir / "wk_radicals_current_next.apkg"
    write_apkg(deck, out)
    return out, deck



def build_leech_deck(items, indexes, pitch_index, output_dir: Path) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["leeches"], DECK_NAMES["leeches"])
    model = make_item_model()
    for item in items:
        add_item_note(deck, model, item, indexes, pitch_index, "leech")
    out = output_dir / "wk_leeches.apkg"
    write_apkg(deck, out)
    return out, deck


def build_pitch_leeches_deck(items, indexes, pitch_index, output_dir: Path) -> Optional[Tuple[Path, genanki.Deck]]:
    pitch_items = [i for i in items if pitch_for(i, pitch_index).get("pitch") or pitch_for(i, pitch_index).get("pattern")]
    if not pitch_items:
        return None
    deck = genanki.Deck(DECK_IDS["pitch-leeches"], DECK_NAMES["pitch-leeches"])
    model = make_item_model()
    for item in pitch_items:
        add_item_note(deck, model, item, indexes, pitch_index, "pitch-leech")
    out = output_dir / "wk_pitch_leeches.apkg"
    write_apkg(deck, out)
    return out, deck


def build_pair_deck(pairs: List[Tuple[dict, dict]], indexes: dict, pitch_index: Dict[Tuple[str, str], dict], output_dir: Path) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["verb-pairs"], DECK_NAMES["verb-pairs"])
    model = make_pair_model()
    for left, right in pairs:
        metadata = infer_pair_metadata(left, right)
        lp = pitch_for(left, pitch_index)
        rp = pitch_for(right, pitch_index)
        guid = stable_guid("verb-pair", left["id"], right["id"])

        relationship = metadata.get("relationship", "RELATED VERB CONTRAST")
        left_role = metadata.get("left_role", "")
        right_role = metadata.get("right_role", "")
        examples = metadata.get("examples", "")

        explanation = (
            f"<b>{html.escape(relationship)}</b><br>"
            f"{html.escape(left['data'].get('characters') or '')}: {html.escape(left_role)}<br>"
            f"{html.escape(right['data'].get('characters') or '')}: {html.escape(right_role)}<br><br>"
            "Use the pair as a contrast. The front intentionally hides meanings so you practice the relationship, not recognition by English gloss."
        )

        note = genanki.Note(
            model=model,
            fields=[
                guid,
                compact_pair_front(left),
                compact_pair_front(right),
                detailed_pair_back(left, indexes["assignments"], indexes["reviews"], indexes["studies"], pitch_index, left_role),
                detailed_pair_back(right, indexes["assignments"], indexes["reviews"], indexes["studies"], pitch_index, right_role),
                html.escape(left["data"].get("characters") or ""),
                html.escape(right["data"].get("characters") or ""),
                html.escape(first_reading(left)),
                html.escape(first_reading(right)),
                html.escape(str(lp.get("pitch") or lp.get("pattern") or "")),
                html.escape(str(rp.get("pitch") or rp.get("pattern") or "")),
                html.escape(relationship),
                examples,
                explanation,
            ],
            tags=[
                "wanikani",
                "verb-pair",
                "contrast",
                priority_for_pair(left, right, relationship, indexes["reviews"]),
                re.sub(r"[^A-Za-z0-9_-]+", "-", relationship.lower()),
            ],
            guid=guid,
        )
        deck.add_note(note)
    out = output_dir / "wk_verb_pairs.apkg"
    write_apkg(deck, out)
    return out, deck


def build_confusables_deck(groups, indexes, pitch_index, output_dir: Path, subject_index: Dict[int, dict]) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["confusables"], DECK_NAMES["confusables"])
    model = make_family_model()
    for group in groups:
        key = confusable_group_title(group, subject_index)
        members_front = "\n".join(
            f"<span class='front-member'>{html.escape(i['data'].get('characters') or '')}"
            f"<span class='front-reading'>{html.escape(first_reading(i))}</span></span>"
            for i in group
        )
        members = "\n".join(
            f"<div class='member'>{item_html(i, indexes['assignments'], indexes['reviews'], indexes['studies'], pitch_index)}</div>"
            for i in group
        )
        guid = stable_guid("confusable", *[i["id"] for i in group])
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                html.escape(key),
                "Compare these WaniKani vocabulary items. What makes each one different?",
                f"<div class='front-members'>{members_front}</div>",
                f"<div class='family-members'>{members}</div>",
                "These items share WaniKani kanji components or the same kanji string, so drill the contrast rather than memorizing each in isolation.",
            ],
            tags=[
                "wanikani",
                "confusable",
                priority_for_confusable_group(group, indexes["reviews"]),
            ],
            guid=guid,
        )
        deck.add_note(note)
    out = output_dir / "wk_confusables.apkg"
    write_apkg(deck, out)
    return out, deck


def build_phonetic_family_deck(families, output_dir: Path) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["phonetic-families"], DECK_NAMES["phonetic-families"])
    model = make_family_model()
    for comp, reading, members in families:
        members_front = "".join(
            f"<span class='front-member'>{html.escape(m['data'].get('characters') or '')}"
            f"<span class='front-reading'>{html.escape('、'.join(primary_readings(m)))}</span></span>"
            for m in members
        )
        rows = []
        for k in members:
            d = k["data"]
            rows.append(f"<div class='member'><span class='jp'>{html.escape(d.get('characters') or '')}</span> <span class='reading'>{html.escape('、'.join(primary_readings(k)))}</span> <span class='meaning'>{html.escape('; '.join(primary_meanings(k)))}</span> <span class='meta'>WK Level {d.get('level', '?')}</span></div>")
        guid = stable_guid("phonetic-family", comp, reading, *[m["id"] for m in members])
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                f"{html.escape(comp)} → {html.escape(reading)}",
                "Which kanji share this component/reading pattern?",
                f"<div class='front-members'>{members_front}</div>",
                f"<div class='family-members'>{''.join(rows)}</div>",
                "This is a practical WaniKani reading-pattern card. Treat it as a useful heuristic, not a formal etymology claim.",
            ],
            tags=["wanikani", "phonetic-family", "priority-low", f"reading-{reading}"],
            guid=guid,
        )
        deck.add_note(note)
    out = output_dir / "wk_phonetic_families.apkg"
    write_apkg(deck, out)
    return out, deck



def write_filtered_deck_suggestions(output_dir: Path) -> Path:
    path = output_dir / "anki_filtered_decks.txt"
    lines = ["Suggested Anki filtered decks", ""]
    for index, deck in enumerate(FILTERED_DECK_DEFINITIONS, start=1):
        lines.extend(
            [
                f"{index}. {deck['name']}",
                "Search:",
                deck["search"],
                f"Limit: {deck['limit']}",
                "Order: Relative overdueness",
                "",
            ]
        )
    lines.extend(
        [
            "Automated setup:",
            f"  Install the add-on in anki_addon/wk_filtered_decks, then use",
            f"  Tools → WK Setup Filtered Decks after importing {BUNDLE_FILENAME}.",
            f"  It reads {FILTERED_DECKS_JSON} from your generator output folder.",
            "",
            "Notes:",
            "- Reviews in filtered decks update the original cards.",
            "- After regenerating/importing decks, run WK Setup Filtered Decks again (Rebuild).",
            "- Filtered decks cannot be included inside .apkg files; they live in your Anki profile.",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_filtered_decks_json(output_dir: Path) -> Path:
    path = output_dir / FILTERED_DECKS_JSON
    payload = {
        "generator_version": VERSION,
        "order_labels": {"relative_overdueness": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS},
        "decks": FILTERED_DECK_DEFINITIONS,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path



def write_import_instructions(output_dir: Path) -> Path:
    note_types = ", ".join(NOTE_TYPE_NAMES.values())
    path = output_dir / "anki_import_instructions.txt"
    path.write_text(
        f"""WaniKani → Anki import instructions (generator {VERSION})

RECOMMENDED: import the bundled file
  {BUNDLE_FILENAME}

This updates every deck in one step with one Anki dialog.

When Anki asks about existing note types:
  - Choose UPDATE / replace existing note type
  - Do NOT choose "Create new note type" or "Keep old note type"

Expected note type names (stable — no version suffix):
  {note_types}

After import, verify any leech card back includes:
  template {ITEM_MODEL_TEMPLATE_VERSION}

Meaning / Reading card fronts should show only the Japanese expression.
Pitch cards may also show the reading on front when pitch data exists.

Individual deck files (wk_leeches.apkg, etc.) are still written for one-off
imports, but weekly updates are cleaner with {BUNDLE_FILENAME} alone.

Filtered decks (WK::Daily Priority, etc.) cannot be bundled in .apkg files.
After importing, run Tools → WK Setup Filtered Decks in Anki using the add-on
in anki_addon/wk_filtered_decks (reads {FILTERED_DECKS_JSON}).

If you ever end up with duplicate note types again:
  1. Browse → filter by deck → note the old vs new note type counts
  2. Prefer re-importing {BUNDLE_FILENAME} with "Update existing note type"
  3. Or delete the deck notes once and re-import (loses scheduling)
""",
        encoding="utf-8",
    )
    return path


def print_import_verification_help(bundle_path: Optional[Path] = None) -> None:
    print()
    print("Anki import checklist:")
    if bundle_path:
        print(f"  Recommended: import {bundle_path.name} (all decks in one file)")
    print("  When Anki asks about an existing note type, choose UPDATE — not create new.")
    print(f"  Leech note type name: {NOTE_TYPE_NAMES['item']}")
    print(f"  Verify card backs include: template {ITEM_MODEL_TEMPLATE_VERSION}")
    print(f"  Full instructions: out/anki_import_instructions.txt")
    print(f"  Filtered decks: install anki_addon/wk_filtered_decks, then Tools → WK Setup Filtered Decks")


def subject_summary(subject: dict, review_index: Dict[int, dict]) -> str:
    data = subject["data"]
    expr = data.get("characters") or data.get("slug") or "?"
    kind = subject.get("object") or "item"
    level = data.get("level", "?")
    score = leech_score(subject, review_index)
    weakness = ",".join(leech_weakness_tags(subject, review_index)) or "-"
    return (
        f"{expr} [{kind} L{level}] score={score:.1f} "
        f"m={meaning_incorrect(subject, review_index)}/{meaning_streak(subject, review_index)} "
        f"r={reading_incorrect(subject, review_index)}/{reading_streak(subject, review_index)} "
        f"weak={weakness}"
    )


def preview_deck_section(title: str, lines: Sequence[str], limit: int = 25) -> None:
    print(f"\n{title} ({len(lines)} items)")
    print("-" * len(title))
    if not lines:
        print("  (none)")
        return
    for line in lines[:limit]:
        print(f"  {line}")
    if len(lines) > limit:
        print(f"  ... and {len(lines) - limit} more")


def print_preview_report(
    args: argparse.Namespace,
    *,
    leeches: Sequence[dict],
    verb_pairs: Sequence[Tuple[dict, dict]],
    confusables: Sequence[List[dict]],
    phonetic_families: Sequence[Tuple[str, str, List[dict]]],
    radical_items: Sequence[dict],
    current_level: int,
    next_level: int,
    pitch_index: Dict[Tuple[str, str], dict],
    review_index: Dict[int, dict],
) -> None:
    print("\nDRY RUN — no .apkg files will be written")
    print("=" * 60)
    wanted = {args.deck} if args.deck != "all" else {"leeches", "verb-pairs", "confusables", "phonetic-families", "pitch-leeches", "radicals"}

    if "leeches" in wanted:
        preview_deck_section(
            DECK_NAMES["leeches"],
            [subject_summary(item, review_index) for item in leeches],
        )
    if "pitch-leeches" in wanted:
        pitch_leeches = [i for i in leeches if pitch_for(i, pitch_index).get("pitch") or pitch_for(i, pitch_index).get("pattern")]
        preview_deck_section(
            DECK_NAMES["pitch-leeches"],
            [subject_summary(item, review_index) for item in pitch_leeches],
        )
    if "verb-pairs" in wanted:
        preview_deck_section(
            DECK_NAMES["verb-pairs"],
            [
                f"{left['data'].get('characters') or '?'} ↔ {right['data'].get('characters') or '?'}"
                for left, right in verb_pairs
            ],
        )
    if "confusables" in wanted:
        preview_deck_section(
            DECK_NAMES["confusables"],
            [
                " / ".join(i["data"].get("characters") or "?" for i in group)
                for group in confusables
            ],
        )
    if "phonetic-families" in wanted:
        preview_deck_section(
            DECK_NAMES["phonetic-families"],
            [f"{comp} → {reading} ({len(members)} kanji)" for comp, reading, members in phonetic_families],
        )
    if "radicals" in wanted:
        selected = [
            r for r in radical_items
            if int(r["data"].get("level") or 999) in {current_level, next_level}
        ]
        preview_deck_section(
            DECK_NAMES["radicals"],
            [
                f"{radical_display(r)} [L{r['data'].get('level', '?')}] {'; '.join(primary_meanings(r))}"
                for r in sorted(selected, key=lambda x: (x["data"].get("level", 999), radical_display(x)))
            ],
        )

    print("\nLeech filters:")
    print(f"  incorrect_min={args.leech_incorrect_min}, streak_max={args.leech_streak_max}, score_min={args.leech_score_min}")
    print("\nRe-run without --dry-run to write decks.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--deck", choices=["leeches", "verb-pairs", "confusables", "phonetic-families", "pitch-leeches", "radicals", "all"], default="all")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--pitch-csv")
    parser.add_argument("--yomitan-dict")
    parser.add_argument("--write-pitch-template")
    parser.add_argument("--max-level", type=int, default=60)
    parser.add_argument("--radical-current-level", type=int, default=None, help="Override detected current WaniKani level for radical preview.")
    parser.add_argument("--min-srs", type=int, default=1)
    parser.add_argument("--only-unlocked", action="store_true")
    parser.add_argument("--only-started", action="store_true")
    parser.add_argument("--only-burned", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Preview generated deck contents without writing .apkg files.")
    parser.add_argument("--no-bundle", action="store_true", help="Do not write the combined out/wk_all.apkg file.")
    parser.add_argument("--leech-incorrect-min", type=int, default=3)
    parser.add_argument("--leech-streak-max", type=int, default=5)
    parser.add_argument("--leech-score-min", type=float, default=1.0, help="Minimum composite leech score after incorrect/streak filters.")
    parser.add_argument("--max-cards", type=int, default=200)
    parser.add_argument("--max-confusable-group-size", type=int, default=7)
    parser.add_argument("--min-family-size", type=int, default=3)
    parser.add_argument("--max-family-members", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.version:
        print(f"wk_decks.py v{VERSION} ({BUILD_DATE})")
        return

    print()
    print("=" * 60)
    print(f"WK Deck Generator v{VERSION}")
    print(f"Build Date: {BUILD_DATE}")
    print("=" * 60)
    print()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    user = get_cached_user(refresh=args.refresh_cache)
    subjects = get_cached_collection(
        "subjects",
        params={"types": "vocabulary,kanji,radical"},
        params_key="vocabulary_kanji_radical",
        refresh=args.refresh_cache,
    )
    assignment_params = build_assignment_params(args)
    assignment_key = assignment_params_key(assignment_params)
    assignments = get_cached_collection(
        "assignments",
        params=assignment_params,
        params_key=assignment_key,
        refresh=args.refresh_cache,
    )
    assignment_index = assignment_by_subject_id(assignments)
    review_subject_ids = [
        assignment["data"]["subject_id"]
        for assignment in assignments
        if assignment["data"].get("subject_type") in {"kanji", "vocabulary"}
    ]
    reviews = get_cached_review_statistics(
        review_subject_ids,
        params_key=assignment_key,
        refresh=args.refresh_cache,
    )
    studies = get_cached_collection("study_materials", refresh=args.refresh_cache)
    subject_index = index_subjects_by_id(subjects)
    indexes = {
        "assignments": assignment_index,
        "reviews": review_stats_by_subject_id(reviews),
        "studies": study_materials_by_subject_id(studies),
    }
    pitch_index = merge_pitch_indexes(load_yomitan_pitch(args.yomitan_dict), load_pitch_csv(args.pitch_csv))
    vocab_items = vocab_subjects(subjects, indexes["assignments"], args)
    kanji_items = kanji_subjects(subjects, indexes["assignments"], args)
    radical_items = radical_subjects(subjects, args)
    current_level, next_level = selected_radical_levels(user, subjects, indexes["assignments"], args)
    print(f"WaniKani user level: {user.get('level', '?')}")
    if args.write_pitch_template:
        write_pitch_template(vocab_items, args.write_pitch_template)
        return
    leeches = find_leeches(subjects, indexes["assignments"], indexes["reviews"], args)
    verb_pairs = find_verb_pairs(vocab_items, args)
    confusables = find_confusable_groups(vocab_items, args)
    phonetic_families = find_phonetic_families(kanji_items, args)
    print(f"Eligible vocab: {len(vocab_items)}")
    print(f"Eligible kanji: {len(kanji_items)}")
    print(f"Eligible radicals: {len(radical_items)}")
    print(f"Radical preview levels: current={current_level}, next={next_level}")
    print(f"Leeches: {len(leeches)}")
    print(f"Verb pairs: {len(verb_pairs)}")
    print(f"Confusable groups: {len(confusables)}")
    print(f"Phonetic families: {len(phonetic_families)}")
    print(f"Pitch entries loaded: {len(pitch_index)}")
    if args.dry_run:
        print_preview_report(
            args,
            leeches=leeches,
            verb_pairs=verb_pairs,
            confusables=confusables,
            phonetic_families=phonetic_families,
            radical_items=radical_items,
            current_level=current_level,
            next_level=next_level,
            pitch_index=pitch_index,
            review_index=indexes["reviews"],
        )
        return
    created: List[Path] = []
    built_decks: List[genanki.Deck] = []
    wanted = {args.deck} if args.deck != "all" else {"leeches", "verb-pairs", "confusables", "phonetic-families", "pitch-leeches", "radicals"}
    if "radicals" in wanted and radical_items:
        path, deck = build_radical_deck(radical_items, kanji_items, indexes, args, output_dir, current_level, next_level)
        created.append(path)
        built_decks.append(deck)
    if "leeches" in wanted and leeches:
        path, deck = build_leech_deck(leeches, indexes, pitch_index, output_dir)
        created.append(path)
        built_decks.append(deck)
    if "verb-pairs" in wanted and verb_pairs:
        path, deck = build_pair_deck(verb_pairs, indexes, pitch_index, output_dir)
        created.append(path)
        built_decks.append(deck)
    if "confusables" in wanted and confusables:
        path, deck = build_confusables_deck(confusables, indexes, pitch_index, output_dir, subject_index)
        created.append(path)
        built_decks.append(deck)
    if "phonetic-families" in wanted and phonetic_families:
        path, deck = build_phonetic_family_deck(phonetic_families, output_dir)
        created.append(path)
        built_decks.append(deck)
    if "pitch-leeches" in wanted and leeches:
        maybe = build_pitch_leeches_deck(leeches, indexes, pitch_index, output_dir)
        if maybe:
            path, deck = maybe
            created.append(path)
            built_decks.append(deck)
    if not created:
        print("No decks created. Try lowering filters, refreshing cache, or adding pitch data.", file=sys.stderr)
        sys.exit(1)
    bundle_path: Optional[Path] = None
    if built_decks and not args.no_bundle:
        bundle_path = output_dir / BUNDLE_FILENAME
        write_bundled_apkg(built_decks, bundle_path)
    settings_path = write_filtered_deck_suggestions(output_dir)
    filtered_json_path = write_filtered_decks_json(output_dir)
    instructions_path = write_import_instructions(output_dir)
    print("Created:")
    if bundle_path:
        print(f"  {bundle_path}  ← recommended import")
    for path in created:
        print(f"  {path}")
    print(f"  {settings_path}")
    print(f"  {filtered_json_path}")
    print(f"  {instructions_path}")
    print_import_verification_help(bundle_path)


if __name__ == "__main__":
    main()
