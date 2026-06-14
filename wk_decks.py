#!/usr/bin/env python3
"""
wk_decks.py

Generate update-safe Anki decks from your WaniKani account.

Decks:
  - leeches: items you repeatedly miss in WaniKani
  - verb-pairs: transitive/intransitive and related contrast pairs
  - confusables: vocabulary sharing kanji/readings that are easy to mix up
  - phonetic-families: Keisei phonetic + shared on'yomi reading → WK kanji in that sound group
  - pitch-leeches: leeches with pitch data, if pitch data is supplied
  - radicals: current-level and next-level radicals
  - reading-keywords: high-confidence WK phonetic keywords from reading mnemonics
  - kanji-radicals: kanji whose radical components are unlocked in WaniKani
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

Each run appends one row to out/wk_run_history.csv with deck counts and bundle contents.
"""

from __future__ import annotations

VERSION = "2.14.1"
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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

import genanki
import requests

WK_API_BASE = "https://api.wanikani.com/v2"
WK_REVISION = "20170710"
CACHE_DIR = Path(".wk_cache")
CACHE_MAX_AGE_HOURS = 24
OUTPUT_DIR = Path("out")

# Keisei phonetic-semantic DB (GPL-3.0, mwil/wanikani-userscripts).
# Pinned commit for stable raw JSON URLs; auto-downloaded into .wk_cache/keisei/.
KEISEI_DB_COMMIT = "8ee517737d604f1df0ff103a33b69f1f07218815"
KEISEI_DB_BASE = (
    f"https://raw.githubusercontent.com/mwil/wanikani-userscripts/{KEISEI_DB_COMMIT}"
    "/wanikani-phonetic-compounds/db"
)
KEISEI_CACHE_DIR = CACHE_DIR / "keisei"
KEISEI_DB_FILES = {
    "kanji": "kanji_esc.json",
    "phonetic": "phonetic_esc.json",
    "wk_kanji": "wk_kanji_esc.json",
}

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
READING_KEYWORD_MIN_USES = 5
READING_KEYWORD_MIN_CONSISTENCY = 0.9
READING_KEYWORD_EXAMPLE_LIMIT = 5
READING_MNEMONIC_TAG_RE = re.compile(r"<reading>", re.IGNORECASE)
READING_MNEMONIC_TAG_BODY_RE = re.compile(r"<reading>(.*?)</reading>", re.DOTALL | re.IGNORECASE)
READING_MNEMONIC_PAIR_RE = re.compile(
    r"<reading>(.*?)</reading>\s*(?:\(([^)]+)\)|（([^）]+)）)",
    re.DOTALL | re.IGNORECASE,
)
READING_MNEMONIC_PAREN_KANA_RE = re.compile(r"\(([ぁ-んー]+)\)|（([ぁ-んー]+)）")

# Keep stable after first import.
DECK_IDS = {
    "leeches": 2059400111,
    "verb-pairs": 2059400112,
    "confusables": 2059400113,
    "phonetic-families": 2059400114,
    "pitch-leeches": 2059400115,
    "radicals": 2059400116,
    "reading-keywords": 2059400117,
    "kanji-radicals": 2059400118,
}

MODEL_IDS = {
    "item": 1865429012,
    "pair": 1865429013,
    "family": 1865429014,
    "radical": 1865429015,
    "reading_keyword": 1865429016,
    "kanji_radical": 1865429017,
    "phonetic_drill": 1865429018,
}

# Bump the relevant key when that note type's templates/CSS change.
# Anki import uses model.mod; these map to stable epoch seconds (see template_mod_epoch).
MODEL_TEMPLATE_VERSIONS = {
    "item": "v5",
    "pair": "v2",
    "family": "v1",
    "radical": "v2",
    "reading_keyword": "v1",
    "kanji_radical": "v1",
    "phonetic_drill": "v2",
}
ITEM_MODEL_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["item"]

# Floor for model.mod in .apkg — must exceed past genanki imports that used time.time().
TEMPLATE_MOD_GENERATION_BASE = 1781000000
MODEL_TEMPLATE_MOD_SLOT = {
    "item": 0,
    "pair": 1,
    "family": 2,
    "radical": 3,
    "reading_keyword": 4,
    "kanji_radical": 5,
    "phonetic_drill": 6,
}
TEMPLATE_MOD_SLOT_STRIDE = 10_000_000
TEMPLATE_MOD_SECONDS_PER_VERSION = 86400

# Stable Anki note type names — do not embed version numbers here.
# Template/schema version lives in MODEL_TEMPLATE_VERSIONS and card Meta fields.
NOTE_TYPE_NAMES = {
    "item": "WK Update-Safe Item",
    "pair": "WK Update-Safe Verb Pair",
    "family": "WK Update-Safe Family",
    "radical": "WK Update-Safe Radical",
    "reading_keyword": "WK Update-Safe Reading Keyword",
    "kanji_radical": "WK Update-Safe Kanji Radicals",
    "phonetic_drill": "WK Update-Safe Phonetic Drill",
}

BUNDLE_FILENAME = "wk_all.apkg"
RUN_HISTORY_FILENAME = "wk_run_history.csv"
FILTERED_DECKS_JSON = "anki_filtered_decks.json"
RUN_HISTORY_COLUMNS = [
    "run_at",
    "generator_version",
    "dry_run",
    "deck",
    "wk_level",
    "only_started",
    "only_unlocked",
    "only_burned",
    "min_srs",
    "max_level",
    "refresh_cache",
    "eligible_vocab",
    "eligible_kanji",
    "eligible_radicals",
    "radical_level_current",
    "radical_level_next",
    "leeches",
    "verb_pairs",
    "confusables",
    "phonetic_families",
    "reading_keywords",
    "kanji_radical_breakdown",
    "pitch_entries",
    "pitch_leeches",
    "bundled_in_wk_all",
    "bundled_decks",
]
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
    "reading-keywords": "WaniKani Reading Keywords",
    "kanji-radicals": "WaniKani Kanji Radical Breakdown",
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

/* Kanji vs vocabulary color cues (meaning / reading cards) */
.wk-card { margin: 0 auto; max-width: 760px; padding: 8px 12px 4px; border-radius: 10px; }
.subject-badge {
  display: inline-block;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 999px;
  margin-bottom: 10px;
}
.prompt-hint { font-size: 14px; font-weight: 500; margin-top: 6px; opacity: 0.92; }

