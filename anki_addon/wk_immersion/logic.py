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
from typing import List, Optional, Tuple

try:
    from .mining_note_types import MINING_NOTE_TYPE, is_mining_note_type
except ImportError:  # loaded as a loose module in unit tests
    from mining_note_types import MINING_NOTE_TYPE, is_mining_note_type

FIELD_SENTENCE = "Sentence"
FIELD_SENTENCE_FURIGANA = "SentenceFurigana"
FIELD_SENTENCE_AUDIO = "SentenceAudio"
FIELD_SENTENCE_AUDIO_EASY = "SentenceAudioEasy"
FIELD_AUDIO = "Audio"
FIELD_READING_AUDIO = "ReadingAudio"
FIELD_EXPRESSION = "Expression"
FIELD_READING = "Reading"
FIELD_SPEAKER = "VoicevoxSpeakerId"

DEFAULT_VOICEVOX_ENGINE_URL = "http://127.0.0.1:50021"
DEFAULT_VOICEVOX_SPEAKER_ID = 2  # 四国めたん (Shikoku Metan), normal style
DEFAULT_VOICEVOX_VOLUME_SCALE = 1.5
DEFAULT_VOICEVOX_SPEED_SCALE = 1.0
DEFAULT_VOICEVOX_EASY_SPEED_SCALE = 0.75
DEFAULT_EDGE_TTS_VOICE = "ja-JP-NanamiNeural"
DEFAULT_SYNTH_ENGINE = "voicevox"
SENTENCE_AUDIO_FILENAME_PREFIX = "wk_immersion_sent_"
# Packaged native clips from shadowing project imports (never overwrite with TTS).
NATIVE_SHADOWING_AUDIO_PREFIX = "wk_shadowing_"
IMMERSION_AUDIO_CACHE_SUBDIR = "immersion_sentence_audio"
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
    voicevox_speed_scale: float = DEFAULT_VOICEVOX_SPEED_SCALE
    voicevox_easy_speed_scale: float = DEFAULT_VOICEVOX_EASY_SPEED_SCALE
    edge_tts_voice: str = DEFAULT_EDGE_TTS_VOICE
    python_executable: str = ""
    cache_enabled: bool = True
    cache_dir: str = ""  # empty → resolve_immersion_audio_cache_dir()

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
            voicevox_speed_scale=float(
                payload.get("voicevox_speed_scale", DEFAULT_VOICEVOX_SPEED_SCALE)
            ),
            voicevox_easy_speed_scale=float(
                payload.get("voicevox_easy_speed_scale", DEFAULT_VOICEVOX_EASY_SPEED_SCALE)
            ),
            edge_tts_voice=str(payload.get("edge_tts_voice", DEFAULT_EDGE_TTS_VOICE)),
            python_executable=str(payload.get("python_executable", "")),
            cache_enabled=bool(payload.get("cache_enabled", True)),
            cache_dir=str(payload.get("cache_dir", "")),
        )


def strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def sentence_plain_text(sentence_field: str) -> str:
    return strip_html(sentence_field).strip()


_RUBY_WITH_RT = re.compile(r"<ruby>(.*?)<rt>(.*?)</rt></ruby>", re.DOTALL | re.IGNORECASE)
# Anki / Satori ReadingsInline: 漢字[かんじ] (VOICEVOX must not hear the bracket reading).
_ANKI_FURIGANA_BRACKET_RE = re.compile(r"(\S+?)\[([^\]]+)\]")


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


def strip_anki_furigana_brackets(value: str) -> str:
    """Keep surface text from Anki ``漢字[かんじ]`` markup; drop bracket readings."""
    if not (value or "").strip():
        return ""
    return _ANKI_FURIGANA_BRACKET_RE.sub(r"\1", value)


def kanji_plain_from_furigana_html(value: str) -> str:
    """Kanji surface string from furigana HTML or Anki bracket markup (drop readings)."""
    without_readings = re.sub(r"<rt>.*?</rt>", "", value or "", flags=re.DOTALL | re.IGNORECASE)
    without_brackets = strip_anki_furigana_brackets(without_readings)
    return strip_html(without_brackets).strip()


def _same_japanese_text(left: str, right: str) -> bool:
    return left.replace(" ", "") == right.replace(" ", "")


