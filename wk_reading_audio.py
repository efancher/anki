"""
wk_reading_audio.py

Reading pronunciation for Anki cards: WaniKani native audio for vocabulary,
edge-tts for kanji readings (WK has no kanji pronunciation clips).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
from pathlib import Path
from typing import List, Optional, TextIO, Tuple

import requests

from wk_decks import (
    CACHE_DIR,
    DEFAULT_SENTENCE_AUDIO_VOICE,
    ensure_sentence_audio_file,
    first_reading,
    primary_readings,
    tts_audio_basename,
)

PRONUNCIATION_AUDIO_CACHE_DIR = CACHE_DIR / "pronunciation_audio"
DEFAULT_WK_READING_VOICE = "Kyoko"
WK_READING_VOICES = ("Kyoko", "Kenichi")

READING_AUDIO_CSS = """
.reading-audio { margin: 10px auto 6px; }
"""

PROGRESS_BAR_WIDTH = 40


def format_progress_line(
    current: int,
    total: int,
    *,
    label: str,
    width: int = PROGRESS_BAR_WIDTH,
) -> str:
    """Format a single-line progress bar (no trailing newline)."""
    total = max(total, 1)
    current = min(max(current, 0), total)
    ratio = current / total
    filled = int(width * ratio)
    if filled >= width:
        bar = "=" * width
    else:
        bar = "=" * filled + ">" + " " * (width - filled - 1)
    pct = int(ratio * 100)
    return f"{label}: [{bar}] {current}/{total} ({pct}%)"


class ReadingAudioProgressBar:
    """TTY progress bar for long reading-audio generation loops."""

    def __init__(
        self,
        total: int,
        *,
        label: str = "Reading audio",
        stream: Optional[TextIO] = None,
        enabled: bool = True,
    ) -> None:
        self.total = max(int(total), 1)
        self.label = label
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = enabled and total > 0
        self.current = 0
        self._is_tty = (
            self.enabled
            and hasattr(self.stream, "isatty")
            and self.stream.isatty()
        )
        self._plain_log_every = max(1, self.total // 100)

    def advance(self) -> None:
        if not self.enabled:
            return
        self.current = min(self.current + 1, self.total)
        if self._is_tty:
            self.stream.write("\r" + format_progress_line(self.current, self.total, label=self.label))
            self.stream.flush()
        elif (
            self.current == 1
            or self.current == self.total
            or self.current % self._plain_log_every == 0
        ):
            print(
                format_progress_line(self.current, self.total, label=self.label),
                file=self.stream,
            )

    def finish(self, *, ok_count: int, detail: str = "") -> None:
        if not self.enabled:
            summary = f"{self.label}: {ok_count}/{self.total} cards"
            if detail:
                summary += f" ({detail})"
            print(summary, file=self.stream)
            return
        suffix = f"{ok_count} with audio"
        if detail:
            suffix += f" · {detail}"
        if self._is_tty:
            self.current = self.total
            line = format_progress_line(self.current, self.total, label=self.label)
            line += f" · {suffix}"
            self.stream.write("\r" + line + "\n")
            self.stream.flush()
        else:
            summary = f"{self.label}: {self.total}/{self.total} cards ({suffix})"
            print(summary, file=self.stream)


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


def reading_filename_slug(reading: str) -> str:
    """Stable ASCII slug for a kana reading (used in kanji audio filenames)."""
    return hashlib.sha256(reading.encode("utf-8")).hexdigest()[:10]


def kanji_tts_readings(subject: dict) -> List[str]:
    """Distinct primary readings to synthesize for a kanji subject."""
    seen: set[str] = set()
    readings: List[str] = []
    for reading in primary_readings(subject):
        if reading and reading not in seen:
            seen.add(reading)
            readings.append(reading)
    if not readings:
        fallback = first_reading(subject)
        if fallback:
            readings.append(fallback)
    return readings


def reading_audio_basename(
    subject: dict,
    voice_actor: str,
    ext: str,
    *,
    reading: Optional[str] = None,
) -> str:
    kind = subject.get("object") or "subject"
    slug = voice_actor_slug(voice_actor)
    if reading:
        rslug = reading_filename_slug(reading)
        if kind == "kanji":
            return f"wk_reading_kanji_{subject['id']}_{rslug}_{slug}.{ext}"
        if kind == "vocabulary":
            return f"wk_reading_vocabulary_{subject['id']}_{rslug}_{slug}.{ext}"
    return f"wk_reading_{kind}_{subject['id']}_{slug}.{ext}"


def pronunciation_audio_cache_path(
    vocab_id: int,
    voice_actor: str,
    ext: str,
    *,
    reading: Optional[str] = None,
) -> Path:
    slug = voice_actor_slug(voice_actor)
    if reading:
        rslug = reading_filename_slug(reading)
        return PRONUNCIATION_AUDIO_CACHE_DIR / f"wk_dictation_{vocab_id}_{rslug}_{slug}.{ext}"
    return PRONUNCIATION_AUDIO_CACHE_DIR / f"wk_dictation_{vocab_id}_{slug}.{ext}"


def pronunciation_from_audio_entry(entry: dict) -> Optional[str]:
    pronunciation = (entry.get("metadata") or {}).get("pronunciation")
    if pronunciation and str(pronunciation).strip():
        return str(pronunciation).strip()
    return None


def select_pronunciation_audio(
    vocab: dict,
    *,
    voice_actor: str = DEFAULT_WK_READING_VOICE,
    prefer_mpeg: bool = True,
    reading: Optional[str] = None,
) -> Optional[dict]:
    """Pick one pronunciation_audios entry for a vocabulary subject."""
    audios = vocab.get("data", {}).get("pronunciation_audios") or []
    if not audios:
        return None

    target_readings: List[str] = []
    if reading:
        target_readings = [reading]
    else:
        target_readings = primary_readings(vocab)

    def voice_matches(entry: dict) -> bool:
        return str((entry.get("metadata") or {}).get("voice_actor_name") or "") == voice_actor

    def reading_matches(entry: dict) -> bool:
        if not target_readings:
            return True
        pron = pronunciation_from_audio_entry(entry)
        return pron in target_readings if pron else False

    def sort_key(entry: dict) -> Tuple[int, int]:
        content_type = str(entry.get("content_type") or "").lower()
        mpeg_rank = 0 if prefer_mpeg and "mpeg" in content_type else 1
        pron = pronunciation_from_audio_entry(entry) or ""
        try:
            reading_rank = target_readings.index(pron)
        except ValueError:
            reading_rank = len(target_readings)
        return mpeg_rank, reading_rank

    candidates = [entry for entry in audios if voice_matches(entry) and reading_matches(entry)]
    if candidates:
        return min(candidates, key=sort_key)

    voice_pool = [entry for entry in audios if voice_matches(entry)]
    if voice_pool:
        if prefer_mpeg:
            for entry in voice_pool:
                if "mpeg" in str(entry.get("content_type") or "").lower():
                    return entry
        return voice_pool[0]

    if prefer_mpeg:
        for entry in audios:
            if "mpeg" in str(entry.get("content_type") or "").lower():
                return entry
    return audios[0]


def dictation_audio_basename(vocab: dict, voice_actor: str, ext: str) -> str:
    """Same packaged filename as core vocab reading audio (one file per vocab/voice/reading)."""
    entry = select_pronunciation_audio(vocab, voice_actor=voice_actor)
    reading = pronunciation_from_audio_entry(entry) if entry else None
    return reading_audio_basename(vocab, voice_actor, ext, reading=reading)


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
    reading: Optional[str] = None,
) -> Tuple[bool, bool]:
    """Download WK native vocabulary audio. Returns (success, was_cached)."""
    entry = select_pronunciation_audio(vocab, voice_actor=voice_actor, reading=reading)
    if entry is None:
        return False, False
    url = str(entry.get("url") or "").strip()
    if not url:
        return False, False
    ext = _audio_extension(str(entry.get("content_type") or ""), url)
    pronunciation = pronunciation_from_audio_entry(entry)
    cache_path = pronunciation_audio_cache_path(
        vocab["id"],
        voice_actor,
        ext,
        reading=pronunciation,
    )
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
    readings = kanji_tts_readings(subject)
    return readings[0] if readings else ""


def ensure_kanji_reading_audio_file(
    subject: dict,
    reading: str,
    dest_path: Path,
    *,
    tts_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh: bool = False,
) -> Tuple[bool, bool]:
    if not reading:
        return False, False
    return ensure_sentence_audio_file(reading, tts_voice, dest_path, refresh=refresh)


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
        return ensure_kanji_reading_audio_file(
            subject,
            text,
            dest_path,
            tts_voice=tts_voice,
            refresh=refresh,
        )
    return False, False


def prepare_reading_audio_field(
    subject: dict,
    media_dir: Path,
    *,
    wk_voice: str = DEFAULT_WK_READING_VOICE,
    tts_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh: bool = False,
) -> Tuple[str, List[str]]:
    """
    Download/cache reading audio and return Anki [sound:…] field value plus media paths.
    Kanji: one clip per primary reading. Vocabulary: one WK native clip.
    Radicals and other types without readings return ("", []).
    """
    obj = subject.get("object")
    if obj not in {"vocabulary", "kanji"}:
        return "", []

    if obj == "vocabulary":
        entry = select_pronunciation_audio(subject, voice_actor=wk_voice)
        pronunciation = pronunciation_from_audio_entry(entry) if entry else None
        ext = _audio_extension(
            str((entry or {}).get("content_type") or ""),
            str((entry or {}).get("url") or ""),
        )
        basename = reading_audio_basename(
            subject,
            wk_voice,
            ext,
            reading=pronunciation,
        )
        dest = media_dir / basename
        ok, _was_cached = ensure_pronunciation_audio_file(
            subject,
            voice_actor=wk_voice,
            dest_path=dest,
            refresh=refresh,
        )
        if not ok:
            return "", []
        return f"[sound:{basename}]", [str(dest.resolve())]

    sound_tags: List[str] = []
    media_paths: List[str] = []
    for reading in kanji_tts_readings(subject):
        basename = reading_audio_basename(subject, wk_voice, "mp3", reading=reading)
        dest = media_dir / basename
        ok, _was_cached = ensure_kanji_reading_audio_file(
            subject,
            reading,
            dest,
            tts_voice=tts_voice,
            refresh=refresh,
        )
        if not ok:
            continue
        sound_tags.append(f"[sound:{basename}]")
        media_paths.append(str(dest.resolve()))
    return "".join(sound_tags), media_paths


def prepare_kana_reading_audio_field(
    reading: str,
    media_dir: Path,
    *,
    vocab: Optional[dict] = None,
    wk_voice: str = DEFAULT_WK_READING_VOICE,
    tts_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh: bool = False,
) -> Tuple[str, List[str]]:
    """
    Audio for a single kana reading on drill cards.
    Uses WK native vocabulary audio when available; otherwise edge-tts.
    """
    plain = (reading or "").strip()
    if not plain:
        return "", []

    if vocab is not None and vocab.get("object") == "vocabulary":
        entry = select_pronunciation_audio(vocab, voice_actor=wk_voice, reading=plain)
        if entry is not None:
            ext = _audio_extension(
                str(entry.get("content_type") or ""),
                str(entry.get("url") or ""),
            )
            pronunciation = pronunciation_from_audio_entry(entry) or plain
            basename = reading_audio_basename(
                vocab,
                wk_voice,
                ext,
                reading=pronunciation,
            )
            dest = media_dir / basename
            ok, _was_cached = ensure_pronunciation_audio_file(
                vocab,
                voice_actor=wk_voice,
                dest_path=dest,
                refresh=refresh,
                reading=plain,
            )
            if ok:
                return f"[sound:{basename}]", [str(dest.resolve())]

    basename = tts_audio_basename(plain, tts_voice)
    dest = media_dir / basename
    ok, _was_cached = ensure_sentence_audio_file(plain, tts_voice, dest, refresh=refresh)
    if not ok:
        return "", []
    return f"[sound:{basename}]", [str(dest.resolve())]
