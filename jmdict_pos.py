"""
Offline JMDict POS lookup for conjugation word-class classification.

Downloads/caches jmdict-simplified English JSON under out/ (gitignored) and
builds a compact (expression, reading) → conjugable word_class index.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_JMDICT_DIR = REPO_ROOT / "out"
DEFAULT_JMDICT_JSON_NAME = "jmdict-eng.json"
DEFAULT_JMDICT_INDEX_NAME = "jmdict_pos_index.json"

# Pinned jmdict-simplified eng release (scriptin/jmdict-simplified).
JMDICT_ENG_ZIP_URL = (
    "https://github.com/scriptin/jmdict-simplified/releases/download/"
    "3.6.2%2B20260511143416/jmdict-eng-3.6.2+20260511143416.json.zip"
)

CONJUGABLE_WORD_CLASSES = frozenset(
    {
        "godan",
        "ichidan",
        "suru_verb",
        "irregular_verb",
        "i_adjective",
        "na_adjective",
    }
)

_POS_SPLIT_RE = re.compile(r"[,;/|]+")


def _normalize(text: str) -> str:
    return (text or "").strip()


def lemma_key(expression: str, reading: str) -> str:
    return f"{_normalize(expression)}|{_normalize(reading)}"


def _pos_tokens(raw: str) -> List[str]:
    text = (raw or "").strip().lower()
    if not text:
        return []
    tokens = [part.strip() for part in _POS_SPLIT_RE.split(text) if part.strip()]
    return tokens or [text]


def pos_string_to_word_class(parts_of_speech: str) -> Optional[str]:
    """Map Satori/JMDict POS strings to conjugation word classes."""
    tokens = _pos_tokens(parts_of_speech)
    joined = " ".join(tokens)
    raw = parts_of_speech or ""

    if any(token in {"adj-i", "adj-ix", "い adjective", "i-adjective", "i_adjective"} for token in tokens):
        return "i_adjective"
    if "い adjective" in joined or "i adjective" in joined:
        return "i_adjective"

    if any(token in {"adj-na", "な adjective", "na-adjective", "na_adjective"} for token in tokens):
        return "na_adjective"
    if "な adjective" in joined or "na adjective" in joined:
        return "na_adjective"

    if any(token in {"vk", "kuru", "irregular_verb"} for token in tokens) or "来る" in raw:
        return "irregular_verb"

    if any(
        token.startswith("vs") or token in {"する verb", "suru", "suru_verb", "vs", "vs-i", "vs-s"}
        for token in tokens
    ):
        return "suru_verb"
    if "する verb" in joined or "suru verb" in joined:
        return "suru_verb"

    if any(token.startswith("v1") or token in {"ichidan", "ichidan verb"} for token in tokens):
        return "ichidan"
    if "ichidan" in joined:
        return "ichidan"

    if any(token.startswith("v5") or token in {"godan", "godan verb"} for token in tokens):
        return "godan"
    if "godan" in joined:
        return "godan"

    return None


def jmdict_tags_to_word_class(tags: Sequence[str]) -> Optional[str]:
    """Map JMDict POS tags (v5u, v1, adj-i, …) to conjugation word_class."""
    if not tags:
        return None
    joined = ";".join(str(tag).strip() for tag in tags if str(tag).strip())
    word_class = pos_string_to_word_class(joined)
    if word_class in CONJUGABLE_WORD_CLASSES:
        return word_class
    for tag in tags:
        word_class = pos_string_to_word_class(str(tag))
        if word_class in CONJUGABLE_WORD_CLASSES:
            return word_class
    return None


def _entry_kanji_texts(entry: dict) -> List[str]:
    texts: List[str] = []
    for item in entry.get("kanji") or []:
        text = _normalize(item.get("text") or "")
        if text:
            texts.append(text)
    return texts


def _entry_kana_texts(entry: dict) -> List[str]:
    texts: List[str] = []
    for item in entry.get("kana") or []:
        text = _normalize(item.get("text") or "")
        if text:
            texts.append(text)
    return texts


def _entry_pos_tags(entry: dict) -> List[str]:
    tags: List[str] = []
    seen = set()
    for sense in entry.get("sense") or []:
        for tag in sense.get("partOfSpeech") or []:
            text = _normalize(str(tag))
            if text and text not in seen:
                seen.add(text)
                tags.append(text)
    return tags


def build_jmdict_pos_index(words: Iterable[dict]) -> Dict[str, str]:
    """Build lemma_key → word_class from jmdict-simplified words array."""
    index: Dict[str, str] = {}
    for entry in words:
        tags = _entry_pos_tags(entry)
        word_class = jmdict_tags_to_word_class(tags)
        if not word_class:
            continue
        kanji_texts = _entry_kanji_texts(entry)
        kana_texts = _entry_kana_texts(entry)
        if not kana_texts:
            continue
        surfaces = list(kanji_texts) if kanji_texts else list(kana_texts)
        for surface in surfaces:
            for kana in kana_texts:
                index.setdefault(lemma_key(surface, kana), word_class)
        for kana in kana_texts:
            index.setdefault(lemma_key(kana, kana), word_class)
        # vs nouns conjugate as 〜する compounds.
        if word_class == "suru_verb":
            for surface in surfaces:
                if surface.endswith("する"):
                    continue
                for kana in kana_texts:
                    if kana.endswith("する"):
                        continue
                    index.setdefault(lemma_key(surface + "する", kana + "する"), "suru_verb")
            for kana in kana_texts:
                if not kana.endswith("する"):
                    index.setdefault(lemma_key(kana + "する", kana + "する"), "suru_verb")
    return index


def load_jmdict_words(json_path: Path) -> List[dict]:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        words = payload.get("words")
        if isinstance(words, list):
            return words
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Unexpected JMDict JSON shape in {json_path}")


def write_jmdict_pos_index(index: Dict[str, str], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"by_key": index}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return path


def load_jmdict_pos_index(path: Path) -> Dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("by_key"), dict):
        return {str(k): str(v) for k, v in payload["by_key"].items()}
    if isinstance(payload, dict):
        return {str(k): str(v) for k, v in payload.items() if "|" in str(k)}
    raise ValueError(f"Unexpected JMDict POS index shape in {path}")


def lookup_jmdict_word_class(
    expression: str,
    reading: str,
    index: Dict[str, str],
) -> Optional[str]:
    expr = _normalize(expression)
    read = _normalize(reading)
    if not read:
        return None
    for key in (lemma_key(expr, read), lemma_key(read, read)):
        word_class = index.get(key)
        if word_class in CONJUGABLE_WORD_CLASSES:
            return word_class
    return None


def default_jmdict_json_path(cache_dir: Optional[Path] = None) -> Path:
    return (cache_dir or DEFAULT_JMDICT_DIR) / DEFAULT_JMDICT_JSON_NAME


def default_jmdict_index_path(cache_dir: Optional[Path] = None) -> Path:
    return (cache_dir or DEFAULT_JMDICT_DIR) / DEFAULT_JMDICT_INDEX_NAME


def download_jmdict_eng_json(
    dest: Path,
    *,
    url: str = JMDICT_ENG_ZIP_URL,
) -> Path:
    """Download jmdict-simplified eng zip and extract the JSON to dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "anki-wk-decks/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download JMDict from {url}: {exc}") from exc

    with zipfile.ZipFile(BytesIO(payload)) as archive:
        json_names = [name for name in archive.namelist() if name.endswith(".json")]
        if not json_names:
            raise RuntimeError(f"No JSON found in JMDict zip from {url}")
        # Prefer the largest JSON member (full dictionary).
        json_names.sort(key=lambda name: archive.getinfo(name).file_size, reverse=True)
        with archive.open(json_names[0]) as handle:
            dest.write_bytes(handle.read())
    return dest


