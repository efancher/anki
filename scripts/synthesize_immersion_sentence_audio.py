"""
WK Immersion — synthesize sentence + Target/Reading audio for immersion notes.

Fills SentenceAudio (normal) and SentenceAudioEasy (slower). For Satori/Shadowing
notes, also fills:
  • Audio — Voicevox of the cloze surface span (Target button)
  • ReadingAudio — Voicevox of the hiragana Reading (answer)
Shadowing Immersion / Candidate notes keep native wk_shadowing_* SentenceAudio;
--force never replaces those (use Target/Reading TTS only, or --surface-only).
Cached under .wk_cache/immersion_sentence_audio/.
Pass --force to regenerate cache and overwrite note fields (non-shadowing).

Usage (Anki must be running; VOICEVOX engine recommended):

  python3 scripts/synthesize_immersion_sentence_audio.py
  python3 scripts/synthesize_immersion_sentence_audio.py --note-id 1234567890
  python3 scripts/synthesize_immersion_sentence_audio.py --note-type "WK Satori Immersion"
  python3 scripts/synthesize_immersion_sentence_audio.py --note-type "WK Satori Immersion" --force
  python3 scripts/synthesize_immersion_sentence_audio.py --surface-only --note-type "WK Satori Immersion"

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
FIELD_AUDIO = _logic.FIELD_AUDIO
FIELD_READING_AUDIO = _logic.FIELD_READING_AUDIO
FIELD_EXPRESSION = _logic.FIELD_EXPRESSION
FIELD_READING = _logic.FIELD_READING
FIELD_PITCH_POSITIONS = "PitchPositions"
MINING_NOTE_TYPES = _note_types.MINING_NOTE_TYPES
SATORI_NOTE_TYPE = _note_types.SATORI_NOTE_TYPE
SHADOWING_NOTE_TYPE = _note_types.SHADOWING_NOTE_TYPE
SHADOWING_CANDIDATE_NOTE_TYPE = _note_types.SHADOWING_CANDIDATE_NOTE_TYPE
ImmersionTtsConfig = _logic.ImmersionTtsConfig
audio_field_value = _logic.audio_field_value
parse_primary_pitch_position = _logic.parse_primary_pitch_position
sentence_audio_already_set = _logic.sentence_audio_already_set
sentence_audio_autoplay = _logic.sentence_audio_autoplay
sentence_audio_fields_needing_synth = _logic.sentence_audio_fields_needing_synth
sentence_media_basename = _logic.sentence_media_basename
sentence_text_for_tts = _logic.sentence_text_for_tts
should_synthesize_note = _logic.should_synthesize_note
synthesize_sentence_audio = _logic.synthesize_sentence_audio
unwrap_sound_tag = _logic.unwrap_sound_tag
voicevox_reading_tts_text = _logic.voicevox_reading_tts_text

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# satori_decks imports mining_logic from wk_immersion — keep that ahead of repo root.
_immersion_dir = str(REPO_ROOT / "anki_addon" / "wk_immersion")
if _immersion_dir in sys.path:
    sys.path.remove(_immersion_dir)
sys.path.insert(0, _immersion_dir)
# Drop a stale top-level mining_logic if tests/other loaders registered it.
sys.modules.pop("mining_logic", None)
from satori_decks import surface_span_text  # noqa: E402

SURFACE_AUDIO_NOTE_TYPES = frozenset(
    {
        SATORI_NOTE_TYPE,
        SHADOWING_NOTE_TYPE,
        SHADOWING_CANDIDATE_NOTE_TYPE,
    }
)

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
    pitch_positions: str = "",
    match_kana: str = "",
    update_sentence_pitch_graphs: bool = False,
) -> bool:
    pitch_accent = parse_primary_pitch_position(pitch_positions)
    with tempfile.TemporaryDirectory(prefix="wk_immersion_cli_") as tmp:
        audio_bytes, ext, engine_label, sentence_pitch_html = synthesize_sentence_audio(
            tts_text,
            config=config,
            temp_dir=Path(tmp),
            edge_tts_script=EDGE_TTS_SCRIPT,
            speed_scale=speed_scale,
            force=force,
            pitch_accent=pitch_accent,
            match_kana=match_kana,
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
        pitch_accent=pitch_accent if engine_label == "voicevox" else None,
        match_kana=match_kana if engine_label == "voicevox" else "",
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
    update_fields = {
        field_name: audio_field_value(stored or basename, autoplay=autoplay)
    }
    if (
        update_sentence_pitch_graphs
        and sentence_pitch_html
        and field_name in {FIELD_SENTENCE_AUDIO, FIELD_SENTENCE_AUDIO_EASY}
    ):
        update_fields[_logic.FIELD_SENTENCE_PITCH_GRAPHS] = sentence_pitch_html
    anki_request(
        base_url,
        "updateNoteFields",
        note={
            "id": note_id,
            "fields": update_fields,
        },
    )
    return True


def unwrap_satori_normal_if_needed(
    *, base_url: str, note_id: int, note_type_name: str, sentence_audio: str
) -> str:
    """Ensure Satori SentenceAudio is ``[sound:]`` (deck options control autoplay)."""
    if note_type_name != SATORI_NOTE_TYPE:
        return sentence_audio
    bare = unwrap_sound_tag(sentence_audio)
    if not bare:
        return sentence_audio
    tagged = audio_field_value(bare, autoplay=True)
    if tagged == (sentence_audio or "").strip():
        return sentence_audio
    anki_request(
        base_url,
        "updateNoteFields",
        note={"id": note_id, "fields": {FIELD_SENTENCE_AUDIO: tagged}},
    )
    return tagged


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
        help="Replace existing SentenceAudio / SentenceAudioEasy / Audio and regenerate disk cache",
    )
    parser.add_argument(
        "--surface-only",
        action="store_true",
        help=(
            "Only fill Target (Audio / surface span) and Reading (ReadingAudio / hiragana) "
            "on Satori/Shadowing notes"
        ),
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

    if not args.surface_only:
        required = [FIELD_SENTENCE, FIELD_SENTENCE_AUDIO]
        missing = [name for name in required if name not in field_names]
        if missing:
            raise SystemExit(
                f"Note type {check_type!r} is missing field(s): {', '.join(missing)}.\n"
                "For Satori: re-run scripts/import_satori.py and import with Update.\n"
                "For Yomitan: python3 wk_decks.py --deck mining → import → Update."
            )
    has_easy = FIELD_SENTENCE_AUDIO_EASY in field_names
    has_audio = FIELD_AUDIO in field_names
    has_reading_audio = FIELD_READING_AUDIO in field_names

    note_ids = find_immersion_note_ids(args.anki_connect, args.note_id, note_types)
    total = len(note_ids)
    print(f"Processing {total} note(s)…", flush=True)
    ok = failed = skipped = 0
    surface_ok = surface_failed = surface_skipped = 0
    reading_ok = reading_failed = reading_skipped = 0

    for index, nid in enumerate(note_ids, start=1):
        info = anki_request(args.anki_connect, "notesInfo", notes=[nid])[0]
        fields = info.get("fields") or {}
        model_name = info.get("modelName") or check_type

        def value(name: str) -> str:
            return (fields.get(name) or {}).get("value") or ""

        sentence = value(FIELD_SENTENCE)
        sentence_furigana = value(FIELD_SENTENCE_FURIGANA)
        sentence_audio = value(FIELD_SENTENCE_AUDIO)
        sentence_audio_easy = value(FIELD_SENTENCE_AUDIO_EASY) if has_easy else "[sound:skip]"
        word_audio = value(FIELD_AUDIO) if has_audio else ""
        reading_audio = value(FIELD_READING_AUDIO) if has_reading_audio else ""
        expression = value(FIELD_EXPRESSION)
        reading = value(FIELD_READING)
        pitch_positions = value(FIELD_PITCH_POSITIONS)

        # Per-note field presence ( --note-id may resolve field flags from another type).
        note_has_audio = FIELD_AUDIO in fields
        note_has_reading_audio = FIELD_READING_AUDIO in fields
        note_has_easy = FIELD_SENTENCE_AUDIO_EASY in fields
        if note_has_easy:
            sentence_audio_easy = value(FIELD_SENTENCE_AUDIO_EASY)
        if note_has_audio:
            word_audio = value(FIELD_AUDIO)
        if note_has_reading_audio:
            reading_audio = value(FIELD_READING_AUDIO)

        note_actions: list[str] = []
        did_sentence = False
        if not args.surface_only and not _logic.uses_native_sentence_clip(model_name):
            sentence_audio = unwrap_satori_normal_if_needed(
                base_url=args.anki_connect,
                note_id=nid,
                note_type_name=model_name,
                sentence_audio=sentence_audio,
            )
            if args.force or should_synthesize_note(
                note_type_name=model_name,
                sentence=sentence,
                sentence_furigana=sentence_furigana,
                sentence_audio=sentence_audio,
                sentence_audio_easy=sentence_audio_easy if has_easy else "",
                config=config,
                on_mine=True,
            ):
                tts_text = sentence_text_for_tts(sentence, sentence_furigana)
                if tts_text:
                    needed = sentence_audio_fields_needing_synth(
                        sentence_audio=sentence_audio,
                        sentence_audio_easy=sentence_audio_easy if has_easy else "[sound:skip]",
                        force=args.force,
                        note_type_name=model_name,
                    )
                    if not has_easy:
                        needed = tuple(
                            name for name in needed if name != FIELD_SENTENCE_AUDIO_EASY
                        )
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
                            pitch_positions=pitch_positions,
                            match_kana=(reading or "").strip(),
                            update_sentence_pitch_graphs=True,
                        ):
                            note_ok = True
                        else:
                            note_failed = True
                    if note_ok:
                        ok += 1
                        did_sentence = True
                        note_actions.append("sentence")
                    elif note_failed:
                        failed += 1
                        note_actions.append("sentence-fail")
                    else:
                        skipped += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        elif not args.surface_only:
            skipped += 1

        if model_name in SURFACE_AUDIO_NOTE_TYPES:
            surface = surface_span_text(sentence, expression, reading)
            reading_text = (reading or "").strip()

            if note_has_audio and (
                args.force or args.surface_only or not sentence_audio_already_set(word_audio)
            ):
                # Candidates previously stored Reading TTS in Audio — always
                # (re)fill Target from the surface span when forcing/surface-only.
                tts_surface = surface or voicevox_reading_tts_text(expression, reading_text)
                if not tts_surface:
                    surface_skipped += 1
                else:
                    # Dictionary pitch maps cleanly to lemma/reading TTS, not conjugations.
                    surface_pitch = (
                        pitch_positions
                        if tts_surface
                        in {
                            (reading_text or "").strip(),
                            (expression or "").strip(),
                            voicevox_reading_tts_text(expression, reading_text),
                        }
                        else ""
                    )
                    if store_field_audio(
                        base_url=args.anki_connect,
                        note_id=nid,
                        note_type_name=model_name,
                        field_name=FIELD_AUDIO,
                        tts_text=tts_surface,
                        config=config,
                        speed_scale=config.voicevox_speed_scale,
                        force=args.force or (
                            # Candidate Audio held Reading TTS before ReadingAudio existed.
                            model_name == SHADOWING_CANDIDATE_NOTE_TYPE and args.surface_only
                        ),
                        pitch_positions=surface_pitch,
                    ):
                        surface_ok += 1
                        note_actions.append("target")
                    else:
                        surface_failed += 1
                        note_actions.append("target-fail")
            elif note_has_audio:
                surface_skipped += 1

            if note_has_reading_audio and (
                args.force
                or args.surface_only
                or not sentence_audio_already_set(reading_audio)
            ):
                reading_tts = voicevox_reading_tts_text(expression, reading_text)
                if not reading_tts:
                    reading_skipped += 1
                elif store_field_audio(
                    base_url=args.anki_connect,
                    note_id=nid,
                    note_type_name=model_name,
                    field_name=FIELD_READING_AUDIO,
                    tts_text=reading_tts,
                    config=config,
                    speed_scale=config.voicevox_speed_scale,
                    force=args.force,
                    pitch_positions=pitch_positions,
                    match_kana=reading_text,
                ):
                    reading_ok += 1
                    note_actions.append("reading")
                else:
                    reading_failed += 1
                    note_actions.append("reading-fail")
            elif note_has_reading_audio:
                reading_skipped += 1

        _ = did_sentence  # keep branch clarity for sentence counters above
        label = expression or reading or sentence[:20] or str(nid)
        action = ",".join(note_actions) if note_actions else "skip"
        print(f"[{index}/{total}] {label} · {action}", flush=True)

    print(f"Sentence audio: {ok} synthesized, {failed} failed, {skipped} skipped.")
    print(
        f"Target (surface) audio: {surface_ok} synthesized, "
        f"{surface_failed} failed, {surface_skipped} skipped."
    )
    print(
        f"Reading audio: {reading_ok} synthesized, "
        f"{reading_failed} failed, {reading_skipped} skipped."
    )


if __name__ == "__main__":
    main()
