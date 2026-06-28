"""
wk_reading_audio.py

Reading pronunciation for Anki cards: WaniKani native audio for vocabulary,
edge-tts for kanji readings (WK has no kanji pronunciation clips).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional, Tuple

import requests

from wk_decks import (
    CACHE_DIR,
    DEFAULT_SENTENCE_AUDIO_VOICE,
    ensure_sentence_audio_file,
    first_reading,
    primary_readings,
)

PRONUNCIATION_AUDIO_CACHE_DIR = CACHE_DIR / "pronunciation_audio"
DEFAULT_WK_READING_VOICE = "Kyoko"
WK_READING_VOICES = ("Kyoko", "Kenichi")

READING_AUDIO_CSS = """
.reading-audio { margin: 10px auto 6px; }
"""

_VOICE_SLUG_RE = re.compile(r"[^a-z0-9]+", re.I)


def voice_actor_slug(name: str) -> str:
    return _VOICE_SLUG_RE.sub("", name.lower()) or "voice"


def _audio_extension(content_type: str, url: str) -> str:
    lowered = (content_type or "").lower()
    if "mpeg" in lowered or url.lower().endswith(".mp3"):
        return "mp3"
    if "webm" in lowered or url.lower().endswith(".webm"):
        return "webm"
    if "ogg" in lowered:
        return "ogg"
    return "mp3"


def reading_audio_basename(subject: dict, voice_actor: str, ext: str) -> str:
    kind = subject.get("object") or "subject"
    slug = voice_actor_slug(voice_actor)
    return f"wk_reading_{kind}_{subject['id']}_{slug}.{ext}"


def pronunciation_audio_cache_path(vocab_id: int, voice_actor: str, ext: str) -> Path:
    slug = voice_actor_slug(voice_actor)
    return PRONUNCIATION_AUDIO_CACHE_DIR / f"wk_dictation_{vocab_id}_{slug}.{ext}"


def dictation_audio_basename(vocab_id: int, voice_actor: str, ext: str) -> str:
    """Legacy dictation deck media name (same cache as reading audio for vocab)."""
    slug = voice_actor_slug(voice_actor)
    return f"wk_dictation_{vocab_id}_{slug}.{ext}"


def select_pronunciation_audio(
    vocab: dict,
    *,
    voice_actor: str = DEFAULT_WK_READING_VOICE,
    prefer_mpeg: bool = True,
) -> Optional[dict]:
    """Pick one pronunciation_audios entry for a vocabulary subject."""
    audios = vocab.get("data", {}).get("pronunciation_audios") or []
    if not audios:
        return None
    matches = [
        entry
        for entry in audios
        if str((entry.get("metadata") or {}).get("voice_actor_name") or "") == voice_actor
    ]
    pool = matches or list(audios)
    if prefer_mpeg:
        for entry in pool:
            content_type = str(entry.get("content_type") or "")
            if "mpeg" in content_type.lower():
                return entry
    return pool[0] if pool else None


def pronunciation_audio_request_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; wk_decks/reading-audio)",
        "Referer": "https://www.wanikani.com/",
    }


def ensure_pronunciation_audio_file(
    vocab: dict,
    *,
    voice_actor: str = DEFAULT_WK_READING_VOICE,
    dest_path: Path,
    refresh: bool = False,
) -> Tuple[bool, bool]:
    """Download WK native vocabulary audio. Returns (success, was_cached)."""
    entry = select_pronunciation_audio(vocab, voice_actor=voice_actor)
    if entry is None:
        return False, False
    url = str(entry.get("url") or "").strip()
    if not url:
        return False, False
    ext = _audio_extension(str(entry.get("content_type") or ""), url)
    cache_path = pronunciation_audio_cache_path(vocab["id"], voice_actor, ext)
    try:
        was_cached = cache_path.is_file() and cache_path.stat().st_size > 0 and not refresh
        if not was_cached:
            PRONUNCIATION_AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            response = requests.get(url, headers=pronunciation_audio_request_headers(), timeout=45)
            response.raise_for_status()
            cache_path.write_bytes(response.content)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache_path, dest_path)
        ok = dest_path.is_file() and dest_path.stat().st_size > 0
        return ok, was_cached and ok
    except (requests.RequestException, OSError) as exc:
        chars = (vocab.get("data") or {}).get("characters") or vocab["id"]
        print(f"  Warning: reading audio failed ({chars}): {exc}")
        return False, False


def reading_tts_text(subject: dict) -> str:
    """Kana text for kanji TTS (first primary reading)."""
    readings = primary_readings(subject)
    if readings:
        return readings[0]
    return first_reading(subject) or ""


def ensure_reading_audio_for_subject(
    subject: dict,
    dest_path: Path,
    *,
    wk_voice: str = DEFAULT_WK_READING_VOICE,
    tts_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh: bool = False,
) -> Tuple[bool, bool]:
    """Ensure reading audio file exists. Returns (success, was_cached)."""
    obj = subject.get("object")
    if obj == "vocabulary":
        return ensure_pronunciation_audio_file(
            subject,
            voice_actor=wk_voice,
            dest_path=dest_path,
            refresh=refresh,
        )
    if obj == "kanji":
        text = reading_tts_text(subject)
        if not text:
            return False, False
        return ensure_sentence_audio_file(text, tts_voice, dest_path, refresh=refresh)
    return False, False


def prepare_reading_audio_field(
    subject: dict,
    media_dir: Path,
    *,
    wk_voice: str = DEFAULT_WK_READING_VOICE,
    tts_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh: bool = False,
) -> Tuple[str, Optional[str]]:
    """
    Download/cache reading audio and return Anki [sound:…] field value plus media path.
    Radicals and other types without readings return ("", None).
    """
    obj = subject.get("object")
    if obj not in {"vocabulary", "kanji"}:
        return "", None

    if obj == "vocabulary":
        entry = select_pronunciation_audio(subject, voice_actor=wk_voice)
        ext = _audio_extension(
            str((entry or {}).get("content_type") or ""),
            str((entry or {}).get("url") or ""),
        )
    else:
        ext = "mp3"

    basename = reading_audio_basename(subject, wk_voice, ext)
    dest = media_dir / basename
    ok, _was_cached = ensure_reading_audio_for_subject(
        subject,
        dest,
        wk_voice=wk_voice,
        tts_voice=tts_voice,
        refresh=refresh,
    )
    if not ok:
        return "", None
    return f"[sound:{basename}]", str(dest.resolve())