def ensure_jmdict_json(
    path: Optional[Path] = None,
    *,
    download: bool = True,
) -> Path:
    dest = path or default_jmdict_json_path()
    if dest.is_file():
        return dest
    if not download:
        raise FileNotFoundError(f"JMDict JSON not found: {dest}")
    return download_jmdict_eng_json(dest)


def build_and_save_jmdict_pos_index(
    json_path: Optional[Path] = None,
    index_path: Optional[Path] = None,
    *,
    download: bool = True,
) -> Tuple[Path, Dict[str, str]]:
    jmdict_path = ensure_jmdict_json(json_path, download=download)
    index = build_jmdict_pos_index(load_jmdict_words(jmdict_path))
    out = write_jmdict_pos_index(index, index_path or default_jmdict_index_path())
    return out, index


def load_or_build_jmdict_pos_index(
    index_path: Optional[Path] = None,
    json_path: Optional[Path] = None,
    *,
    download: bool = True,
    rebuild: bool = False,
) -> Dict[str, str]:
    dest = index_path or default_jmdict_index_path()
    if dest.is_file() and not rebuild:
        return load_jmdict_pos_index(dest)
    _path, index = build_and_save_jmdict_pos_index(
        json_path=json_path,
        index_path=dest,
        download=download,
    )
    return index
