#!/usr/bin/env python3
"""
wk_decks.py

Generate update-safe Anki decks from your WaniKani account.

Decks (default --deck all):
  - radicals: current level, all previous levels, next, and locked-next-level radicals
  - phonetic-families: per-kanji on'yomi drill via Keisei phonetic map
  - conjugations-verbs / conjugations-adjectives / conjugations-reverse
  - verb-types / adjective-types
  - vocab-cloze: reading cloze in WaniKani context sentences (Master+ by default)
  - grammar: JLPT grammar cloze from Hanabira open data (see grammar_decks.py)
  - tae-kim-exercises: Tae Kim book practice exercises (see tae_kim_exercise_decks.py)
  - dictation: native WK pronunciation audio → type the reading in kana (see dictation_decks.py)
  - all: all of the above

Legacy decks (removed from --deck all; code retained for one-off --deck leeches etc.):
  leeches, verb-pairs, confusables, reading-keywords, kanji-radicals, pitch-leeches

Install:
  pip install requests genanki

Basic use:
  export WANIKANI_API_TOKEN="your_token_here"
  python wk_decks.py --deck all --only-started

With pitch CSV:
  python wk_decks.py --deck all --only-started --pitch-csv pitch.csv

Preview without writing decks:
  python wk_decks.py --deck all --only-started --dry-run

Verify conjugation rules against curated fixtures and eligible vocab:
  python wk_decks.py --verify-conjugations-only --only-started
  python -m unittest tests.test_conjugations
  pytest tests/test_conjugations.py

Recommended weekly import (one file, all decks):
  python wk_decks.py --deck all --only-started
  # then import out/wk_all.apkg into Anki

Regenerate from wk_deck_config.json (grammar caps, deck list, etc.):
  python wk_decks.py --from-config
  # or: python wk_decks.py --config wk_deck_config.json
  # CLI flags override config; missing config file → built-in defaults

Vocabulary context cloze (reading production in WK sentences, Master+ default):
  python wk_decks.py --deck vocab-cloze --only-started
  # uses --vocab-cloze-min-srs 7 by default; run Tools → WK Apply Deck Options after import

Conjugation drills (type-in, Master+ default):
  python wk_decks.py --deck conjugations-verbs --only-started
  python wk_decks.py --deck conjugations-adjectives --only-started

With sentence audio (edge-tts; off by default for WK vocab, on for grammar/exercises — plays on card back):
  python wk_decks.py --deck vocab-cloze --only-started --sentence-audio
  python wk_decks.py --deck grammar --no-grammar-sentence-audio  # skip grammar TTS
  python wk_decks.py --deck tae-kim-exercises --grammar-max-tae-kim-lesson expressing-state-of-being

With Yomitan pitch dictionary zip/folder:
  python wk_decks.py --deck all --only-started --yomitan-dict ~/japanese-dicts/kanjium_pitch_accents.zip

Each run appends one row to out/wk_run_history.csv with deck counts and bundle contents.
"""

from __future__ import annotations

VERSION = "2.27.0"
BUILD_DATE = "2026-06-28"

import warnings

warnings.filterwarnings(
    "ignore",
    message="urllib3 v2 only supports OpenSSL",
)

import argparse
import asyncio
import csv
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

import genanki
import requests

from wk_scheduling import (
    WK_LOCKED_TAG,
    WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME,
    load_srs_stage_interval_days,
    patch_apkg_supplementary_suspend,
    patch_apkg_wk_scheduling,
    wk_subject_mature_at_import,
)

WK_API_BASE = "https://api.wanikani.com/v2"
WK_REVISION = "20170710"
WK_CLOUDFLARE_RETRY_WAIT_SECONDS = 5
WK_CLOUDFLARE_MAX_RETRIES = 2
CACHE_DIR = Path(".wk_cache")
CACHE_MAX_AGE_HOURS = 24
OUTPUT_DIR = Path("out")
WK_DECK_CONFIG_FILENAME = "wk_deck_config.json"
DEFAULT_GENERATE_DECKS = (
    "phonetic-families",
    "radicals",
    "conjugations-verbs",
    "conjugations-adjectives",
    "verb-types",
    "vocab-cloze",
    "dictation",
    "grammar",
    "tae-kim-exercises",
)

# Keisei phonetic-semantic DB (GPL-3.0, mwil/wanikani-userscripts).
# Pinned commit for stable raw JSON URLs; auto-downloaded into .wk_cache/keisei/.
KEISEI_DB_COMMIT = "8ee517737d604f1df0ff103a33b69f1f07218815"
KEISEI_DB_BASE = (
    f"https://raw.githubusercontent.com/mwil/wanikani-userscripts/{KEISEI_DB_COMMIT}"
    "/wanikani-phonetic-compounds/db"
)
KEISEI_CACHE_DIR = CACHE_DIR / "keisei"
RADICAL_MEDIA_CACHE_DIR = CACHE_DIR / "radical_media"
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
# WaniKani assignment SRS stages (API srs_stage): 1 Apprentice I … 9 Burned.
WK_SRS_STAGE_APPRENTICE_1 = 1
WK_SRS_STAGE_GURU_1 = 5
WK_SRS_STAGE_MASTER = 7
PHONETIC_FAMILIES_MIN_SRS = WK_SRS_STAGE_APPRENTICE_1
VOCAB_CLOZE_DEFAULT_MIN_SRS = WK_SRS_STAGE_MASTER
CONJUGATION_DEFAULT_MIN_SRS = WK_SRS_STAGE_MASTER
CLOZE_BLANK_DISPLAY = "＿＿＿"
SENTENCE_AUDIO_CACHE_DIR = CACHE_DIR / "sentence_audio"
DEFAULT_SENTENCE_AUDIO_VOICE = "ja-JP-NanamiNeural"
VOCAB_CLOZE_MEDIA_SUBDIR = "media/vocab_cloze"
WK_SHARED_MEDIA_SUBDIR = "media/shared"
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
READING_MNEMONIC_WORD_BEFORE_KANA_RE = re.compile(
    r"([a-z][a-z'-]*)\s*[\(（]([ぁ-んー]+)[\)）]",
    re.IGNORECASE,
)
WK_PAREN_READING_RE = re.compile(
    r"([\u4e00-\u9fff々〆ヵヶ]+)[（(]([ぁ-んーゔゕゖ]+)[）)]"
)
# WK sometimes defers kanji early (e.g. ふじ山) before teaching the full form (富士山).
WK_KANA_PREFIX_KANJI_SUFFIX_RE = re.compile(r"^([ぁ-んー]+)([\u4e00-\u9fff]+)$")
VOCAB_TYPE_HONORIFIC_PREFIXES = ("お", "ご", "御")

RADICAL_IMAGE_STYLE_PREFERENCE: Tuple[str, ...] = (
    "128px",
    "256px",
    "512px",
    "64px",
    "1024px",
    "original",
)
WANIKANI_CDN_SUBJECT_IMAGE_URL = (
    "https://cdn.wanikani.com/subjects/images/{subject_id}-{slug}-large.png"
)

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
    "conjugations-verbs": 2059400119,
    "verb-types": 2059400120,
    "adjective-types": 2059400121,
    "vocab-cloze": 2059400122,
    "conjugations-reverse": 2059400123,
    "conjugations-adjectives": 2059400124,
    "dictation": 2059400127,
    "core-radical": 2059400128,
    "core-kanji": 2059400129,
    "core-vocabulary": 2059400130,
}

MODEL_IDS = {
    "item": 1865429012,
    "pair": 1865429013,
    "family": 1865429014,
    "radical": 1865429015,
    "reading_keyword": 1865429016,
    "kanji_radical": 1865429017,
    "phonetic_drill": 1865429018,
    "conjugation": 1865429019,
    "word_class": 1865429020,
    "vocab_cloze": 1865429021,
    "conjugation_reverse": 1865429022,
    "dictation": 1865429024,
    "core_radical": 1865429025,
    "core_item": 1865429026,
}

# Bump the relevant key when that note type's templates/CSS change.
# Anki import uses model.mod; these map to stable epoch seconds (see template_mod_epoch).
MODEL_TEMPLATE_VERSIONS = {
    "item": "v7",
    "pair": "v2",
    "family": "v1",
    "radical": "v5",
    "reading_keyword": "v3",
    "kanji_radical": "v2",
    "phonetic_drill": "v5",
    "conjugation": "v4",
    "word_class": "v2",
    "vocab_cloze": "v7",
    "conjugation_reverse": "v4",
    "grammar_cloze": "v4",
    "dictation": "v3",
    "core_radical": "v2",
    "core_item": "v5",
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
    "conjugation": 7,
    "word_class": 8,
    "vocab_cloze": 9,
    "conjugation_reverse": 10,
    "grammar_cloze": 11,
    "dictation": 12,
    "core_radical": 13,
    "core_item": 14,
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
    "conjugation": "WK Update-Safe Conjugation",
    "word_class": "WK Update-Safe Word Class",
    "vocab_cloze": "WK Update-Safe Vocab Cloze",
    "grammar_cloze": "WK Update-Safe Grammar Cloze",
    "conjugation_reverse": "WK Update-Safe Conjugation Reverse",
    "dictation": "WK Update-Safe Dictation",
    "core_radical": "WK Core Radical",
    "core_item": "WK Core Item",
}

BUNDLE_FILENAME = "wk_all.apkg"
RUN_HISTORY_FILENAME = "wk_run_history.csv"
FILTERED_DECKS_JSON = "anki_filtered_decks.json"
DECK_OPTIONS_JSON = "anki_deck_options.json"
WK_FSRS_PRESET_NAME = "WK FSRS"
WK_FSRS_DECK_CONFIG_ID = 2059400100
WK_FSRS_DEFAULT_RETENTION = 0.9
WK_FSRS_DEFAULT_NEW_PER_DAY = 15
WK_FSRS_DEFAULT_REVIEWS_PER_DAY = 200
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
    "radical_level_locked_next",
    "leeches",
    "verb_pairs",
    "confusables",
    "phonetic_families",
    "reading_keywords",
    "kanji_radical_breakdown",
    "conjugation_verb_drills",
    "conjugation_adjective_drills",
    "conjugation_reverse_drills",
    "verb_type_cards",
    "adjective_type_cards",
    "vocab_cloze",
    "dictation_items",
    "grammar_cards",
    "tae_kim_exercise_cards",
    "pitch_entries",
    "pitch_leeches",
    "bundled_in_wk_all",
    "bundled_decks",
]
FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS = 10
# Core daily queues must reschedule (FSRS updates on home deck). If reschedule is off,
# Good/Easy show "(end)" and reviews do not stick.
FILTERED_DECK_RESCHEDULE_DEFAULT = True

