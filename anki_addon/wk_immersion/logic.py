"""
Pure logic for wk_immersion sentence TTS (testable without Anki runtime).
"""

from __future__ import annotations

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
from typing import Optional, Tuple

MINING_NOTE_TYPE = "WK Yomitan Immersion"
FIELD_SENTENCE = "Sentence"
FIELD_SENTENCE_FURIGANA = "SentenceFurigana"
FIELD_SENTENCE_AUDIO = "SentenceAudio"
FIELD_SPEAKER = "VoicevoxSpeakerId"

DEFAULT_VOICEVOX_ENGINE_URL = "http://127.0.0.1:50021"
DEFAULT_VOICEVOX_SPEAKER_ID = 2  # 四国めたん (Shikoku Metan), normal style
DEFAULT_VOICEVOX_VOLUME_SCALE = 1.5
DEFAULT_EDGE_TTS_VOICE = "ja-JP-NanamiNeural"
DEFAULT_SYNTH_ENGINE = "voicevox"
SENTENCE_AUDIO_FILENAME_PREFIX = "wk_immersion_sent_"
VOICEVOX_SYNTH_TIMEOUT_SECONDS = 45
EDGE_TTS_SUBPROCESS_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ImmersionTtsConfig:
    enabled: bool = True
    on_mine: bool = True
    engine: str = DEFAULT_SYNTH_ENGINE  # voicevox | edge | auto
    voicevox_engine_url: str = DEFAULT_VOICEVOX_ENGINE_URL
    voicevox_speaker_id: int = DEFAULT_VOICEVOX_SPEAKER_ID
    voicevox_volume_scale: float = DEFAULT_VOICEVOX_VOLUME_SCALE
    edge_tts_voice: str = DEFAULT_EDGE_TTS_VOICE
    python_executable: str = ""

    @classmethod
    def from_mapping(cls, payload: dict) -> "ImmersionTtsConfig":
        return cls(
            enabled=bool(payload.get("enabled", True)),
            on_mine=bool(payload.get("on_mine", True)),
            engine=str(payload.get("engine", DEFAULT_SYNTH_ENGINE)),
            voicevox_engine_url=str(
                payload.get("voicevox_engine_url", DEFAULT_VOICEVOX_ENGINE_URL)
            ).rstrip("/"),
            voicevox_speaker_id=int(payload.get("voicevox_speaker_id", DEFAULT_VOICEVOX_SPEAKER_ID)),
            voicevox_volume_scale=float(
                payload.get("voicevox_volume_scale", DEFAULT_VOICEVOX_VOLUME_SCALE)
            ),
            edge_tts_voice=str(payload.get("edge_tts_voice", DEFAULT_EDGE_TTS_VOICE)),
            python_executable=str(payload.get("python_executable", "")),
        )


def strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def sentence_plain_text(sentence_field: str) -> str:
    return strip_html(sentence_field).strip()


_RUBY_WITH_RT = re.compile(r"<ruby>(.*?)<rt>(.*?)</rt></ruby>", re.DOTALL | re.IGNORECASE)


def ruby_html_to_plain(value: str) -> str:
    """Extract kana readings from Yomitan ruby HTML (for TTS when kanji unavailable)."""
    if not (value or "").strip():
        return ""
    text = value
    while True:
        updated = _RUBY_WITH_RT.sub(
            lambda match: (match.group(2) or match.group(1)).strip(),
            text,
        )
        if updated == text:
            break
        text = updated
    return strip_html(text).strip()


def kanji_plain_from_furigana_html(value: str) -> str:
    """Kanji surface string from furigana HTML (drop rt readings, then strip tags)."""
    without_readings = re.sub(r"<rt>.*?</rt>", "", value or "", flags=re.DOTALL | re.IGNORECASE)
    return strip_html(without_readings).strip()


def _same_japanese_text(left: str, right: str) -> bool:
    return left.replace(" ", "") == right.replace(" ", "")


def sentence_text_for_tts(sentence: str, sentence_furigana: str = "") -> str:
    """
    Text to synthesize for the sentence player.

    Prefer plain **Sentence** (kanji) when furigana is the same line with ruby markup.
    Use furigana-derived kanji only when it contains more text (page context).
    VOICEVOX reads kanji; avoid substituting compact kana like ずつう for 頭痛.
    """
    plain = sentence_plain_text(sentence)
    if not (sentence_furigana or "").strip():
        return plain

    furi_kanji = kanji_plain_from_furigana_html(sentence_furigana)
    if plain and furi_kanji:
        if _same_japanese_text(plain, furi_kanji):
            return plain
        if len(furi_kanji) > len(plain):
            return furi_kanji

    return plain or ruby_html_to_plain(sentence_furigana) or furi_kanji


