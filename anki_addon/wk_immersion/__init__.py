"""
WK Immersion — Migaku mining enrichment and sentence-audio fallback at add time.

Runs on note_will_be_added (Migaku → Anki) and optional batch menu.
Uses native Migaku SentenceAudio when present; otherwise VOICEVOX / edge-tts.

Tools → WK Synthesize Immersion Sentence Audio
Tools → WK Enrich Mining Notes
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
    FIELD_SENTENCE,
    FIELD_SENTENCE_AUDIO,
    FIELD_SENTENCE_FURIGANA,
    FIELD_SPEAKER,
    MINING_NOTE_TYPE,
    ImmersionTtsConfig,
    sentence_media_basename,
    sentence_text_for_tts,
    should_synthesize_note,
    sound_field_value,
    synthesize_sentence_audio,
)
from .migaku_field_map import configure_migaku_field_map
from .mining_enrich import apply_mining_enrichment
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
    model = mw.col.models.by_name(MINING_NOTE_TYPE)
    if model is None:
        return []
    return [field["name"] for field in model["flds"]]


def _missing_required_field_names(field_names: List[str]) -> List[str]:
    return [
        name
        for name in (FIELD_SENTENCE, FIELD_SENTENCE_AUDIO)
        if name not in field_names
    ]


def _note_type_update_message(missing: List[str]) -> str:
    missing_text = ", ".join(missing)
    return (
        f"Note type {MINING_NOTE_TYPE!r} is missing field(s): {missing_text}.\n\n"
        "The add-on can synthesize audio but cannot store it until you update the note type:\n"
        "  1. python3 wk_decks.py --deck mining\n"
        "  2. Anki → File → Import → out/wk_migaku.apkg\n"
        "  3. Choose **Update** for WK Migaku Immersion\n"
        "  4. Run this action again"
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


def _store_sentence_audio(
    note,
    *,
    col,
    config: ImmersionTtsConfig,
    silent: bool,
) -> bool:
    sentence = _field_value(note, FIELD_SENTENCE)
    sentence_furigana = _field_value(note, FIELD_SENTENCE_FURIGANA)
    existing_audio = _field_value(note, FIELD_SENTENCE_AUDIO)
    if not should_synthesize_note(
        note_type_name=note.note_type()["name"],
        sentence=sentence,
        sentence_furigana=sentence_furigana,
        sentence_audio=existing_audio,
        config=config,
        on_mine=True,
    ):
        return False

    tts_text = sentence_text_for_tts(sentence, sentence_furigana)
    with tempfile.TemporaryDirectory(prefix="wk_immersion_tts_") as tmp:
        temp_dir = Path(tmp)
        audio_bytes, ext, engine_label = synthesize_sentence_audio(
            tts_text,
            config=config,
            temp_dir=temp_dir,
            edge_tts_script=EDGE_TTS_SCRIPT,
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
            ext=ext,
        )
        if col.media.have(basename):
            stored_name = basename
        else:
            suffix = ext if ext.startswith(".") else f".{ext}"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(audio_bytes)
                temp_path = Path(handle.name)
            try:
                stored_name = col.media.add_file(str(temp_path))
            finally:
                temp_path.unlink(missing_ok=True)

        changed = _set_field(note, FIELD_SENTENCE_AUDIO, sound_field_value(stored_name))
        if not changed:
            if FIELD_SENTENCE_AUDIO not in _field_map(note):
                if not silent:
                    showWarning(_note_type_update_message([FIELD_SENTENCE_AUDIO]))
            return False
        if engine_label == "voicevox":
            _set_field(note, FIELD_SPEAKER, str(config.voicevox_speaker_id))
        return True


def synthesize_for_note_ids(note_ids: List[int], *, silent: bool) -> None:
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
        if note.note_type()["name"] != MINING_NOTE_TYPE:
            skipped += 1
            continue
        if _store_sentence_audio(note, col=mw.col, config=config, silent=silent):
            note.flush()
            ok += 1
        elif should_synthesize_note(
            note_type_name=note.note_type()["name"],
            sentence=_field_value(note, FIELD_SENTENCE),
            sentence_furigana=_field_value(note, FIELD_SENTENCE_FURIGANA),
            sentence_audio=_field_value(note, FIELD_SENTENCE_AUDIO),
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
    """Migaku → Anki — enrich cloze fields; synthesize audio only when Migaku did not."""
    try:
        if col is None or note.note_type()["name"] != MINING_NOTE_TYPE:
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
        if note.note_type()["name"] != MINING_NOTE_TYPE:
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


def enrich_selected_mining_notes() -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    note_ids = mw.col.find_notes(f'note:"{MINING_NOTE_TYPE}" -tag:mining-setup')
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
    for note_id in mw.col.find_notes(f'note:"{MINING_NOTE_TYPE}"'):
        note = mw.col.get_note(note_id)
        if (
            sentence_text_for_tts(
                _field_value(note, FIELD_SENTENCE),
                _field_value(note, FIELD_SENTENCE_FURIGANA),
            )
            and not _field_value(note, FIELD_SENTENCE_AUDIO)
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