.wk-card.wk-kanji {
  background: rgba(74, 144, 226, 0.12);
  border: 2px solid rgba(74, 144, 226, 0.45);
}
.wk-card.wk-kanji .subject-badge { background: #2f6fad; color: #f5f9ff; }
.wk-card.wk-kanji .prompt { color: #4a90e2; }
.wk-card.wk-kanji .prompt-hint { color: #5a9fd4; }
.wk-card.wk-kanji .jp { color: #3d7fc4; }

.wk-card.wk-vocabulary {
  background: rgba(76, 175, 120, 0.12);
  border: 2px solid rgba(76, 175, 120, 0.45);
}
.wk-card.wk-vocabulary .subject-badge { background: #3d8f5c; color: #f4fff7; }
.wk-card.wk-vocabulary .prompt { color: #4caf7a; }
.wk-card.wk-vocabulary .prompt-hint { color: #5cbf8e; }
.wk-card.wk-vocabulary .jp { color: #3d9f68; }

.nightMode .wk-card.wk-kanji,
.card.nightMode .wk-card.wk-kanji,
.night_mode .wk-card.wk-kanji {
  background: rgba(74, 144, 226, 0.18);
  border-color: rgba(126, 184, 232, 0.55);
}
.nightMode .wk-card.wk-kanji .prompt,
.card.nightMode .wk-card.wk-kanji .prompt,
.night_mode .wk-card.wk-kanji .prompt { color: #9ecfff; }
.nightMode .wk-card.wk-kanji .jp,
.card.nightMode .wk-card.wk-kanji .jp,
.night_mode .wk-card.wk-kanji .jp { color: #b8dcff; }

.nightMode .wk-card.wk-vocabulary,
.card.nightMode .wk-card.wk-vocabulary,
.night_mode .wk-card.wk-vocabulary {
  background: rgba(76, 175, 120, 0.16);
  border-color: rgba(125, 206, 160, 0.55);
}
.nightMode .wk-card.wk-vocabulary .prompt,
.card.nightMode .wk-card.wk-vocabulary .prompt,
.night_mode .wk-card.wk-vocabulary .prompt { color: #9de0b8; }
.nightMode .wk-card.wk-vocabulary .jp,
.card.nightMode .wk-card.wk-vocabulary .jp,
.night_mode .wk-card.wk-vocabulary .jp { color: #b8ecc9; }

.pair-back-item { text-align: left; margin: 0 auto; max-width: 360px; padding: 8px; }
.pair-back-item .meaning { font-size: 18px; color: #cfcfcf; margin: 8px 0 10px; }
.pair-role { font-size: 15px; margin: 8px 0; color: #bbb; }
.pair-back-item h4 { font-size: 15px; margin: 12px 0 6px; text-align: left; }
.pair-example { margin: 8px 0; padding: 8px 0; border-top: 1px solid #ddd; }
.pair-example .jp { font-size: 22px; margin-top: 0; }
.pair-example .meaning { font-size: 16px; margin-top: 4px; }
.radical-breakdown { text-align: left; margin: 12px auto; max-width: 640px; }
.radical-piece { margin: 10px 0; padding-bottom: 8px; border-bottom: 1px solid #ddd; }
.radical-piece .jp { font-size: 32px; }
.radicals-front { margin: 16px auto; max-width: 760px; }
.radicals-front-piece { display: inline-block; margin: 6px 12px; font-size: 28px; vertical-align: top; }
.radicals-front-meaning { display: block; font-size: 14px; color: #aaa; margin-top: 4px; }

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


def keisei_cache_path(filename: str) -> Path:
    return KEISEI_CACHE_DIR / filename


def download_keisei_json(url: str) -> dict:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return json.loads(response.text)


def load_keisei_json(key: str, refresh: bool = False) -> dict:
    filename = KEISEI_DB_FILES[key]
    path = keisei_cache_path(filename)
    url = f"{KEISEI_DB_BASE}/{filename}"
    if refresh or not path.exists():
        print(f"Downloading Keisei {key} database...")
        KEISEI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = download_keisei_json(url)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"Saved Keisei cache: {path}")
        return data
    print(f"Using cached Keisei {key}: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def ensure_keisei_databases(refresh: bool = False) -> Dict[str, dict]:
    """Download missing Keisei phonetic DB JSON files; return parsed data when available."""
    loaded: Dict[str, dict] = {}
    for key, filename in KEISEI_DB_FILES.items():
        path = keisei_cache_path(filename)
        try:
            loaded[key] = load_keisei_json(key, refresh=refresh)
        except requests.RequestException as exc:
            print(f"Warning: could not fetch Keisei {key} database: {exc}", file=sys.stderr)
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    loaded[key] = json.load(f)
    return loaded


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

    if refresh or envelope is None:
        print(f"Downloading WaniKani {collection}...")
        items = wk_get_all(collection, params=params)
        save_cache_envelope(path, items)
        print(f"Saved {collection} cache: {path} ({len(items)} items)")
        return items

    if envelope.get("synced_at"):
        print(f"Syncing {collection} since {envelope['synced_at']}...")
        sync_params = dict(params or {})
        sync_params["updated_after"] = envelope["synced_at"]
        delta = wk_get_all(collection, params=sync_params)
        items = merge_records(envelope["items"], delta)
        save_cache_envelope(path, items)
        if delta:
            print(f"Updated {collection} cache: {path} (+{len(delta)} changed, {len(items)} total)")
        else:
            print(f"No {collection} changes since last sync ({len(items)} items in cache)")
        return items

    if not is_stale:
        print(f"Using cached {collection}: {path} ({len(envelope['items'])} items)")
        return envelope["items"]

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

    if refresh or envelope is None:
        print("Downloading WaniKani review_statistics...")
        items = fetch_review_statistics(subject_ids)
        save_cache_envelope(path, items)
        print(f"Saved review_statistics cache: {path} ({len(items)} items)")
        return items

    if envelope.get("synced_at"):
        print(f"Syncing review_statistics since {envelope['synced_at']}...")
        delta = fetch_review_statistics(subject_ids, updated_after=envelope["synced_at"])
        items = merge_records(envelope["items"], delta)
        save_cache_envelope(path, items)
        if delta:
            print(f"Updated review_statistics cache: {path} (+{len(delta)} changed, {len(items)} total)")
        else:
            print(f"No review_statistics changes since last sync ({len(items)} items in cache)")
        return items

    if not is_stale:
        print(f"Using cached review_statistics: {path} ({len(envelope['items'])} items)")
        return envelope["items"]

    print("Downloading WaniKani review_statistics...")
    items = fetch_review_statistics(subject_ids)
    save_cache_envelope(path, items)
    print(f"Saved review_statistics cache: {path} ({len(items)} items)")
    return items


def template_mod_epoch(model_key: str) -> int:
    version = MODEL_TEMPLATE_VERSIONS[model_key]
    match = re.search(r"v(\d+)$", version, re.IGNORECASE)
    version_index = int(match.group(1)) if match else 0
    slot = MODEL_TEMPLATE_MOD_SLOT[model_key]
    return (
        TEMPLATE_MOD_GENERATION_BASE
        + slot * TEMPLATE_MOD_SLOT_STRIDE
        + version_index * TEMPLATE_MOD_SECONDS_PER_VERSION
    )


def versioned_css(css: str, model_key: str) -> str:
    label = f"{model_key}-{MODEL_TEMPLATE_VERSIONS[model_key]}"
    return f"/* WK template {label} · generator {VERSION} */\n{css}"


class WkModel(genanki.Model):
    """genanki.Model with per-note-type mod timestamps so Anki accepts template updates on import."""

    def __init__(self, *args, template_key: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.template_key = template_key

    def to_json(self, timestamp: float, deck_id):
        data = super().to_json(timestamp, deck_id)
        data["mod"] = template_mod_epoch(self.template_key)
        return data


def package_write_timestamp(models: Iterable[genanki.Model]) -> float:
    epochs = [template_mod_epoch(model.template_key) for model in models if hasattr(model, "template_key")]
    if not epochs:
        return time.time()
    return max(epochs) + 1.0


def write_apkg(deck: genanki.Deck, path: Path) -> None:
    models = list(deck.models.values())
    genanki.Package(deck).write_to_file(str(path), timestamp=package_write_timestamp(models))


def write_bundled_apkg(decks: Sequence[genanki.Deck], path: Path) -> None:
    if not decks:
        return
    all_models: List[genanki.Model] = []
    for deck in decks:
        all_models.extend(deck.models.values())
    package = genanki.Package(decks[0])
    package.decks = list(decks)
    package.write_to_file(str(path), timestamp=package_write_timestamp(all_models))


def primary_meanings(subject: dict) -> List[str]:
    meanings = subject["data"].get("meanings", [])
    primary = [m["meaning"] for m in meanings if m.get("primary") or m.get("accepted_answer")]
    return primary or [m["meaning"] for m in meanings]


def primary_readings(subject: dict) -> List[str]:
    readings = subject["data"].get("readings", [])
    primary = [r["reading"] for r in readings if r.get("primary") or r.get("accepted_answer")]
    return primary or [r["reading"] for r in readings]


def wk_onyomi_readings(subject: dict) -> List[str]:
    readings = subject["data"].get("readings", [])
    return [r["reading"] for r in readings if r.get("type") == "onyomi"]


def keisei_kanji_readings(char: str, keisei_kanji: dict) -> List[str]:
    return list((keisei_kanji.get(char) or {}).get("readings") or [])


def kanji_shares_phonetic_reading(
    subject: dict,
    char: str,
    reading: str,
    keisei_kanji: dict,
) -> bool:
    """True when Keisei and WK both list this on'yomi for the kanji."""
    keisei_readings = keisei_kanji_readings(char, keisei_kanji)
    if reading not in keisei_readings:
        return False
    wk_onyomi = wk_onyomi_readings(subject)
    return bool(wk_onyomi) and reading in wk_onyomi


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


def subject_style_class(subject: dict) -> str:
    kind = subject.get("object") or ""
    if kind == "kanji":
        return "wk-kanji"
    if kind == "vocabulary":
        return "wk-vocabulary"
    return "wk-item"


def subject_type_flags(subject: dict) -> Tuple[str, str]:
    kind = subject.get("object") or ""
    is_kanji = "1" if kind == "kanji" else ""
    is_vocabulary = "1" if kind == "vocabulary" else ""
    return is_kanji, is_vocabulary


def reading_mnemonic(subject: dict) -> str:
    return strip_html(subject["data"].get("reading_mnemonic"))


class ReadingKeywordEntry(NamedTuple):
    kana: str
    keyword: str
    uses: int
    consistency: float
    example_html: str


def normalize_reading_keyword(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw).strip().lower()
    text = re.sub(r"\s+", " ", text)
    if len(text) > 32:
        text = text.split(" ", 1)[0]
    return text.strip()


def primary_reading_list(subject: dict) -> List[str]:
    readings = subject["data"].get("readings") or []
    primary = [r["reading"] for r in readings if r.get("primary") or r.get("accepted_answer")]
    return primary or [r["reading"] for r in readings]


def extract_reading_mnemonic_pairs(subject: dict) -> List[Tuple[str, str]]:
    mnemonic = subject["data"].get("reading_mnemonic") or ""
    if not mnemonic:
        return []

    pairs: List[Tuple[str, str]] = []
    for match in READING_MNEMONIC_PAIR_RE.finditer(mnemonic):
        keyword = normalize_reading_keyword(match.group(1))
        kana = (match.group(2) or match.group(3) or "").strip()
        if keyword and kana:
            pairs.append((kana, keyword))

    if pairs:
        return pairs

    if not READING_MNEMONIC_TAG_RE.search(mnemonic):
        return []

    tags = [normalize_reading_keyword(tag) for tag in READING_MNEMONIC_TAG_BODY_RE.findall(mnemonic)]
    kana_in_paren = [
        match.group(1) or match.group(2) or ""
        for match in READING_MNEMONIC_PAREN_KANA_RE.finditer(mnemonic)
    ]
    if tags and kana_in_paren and len(tags) == len(kana_in_paren):
        return [(kana.strip(), keyword) for kana, keyword in zip(kana_in_paren, tags) if kana and keyword]
    if len(tags) == 1 and len(kana_in_paren) == 1:
        return [(kana_in_paren[0].strip(), tags[0])]
    primary = primary_reading_list(subject)
    if len(tags) == 1 and primary:
        return [(primary[0], tags[0])]
    return []


def reading_keyword_example_html(subjects: Sequence[dict]) -> str:
    rows: List[str] = []
    for subject in subjects[:READING_KEYWORD_EXAMPLE_LIMIT]:
        data = subject["data"]
        chars = html.escape(data.get("characters") or data.get("slug") or "?")
        kind = subject.get("object") or "item"
        level = data.get("level", "?")
        meaning = html.escape("; ".join(primary_meanings(subject)))
        rows.append(
            f"<div class='member'><span class='jp'>{chars}</span> "
            f"<span class='meta'>{html.escape(kind)} · WK Level {level}</span> "
            f"<span class='meaning'>{meaning}</span></div>"
        )
    return "".join(rows)


def build_reading_keyword_catalog(
    subjects: Sequence[dict],
    min_uses: int = READING_KEYWORD_MIN_USES,
    min_consistency: float = READING_KEYWORD_MIN_CONSISTENCY,
) -> List[ReadingKeywordEntry]:
    counts: DefaultDict[str, Counter] = defaultdict(Counter)
    examples: DefaultDict[Tuple[str, str], List[dict]] = defaultdict(list)

    for subject in subjects:
        if subject.get("object") not in ("kanji", "vocabulary"):
            continue
        for kana, keyword in extract_reading_mnemonic_pairs(subject):
            counts[kana][keyword] += 1
            key = (kana, keyword)
            if len(examples[key]) < READING_KEYWORD_EXAMPLE_LIMIT:
                examples[key].append(subject)

    entries: List[ReadingKeywordEntry] = []
    for kana, keyword_counts in counts.items():
        total = sum(keyword_counts.values())
        if total < min_uses:
            continue
        keyword, top_count = keyword_counts.most_common(1)[0]
        consistency = top_count / total
        if consistency < min_consistency:
            continue
        entries.append(
            ReadingKeywordEntry(
                kana=kana,
                keyword=keyword,
                uses=total,
                consistency=consistency,
                example_html=reading_keyword_example_html(examples[(kana, keyword)]),
            )
        )

    return sorted(entries, key=lambda entry: (-entry.uses, entry.kana))


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



def make_radical_model() -> WkModel:
    return WkModel(
        MODEL_IDS["radical"],
        NOTE_TYPE_NAMES["radical"],
        template_key="radical",
        fields=[
            {"name": "GuidKey"},
            {"name": "Radical"},
            {"name": "Meaning"},
            {"name": "Level"},
            {"name": "Status"},
            {"name": "KanjiPreview"},
            {"name": "Notes"},
            {"name": "Description"},
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
                {{#Description}}<h3>Description</h3><div class='notes'>{{Description}}</div>{{/Description}}
                {{#KanjiPreview}}<h3>Used in / upcoming kanji</h3><div class='family-members'>{{KanjiPreview}}</div>{{/KanjiPreview}}
                """,
            }
        ],
        css=versioned_css(COMMON_CSS, "radical"),
    )



def make_item_model() -> WkModel:
    return WkModel(
        MODEL_IDS["item"],
        NOTE_TYPE_NAMES["item"],
        template_key="item",
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
            {"name": "StyleClass"},
            {"name": "IsKanji"},
            {"name": "IsVocabulary"},
        ],
        templates=[
            {
                "name": "Meaning",
                "qfmt": """
                <div class="wk-card {{StyleClass}}">
                <div class="subject-badge">{{SubjectType}}</div>
                <div class="prompt">
                  Meaning?
                  {{#IsKanji}}<div class="prompt-hint">Kanji meaning (English)</div>{{/IsKanji}}
                  {{#IsVocabulary}}<div class="prompt-hint">Vocabulary meaning (English)</div>{{/IsVocabulary}}
                </div>
                {{#MeaningWeak}}<div class="weak-side">Meaning side needs work</div>{{/MeaningWeak}}
                <div class="jp">{{Expression}}</div>
                </div>
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
                <div class="wk-card {{StyleClass}}">
                <div class="subject-badge">{{SubjectType}}</div>
                <div class="prompt">
                  Reading?
                  {{#IsKanji}}<div class="prompt-hint">On'yomi / kun'yomi</div>{{/IsKanji}}
                  {{#IsVocabulary}}<div class="prompt-hint">Vocabulary reading (kana)</div>{{/IsVocabulary}}
                </div>
                {{#ReadingWeak}}<div class="weak-side">Reading side needs work</div>{{/ReadingWeak}}
                <div class="jp">{{Expression}}</div>
                </div>
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
                "qfmt": "{{#Pitch}}<div class='wk-card {{StyleClass}}'><div class='subject-badge'>{{SubjectType}}</div><div class='prompt'>Pitch accent?</div><div class='jp'>{{Expression}}</div><div class='reading'>{{Reading}}</div></div>{{/Pitch}}",
                "afmt": "{{FrontSide}}<hr><div class='pitch-answer'>{{Pitch}} {{PitchPattern}}</div>{{ItemHtml}}",
            },
        ],
        css=versioned_css(COMMON_CSS, "item"),
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


def pair_context_block_html(subject: dict, heading: str = "Context") -> str:
    sentences = context_sentences_html(subject)
    if not sentences:
        return ""
    return f"<h4>{html.escape(heading)}</h4>{sentences}"


def pair_side_back_html(
    subject: dict,
    assignment_index: Dict[int, dict],
    pitch_index: Dict[Tuple[str, str], dict],
    role: str = "",
) -> str:
    data = subject["data"]
    expr = html.escape(data.get("characters") or "")
    reading = html.escape("、".join(primary_readings(subject)) or first_reading(subject))
    meanings = html.escape("; ".join(primary_meanings(subject)))
    role_html = f"<div class='pair-role'><b>Contrast role:</b> {html.escape(role)}</div>" if role else ""
    vt = verb_type(subject)
    vt_html = f"<div class='meta'><b>Verb type:</b> {html.escape(vt)}</div>" if vt else ""
    pitch = pitch_for(subject, pitch_index)
    pitch_html = ""
    if pitch.get("pitch") or pitch.get("pattern"):
        pitch_html = (
            f"<div class='pitch'><b>Pitch:</b> "
            f"{html.escape(str(pitch.get('pitch') or ''))} "
            f"<span>{html.escape(str(pitch.get('pattern') or ''))}</span></div>"
        )
    context_html = pair_context_block_html(subject)
    return f"""
    <div class="pair-back-item">
      <div class="jp">{expr}</div>
      <div class="reading">{reading}</div>
      <div class="meaning">{meanings}</div>
      {role_html}
      {vt_html}
      {context_html}
      {pitch_html}
      <div class="meta">WK Level {data.get('level', '?')} · SRS {srs_stage(subject, assignment_index)} · template {MODEL_TEMPLATE_VERSIONS['pair']}</div>
    </div>
    """


def pair_examples_html(curated_examples: str) -> str:
    return curated_examples or ""

def make_pair_model() -> WkModel:
    return WkModel(
        MODEL_IDS["pair"],
        NOTE_TYPE_NAMES["pair"],
        template_key="pair",
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
                {{#Examples}}<h3>Contrast examples</h3><div class='notes'>{{Examples}}</div>{{/Examples}}
                <h3>Relationship</h3>
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
                {{#Examples}}<h3>Examples</h3><div class='notes'>{{Examples}}</div>{{/Examples}}
                <div class='notes'>{{Explanation}}</div>
                """,
            },
            {
                "name": "Pitch Contrast",
                "qfmt": "{{#LeftPitch}}<div class='prompt'>Compare pitch accent.</div><div class='pair-line'>{{LeftExpression}} / {{RightExpression}}</div>{{/LeftPitch}}",
                "afmt": "{{FrontSide}}<hr><b>{{LeftExpression}}</b>: {{LeftPitch}}<br><b>{{RightExpression}}</b>: {{RightPitch}}",
            },
        ],
        css=versioned_css(COMMON_CSS, "pair"),
    )


def make_family_model() -> WkModel:
    return WkModel(
        MODEL_IDS["family"],
        NOTE_TYPE_NAMES["family"],
        template_key="family",
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
        css=versioned_css(COMMON_CSS, "family"),
    )



def make_reading_keyword_model() -> WkModel:
    return WkModel(
        MODEL_IDS["reading_keyword"],
        NOTE_TYPE_NAMES["reading_keyword"],
        template_key="reading_keyword",
        fields=[
            {"name": "GuidKey"},
            {"name": "Kana"},
            {"name": "Keyword"},
            {"name": "Examples"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Reading → Keyword",
                "qfmt": """
                <div class="prompt">WK phonetic keyword?</div>
                <div class="reading-kana">{{Kana}}</div>
                <div class="meta">WaniKani reading mnemonic keyword</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="keyword-answer">{{Keyword}}</div>
                {{#Examples}}<h3>Used in WK mnemonics</h3><div class="family-members">{{Examples}}</div>{{/Examples}}
                <div class="meta">{{Meta}}</div>
                """,
            },
            {
                "name": "Keyword → Reading",
                "qfmt": """
                <div class="prompt">Which reading chunk?</div>
                <div class="keyword-front">{{Keyword}}</div>
                <div class="meta">Recall the kana this WK keyword represents</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="reading answer">{{Kana}}</div>
                {{#Examples}}<h3>Used in WK mnemonics</h3><div class="family-members">{{Examples}}</div>{{/Examples}}
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(COMMON_CSS + """
.reading-kana { font-size: 48px; margin: 16px 0; color: #d8d8d8; font-weight: 600; }
.keyword-front { font-size: 40px; margin: 16px 0; color: #cfcfcf; font-weight: 600; }
.keyword-answer { font-size: 36px; margin: 12px 0; color: #cfcfcf; font-weight: 600; }
""", "reading_keyword"),
    )



def make_kanji_radical_model() -> WkModel:
    return WkModel(
        MODEL_IDS["kanji_radical"],
        NOTE_TYPE_NAMES["kanji_radical"],
        template_key="kanji_radical",
        fields=[
            {"name": "GuidKey"},
            {"name": "Kanji"},
            {"name": "RadicalsFrontHtml"},
            {"name": "RadicalsBackHtml"},
            {"name": "MeaningMnemonic"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Kanji → Radicals",
                "qfmt": """
                <div class="prompt">Which radicals?</div>
                <div class="jp">{{Kanji}}</div>
                <div class="meta">Recall the radical building blocks</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                {{RadicalsBackHtml}}
                {{#MeaningMnemonic}}<h3>Meaning mnemonic</h3><div class="notes">{{MeaningMnemonic}}</div>{{/MeaningMnemonic}}
                <div class="meta">{{Meta}}</div>
                """,
            },
            {
                "name": "Radicals → Kanji",
                "qfmt": """
                <div class="prompt">Which kanji uses these radicals?</div>
                {{RadicalsFrontHtml}}
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="jp">{{Kanji}}</div>
                {{#MeaningMnemonic}}<h3>Meaning mnemonic</h3><div class="notes">{{MeaningMnemonic}}</div>{{/MeaningMnemonic}}
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(COMMON_CSS, "kanji_radical"),
    )


def make_phonetic_drill_model() -> WkModel:
    return WkModel(
        MODEL_IDS["phonetic_drill"],
        NOTE_TYPE_NAMES["phonetic_drill"],
        template_key="phonetic_drill",
        fields=[
            {"name": "GuidKey"},
            {"name": "Kanji"},
            {"name": "Prompt"},
            {"name": "ReadingAnswer"},
            {"name": "PhoneticPiece"},
            {"name": "AnchorHtml"},
            {"name": "Meaning"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Kanji → On'yomi via phonetic",
                "qfmt": """
                <div class="prompt">{{Prompt}}</div>
                <div class="jp">{{Kanji}}</div>
                <div class="meta">Predict the on'yomi using the phonetic component</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="reading answer">{{ReadingAnswer}}</div>
                <div class="phonetic-piece">
                  <span class="meta">Phonetic component</span>
                  <span class="jp">{{PhoneticPiece}}</span>
                </div>
                <div class="meaning">{{Meaning}}</div>
                <div class="meta">{{Meta}}</div>
                {{AnchorHtml}}
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.phonetic-piece { margin: 12px 0; }
.phonetic-piece .jp { font-size: 36px; }
.phonetic-anchor-footnote {
  font-size: 13px;
  font-weight: normal;
  color: #aaa;
  margin-top: 14px;
  text-align: left;
  max-width: 760px;
  margin-left: auto;
  margin-right: auto;
}
.phonetic-anchor-footnote .phonetic-anchor-label {
  font-size: 13px;
  font-weight: normal;
  color: #aaa;
  margin-bottom: 6px;
}
.phonetic-anchor-footnote .phonetic-anchor { margin: 6px 0; }
.phonetic-anchor-footnote .jp { font-size: 18px; }
.phonetic-anchor-footnote .reading { font-size: 15px; color: #aaa; font-weight: normal; }
.phonetic-anchor-footnote .meta { font-size: 12px; }
""",
            "phonetic_drill",
        ),
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


def radical_description_html(radical: dict) -> str:
    mnemonic = strip_html(radical["data"].get("meaning_mnemonic"))
    return html.escape(mnemonic) if mnemonic else ""


def radical_index_by_id(subjects: Sequence[dict]) -> Dict[int, dict]:
    return {subject["id"]: subject for subject in subjects if subject.get("object") == "radical"}


def unlocked_subject_ids(subjects: Sequence[dict], assignment_index: Dict[int, dict]) -> Set[int]:
    return {subject["id"] for subject in subjects if is_unlocked(subject, assignment_index)}


def kanji_has_unlocked_radicals_only(kanji: dict, unlocked_radical_ids: Set[int]) -> bool:
    component_ids = kanji["data"].get("component_subject_ids") or []
    return bool(component_ids) and all(component_id in unlocked_radical_ids for component_id in component_ids)


def kanji_radicals_back_html(kanji: dict, radical_index: Dict[int, dict]) -> str:
    rows: List[str] = []
    for component_id in kanji["data"].get("component_subject_ids") or []:
        radical = radical_index.get(component_id)
        if not radical:
            continue
        display = html.escape(radical_display(radical))
        meaning = html.escape("; ".join(primary_meanings(radical)))
        rows.append(
            f"<div class='radical-piece'><span class='jp'>{display}</span> "
            f"<span class='meaning'>{meaning}</span></div>"
        )
    return f"<div class='radical-breakdown'>{''.join(rows)}</div>" if rows else ""


def kanji_radicals_front_html(kanji: dict, radical_index: Dict[int, dict]) -> str:
    pieces: List[str] = []
    for component_id in kanji["data"].get("component_subject_ids") or []:
        radical = radical_index.get(component_id)
        if not radical:
            continue
        display = html.escape(radical_display(radical))
        meaning = html.escape("; ".join(primary_meanings(radical)))
        pieces.append(
            f"<span class='radicals-front-piece'>{display}"
            f"<span class='radicals-front-meaning'>{meaning}</span></span>"
        )
    if not pieces:
        return ""
    return f"<div class='radicals-front'>{''.join(pieces)}</div>"


def meaning_mnemonic_html(subject: dict) -> str:
    mnemonic = strip_html(subject["data"].get("meaning_mnemonic"))
    return html.escape(mnemonic) if mnemonic else ""


def find_kanji_radical_breakdown(
    kanji_items: Sequence[dict],
    radical_items: Sequence[dict],
    assignment_index: Dict[int, dict],
    args: argparse.Namespace,
) -> List[dict]:
    unlocked_radical_ids = unlocked_subject_ids(radical_items, assignment_index)
    candidates = [
        kanji
        for kanji in kanji_items
        if kanji_has_unlocked_radicals_only(kanji, unlocked_radical_ids)
    ]
    return sorted(
        candidates,
        key=lambda kanji: (
            kanji["data"].get("level", 999),
            kanji["data"].get("characters") or "",
        ),
    )[: args.max_cards]


def vocab_subjects(subjects: Sequence[dict], assignment_index: Dict[int, dict], args: argparse.Namespace) -> List[dict]:
    return [s for s in subjects if s.get("object") == "vocabulary" and passes_progress_filter(s, assignment_index, args)]


def kanji_subjects(subjects: Sequence[dict], assignment_index: Dict[int, dict], args: argparse.Namespace) -> List[dict]:
    return [s for s in subjects if s.get("object") == "kanji" and passes_progress_filter(s, assignment_index, args)]


def all_wk_kanji_subjects(subjects: Sequence[dict], args: argparse.Namespace) -> List[dict]:
    """All WaniKani kanji up to max_level (ignores started/unlocked filters)."""
    return [
        s
        for s in subjects
        if s.get("object") == "kanji" and s["data"].get("level", 999) <= args.max_level
    ]


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


def kanji_by_char(kanji_items: Sequence[dict]) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for item in kanji_items:
        char = item["data"].get("characters")
        if char:
            index[char] = item
    return index


def known_phonetic_components(started_kanji: Sequence[dict], keisei_kanji: dict) -> Set[str]:
    """Phonetic pieces from Keisei for kanji the user has already started."""
    known: Set[str] = set()
    for item in started_kanji:
        char = item["data"].get("characters")
        if not char:
            continue
        phonetic = (keisei_kanji.get(char) or {}).get("phonetic")
        if phonetic:
            known.add(phonetic)
    return known


def find_phonetic_families(
    started_kanji_items: Sequence[dict],
    all_kanji_items: Sequence[dict],
    keisei_phonetic: dict,
    keisei_kanji: dict,
    args: argparse.Namespace,
) -> List[Tuple[str, str, List[dict]]]:
    """Phonetic + on'yomi groups seeded from started kanji; members may include future WK kanji."""
    if not keisei_phonetic or not keisei_kanji or not started_kanji_items:
        return []

    known_phonetics = known_phonetic_components(started_kanji_items, keisei_kanji)
    if not known_phonetics:
        return []

    started_ids = {item["id"] for item in started_kanji_items}
    by_char = kanji_by_char(all_kanji_items)
    families: List[Tuple[str, str, List[dict]]] = []
    for comp in sorted(known_phonetics):
        meta = keisei_phonetic.get(comp)
        if not meta:
            continue
        by_reading: DefaultDict[str, List[dict]] = defaultdict(list)
        for char in meta.get("compounds") or []:
            if char == comp or char not in by_char:
                continue
            subject = by_char[char]
            for reading in meta.get("readings") or []:
                if not reading or not kanji_shares_phonetic_reading(subject, char, reading, keisei_kanji):
                    continue
                by_reading[reading].append(subject)
        for reading, members in by_reading.items():
            unique_members = sorted(
                {item["id"]: item for item in members}.values(),
                key=lambda item: item["data"].get("level", 999),
            )
            if len(unique_members) < args.min_family_size:
                continue
            if not any(item["id"] in started_ids for item in unique_members):
                continue
            families.append((comp, reading, unique_members[: args.max_family_members]))

    families.sort(
        key=lambda family: (
            min(member["data"].get("level", 999) for member in family[2]),
            family[0],
            family[1],
        ),
    )
    return families[: args.max_cards]


def phonetic_drill_note_count(families: Sequence[Tuple[str, str, List[dict]]]) -> int:
    return sum(len(members) for _, _, members in families)


def kanji_onyomi_label(kanji: dict, char: str, keisei_kanji: dict) -> str:
    onyomi = wk_onyomi_readings(kanji) or keisei_kanji_readings(char, keisei_kanji)
    return "、".join(onyomi)


def phonetic_anchor_back_html(
    comp: str,
    members: Sequence[dict],
    current_kanji_id: int,
    started_kanji_ids: Set[int],
    all_kanji_by_char: Dict[str, dict],
    keisei_kanji: dict,
) -> str:
    """Anchor kanji with full on'yomi so the phonetic piece is not mis-learned."""
    parts: List[str] = []
    if comp in all_kanji_by_char:
        anchor = all_kanji_by_char[comp]
        onyomi_label = kanji_onyomi_label(anchor, comp, keisei_kanji)
        parts.append(
            f"<div class='phonetic-anchor'>"
            f"<div class='meta'>Phonetic kanji {html.escape(comp)} — all on'yomi:</div>"
            f"<span class='jp'>{html.escape(comp)}</span> "
            f"<span class='reading'>{html.escape(onyomi_label)}</span>"
            f"</div>"
        )
    started_others = sorted(
        [
            member
            for member in members
            if member["id"] in started_kanji_ids and member["id"] != current_kanji_id
        ],
        key=lambda item: item["data"].get("level", 999),
    )
    if started_others:
        rows = []
        for member in started_others:
            char = member["data"].get("characters") or ""
            onyomi_label = kanji_onyomi_label(member, char, keisei_kanji)
            rows.append(
                f"<div class='member'>"
                f"<span class='jp'>{html.escape(char)}</span> "
                f"<span class='reading'>{html.escape(onyomi_label)}</span>"
                f"</div>"
            )
        parts.append(
            f"<div class='phonetic-anchor'>"
            f"<div class='meta'>You already know (same sound family):</div>"
            f"<div class='family-members'>{''.join(rows)}</div>"
            f"</div>"
        )
    if not parts:
        return ""
    return (
        "<div class='phonetic-anchor-footnote'>"
        "<div class='phonetic-anchor-label'>Don't mix up these readings</div>"
        f"{''.join(parts)}"
        "</div>"
    )


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
    is_kanji, is_vocabulary = subject_type_flags(subject)
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
            subject_style_class(subject),
            is_kanji,
            is_vocabulary,
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
        kanji_html = ""
        if preview_kanji:
            kanji_html = "".join(
                f"<div class='member'><span class='jp'>{html.escape(k['data'].get('characters') or '')}</span> "
                f"<span class='reading'>{html.escape('、'.join(primary_readings(k)))}</span> "
                f"<span class='meaning'>{html.escape('; '.join(primary_meanings(k)))}</span> "
                f"<span class='meta'>WK Level {k['data'].get('level', '?')}</span></div>"
                for k in preview_kanji
            )

        note = genanki.Note(
            model=model,
            fields=[
                stable_guid("radical", radical["id"], current_level, next_level),
                radical_text,
                meanings,
                str(level),
                html.escape(status),
                kanji_html,
                "",
                radical_description_html(radical),
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
        examples = pair_examples_html(metadata.get("examples", ""))

        explanation = (
            f"<b>{html.escape(relationship)}</b><br>"
            f"{html.escape(left['data'].get('characters') or '')}: {html.escape(left_role)}<br>"
            f"{html.escape(right['data'].get('characters') or '')}: {html.escape(right_role)}"
        )

        note = genanki.Note(
            model=model,
            fields=[
                guid,
                compact_pair_front(left),
                compact_pair_front(right),
                pair_side_back_html(left, indexes["assignments"], pitch_index, left_role),
                pair_side_back_html(right, indexes["assignments"], pitch_index, right_role),
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


def build_phonetic_family_deck(
    families: Sequence[Tuple[str, str, List[dict]]],
    keisei_kanji: dict,
    started_kanji_ids: Set[int],
    all_kanji_by_char: Dict[str, dict],
    output_dir: Path,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["phonetic-families"], DECK_NAMES["phonetic-families"])
    model = make_phonetic_drill_model()
    template_label = MODEL_TEMPLATE_VERSIONS["phonetic_drill"]
    for comp, reading, members in families:
        for kanji in members:
            data = kanji["data"]
            char = data.get("characters") or ""
            is_started = kanji["id"] in started_kanji_ids
            meaning = "; ".join(primary_meanings(kanji))
            level = data.get("level", "?")
            progress = "started" if is_started else "preview"
            anchor_html = phonetic_anchor_back_html(
                comp,
                members,
                kanji["id"],
                started_kanji_ids,
                all_kanji_by_char,
                keisei_kanji,
            )
            meta = (
                f"WK Level {level} · {progress} · {comp}→{reading} · "
                f"template {template_label}"
            )
            guid = stable_guid("phonetic-drill", kanji["id"], comp, reading)
            note = genanki.Note(
                model=model,
                fields=[
                    guid,
                    html.escape(char),
                    "What is the on'yomi reading?",
                    html.escape(reading),
                    html.escape(comp),
                    anchor_html,
                    html.escape(meaning),
                    html.escape(meta),
                ],
                tags=[
                    "wanikani",
                    "phonetic-drill",
                    "phonetic-family",
                    "priority-low",
                    f"reading-{reading}",
                    progress,
                ],
                guid=guid,
            )
            deck.add_note(note)
    out = output_dir / "wk_phonetic_families.apkg"
    write_apkg(deck, out)
    return out, deck


def build_reading_keyword_deck(
    entries: Sequence[ReadingKeywordEntry],
    output_dir: Path,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["reading-keywords"], DECK_NAMES["reading-keywords"])
    model = make_reading_keyword_model()
    for entry in entries:
        guid = stable_guid("reading-keyword", entry.kana)
        meta = (
            f"WK mnemonic uses: {entry.uses} · consistency {entry.consistency:.0%} · "
            f"template {MODEL_TEMPLATE_VERSIONS['reading_keyword']}"
        )
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                html.escape(entry.kana),
                html.escape(entry.keyword),
                entry.example_html,
                html.escape(meta),
            ],
            tags=[
                "wanikani",
                "reading-keyword",
                "priority-low",
                f"reading-{entry.kana}",
            ],
            guid=guid,
        )
        deck.add_note(note)
    out = output_dir / "wk_reading_keywords.apkg"
    write_apkg(deck, out)
    return out, deck


def build_kanji_radical_deck(
    kanji_items: Sequence[dict],
    radical_index: Dict[int, dict],
    assignment_index: Dict[int, dict],
    output_dir: Path,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["kanji-radicals"], DECK_NAMES["kanji-radicals"])
    model = make_kanji_radical_model()
    for kanji in kanji_items:
        data = kanji["data"]
        guid = stable_guid("kanji-radical", kanji["id"])
        radicals_back = kanji_radicals_back_html(kanji, radical_index)
        if not radicals_back:
            continue
        level = data.get("level", "?")
        meta = (
            f"WK Level {level} · SRS {srs_stage(kanji, assignment_index)} · "
            f"template {MODEL_TEMPLATE_VERSIONS['kanji_radical']}"
        )
        component_tags = [
            f"radical-{radical['data'].get('slug') or radical_display(radical)}"
            for component_id in data.get("component_subject_ids") or []
            for radical in [radical_index.get(component_id)]
            if radical
        ]
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                html.escape(data.get("characters") or ""),
                kanji_radicals_front_html(kanji, radical_index),
                radicals_back,
                meaning_mnemonic_html(kanji),
                html.escape(meta),
            ],
            tags=[
                "wanikani",
                "kanji-radical",
                "priority-medium",
                f"wk-level-{level}",
                *component_tags[:8],
            ],
            guid=guid,
        )
        deck.add_note(note)
    out = output_dir / "wk_kanji_radicals.apkg"
    write_apkg(deck, out)
    return out, deck



def count_pitch_leeches(leeches: Sequence[dict], pitch_index: Dict[Tuple[str, str], dict]) -> int:
    return sum(
        1
        for item in leeches
        if pitch_for(item, pitch_index).get("pitch") or pitch_for(item, pitch_index).get("pattern")
    )


def wanted_decks(args: argparse.Namespace) -> Set[str]:
    if args.deck != "all":
        return {args.deck}
    return {
        "leeches",
        "verb-pairs",
        "confusables",
        "phonetic-families",
        "pitch-leeches",
        "radicals",
        "reading-keywords",
        "kanji-radicals",
    }


def deck_names_for_run(
    wanted: Set[str],
    *,
    radical_items: Sequence[dict],
    leeches: Sequence[dict],
    verb_pairs: Sequence[Tuple[dict, dict]],
    confusables: Sequence[List[dict]],
    phonetic_families: Sequence[Tuple[str, str, List[dict]]],
    reading_keywords: Sequence[ReadingKeywordEntry],
    kanji_radical_items: Sequence[dict],
    pitch_index: Dict[Tuple[str, str], dict],
) -> List[str]:
    names: List[str] = []
    if "radicals" in wanted and radical_items:
        names.append(DECK_NAMES["radicals"])
    if "leeches" in wanted and leeches:
        names.append(DECK_NAMES["leeches"])
    if "verb-pairs" in wanted and verb_pairs:
        names.append(DECK_NAMES["verb-pairs"])
    if "confusables" in wanted and confusables:
        names.append(DECK_NAMES["confusables"])
    if "phonetic-families" in wanted and phonetic_families:
        names.append(DECK_NAMES["phonetic-families"])
    if "reading-keywords" in wanted and reading_keywords:
        names.append(DECK_NAMES["reading-keywords"])
    if "kanji-radicals" in wanted and kanji_radical_items:
        names.append(DECK_NAMES["kanji-radicals"])
    if "pitch-leeches" in wanted and leeches and count_pitch_leeches(leeches, pitch_index):
        names.append(DECK_NAMES["pitch-leeches"])
    return names


def build_run_history_row(
    args: argparse.Namespace,
    user: dict,
    *,
    dry_run: bool,
    current_level: int,
    next_level: int,
    vocab_count: int,
    kanji_count: int,
    radical_count: int,
    leeches: Sequence[dict],
    verb_pairs: Sequence[Tuple[dict, dict]],
    confusables: Sequence[List[dict]],
    phonetic_families: Sequence[Tuple[str, str, List[dict]]],
    reading_keywords: Sequence[ReadingKeywordEntry],
    kanji_radical_items: Sequence[dict],
    radical_items: Sequence[dict],
    pitch_index: Dict[Tuple[str, str], dict],
    bundled_deck_names: Sequence[str],
    bundled_in_wk_all: bool,
) -> Dict[str, Any]:
    wanted = wanted_decks(args)
    return {
        "run_at": utc_now_iso(),
        "generator_version": VERSION,
        "dry_run": int(dry_run),
        "deck": args.deck,
        "wk_level": user.get("level", ""),
        "only_started": int(args.only_started),
        "only_unlocked": int(args.only_unlocked),
        "only_burned": int(args.only_burned),
        "min_srs": args.min_srs,
        "max_level": args.max_level,
        "refresh_cache": int(args.refresh_cache),
        "eligible_vocab": vocab_count,
        "eligible_kanji": kanji_count,
        "eligible_radicals": radical_count,
        "radical_level_current": current_level,
        "radical_level_next": next_level,
        "leeches": len(leeches),
        "verb_pairs": len(verb_pairs),
        "confusables": len(confusables),
        "phonetic_families": len(phonetic_families),
        "reading_keywords": len(reading_keywords),
        "kanji_radical_breakdown": len(kanji_radical_items),
        "pitch_entries": len(pitch_index),
        "pitch_leeches": count_pitch_leeches(leeches, pitch_index),
        "bundled_in_wk_all": int(bundled_in_wk_all),
        "bundled_decks": "|".join(bundled_deck_names),
    }


def append_run_history(output_dir: Path, row: Dict[str, Any]) -> Path:
    path = output_dir / RUN_HISTORY_FILENAME
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RUN_HISTORY_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in RUN_HISTORY_COLUMNS})
    return path


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



def format_template_versions() -> str:
    lines = [f"  {NOTE_TYPE_NAMES[key]}: template {MODEL_TEMPLATE_VERSIONS[key]}" for key in MODEL_TEMPLATE_VERSIONS]
    return "\n".join(lines)


def write_import_instructions(output_dir: Path) -> Path:
    note_types = ", ".join(NOTE_TYPE_NAMES.values())
    template_lines = format_template_versions()
    path = output_dir / "anki_import_instructions.txt"
    path.write_text(
        f"""WaniKani → Anki import instructions (generator {VERSION})

RECOMMENDED: import the bundled file
  {BUNDLE_FILENAME}

This updates every deck in one step with one Anki dialog.

When Anki asks about existing note types:
  - Choose UPDATE / replace existing note type
  - "Update if newer" is usually enough after regenerating decks
  - Use "Always update" if templates still look stale
  - Do NOT choose "Create new note type" or "Keep old note type"

Expected note type names (stable — no version suffix):
  {note_types}

Current template versions (bump in wk_decks.py when cards/CSS change):
{template_lines}

After import, verify card backs include the expected template label:
  - Leech / pitch leech: template {MODEL_TEMPLATE_VERSIONS['item']}
  - Verb pairs: template {MODEL_TEMPLATE_VERSIONS['pair']} on each verb back

Meaning / Reading card fronts should show only the Japanese expression.
Pitch cards may also show the reading on front when pitch data exists.

Individual deck files (wk_leeches.apkg, etc.) are still written for one-off
imports, but weekly updates are cleaner with {BUNDLE_FILENAME} alone.

Each run syncs WaniKani data with updated_after when a prior cache exists
(assignments, subjects, review stats). Use --refresh-cache to force a full
re-download. Re-import the .apkg to add new notes; stable GUIDs update existing cards.

Each run appends a row to {RUN_HISTORY_FILENAME} with deck counts and which
decks were bundled into {BUNDLE_FILENAME}.

Filtered decks (WK::Daily Priority, etc.) cannot be bundled in .apkg files.
After importing, run Tools → WK Setup Filtered Decks in Anki using the add-on
in anki_addon/wk_filtered_decks (reads {FILTERED_DECKS_JSON}).

If templates still do not update after import:
  1. Tools → Manage Note Types → Cards — confirm CSS starts with WK template comment
  2. Re-import with "Always update" for the note type
  3. Last resort: delete notes in that deck and re-import (loses scheduling)
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
    print(f"  Leech note type: {NOTE_TYPE_NAMES['item']} · template {MODEL_TEMPLATE_VERSIONS['item']}")
    print(f"  Verb pair note type: {NOTE_TYPE_NAMES['pair']} · template {MODEL_TEMPLATE_VERSIONS['pair']}")
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
    reading_keywords: Sequence[ReadingKeywordEntry],
    kanji_radical_items: Sequence[dict],
    radical_items: Sequence[dict],
    current_level: int,
    next_level: int,
    pitch_index: Dict[Tuple[str, str], dict],
    review_index: Dict[int, dict],
) -> None:
    print("\nDRY RUN — no .apkg files will be written")
    print("=" * 60)
    wanted = {args.deck} if args.deck != "all" else {
        "leeches", "verb-pairs", "confusables", "phonetic-families",
        "pitch-leeches", "radicals", "reading-keywords", "kanji-radicals",
    }

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
            [
                f"{m['data'].get('characters') or '?'} → {reading} via {comp}"
                for comp, reading, members in phonetic_families
                for m in members
            ],
        )
    if "reading-keywords" in wanted:
        preview_deck_section(
            DECK_NAMES["reading-keywords"],
            [
                f"{entry.kana} → {entry.keyword} (uses={entry.uses}, {entry.consistency:.0%})"
                for entry in reading_keywords
            ],
        )
    if "kanji-radicals" in wanted:
        preview_deck_section(
            DECK_NAMES["kanji-radicals"],
            [
                f"{kanji['data'].get('characters') or '?'} [L{kanji['data'].get('level', '?')}] "
                f"{len(kanji['data'].get('component_subject_ids') or [])} radicals"
                for kanji in kanji_radical_items
            ],
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
    parser.add_argument("--deck", choices=[
        "leeches", "verb-pairs", "confusables", "phonetic-families",
        "pitch-leeches", "radicals", "reading-keywords", "kanji-radicals", "all",
    ], default="all")
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
    keisei_databases = ensure_keisei_databases(refresh=args.refresh_cache)
    if keisei_databases:
        print(
            "Keisei phonetic DB:",
            ", ".join(f"{key}={len(keisei_databases[key])}" for key in sorted(keisei_databases)),
        )
    leeches = find_leeches(subjects, indexes["assignments"], indexes["reviews"], args)
    verb_pairs = find_verb_pairs(vocab_items, args)
    confusables = find_confusable_groups(vocab_items, args)
    phonetic_families = find_phonetic_families(
        kanji_items,
        all_wk_kanji_subjects(subjects, args),
        keisei_databases.get("phonetic", {}),
        keisei_databases.get("kanji", {}),
        args,
    )
    started_kanji_ids = {item["id"] for item in kanji_items}
    all_kanji_by_char = kanji_by_char(all_wk_kanji_subjects(subjects, args))
    reading_keywords = build_reading_keyword_catalog(subjects)
    kanji_radical_items = find_kanji_radical_breakdown(kanji_items, radical_items, indexes["assignments"], args)
    print(f"Eligible vocab: {len(vocab_items)}")
    print(f"Eligible kanji: {len(kanji_items)}")
    print(f"Eligible radicals: {len(radical_items)}")
    print(f"Radical preview levels: current={current_level}, next={next_level}")
    print(f"Leeches: {len(leeches)}")
    print(f"Verb pairs: {len(verb_pairs)}")
    print(f"Confusable groups: {len(confusables)}")
    print(f"Phonetic families: {len(phonetic_families)} ({phonetic_drill_note_count(phonetic_families)} drill cards)")
    print(f"Reading keywords: {len(reading_keywords)}")
    print(f"Kanji radical breakdown: {len(kanji_radical_items)}")
    print(f"Pitch entries loaded: {len(pitch_index)}")
    wanted = wanted_decks(args)
    if args.dry_run:
        would_bundle = deck_names_for_run(
            wanted,
            radical_items=radical_items,
            leeches=leeches,
            verb_pairs=verb_pairs,
            confusables=confusables,
            phonetic_families=phonetic_families,
            reading_keywords=reading_keywords,
            kanji_radical_items=kanji_radical_items,
            pitch_index=pitch_index,
        )
        history_path = append_run_history(
            output_dir,
            build_run_history_row(
                args,
                user,
                dry_run=True,
                current_level=current_level,
                next_level=next_level,
                vocab_count=len(vocab_items),
                kanji_count=len(kanji_items),
                radical_count=len(radical_items),
                leeches=leeches,
                verb_pairs=verb_pairs,
                confusables=confusables,
                phonetic_families=phonetic_families,
                reading_keywords=reading_keywords,
                kanji_radical_items=kanji_radical_items,
                radical_items=radical_items,
                pitch_index=pitch_index,
                bundled_deck_names=would_bundle,
                bundled_in_wk_all=bool(would_bundle and not args.no_bundle),
            ),
        )
        print(f"Run history: {history_path}")
        print_preview_report(
            args,
            leeches=leeches,
            verb_pairs=verb_pairs,
            confusables=confusables,
            phonetic_families=phonetic_families,
            reading_keywords=reading_keywords,
            kanji_radical_items=kanji_radical_items,
            radical_items=radical_items,
            current_level=current_level,
            next_level=next_level,
            pitch_index=pitch_index,
            review_index=indexes["reviews"],
        )
        return
    created: List[Path] = []
    built_decks: List[genanki.Deck] = []
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
        path, deck = build_phonetic_family_deck(
            phonetic_families,
            keisei_databases.get("kanji", {}),
            started_kanji_ids,
            all_kanji_by_char,
            output_dir,
        )
        created.append(path)
        built_decks.append(deck)
    if "reading-keywords" in wanted and reading_keywords:
        path, deck = build_reading_keyword_deck(reading_keywords, output_dir)
        created.append(path)
        built_decks.append(deck)
    if "kanji-radicals" in wanted and kanji_radical_items:
        path, deck = build_kanji_radical_deck(
            kanji_radical_items,
            radical_index_by_id(subjects),
            indexes["assignments"],
            output_dir,
        )
        created.append(path)
        built_decks.append(deck)
    if "pitch-leeches" in wanted and leeches:
        maybe = build_pitch_leeches_deck(leeches, indexes, pitch_index, output_dir)
        if maybe:
            path, deck = maybe
            created.append(path)
            built_decks.append(deck)
    if not created:
        history_path = append_run_history(
            output_dir,
            build_run_history_row(
                args,
                user,
                dry_run=False,
                current_level=current_level,
                next_level=next_level,
                vocab_count=len(vocab_items),
                kanji_count=len(kanji_items),
                radical_count=len(radical_items),
                leeches=leeches,
                verb_pairs=verb_pairs,
                confusables=confusables,
                phonetic_families=phonetic_families,
                reading_keywords=reading_keywords,
                kanji_radical_items=kanji_radical_items,
                radical_items=radical_items,
                pitch_index=pitch_index,
                bundled_deck_names=[],
                bundled_in_wk_all=False,
            ),
        )
        print(f"Run history: {history_path}")
        print("No decks created. Try lowering filters, refreshing cache, or adding pitch data.", file=sys.stderr)
        sys.exit(1)
    bundle_path: Optional[Path] = None
    if built_decks and not args.no_bundle:
        bundle_path = output_dir / BUNDLE_FILENAME
        write_bundled_apkg(built_decks, bundle_path)
    settings_path = write_filtered_deck_suggestions(output_dir)
    filtered_json_path = write_filtered_decks_json(output_dir)
    instructions_path = write_import_instructions(output_dir)
    history_path = append_run_history(
        output_dir,
        build_run_history_row(
            args,
            user,
            dry_run=False,
            current_level=current_level,
            next_level=next_level,
            vocab_count=len(vocab_items),
            kanji_count=len(kanji_items),
            radical_count=len(radical_items),
            leeches=leeches,
            verb_pairs=verb_pairs,
            confusables=confusables,
            phonetic_families=phonetic_families,
            reading_keywords=reading_keywords,
            kanji_radical_items=kanji_radical_items,
            radical_items=radical_items,
            pitch_index=pitch_index,
            bundled_deck_names=[deck.name for deck in built_decks],
            bundled_in_wk_all=bool(bundle_path),
        ),
    )
    print("Created:")
    if bundle_path:
        print(f"  {bundle_path}  ← recommended import")
    for path in created:
        print(f"  {path}")
    print(f"  {settings_path}")
    print(f"  {filtered_json_path}")
    print(f"  {instructions_path}")
    print(f"  {history_path}")
    print_import_verification_help(bundle_path)


if __name__ == "__main__":
    main()