FILTERED_DECK_DEFINITIONS = [
    {
        "name": "WK::Core Radicals",
        "search": 'deck:"WaniKani Core · Radicals" -is:suspended',
        "limit": 20,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Core Kanji",
        "search": 'deck:"WaniKani Core · Kanji" -is:suspended',
        "limit": 25,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Core Vocabulary",
        "search": 'deck:"WaniKani Core · Vocabulary" -is:suspended',
        "limit": 25,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Tae Kim · Grammar Vocab",
        "search": 'tag:wk-core tag:tk-grammar-vocab -is:suspended',
        "limit": 25,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Tae Kim · Grammar Prereq Kanji",
        "search": 'tag:wk-core tag:tk-grammar-prereq tag:kanji -is:suspended',
        "limit": 25,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Tae Kim · Grammar Prereq Radicals",
        "search": 'tag:wk-core tag:tk-grammar-prereq tag:radical -is:suspended',
        "limit": 20,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::N5 · Kanji & Vocab",
        "search": 'tag:wk-core tag:jlpt-n5-vocab -is:suspended',
        "limit": 25,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::N5 · Prereq Kanji",
        "search": 'tag:wk-core tag:jlpt-n5-prereq tag:kanji -is:suspended',
        "limit": 25,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::N5 · Prereq Radicals",
        "search": 'tag:wk-core tag:jlpt-n5-prereq tag:radical -is:suspended',
        "limit": 20,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Vocab Context",
        "search": 'deck:"WaniKani Vocabulary Context" -is:suspended',
        "limit": 25,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Dictation",
        "search": 'deck:"WaniKani Dictation" -is:suspended',
        "limit": 25,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Grammar",
        "search": 'deck:"Japanese Grammar Context" tag:tk-lesson-basic-expressing-state-of-being OR tag:tk-lesson-basic-introduction-to-particles OR tag:tk-lesson-basic-adjectives -is:suspended',
        "limit": 25,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Grammar Exercises",
        "search": 'deck:"Japanese Grammar Exercises" tag:tae-kim-exercise -is:suspended',
        "limit": 25,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    },
    {
        "name": "WK::Phonetic Families",
        "search": 'deck:"WaniKani Phonetic Families" tag:priority-low -is:suspended',
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
    "conjugations-verbs": "WaniKani Verb Conjugation Practice",
    "conjugations-adjectives": "WaniKani Adjective Conjugation Practice",
    "conjugations-reverse": "WaniKani Verb Conjugation Reverse",
    "verb-types": "WaniKani Verb Type Practice",
    "adjective-types": "WaniKani Adjective Type Practice",
    "vocab-cloze": "WaniKani Vocabulary Context",
    "dictation": "WaniKani Dictation",
    "grammar": "Japanese Grammar Context",
    "tae-kim-exercises": "Japanese Grammar Exercises",
    "core-radical": "WaniKani Core · Radicals",
    "core-kanji": "WaniKani Core · Kanji",
    "core-vocabulary": "WaniKani Core · Vocabulary",
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

# WK mnemonic tag highlights — append to note types that render wk_mnemonic_html().
WK_MNEMONIC_CSS = """
.wk-mnemonic .wk-mnemonic-radical { color: #4da6ff; font-weight: 600; }
.wk-mnemonic .wk-mnemonic-kanji { color: #ff6b6b; font-weight: 600; }
.wk-mnemonic .wk-mnemonic-vocabulary { color: #ff6b6b; font-weight: 600; }
.wk-mnemonic .wk-mnemonic-reading { color: #c77dff; font-weight: 600; }
.wk-mnemonic .jp { font-family: inherit; }
.nightMode .wk-mnemonic .wk-mnemonic-radical,
.card.nightMode .wk-mnemonic .wk-mnemonic-radical,
.night_mode .wk-mnemonic .wk-mnemonic-radical { color: #7ec8ff; }
.nightMode .wk-mnemonic .wk-mnemonic-kanji,
.card.nightMode .wk-mnemonic .wk-mnemonic-kanji,
.night_mode .wk-mnemonic .wk-mnemonic-kanji,
.nightMode .wk-mnemonic .wk-mnemonic-vocabulary,
.card.nightMode .wk-mnemonic .wk-mnemonic-vocabulary,
.night_mode .wk-mnemonic .wk-mnemonic-vocabulary { color: #ff9a9a; }
.nightMode .wk-mnemonic .wk-mnemonic-reading,
.card.nightMode .wk-mnemonic .wk-mnemonic-reading,
.night_mode .wk-mnemonic .wk-mnemonic-reading { color: #ddb0ff; }
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
    return {
        "Authorization": f"Bearer {token.strip()}",
        "Wanikani-Revision": WK_REVISION,
        "Accept": "application/json",
        "User-Agent": f"wk-decks/{VERSION} (+https://www.wanikani.com; personal-deck-generator)",
    }


def wk_is_cloudflare_block(response: requests.Response) -> bool:
    if response.status_code not in (403, 503):
        return False
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        return False
    snippet = (response.text or "")[:500].lower()
    return (
        "just a moment" in snippet
        or "cloudflare" in snippet
        or snippet.lstrip().startswith("<!doctype html")
    )


def wk_warn_use_cached_api_data(collection: str, response: requests.Response, cached_count: int) -> None:
    if wk_is_cloudflare_block(response):
        reason = "Cloudflare blocked the WaniKani API request"
    else:
        reason = f"WaniKani returned {response.status_code} for {collection}"
    print(f"Warning: {reason}; using cached {cached_count} items.", file=sys.stderr)
    print(
        "  Try again in a few minutes. Use --refresh-cache when the API is reachable.",
        file=sys.stderr,
    )


def wk_http_get(
    url: str,
    *,
    params: Optional[dict] = None,
    context: str = "WaniKani API",
) -> requests.Response:
    response: Optional[requests.Response] = None
    for attempt in range(WK_CLOUDFLARE_MAX_RETRIES + 1):
        response = requests.get(url, headers=wk_headers(), params=params, timeout=45)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "5"))
            print(f"Rate limited by WaniKani. Waiting {retry_after}s...")
            time.sleep(retry_after)
            continue
        if wk_is_cloudflare_block(response) and attempt < WK_CLOUDFLARE_MAX_RETRIES:
            wait = WK_CLOUDFLARE_RETRY_WAIT_SECONDS * (attempt + 1)
            print(f"Cloudflare challenge on {context}; retrying in {wait}s...")
            time.sleep(wait)
            continue
        return response
    assert response is not None
    return response


def wk_get_all_with_cache_fallback(
    collection: str,
    params: Optional[dict],
    cached_items: Optional[Sequence[dict]],
) -> Tuple[List[dict], bool]:
    """Return (items, used_cache). used_cache is True when cached_items were returned."""
    try:
        return wk_get_all(collection, params=params), False
    except requests.HTTPError as exc:
        if (
            cached_items is not None
            and exc.response is not None
            and exc.response.status_code == 403
        ):
            wk_warn_use_cached_api_data(collection, exc.response, len(cached_items))
            return list(cached_items), True
        raise


def wk_get_resource(resource: str) -> dict:
    response = wk_http_get(f"{WK_API_BASE}/{resource}", context=resource)
    wk_raise_for_status(response, context=resource)
    return response.json()


def wk_response_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
        for key in ("error", "message", "code"):
            value = payload.get(key)
            if value:
                return str(value)
    except ValueError:
        pass
    text = (response.text or "").strip()
    return text[:240] if text else response.reason or "Unknown error"


def wk_raise_for_status(response: requests.Response, *, context: str) -> None:
    if response.ok:
        return
    detail = wk_response_error_detail(response)
    message = f"{response.status_code} {response.reason} for {context}: {detail}"
    raise requests.HTTPError(message, response=response)


def wk_get_all(collection: str, params: Optional[dict] = None) -> List[dict]:
    url = f"{WK_API_BASE}/{collection}"
    out: List[dict] = []
    page = 1
    while url:
        response = wk_http_get(url, params=params, context=f"{collection} (page {page})")
        wk_raise_for_status(response, context=f"{collection} (page {page})")
        payload = response.json()
        out.extend(payload.get("data", []))
        url = payload.get("pages", {}).get("next_url")
        params = None
        page += 1
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


def build_core_assignment_params(args: argparse.Namespace) -> dict:
    """Full assignment index for core SRS import (no started/SRS filters)."""
    params: dict = {"subject_types": "radical,kanji,vocabulary"}
    if args.max_level < 60:
        params["levels"] = ",".join(str(level) for level in range(1, args.max_level + 1))
    return params


def get_cached_user(refresh: bool = False) -> dict:
    path = CACHE_DIR / "user.json"
    cached = load_json_cache(path, CACHE_MAX_AGE_HOURS, refresh=refresh)
    if cached is not None:
        print(f"Using cached user: {path}")
        return cached
    print("Downloading WaniKani user...")
    try:
        payload = wk_get_resource("user")
    except requests.HTTPError as exc:
        if refresh and path.exists() and exc.response is not None and exc.response.status_code == 403:
            with path.open("r", encoding="utf-8") as f:
                cached = json.load(f)
            wk_warn_use_cached_api_data("user", exc.response, 1)
            return cached
        raise
    user = payload["data"]
    save_json_cache(path, user)
    print(f"Saved user cache: {path}")
    return user


def get_cached_spaced_repetition_systems(*, refresh: bool = False) -> List[dict]:
    """Fetch/cache WK /v2/spaced_repetition_systems for SRS stage interval mapping."""
    path = CACHE_DIR / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME
    cached = load_json_cache(path, CACHE_MAX_AGE_HOURS, refresh=refresh)
    if cached is not None and not refresh:
        if isinstance(cached, dict) and isinstance(cached.get("items"), list):
            print(f"Using cached spaced_repetition_systems: {path}")
            return cached["items"]
        if isinstance(cached, list):
            print(f"Using cached spaced_repetition_systems: {path}")
            return cached
    print("Downloading WaniKani spaced_repetition_systems...")
    try:
        items = wk_get_all("spaced_repetition_systems")
    except requests.HTTPError as exc:
        if refresh and path.exists() and exc.response is not None and exc.response.status_code == 403:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            items = envelope.get("items") if isinstance(envelope, dict) else envelope
            if isinstance(items, list):
                wk_warn_use_cached_api_data("spaced_repetition_systems", exc.response, len(items))
                return items
        raise
    save_cache_envelope(path, items)
    print(f"Saved spaced_repetition_systems cache: {path} ({len(items)} items)")
    return items


def get_cached_collection(
    collection: str,
    *,
    params: Optional[dict] = None,
    params_key: str = "all",
    refresh: bool = False,
) -> List[dict]:
    path = cache_path(collection, params_key)
    envelope, is_stale = load_cache_envelope(path, CACHE_MAX_AGE_HOURS, refresh=refresh)
    cached_items = envelope["items"] if envelope else load_cache_items_only(collection, params_key)

    if refresh or envelope is None:
        print(f"Downloading WaniKani {collection}...")
        items, used_cache = wk_get_all_with_cache_fallback(collection, params, cached_items)
        if used_cache:
            return items
        save_cache_envelope(path, items)
        print(f"Saved {collection} cache: {path} ({len(items)} items)")
        return items

    if envelope.get("synced_at"):
        print(f"Syncing {collection} since {envelope['synced_at']}...")
        sync_params = dict(params or {})
        sync_params["updated_after"] = envelope["synced_at"]
        delta, used_cache = wk_get_all_with_cache_fallback(
            collection,
            sync_params,
            envelope["items"],
        )
        if used_cache:
            return delta
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
    items, used_cache = wk_get_all_with_cache_fallback(collection, params, envelope["items"])
    if used_cache:
        return items
    save_cache_envelope(path, items)
    print(f"Saved {collection} cache: {path} ({len(items)} items)")
    return items


def load_cache_items_only(collection: str, params_key: str = "all") -> Optional[List[dict]]:
    """Read cached collection items without contacting the WaniKani API."""
    path = cache_path(collection, params_key)
    if not path.exists():
        return None
    envelope = json.loads(path.read_text(encoding="utf-8"))
    items = envelope.get("items")
    return items if isinstance(items, list) else None


def fetch_review_statistics(
    subject_ids: Sequence[int],
    *,
    updated_after: Optional[str] = None,
    cached_items: Optional[Sequence[dict]] = None,
) -> Tuple[List[dict], bool]:
    if updated_after:
        return wk_get_all_with_cache_fallback(
            "review_statistics",
            {
                "subject_types": "kanji,vocabulary",
                "updated_after": updated_after,
            },
            cached_items,
        )

    if not subject_ids:
        return wk_get_all_with_cache_fallback(
            "review_statistics",
            {"subject_types": "kanji,vocabulary"},
            cached_items,
        )

    if cached_items is not None:
        try:
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
            return merge_records([], out), False
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 403:
                wk_warn_use_cached_api_data("review_statistics", exc.response, len(cached_items))
                return list(cached_items), True
            raise

    out = []
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
    return merge_records([], out), False


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
        cached_items = load_cache_items_only("review_statistics", params_key) if refresh else None
        items, used_cache = fetch_review_statistics(subject_ids, cached_items=cached_items)
        if used_cache:
            return items
        save_cache_envelope(path, items)
        print(f"Saved review_statistics cache: {path} ({len(items)} items)")
        return items

    if envelope.get("synced_at"):
        print(f"Syncing review_statistics since {envelope['synced_at']}...")
        delta, used_cache = fetch_review_statistics(
            subject_ids,
            updated_after=envelope["synced_at"],
            cached_items=envelope["items"],
        )
        if used_cache:
            return delta
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
    items, used_cache = fetch_review_statistics(subject_ids, cached_items=envelope["items"])
    if used_cache:
        return items
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


def attach_deck_media(package: genanki.Package, decks: Sequence[genanki.Deck]) -> None:
    media_paths: List[str] = []
    seen: Set[str] = set()
    for deck in decks:
        for media_path in getattr(deck, "wk_media_files", []) or []:
            path_str = str(media_path)
            if path_str not in seen:
                seen.add(path_str)
                media_paths.append(path_str)
    if media_paths:
        package.media_files = media_paths


def merge_package_media_files(
    package: genanki.Package,
    media_files: Optional[Sequence[str]],
) -> None:
    if not media_files:
        return
    existing = list(package.media_files or [])
    seen = set(existing)
    for media_path in media_files:
        path_str = str(media_path)
        if path_str not in seen:
            seen.add(path_str)
            existing.append(path_str)
    package.media_files = existing


def write_bundled_apkg(
    decks: Sequence[genanki.Deck],
    path: Path,
    *,
    media_files: Optional[Sequence[str]] = None,
) -> None:
    if not decks:
        return
    all_models: List[genanki.Model] = []
    for deck in decks:
        all_models.extend(deck.models.values())
    package = genanki.Package(decks[0])
    package.decks = list(decks)
    attach_deck_media(package, decks)
    merge_package_media_files(package, media_files)
    package.write_to_file(str(path), timestamp=package_write_timestamp(all_models))
    patch_apkg_deck_options(path)
    maybe_patch_apkg_wk_scheduling(path, decks)
    patch_apkg_supplementary_suspend(path)


# Default FSRS-5 weights shipped with Anki 23.10+ (used when preset is created on import).
WK_FSRS_DEFAULT_WEIGHTS: Tuple[float, ...] = (
    0.40255,
    1.18385,
    3.173,
    15.69105,
    7.1949,
    0.5345,
    1.4604,
    0.0046,
    1.54575,
    0.1192,
    1.01925,
    1.9395,
    0.11,
    0.29605,
    2.2698,
    0.2315,
    2.9898,
    0.51655,
    0.662,
)


def wk_fsrs_dconf_entry() -> dict:
    return {
        "autoplay": True,
        "id": WK_FSRS_DECK_CONFIG_ID,
        "lapse": {
            "delays": [10],
            "leechAction": 1,
            "leechFails": 8,
            "minInt": 1,
            "mult": 0,
        },
        "maxTaken": 60,
        "mod": 0,
        "name": WK_FSRS_PRESET_NAME,
        "new": {
            "bury": True,
            "delays": [1, 10],
            "initialFactor": 2500,
            "ints": [1, 4, 0],
            "order": 1,
            "perDay": WK_FSRS_DEFAULT_NEW_PER_DAY,
            "separate": True,
        },
        "replayq": True,
        "rev": {
            "bury": True,
            "ease4": 1.3,
            "fuzz": 0.05,
            "ivlFct": 1,
            "maxIvl": 36500,
            "minSpace": 1,
            "perDay": WK_FSRS_DEFAULT_REVIEWS_PER_DAY,
        },
        "timer": 0,
        "usn": 0,
        "desiredRetention": WK_FSRS_DEFAULT_RETENTION,
        "w": list(WK_FSRS_DEFAULT_WEIGHTS),
    }


def patch_apkg_deck_options(apkg_path: Path) -> None:
    """Assign every deck in an .apkg to the WK FSRS preset (for Anki import)."""
    apkg_path = Path(apkg_path)
    if not apkg_path.exists():
        return

    with zipfile.ZipFile(apkg_path, "r") as archive:
        if "collection.anki2" not in archive.namelist():
            return
        db_bytes = archive.read("collection.anki2")
        other_entries = {
            name: archive.read(name)
            for name in archive.namelist()
            if name != "collection.anki2"
        }

    with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as tmp_db:
        tmp_db.write(db_bytes)
        tmp_db_path = tmp_db.name

    try:
        conn = sqlite3.connect(tmp_db_path)
        decks_str, dconf_str = conn.execute("SELECT decks, dconf FROM col").fetchone()
        decks = json.loads(decks_str)
        dconf = json.loads(dconf_str)
        dconf[str(WK_FSRS_DECK_CONFIG_ID)] = wk_fsrs_dconf_entry()
        for deck in decks.values():
            deck["conf"] = WK_FSRS_DECK_CONFIG_ID
        conn.execute(
            "UPDATE col SET decks = ?, dconf = ?",
            (json.dumps(decks), json.dumps(dconf)),
        )
        conn.commit()
        conn.close()

        patched_bytes = Path(tmp_db_path).read_bytes()
        tmp_apkg = apkg_path.with_suffix(".patching.apkg")
        with zipfile.ZipFile(tmp_apkg, "w", compression=zipfile.ZIP_DEFLATED) as outzip:
            outzip.writestr("collection.anki2", patched_bytes)
            for name, payload in other_entries.items():
                outzip.writestr(name, payload)
        tmp_apkg.replace(apkg_path)
    finally:
        Path(tmp_db_path).unlink(missing_ok=True)


def collect_deck_schedule_specs(decks: Sequence[genanki.Deck]) -> Dict[str, object]:
    merged: Dict[str, object] = {}
    for deck in decks:
        specs = getattr(deck, "wk_schedule_specs", None) or {}
        merged.update(specs)
    return merged


def maybe_patch_apkg_wk_scheduling(apkg_path: Path, decks: Sequence[genanki.Deck]) -> int:
    specs = collect_deck_schedule_specs(decks)
    if not specs:
        return 0
    interval_map = load_srs_stage_interval_days(CACHE_DIR / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME)
    return patch_apkg_wk_scheduling(apkg_path, specs, interval_map=interval_map)


def write_apkg(deck: genanki.Deck, path: Path, *, media_files: Optional[Sequence[str]] = None) -> None:
    models = list(deck.models.values())
    package = genanki.Package(deck)
    attach_deck_media(package, [deck])
    merge_package_media_files(package, media_files)
    package.write_to_file(str(path), timestamp=package_write_timestamp(models))
    patch_apkg_deck_options(path)
    maybe_patch_apkg_wk_scheduling(path, [deck])
    patch_apkg_supplementary_suspend(path)


def subject_is_hidden(subject: dict) -> bool:
    """True when WK retired the subject (hidden_at set on API subject data)."""
    return bool(subject.get("data", {}).get("hidden_at"))


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


WK_MNEMONIC_TAG_OPEN_RE = re.compile(
    r"<(radical|kanji|vocabulary|reading|em|i|ja)>",
    re.IGNORECASE,
)

WK_MNEMONIC_SEMANTIC_CLASS = {
    "radical": "wk-mnemonic-radical",
    "kanji": "wk-mnemonic-kanji",
    "vocabulary": "wk-mnemonic-vocabulary",
    "reading": "wk-mnemonic-reading",
}


def _wk_mnemonic_fragment(text: str) -> str:
    match = WK_MNEMONIC_TAG_OPEN_RE.search(text)
    if not match:
        return html.escape(text)
    tag = match.group(1).lower()
    before = html.escape(text[: match.start()])
    close_tag = f"</{tag}>"
    close_at = text.lower().find(close_tag, match.end())
    if close_at == -1:
        return html.escape(text)
    inner = _wk_mnemonic_fragment(text[match.end() : close_at])
    rest = _wk_mnemonic_fragment(text[close_at + len(close_tag) :])
    if tag in WK_MNEMONIC_SEMANTIC_CLASS:
        wrapped = f"<span class='{WK_MNEMONIC_SEMANTIC_CLASS[tag]}'>{inner}</span>"
    elif tag == "ja":
        wrapped = f"<span class='jp'>{inner}</span>"
    else:
        wrapped = f"<{tag}>{inner}</{tag}>"
    return before + wrapped + rest


def wk_mnemonic_html(raw: Optional[str]) -> str:
    """Render WK meaning/reading mnemonic with radical (blue) and kanji/vocab (red) highlights."""
    if not raw or not str(raw).strip():
        return ""
    return f"<span class='wk-mnemonic'>{_wk_mnemonic_fragment(str(raw).strip())}</span>"


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


def supplementary_min_srs(args: argparse.Namespace, deck_min_srs: int) -> int:
    """Return 0 to include all eligible subjects when import-time gating replaces build-time SRS filter."""
    return 0 if getattr(args, "no_wk_progress_filter", False) else deck_min_srs


def supplementary_import_tags(
    subject: dict,
    assignment_index: Dict[int, dict],
    *,
    interval_map: Optional[Mapping[int, int]] = None,
) -> List[str]:
    """Tags for supplementary notes; adds wk-locked when linked subject is not mature at import."""
    stage = srs_stage(subject, assignment_index)
    tags: List[str] = []
    if not wk_subject_mature_at_import(stage, interval_map=interval_map):
        tags.append(WK_LOCKED_TAG)
    return tags


def all_vocab_subjects(subjects: Sequence[dict], args: argparse.Namespace) -> List[dict]:
    return [
        subject
        for subject in subjects
        if subject.get("object") == "vocabulary"
        and not subject_is_hidden(subject)
        and int(subject["data"].get("level", 999)) <= args.max_level
    ]


def is_unlocked(subject: dict, assignment_index: Dict[int, dict]) -> bool:
    assignment = assignment_index.get(subject["id"])
    return bool(assignment and assignment["data"].get("unlocked_at"))


def is_started(subject: dict, assignment_index: Dict[int, dict]) -> bool:
    assignment = assignment_index.get(subject["id"])
    return bool(assignment and assignment["data"].get("started_at"))


def is_burned(subject: dict, assignment_index: Dict[int, dict]) -> bool:
    assignment = assignment_index.get(subject["id"])
    return bool(assignment and assignment["data"].get("burned_at"))


def passes_progress_filter(
    subject: dict,
    assignment_index: Dict[int, dict],
    args: argparse.Namespace,
    *,
    min_srs: Optional[int] = None,
) -> bool:
    if subject["data"].get("level", 999) > args.max_level:
        return False
    if args.only_unlocked and not is_unlocked(subject, assignment_index):
        return False
    if getattr(args, "no_wk_progress_filter", False):
        if args.only_burned and not is_burned(subject, assignment_index):
            return False
        return True
    if args.only_started and not is_started(subject, assignment_index):
        return False
    if args.only_burned and not is_burned(subject, assignment_index):
        return False
    srs_floor = args.min_srs if min_srs is None else min_srs
    return srs_stage(subject, assignment_index) >= srs_floor


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


def canonical_reading_keyword(keyword: str) -> str:
    """Collapse plural/possessive variants so eagle/eagles/eagle's count together."""
    kw = keyword.strip().lower()
    if not kw:
        return kw
    if kw.endswith("'s") and len(kw) > 3:
        kw = kw[:-2]
    if len(kw) > 4 and kw.endswith("s") and not kw.endswith(("ss", "us", "is", "as", "os")):
        kw = kw[:-1]
    return kw


# WK <reading> tag shorthands when the story word is predictable and in the mnemonic text.
WK_READING_TAG_HINTS: Dict[str, str] = {
    "ea": "eagle",
    "shee": "sheep",
}


def expand_reading_keyword_from_mnemonic(tag_keyword: str, kana: str, plain_mnemonic: str) -> str:
    """Prefer full mnemonic words (sheep) over tag shorthand (shee) from WK HTML."""
    if not tag_keyword or not kana:
        return tag_keyword
    plain_lower = plain_mnemonic.lower()
    best: Optional[str] = None
    for match in READING_MNEMONIC_WORD_BEFORE_KANA_RE.finditer(plain_mnemonic):
        if match.group(2) != kana:
            continue
        word = normalize_reading_keyword(match.group(1))
        if word.startswith(tag_keyword) or len(word) > len(tag_keyword):
            if not best or len(word) > len(best):
                best = word
    if best and len(best) >= len(tag_keyword):
        return canonical_reading_keyword(best)
    prefix_matches = [
        normalize_reading_keyword(candidate)
        for candidate in re.findall(
            rf"\b({re.escape(tag_keyword)}[a-z'-]*)",
            plain_mnemonic,
            flags=re.IGNORECASE,
        )
    ]
    if prefix_matches:
        return canonical_reading_keyword(max(prefix_matches, key=len))
    hint = WK_READING_TAG_HINTS.get(tag_keyword)
    if hint and hint in plain_lower:
        return hint
    return canonical_reading_keyword(tag_keyword)


def primary_reading_list(subject: dict) -> List[str]:
    readings = subject["data"].get("readings") or []
    primary = [r["reading"] for r in readings if r.get("primary") or r.get("accepted_answer")]
    return primary or [r["reading"] for r in readings]


def extract_reading_mnemonic_pairs(subject: dict) -> List[Tuple[str, str]]:
    mnemonic = subject["data"].get("reading_mnemonic") or ""
    if not mnemonic:
        return []

    plain_mnemonic = strip_html(mnemonic)
    pairs: List[Tuple[str, str]] = []
    for match in READING_MNEMONIC_PAIR_RE.finditer(mnemonic):
        keyword = normalize_reading_keyword(match.group(1))
        kana = (match.group(2) or match.group(3) or "").strip()
        if keyword and kana:
            pairs.append((kana, expand_reading_keyword_from_mnemonic(keyword, kana, plain_mnemonic)))

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
        return [
            (kana.strip(), expand_reading_keyword_from_mnemonic(keyword, kana.strip(), plain_mnemonic))
            for kana, keyword in zip(kana_in_paren, tags)
            if kana and keyword
        ]
    if len(tags) == 1 and len(kana_in_paren) == 1:
        kana = kana_in_paren[0].strip()
        return [(kana, expand_reading_keyword_from_mnemonic(tags[0], kana, plain_mnemonic))]
    primary = primary_reading_list(subject)
    if len(tags) == 1 and primary:
        kana = primary[0]
        return [(kana, expand_reading_keyword_from_mnemonic(tags[0], kana, plain_mnemonic))]
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
            keyword = canonical_reading_keyword(keyword)
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


def _kanji_char_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def _vocab_type_honorific_prefix(prefix: str) -> bool:
    return any(prefix.startswith(honorific) for honorific in VOCAB_TYPE_HONORIFIC_PREFIXES)


def build_vocab_cloze_reading_index(vocab_items: Sequence[dict]) -> Dict[str, List[dict]]:
    """Index vocabulary by primary reading for WK full-form lookups."""
    index: Dict[str, List[dict]] = {}
    for vocab in vocab_items:
        if vocab.get("object") != "vocabulary":
            continue
        reading = first_reading(vocab)
        if reading:
            index.setdefault(reading, []).append(vocab)
    return index


def vocab_cloze_type_expression(vocab: dict, reading_index: Dict[str, List[dict]]) -> str:
    """Return the kanji-production answer for type-in; may differ from WK's early spelling."""
    expr = (vocab["data"].get("characters") or "").strip()
    if not expr:
        return expr

    match = WK_KANA_PREFIX_KANJI_SUFFIX_RE.match(expr)
    if not match:
        return expr

    prefix, suffix = match.group(1), match.group(2)
    if _vocab_type_honorific_prefix(prefix):
        return expr

    reading = first_reading(vocab)
    best_expr = expr
    best_kanji = _kanji_char_count(expr)
    for alt_vocab in reading_index.get(reading, ()):
        if alt_vocab["id"] == vocab["id"]:
            continue
        alt_expr = (alt_vocab["data"].get("characters") or "").strip()
        if not alt_expr.endswith(suffix):
            continue
        alt_kanji = _kanji_char_count(alt_expr)
        if alt_kanji > best_kanji:
            best_expr = alt_expr
            best_kanji = alt_kanji
    return best_expr


def vocab_cloze_blank_targets(vocab: dict) -> List[str]:
    """Return expression/reading strings to match in a sentence, longest first."""
    data = vocab["data"]
    chars = (data.get("characters") or "").strip()
    targets: List[str] = []
    if chars:
        targets.append(chars)
        if chars.endswith("する") and len(chars) > 2:
            targets.append(chars[:-2])
    reading = first_reading(vocab)
    if reading:
        targets.append(reading)
    deduped = sorted({target for target in targets if target}, key=len, reverse=True)
    return deduped


def blank_target_in_sentence(sentence: str, targets: Sequence[str]) -> Optional[Tuple[str, str]]:
    """Replace the first matching target with a blank. Returns (cloze, full) or None."""
    plain = strip_html(sentence)
    if not plain:
        return None
    for target in targets:
        idx = plain.find(target)
        if idx >= 0:
            cloze = plain[:idx] + CLOZE_BLANK_DISPLAY + plain[idx + len(target):]
            return cloze, plain
    return None


def select_vocab_cloze_sentence(vocab: dict) -> Optional[Tuple[dict, str, str]]:
    """Pick the first WK context sentence where the vocab can be blanked."""
    if vocab.get("object") != "vocabulary":
        return None
    targets = vocab_cloze_blank_targets(vocab)
    if not targets:
        return None
    for sentence in vocab["data"].get("context_sentences") or []:
        blanked = blank_target_in_sentence(sentence.get("ja") or "", targets)
        if blanked:
            cloze, full = blanked
            return sentence, cloze, full
    return None


class VocabClozeItem(NamedTuple):
    vocab: dict
    cloze_sentence: str
    full_sentence: str
    sentence_en: str
    source_ja: str


def collect_vocab_cloze_items(
    vocab_items: Sequence[dict],
    assignment_index: Dict[int, dict],
    *,
    min_srs: int,
) -> List[VocabClozeItem]:
    items: List[VocabClozeItem] = []
    for vocab in sorted(
        vocab_items,
        key=lambda item: (item["data"].get("level", 999), item["data"].get("characters") or ""),
    ):
        if srs_stage(vocab, assignment_index) < min_srs:
            continue
        selected = select_vocab_cloze_sentence(vocab)
        if not selected:
            continue
        sentence, cloze, full = selected
        items.append(
            VocabClozeItem(
                vocab=vocab,
                cloze_sentence=cloze,
                full_sentence=full,
                sentence_en=strip_html(sentence.get("en")),
                source_ja=sentence.get("ja") or "",
            )
        )
    return items


def apply_wk_paren_readings(text: str) -> str:
    """Replace WK-style 漢字（かんじ） hints with かんじ for TTS."""
    return WK_PAREN_READING_RE.sub(lambda match: match.group(2), text)


def prepare_sentence_for_tts(plain_sentence: str, vocab: dict, *, source_ja: str = "") -> str:
    """Build kana-biased sentence text for TTS; card display keeps kanji."""
    base = strip_html(source_ja) if source_ja else plain_sentence
    text = apply_wk_paren_readings(base)
    if text == base:
        text = apply_wk_paren_readings(plain_sentence)
    expr = (vocab["data"].get("characters") or "").strip()
    reading = first_reading(vocab)
    if expr and reading:
        for target in vocab_cloze_blank_targets(vocab):
            if target in text:
                text = text.replace(target, reading, 1)
                break
    return text


def sentence_audio_cache_key(text: str, voice: str) -> str:
    raw = f"{voice}\0{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def sentence_audio_cache_path(text: str, voice: str) -> Path:
    return SENTENCE_AUDIO_CACHE_DIR / f"{sentence_audio_cache_key(text, voice)}.mp3"


def tts_audio_basename(text: str, voice: str) -> str:
    """Shared Anki media name for TTS clips — dedupes identical sentences across decks."""
    plain = strip_html(text).strip()
    if not plain:
        return ""
    return f"wk_tts_{sentence_audio_cache_key(plain, voice)}.mp3"


def vocab_cloze_audio_basename(vocab_id: int) -> str:
    return f"wk_vocab_cloze_{vocab_id}.mp3"


def require_edge_tts():
    try:
        import edge_tts  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "edge-tts is required for sentence audio. "
            "Install it: pip install edge-tts — or disable with --no-sentence-audio / --no-grammar-sentence-audio."
        ) from exc


async def _write_edge_tts_mp3(text: str, voice: str, path: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(path))


def generate_sentence_audio_cache(text: str, voice: str, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_write_edge_tts_mp3(text, voice, cache_path))


def sentence_audio_cache_is_usable(cache_path: Path) -> bool:
    return cache_path.is_file() and cache_path.stat().st_size > 0


def ensure_sentence_audio_file(
    text: str,
    voice: str,
    dest_path: Path,
    *,
    refresh: bool = False,
) -> Tuple[bool, bool]:
    """Return (success, was_cached). was_cached is True when TTS was skipped."""
    plain = strip_html(text).strip()
    if not plain:
        return False, False
    cache_path = sentence_audio_cache_path(plain, voice)
    try:
        was_cached = sentence_audio_cache_is_usable(cache_path) and not refresh
        if not was_cached:
            generate_sentence_audio_cache(plain, voice, cache_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache_path, dest_path)
        ok = dest_path.is_file() and dest_path.stat().st_size > 0
        return ok, was_cached and ok
    except Exception as exc:
        print(f"  Warning: sentence audio failed ({plain[:40]}…): {exc}", file=sys.stderr)
        return False, False


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
                <div class='radical-display'>{{Radical}}</div>
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
        css=versioned_css(
            COMMON_CSS
            + """
.radical-display { margin: 12px 0; }
.radical-display .jp { font-size: 42px; }
.radical-img {
  max-height: 128px;
  max-width: 128px;
  vertical-align: middle;
}
.radical-text { font-size: 32px; color: #cfcfcf; }
"""
            + WK_MNEMONIC_CSS,
            "radical",
        ),
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
            {"name": "ReadingAudio"},
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
                {{#ReadingAudio}}<div class="reading-audio">{{ReadingAudio}}</div>{{/ReadingAudio}}
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
                {{#ReadingAudio}}<div class="reading-audio">{{ReadingAudio}}</div>{{/ReadingAudio}}
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
                "afmt": "{{FrontSide}}<hr><div class='pitch-answer'>{{Pitch}} {{PitchPattern}}</div>{{#ReadingAudio}}<div class='reading-audio'>{{ReadingAudio}}</div>{{/ReadingAudio}}{{ItemHtml}}",
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.reading-audio { margin: 10px auto 6px; }
""",
            "item",
        ),
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


HIRAGANA_CHAR_RE = re.compile(r"^[ぁ-んー]$")
KATAKANA_CHAR_RE = re.compile(r"^[ァ-ヶー]$")


class ConjugationDrill(NamedTuple):
    vocab: dict
    form_key: str
    prompt: str
    dict_expr: str
    dict_reading: str
    conj_expr: str
    conj_reading: str
    word_class: str


VERB_CONJUGATION_FORMS: Tuple[Tuple[str, str], ...] = (
    ("polite_present", "Polite present"),
    ("polite_negative", "Polite negative"),
    ("polite_past", "Polite past"),
    ("plain_negative", "Plain negative"),
    ("plain_past", "Plain past"),
    ("te_form", "Te-form"),
)

I_ADJECTIVE_CONJUGATION_FORMS: Tuple[Tuple[str, str], ...] = (
    ("plain_negative", "Plain negative"),
    ("plain_past", "Plain past"),
    ("plain_past_negative", "Plain past negative"),
    ("polite", "Polite"),
    ("polite_negative", "Polite negative"),
    ("polite_past", "Polite past"),
)

NA_ADJECTIVE_CONJUGATION_FORMS: Tuple[Tuple[str, str], ...] = (
    ("plain_negative", "Plain negative"),
    ("plain_past", "Plain past"),
    ("plain_past_negative", "Plain past negative"),
    ("polite", "Polite"),
    ("polite_negative", "Polite negative"),
    ("polite_past", "Polite past"),
)

VERB_CONJUGATION_WORD_CLASSES: Set[str] = {
    "godan",
    "ichidan",
    "suru_verb",
    "irregular_verb",
}

ADJECTIVE_CONJUGATION_WORD_CLASSES: Set[str] = {
    "i_adjective",
    "na_adjective",
}

GODAN_POLITE_STEM_SUFFIX = {
    "う": "い",
    "く": "き",
    "ぐ": "ぎ",
    "す": "し",
    "つ": "ち",
    "ぬ": "に",
    "ぶ": "び",
    "む": "み",
    "る": "り",
}

GODAN_NEGATIVE_STEM_SUFFIX = {
    "う": "わ",
    "く": "か",
    "ぐ": "が",
    "す": "さ",
    "つ": "た",
    "ぬ": "な",
    "ぶ": "ば",
    "む": "ま",
    "る": "ら",
}

GODAN_TE_SUFFIX = {
    "う": "って",
    "く": "いて",
    "ぐ": "いで",
    "す": "して",
    "つ": "って",
    "ぬ": "んで",
    "ぶ": "んで",
    "む": "んで",
    "る": "って",
}

GODAN_PAST_SUFFIX = {
    "う": "った",
    "く": "いた",
    "ぐ": "いだ",
    "す": "した",
    "つ": "った",
    "ぬ": "んだ",
    "ぶ": "んだ",
    "む": "んだ",
    "る": "った",
}

IKU_READING_EXCEPTIONS = {
    "いく": {
        "polite_present": "いきます",
        "polite_negative": "いきません",
        "polite_past": "いきました",
        "plain_negative": "いかない",
        "plain_past": "いった",
        "te_form": "いって",
    },
}


def is_kana_char(ch: str) -> bool:
    return bool(HIRAGANA_CHAR_RE.match(ch) or KATAKANA_CHAR_RE.match(ch))


def kana_tail_length(expr: str) -> int:
    length = 0
    while length < len(expr):
        ch = expr[-(length + 1)]
        if not is_kana_char(ch):
            break
        length += 1
    return length


def is_all_kana(expr: str) -> bool:
    return bool(expr) and all(is_kana_char(ch) for ch in expr)


def split_word_stems(expr: str, reading: str) -> Optional[Tuple[str, str, str]]:
    """Return (character stem, reading stem, dictionary okurigana suffix)."""
    if not expr or not reading:
        return None

    if is_all_kana(expr):
        if reading.endswith("する") and expr.endswith("する"):
            return expr[:-2], reading[:-2], "する"
        if reading in {"する", "くる"} and expr == reading:
            return "", reading, expr
        return expr, reading, ""

    if expr.endswith("する") and reading.endswith("する") and len(expr) >= 2 and len(reading) >= 2:
        return expr[:-2], reading[:-2], "する"

    if expr.endswith("る") and reading.endswith("る") and len(expr) >= 2 and len(reading) >= 2:
        return expr[:-1], reading[:-1], "る"

    kana_len = kana_tail_length(expr)
    if kana_len == 0:
        return None

    okurigana = expr[-kana_len:]
    char_stem = expr[:-kana_len]
    if okurigana and reading.endswith(okurigana):
        reading_stem = reading[:-len(okurigana)]
        return char_stem, reading_stem, okurigana

    if len(okurigana) == 1 and okurigana in GODAN_POLITE_STEM_SUFFIX:
        if len(reading) >= 2:
            return char_stem, reading[:-1], okurigana

    return None


def surface_from_reading_stems(char_stem: str, reading_stem: str, conj_reading: str) -> str:
    if conj_reading.startswith(reading_stem):
        return char_stem + conj_reading[len(reading_stem):]
    if is_all_kana(char_stem + reading_stem):
        return conj_reading
    return char_stem + conj_reading[len(reading_stem):]


def conjugation_word_class(vocab: dict) -> Optional[str]:
    pos = set(vocab["data"].get("parts_of_speech") or [])
    if "い adjective" in pos:
        return "i_adjective"
    if "な adjective" in pos:
        return "na_adjective"
    if "する verb" in pos or (vocab["data"].get("characters") or "").endswith("する"):
        return "suru_verb"
    if "ichidan verb" in pos:
        return "ichidan"
    if "godan verb" in pos:
        return "godan"
    if "transitive verb" in pos or "intransitive verb" in pos:
        reading = first_reading(vocab)
        if reading in {"する", "くる"}:
            return "irregular_verb"
        if reading.endswith("する"):
            return "suru_verb"
        if reading.endswith("る") and len(reading) >= 2 and reading[-2] in "いきしちにひみりえけせてねへめれげぜでべぺ":
            return "ichidan"
        return "godan"
    return None


def conjugation_class_label(word_class: str) -> str:
    return {
        "godan": "Godan verb",
        "ichidan": "Ichidan verb",
        "suru_verb": "する verb",
        "irregular_verb": "Irregular verb",
        "i_adjective": "い-adjective",
        "na_adjective": "な-adjective",
    }.get(word_class, word_class)


VERB_DRILL_CLASS_ANSWER: Dict[str, str] = {
    "godan": "Godan verb (五段)",
    "ichidan": "Ichidan verb (一段)",
    "irregular": "Irregular verb (不規則)",
}

VERB_DRILL_CLASS_HINT: Dict[str, str] = {
    "godan": "The last kana shifts before ます / て / た / ない (e.g. 話す → はなします, はなして).",
    "ichidan": "Drop る and add the ending (e.g. 食べる → たべます, たべて).",
    "irregular": "する and 来る break the usual rules; する compounds conjugate the する part.",
}

ADJECTIVE_DRILL_CLASS_ANSWER: Dict[str, str] = {
    "i_adjective": "い-adjective",
    "na_adjective": "な-adjective",
}

ADJECTIVE_DRILL_CLASS_HINT: Dict[str, str] = {
    "i_adjective": "Ends in い; change the い tail (e.g. 高い → 高くない, 高かった, 高く).",
    "na_adjective": "Use な before nouns; です / じゃない / だった (e.g. 静か → 静かな人, 静かだった).",
}


def verb_drill_class(vocab: dict) -> Optional[str]:
    """Learner verb class for type drills: godan, ichidan, or irregular."""
    word_class = conjugation_word_class(vocab)
    if word_class == "godan":
        return "godan"
    if word_class == "ichidan":
        return "ichidan"
    if word_class in {"suru_verb", "irregular_verb"}:
        return "irregular"
    return None


def adjective_drill_class(vocab: dict) -> Optional[str]:
    word_class = conjugation_word_class(vocab)
    if word_class in {"i_adjective", "na_adjective"}:
        return word_class
    return None


def verb_type_drill_answer(vocab: dict, class_key: str) -> str:
    answer = VERB_DRILL_CLASS_ANSWER[class_key]
    word_class = conjugation_word_class(vocab)
    if class_key == "irregular" and word_class == "suru_verb":
        return answer + " · する"
    if class_key == "irregular" and word_class == "irregular_verb":
        expr = vocab["data"].get("characters") or ""
        reading = first_reading(vocab)
        if reading == "くる" or expr in {"来る", "くる"}:
            return answer + " · 来る"
    return answer


def collect_verb_type_items(vocab_items: Sequence[dict], args: argparse.Namespace) -> List[dict]:
    items = [
        vocab
        for vocab in sorted(
            vocab_items,
            key=lambda v: (v["data"].get("level", 999), v["data"].get("characters") or ""),
        )
        if verb_drill_class(vocab)
    ]
    return items[: args.max_cards]


def collect_adjective_type_items(vocab_items: Sequence[dict], args: argparse.Namespace) -> List[dict]:
    items = [
        vocab
        for vocab in sorted(
            vocab_items,
            key=lambda v: (v["data"].get("level", 999), v["data"].get("characters") or ""),
        )
        if adjective_drill_class(vocab)
    ]
    return items[: args.max_cards]


def conjugate_godan(expr: str, reading: str, form_key: str) -> Optional[Tuple[str, str]]:
    if reading in IKU_READING_EXCEPTIONS and form_key in IKU_READING_EXCEPTIONS[reading]:
        conj_reading = IKU_READING_EXCEPTIONS[reading][form_key]
        stems = split_word_stems(expr, reading)
        if not stems:
            return None
        char_stem, reading_stem, _ = stems
        return surface_from_reading_stems(char_stem, reading_stem, conj_reading), conj_reading

    stems = split_word_stems(expr, reading)
    if not stems:
        return None
    char_stem, reading_stem, okurigana = stems
    if len(okurigana) != 1 or okurigana not in GODAN_POLITE_STEM_SUFFIX:
        return None

    ending = okurigana
    if form_key == "polite_present":
        conj_reading = reading_stem + GODAN_POLITE_STEM_SUFFIX[ending] + "ます"
    elif form_key == "polite_negative":
        conj_reading = reading_stem + GODAN_POLITE_STEM_SUFFIX[ending] + "ません"
    elif form_key == "polite_past":
        conj_reading = reading_stem + GODAN_POLITE_STEM_SUFFIX[ending] + "ました"
    elif form_key == "plain_negative":
        conj_reading = reading_stem + GODAN_NEGATIVE_STEM_SUFFIX[ending] + "ない"
    elif form_key == "plain_past":
        conj_reading = reading_stem + GODAN_PAST_SUFFIX[ending]
    elif form_key == "te_form":
        conj_reading = reading_stem + GODAN_TE_SUFFIX[ending]
    else:
        return None

    return surface_from_reading_stems(char_stem, reading_stem, conj_reading), conj_reading


def conjugate_ichidan(expr: str, reading: str, form_key: str) -> Optional[Tuple[str, str]]:
    stems = split_word_stems(expr, reading)
    if not stems:
        return None
    char_stem, reading_stem, okurigana = stems
    if okurigana != "る" or not reading.endswith("る"):
        return None

    if form_key == "polite_present":
        conj_reading = reading_stem + "ます"
    elif form_key == "polite_negative":
        conj_reading = reading_stem + "ません"
    elif form_key == "polite_past":
        conj_reading = reading_stem + "ました"
    elif form_key == "plain_negative":
        conj_reading = reading_stem + "ない"
    elif form_key == "plain_past":
        conj_reading = reading_stem + "た"
    elif form_key == "te_form":
        conj_reading = reading_stem + "て"
    else:
        return None

    return surface_from_reading_stems(char_stem, reading_stem, conj_reading), conj_reading


def conjugate_suru(expr: str, reading: str, form_key: str) -> Optional[Tuple[str, str]]:
    if reading.endswith("する"):
        char_stem = expr[:-2] if expr.endswith("する") else expr
        reading_stem = reading[:-2]
        suru_reading = "する"
        suru_expr = "する"
    elif reading == "する" and expr == "する":
        char_stem = ""
        reading_stem = ""
        suru_reading = "する"
        suru_expr = "する"
    else:
        return None

    suru_forms = {
        "polite_present": ("します", "します"),
        "polite_negative": ("しません", "しません"),
        "polite_past": ("しました", "しました"),
        "plain_negative": ("しない", "しない"),
        "plain_past": ("した", "した"),
        "te_form": ("して", "して"),
    }
    if form_key not in suru_forms:
        return None
    conj_suffix, conj_reading_suffix = suru_forms[form_key]
    conj_expr = char_stem + (suru_expr[:-2] + conj_suffix if suru_expr == "する" else conj_suffix)
    if char_stem and expr.endswith("する"):
        conj_expr = char_stem + conj_suffix
    elif not char_stem:
        conj_expr = conj_suffix
    conj_reading = reading_stem + conj_reading_suffix
    return conj_expr, conj_reading


def conjugate_kuru(expr: str, reading: str, form_key: str) -> Optional[Tuple[str, str]]:
    if reading != "くる" or expr not in {"来る", "くる"}:
        return None
    forms = {
        "polite_present": ("来ます", "きます"),
        "polite_negative": ("来ません", "きません"),
        "polite_past": ("来ました", "きました"),
        "plain_negative": ("来ない", "こない"),
        "plain_past": ("来た", "きた"),
        "te_form": ("来て", "きて"),
    }
    if form_key not in forms:
        return None
    return forms[form_key]


def conjugate_i_adjective(expr: str, reading: str, form_key: str) -> Optional[Tuple[str, str]]:
    if reading in {"いい", "よい"}:
        irregular = {
            "plain_negative": ("よくない", "よくない"),
            "plain_past": ("よかった", "よかった"),
            "plain_past_negative": ("よくなかった", "よくなかった"),
            "polite": ("いいです", "いいです"),
            "polite_negative": ("よくないです", "よくないです"),
            "polite_past": ("よかったです", "よかったです"),
        }
        if form_key in irregular:
            return irregular[form_key]
        return None

    if not reading.endswith("い") or not expr.endswith("い"):
        return None

    char_stem = expr[:-1]
    reading_stem = reading[:-1]
    forms = {
        "plain_negative": ("くない", "くない"),
        "plain_past": ("かった", "かった"),
        "plain_past_negative": ("くなかった", "くなかった"),
        "polite": ("いです", "いです"),
        "polite_negative": ("くないです", "くないです"),
        "polite_past": ("かったです", "かったです"),
    }
    if form_key not in forms:
        return None
    suffix, reading_suffix = forms[form_key]
    return char_stem + suffix, reading_stem + reading_suffix


def conjugate_na_adjective(expr: str, reading: str, form_key: str) -> Optional[Tuple[str, str]]:
    forms = {
        "plain_negative": ("じゃない", "じゃない"),
        "plain_past": ("だった", "だった"),
        "plain_past_negative": ("じゃなかった", "じゃなかった"),
        "polite": ("です", "です"),
        "polite_negative": ("じゃないです", "じゃないです"),
        "polite_past": ("でした", "でした"),
    }
    if form_key not in forms:
        return None
    suffix, reading_suffix = forms[form_key]
    return expr + suffix, reading + reading_suffix


def conjugate_vocab_form(vocab: dict, word_class: str, form_key: str) -> Optional[Tuple[str, str]]:
    expr = vocab["data"].get("characters") or ""
    reading = first_reading(vocab)
    if not expr or not reading:
        return None

    if word_class == "godan":
        return conjugate_godan(expr, reading, form_key)
    if word_class == "ichidan":
        return conjugate_ichidan(expr, reading, form_key)
    if word_class == "suru_verb":
        return conjugate_suru(expr, reading, form_key)
    if word_class == "irregular_verb":
        if reading == "くる":
            return conjugate_kuru(expr, reading, form_key)
        if reading == "する":
            return conjugate_suru(expr, reading, form_key)
        return None
    if word_class == "i_adjective":
        return conjugate_i_adjective(expr, reading, form_key)
    if word_class == "na_adjective":
        return conjugate_na_adjective(expr, reading, form_key)
    return None


def conjugation_forms_for_class(word_class: str) -> Tuple[Tuple[str, str], ...]:
    if word_class in {"godan", "ichidan", "suru_verb", "irregular_verb"}:
        return VERB_CONJUGATION_FORMS
    if word_class == "i_adjective":
        return I_ADJECTIVE_CONJUGATION_FORMS
    if word_class == "na_adjective":
        return NA_ADJECTIVE_CONJUGATION_FORMS
    return ()


def collect_conjugation_drills(
    vocab_items: Sequence[dict],
    assignment_index: Dict[int, dict],
    args: argparse.Namespace,
    *,
    min_srs: int,
    word_classes: Optional[Set[str]] = None,
    tae_kim_cap: Optional["TaeKimConjugationCap"] = None,
) -> List[ConjugationDrill]:
    drills: List[ConjugationDrill] = []
    for vocab in sorted(vocab_items, key=lambda v: (v["data"].get("level", 999), v["data"].get("characters") or "")):
        if srs_stage(vocab, assignment_index) < min_srs:
            continue
        word_class = conjugation_word_class(vocab)
        if not word_class:
            continue
        if word_classes is not None and word_class not in word_classes:
            continue
        if tae_kim_cap is not None and not tae_kim_cap.allows_word_class(word_class):
            continue
        expr = vocab["data"].get("characters") or ""
        reading = first_reading(vocab)
        for form_key, prompt in conjugation_forms_for_class(word_class):
            if tae_kim_cap is not None and not tae_kim_cap.allows_form(word_class, form_key):
                continue
            result = conjugate_vocab_form(vocab, word_class, form_key)
            if not result:
                continue
            conj_expr, conj_reading = result
            if conj_expr == expr and conj_reading == reading:
                continue
            drills.append(
                ConjugationDrill(
                    vocab=vocab,
                    form_key=form_key,
                    prompt=prompt,
                    dict_expr=expr,
                    dict_reading=reading,
                    conj_expr=conj_expr,
                    conj_reading=conj_reading,
                    word_class=word_class,
                )
            )
    return drills[: args.max_cards]


def resolve_tae_kim_conjugation_cap(args: argparse.Namespace):
    """When grammar lesson cap is set, limit conjugation forms to match Tae Kim progress."""
    if getattr(args, "conjugation_no_tae_kim_cap", False):
        return None
    if not args.grammar_max_tae_kim_lesson:
        return None
    from tae_kim_mapping import conjugation_cap_for_tae_kim

    return conjugation_cap_for_tae_kim(
        max_tae_kim_lesson=args.grammar_max_tae_kim_lesson,
        max_tae_kim_section=args.grammar_max_tae_kim_section,
    )


CONJUGATION_FIXTURES_FILENAME = "conjugation_fixtures.json"
CONJUGATION_VERIFY_VOCAB_ISSUE_LIMIT = 50

CONJUGATION_WORD_CLASS_POS: Dict[str, List[str]] = {
    "godan": ["godan verb"],
    "ichidan": ["ichidan verb"],
    "suru_verb": ["する verb"],
    "irregular_verb": ["intransitive verb"],
    "i_adjective": ["い adjective"],
    "na_adjective": ["な adjective"],
}


class ConjugationFixture(NamedTuple):
    expr: str
    reading: str
    word_class: str
    form_key: str
    conj_expr: str
    conj_reading: str
    note: str


class ConjugationVocabIssue(NamedTuple):
    vocab: dict
    issues: Tuple[str, ...]


def conjugation_fixtures_path() -> Path:
    return Path(__file__).resolve().parent / CONJUGATION_FIXTURES_FILENAME


def load_conjugation_fixtures(path: Optional[Path] = None) -> List[ConjugationFixture]:
    fixture_path = path or conjugation_fixtures_path()
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixtures: List[ConjugationFixture] = []
    for row in payload.get("fixtures") or []:
        fixtures.append(
            ConjugationFixture(
                expr=str(row.get("expr") or ""),
                reading=str(row.get("reading") or ""),
                word_class=str(row.get("word_class") or ""),
                form_key=str(row.get("form_key") or ""),
                conj_expr=str(row.get("conj_expr") or ""),
                conj_reading=str(row.get("conj_reading") or ""),
                note=str(row.get("note") or ""),
            )
        )
    return fixtures


def mock_vocab_for_conjugation(expr: str, reading: str, parts_of_speech: Sequence[str], vocab_id: int = 0) -> dict:
    return {
        "id": vocab_id,
        "object": "vocabulary",
        "data": {
            "characters": expr,
            "readings": [{"reading": reading, "primary": True}],
            "parts_of_speech": list(parts_of_speech),
            "level": 1,
        },
    }


def conjugate_from_fixture(fixture: ConjugationFixture) -> Optional[Tuple[str, str]]:
    parts = CONJUGATION_WORD_CLASS_POS.get(fixture.word_class, [])
    vocab = mock_vocab_for_conjugation(fixture.expr, fixture.reading, parts)
    detected = conjugation_word_class(vocab)
    if detected != fixture.word_class:
        return None
    return conjugate_vocab_form(vocab, fixture.word_class, fixture.form_key)


def run_conjugation_fixture_checks(fixtures: Optional[Sequence[ConjugationFixture]] = None) -> List[str]:
    failures: List[str] = []
    for fixture in fixtures or load_conjugation_fixtures():
        result = conjugate_from_fixture(fixture)
        expected = (fixture.conj_expr, fixture.conj_reading)
        if result != expected:
            failures.append(
                f"{fixture.expr} ({fixture.reading}) {fixture.form_key} [{fixture.note}]: "
                f"got {result}, expected {expected}"
            )
    return failures


def conjugation_issues_for_vocab(vocab: dict) -> List[str]:
    issues: List[str] = []
    word_class = conjugation_word_class(vocab)
    if not word_class:
        return issues

    expr = vocab["data"].get("characters") or ""
    reading = first_reading(vocab)
    if not expr:
        issues.append("missing expression")
    if not reading:
        issues.append("missing reading")
    if issues:
        return issues

    produced = 0
    for form_key, _prompt in conjugation_forms_for_class(word_class):
        result = conjugate_vocab_form(vocab, word_class, form_key)
        if result is None:
            issues.append(f"missing form: {form_key}")
            continue
        conj_expr, conj_reading = result
        if not conj_expr or not conj_reading:
            issues.append(f"empty result: {form_key}")
            continue
        if conj_expr == expr and conj_reading == reading:
            issues.append(f"unchanged: {form_key}")
            continue
        produced += 1

    if produced == 0:
        issues.append("no conjugations produced")
    return issues


def scan_conjugation_vocab_issues(vocab_items: Sequence[dict]) -> List[ConjugationVocabIssue]:
    flagged: List[ConjugationVocabIssue] = []
    for vocab in vocab_items:
        issues = conjugation_issues_for_vocab(vocab)
        if issues:
            flagged.append(ConjugationVocabIssue(vocab=vocab, issues=tuple(issues)))
    return flagged


def print_conjugation_verification_report(
    fixture_failures: Sequence[str],
    vocab_issues: Sequence[ConjugationVocabIssue],
    *,
    vocab_issue_limit: int = CONJUGATION_VERIFY_VOCAB_ISSUE_LIMIT,
) -> bool:
    """Print verification results. Returns True when no failures were found."""
    fixture_count = len(load_conjugation_fixtures())
    print("\nConjugation verification")
    print("=" * 60)
    print(f"Fixture checks: {fixture_count - len(fixture_failures)}/{fixture_count} passed")

    if fixture_failures:
        print("\nFixture failures:")
        for line in fixture_failures:
            print(f"  FAIL {line}")
    else:
        print("  All curated fixtures passed.")

    print(f"\nEligible vocab scanned: {len(vocab_issues)} suspicious item(s)")
    if not vocab_issues:
        print("  No suspicious conjugation patterns in eligible vocabulary.")
    else:
        print(f"  Showing up to {vocab_issue_limit}:")
        for entry in vocab_issues[:vocab_issue_limit]:
            data = entry.vocab["data"]
            expr = data.get("characters") or "?"
            reading = first_reading(entry.vocab)
            level = data.get("level", "?")
            word_class = conjugation_word_class(entry.vocab) or "?"
            issue_text = "; ".join(entry.issues)
            print(f"  L{level} {expr} ({reading}) [{word_class}] — {issue_text}")
        if len(vocab_issues) > vocab_issue_limit:
            print(f"  ... and {len(vocab_issues) - vocab_issue_limit} more")

    ok = not fixture_failures and not vocab_issues
    if ok:
        print("\nConjugation verification: PASSED")
    else:
        print("\nConjugation verification: FAILED")
    return ok


def run_verify_conjugations(
    args: argparse.Namespace,
    *,
    vocab_items: Optional[Sequence[dict]] = None,
    cache_only: bool = False,
) -> bool:
    fixture_failures = run_conjugation_fixture_checks()
    vocab_issues: List[ConjugationVocabIssue] = []
    if vocab_items is not None:
        vocab_issues = scan_conjugation_vocab_issues(vocab_items)
        print(f"\nScanned eligible vocab: {len(vocab_items)} items")
    elif cache_only:
        subjects = load_cache_items_only("subjects", "vocabulary_kanji_radical")
        assignment_params = build_assignment_params(args)
        assignment_key = assignment_params_key(assignment_params)
        assignments = load_cache_items_only("assignments", assignment_key)
        if subjects and assignments:
            assignment_index = assignment_by_subject_id(assignments)
            cached_vocab = vocab_subjects(subjects, assignment_index, args)
            vocab_issues = scan_conjugation_vocab_issues(cached_vocab)
            print(f"\nLoaded cached vocab for scan: {len(cached_vocab)} eligible items")
        else:
            print("\nSkipping eligible-vocab scan (no matching .wk_cache data). Fixture checks still ran.")
    return print_conjugation_verification_report(fixture_failures, vocab_issues)


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
        css=versioned_css(COMMON_CSS + WK_MNEMONIC_CSS, "kanji_radical"),
    )


def make_phonetic_drill_model() -> WkModel:
    return WkModel(
        MODEL_IDS["phonetic_drill"],
        NOTE_TYPE_NAMES["phonetic_drill"],
        template_key="phonetic_drill",
        fields=[
            {"name": "GuidKey"},
            {"name": "WkSubjectId"},
            {"name": "Kanji"},
            {"name": "Prompt"},
            {"name": "WkReadings"},
            {"name": "PhoneticPiece"},
            {"name": "PhoneticReadings"},
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
                <div class="meta">Recall WK on'yomi; use the phonetic piece as a hint</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="reading answer">WK on'yomi: {{WkReadings}}</div>
                <div class="phonetic-piece">
                  <span class="meta">Phonetic component</span>
                  <span class="jp">{{PhoneticPiece}}</span>
                  <div class="phonetic-map">Usually signals: <span class="reading">{{PhoneticReadings}}</span></div>
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
.phonetic-map { font-size: 16px; color: #bbb; margin-top: 6px; }
.phonetic-map .reading { font-size: 22px; color: #d8d8d8; }
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


def make_conjugation_model() -> WkModel:
    return WkModel(
        MODEL_IDS["conjugation"],
        NOTE_TYPE_NAMES["conjugation"],
        template_key="conjugation",
        fields=[
            {"name": "GuidKey"},
            {"name": "WkSubjectId"},
            {"name": "Prompt"},
            {"name": "DictExpression"},
            {"name": "DictReading"},
            {"name": "Meaning"},
            {"name": "WordClass"},
            {"name": "ConjExpression"},
            {"name": "TypeConjExpression"},
            {"name": "ConjReading"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Conjugate",
                "qfmt": """
                <div class="prompt">{{Prompt}}</div>
                <div class="jp">{{DictExpression}}</div>
                <div class="reading">{{DictReading}}</div>
                <div class="meaning">{{Meaning}}</div>
                <div class="type-answer">{{type:TypeConjExpression}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="jp answer">{{ConjExpression}}</div>
                <div class="reading answer">{{ConjReading}}</div>
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.type-answer { margin: 16px auto; max-width: 520px; font-size: 28px; }
.answer { margin-top: 8px; }
.jp.answer { font-size: 40px; }
""",
            "conjugation",
        ),
    )


def make_conjugation_reverse_model() -> WkModel:
    return WkModel(
        MODEL_IDS["conjugation_reverse"],
        NOTE_TYPE_NAMES["conjugation_reverse"],
        template_key="conjugation_reverse",
        fields=[
            {"name": "GuidKey"},
            {"name": "WkSubjectId"},
            {"name": "Prompt"},
            {"name": "DictExpression"},
            {"name": "TypeDictExpression"},
            {"name": "DictReading"},
            {"name": "Meaning"},
            {"name": "ConjExpression"},
            {"name": "ConjReading"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Conjugated → Dictionary",
                "qfmt": """
                <div class="prompt">What is the dictionary form?</div>
                <div class="jp">{{ConjExpression}}</div>
                <div class="type-answer">{{type:TypeDictExpression}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="meta form-label">{{Prompt}}</div>
                <div class="jp answer">{{DictExpression}}</div>
                <div class="reading answer">{{DictReading}}</div>
                <div class="meaning">{{Meaning}}</div>
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.type-answer { margin: 16px auto; max-width: 520px; font-size: 28px; }
.answer { margin-top: 8px; }
.jp.answer { font-size: 40px; }
.form-label { margin-bottom: 8px; font-style: italic; }
""",
            "conjugation_reverse",
        ),
    )


def make_word_class_model() -> WkModel:
    return WkModel(
        MODEL_IDS["word_class"],
        NOTE_TYPE_NAMES["word_class"],
        template_key="word_class",
        fields=[
            {"name": "GuidKey"},
            {"name": "WkSubjectId"},
            {"name": "Prompt"},
            {"name": "Expression"},
            {"name": "Reading"},
            {"name": "Meaning"},
            {"name": "ClassAnswer"},
            {"name": "ClassHint"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Word class",
                "qfmt": """
                <div class="prompt">{{Prompt}}</div>
                <div class="jp">{{Expression}}</div>
                <div class="reading">{{Reading}}</div>
                <div class="meaning">{{Meaning}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="class-answer">{{ClassAnswer}}</div>
                <div class="class-hint">{{ClassHint}}</div>
                <div class="meta">{{Meta}}</div>
                """,
            },
        ],
        css=versioned_css(
            COMMON_CSS
            + """
.class-answer { font-size: 32px; margin: 12px 0; color: #e8e8e8; font-weight: 600; }
.class-hint {
  font-size: 15px;
  color: #bbb;
  margin: 8px auto;
  max-width: 720px;
  line-height: 1.4;
}
""",
            "word_class",
        ),
    )


def vocab_cloze_form_hint(
    sentence_en: str,
    *,
    type_expression: str = "",
    expression: str = "",
) -> str:
    """Front-side context for vocab production without revealing the blanked word."""
    parts: List[str] = []
    plain = strip_html(sentence_en).strip()
    if plain:
        parts.append(plain)
    if type_expression and expression and type_expression != expression:
        parts.append("Type full kanji spelling (not early WK kana)")
    return " · ".join(parts)


def make_vocab_cloze_model() -> WkModel:
    return WkModel(
        MODEL_IDS["vocab_cloze"],
        NOTE_TYPE_NAMES["vocab_cloze"],
        template_key="vocab_cloze",
        fields=[
            {"name": "GuidKey"},
            {"name": "WkSubjectId"},
            {"name": "ClozeSentence"},
            {"name": "Hint"},
            {"name": "FormHint"},
            {"name": "Expression"},
            {"name": "TypeExpression"},
            {"name": "WkSpellingNote"},
            {"name": "Reading"},
            {"name": "Meaning"},
            {"name": "FullSentence"},
            {"name": "SentenceEnglish"},
            {"name": "SentenceAudio"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Reading cloze",
                "qfmt": """
                <div class="prompt">Type the missing word</div>
                <div class="jp cloze">{{ClozeSentence}}</div>
                <div class="meaning hint">{{Hint}}</div>
                {{#FormHint}}<div class="form-hint">{{FormHint}}</div>{{/FormHint}}
                <div class="type-answer">{{type:TypeExpression}}</div>
                <div class="meta">{{Meta}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="reading answer">{{Reading}}</div>
                <div class="meaning answer">{{Meaning}}</div>
                {{#WkSpellingNote}}<div class="wk-spelling">{{WkSpellingNote}}</div>{{/WkSpellingNote}}
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
.cloze { font-size: 34px; line-height: 1.55; }
.hint { font-size: 17px; margin-top: 10px; color: #bbb; font-style: italic; }
.form-hint { font-size: 15px; margin-top: 6px; color: #c8c8c8; font-weight: 600; letter-spacing: 0.02em; }
.type-answer { margin: 16px auto; max-width: 520px; font-size: 28px; }
.jp.answer { font-size: 40px; }
.wk-spelling { font-size: 15px; color: #aaa; margin: 8px 0; font-style: italic; }
.sentence-audio { margin-top: 10px; margin-bottom: 4px; }
""",
            "vocab_cloze",
        ),
    )


def radical_subjects(subjects: Sequence[dict], args: argparse.Namespace) -> List[dict]:
    max_level = min(args.max_level, 60)
    return [
        s for s in subjects
        if s.get("object") == "radical"
        and int(s["data"].get("level", 999)) <= max_level
        and not subject_is_hidden(s)
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


class RadicalPreviewLevels(NamedTuple):
    current: int
    next: int
    locked_next: int

    def level_set(self) -> Set[int]:
        """Levels 1..current (review), plus next and locked-next preview."""
        levels = set(range(1, self.current + 1))
        levels.add(self.next)
        levels.add(self.locked_next)
        return levels


def selected_radical_levels(
    user: dict,
    subjects: Sequence[dict],
    assignment_index: Dict[int, dict],
    args: argparse.Namespace,
) -> RadicalPreviewLevels:
    if args.radical_current_level:
        current = args.radical_current_level
    else:
        current = current_wk_level(user, subjects, assignment_index)
    next_level = min(current + 1, 60)
    locked_next = min(current + 2, 60)
    return RadicalPreviewLevels(current, next_level, locked_next)


def radical_level_status(level: int, preview_levels: RadicalPreviewLevels) -> str:
    if level == preview_levels.current:
        return "current-level"
    if level == preview_levels.next:
        return "next-level"
    if level == preview_levels.locked_next:
        return "locked-next-level"
    if level < preview_levels.current:
        return "previous-level"
    return "preview-level"


def radical_priority(radical: dict, preview_levels: RadicalPreviewLevels) -> str:
    level = int(radical["data"].get("level") or 999)
    if level == preview_levels.current or level == preview_levels.next:
        return "priority-high"
    if level == preview_levels.locked_next:
        return "priority-medium"
    if level < preview_levels.current:
        return "priority-low"
    return "priority-medium"


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


def radical_display(radical: dict) -> str:
    chars = radical["data"].get("characters")
    if chars:
        return chars
    # Some WK radicals are images rather than Unicode characters.
    return radical["data"].get("slug") or "radical"


def radical_image_content_extension(image: dict) -> str:
    content_type = str(image.get("content_type") or "").lower()
    if "svg" in content_type:
        return "svg"
    if "png" in content_type:
        return "png"
    url = str(image.get("url") or "").lower()
    if url.endswith(".svg"):
        return "svg"
    return "png"


def wanikani_files_url_is_downloadable(url: str, content_type: str = "") -> bool:
    """PNG assets on files.wanikani.com return 403; SVG URLs work with Referer."""
    if "files.wanikani.com" not in url:
        return True
    return "svg" in content_type.lower()


def radical_image_download_candidates(radical: dict) -> List[Tuple[str, str]]:
    """Return (url, file_extension) pairs to try, best first."""
    candidates: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    images = radical["data"].get("character_images") or []
    slug = radical["data"].get("slug") or ""
    subject_id = radical["id"]

    def add(url: str, ext: str) -> None:
        if url and url not in seen:
            seen.add(url)
            candidates.append((url, ext))

    for image in images:
        if not isinstance(image, dict):
            continue
        url = str(image.get("url") or "")
        content_type = str(image.get("content_type") or "")
        ext = radical_image_content_extension(image)
        if ext == "svg" and wanikani_files_url_is_downloadable(url, content_type):
            add(url, ext)

    if slug:
        add(
            WANIKANI_CDN_SUBJECT_IMAGE_URL.format(subject_id=subject_id, slug=slug),
            "png",
        )

    by_style = {
        (img.get("metadata") or {}).get("style_name"): img
        for img in images
        if isinstance(img, dict)
    }
    for style in RADICAL_IMAGE_STYLE_PREFERENCE:
        image = by_style.get(style)
        if not image:
            continue
        url = str(image.get("url") or "")
        content_type = str(image.get("content_type") or "")
        if wanikani_files_url_is_downloadable(url, content_type):
            add(url, radical_image_content_extension(image))

    for image in images:
        if not isinstance(image, dict):
            continue
        url = str(image.get("url") or "")
        content_type = str(image.get("content_type") or "")
        if wanikani_files_url_is_downloadable(url, content_type):
            add(url, radical_image_content_extension(image))

    return candidates


def radical_image_media_name(radical_id: int, ext: str = "png") -> str:
    return f"wk-radical-{radical_id}.{ext}"


def radical_image_request_headers() -> dict:
    return {
        "User-Agent": f"Mozilla/5.0 (compatible; wk_decks/{VERSION})",
        "Referer": "https://www.wanikani.com/",
    }


def ensure_radical_image_media(radical: dict) -> Optional[Tuple[str, Path]]:
    """Download WK radical image into cache; return Anki media basename and local path."""
    radical_id = radical["id"]
    RADICAL_MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("svg", "png"):
        media_name = radical_image_media_name(radical_id, ext)
        path = RADICAL_MEDIA_CACHE_DIR / media_name
        if path.exists() and path.stat().st_size > 0:
            return media_name, path

    candidates = radical_image_download_candidates(radical)
    if not candidates:
        return None

    errors: List[str] = []
    headers = radical_image_request_headers()
    for url, ext in candidates:
        media_name = radical_image_media_name(radical_id, ext)
        path = RADICAL_MEDIA_CACHE_DIR / media_name
        try:
            response = requests.get(url, headers=headers, timeout=45)
            response.raise_for_status()
            if not response.content:
                errors.append(f"{url}: empty response")
                continue
            path.write_bytes(response.content)
            return media_name, path
        except requests.RequestException as exc:
            errors.append(f"{url}: {exc}")
            continue

    slug = radical["data"].get("slug") or radical_id
    print(
        f"Warning: could not download radical image for {slug}: {errors[0]}",
        file=sys.stderr,
    )
    return None


def ensure_radical_media_files(radicals: Iterable[dict]) -> Tuple[Dict[int, str], List[str]]:
    media_names: Dict[int, str] = {}
    media_paths: List[str] = []
    for radical in radicals:
        if radical["data"].get("characters"):
            continue
        cached = ensure_radical_image_media(radical)
        if not cached:
            continue
        media_name, path = cached
        media_names[radical["id"]] = media_name
        path_str = str(path)
        if path_str not in media_paths:
            media_paths.append(path_str)
    return media_names, media_paths


def radical_display_html(radical: dict, media_names: Optional[Dict[int, str]] = None) -> str:
    chars = radical["data"].get("characters")
    if chars:
        return f"<span class='jp'>{html.escape(chars)}</span>"
    slug = radical["data"].get("slug") or "radical"
    alt = html.escape(slug)
    media_name = (media_names or {}).get(radical["id"])
    if media_name:
        return f'<img class="radical-img" src="{html.escape(media_name)}" alt="{alt}">'
    return f"<span class='radical-text'>{html.escape(slug)}</span>"


def radical_description_html(radical: dict) -> str:
    return wk_mnemonic_html(radical["data"].get("meaning_mnemonic"))


def radical_index_by_id(subjects: Sequence[dict]) -> Dict[int, dict]:
    return {subject["id"]: subject for subject in subjects if subject.get("object") == "radical"}


def unlocked_subject_ids(subjects: Sequence[dict], assignment_index: Dict[int, dict]) -> Set[int]:
    return {subject["id"] for subject in subjects if is_unlocked(subject, assignment_index)}


def kanji_has_unlocked_radicals_only(kanji: dict, unlocked_radical_ids: Set[int]) -> bool:
    component_ids = kanji["data"].get("component_subject_ids") or []
    return bool(component_ids) and all(component_id in unlocked_radical_ids for component_id in component_ids)


def kanji_radicals_back_html(
    kanji: dict,
    radical_index: Dict[int, dict],
    media_names: Optional[Dict[int, str]] = None,
) -> str:
    rows: List[str] = []
    for component_id in kanji["data"].get("component_subject_ids") or []:
        radical = radical_index.get(component_id)
        if not radical:
            continue
        display = radical_display_html(radical, media_names)
        meaning = html.escape("; ".join(primary_meanings(radical)))
        rows.append(
            f"<div class='radical-piece'>{display} "
            f"<span class='meaning'>{meaning}</span></div>"
        )
    return f"<div class='radical-breakdown'>{''.join(rows)}</div>" if rows else ""


def kanji_radicals_front_html(
    kanji: dict,
    radical_index: Dict[int, dict],
    media_names: Optional[Dict[int, str]] = None,
) -> str:
    pieces: List[str] = []
    for component_id in kanji["data"].get("component_subject_ids") or []:
        radical = radical_index.get(component_id)
        if not radical:
            continue
        display = radical_display_html(radical, media_names)
        meaning = html.escape("; ".join(primary_meanings(radical)))
        pieces.append(
            f"<span class='radicals-front-piece'>{display}"
            f"<span class='radicals-front-meaning'>{meaning}</span></span>"
        )
    if not pieces:
        return ""
    return f"<div class='radicals-front'>{''.join(pieces)}</div>"


def meaning_mnemonic_html(subject: dict) -> str:
    return wk_mnemonic_html(subject["data"].get("meaning_mnemonic"))


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
    if getattr(args, "no_wk_progress_filter", False):
        return all_vocab_subjects(subjects, args)
    return [
        s
        for s in subjects
        if s.get("object") == "vocabulary"
        and not subject_is_hidden(s)
        and passes_progress_filter(s, assignment_index, args)
    ]


def kanji_subjects(
    subjects: Sequence[dict],
    assignment_index: Dict[int, dict],
    args: argparse.Namespace,
    *,
    min_srs: Optional[int] = None,
) -> List[dict]:
    return [
        s
        for s in subjects
        if s.get("object") == "kanji"
        and not subject_is_hidden(s)
        and passes_progress_filter(s, assignment_index, args, min_srs=min_srs)
    ]


def all_wk_kanji_subjects(subjects: Sequence[dict], args: argparse.Namespace) -> List[dict]:
    """All WaniKani kanji up to max_level (ignores started/unlocked filters)."""
    return [
        s
        for s in subjects
        if s.get("object") == "kanji"
        and s["data"].get("level", 999) <= args.max_level
        and not subject_is_hidden(s)
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
    return len(collect_phonetic_drill_items(families))


def collect_phonetic_drill_items(
    families: Sequence[Tuple[str, str, List[dict]]],
) -> List[Tuple[dict, str, List[dict]]]:
    """One card per (kanji, phonetic component), not per reading branch."""
    by_kanji_comp: Dict[Tuple[int, str], dict] = {}
    comp_members: DefaultDict[str, Dict[int, dict]] = defaultdict(dict)
    for comp, _reading, members in families:
        for member in members:
            comp_members[comp][member["id"]] = member
            key = (member["id"], comp)
            if key not in by_kanji_comp:
                by_kanji_comp[key] = member
    items: List[Tuple[dict, str, List[dict]]] = []
    for (kanji_id, comp), kanji in by_kanji_comp.items():
        members = sorted(
            comp_members[comp].values(),
            key=lambda item: item["data"].get("level", 999),
        )
        items.append((kanji, comp, members))
    items.sort(
        key=lambda item: (
            item[0]["data"].get("level", 999),
            item[1],
            item[0]["data"].get("characters") or "",
        ),
    )
    return items


def wk_onyomi_label(kanji: dict) -> str:
    onyomi = wk_onyomi_readings(kanji)
    return "、".join(onyomi) if onyomi else "—"


def phonetic_component_readings_label(comp: str, keisei_phonetic: dict) -> str:
    readings = (keisei_phonetic.get(comp) or {}).get("readings") or []
    return "、".join(reading for reading in readings if reading)


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



def add_item_note(
    deck,
    model,
    subject,
    indexes,
    pitch_index,
    kind: str,
    confusables_html: str = "",
    *,
    reading_audio_field: str = "",
) -> None:
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
            reading_audio_field,
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
    preview_levels: RadicalPreviewLevels,
) -> Tuple[Path, genanki.Deck]:
    selected = [
        r for r in radicals
        if int(r["data"].get("level") or 999) in preview_levels.level_set()
    ]

    deck = genanki.Deck(DECK_IDS["radicals"], DECK_NAMES["radicals"])
    model = make_radical_model()
    media_names, media_paths = ensure_radical_media_files(selected)
    deck.wk_media_files = media_paths

    for radical in sorted(selected, key=lambda r: (r["data"].get("level", 999), radical_display(r))):
        data = radical["data"]
        level = int(data.get("level") or 0)
        status = radical_level_status(level, preview_levels)
        if radical_is_learned(radical, indexes["assignments"]):
            status += " · started"

        meanings = html.escape("; ".join(primary_meanings(radical)))
        radical_text = radical_display_html(radical, media_names)
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
                stable_guid(
                    "radical",
                    radical["id"],
                    preview_levels.current,
                    preview_levels.next,
                    preview_levels.locked_next,
                ),
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
                radical_priority(radical, preview_levels),
                f"wk-level-{level}",
            ],
            guid=stable_guid(
                "radical",
                radical["id"],
                preview_levels.current,
                preview_levels.next,
                preview_levels.locked_next,
            ),
        )
        deck.add_note(note)

    out = output_dir / "wk_radicals_current_next.apkg"
    write_apkg(deck, out)
    return out, deck



def build_leech_deck(
    items,
    indexes,
    pitch_index,
    output_dir: Path,
    *,
    reading_audio: bool = True,
    wk_voice: str = "Kyoko",
    tts_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh_reading_audio: bool = False,
) -> Tuple[Path, genanki.Deck]:
    from wk_reading_audio import DEFAULT_WK_READING_VOICE, ReadingAudioProgressBar, prepare_reading_audio_field

    deck = genanki.Deck(DECK_IDS["leeches"], DECK_NAMES["leeches"])
    model = make_item_model()
    media_dir = output_dir / "media/leech_reading"
    media_files: List[str] = []
    if reading_audio:
        print(f"Leech reading audio (vocab: WK {wk_voice}, kanji: TTS {tts_voice})...")
    progress = ReadingAudioProgressBar(len(items), label="Leech reading audio", enabled=reading_audio)
    audio_ok = 0
    for item in items:
        audio_field = ""
        if reading_audio:
            audio_field, media_paths = prepare_reading_audio_field(
                item,
                media_dir,
                wk_voice=wk_voice or DEFAULT_WK_READING_VOICE,
                tts_voice=tts_voice,
                refresh=refresh_reading_audio,
            )
            if media_paths:
                media_files.extend(media_paths)
                audio_ok += 1
            progress.advance()
        add_item_note(
            deck,
            model,
            item,
            indexes,
            pitch_index,
            "leech",
            reading_audio_field=audio_field,
        )
    if reading_audio:
        progress.finish(ok_count=audio_ok)
    out = output_dir / "wk_leeches.apkg"
    write_apkg(deck, out, media_files=media_files or None)
    return out, deck


def build_pitch_leeches_deck(
    items,
    indexes,
    pitch_index,
    output_dir: Path,
    *,
    reading_audio: bool = True,
    wk_voice: str = "Kyoko",
    tts_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh_reading_audio: bool = False,
) -> Optional[Tuple[Path, genanki.Deck]]:
    from wk_reading_audio import DEFAULT_WK_READING_VOICE, ReadingAudioProgressBar, prepare_reading_audio_field

    pitch_items = [i for i in items if pitch_for(i, pitch_index).get("pitch") or pitch_for(i, pitch_index).get("pattern")]
    if not pitch_items:
        return None
    deck = genanki.Deck(DECK_IDS["pitch-leeches"], DECK_NAMES["pitch-leeches"])
    model = make_item_model()
    media_dir = output_dir / "media/pitch_leech_reading"
    media_files: List[str] = []
    progress = ReadingAudioProgressBar(len(pitch_items), label="Pitch leech reading audio", enabled=reading_audio)
    audio_ok = 0
    for item in pitch_items:
        audio_field = ""
        if reading_audio:
            audio_field, media_paths = prepare_reading_audio_field(
                item,
                media_dir,
                wk_voice=wk_voice or DEFAULT_WK_READING_VOICE,
                tts_voice=tts_voice,
                refresh=refresh_reading_audio,
            )
            if media_paths:
                media_files.extend(media_paths)
                audio_ok += 1
            progress.advance()
        add_item_note(
            deck,
            model,
            item,
            indexes,
            pitch_index,
            "pitch-leech",
            reading_audio_field=audio_field,
        )
    if reading_audio:
        progress.finish(ok_count=audio_ok)
    out = output_dir / "wk_pitch_leeches.apkg"
    write_apkg(deck, out, media_files=media_files or None)
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
    keisei_phonetic: dict,
    keisei_kanji: dict,
    started_kanji_ids: Set[int],
    all_kanji_by_char: Dict[str, dict],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    interval_map: Optional[Mapping[int, int]] = None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["phonetic-families"], DECK_NAMES["phonetic-families"])
    model = make_phonetic_drill_model()
    template_label = MODEL_TEMPLATE_VERSIONS["phonetic_drill"]
    stage_interval_map = interval_map or load_srs_stage_interval_days(
        CACHE_DIR / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME
    )
    for kanji, comp, family_members in collect_phonetic_drill_items(families):
        data = kanji["data"]
        char = data.get("characters") or ""
        is_started = kanji["id"] in started_kanji_ids
        meaning = "; ".join(primary_meanings(kanji))
        level = data.get("level", "?")
        progress = "started" if is_started else "preview"
        wk_readings = wk_onyomi_label(kanji)
        comp_readings = phonetic_component_readings_label(comp, keisei_phonetic)
        anchor_html = phonetic_anchor_back_html(
            comp,
            family_members,
            kanji["id"],
            started_kanji_ids,
            all_kanji_by_char,
            keisei_kanji,
        )
        meta = f"WK Level {level} · {progress} · phonetic {comp} · template {template_label}"
        guid = stable_guid("phonetic-drill", kanji["id"], comp)
        reading_tags = [f"reading-{r}" for r in wk_onyomi_readings(kanji)]
        note_tags = [
            "wanikani",
            "phonetic-drill",
            "phonetic-family",
            "priority-low",
            f"phonetic-{comp}",
            progress,
            *reading_tags,
        ]
        note_tags.extend(supplementary_import_tags(kanji, assignment_index, interval_map=stage_interval_map))
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                str(kanji["id"]),
                html.escape(char),
                "What is the on'yomi reading?",
                html.escape(wk_readings),
                html.escape(comp),
                html.escape(comp_readings),
                anchor_html,
                html.escape(meaning),
                html.escape(meta),
            ],
            tags=note_tags,
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
    component_radicals = [
        radical_index[component_id]
        for kanji in kanji_items
        for component_id in kanji["data"].get("component_subject_ids") or []
        if component_id in radical_index
    ]
    media_names, media_paths = ensure_radical_media_files(component_radicals)
    deck.wk_media_files = media_paths
    for kanji in kanji_items:
        data = kanji["data"]
        guid = stable_guid("kanji-radical", kanji["id"])
        radicals_back = kanji_radicals_back_html(kanji, radical_index, media_names)
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
                kanji_radicals_front_html(kanji, radical_index, media_names),
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


def build_conjugation_deck(
    deck_key: str,
    drills: Sequence[ConjugationDrill],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    tag_kind: str,
    interval_map: Optional[Mapping[int, int]] = None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS[deck_key], DECK_NAMES[deck_key])
    model = make_conjugation_model()
    template_label = MODEL_TEMPLATE_VERSIONS["conjugation"]
    stage_interval_map = interval_map or load_srs_stage_interval_days(
        CACHE_DIR / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME
    )
    outfile = (
        "wk_conjugations_verbs.apkg"
        if deck_key == "conjugations-verbs"
        else "wk_conjugations_adjectives.apkg"
    )
    for drill in drills:
        vocab = drill.vocab
        level = vocab["data"].get("level", "?")
        guid = stable_guid(tag_kind, vocab["id"], drill.form_key)
        meaning = "; ".join(primary_meanings(vocab))
        class_label = conjugation_class_label(drill.word_class)
        meta = f"WK L{level} · {class_label} · template {template_label} · {drill.form_key}"
        note_tags = [
            "wanikani",
            tag_kind,
            drill.word_class.replace("_", "-"),
            drill.form_key,
            f"wk-level-{level}",
        ]
        note_tags.extend(supplementary_import_tags(vocab, assignment_index, interval_map=stage_interval_map))
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                str(vocab["id"]),
                html.escape(drill.prompt),
                html.escape(drill.dict_expr),
                html.escape(drill.dict_reading),
                html.escape(meaning),
                html.escape(class_label),
                html.escape(drill.conj_expr),
                html.escape(drill.conj_expr),
                html.escape(drill.conj_reading),
                html.escape(meta),
            ],
            tags=note_tags,
            guid=guid,
        )
        deck.add_note(note)
    out = output_dir / outfile
    write_apkg(deck, out)
    return out, deck


def build_conjugation_verb_deck(
    drills: Sequence[ConjugationDrill],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    interval_map: Optional[Mapping[int, int]] = None,
) -> Tuple[Path, genanki.Deck]:
    return build_conjugation_deck(
        "conjugations-verbs",
        drills,
        output_dir,
        assignment_index,
        tag_kind="conjugation-verb",
        interval_map=interval_map,
    )


def build_conjugation_adjective_deck(
    drills: Sequence[ConjugationDrill],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    interval_map: Optional[Mapping[int, int]] = None,
) -> Tuple[Path, genanki.Deck]:
    return build_conjugation_deck(
        "conjugations-adjectives",
        drills,
        output_dir,
        assignment_index,
        tag_kind="conjugation-adjective",
        interval_map=interval_map,
    )


def build_conjugation_reverse_deck(
    drills: Sequence[ConjugationDrill],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    interval_map: Optional[Mapping[int, int]] = None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["conjugations-reverse"], DECK_NAMES["conjugations-reverse"])
    model = make_conjugation_reverse_model()
    template_label = MODEL_TEMPLATE_VERSIONS["conjugation_reverse"]
    stage_interval_map = interval_map or load_srs_stage_interval_days(
        CACHE_DIR / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME
    )
    for drill in drills:
        vocab = drill.vocab
        level = vocab["data"].get("level", "?")
        guid = stable_guid("conjugation-reverse", vocab["id"], drill.form_key)
        meaning = "; ".join(primary_meanings(vocab))
        class_label = conjugation_class_label(drill.word_class)
        meta = f"WK L{level} · {class_label} · template {template_label} · {drill.form_key}"
        note_tags = [
            "wanikani",
            "conjugation-reverse",
            drill.word_class.replace("_", "-"),
            drill.form_key,
            f"wk-level-{level}",
        ]
        note_tags.extend(supplementary_import_tags(vocab, assignment_index, interval_map=stage_interval_map))
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                str(vocab["id"]),
                html.escape(drill.prompt),
                html.escape(drill.dict_expr),
                html.escape(drill.dict_expr),
                html.escape(drill.dict_reading),
                html.escape(meaning),
                html.escape(drill.conj_expr),
                html.escape(drill.conj_reading),
                html.escape(meta),
            ],
            tags=note_tags,
            guid=guid,
        )
        deck.add_note(note)
    out = output_dir / "wk_conjugations_reverse.apkg"
    write_apkg(deck, out)
    return out, deck


def build_word_class_deck(
    deck_key: str,
    vocab_items: Sequence[dict],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    drill_kind: str,
    interval_map: Optional[Mapping[int, int]] = None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS[deck_key], DECK_NAMES[deck_key])
    model = make_word_class_model()
    template_label = MODEL_TEMPLATE_VERSIONS["word_class"]
    stage_interval_map = interval_map or load_srs_stage_interval_days(
        CACHE_DIR / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME
    )
    guid_kind = "verb-type" if drill_kind == "verb" else "adjective-type"
    tag_kind = "verb-type" if drill_kind == "verb" else "adjective-type"
    prompt = (
        "What type of verb is this?"
        if drill_kind == "verb"
        else "What type of adjective is this?"
    )
    outfile = "wk_verb_types.apkg" if drill_kind == "verb" else "wk_adjective_types.apkg"

    for vocab in vocab_items:
        if drill_kind == "verb":
            class_key = verb_drill_class(vocab)
            if not class_key:
                continue
            class_answer = verb_type_drill_answer(vocab, class_key)
            class_hint = VERB_DRILL_CLASS_HINT[class_key]
        else:
            class_key = adjective_drill_class(vocab)
            if not class_key:
                continue
            class_answer = ADJECTIVE_DRILL_CLASS_ANSWER[class_key]
            class_hint = ADJECTIVE_DRILL_CLASS_HINT[class_key]

        data = vocab["data"]
        expr = data.get("characters") or ""
        reading = first_reading(vocab)
        level = data.get("level", "?")
        meaning = "; ".join(primary_meanings(vocab))
        guid = stable_guid(guid_kind, vocab["id"])
        meta = f"WK L{level} · template {template_label} · {class_key}"
        note_tags = [
            "wanikani",
            tag_kind,
            class_key.replace("_", "-"),
            f"wk-level-{level}",
        ]
        note_tags.extend(supplementary_import_tags(vocab, assignment_index, interval_map=stage_interval_map))
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                str(vocab["id"]),
                html.escape(prompt),
                html.escape(expr),
                html.escape(reading),
                html.escape(meaning),
                html.escape(class_answer),
                html.escape(class_hint),
                html.escape(meta),
            ],
            tags=note_tags,
            guid=guid,
        )
        deck.add_note(note)

    out = output_dir / outfile
    write_apkg(deck, out)
    return out, deck


def build_verb_type_deck(
    vocab_items: Sequence[dict],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    interval_map: Optional[Mapping[int, int]] = None,
) -> Tuple[Path, genanki.Deck]:
    return build_word_class_deck(
        "verb-types",
        vocab_items,
        output_dir,
        assignment_index,
        drill_kind="verb",
        interval_map=interval_map,
    )


def build_adjective_type_deck(
    vocab_items: Sequence[dict],
    output_dir: Path,
    assignment_index: Dict[int, dict],
    *,
    interval_map: Optional[Mapping[int, int]] = None,
) -> Tuple[Path, genanki.Deck]:
    return build_word_class_deck(
        "adjective-types",
        vocab_items,
        output_dir,
        assignment_index,
        drill_kind="adjective",
        interval_map=interval_map,
    )


def build_vocab_cloze_deck(
    cloze_items: Sequence[VocabClozeItem],
    assignment_index: Dict[int, dict],
    output_dir: Path,
    *,
    vocab_reading_index: Optional[Dict[str, List[dict]]] = None,
    sentence_audio: bool = False,
    sentence_audio_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh_sentence_audio: bool = False,
    interval_map: Optional[Mapping[int, int]] = None,
) -> Tuple[Path, genanki.Deck, List[str]]:
    deck = genanki.Deck(DECK_IDS["vocab-cloze"], DECK_NAMES["vocab-cloze"])
    model = make_vocab_cloze_model()
    template_label = MODEL_TEMPLATE_VERSIONS["vocab_cloze"]
    stage_interval_map = interval_map or load_srs_stage_interval_days(
        CACHE_DIR / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME
    )
    media_dir = output_dir / WK_SHARED_MEDIA_SUBDIR
    media_files: List[str] = []
    audio_ok = 0
    audio_cached = 0
    audio_new = 0
    if sentence_audio:
        require_edge_tts()
        print(f"Sentence audio (voice={sentence_audio_voice}, cache={SENTENCE_AUDIO_CACHE_DIR})...")
    reading_index = vocab_reading_index or {}
    for item in cloze_items:
        vocab = item.vocab
        data = vocab["data"]
        expr = data.get("characters") or ""
        type_expr = vocab_cloze_type_expression(vocab, reading_index)
        wk_spelling_note = (
            f"WK spelling in sentences: {expr}"
            if type_expr != expr
            else ""
        )
        reading = first_reading(vocab)
        meaning = "; ".join(primary_meanings(vocab))
        level = data.get("level", "?")
        srs = srs_stage(vocab, assignment_index)
        guid = stable_guid("vocab-cloze", vocab["id"])
        meta = f"WK L{level} · SRS {srs} · template {template_label}"
        sentence_audio_field = ""
        if sentence_audio:
            tts_text = prepare_sentence_for_tts(
                item.full_sentence,
                item.vocab,
                source_ja=item.source_ja,
            )
            basename = tts_audio_basename(tts_text, sentence_audio_voice)
            if basename:
                dest = media_dir / basename
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
        form_hint = vocab_cloze_form_hint(
            item.sentence_en,
            type_expression=type_expr,
            expression=expr,
        )
        note_tags = [
            "wanikani",
            "vocab-cloze",
            f"wk-level-{level}",
        ]
        note_tags.extend(supplementary_import_tags(vocab, assignment_index, interval_map=stage_interval_map))
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                str(vocab["id"]),
                html.escape(item.cloze_sentence),
                html.escape(meaning),
                html.escape(form_hint),
                html.escape(expr),
                html.escape(type_expr),
                html.escape(wk_spelling_note),
                html.escape(reading),
                html.escape(meaning),
                html.escape(item.full_sentence),
                html.escape(item.sentence_en),
                sentence_audio_field,
                html.escape(meta),
            ],
            tags=note_tags,
            guid=guid,
        )
        deck.add_note(note)
    if sentence_audio:
        print(
            f"Sentence audio: {audio_ok}/{len(cloze_items)} cards "
            f"({audio_new} new, {audio_cached} cached)"
        )
    out = output_dir / "wk_vocab_cloze.apkg"
    write_apkg(deck, out, media_files=media_files or None)
    return out, deck, media_files


def count_pitch_leeches(leeches: Sequence[dict], pitch_index: Dict[Tuple[str, str], dict]) -> int:
    return sum(
        1
        for item in leeches
        if pitch_for(item, pitch_index).get("pitch") or pitch_for(item, pitch_index).get("pattern")
    )


def normalize_wanted_decks(wanted: Set[str]) -> Set[str]:
    normalized = set(wanted)
    if "core" in normalized:
        normalized.discard("core")
        normalized.update(("core-radical", "core-kanji", "core-vocabulary"))
    if "conjugations" in normalized:
        normalized.discard("conjugations")
        normalized.add("conjugations-verbs")
        normalized.add("conjugations-adjectives")
    return normalized


def wanted_decks(args: argparse.Namespace) -> Set[str]:
    if args.deck != "all":
        return normalize_wanted_decks({args.deck})
    generate_decks = getattr(args, "generate_decks", None) or DEFAULT_GENERATE_DECKS
    return normalize_wanted_decks(set(generate_decks))


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
    conjugation_verb_drills: Sequence[ConjugationDrill],
    conjugation_adjective_drills: Sequence[ConjugationDrill],
    conjugation_reverse_drills: Sequence[ConjugationDrill],
    verb_type_items: Sequence[dict],
    adjective_type_items: Sequence[dict],
    vocab_cloze_items: Sequence[VocabClozeItem],
    grammar_card_count: int,
    tae_kim_exercise_card_count: int = 0,
    dictation_item_count: int = 0,
    pitch_index: Dict[Tuple[str, str], dict],
) -> List[str]:
    names: List[str] = []
    if "core-radical" in wanted:
        names.append(DECK_NAMES["core-radical"])
    if "core-kanji" in wanted:
        names.append(DECK_NAMES["core-kanji"])
    if "core-vocabulary" in wanted:
        names.append(DECK_NAMES["core-vocabulary"])
    if "radicals" in wanted and radical_items:
        names.append(DECK_NAMES["radicals"])
    if "phonetic-families" in wanted and phonetic_families:
        names.append(DECK_NAMES["phonetic-families"])
    if "conjugations-verbs" in wanted and conjugation_verb_drills:
        names.append(DECK_NAMES["conjugations-verbs"])
    if "conjugations-adjectives" in wanted and conjugation_adjective_drills:
        names.append(DECK_NAMES["conjugations-adjectives"])
    if "conjugations-reverse" in wanted and conjugation_reverse_drills:
        names.append(DECK_NAMES["conjugations-reverse"])
    if "verb-types" in wanted and verb_type_items:
        names.append(DECK_NAMES["verb-types"])
    if "adjective-types" in wanted and adjective_type_items:
        names.append(DECK_NAMES["adjective-types"])
    if "vocab-cloze" in wanted and vocab_cloze_items:
        names.append(DECK_NAMES["vocab-cloze"])
    if "grammar" in wanted and grammar_card_count:
        names.append(DECK_NAMES["grammar"])
    if "tae-kim-exercises" in wanted and tae_kim_exercise_card_count:
        names.append(DECK_NAMES["tae-kim-exercises"])
    if "dictation" in wanted and dictation_item_count:
        names.append(DECK_NAMES["dictation"])
    if "pitch-leeches" in wanted and leeches and count_pitch_leeches(leeches, pitch_index):
        names.append(DECK_NAMES["pitch-leeches"])
    return names


def build_run_history_row(
    args: argparse.Namespace,
    user: dict,
    *,
    dry_run: bool,
    preview_levels: RadicalPreviewLevels,
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
    conjugation_verb_drills: Sequence[ConjugationDrill],
    conjugation_adjective_drills: Sequence[ConjugationDrill],
    conjugation_reverse_drills: Sequence[ConjugationDrill],
    verb_type_items: Sequence[dict],
    adjective_type_items: Sequence[dict],
    vocab_cloze_items: Sequence[VocabClozeItem],
    grammar_card_count: int,
    tae_kim_exercise_card_count: int = 0,
    dictation_item_count: int = 0,
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
        "radical_level_current": preview_levels.current,
        "radical_level_next": preview_levels.next,
        "radical_level_locked_next": preview_levels.locked_next,
        "leeches": len(leeches),
        "verb_pairs": len(verb_pairs),
        "confusables": len(confusables),
        "phonetic_families": len(phonetic_families),
        "reading_keywords": len(reading_keywords),
        "kanji_radical_breakdown": len(kanji_radical_items),
        "conjugation_verb_drills": len(conjugation_verb_drills),
        "conjugation_adjective_drills": len(conjugation_adjective_drills),
        "conjugation_reverse_drills": len(conjugation_reverse_drills),
        "verb_type_cards": len(verb_type_items),
        "adjective_type_cards": len(adjective_type_items),
        "vocab_cloze": len(vocab_cloze_items),
        "grammar_cards": grammar_card_count,
        "tae_kim_exercise_cards": tae_kim_exercise_card_count,
        "dictation_items": dictation_item_count,
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


def write_filtered_deck_suggestions(
    output_dir: Path,
    *,
    max_tae_kim_lesson: Optional[str] = None,
) -> Path:
    path = output_dir / "anki_filtered_decks.txt"
    lines = ["Suggested Anki filtered decks", ""]
    for index, deck in enumerate(
        effective_filtered_deck_definitions(max_tae_kim_lesson=max_tae_kim_lesson),
        start=1,
    ):
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


def _tae_kim_current_lesson_tag(max_tae_kim_lesson: str) -> Optional[str]:
    """Lesson tag for the reading lesson referenced by a grammar cap string."""
    from tae_kim_mapping import tae_kim_lesson_from_cap, tae_kim_lesson_tags

    lesson = tae_kim_lesson_from_cap(max_tae_kim_lesson)
    if lesson is None or not lesson.has_cards:
        return None
    return next(
        (tag for tag in tae_kim_lesson_tags(lesson) if tag.startswith("tk-lesson-")),
        None,
    )


def grammar_context_current_lesson_filtered_deck(max_tae_kim_lesson: str) -> Optional[dict]:
    """Filtered deck for Hanabira/context grammar on the current reading lesson only."""
    lesson_tag = _tae_kim_current_lesson_tag(max_tae_kim_lesson)
    if lesson_tag is None:
        return None
    return {
        "name": "WK::Grammar · Current Tae Kim lesson",
        "search": (
            f'deck:"{DECK_NAMES["grammar"]}" '
            f"tag:{lesson_tag} -is:suspended"
        ),
        "limit": 20,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    }


def grammar_exercise_current_lesson_filtered_deck(max_tae_kim_lesson: str) -> Optional[dict]:
    """Filtered deck for Tae Kim practice exercises on the current reading lesson only."""
    lesson_tag = _tae_kim_current_lesson_tag(max_tae_kim_lesson)
    if lesson_tag is None:
        return None
    return {
        "name": "WK::Grammar Exercises · Current Tae Kim lesson",
        "search": (
            f'deck:"{DECK_NAMES["tae-kim-exercises"]}" '
            f"tag:tae-kim-exercise tag:{lesson_tag} -is:suspended"
        ),
        "limit": 20,
        "order": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS,
    }


def effective_filtered_deck_definitions(
    *,
    max_tae_kim_lesson: Optional[str] = None,
) -> List[dict]:
    decks = list(FILTERED_DECK_DEFINITIONS)
    if max_tae_kim_lesson:
        for builder in (
            grammar_context_current_lesson_filtered_deck,
            grammar_exercise_current_lesson_filtered_deck,
        ):
            current = builder(max_tae_kim_lesson)
            if current is not None:
                decks.append(current)
    return decks


def normalized_filtered_deck_definitions(
    *,
    max_tae_kim_lesson: Optional[str] = None,
) -> List[dict]:
    return [
        {
            **spec,
            "reschedule": spec.get("reschedule", FILTERED_DECK_RESCHEDULE_DEFAULT),
        }
        for spec in effective_filtered_deck_definitions(max_tae_kim_lesson=max_tae_kim_lesson)
    ]


def write_filtered_decks_json(
    output_dir: Path,
    *,
    max_tae_kim_lesson: Optional[str] = None,
) -> Path:
    path = output_dir / FILTERED_DECKS_JSON
    payload = {
        "generator_version": VERSION,
        "order_labels": {"relative_overdueness": FILTERED_DECK_ORDER_RELATIVE_OVERDUENESS},
        "reschedule_default": FILTERED_DECK_RESCHEDULE_DEFAULT,
        "decks": normalized_filtered_deck_definitions(max_tae_kim_lesson=max_tae_kim_lesson),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_deck_options_json(output_dir: Path, deck_names: Sequence[str]) -> Path:
    path = output_dir / DECK_OPTIONS_JSON
    payload = {
        "generator_version": VERSION,
        "preset": {
            "name": WK_FSRS_PRESET_NAME,
            "desired_retention": WK_FSRS_DEFAULT_RETENTION,
            "new_per_day": WK_FSRS_DEFAULT_NEW_PER_DAY,
            "reviews_per_day": WK_FSRS_DEFAULT_REVIEWS_PER_DAY,
        },
        "deck_names": sorted(set(deck_names)),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def default_sync_anki_addons() -> bool:
    return sys.platform == "darwin"


def maybe_sync_anki_addons(args: argparse.Namespace) -> None:
    if args.dry_run or not args.sync_addons:
        return
    script = Path(__file__).resolve().parent / "scripts" / "sync_anki_addons.sh"
    if not script.is_file():
        print(
            "Warning: add-on sync script missing; copy anki_addon/ manually.",
            file=sys.stderr,
        )
        return
    print()
    print("Syncing Anki add-ons...")
    try:
        result = subprocess.run(
            ["/bin/bash", str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            print(result.stdout.rstrip())
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            print(f"Add-on sync failed: {detail}", file=sys.stderr)
            print(f"Retry manually: {script}", file=sys.stderr)
    except OSError as exc:
        print(f"Add-on sync failed: {exc}", file=sys.stderr)
        print(f"Retry manually: {script}", file=sys.stderr)


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

Anki treats note-type updates and note updates separately. "Always update" on one
prompt may not refresh both. If card layout or typed answers look wrong after import:
  1. Re-import and accept UPDATE for the note type AND for existing notes
  2. In Browse, spot-check TypeExpression / SentenceAudio on a card
  3. If fields are still old: delete the deck (or its notes) and import again
     — loses scheduling for that deck only; other WK decks are unaffected

If Anki reports notes could not be imported (often exactly 246 notes):
  That count matches the conjugation + conjugation-reverse decks. It usually means
  Anki kept an older note type schema without the type-in fields (TypeConjExpression,
  TypeDictExpression). Re-import and choose "Always update" for:
    - {NOTE_TYPE_NAMES['conjugation']} (template {MODEL_TEMPLATE_VERSIONS['conjugation']})
    - {NOTE_TYPE_NAMES['conjugation_reverse']} (template {MODEL_TEMPLATE_VERSIONS['conjugation_reverse']})
  Also update if prompted:
    - {NOTE_TYPE_NAMES['vocab_cloze']} (template {MODEL_TEMPLATE_VERSIONS['vocab_cloze']})
    - {NOTE_TYPE_NAMES['grammar_cloze']} (template {MODEL_TEMPLATE_VERSIONS['grammar_cloze']})

If Anki reports exactly 40 notes could not be imported:
  That count matches the Japanese Grammar Exercises deck (Tae Kim practice pages) at
  your current --grammar-max-tae-kim-lesson cap. Those cards share the same note type
  as Japanese Grammar Context ({NOTE_TYPE_NAMES['grammar_cloze']}). Common causes:
    1. Note type not updated to template {MODEL_TEMPLATE_VERSIONS['grammar_cloze']}
       (FormHint field added in v4) — re-import and choose Always update for the note
       type AND for existing notes.
    2. A prior partial import left conflicting copies — in Browse, filter deck
       "Japanese Grammar Exercises"; if empty or broken, delete that deck (notes only)
       and re-import {BUNDLE_FILENAME}.
    3. Duplicate note type — Tools → Manage Note Types; there should be only one
       "{NOTE_TYPE_NAMES['grammar_cloze']}". Remove stray duplicates if you created
       "Create new note type" on an earlier import.

Grammar sentence audio (template {MODEL_TEMPLATE_VERSIONS['grammar_cloze']}):
  - Plays on the card BACK only — flip after typing the answer.
  - Choose UPDATE for {NOTE_TYPE_NAMES['grammar_cloze']} so the back template includes SentenceAudio.
  - In Browse, SentenceAudio should be [sound:wk_grammar_....mp3]; build log should show N/N cards.
  - Install edge-tts for TTS; use --no-grammar-sentence-audio only to skip generation.

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

Deck options: each .apkg embeds the "{WK_FSRS_PRESET_NAME}" preset. After import,
run Tools → WK Apply Deck Options (anki_addon/wk_deck_options, reads {DECK_OPTIONS_JSON})
to assign that preset to all WK decks. Enable FSRS globally in Anki if prompted.

If templates still do not update after import:
  1. Tools → Manage Note Types → Cards — confirm CSS starts with WK template comment
  2. Re-import; choose UPDATE for both the note type and existing notes
  3. Delete the deck (or all notes in it) and re-import if fields/answers stay stale
     (common after generator changes to TypeExpression or cloze text)
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
    print("  Also accept UPDATE for existing notes (separate prompt); delete deck if answers stay stale.")
    print("  If ~246 notes fail: update Conjugation + Conjugation Reverse note types (type-in fields).")
    print(f"  Conjugation: {NOTE_TYPE_NAMES['conjugation']} · template {MODEL_TEMPLATE_VERSIONS['conjugation']}")
    print(f"  Grammar: {NOTE_TYPE_NAMES['grammar_cloze']} · template {MODEL_TEMPLATE_VERSIONS['grammar_cloze']}")
    print(
        "  If import says 40 notes failed: that is usually Japanese Grammar Exercises — "
        f"update {NOTE_TYPE_NAMES['grammar_cloze']} to template {MODEL_TEMPLATE_VERSIONS['grammar_cloze']} "
        "and re-import (see out/anki_import_instructions.txt)."
    )
    print("  Grammar sentence audio plays on the card BACK (flip first); update that note type on import.")
    print(f"  Full instructions: out/anki_import_instructions.txt")
    print(f"  Filtered decks: install anki_addon/wk_filtered_decks, then Tools → WK Setup Filtered Decks")
    print(f"  Deck options: install anki_addon/wk_deck_options, then Tools → WK Apply Deck Options")


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
    keisei_phonetic: dict,
    reading_keywords: Sequence[ReadingKeywordEntry],
    kanji_radical_items: Sequence[dict],
    conjugation_verb_drills: Sequence[ConjugationDrill],
    conjugation_adjective_drills: Sequence[ConjugationDrill],
    conjugation_reverse_drills: Sequence[ConjugationDrill],
    verb_type_items: Sequence[dict],
    adjective_type_items: Sequence[dict],
    vocab_cloze_items: Sequence[VocabClozeItem],
    grammar_cards: Sequence[Any],
    tae_kim_exercise_cards: Sequence[Any],
    dictation_items: Sequence[Any],
    radical_items: Sequence[dict],
    preview_levels: RadicalPreviewLevels,
    pitch_index: Dict[Tuple[str, str], dict],
    review_index: Dict[int, dict],
    vocab_reading_index: Optional[Dict[str, List[dict]]] = None,
) -> None:
    print("\nDRY RUN — no .apkg files will be written")
    print("=" * 60)
    wanted = wanted_decks(args)

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
                f"{kanji['data'].get('characters') or '?'} · WK {wk_onyomi_label(kanji)} · phonetic {comp} → {phonetic_component_readings_label(comp, keisei_phonetic or {})}"
                for kanji, comp, _ in collect_phonetic_drill_items(phonetic_families)
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
    if "conjugations-verbs" in wanted:
        preview_deck_section(
            DECK_NAMES["conjugations-verbs"],
            [
                f"{drill.dict_expr} ({drill.dict_reading}) → {drill.conj_expr} ({drill.conj_reading}) · {drill.prompt}"
                for drill in conjugation_verb_drills
            ],
        )
    if "conjugations-adjectives" in wanted:
        preview_deck_section(
            DECK_NAMES["conjugations-adjectives"],
            [
                f"{drill.dict_expr} ({drill.dict_reading}) → {drill.conj_expr} ({drill.conj_reading}) · {drill.prompt}"
                for drill in conjugation_adjective_drills
            ],
        )
    if "conjugations-reverse" in wanted:
        preview_deck_section(
            DECK_NAMES["conjugations-reverse"],
            [
                f"{drill.conj_expr} ({drill.conj_reading}) → {drill.dict_expr} ({drill.dict_reading}) · {drill.prompt}"
                for drill in conjugation_reverse_drills
            ],
        )
    if "verb-types" in wanted:
        preview_deck_section(
            DECK_NAMES["verb-types"],
            [
                f"{v['data'].get('characters') or '?'} ({first_reading(v)}) → "
                f"{verb_type_drill_answer(v, verb_drill_class(v) or '')}"
                for v in verb_type_items
                if verb_drill_class(v)
            ],
        )
    if "adjective-types" in wanted:
        preview_deck_section(
            DECK_NAMES["adjective-types"],
            [
                f"{v['data'].get('characters') or '?'} ({first_reading(v)}) → "
                f"{ADJECTIVE_DRILL_CLASS_ANSWER.get(adjective_drill_class(v) or '', '?')}"
                for v in adjective_type_items
                if adjective_drill_class(v)
            ],
        )
    if "vocab-cloze" in wanted:
        reading_index = vocab_reading_index or {}
        preview_deck_section(
            DECK_NAMES["vocab-cloze"],
            [
                (
                    f"{item.vocab['data'].get('characters') or '?'} "
                    f"(type {vocab_cloze_type_expression(item.vocab, reading_index)}) · "
                    f"{item.cloze_sentence}"
                )
                if vocab_cloze_type_expression(item.vocab, reading_index)
                != (item.vocab["data"].get("characters") or "")
                else f"{item.vocab['data'].get('characters') or '?'} · {item.cloze_sentence}"
                for item in vocab_cloze_items
            ],
        )
    if "grammar" in wanted:
        preview_deck_section(
            DECK_NAMES["grammar"],
            [
                f"JLPT {item.jlpt} · {item.title[:50]} · {item.cloze_sentence}"
                for item in grammar_cards
            ],
        )
    if "tae-kim-exercises" in wanted:
        preview_deck_section(
            DECK_NAMES["tae-kim-exercises"],
            [
                f"{item.title[:50]} · {item.cloze_sentence}"
                for item in tae_kim_exercise_cards
            ],
        )
    if "dictation" in wanted:
        preview_deck_section(
            DECK_NAMES["dictation"],
            [
                f"{item.expression} ({item.reading}) · {item.meaning[:40]}"
                for item in dictation_items
            ],
        )
    if "radicals" in wanted:
        selected = [
            r for r in radical_items
            if int(r["data"].get("level") or 999) in preview_levels.level_set()
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
    print(f"\nVocab cloze filter: min_srs={args.vocab_cloze_min_srs} (Master+ when 7, Guru+ when 5)")
    print(
        f"Conjugation filter: min_srs={args.conjugation_min_srs} "
        f"(Master+ when {WK_SRS_STAGE_MASTER}, Guru+ when {WK_SRS_STAGE_GURU_1})"
    )
    if getattr(args, "grammar_max_tae_kim_lesson", None) and not getattr(args, "conjugation_no_tae_kim_cap", False):
        cap = resolve_tae_kim_conjugation_cap(args)
        if cap is not None:
            print(
                f"Conjugation Tae Kim cap: lesson={args.grammar_max_tae_kim_lesson}, "
                f"verb forms={sorted(cap.verb_forms) or 'none'}, "
                f"i-adj={bool(cap.i_adjective_forms)}, na-adj={bool(cap.na_adjective_forms)}"
            )
    print(
        f"Phonetic families filter: min_srs={PHONETIC_FAMILIES_MIN_SRS} "
        f"(Apprentice+; independent of --min-srs)"
    )
    if "grammar" in wanted:
        print(
            f"Grammar filter: max_jlpt={args.grammar_max_jlpt}, "
            f"max_tae_kim_section={args.grammar_max_tae_kim_section}, "
            f"max_tae_kim_lesson={args.grammar_max_tae_kim_lesson or 'off'}, "
            f"examples_per_point={args.grammar_max_examples}, "
            f"max_unknown_kanji={args.grammar_max_unknown_kanji}"
        )
    if "tae-kim-exercises" in wanted:
        print(
            f"Tae Kim exercise filter: max_tae_kim_section={args.grammar_max_tae_kim_section}, "
            f"max_tae_kim_lesson={args.grammar_max_tae_kim_lesson or 'off'}"
        )
    if "dictation" in wanted:
        print(
            f"Dictation filter: min_srs={args.dictation_min_srs}, voice={args.dictation_voice} "
            f"(WaniKani native pronunciation)"
        )
    if args.sentence_audio:
        print(f"Vocab sentence audio: on (voice={args.sentence_audio_voice})")
    else:
        print("Vocab sentence audio: off (pass --sentence-audio to generate; plays on card back)")
    if args.grammar_sentence_audio:
        print(f"Grammar sentence audio: on (voice={args.sentence_audio_voice})")
    else:
        print("Grammar sentence audio: off (--no-grammar-sentence-audio)")
    print("\nRe-run without --dry-run to write decks.")


def wk_deck_config_path(config_path: Optional[str | Path] = None) -> Path:
    if config_path is None:
        return Path(__file__).resolve().parent / WK_DECK_CONFIG_FILENAME
    candidate = Path(config_path)
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parent / candidate
    return candidate


def resolve_config_path_from_argv(argv: Optional[Sequence[str]] = None) -> Optional[Path]:
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path: Optional[str] = None
    from_config = False
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--config":
            if index + 1 >= len(argv):
                raise SystemExit("error: --config requires a path")
            config_path = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--config="):
            config_path = arg.split("=", 1)[1]
            index += 1
            continue
        if arg == "--from-config":
            from_config = True
            index += 1
            continue
        index += 1
    if config_path is not None:
        return wk_deck_config_path(config_path)
    if from_config:
        return wk_deck_config_path()
    return None


def load_wk_deck_config(config_path: Optional[Path] = None) -> dict:
    if config_path is None or not config_path.is_file():
        return {}
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{config_path.name} must contain a JSON object.")
    return payload


def parser_defaults_from_config(config: dict) -> dict:
    """Map wk_deck_config.json keys to argparse dest names."""
    defaults: dict[str, Any] = {}
    if "deck" in config:
        defaults["deck"] = config["deck"]
    if config.get("generate_decks") is not None:
        defaults["generate_decks"] = list(config["generate_decks"])
    if "output_dir" in config:
        defaults["output_dir"] = config["output_dir"]
    for flag in (
        "only_started",
        "only_unlocked",
        "only_burned",
        "refresh_cache",
        "no_bundle",
        "dry_run",
        "no_wk_progress_filter",
        "sync_anki_addons",
    ):
        if flag in config:
            defaults[flag] = bool(config[flag])
    if "min_srs" in config:
        defaults["min_srs"] = int(config["min_srs"])
    if "max_level" in config:
        defaults["max_level"] = int(config["max_level"])
    if "vocab_cloze_min_srs" in config:
        defaults["vocab_cloze_min_srs"] = int(config["vocab_cloze_min_srs"])
    if "conjugation_min_srs" in config:
        defaults["conjugation_min_srs"] = int(config["conjugation_min_srs"])
    if "sentence_audio_voice" in config:
        defaults["sentence_audio_voice"] = config["sentence_audio_voice"]
    if "refresh_sentence_audio" in config:
        defaults["refresh_sentence_audio"] = bool(config["refresh_sentence_audio"])
    if "reading_audio" in config:
        defaults["reading_audio"] = bool(config["reading_audio"])
    if "reading_voice" in config:
        defaults["reading_voice"] = config["reading_voice"]
    if "refresh_reading_audio" in config:
        defaults["refresh_reading_audio"] = bool(config["refresh_reading_audio"])

    grammar = config.get("grammar") or {}
    grammar_key_map = {
        "max_jlpt": "grammar_max_jlpt",
        "max_tae_kim_section": "grammar_max_tae_kim_section",
        "max_tae_kim_lesson": "grammar_max_tae_kim_lesson",
        "max_examples": "grammar_max_examples",
        "max_unknown_kanji": "grammar_max_unknown_kanji",
        "no_wk_filter": "grammar_no_wk_filter",
        "sentence_audio": "grammar_sentence_audio",
    }
    for config_key, dest in grammar_key_map.items():
        if config_key in grammar:
            defaults[dest] = grammar[config_key]

    vocab_cloze = config.get("vocab_cloze") or {}
    if "sentence_audio" in vocab_cloze:
        defaults["sentence_audio"] = bool(vocab_cloze["sentence_audio"])

    dictation = config.get("dictation") or {}
    dictation_key_map = {
        "min_srs": "dictation_min_srs",
        "voice": "dictation_voice",
        "refresh_audio": "refresh_dictation_audio",
    }
    for config_key, dest in dictation_key_map.items():
        if config_key in dictation:
            defaults[dest] = dictation[config_key]

    core = config.get("core") or {}
    core_bool_keys = {
        "bootstrap_scheduling",
        "import_all_subjects",
        "suspend_unstarted",
        "reading_audio",
        "refresh_reading_audio",
    }
    core_key_map = {
        "bootstrap_scheduling": "bootstrap_wk_scheduling",
        "import_all_subjects": "core_import_all",
        "suspend_unstarted": "core_suspend_unstarted",
        "reading_audio": "reading_audio",
        "reading_voice": "reading_voice",
        "refresh_reading_audio": "refresh_reading_audio",
    }
    for config_key, dest in core_key_map.items():
        if config_key in core:
            value = core[config_key]
            defaults[dest] = bool(value) if config_key in core_bool_keys else value

    return defaults


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    from grammar_decks import (
        GRAMMAR_DEFAULT_EXAMPLES_PER_POINT,
        GRAMMAR_DEFAULT_MAX_JLPT,
        GRAMMAR_DEFAULT_MAX_TAE_KIM_SECTION,
        GRAMMAR_DEFAULT_MAX_UNKNOWN_KANJI,
        JLPT_LEVELS,
    )
    from dictation_decks import DEFAULT_DICTATION_VOICE, DICTATION_DEFAULT_MIN_SRS
    from tae_kim_mapping import load_tae_kim_sections

    config_path = resolve_config_path_from_argv(argv)
    cfg = parser_defaults_from_config(load_wk_deck_config(config_path))

    parser = argparse.ArgumentParser(
        description="Generate update-safe Anki decks from WaniKani and grammar sources.",
        epilog=(
            f"Defaults can live in {WK_DECK_CONFIG_FILENAME} beside this script; "
            "use --from-config or --config PATH. CLI flags override config."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=f"Load defaults from a JSON config file (default path: {WK_DECK_CONFIG_FILENAME}).",
    )
    parser.add_argument(
        "--from-config",
        action="store_true",
        help=f"Load defaults from {WK_DECK_CONFIG_FILENAME} beside this script.",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--deck", choices=[
        "leeches", "verb-pairs", "confusables", "phonetic-families",
        "pitch-leeches", "radicals", "reading-keywords", "kanji-radicals",
        "conjugations",
        "conjugations-verbs",
        "conjugations-adjectives",
        "conjugations-reverse",
        "verb-types", "adjective-types", "vocab-cloze", "dictation", "grammar",
        "tae-kim-exercises", "core", "all",
    ], default=cfg.get("deck", "all"))
    parser.add_argument("--refresh-cache", action="store_true", default=cfg.get("refresh_cache", False))
    parser.add_argument("--output-dir", default=cfg.get("output_dir", str(OUTPUT_DIR)))
    parser.add_argument("--pitch-csv")
    parser.add_argument("--yomitan-dict")
    parser.add_argument("--write-pitch-template")
    parser.add_argument("--max-level", type=int, default=cfg.get("max_level", 60))
    parser.add_argument("--radical-current-level", type=int, default=None, help="Override detected current WaniKani level for radical preview.")
    parser.add_argument("--min-srs", type=int, default=cfg.get("min_srs", 1))
    parser.add_argument("--only-unlocked", action="store_true", default=cfg.get("only_unlocked", False))
    parser.add_argument("--only-started", action="store_true", default=cfg.get("only_started", False))
    parser.add_argument(
        "--no-wk-progress-filter",
        action="store_true",
        default=cfg.get("no_wk_progress_filter", False),
        help="Import all supplementary subjects; suspend until core matures (replaces --only-started gating).",
    )
    parser.add_argument("--only-burned", action="store_true", default=cfg.get("only_burned", False))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=cfg.get("dry_run", False),
        help="Preview generated deck contents without writing .apkg files.",
    )
    parser.add_argument(
        "--no-bundle",
        action="store_true",
        default=cfg.get("no_bundle", False),
        help="Do not write the combined out/wk_all.apkg file.",
    )
    sync_addons_default = cfg.get("sync_anki_addons")
    if sync_addons_default is None:
        sync_addons_default = default_sync_anki_addons()
    parser.add_argument(
        "--sync-addons",
        action=argparse.BooleanOptionalAction,
        default=bool(sync_addons_default),
        help="After generating, rsync anki_addon/ into Anki's add-ons folder (default: on macOS).",
    )
    parser.add_argument(
        "--bootstrap-wk-scheduling",
        action=argparse.BooleanOptionalAction,
        default=cfg.get("bootstrap_wk_scheduling", False),
        help="Patch core card ivl/due/type from WK assignments (one-time migration).",
    )
    parser.add_argument(
        "--core-suspend-unstarted",
        action=argparse.BooleanOptionalAction,
        default=cfg.get("core_suspend_unstarted", True),
        help="Suspend core notes without WK started_at (default: suspend + wk-locked).",
    )
    parser.add_argument(
        "--vocab-cloze-min-srs",
        type=int,
        default=cfg.get("vocab_cloze_min_srs", VOCAB_CLOZE_DEFAULT_MIN_SRS),
        help="Minimum WK SRS stage for vocabulary context cloze cards (7 = Master+, 5 = Guru+).",
    )
    parser.add_argument(
        "--conjugation-min-srs",
        type=int,
        default=cfg.get("conjugation_min_srs", CONJUGATION_DEFAULT_MIN_SRS),
        help="Minimum WK SRS stage for conjugation decks (7 = Master+, 5 = Guru+).",
    )
    parser.add_argument(
        "--conjugation-no-tae-kim-cap",
        action="store_true",
        default=cfg.get("conjugation_no_tae_kim_cap", False),
        help="Do not limit conjugation forms to --grammar-max-tae-kim-lesson progress.",
    )
    parser.add_argument(
        "--dictation-min-srs",
        type=int,
        default=cfg.get("dictation_min_srs", DICTATION_DEFAULT_MIN_SRS),
        help="Minimum WK SRS stage for dictation cards (7 = Master+, 5 = Guru+).",
    )
    parser.add_argument(
        "--dictation-voice",
        choices=["Kyoko", "Kenichi"],
        default=cfg.get("dictation_voice", DEFAULT_DICTATION_VOICE),
        help="WaniKani voice actor for dictation audio (default: Kyoko).",
    )
    parser.add_argument(
        "--refresh-dictation-audio",
        action="store_true",
        default=cfg.get("refresh_dictation_audio", False),
        help="Re-download WaniKani pronunciation audio instead of using cache.",
    )
    parser.add_argument(
        "--sentence-audio",
        action=argparse.BooleanOptionalAction,
        default=cfg.get("sentence_audio", False),
        help="Generate sentence audio for vocab-cloze cards via edge-tts (plays on card back).",
    )
    parser.add_argument(
        "--grammar-sentence-audio",
        action=argparse.BooleanOptionalAction,
        default=cfg.get("grammar_sentence_audio", True),
        help="Generate sentence audio for grammar-cloze cards via edge-tts (plays on card back; default: on).",
    )
    parser.add_argument(
        "--sentence-audio-voice",
        default=cfg.get("sentence_audio_voice", DEFAULT_SENTENCE_AUDIO_VOICE),
        help=f"edge-tts voice for sentence audio (default: {DEFAULT_SENTENCE_AUDIO_VOICE}).",
    )
    parser.add_argument(
        "--refresh-sentence-audio",
        action="store_true",
        default=cfg.get("refresh_sentence_audio", False),
        help="Re-download sentence audio instead of using the local TTS cache.",
    )
    from wk_reading_audio import DEFAULT_WK_READING_VOICE

    parser.add_argument(
        "--reading-audio",
        action=argparse.BooleanOptionalAction,
        default=cfg.get("reading_audio", True),
        help="Generate reading pronunciation on core/leech cards (WK native for vocab, TTS for kanji).",
    )
    parser.add_argument(
        "--reading-voice",
        choices=["Kyoko", "Kenichi"],
        default=cfg.get("reading_voice", DEFAULT_WK_READING_VOICE),
        help="WaniKani voice for vocabulary reading audio (default: Kyoko).",
    )
    parser.add_argument(
        "--refresh-reading-audio",
        action="store_true",
        default=cfg.get("refresh_reading_audio", False),
        help="Re-download reading audio instead of using cache.",
    )
    parser.add_argument(
        "--grammar-max-jlpt",
        choices=list(JLPT_LEVELS),
        default=cfg.get("grammar_max_jlpt", GRAMMAR_DEFAULT_MAX_JLPT),
        help="Include grammar points through this JLPT level (default: N2).",
    )
    tae_kim_section_nums = [str(section.num) for section in load_tae_kim_sections()]
    parser.add_argument(
        "--grammar-max-tae-kim-section",
        type=int,
        choices=[int(num) for num in tae_kim_section_nums],
        default=cfg.get("grammar_max_tae_kim_section", GRAMMAR_DEFAULT_MAX_TAE_KIM_SECTION),
        help=(
            "Include grammar through this Tae Kim chapter (3=Basic Grammar, "
            "4=Essential, 5=Special, 6=Advanced; default: 6)."
        ),
    )
    parser.add_argument(
        "--grammar-max-tae-kim-lesson",
        default=cfg.get("grammar_max_tae_kim_lesson"),
        metavar="CHAPTER:SUBSECTION",
        help=(
            "Cap at a guidetojapanese.org subsection title, e.g. "
            "basic:introduction-to-particles or introduction-to-particles."
        ),
    )
    parser.add_argument(
        "--grammar-max-examples",
        type=int,
        default=cfg.get("grammar_max_examples", GRAMMAR_DEFAULT_EXAMPLES_PER_POINT),
        help="Max example cloze cards per grammar point (default: 2).",
    )
    parser.add_argument(
        "--grammar-max-unknown-kanji",
        type=int,
        default=cfg.get("grammar_max_unknown_kanji", GRAMMAR_DEFAULT_MAX_UNKNOWN_KANJI),
        help="Skip example sentences with more than this many unknown WK kanji (default: 5).",
    )
    parser.add_argument(
        "--grammar-no-wk-filter",
        action="store_true",
        default=cfg.get("grammar_no_wk_filter", False),
        help="Do not filter grammar examples by WaniKani kanji knowledge.",
    )
    parser.add_argument("--leech-incorrect-min", type=int, default=3)
    parser.add_argument("--leech-streak-max", type=int, default=5)
    parser.add_argument("--leech-score-min", type=float, default=1.0, help="Minimum composite leech score after incorrect/streak filters.")
    parser.add_argument("--max-cards", type=int, default=200)
    parser.add_argument("--max-confusable-group-size", type=int, default=7)
    parser.add_argument("--min-family-size", type=int, default=3)
    parser.add_argument("--max-family-members", type=int, default=12)
    parser.add_argument(
        "--verify-conjugations",
        action="store_true",
        help="Run curated conjugation fixture checks and flag suspicious forms in eligible vocab.",
    )
    parser.add_argument(
        "--verify-conjugations-only",
        action="store_true",
        help="Run --verify-conjugations and exit without writing decks.",
    )
    parser.set_defaults(generate_decks=cfg.get("generate_decks"))
    return parser.parse_args(argv)


def run_standalone_grammar_deck(args: argparse.Namespace, output_dir: Path) -> None:
    """Build grammar deck without WaniKani API (grammar-only runs)."""
    from grammar_decks import build_grammar_deck, collect_grammar_cards

    grammar_cards = collect_grammar_cards(
        max_jlpt=args.grammar_max_jlpt,
        max_tae_kim_section=args.grammar_max_tae_kim_section,
        max_tae_kim_lesson=args.grammar_max_tae_kim_lesson,
        max_examples_per_point=args.grammar_max_examples,
        max_unknown_kanji=args.grammar_max_unknown_kanji,
        known_kanji=set(),
        refresh=args.refresh_cache,
    )
    print(
        f"Grammar context cloze: {len(grammar_cards)} "
        f"(JLPT ≤ {args.grammar_max_jlpt}, Tae Kim ≤ §{args.grammar_max_tae_kim_section}, "
        f"{args.grammar_max_examples} ex/point)"
    )
    if args.dry_run:
        preview_deck_section(
            DECK_NAMES["grammar"],
            [f"JLPT {c.jlpt} · {c.title[:50]} · {c.cloze_sentence}" for c in grammar_cards],
        )
        print("\nRe-run without --dry-run to write decks.")
        return
    if not grammar_cards:
        print("No grammar cards created.", file=sys.stderr)
        sys.exit(1)
    path, deck, media = build_grammar_deck(
        grammar_cards,
        output_dir,
        sentence_audio=args.grammar_sentence_audio,
        sentence_audio_voice=args.sentence_audio_voice,
        refresh_sentence_audio=args.refresh_sentence_audio,
    )
    bundle_path: Optional[Path] = None
    if not args.no_bundle:
        bundle_path = output_dir / BUNDLE_FILENAME
        write_bundled_apkg([deck], bundle_path, media_files=media or None)
    print("Created:")
    if bundle_path:
        print(f"  {bundle_path}  ← recommended import")
    print(f"  {path}")
    print_import_verification_help(bundle_path)
    maybe_sync_anki_addons(args)


def run_standalone_tae_kim_exercise_deck(args: argparse.Namespace, output_dir: Path) -> None:
    """Build Tae Kim exercise deck without WaniKani API."""
    from tae_kim_exercise_decks import build_tae_kim_exercise_deck, collect_tae_kim_exercise_cards

    exercise_cards = collect_tae_kim_exercise_cards(
        max_tae_kim_section=args.grammar_max_tae_kim_section,
        max_tae_kim_lesson=args.grammar_max_tae_kim_lesson,
        refresh=args.refresh_cache,
    )
    print(
        f"Tae Kim exercise cloze: {len(exercise_cards)} "
        f"(Tae Kim ≤ §{args.grammar_max_tae_kim_section}, "
        f"lesson cap={args.grammar_max_tae_kim_lesson or 'off'})"
    )
    if args.dry_run:
        preview_deck_section(
            DECK_NAMES["tae-kim-exercises"],
            [f"{c.title[:50]} · {c.cloze_sentence}" for c in exercise_cards],
        )
        print("\nRe-run without --dry-run to write decks.")
        return
    if not exercise_cards:
        print("No Tae Kim exercise cards created.", file=sys.stderr)
        sys.exit(1)
    path, deck, media = build_tae_kim_exercise_deck(
        exercise_cards,
        output_dir,
        sentence_audio=args.grammar_sentence_audio,
        sentence_audio_voice=args.sentence_audio_voice,
        refresh_sentence_audio=args.refresh_sentence_audio,
    )
    bundle_path: Optional[Path] = None
    if not args.no_bundle:
        bundle_path = output_dir / BUNDLE_FILENAME
        write_bundled_apkg([deck], bundle_path, media_files=media or None)
    print("Created:")
    if bundle_path:
        print(f"  {bundle_path}  ← recommended import")
    print(f"  {path}")
    print_import_verification_help(bundle_path)
    maybe_sync_anki_addons(args)


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

    if args.verify_conjugations_only:
        ok = run_verify_conjugations(args, cache_only=True)
        if not ok:
            sys.exit(1)
        return

    if wanted_decks(args) == {"grammar"}:
        run_standalone_grammar_deck(args, output_dir)
        return

    if wanted_decks(args) == {"tae-kim-exercises"}:
        run_standalone_tae_kim_exercise_deck(args, output_dir)
        return

    user = get_cached_user(refresh=args.refresh_cache)
    get_cached_spaced_repetition_systems(refresh=args.refresh_cache)
    srs_interval_map = load_srs_stage_interval_days(CACHE_DIR / WK_SPACED_REPETITION_SYSTEMS_CACHE_NAME)
    subjects = get_cached_collection(
        "subjects",
        params={"types": "vocabulary,kanji,radical"},
        params_key="vocabulary_kanji_radical",
        refresh=args.refresh_cache,
    )
    wanted_preview = wanted_decks(args)
    use_full_assignments = (
        args.no_wk_progress_filter
        or args.bootstrap_wk_scheduling
        or bool(wanted_preview & {"core-radical", "core-kanji", "core-vocabulary", "core"})
    )
    assignment_params = (
        build_core_assignment_params(args) if use_full_assignments else build_assignment_params(args)
    )
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
    phonetic_seed_kanji = kanji_subjects(
        subjects,
        indexes["assignments"],
        args,
        min_srs=supplementary_min_srs(args, PHONETIC_FAMILIES_MIN_SRS),
    )
    radical_items = radical_subjects(subjects, args)
    preview_levels = selected_radical_levels(user, subjects, indexes["assignments"], args)
    if args.verify_conjugations:
        if not run_verify_conjugations(args, vocab_items=vocab_items):
            sys.exit(1)
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
    wanted = wanted_decks(args)
    core_wanted = wanted & {"core-radical", "core-kanji", "core-vocabulary"}
    core_assignment_index = assignment_index
    if core_wanted:
        core_assignment_params = build_core_assignment_params(args)
        core_assignment_key = assignment_params_key(core_assignment_params)
        if core_assignment_key != assignment_key:
            core_assignments = get_cached_collection(
                "assignments",
                params=core_assignment_params,
                params_key=core_assignment_key,
                refresh=args.refresh_cache,
            )
            core_assignment_index = assignment_by_subject_id(core_assignments)
    core_radical_items = radical_subjects(subjects, args) if "core-radical" in wanted else []
    core_kanji_items = all_wk_kanji_subjects(subjects, args) if "core-kanji" in wanted else []
    core_vocab_items: List[dict] = []
    if "core-vocabulary" in wanted:
        from core_decks import all_core_vocab_subjects

        core_vocab_items = all_core_vocab_subjects(subjects, args)
    leeches = (
        find_leeches(subjects, indexes["assignments"], indexes["reviews"], args)
        if "leeches" in wanted or "pitch-leeches" in wanted
        else []
    )
    verb_pairs = find_verb_pairs(vocab_items, args) if "verb-pairs" in wanted else []
    confusables = (
        find_confusable_groups(vocab_items, args) if "confusables" in wanted else []
    )
    phonetic_families = (
        find_phonetic_families(
            phonetic_seed_kanji,
            all_wk_kanji_subjects(subjects, args),
            keisei_databases.get("phonetic", {}),
            keisei_databases.get("kanji", {}),
            args,
        )
        if "phonetic-families" in wanted
        else []
    )
    started_kanji_ids = {item["id"] for item in phonetic_seed_kanji}
    all_kanji_by_char = kanji_by_char(all_wk_kanji_subjects(subjects, args))
    reading_keywords = (
        build_reading_keyword_catalog(subjects) if "reading-keywords" in wanted else []
    )
    kanji_radical_items = (
        find_kanji_radical_breakdown(kanji_items, radical_items, indexes["assignments"], args)
        if "kanji-radicals" in wanted
        else []
    )
    tae_kim_conjugation_cap = resolve_tae_kim_conjugation_cap(args)
    conjugation_verb_drills = (
        collect_conjugation_drills(
            vocab_items,
            indexes["assignments"],
            args,
            min_srs=supplementary_min_srs(args, args.conjugation_min_srs),
            word_classes=VERB_CONJUGATION_WORD_CLASSES,
            tae_kim_cap=tae_kim_conjugation_cap,
        )
        if "conjugations-verbs" in wanted or "conjugations-reverse" in wanted
        else []
    )
    conjugation_adjective_drills = (
        collect_conjugation_drills(
            vocab_items,
            indexes["assignments"],
            args,
            min_srs=supplementary_min_srs(args, args.conjugation_min_srs),
            word_classes=ADJECTIVE_CONJUGATION_WORD_CLASSES,
            tae_kim_cap=tae_kim_conjugation_cap,
        )
        if "conjugations-adjectives" in wanted
        else []
    )
    conjugation_reverse_drills = (
        collect_conjugation_drills(
            vocab_items,
            indexes["assignments"],
            args,
            min_srs=supplementary_min_srs(args, args.conjugation_min_srs),
            word_classes=VERB_CONJUGATION_WORD_CLASSES,
            tae_kim_cap=tae_kim_conjugation_cap,
        )
        if "conjugations-reverse" in wanted
        else []
    )
    verb_type_items = collect_verb_type_items(vocab_items, args) if "verb-types" in wanted else []
    adjective_type_items = (
        collect_adjective_type_items(vocab_items, args) if "adjective-types" in wanted else []
    )
    vocab_cloze_items = (
        collect_vocab_cloze_items(
            vocab_items,
            indexes["assignments"],
            min_srs=supplementary_min_srs(args, args.vocab_cloze_min_srs),
        )
        if "vocab-cloze" in wanted
        else []
    )
    vocab_reading_index = build_vocab_cloze_reading_index(vocab_items) if vocab_cloze_items else {}
    grammar_cards = []
    if "grammar" in wanted:
        from grammar_decks import collect_grammar_cards, known_kanji_from_subjects

        grammar_cards = collect_grammar_cards(
            max_jlpt=args.grammar_max_jlpt,
            max_tae_kim_section=args.grammar_max_tae_kim_section,
            max_tae_kim_lesson=args.grammar_max_tae_kim_lesson,
            max_examples_per_point=args.grammar_max_examples,
            max_unknown_kanji=args.grammar_max_unknown_kanji,
            known_kanji=set()
            if args.grammar_no_wk_filter
            else known_kanji_from_subjects(vocab_items, kanji_items),
            vocab_items=vocab_items,
            refresh=args.refresh_cache,
        )
    tae_kim_exercise_cards = []
    if "tae-kim-exercises" in wanted:
        from tae_kim_exercise_decks import collect_tae_kim_exercise_cards

        tae_kim_exercise_cards = collect_tae_kim_exercise_cards(
            max_tae_kim_section=args.grammar_max_tae_kim_section,
            max_tae_kim_lesson=args.grammar_max_tae_kim_lesson,
            refresh=args.refresh_cache,
        )
    dictation_items = []
    if "dictation" in wanted:
        from dictation_decks import collect_vocab_dictation_items

        dictation_items = collect_vocab_dictation_items(
            vocab_items,
            indexes["assignments"],
            min_srs=supplementary_min_srs(args, args.dictation_min_srs),
            voice_actor=args.dictation_voice,
        )
    core_priority_index: Dict[int, object] = {}
    if "core-radical" in wanted or "core-kanji" in wanted or "core-vocabulary" in wanted:
        from wk_study_priority import build_core_priority_index, write_study_priority_json
        from tae_kim_exercise_decks import collect_tae_kim_section_vocabulary_entries

        tae_kim_priority_entries = collect_tae_kim_section_vocabulary_entries(
            max_tae_kim_section=args.grammar_max_tae_kim_section,
            max_tae_kim_lesson=args.grammar_max_tae_kim_lesson,
            refresh=args.refresh_cache,
        )
        core_priority_index = build_core_priority_index(
            core_radical_items,
            core_kanji_items,
            core_vocab_items,
            tae_kim_priority_entries=tae_kim_priority_entries,
        )
        priority_path = write_study_priority_json(output_dir, core_priority_index)
        print(
            f"Core study priority: {priority_path} ({len(core_priority_index)} subjects, "
            f"{len(tae_kim_priority_entries)} Tae Kim section vocabulary terms)"
        )
    print(f"Eligible vocab: {len(vocab_items)}")
    print(f"Eligible kanji: {len(kanji_items)}")
    print(f"Eligible radicals: {len(radical_items)}")
    print(f"Radical preview levels: current={preview_levels.current}, next={preview_levels.next}, locked_next={preview_levels.locked_next}")
    if leeches:
        print(f"Leeches: {len(leeches)}")
    if verb_pairs:
        print(f"Verb pairs: {len(verb_pairs)}")
    if confusables:
        print(f"Confusable groups: {len(confusables)}")
    if "phonetic-families" in wanted:
        print(f"Phonetic family seed kanji: {len(phonetic_seed_kanji)} (min SRS {PHONETIC_FAMILIES_MIN_SRS})")
        print(f"Phonetic families: {len(phonetic_families)} ({phonetic_drill_note_count(phonetic_families)} drill cards)")
    if reading_keywords:
        print(f"Reading keywords: {len(reading_keywords)}")
    if kanji_radical_items:
        print(f"Kanji radical breakdown: {len(kanji_radical_items)}")
    if conjugation_verb_drills:
        print(f"Verb conjugation drills: {len(conjugation_verb_drills)} (min SRS {args.conjugation_min_srs})")
        if tae_kim_conjugation_cap is not None:
            print(f"  Tae Kim cap: {args.grammar_max_tae_kim_lesson}")
    if conjugation_adjective_drills:
        print(f"Adjective conjugation drills: {len(conjugation_adjective_drills)} (min SRS {args.conjugation_min_srs})")
    if conjugation_reverse_drills:
        print(f"Verb conjugation reverse drills: {len(conjugation_reverse_drills)} (min SRS {args.conjugation_min_srs})")
    if verb_type_items:
        print(f"Verb type cards: {len(verb_type_items)}")
    if adjective_type_items:
        print(f"Adjective type cards: {len(adjective_type_items)}")
    if vocab_cloze_items:
        print(f"Vocabulary context cloze: {len(vocab_cloze_items)} (min SRS {args.vocab_cloze_min_srs})")
    if grammar_cards:
        print(
            f"Grammar context cloze: {len(grammar_cards)} "
            f"(JLPT ≤ {args.grammar_max_jlpt}, Tae Kim ≤ §{args.grammar_max_tae_kim_section}, "
            f"{args.grammar_max_examples} ex/point)"
        )
    if tae_kim_exercise_cards:
        print(
            f"Tae Kim exercise cloze: {len(tae_kim_exercise_cards)} "
            f"(Tae Kim ≤ §{args.grammar_max_tae_kim_section}, "
            f"lesson cap={args.grammar_max_tae_kim_lesson or 'off'})"
        )
    if dictation_items:
        print(
            f"Dictation: {len(dictation_items)} "
            f"(min SRS {args.dictation_min_srs}, voice={args.dictation_voice})"
        )
    if core_radical_items:
        print(f"Core radicals: {len(core_radical_items)} (full catalog ≤ level {args.max_level})")
    if core_kanji_items:
        print(f"Core kanji: {len(core_kanji_items)} (full catalog ≤ level {args.max_level})")
    if core_vocab_items:
        print(f"Core vocabulary: {len(core_vocab_items)} (full catalog ≤ level {args.max_level})")
    if args.bootstrap_wk_scheduling and core_wanted:
        print("WK scheduling bootstrap: enabled for core decks")
    print(f"Pitch entries loaded: {len(pitch_index)}")
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
            conjugation_verb_drills=conjugation_verb_drills,
            conjugation_adjective_drills=conjugation_adjective_drills,
            conjugation_reverse_drills=conjugation_reverse_drills,
            verb_type_items=verb_type_items,
            adjective_type_items=adjective_type_items,
            vocab_cloze_items=vocab_cloze_items,
            grammar_card_count=len(grammar_cards),
            tae_kim_exercise_card_count=len(tae_kim_exercise_cards),
            dictation_item_count=len(dictation_items),
            pitch_index=pitch_index,
        )
        history_path = append_run_history(
            output_dir,
            build_run_history_row(
                args,
                user,
                dry_run=True,
                preview_levels=preview_levels,
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
                conjugation_verb_drills=conjugation_verb_drills,
                conjugation_adjective_drills=conjugation_adjective_drills,
                conjugation_reverse_drills=conjugation_reverse_drills,
                verb_type_items=verb_type_items,
                adjective_type_items=adjective_type_items,
                vocab_cloze_items=vocab_cloze_items,
                grammar_card_count=len(grammar_cards),
                tae_kim_exercise_card_count=len(tae_kim_exercise_cards),
                dictation_item_count=len(dictation_items),
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
            keisei_phonetic=keisei_databases.get("phonetic", {}),
            reading_keywords=reading_keywords,
            kanji_radical_items=kanji_radical_items,
            conjugation_verb_drills=conjugation_verb_drills,
            conjugation_adjective_drills=conjugation_adjective_drills,
            conjugation_reverse_drills=conjugation_reverse_drills,
            verb_type_items=verb_type_items,
            adjective_type_items=adjective_type_items,
            vocab_cloze_items=vocab_cloze_items,
            grammar_cards=grammar_cards,
            tae_kim_exercise_cards=tae_kim_exercise_cards,
            dictation_items=dictation_items,
            radical_items=radical_items,
            preview_levels=preview_levels,
            pitch_index=pitch_index,
            review_index=indexes["reviews"],
            vocab_reading_index=vocab_reading_index,
        )
        return
    created: List[Path] = []
    built_decks: List[genanki.Deck] = []
    bundled_media_files: List[str] = []
    if core_wanted:
        from core_decks import build_core_kanji_deck, build_core_radical_deck, build_core_vocab_deck

        bootstrap = bool(args.bootstrap_wk_scheduling)
        suspend_unstarted = bool(args.core_suspend_unstarted)
        reading_audio_kwargs = {
            "reading_audio": bool(args.reading_audio),
            "wk_voice": args.reading_voice,
            "tts_voice": args.sentence_audio_voice,
            "refresh_reading_audio": bool(args.refresh_reading_audio),
        }
        if "core-radical" in wanted and core_radical_items:
            path, deck = build_core_radical_deck(
                core_radical_items,
                core_assignment_index,
                output_dir,
                bootstrap_scheduling=bootstrap,
                suspend_unstarted=suspend_unstarted,
                priority_index=core_priority_index,
            )
            created.append(path)
            built_decks.append(deck)
            bundled_media_files.extend(getattr(deck, "wk_media_files", []) or [])
        if "core-kanji" in wanted and core_kanji_items:
            path, deck = build_core_kanji_deck(
                core_kanji_items,
                core_assignment_index,
                output_dir,
                bootstrap_scheduling=bootstrap,
                suspend_unstarted=suspend_unstarted,
                priority_index=core_priority_index,
                **reading_audio_kwargs,
            )
            created.append(path)
            built_decks.append(deck)
            bundled_media_files.extend(getattr(deck, "wk_media_files", []) or [])
        if "core-vocabulary" in wanted and core_vocab_items:
            path, deck = build_core_vocab_deck(
                core_vocab_items,
                core_assignment_index,
                output_dir,
                bootstrap_scheduling=bootstrap,
                suspend_unstarted=suspend_unstarted,
                priority_index=core_priority_index,
                **reading_audio_kwargs,
            )
            created.append(path)
            built_decks.append(deck)
            bundled_media_files.extend(getattr(deck, "wk_media_files", []) or [])
    if "radicals" in wanted and radical_items:
        path, deck = build_radical_deck(radical_items, kanji_items, indexes, args, output_dir, preview_levels)
        created.append(path)
        built_decks.append(deck)
    if "leeches" in wanted and leeches:
        path, deck = build_leech_deck(
            leeches,
            indexes,
            pitch_index,
            output_dir,
            reading_audio=bool(args.reading_audio),
            wk_voice=args.reading_voice,
            tts_voice=args.sentence_audio_voice,
            refresh_reading_audio=bool(args.refresh_reading_audio),
        )
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
            keisei_databases.get("phonetic", {}),
            keisei_databases.get("kanji", {}),
            started_kanji_ids,
            all_kanji_by_char,
            output_dir,
            indexes["assignments"],
            interval_map=srs_interval_map,
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
    if "conjugations-verbs" in wanted and conjugation_verb_drills:
        path, deck = build_conjugation_verb_deck(
            conjugation_verb_drills,
            output_dir,
            indexes["assignments"],
            interval_map=srs_interval_map,
        )
        created.append(path)
        built_decks.append(deck)
    if "conjugations-adjectives" in wanted and conjugation_adjective_drills:
        path, deck = build_conjugation_adjective_deck(
            conjugation_adjective_drills,
            output_dir,
            indexes["assignments"],
            interval_map=srs_interval_map,
        )
        created.append(path)
        built_decks.append(deck)
    if "conjugations-reverse" in wanted and conjugation_reverse_drills:
        path, deck = build_conjugation_reverse_deck(
            conjugation_reverse_drills,
            output_dir,
            indexes["assignments"],
            interval_map=srs_interval_map,
        )
        created.append(path)
        built_decks.append(deck)
    if "verb-types" in wanted and verb_type_items:
        path, deck = build_verb_type_deck(
            verb_type_items,
            output_dir,
            indexes["assignments"],
            interval_map=srs_interval_map,
        )
        created.append(path)
        built_decks.append(deck)
    if "adjective-types" in wanted and adjective_type_items:
        path, deck = build_adjective_type_deck(
            adjective_type_items,
            output_dir,
            indexes["assignments"],
            interval_map=srs_interval_map,
        )
        created.append(path)
        built_decks.append(deck)
    if "vocab-cloze" in wanted and vocab_cloze_items:
        path, deck, media = build_vocab_cloze_deck(
            vocab_cloze_items,
            indexes["assignments"],
            output_dir,
            vocab_reading_index=vocab_reading_index,
            sentence_audio=args.sentence_audio,
            sentence_audio_voice=args.sentence_audio_voice,
            refresh_sentence_audio=args.refresh_sentence_audio,
            interval_map=srs_interval_map,
        )
        created.append(path)
        built_decks.append(deck)
        bundled_media_files.extend(media)
    if "grammar" in wanted and grammar_cards:
        from grammar_decks import build_grammar_deck

        path, deck, media = build_grammar_deck(
            grammar_cards,
            output_dir,
            sentence_audio=args.grammar_sentence_audio,
            sentence_audio_voice=args.sentence_audio_voice,
            refresh_sentence_audio=args.refresh_sentence_audio,
        )
        created.append(path)
        built_decks.append(deck)
        bundled_media_files.extend(media)
    if "tae-kim-exercises" in wanted and tae_kim_exercise_cards:
        from tae_kim_exercise_decks import build_tae_kim_exercise_deck

        path, deck, media = build_tae_kim_exercise_deck(
            tae_kim_exercise_cards,
            output_dir,
            sentence_audio=args.grammar_sentence_audio,
            sentence_audio_voice=args.sentence_audio_voice,
            refresh_sentence_audio=args.refresh_sentence_audio,
        )
        created.append(path)
        built_decks.append(deck)
        bundled_media_files.extend(media)
    if "dictation" in wanted and dictation_items:
        from dictation_decks import build_dictation_deck

        path, deck, media = build_dictation_deck(
            dictation_items,
            output_dir,
            indexes["assignments"],
            voice_actor=args.dictation_voice,
            refresh_audio=args.refresh_dictation_audio,
            interval_map=srs_interval_map,
        )
        created.append(path)
        built_decks.append(deck)
        bundled_media_files.extend(media)
    if "pitch-leeches" in wanted and leeches:
        maybe = build_pitch_leeches_deck(
            leeches,
            indexes,
            pitch_index,
            output_dir,
            reading_audio=bool(args.reading_audio),
            wk_voice=args.reading_voice,
            tts_voice=args.sentence_audio_voice,
            refresh_reading_audio=bool(args.refresh_reading_audio),
        )
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
                preview_levels=preview_levels,
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
                conjugation_verb_drills=conjugation_verb_drills,
                conjugation_adjective_drills=conjugation_adjective_drills,
                conjugation_reverse_drills=conjugation_reverse_drills,
                verb_type_items=verb_type_items,
                adjective_type_items=adjective_type_items,
                vocab_cloze_items=vocab_cloze_items,
                grammar_card_count=len(grammar_cards),
                tae_kim_exercise_card_count=len(tae_kim_exercise_cards),
                dictation_item_count=len(dictation_items),
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
        write_bundled_apkg(
            built_decks,
            bundle_path,
            media_files=bundled_media_files or None,
        )
    settings_path = write_filtered_deck_suggestions(
        output_dir,
        max_tae_kim_lesson=args.grammar_max_tae_kim_lesson,
    )
    filtered_json_path = write_filtered_decks_json(
        output_dir,
        max_tae_kim_lesson=args.grammar_max_tae_kim_lesson,
    )
    deck_options_json_path = write_deck_options_json(
        output_dir,
        [deck.name for deck in built_decks],
    )
    instructions_path = write_import_instructions(output_dir)
    history_path = append_run_history(
        output_dir,
        build_run_history_row(
            args,
            user,
            dry_run=False,
            preview_levels=preview_levels,
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
            conjugation_verb_drills=conjugation_verb_drills,
            conjugation_adjective_drills=conjugation_adjective_drills,
            conjugation_reverse_drills=conjugation_reverse_drills,
            verb_type_items=verb_type_items,
            adjective_type_items=adjective_type_items,
            vocab_cloze_items=vocab_cloze_items,
            grammar_card_count=len(grammar_cards),
            tae_kim_exercise_card_count=len(tae_kim_exercise_cards),
            dictation_item_count=len(dictation_items),
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
    print(f"  {deck_options_json_path}")
    print(f"  {instructions_path}")
    print(f"  {history_path}")
    print_import_verification_help(bundle_path)
    maybe_sync_anki_addons(args)


if __name__ == "__main__":
    main()