def sentence_audio_already_set(sentence_audio_field: str) -> bool:
    return bool(strip_html(sentence_audio_field).strip())


def resolve_python_executable(configured: str = "") -> Optional[str]:
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path)
    found = shutil.which("python3") or shutil.which("python")
    return found


def sentence_media_basename(
    text: str,
    *,
    engine: str,
    speaker_id: int,
    volume_scale: float = DEFAULT_VOICEVOX_VOLUME_SCALE,
    ext: str,
) -> str:
    raw = f"{engine}\0{speaker_id}\0{volume_scale:g}\0{text}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:24]
    return f"{SENTENCE_AUDIO_FILENAME_PREFIX}{digest}{ext}"


def apply_voicevox_volume(audio_query: dict, volume_scale: float) -> dict:
    if volume_scale == 1.0:
        return audio_query
    updated = dict(audio_query)
    updated["volumeScale"] = float(volume_scale)
    return updated


def synthesize_voicevox_wav(
    text: str,
    *,
    engine_url: str,
    speaker_id: int,
    volume_scale: float = DEFAULT_VOICEVOX_VOLUME_SCALE,
    timeout_seconds: int = VOICEVOX_SYNTH_TIMEOUT_SECONDS,
) -> Optional[bytes]:
    if not text.strip():
        return None
    base = engine_url.rstrip("/")
    query_url = (
        f"{base}/audio_query?"
        f"{urllib.parse.urlencode({'text': text, 'speaker': str(speaker_id)})}"
    )
    try:
        query_req = urllib.request.Request(query_url, data=b"", method="POST")
        with urllib.request.urlopen(query_req, timeout=timeout_seconds) as resp:
            audio_query = apply_voicevox_volume(
                json.loads(resp.read().decode("utf-8")),
                volume_scale,
            )
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
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def synthesize_edge_tts_mp3(
    text: str,
    *,
    voice: str,
    dest_path: Path,
    python_executable: str,
    script_path: Path,
    timeout_seconds: int = EDGE_TTS_SUBPROCESS_TIMEOUT_SECONDS,
) -> bool:
    if not text.strip() or not python_executable or not script_path.is_file():
        return False
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [python_executable, str(script_path), text, voice, str(dest_path)],
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and dest_path.is_file() and dest_path.stat().st_size > 0


def synthesize_sentence_audio(
    text: str,
    *,
    config: ImmersionTtsConfig,
    temp_dir: Path,
    edge_tts_script: Path,
) -> Tuple[Optional[bytes], str, str]:
    """
    Return (audio_bytes, media_ext_including_dot, engine_label).
    engine_label is voicevox or edge.
    """
    plain = sentence_plain_text(text)
    if not plain:
        return None, "", ""

    engines = []
    if config.engine == "auto":
        engines = ["voicevox", "edge"]
    else:
        engines = [config.engine]

    for engine in engines:
        if engine == "voicevox":
            wav = synthesize_voicevox_wav(
                plain,
                engine_url=config.voicevox_engine_url,
                speaker_id=config.voicevox_speaker_id,
                volume_scale=config.voicevox_volume_scale,
            )
            if wav:
                return wav, ".wav", "voicevox"
        elif engine == "edge":
            python_exe = resolve_python_executable(config.python_executable)
            if not python_exe:
                continue
            dest = temp_dir / sentence_media_basename(
                plain,
                engine="edge",
                speaker_id=0,
                ext=".mp3",
            )
            if synthesize_edge_tts_mp3(
                plain,
                voice=config.edge_tts_voice,
                dest_path=dest,
                python_executable=python_exe,
                script_path=edge_tts_script,
            ):
                return dest.read_bytes(), ".mp3", "edge"
    return None, "", ""


def sound_field_value(stored_filename: str) -> str:
    return f"[sound:{stored_filename}]"


def should_synthesize_note(
    *,
    note_type_name: str,
    sentence: str,
    sentence_audio: str,
    config: ImmersionTtsConfig,
    on_mine: bool,
    sentence_furigana: str = "",
) -> bool:
    if not config.enabled:
        return False
    if on_mine and not config.on_mine:
        return False
    if note_type_name != MINING_NOTE_TYPE:
        return False
    if sentence_audio_already_set(sentence_audio):
        return False
    return bool(sentence_text_for_tts(sentence, sentence_furigana))
