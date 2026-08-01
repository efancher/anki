"""
WK Immersion — Yomitan (primary) / Migaku (legacy) mining enrichment + sentence TTS.

Runs on note_will_be_added (Yomitan/Migaku → Anki) and optional batch menus.
Uses existing SentenceAudio when present; otherwise VOICEVOX / edge-tts.

Tools → WK Enrich Mining Notes
Tools → WK Synthesize Immersion Sentence Audio
Tools → WK Configure Migaku Field Map (legacy)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from anki import hooks as anki_hooks
from aqt import gui_hooks, mw
from aqt.qt import QAction
from aqt.utils import showInfo, showWarning, tooltip

from .logic import (
    FIELD_READING,
    FIELD_PITCH_POSITIONS,
    FIELD_SENTENCE,
    FIELD_SENTENCE_AUDIO,
    FIELD_SENTENCE_AUDIO_EASY,
    FIELD_SENTENCE_FURIGANA,
    FIELD_SPEAKER,
    MINING_NOTE_TYPE,
    ImmersionTtsConfig,
    audio_field_value,
    parse_primary_pitch_position,
    sentence_audio_autoplay,
    sentence_audio_fields_needing_synth,
    sentence_media_basename,
    sentence_text_for_tts,
    should_synthesize_note,
    synthesize_sentence_audio,
    unwrap_sound_tag,
    uses_native_sentence_clip,
)
from .migaku_field_map import configure_migaku_field_map
from .mining_enrich import apply_mining_enrichment
from .mining_note_types import MINING_NOTE_TYPES, SATORI_NOTE_TYPE, is_mining_note_type
from .model_upgrade import ensure_immersion_model

ADDON_NAME = "WK Immersion"
DEFAULT_CONFIG_NAME = "wk_immersion_config.json"
EDGE_TTS_SCRIPT = Path(__file__).resolve().parent / "edge_tts_once.py"


def candidate_config_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.environ.get("WK_IMMERSION_CONFIG")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.extend(
        [
            Path.home() / "anki" / "out" / DEFAULT_CONFIG_NAME,
            Path.cwd() / "out" / DEFAULT_CONFIG_NAME,
            Path.cwd() / DEFAULT_CONFIG_NAME,
        ]
    )
    seen = set()
    unique: List[Path] = []
    for path in paths:
        key = str(path.expanduser())
        if key not in seen:
            seen.add(key)
            unique.append(path.expanduser())
    return unique


def load_immersion_config() -> ImmersionTtsConfig:
    for path in candidate_config_paths():
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return ImmersionTtsConfig.from_mapping(payload)
    return ImmersionTtsConfig()


def _field_map(note) -> Dict[str, int]:
    return {field["name"]: index for index, field in enumerate(note.note_type()["flds"])}


def _model_field_names() -> List[str]:
    if mw.col is None:
        return []
    for name in (MINING_NOTE_TYPE, *sorted(MINING_NOTE_TYPES - {MINING_NOTE_TYPE})):
        model = mw.col.models.by_name(name)
        if model is not None:
            return [field["name"] for field in model["flds"]]
    return []


def _missing_required_field_names(field_names: List[str]) -> List[str]:
    return [
        name
        for name in (FIELD_SENTENCE, FIELD_SENTENCE_AUDIO, FIELD_SENTENCE_AUDIO_EASY)
        if name not in field_names
    ]


def _note_type_update_message(missing: List[str]) -> str:
    missing_text = ", ".join(missing)
    return (
        f"Mining note type is missing field(s): {missing_text}.\n\n"
        "Update the note type:\n"
        "  For Satori: python3 scripts/import_satori.py … → Import → Update WK Satori Immersion\n"
        "  For Yomitan: python3 wk_decks.py --deck mining → Import out/wk_mining.apkg → Update\n"
        "  Then run this action again"
    )


def _field_value(note, name: str) -> str:
    ord_index = _field_map(note).get(name)
    if ord_index is None:
        return ""
    return note.fields[ord_index] or ""


def _set_field(note, name: str, value: str) -> bool:
    ord_index = _field_map(note).get(name)
    if ord_index is None:
        return False
    if note.fields[ord_index] == value:
        return False
    note.fields[ord_index] = value
    return True


def _add_media_bytes(col, audio_bytes: bytes, basename: str, ext: str) -> str:
    if col.media.have(basename):
        return basename
    suffix = ext if ext.startswith(".") else f".{ext}"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(audio_bytes)
        temp_path = Path(handle.name)
    try:
        return col.media.add_file(str(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)


def _store_one_sentence_audio(
    note,
    *,
    col,
    config: ImmersionTtsConfig,
    tts_text: str,
    field_name: str,
    speed_scale: float,
    silent: bool,
    force: bool = False,
    pitch_accent=None,
    match_kana: str = "",
) -> bool:
    with tempfile.TemporaryDirectory(prefix="wk_immersion_tts_") as tmp:
        temp_dir = Path(tmp)
        audio_bytes, ext, engine_label = synthesize_sentence_audio(
            tts_text,
            config=config,
            temp_dir=temp_dir,
            edge_tts_script=EDGE_TTS_SCRIPT,
            speed_scale=speed_scale,
            force=force,
            pitch_accent=pitch_accent,
            match_kana=match_kana,
        )
        if not audio_bytes or not ext:
            if not silent:
                showWarning(
                    "Could not synthesize sentence audio. "
                    "Start VOICEVOX (or set engine to edge in wk_immersion_config.json)."
                )
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
        stored_name = _add_media_bytes(col, audio_bytes, basename, ext)
        note_type_name = note.note_type()["name"]
        autoplay = sentence_audio_autoplay(
            note_type_name=note_type_name, field_name=field_name
        )
        changed = _set_field(
            note, field_name, audio_field_value(stored_name, autoplay=autoplay)
        )
        if not changed:
            if field_name not in _field_map(note):
                if not silent:
                    showWarning(_note_type_update_message([field_name]))
                return False
            return True
        if engine_label == "voicevox":
            _set_field(note, FIELD_SPEAKER, str(config.voicevox_speaker_id))
        return True


def _ensure_sound_tag_audio(note, field_name: str) -> bool:
    """Store ``[sound:]`` so Anki tracks media and AnkiMobile can play it."""
    raw = _field_value(note, field_name)
    bare = unwrap_sound_tag(raw)
    if not bare:
        return False
    tagged = audio_field_value(bare, autoplay=True)
    if tagged == (raw or "").strip():
        return False
    return _set_field(note, field_name, tagged)


def _unwrap_satori_normal_audio(note) -> bool:
    """Compat alias: Normal stays ``[sound:]``; deck options control autoplay."""
    return _ensure_sound_tag_audio(note, FIELD_SENTENCE_AUDIO)


def _store_sentence_audio(
    note,
    *,
    col,
    config: ImmersionTtsConfig,
    silent: bool,
    force: bool = False,
) -> bool:
    sentence = _field_value(note, FIELD_SENTENCE)
    sentence_furigana = _field_value(note, FIELD_SENTENCE_FURIGANA)
    existing_audio = _field_value(note, FIELD_SENTENCE_AUDIO)
    existing_easy = _field_value(note, FIELD_SENTENCE_AUDIO_EASY)
    note_type_name = note.note_type()["name"]
    unwrapped = _unwrap_satori_normal_audio(note)
    if unwrapped:
        existing_audio = _field_value(note, FIELD_SENTENCE_AUDIO)
    if uses_native_sentence_clip(note_type_name):
        return unwrapped

    if not should_synthesize_note(
        note_type_name=note_type_name,
        sentence=sentence,
        sentence_furigana=sentence_furigana,
        sentence_audio=existing_audio,
        sentence_audio_easy=existing_easy,
        config=config,
        on_mine=True,
    ) and not force:
        return unwrapped

    tts_text = sentence_text_for_tts(sentence, sentence_furigana)
    if not tts_text:
        return unwrapped

    needed = sentence_audio_fields_needing_synth(
        sentence_audio=existing_audio,
        sentence_audio_easy=existing_easy,
        force=force,
        note_type_name=note_type_name,
    )
    if not needed:
        return unwrapped

    pitch_accent = parse_primary_pitch_position(_field_value(note, FIELD_PITCH_POSITIONS))
    match_kana = (_field_value(note, FIELD_READING) or "").strip()

    any_ok = unwrapped
    for field_name in needed:
        speed = (
            config.voicevox_easy_speed_scale
            if field_name == FIELD_SENTENCE_AUDIO_EASY
            else config.voicevox_speed_scale
        )
        if _store_one_sentence_audio(
            note,
            col=col,
            config=config,
            tts_text=tts_text,
            field_name=field_name,
            speed_scale=speed,
            silent=silent,
            force=force,
            pitch_accent=pitch_accent,
            match_kana=match_kana,
        ):
            any_ok = True
        elif not silent and field_name == FIELD_SENTENCE_AUDIO:
            return False
    return any_ok


def synthesize_for_note_ids(note_ids: List[int], *, silent: bool, force: bool = False) -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    config = load_immersion_config()
    if not config.enabled:
        showWarning("WK Immersion TTS is disabled in config.")
        return

    ok = 0
    skipped = 0
    failed = 0
    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        if not is_mining_note_type(note.note_type()["name"]):
            skipped += 1
            continue
        if _store_sentence_audio(note, col=mw.col, config=config, silent=silent, force=force):
            note.flush()
            ok += 1
        elif should_synthesize_note(
            note_type_name=note.note_type()["name"],
            sentence=_field_value(note, FIELD_SENTENCE),
            sentence_furigana=_field_value(note, FIELD_SENTENCE_FURIGANA),
            sentence_audio=_field_value(note, FIELD_SENTENCE_AUDIO),
            sentence_audio_easy=_field_value(note, FIELD_SENTENCE_AUDIO_EASY),
            config=config,
            on_mine=True,
        ):
            failed += 1
        else:
            skipped += 1

    mw.col.save()
    message = f"Sentence audio: {ok} synthesized, {failed} failed, {skipped} skipped."
    if silent:
        tooltip(message)
    else:
        if failed:
            showWarning(
                message
                + "\n\nStart VOICEVOX before running this action, or set "
                '"engine": "edge" in wk_immersion_config.json.'
            )
        else:
            showInfo(message)


def _enrich_mining_note(note) -> None:
    field_map = _field_map(note)
    if "ClozeSentence" not in field_map:
        return
    apply_mining_enrichment(note, field_map=field_map)


def on_note_will_be_added(col, note, deck_id) -> None:
    """Yomitan/Migaku → Anki — enrich cloze; synthesize only when SentenceAudio empty."""
    try:
        if col is None or not is_mining_note_type(note.note_type()["name"]):
            return
        ensure_immersion_model(col)
        _enrich_mining_note(note)
        config = load_immersion_config()
        if not config.enabled or not config.on_mine:
            return
        _store_sentence_audio(note, col=col, config=config, silent=True)
    except Exception as exc:
        # Never block note creation — user can backfill from Tools menu.
        print(f"wk_immersion: {exc}")


def on_add_cards_did_add_note(_note) -> None:
    """Add dialog path — note is saved after this hook; batch menu can backfill."""
    pass


def enrich_mining_notes(note_ids: List[int], *, silent: bool) -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    if ensure_immersion_model(mw.col):
        mw.col.save()
    ok = 0
    skipped = 0
    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        if not is_mining_note_type(note.note_type()["name"]):
            skipped += 1
            continue
        if apply_mining_enrichment(note, field_map=_field_map(note)):
            note.flush()
            ok += 1
        else:
            skipped += 1
    mw.col.save()
    message = f"Mining enrich: {ok} updated, {skipped} skipped."
    if silent:
        tooltip(message)
    else:
        showInfo(message)


def _mining_notes_query(extra: str = "") -> str:
    note_clause = " OR ".join(f'note:"{name}"' for name in sorted(MINING_NOTE_TYPES))
    query = f"({note_clause})"
    if extra:
        query = f"{query} {extra}"
    return query


def enrich_selected_mining_notes() -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    note_ids = mw.col.find_notes(_mining_notes_query("-tag:mining-setup"))
    if not note_ids:
        showInfo("No mining notes found.")
        return
    enrich_mining_notes([int(note_id) for note_id in note_ids], silent=False)


def synthesize_missing_sentence_audio() -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    if ensure_immersion_model(mw.col):
        mw.col.save()
    missing = _missing_required_field_names(_model_field_names())
    if missing:
        showWarning(_note_type_update_message(missing))
        return
    config = load_immersion_config()
    note_ids = []
    for note_id in mw.col.find_notes(_mining_notes_query()):
        note = mw.col.get_note(note_id)
        if sentence_text_for_tts(
            _field_value(note, FIELD_SENTENCE),
            _field_value(note, FIELD_SENTENCE_FURIGANA),
        ) and sentence_audio_fields_needing_synth(
            sentence_audio=_field_value(note, FIELD_SENTENCE_AUDIO),
            sentence_audio_easy=_field_value(note, FIELD_SENTENCE_AUDIO_EASY),
        ):
            note_ids.append(int(note_id))
    if not note_ids:
        showInfo("No immersion notes need sentence audio.")
        return
    synthesize_for_note_ids(note_ids, silent=False)


def configure_migaku_map_action() -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    try:
        message = configure_migaku_field_map(mw.col, mw.addonManager)
    except RuntimeError as exc:
        showWarning(str(exc))
        return
    showInfo(message)


def setup_menu() -> None:
    action = QAction("WK Synthesize Immersion Sentence Audio", mw)
    action.triggered.connect(synthesize_missing_sentence_audio)
    mw.form.menuTools.addAction(action)
    enrich_action = QAction("WK Enrich Mining Notes (cloze + WK links)", mw)
    enrich_action.triggered.connect(enrich_selected_mining_notes)
    mw.form.menuTools.addAction(enrich_action)
    migaku_action = QAction("WK Configure Migaku Field Map", mw)
    migaku_action.triggered.connect(configure_migaku_map_action)
    mw.form.menuTools.addAction(migaku_action)


def on_main_window_did_init() -> None:
    setup_menu()
    if mw.col is not None and ensure_immersion_model(mw.col):
        mw.col.save()


def register_hooks() -> None:
    try:
        anki_hooks.note_will_be_added.remove(on_note_will_be_added)
    except ValueError:
        pass
    anki_hooks.note_will_be_added.append(on_note_will_be_added)
    if hasattr(gui_hooks, "add_cards_did_add_note"):
        try:
            gui_hooks.add_cards_did_add_note.remove(on_add_cards_did_add_note)
        except ValueError:
            pass
        gui_hooks.add_cards_did_add_note.append(on_add_cards_did_add_note)


register_hooks()
gui_hooks.main_window_did_init.append(on_main_window_did_init)
