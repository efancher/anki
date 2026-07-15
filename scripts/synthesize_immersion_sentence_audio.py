"""
WK Immersion — synthesize full-sentence audio for Yomitan / Migaku / Satori notes.

Fills SentenceAudio (normal speed) and SentenceAudioEasy (slower VOICEVOX speed).
Audio is cached under .wk_cache/immersion_sentence_audio/ (skip VOICEVOX on cache hit).
Pass --force to regenerate cache and overwrite note fields.

Usage (Anki must be running; VOICEVOX engine recommended):

  python3 scripts/synthesize_immersion_sentence_audio.py
  python3 scripts/synthesize_immersion_sentence_audio.py --note-id 1234567890
  python3 scripts/synthesize_immersion_sentence_audio.py --note-type "WK Satori Immersion"
  python3 scripts/synthesize_immersion_sentence_audio.py --note-type "WK Satori Immersion" --force

Requires AnkiConnect (default http://127.0.0.1:8765) or use the in-Anki menu instead:
Tools → WK Synthesize Immersion Sentence Audio
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
LOGIC_PATH = REPO_ROOT / "anki_addon" / "wk_immersion" / "logic.py"
NOTE_TYPES_PATH = REPO_ROOT / "anki_addon" / "wk_immersion" / "mining_note_types.py"
EDGE_TTS_SCRIPT = REPO_ROOT / "anki_addon" / "wk_immersion" / "edge_tts_once.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_note_types = _load_module(NOTE_TYPES_PATH, "wk_immersion_mining_note_types")
_addon_dir = LOGIC_PATH.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))
_logic = _load_module(LOGIC_PATH, "wk_immersion_logic")

FIELD_SENTENCE = _logic.FIELD_SENTENCE
FIELD_SENTENCE_FURIGANA = _logic.FIELD_SENTENCE_FURIGANA
FIELD_SENTENCE_AUDIO = _logic.FIELD_SENTENCE_AUDIO
FIELD_SENTENCE_AUDIO_EASY = _logic.FIELD_SENTENCE_AUDIO_EASY
MINING_NOTE_TYPES = _note_types.MINING_NOTE_TYPES
SATORI_NOTE_TYPE = _note_types.SATORI_NOTE_TYPE
ImmersionTtsConfig = _logic.ImmersionTtsConfig
audio_field_value = _logic.audio_field_value
sentence_audio_autoplay = _logic.sentence_audio_autoplay
sentence_audio_fields_needing_synth = _logic.sentence_audio_fields_needing_synth
sentence_media_basename = _logic.sentence_media_basename
sentence_text_for_tts = _logic.sentence_text_for_tts
should_synthesize_note = _logic.should_synthesize_note
synthesize_sentence_audio = _logic.synthesize_sentence_audio
unwrap_sound_tag = _logic.unwrap_sound_tag

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"


def anki_request(base_url: str, action: str, **params):
    payload = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("error"):
        raise RuntimeError(body["error"])
    return body.get("result")


def note_field_names(base_url: str, model_name: str) -> list[str]:
    models = anki_request(base_url, "modelNames")
    if model_name not in models:
        raise RuntimeError(f"Note type not found: {model_name}")
    fields = anki_request(base_url, "modelFieldNames", modelName=model_name)
    return list(fields)


def find_immersion_note_ids(
    base_url: str,
    note_id: Optional[int],
    note_types: Sequence[str],
) -> list[int]:
    if note_id is not None:
        return [note_id]
    clause = " OR ".join(f'note:"{name}"' for name in note_types)
    return [int(nid) for nid in anki_request(base_url, "findNotes", query=f"({clause})")]


def resolve_note_types(requested: Optional[str]) -> list[str]:
    if requested:
        if requested not in MINING_NOTE_TYPES:
            raise SystemExit(
                f"Unknown note type {requested!r}. Expected one of: "
                + ", ".join(sorted(MINING_NOTE_TYPES))
            )
        return [requested]
    return sorted(MINING_NOTE_TYPES)


def load_config() -> ImmersionTtsConfig:
    for path in (
        REPO_ROOT / "out" / "wk_immersion_config.json",
        REPO_ROOT / "wk_immersion_config.json",
    ):
        if path.is_file():
            return ImmersionTtsConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    return ImmersionTtsConfig()


def store_field_audio(
    *,
    base_url: str,
    note_id: int,
    note_type_name: str,
    field_name: str,
    tts_text: str,
    config: ImmersionTtsConfig,
    speed_scale: float,
    force: bool = False,
) -> bool:
    with tempfile.TemporaryDirectory(prefix="wk_immersion_cli_") as tmp:
        audio_bytes, ext, engine_label = synthesize_sentence_audio(
            tts_text,
            config=config,
            temp_dir=Path(tmp),
            edge_tts_script=EDGE_TTS_SCRIPT,
            speed_scale=speed_scale,
            force=force,
        )
    if not audio_bytes:
        return False
    speaker_id = config.voicevox_speaker_id if engine_label == "voicevox" else 0
    volume_scale = config.voicevox_volume_scale if engine_label == "voicevox" else 1.0
    basename = sentence_media_basename(
        tts_text,
        engine=engine_label,
        speaker_id=speaker_id,
        volume_scale=volume_scale,
        speed_scale=speed_scale if engine_label == "voicevox" else 1.0,
        ext=ext,
    )
    stored = anki_request(
        base_url,
        "storeMediaFile",
        filename=basename,
        data=base64.b64encode(audio_bytes).decode("ascii"),
    )
    autoplay = sentence_audio_autoplay(
        note_type_name=note_type_name, field_name=field_name
    )
    anki_request(
        base_url,
        "updateNoteFields",
        note={
            "id": note_id,
            "fields": {
                field_name: audio_field_value(stored or basename, autoplay=autoplay)
            },
        },
    )
    return True


def unwrap_satori_normal_if_needed(
    *, base_url: str, note_id: int, note_type_name: str, sentence_audio: str
) -> str:
    """Rewrite Satori SentenceAudio from [sound:x] to bare x (no autoplay)."""
    if note_type_name != SATORI_NOTE_TYPE:
        return sentence_audio
    bare = unwrap_sound_tag(sentence_audio)
    if not bare or bare == (sentence_audio or "").strip():
        return sentence_audio
    anki_request(
        base_url,
        "updateNoteFields",
        note={"id": note_id, "fields": {FIELD_SENTENCE_AUDIO: bare}},
    )
    return bare


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument("--note-id", type=int, default=None)
    parser.add_argument(
        "--note-type",
        default=None,
        help="Limit to one note type (default: all immersion mining types including Satori)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing SentenceAudio / SentenceAudioEasy and regenerate disk cache",
    )
    args = parser.parse_args()

    config = load_config()
    note_types = resolve_note_types(args.note_type)
    try:
        available = set(anki_request(args.anki_connect, "modelNames") or [])
        check_type = note_types[0]
        for candidate in note_types:
            if candidate in available:
                check_type = candidate
                break
        field_names = note_field_names(args.anki_connect, check_type)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Cannot reach AnkiConnect at {args.anki_connect}: {exc}\n"
            "• Open Anki and install the AnkiConnect add-on.\n"
            "Or use Tools → WK Synthesize Immersion Sentence Audio inside Anki."
        ) from exc

    required = [FIELD_SENTENCE, FIELD_SENTENCE_AUDIO]
    missing = [name for name in required if name not in field_names]
    if missing:
        raise SystemExit(
            f"Note type {check_type!r} is missing field(s): {', '.join(missing)}.\n"
            "For Satori: re-run scripts/import_satori.py and import with Update.\n"
            "For Yomitan: python3 wk_decks.py --deck mining → import → Update."
        )
    has_easy = FIELD_SENTENCE_AUDIO_EASY in field_names

    note_ids = find_immersion_note_ids(args.anki_connect, args.note_id, note_types)
    ok = failed = skipped = 0

    for nid in note_ids:
        info = anki_request(args.anki_connect, "notesInfo", notes=[nid])[0]
        fields = info.get("fields") or {}
        model_name = info.get("modelName") or check_type
        sentence = (fields.get(FIELD_SENTENCE) or {}).get("value") or ""
        sentence_furigana = (fields.get(FIELD_SENTENCE_FURIGANA) or {}).get("value") or ""
        sentence_audio = (fields.get(FIELD_SENTENCE_AUDIO) or {}).get("value") or ""
        sentence_audio_easy = (
            (fields.get(FIELD_SENTENCE_AUDIO_EASY) or {}).get("value") or "" if has_easy else "[sound:skip]"
        )
        sentence_audio = unwrap_satori_normal_if_needed(
            base_url=args.anki_connect,
            note_id=nid,
            note_type_name=model_name,
            sentence_audio=sentence_audio,
        )
        if not args.force and not should_synthesize_note(
            note_type_name=model_name,
            sentence=sentence,
            sentence_furigana=sentence_furigana,
            sentence_audio=sentence_audio,
            sentence_audio_easy=sentence_audio_easy if has_easy else "",
            config=config,
            on_mine=True,
        ):
            skipped += 1
            continue
        tts_text = sentence_text_for_tts(sentence, sentence_furigana)
        if not tts_text:
            skipped += 1
            continue

        needed = sentence_audio_fields_needing_synth(
            sentence_audio=sentence_audio,
            sentence_audio_easy=sentence_audio_easy if has_easy else "[sound:skip]",
            force=args.force,
        )
        if not has_easy:
            needed = tuple(name for name in needed if name != FIELD_SENTENCE_AUDIO_EASY)
        if not needed:
            skipped += 1
            continue

        note_ok = False
        note_failed = False
        for field_name in needed:
            speed = (
                config.voicevox_easy_speed_scale
                if field_name == FIELD_SENTENCE_AUDIO_EASY
                else config.voicevox_speed_scale
            )
            if store_field_audio(
                base_url=args.anki_connect,
                note_id=nid,
                note_type_name=model_name,
                field_name=field_name,
                tts_text=tts_text,
                config=config,
                speed_scale=speed,
                force=args.force,
            ):
                note_ok = True
            else:
                note_failed = True
        if note_ok:
            ok += 1
        elif note_failed:
            failed += 1
        else:
            skipped += 1

    print(f"Done: {ok} synthesized, {failed} failed, {skipped} skipped.")


if __name__ == "__main__":
    main()
