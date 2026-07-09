# VOICEVOX setup for immersion mining

Use [VOICEVOX](https://voicevox.hiroshiba.jp/) to generate **full-sentence audio** when you mine cards from Yomitan. The **wk_immersion** Anki add-on calls VOICEVOX over HTTP — you do **not** need to use VOICEVOX’s Japanese UI for mining.

**Related:** [Yomitan immersion mining](yomitan_mining.md) · [wk_immersion add-on](../anki_addon/README.md#wk_immersion)

---

## What happens automatically

1. You click **+** in Yomitan (Anki + AnkiConnect running).
2. **wk_immersion** reads the note’s **Sentence** field.
3. It POSTs to the local VOICEVOX engine (`http://127.0.0.1:50021`).
4. The WAV is stored in Anki media and **SentenceAudio** is set to `[sound:…]`.

Yomitan never maps **SentenceAudio** — the add-on fills it after the note is created.

---

## Quick start (Mac)

1. **Download** VOICEVOX from [voicevox.hiroshiba.jp](https://voicevox.hiroshiba.jp/) and install to **Applications**.
2. **Launch VOICEVOX** and leave it open while you mine. The engine starts automatically on port **50021**.
3. **Sync the add-on** and restart Anki:
   ```bash
   ./scripts/sync_anki_addons.sh
   ```
4. **Verify** the engine in a browser: [http://127.0.0.1:50021/version](http://127.0.0.1:50021/version) — you should see a version string (e.g. `"0.25.2"`).
5. Mine a word in Yomitan. After a short pause, open **Browse** → note → **SentenceAudio** should contain `[sound:wk_immersion_sent_….wav]`.

That is the entire VOICEVOX “setup” for this workflow.

---

## You do not need the Japanese UI

VOICEVOX’s window is for manually typing text and previewing voices. For Anki mining, **only the background engine matters**.

| UI area (Japanese) | Meaning | Needed for mining? |
|--------------------|---------|-------------------|
| Left panel — character list | Pick a voice to preview | No — voice comes from config (below) |
| Center — テキストを入力 | Text box + ▶ play | No |
| Menus (ファイル, 設定, …) | File / settings | No |

Keep the app running; ignore the rest unless you want to audition voices.

---

## Add-on config

Optional file: **`out/wk_immersion_config.json`** (created on first use if missing).

```json
{
  "enabled": true,
  "on_mine": true,
  "engine": "voicevox",
  "voicevox_engine_url": "http://127.0.0.1:50021",
  "voicevox_speaker_id": 2,
  "voicevox_volume_scale": 1.5,
  "edge_tts_voice": "ja-JP-NanamiNeural",
  "python_executable": ""
}
```

| Key | Default | Meaning |
|-----|---------|---------|
| `enabled` | `true` | Master switch for sentence TTS |
| `on_mine` | `true` | Synthesize when Yomitan adds a note |
| `engine` | `voicevox` | `voicevox`, `edge`, or `auto` (try VOICEVOX, then edge-tts) |
| `voicevox_engine_url` | `http://127.0.0.1:50021` | VOICEVOX HTTP API base URL |
| `voicevox_speaker_id` | `2` | Numeric style id (see table below) |
| `voicevox_volume_scale` | `1.5` | VOICEVOX `volumeScale` (1.0 = engine default; try 1.25–2.0) |
| `edge_tts_voice` | `ja-JP-NanamiNeural` | Used when `engine` is `edge` or `auto` fallback |
| `python_executable` | `""` | Path to Python for edge-tts; empty = `python3` on PATH |

After editing config, restart Anki (or use **Tools → WK Synthesize Immersion Sentence Audio** to test without re-mining).

---

## Choosing a voice (speaker id)

Default **`voicevox_speaker_id`: 2** = **四国めたん** (Shikoku Metan), normal style.

Common ids (VOICEVOX must be running to list all):

| ID | Character | Style |
|----|-----------|-------|
| 2 | 四国めたん (Shikoku Metan) | Normal — **default** |
| 3 | ずんだもん (Zundamon) | Normal |
| 8 | 春日部つむぎ (Kasukabe Tsumugi) | Normal |
| 11 | 玄野武宏 (Genno Takehiro) | Normal (male) |
| 13 | 青山龍星 (Aoyama Ryusei) | Normal (male) |

**List every voice** (Terminal, engine running):

```bash
curl -s http://127.0.0.1:50021/speakers | python3 -m json.tool
```

Use the `"id"` under each entry in `"styles"` — not the character’s display name.

---

## Without VOICEVOX (edge-tts fallback)

If you prefer not to run VOICEVOX:

```bash
pip install edge-tts
```

Set in `out/wk_immersion_config.json`:

```json
{
  "engine": "edge"
}
```

Or `"engine": "auto"` to try VOICEVOX first and fall back to edge-tts when the engine is down.

edge-tts uses Microsoft’s online voices (requires network). Output is MP3 instead of WAV.

---

## Backfill existing cards

Notes mined before **wk_immersion** was installed may have an empty **SentenceAudio**:

- **Anki menu:** **Tools → WK Synthesize Immersion Sentence Audio** (selected notes or whole deck).
- **CLI** (Anki + AnkiConnect running):
  ```bash
  python3 scripts/synthesize_immersion_sentence_audio.py
  ```

---

## Troubleshooting

### `curl http://127.0.0.1:50021/version` fails

- Launch **VOICEVOX.app** and wait a few seconds.
- Quit other copies of VOICEVOX or duplicate engine processes (only one listener on port 50021).
- Firewall: allow local connections to `127.0.0.1:50021`.

### Mining works but **SentenceAudio** stays empty

1. Confirm add-on is installed: **Tools → Add-ons** → **WK Immersion Sentence TTS**.
2. Re-sync: `./scripts/sync_anki_addons.sh` → restart Anki.
3. Check config: `"enabled": true`, `"on_mine": true`, `"engine": "voicevox"`.
4. Note must use model **WK Yomitan Immersion** and have non-empty **Sentence**.
5. Try **Tools → WK Synthesize Immersion Sentence Audio** on one note — if that works, the hook path may need attention; if not, VOICEVOX or config is the issue.

### Backfill CLI: `missing Sentence or SentenceAudio`

Your **WK Yomitan Immersion** note type is outdated — it was imported before **SentenceAudio** existed.

**Automatic fix (recommended):** restart Anki after syncing add-ons. **WK Immersion** adds **SentenceAudio** and upgrades the card template on startup.

**Manual fix:** if the field is still missing:

1. Regenerate: `python3 wk_decks.py --deck mining`
2. **File → Import** → `out/wk_mining.apkg`
3. Choose **Update** for **WK Yomitan Immersion** (not “Add new”)
4. Re-run the backfill tool or menu action

### Backfill CLI: `Connection refused`

The script talks to **AnkiConnect** (default `http://127.0.0.1:8765`), not VOICEVOX directly.

1. **Open Anki** (the app must be running).
2. Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) if missing.
3. Visit [http://127.0.0.1:8765](http://127.0.0.1:8765) — you should see an AnkiConnect banner.
4. Re-run: `python3 scripts/synthesize_immersion_sentence_audio.py`

If you customized AnkiConnect’s port: `--anki-connect http://127.0.0.1:YOUR_PORT`

**Alternative:** **Tools → WK Synthesize Immersion Sentence Audio** inside Anki — no AnkiConnect required.

### Mining is slow

VOICEVOX synthesis runs **before** the note is saved. Long sentences can take several seconds. This is expected.

### Wrong or unexpected voice

Change `voicevox_speaker_id` in config and re-synthesize (backfill menu or delete **SentenceAudio** and run batch tool).

---

## Card playback order

On the immersion card **back**, two labeled players:

| Label | Field / source | Fallback |
|-------|----------------|----------|
| **Word** | **Audio** (Yomitan `{audio}` clip) | TTS on **Reading**, then **Expression** |
| **Sentence** | **SentenceAudio** (wk_immersion) | **VoicevoxAudio** → TTS on **Sentence** |

---

## Technical reference

VOICEVOX exposes a REST API. The add-on uses:

```
POST /audio_query?text=…&speaker=…
POST /synthesis?speaker=…  (body = audio_query JSON)
```

Interactive API docs (engine running): [http://127.0.0.1:50021/docs](http://127.0.0.1:50021/docs)

Implementation: `anki_addon/wk_immersion/logic.py`
