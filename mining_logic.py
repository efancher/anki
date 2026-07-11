"""
mining_logic.py

Duplicate-key helpers for Migaku immersion cards (Anki first-field dedup).
"""

from __future__ import annotations

import re
import unicodedata

MINING_DUPLICATE_KEY_SEP = "|"
_KANA_TO_ASCII = str.maketrans(
    "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロワヲンー",
    "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろわをんー",
)


def normalize_mining_text(text: str) -> str:
    """Normalize text for duplicate-key comparison."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text.strip())
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def normalize_mining_reading(reading: str) -> str:
    if not reading:
        return ""
    return normalize_mining_text(reading).translate(_KANA_TO_ASCII)


def mining_duplicate_key(expression: str, sentence: str = "") -> str:
    """
    Anki first-field duplicate key for mined cards.

    Same expression in different sentences → different keys.
    Empty sentence → expression-only key (term mining).
    """
    expr = normalize_mining_text(expression)
    sent = normalize_mining_text(sentence)
    if not sent:
        return expr
    return f"{expr}{MINING_DUPLICATE_KEY_SEP}{sent}"