def sentence_text_for_tts(sentence: str, sentence_furigana: str = "") -> str:
    """
    Text to synthesize for the sentence player.

    Prefer plain **Sentence** (kanji) when furigana is the same line with ruby/bracket markup.
    Use furigana-derived kanji only when it contains more text (page context).
    VOICEVOX reads kanji; never feed ``漢字[かんじ]`` or ruby readings as spoken text.
    """
    plain = sentence_plain_text(sentence)
    if not (sentence_furigana or "").strip():
        return plain

    furi_kanji = kanji_plain_from_furigana_html(sentence_furigana)
    if plain and furi_kanji:
        if _same_japanese_text(plain, furi_kanji):
            return plain
        if len(furi_kanji.replace(" ", "")) > len(plain.replace(" ", "")):
            return furi_kanji

    return plain or furi_kanji or ruby_html_to_plain(sentence_furigana)


def sentence_audio_already_set(sentence_audio_field: str) -> bool:
    return bool(strip_html(sentence_audio_field).strip())


def uses_native_sentence_clip(note_type_name: str) -> bool:
    """Shadowing notes ship video/audio clips; sentence TTS must not replace them."""
    try:
        from .mining_note_types import (
            SHADOWING_CANDIDATE_NOTE_TYPE,
            SHADOWING_NOTE_TYPE,
        )
    except ImportError:
        from mining_note_types import (  # type: ignore
            SHADOWING_CANDIDATE_NOTE_TYPE,
            SHADOWING_NOTE_TYPE,
        )

    return note_type_name in {SHADOWING_NOTE_TYPE, SHADOWING_CANDIDATE_NOTE_TYPE}


def is_native_shadowing_audio_field(sentence_audio_field: str) -> bool:
    bare = unwrap_sound_tag(sentence_audio_field)
    return bare.startswith(NATIVE_SHADOWING_AUDIO_PREFIX)


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
    speed_scale: float = DEFAULT_VOICEVOX_SPEED_SCALE,
    pitch_accent: Optional[int] = None,
    ext: str,
) -> str:
    pitch_token = "" if pitch_accent is None else str(int(pitch_accent))
    raw = (
        f"{engine}\0{speaker_id}\0{volume_scale:g}\0{speed_scale:g}\0"
        f"{pitch_token}\0{text}".encode("utf-8")
    )
    digest = hashlib.sha256(raw).hexdigest()[:24]
    return f"{SENTENCE_AUDIO_FILENAME_PREFIX}{digest}{ext}"


def resolve_immersion_audio_cache_dir(configured: str = "") -> Path:
    """Disk cache for immersion TTS (same role as .wk_cache/sentence_audio for deck builds)."""
    if configured.strip():
        return Path(configured).expanduser()
    cwd_cache = Path.cwd() / ".wk_cache" / IMMERSION_AUDIO_CACHE_SUBDIR
    home_cache = Path.home() / "anki" / ".wk_cache" / IMMERSION_AUDIO_CACHE_SUBDIR
    if (Path.cwd() / ".wk_cache").is_dir() or (Path.cwd() / "anki_addon").is_dir():
        return cwd_cache
    if (Path.home() / "anki").is_dir():
        return home_cache
    return cwd_cache


def immersion_audio_cache_path(
    text: str,
    *,
    engine: str,
    speaker_id: int,
    volume_scale: float,
    speed_scale: float,
    ext: str,
    cache_dir: Path,
    pitch_accent: Optional[int] = None,
) -> Path:
    return cache_dir / sentence_media_basename(
        text,
        engine=engine,
        speaker_id=speaker_id,
        volume_scale=volume_scale,
        speed_scale=speed_scale,
        pitch_accent=pitch_accent,
        ext=ext,
    )


