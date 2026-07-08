"""
wk_sentence_tts.py

Shared sentence TTS for deck generation and wk_immersion: VOICEVOX (local) with
edge-tts fallback when engine is auto.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple, Union

DEFAULT_VOICEVOX_ENGINE_URL = "http://127.0.0.1:50021"
DEFAULT_VOICEVOX_SPEAKER_ID = 3
DEFAULT_EDGE_TTS_VOICE = "ja-JP-NanamiNeural"
DEFAULT_SENTENCE_TTS_ENGINE = "auto"
VOICEVOX_SYNTH_TIMEOUT_SECONDS = 45
EDGE_TTS_SUBPROCESS_TIMEOUT_SECONDS = 60
SENTENCE_AUDIO_PREFETCH_CONCURRENCY = 4


@dataclass(frozen=True)
class SentenceTtsConfig:
    engine: str = DEFAULT_SENTENCE_TTS_ENGINE  # voicevox | edge | auto
    voicevox_engine_url: str = DEFAULT_VOICEVOX_ENGINE_URL
    voicevox_speaker_id: int = DEFAULT_VOICEVOX_SPEAKER_ID
    edge_tts_voice: str = DEFAULT_EDGE_TTS_VOICE

    @classmethod
    def from_mapping(cls, payload: dict) -> "SentenceTtsConfig":
        return cls(
            engine=str(payload.get("engine", DEFAULT_SENTENCE_TTS_ENGINE)),
            voicevox_engine_url=str(
                payload.get("voicevox_engine_url", DEFAULT_VOICEVOX_ENGINE_URL)
            ).rstrip("/"),
            voicevox_speaker_id=int(
                payload.get("voicevox_speaker_id", DEFAULT_VOICEVOX_SPEAKER_ID)
            ),
            edge_tts_voice=str(payload.get("edge_tts_voice", DEFAULT_EDGE_TTS_VOICE)),
        )

    @classmethod
    def edge_only(cls, voice: str) -> "SentenceTtsConfig":
        return cls(engine="edge", edge_tts_voice=voice)


def strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def sentence_audio_cache_key(
    text: str,
    config: SentenceTtsConfig,
    *,
    engine: str,
) -> str:
    plain = strip_html(text).strip()
    voice_part = (
        f"vv:{config.voicevox_speaker_id}"
        if engine == "voicevox"
        else config.edge_tts_voice
    )
    raw = f"{engine}\0{voice_part}\0{plain}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def sentence_audio_cache_path(
    text: str,
    config: SentenceTtsConfig,
    *,
    engine: str,
    cache_dir: Path,
) -> Path:
    ext = ".wav" if engine == "voicevox" else ".mp3"
    key = sentence_audio_cache_key(text, config, engine=engine)
    return cache_dir / f"{key}{ext}"


def engines_to_try(config: SentenceTtsConfig) -> Tuple[str, ...]:
    if config.engine == "auto":
        return ("voicevox", "edge")
    return (config.engine,)


## `format_sentence_tts_label` — human-readable engine summary for logs
def format_sentence_tts_label(config: SentenceTtsConfig) -> str:
    """Describe which sentence TTS engine(s) will be used (for startup logs)."""
    if config.engine == "voicevox":
        return f"VOICEVOX speaker {config.voicevox_speaker_id}"
    if config.engine == "edge":
        return f"edge-tts {config.edge_tts_voice}"
    if voicevox_engine_reachable(config.voicevox_engine_url):
        return (
            f"auto → VOICEVOX speaker {config.voicevox_speaker_id} "
            f"(edge fallback: {config.edge_tts_voice})"
        )
    return (
        f"auto → edge-tts {config.edge_tts_voice} "
        f"(VOICEVOX unreachable at {config.voicevox_engine_url})"
    )


def voicevox_engine_reachable(
    engine_url: str,
    *,
    timeout_seconds: float = 2.0,
) -> bool:
    base = engine_url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/version", timeout=timeout_seconds) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def resolve_python_executable() -> Optional[str]:
    return shutil.which("python3") or shutil.which("python")


def synthesize_voicevox_wav(
    text: str,
    *,
    engine_url: str,
    speaker_id: int,
    timeout_seconds: int = VOICEVOX_SYNTH_TIMEOUT_SECONDS,
) -> Optional[bytes]:
    plain = strip_html(text).strip()
    if not plain:
        return None
    base = engine_url.rstrip("/")
    query_url = (
        f"{base}/audio_query?"
        f"{urllib.parse.urlencode({'text': plain, 'speaker': str(speaker_id)})}"
    )
    try:
        query_req = urllib.request.Request(query_url, data=b"", method="POST")
        with urllib.request.urlopen(query_req, timeout=timeout_seconds) as resp:
            audio_query = json.loads(resp.read().decode("utf-8"))
        synth_url = f"{base}/synthesis?{urllib.parse.urlencode({'speaker': str(speaker_id)})}"
        body = json.dumps(audio_query).encode("utf-8")
        req = urllib.request.Request(
            synth_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            wav = resp.read()
        return wav if wav else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        return None


async def write_edge_tts_mp3(text: str, voice: str, path: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(strip_html(text).strip(), voice)
    await communicate.save(str(path))


def write_edge_tts_mp3_sync(text: str, voice: str, path: Path) -> bool:
    plain = strip_html(text).strip()
    if not plain:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(write_edge_tts_mp3(plain, voice, path))
    except Exception:
        return False
    return path.is_file() and path.stat().st_size > 0


def synthesize_edge_tts_mp3_subprocess(
    text: str,
    *,
    voice: str,
    dest_path: Path,
    python_executable: str,
    script_path: Path,
    timeout_seconds: int = EDGE_TTS_SUBPROCESS_TIMEOUT_SECONDS,
) -> bool:
    plain = strip_html(text).strip()
    if not plain or not python_executable or not script_path.is_file():
        return False
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [python_executable, str(script_path), plain, voice, str(dest_path)],
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and dest_path.is_file() and dest_path.stat().st_size > 0


def sentence_audio_cache_is_usable(cache_path: Path) -> bool:
    return cache_path.is_file() and cache_path.stat().st_size > 0


def _write_cache_file(cache_path: Path, payload: bytes) -> bool:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(payload)
    return sentence_audio_cache_is_usable(cache_path)


def synthesize_sentence_audio_cache(
    text: str,
    config: SentenceTtsConfig,
    cache_path: Path,
    *,
    engine: str,
) -> bool:
    plain = strip_html(text).strip()
    if not plain:
        return False
    if engine == "voicevox":
        wav = synthesize_voicevox_wav(
            plain,
            engine_url=config.voicevox_engine_url,
            speaker_id=config.voicevox_speaker_id,
        )
        return bool(wav and _write_cache_file(cache_path, wav))
    if engine == "edge":
        return write_edge_tts_mp3_sync(plain, config.edge_tts_voice, cache_path)
    return False


def resolve_cached_engine(
    text: str,
    config: SentenceTtsConfig,
    *,
    cache_dir: Path,
) -> Optional[str]:
    plain = strip_html(text).strip()
    if not plain:
        return None
    for engine in engines_to_try(config):
        cache_path = sentence_audio_cache_path(plain, config, engine=engine, cache_dir=cache_dir)
        if sentence_audio_cache_is_usable(cache_path):
            return engine
    return None


def tts_audio_basename(
    text: str,
    voice_or_config: Union[str, SentenceTtsConfig],
    *,
    cache_dir: Optional[Path] = None,
) -> str:
    """Shared Anki media name for TTS clips — dedupes identical sentences across decks."""
    config = (
        SentenceTtsConfig.edge_only(voice_or_config)
        if isinstance(voice_or_config, str)
        else voice_or_config
    )
    plain = strip_html(text).strip()
    if not plain:
        return ""
    if cache_dir is not None:
        cached_engine = resolve_cached_engine(plain, config, cache_dir=cache_dir)
        if cached_engine:
            cache_path = sentence_audio_cache_path(
                plain,
                config,
                engine=cached_engine,
                cache_dir=cache_dir,
            )
            return f"wk_tts_{cache_path.name}"
    preferred = engines_to_try(config)[0]
    ext = ".wav" if preferred == "voicevox" else ".mp3"
    key = sentence_audio_cache_key(plain, config, engine=preferred)
    return f"wk_tts_{key}{ext}"


def require_sentence_tts(config: SentenceTtsConfig) -> None:
    if config.engine == "voicevox":
        return
    if config.engine == "edge":
        require_edge_tts()
        return
    if config.engine == "auto" and not voicevox_engine_reachable(config.voicevox_engine_url):
        require_edge_tts()


def require_edge_tts() -> None:
    try:
        import edge_tts  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "edge-tts is required for sentence audio when VOICEVOX is unavailable. "
            "Install it: pip install edge-tts — or start VOICEVOX / set engine to voicevox."
        ) from exc


def ensure_sentence_audio_file(
    text: str,
    voice_or_config: Union[str, SentenceTtsConfig],
    dest_path: Path,
    *,
    cache_dir: Path,
    refresh: bool = False,
) -> Tuple[bool, bool]:
    """Return (success, was_cached). was_cached is True when synthesis was skipped."""
    config = (
        SentenceTtsConfig.edge_only(voice_or_config)
        if isinstance(voice_or_config, str)
        else voice_or_config
    )
    plain = strip_html(text).strip()
    if not plain:
        return False, False

    for engine in engines_to_try(config):
        cache_path = sentence_audio_cache_path(plain, config, engine=engine, cache_dir=cache_dir)
        was_cached = sentence_audio_cache_is_usable(cache_path) and not refresh
        if not was_cached:
            if engine == "edge":
                require_edge_tts()
            if not synthesize_sentence_audio_cache(plain, config, cache_path, engine=engine):
                continue
            was_cached = False
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache_path, dest_path)
        ok = dest_path.is_file() and dest_path.stat().st_size > 0
        if ok:
            return ok, was_cached
    return False, False


def unique_sentence_audio_texts(texts: Sequence[str]) -> List[str]:
    unique: List[str] = []
    seen: Set[str] = set()
    for text in texts:
        plain = strip_html(text).strip()
        if plain and plain not in seen:
            seen.add(plain)
            unique.append(plain)
    return unique


def _sync_prefetch_one(
    plain: str,
    config: SentenceTtsConfig,
    *,
    cache_dir: Path,
    refresh: bool,
) -> Tuple[bool, bool]:
    for engine in engines_to_try(config):
        cache_path = sentence_audio_cache_path(plain, config, engine=engine, cache_dir=cache_dir)
        was_cached = sentence_audio_cache_is_usable(cache_path) and not refresh
        if was_cached:
            return True, True
        if engine == "edge":
            try:
                require_edge_tts()
            except SystemExit:
                continue
        if synthesize_sentence_audio_cache(plain, config, cache_path, engine=engine):
            return True, False
    return False, False


async def _prefetch_sentence_audio_batch_async(
    texts: Sequence[str],
    config: SentenceTtsConfig,
    *,
    cache_dir: Path,
    refresh: bool,
    concurrency: int,
    progress: object,
) -> Tuple[int, int, int]:
    unique = unique_sentence_audio_texts(texts)
    if not unique:
        return 0, 0, 0
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))
    loop = asyncio.get_running_loop()

    async def run_one(plain: str) -> Tuple[bool, bool]:
        async with semaphore:
            result = await loop.run_in_executor(
                None,
                lambda: _sync_prefetch_one(plain, config, cache_dir=cache_dir, refresh=refresh),
            )
            progress.advance()
            return result

    results = await asyncio.gather(*(run_one(plain) for plain in unique))
    ok = cached = new = 0
    for success, was_cached in results:
        if not success:
            continue
        ok += 1
        if was_cached:
            cached += 1
        else:
            new += 1
    return ok, cached, new


def prefetch_sentence_audio_texts(
    texts: Sequence[str],
    config: SentenceTtsConfig,
    *,
    cache_dir: Path,
    refresh: bool = False,
    label: str = "Sentence audio",
    concurrency: int = SENTENCE_AUDIO_PREFETCH_CONCURRENCY,
) -> Tuple[int, int, int]:
    """Generate missing sentence TTS clips for unique texts with progress and concurrency."""
    unique = unique_sentence_audio_texts(texts)
    if not unique:
        return 0, 0, 0

    if config.engine == "auto" and not voicevox_engine_reachable(config.voicevox_engine_url):
        require_edge_tts()

    from wk_reading_audio import ReadingAudioProgressBar

    print(
        f"{label} ({format_sentence_tts_label(config)}, cache={cache_dir}, unique={len(unique)})..."
    )
    progress = ReadingAudioProgressBar(len(unique), label=label)
    ok, cached, new = asyncio.run(
        _prefetch_sentence_audio_batch_async(
            unique,
            config,
            cache_dir=cache_dir,
            refresh=refresh,
            concurrency=concurrency,
            progress=progress,
        )
    )
    progress.finish(ok_count=ok, detail=f"{new} new, {cached} cached")
    return ok, cached, new
