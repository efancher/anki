"""
WK Immersion — synthesize full-sentence audio for Yomitan-mined notes.

Usage (Anki must be running; VOICEVOX engine recommended):

  python3 scripts/synthesize_immersion_sentence_audio.py
  python3 scripts/synthesize_immersion_sentence_audio.py --note-id 1234567890

Requires AnkiConnect (default http://127.0.0.1:8765) or use the in-Anki menu instead:
Tools → WK Synthesize Immersion Sentence Audio
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
LOGIC_PATH = REPO_ROOT / "anki_addon" / "wk_immersion" / "logic.py"
EDGE_TTS_SCRIPT = REPO_ROOT / "anki_addon" / "wk_immersion" / "edge_tts_once.py"


def _load_logic_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("wk_immersion_logic", LOGIC_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_logic = _load_logic_module()
FIELD_SENTENCE = _logic.FIELD_SENTENCE
FIELD_SENTENCE_FURIGANA = _logic.FIELD_SENTENCE_FURIGANA
FIELD_SENTENCE_AUDIO = _logic.FIELD_SENTENCE_AUDIO
MINING_NOTE_TYPE = _logic.MINING_NOTE_TYPE
ImmersionTtsConfig = _logic.ImmersionTtsConfig
sentence_media_basename = _logic.sentence_media_basename
sentence_text_for_tts = _logic.sentence_text_for_tts
should_synthesize_note = _logic.should_synthesize_note
sound_field_value = _logic.sound_field_value
synthesize_sentence_audio = _logic.synthesize_sentence_audio

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


def find_immersion_note_ids(base_url: str, note_id: Optional[int]) -> list[int]:
    if note_id is not None:
        return [note_id]
    return [int(nid) for nid in anki_request(base_url, "findNotes", query=f'note:"{MINING_NOTE_TYPE}"')]


def load_config() -> ImmersionTtsConfig:
    for path in (
        REPO_ROOT / "out" / "wk_immersion_config.json",
        REPO_ROOT / "wk_immersion_config.json",
    ):
        if path.is_file():
            return ImmersionTtsConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    return ImmersionTtsConfig()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument("--note-id", type=int, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing SentenceAudio (use after fixing Sentence / furigana fields)",
    )
    args = parser.parse_args()

    config = load_config()
    try:
        field_names = note_field_names(args.anki_connect, MINING_NOTE_TYPE)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Cannot reach AnkiConnect at {args.anki_connect}: {exc}\n"
            "• Open Anki and install the AnkiConnect add-on.\n"
            "• Confirm http://127.0.0.1:8765 loads in a browser.\n"
            "• If you changed AnkiConnect's port, pass --anki-connect http://127.0.0.1:PORT\n"
            "Or use Tools → WK Synthesize Immersion Sentence Audio inside Anki (no AnkiConnect needed)."
        ) from exc
    if FIELD_SENTENCE not in field_names or FIELD_SENTENCE_AUDIO not in field_names:
        missing = [
            name
            for name in (FIELD_SENTENCE, FIELD_SENTENCE_AUDIO)
            if name not in field_names
        ]
        raise SystemExit(
            f"Note type {MINING_NOTE_TYPE!r} is missing field(s): {', '.join(missing)}.\n"
            f"Fields in Anki now: {', '.join(field_names)}\n\n"
            "Your note type is outdated (imported before SentenceAudio was added).\n"
            "Fix:\n"
            "  1. python3 wk_decks.py --deck mining\n"
            "  2. Anki → File → Import → out/wk_mining.apkg\n"
            "  3. Choose **Update** (not Add) for note type WK Yomitan Immersion\n"
            "  4. Re-run this script\n\n"
            "Or use Tools → WK Synthesize Immersion Sentence Audio inside Anki after updating."
        )

    note_ids = find_immersion_note_ids(args.anki_connect, args.note_id)
    ok = failed = skipped = 0

    import tempfile

    for nid in note_ids:
        info = anki_request(args.anki_connect, "notesInfo", notes=[nid])[0]
        fields = info.get("fields") or {}
        sentence = (fields.get(FIELD_SENTENCE) or {}).get("value") or ""
        sentence_furigana = (fields.get(FIELD_SENTENCE_FURIGANA) or {}).get("value") or ""
        sentence_audio = (fields.get(FIELD_SENTENCE_AUDIO) or {}).get("value") or ""
        if not args.force and not should_synthesize_note(
            note_type_name=MINING_NOTE_TYPE,
            sentence=sentence,
            sentence_furigana=sentence_furigana,
            sentence_audio=sentence_audio,
            config=config,
            on_mine=True,
        ):
            skipped += 1
            continue
        tts_text = sentence_text_for_tts(sentence, sentence_furigana)
        if not tts_text:
            skipped += 1
            continue

        with tempfile.TemporaryDirectory(prefix="wk_immersion_cli_") as tmp:
            audio_bytes, ext, engine_label = synthesize_sentence_audio(
                tts_text,
                config=config,
                temp_dir=Path(tmp),
                edge_tts_script=EDGE_TTS_SCRIPT,
            )
        if not audio_bytes:
            failed += 1
            continue

        speaker_id = config.voicevox_speaker_id if engine_label == "voicevox" else 0
        volume_scale = config.voicevox_volume_scale if engine_label == "voicevox" else 1.0
        basename = sentence_media_basename(
            tts_text,
            engine=engine_label,
            speaker_id=speaker_id,
            volume_scale=volume_scale,
            ext=ext,
        )
        stored = anki_request(
            args.anki_connect,
            "storeMediaFile",
            filename=basename,
            data=__import__("base64").b64encode(audio_bytes).decode("ascii"),
        )
        anki_request(
            args.anki_connect,
            "updateNoteFields",
            note={
                "id": nid,
                "fields": {FIELD_SENTENCE_AUDIO: sound_field_value(stored or basename)},
            },
        )
        ok += 1

    print(f"Done: {ok} synthesized, {failed} failed, {skipped} skipped.")


if __name__ == "__main__":
    main()