def audio_cache_is_usable(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def parse_primary_pitch_position(pitch_positions_field: str) -> Optional[int]:
    """First Kanjium pitch position from a PitchPositions field (e.g. ``2`` or ``1, 0``)."""
    text = (pitch_positions_field or "").strip()
    if not text:
        return None
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            return int(part)
        except ValueError:
            continue
    return None


def apply_voicevox_accent_phrases(
    audio_query: dict,
    *,
    pitch_accent: Optional[int],
) -> dict:
    """Override VOICEVOX accent on the first usable accent phrase (word-level TTS).

    Kanjium ``position`` matches VOICEVOX ``accent`` (0 = heiban; N = drop after mora N).
    Multi-phrase sentence queries are left alone except the first phrase — prefer
    calling this only for Target/Reading (single-word) synthesis.
    """
    if pitch_accent is None:
        return audio_query
    try:
        desired = int(pitch_accent)
    except (TypeError, ValueError):
        return audio_query
    updated = dict(audio_query)
    phrases = updated.get("accent_phrases")
    if not isinstance(phrases, list) or not phrases:
        return updated
    new_phrases: List[dict] = []
    applied = False
    for phrase in phrases:
        if not isinstance(phrase, dict):
            new_phrases.append(phrase)
            continue
        phrase_copy = dict(phrase)
        moras = phrase_copy.get("moras") or []
        mora_count = len(moras) if isinstance(moras, list) else 0
        if not applied and mora_count > 0:
            # VOICEVOX accepts 0..mora_count (odaka == mora_count).
            phrase_copy["accent"] = max(0, min(desired, mora_count))
            applied = True
        new_phrases.append(phrase_copy)
    updated["accent_phrases"] = new_phrases
    return updated


def apply_voicevox_query_scales(
    audio_query: dict,
    *,
    volume_scale: float = DEFAULT_VOICEVOX_VOLUME_SCALE,
    speed_scale: float = DEFAULT_VOICEVOX_SPEED_SCALE,
) -> dict:
    updated = dict(audio_query)
    if volume_scale != 1.0:
        updated["volumeScale"] = float(volume_scale)
    if speed_scale != 1.0:
        updated["speedScale"] = float(speed_scale)
    return updated


def apply_voicevox_volume(audio_query: dict, volume_scale: float) -> dict:
    """Backward-compatible wrapper; prefer apply_voicevox_query_scales."""
    return apply_voicevox_query_scales(audio_query, volume_scale=volume_scale)


def synthesize_voicevox_wav(
    text: str,
    *,
    engine_url: str,
    speaker_id: int,
    volume_scale: float = DEFAULT_VOICEVOX_VOLUME_SCALE,
    speed_scale: float = DEFAULT_VOICEVOX_SPEED_SCALE,
    pitch_accent: Optional[int] = None,
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
            audio_query = apply_voicevox_query_scales(
                json.loads(resp.read().decode("utf-8")),
                volume_scale=volume_scale,
                speed_scale=speed_scale,
            )
            audio_query = apply_voicevox_accent_phrases(
                audio_query, pitch_accent=pitch_accent
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
    speed_scale: Optional[float] = None,
    force: bool = False,
    cache_dir: Optional[Path] = None,
    pitch_accent: Optional[int] = None,
) -> Tuple[Optional[bytes], str, str]:
    """
    Return (audio_bytes, media_ext_including_dot, engine_label).
    engine_label is voicevox or edge.
    speed_scale overrides config.voicevox_speed_scale for VOICEVOX only.
    pitch_accent (Kanjium position) overrides VOICEVOX accent on word-level TTS.
    When cache_enabled, reads/writes .wk_cache/immersion_sentence_audio (or config.cache_dir).
    force=True regenerates even when a cache file exists.
    """
    plain = sentence_plain_text(text)
    if not plain:
        return None, "", ""

    engines = []
    if config.engine == "auto":
        engines = ["voicevox", "edge"]
    else:
        engines = [config.engine]

    voicevox_speed = (
        float(speed_scale) if speed_scale is not None else float(config.voicevox_speed_scale)
    )
    resolved_cache: Optional[Path] = None
    if config.cache_enabled:
        resolved_cache = cache_dir or resolve_immersion_audio_cache_dir(config.cache_dir)
        resolved_cache.mkdir(parents=True, exist_ok=True)

    for engine in engines:
        if engine == "voicevox":
            cache_path = None
            if resolved_cache is not None:
                cache_path = immersion_audio_cache_path(
                    plain,
                    engine="voicevox",
                    speaker_id=config.voicevox_speaker_id,
                    volume_scale=config.voicevox_volume_scale,
                    speed_scale=voicevox_speed,
                    pitch_accent=pitch_accent,
                    ext=".wav",
                    cache_dir=resolved_cache,
                )
                if not force and audio_cache_is_usable(cache_path):
                    return cache_path.read_bytes(), ".wav", "voicevox"

            wav = synthesize_voicevox_wav(
                plain,
                engine_url=config.voicevox_engine_url,
                speaker_id=config.voicevox_speaker_id,
                volume_scale=config.voicevox_volume_scale,
                speed_scale=voicevox_speed,
                pitch_accent=pitch_accent,
            )
            if wav:
                if cache_path is not None:
                    cache_path.write_bytes(wav)
                return wav, ".wav", "voicevox"
        elif engine == "edge":
            python_exe = resolve_python_executable(config.python_executable)
            if not python_exe:
                continue
            basename = sentence_media_basename(
                plain,
                engine="edge",
                speaker_id=0,
                speed_scale=voicevox_speed,
                pitch_accent=None,
                ext=".mp3",
            )
            cache_path = None
            if resolved_cache is not None:
                cache_path = resolved_cache / basename
                if not force and audio_cache_is_usable(cache_path):
                    return cache_path.read_bytes(), ".mp3", "edge"

            dest = (cache_path if cache_path is not None else temp_dir / basename)
            dest.parent.mkdir(parents=True, exist_ok=True)
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


def unwrap_sound_tag(field_value: str) -> str:
    """Return media filename from `[sound:name]` or the trimmed value as-is."""
    name = (field_value or "").strip()
    if name.startswith("[sound:") and name.endswith("]"):
        return name[len("[sound:") : -1]
    return name


def audio_field_value(stored_filename: str, *, autoplay: bool) -> str:
    """Always store Anki ``[sound:]`` so media syncs and AnkiMobile can play.

    ``autoplay`` is retained for callers; card templates + the immersion deck
    options group (autoplay off + JS click on ``.autoplay-audio``) control which
    clips play on reveal. HTML5 ``<audio>`` is not used — AnkiMobile ignores it.
    """
    del autoplay  # storage format no longer differs; see docstring
    return sound_field_value(unwrap_sound_tag(stored_filename))


def sentence_audio_autoplay(*, note_type_name: str, field_name: str) -> bool:
    """
    Satori: Easy autoplays; Normal is manual.
    Satori/Shadowing word ``Audio`` (surface span) is always manual.
    Yomitan/Migaku: SentenceAudio autoplays (they have no Easy-first layout).
    """
    if field_name == FIELD_AUDIO or field_name == FIELD_READING_AUDIO:
        try:
            from .mining_note_types import (
                SATORI_NOTE_TYPE,
                SHADOWING_CANDIDATE_NOTE_TYPE,
                SHADOWING_NOTE_TYPE,
            )
        except ImportError:
            from mining_note_types import (  # type: ignore
                SATORI_NOTE_TYPE,
                SHADOWING_CANDIDATE_NOTE_TYPE,
                SHADOWING_NOTE_TYPE,
            )

        return note_type_name not in {
            SATORI_NOTE_TYPE,
            SHADOWING_NOTE_TYPE,
            SHADOWING_CANDIDATE_NOTE_TYPE,
        }
    if field_name == FIELD_SENTENCE_AUDIO_EASY:
        return True
    if field_name == FIELD_SENTENCE_AUDIO:
        try:
            from .mining_note_types import SATORI_NOTE_TYPE
        except ImportError:
            from mining_note_types import SATORI_NOTE_TYPE

        return note_type_name != SATORI_NOTE_TYPE
    return True


def sentence_audio_fields_needing_synth(
    *,
    sentence_audio: str,
    sentence_audio_easy: str,
    force: bool = False,
    note_type_name: str = "",
) -> Tuple[str, ...]:
    if note_type_name and uses_native_sentence_clip(note_type_name):
        return ()
    needed: list[str] = []
    # Never replace packaged shadowing clips, even under --force.
    if is_native_shadowing_audio_field(sentence_audio):
        pass
    elif force or not sentence_audio_already_set(sentence_audio):
        needed.append(FIELD_SENTENCE_AUDIO)
    if force or not sentence_audio_already_set(sentence_audio_easy):
        # Shadowing notes do not use Easy sentence TTS.
        if not is_native_shadowing_audio_field(sentence_audio):
            needed.append(FIELD_SENTENCE_AUDIO_EASY)
    return tuple(needed)


def should_synthesize_note(
    *,
    note_type_name: str,
    sentence: str,
    sentence_audio: str,
    config: ImmersionTtsConfig,
    on_mine: bool,
    sentence_furigana: str = "",
    sentence_audio_easy: str = "",
) -> bool:
    if not config.enabled:
        return False
    if on_mine and not config.on_mine:
        return False
    if not is_mining_note_type(note_type_name):
        return False
    if uses_native_sentence_clip(note_type_name):
        return False
    if not sentence_audio_fields_needing_synth(
        sentence_audio=sentence_audio,
        sentence_audio_easy=sentence_audio_easy,
        note_type_name=note_type_name,
    ):
        return False
    return bool(sentence_text_for_tts(sentence, sentence_furigana))
