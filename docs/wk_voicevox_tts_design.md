# VOICEVOX TTS for immersion cards — design plan (deferred)

**Status:** Planned — note type reserved (template v5+); synthesis tooling not built  
**Last updated:** 2026-07-04  
**Scope v1:** Yomitan immersion deck (`WK Yomitan Immersion`); extend to grammar cloze later if useful

> **Prerequisite:** [Yomitan immersion mining](yomitan_mining.md) deck imported; optional Kanjium pitch fields on notes.

---

## Goals

| Goal | How |
|------|-----|
| High-quality Japanese sentence audio | Local [VOICEVOX](https://voicevox.hiroshiba.jp/) engine (`http://127.0.0.1:50021`) |
| Cards ready before tooling exists | **VoicevoxAudio** + **VoicevoxSpeakerId** fields; template prefers VOICEVOX over mined/TTS |
| Optional Kanjium pitch alignment | Future: map **PitchPositions** → VOICEVOX `accent_phrases` before `/synthesis` |
| No breakage today | Empty **VoicevoxAudio** → existing **Audio** (Yomitan) → Anki `{{tts}}` fallback |

## Non-goals (v1)

- Replacing edge-tts on WK grammar / vocab-cloze decks
- Cloud VOICEVOX (su-shiki) — local engine only unless user opts in later
- Auto-synthesis on every Yomitan mine (post-mine batch or menu action first)

---

## Note type (done — template v5)

| Field | Purpose today | Future tooling |
|-------|---------------|----------------|
| **Audio** | Yomitan `{audio}` (dictionary clips) | Unchanged |
| **VoicevoxAudio** | Empty at mine time | `[sound:…]` from VOICEVOX WAV |
| **VoicevoxSpeakerId** | Empty at mine time | VOICEVOX style/speaker id used for synthesis (e.g. `3` = ずんだもん) |
| **PitchPositions** | Kanjium via Yomitan | Input to accent-phrase override (phase 3) |
| **Sentence** | Source text for TTS | VOICEVOX `/accent_phrases` input |

### Template audio priority (back)

1. **VoicevoxAudio** — if non-empty  
2. **Audio** — Yomitan-mined clip  
3. **{{tts ja_JP:Sentence}}** — system voice fallback  

---

## Implementation phases

### Phase 0 — Schema + docs (done)

- [x] Add **VoicevoxAudio**, **VoicevoxSpeakerId** to mining note type  
- [x] Template audio cascade  
- [x] Document in [yomitan_mining.md](yomitan_mining.md)  
- [x] Tracker row in [wk_core_srs_design.md](wk_core_srs_design.md)  

### Phase 1 — Local VOICEVOX batch synthesis (CLI or Anki menu)

- [ ] `voicevox_tts.py` — given text + speaker id → WAV in `collection.media`  
- [ ] Read **Sentence** (or **Reading** for word-only), write **VoicevoxAudio**  
- [ ] Default speaker from config (`voicevox.default_speaker_id`)  
- [ ] Anki add-on menu: **Tools → WK Synthesize VOICEVOX (Immersion)** — selected notes or deck  
- [ ] Tests with mocked HTTP (no VOICEVOX required in CI)  

**Exit:** Browse → select mined notes → menu → **VoicevoxAudio** populated; card plays VOICEVOX on review.

### Phase 2 — Yomitan / post-mine hook (optional)

- [ ] Yomitan custom audio URL → local wrapper that calls VOICEVOX and returns MP3/WAV at mine time  
- [ ] Or: AnkiConnect hook after `note_will_be_added` — synthesize async, fill **VoicevoxAudio**  

**Exit:** New mines get VOICEVOX audio without manual batch step (when engine running).

### Phase 3 — Kanjium pitch → VOICEVOX accent phrases (research)

- [ ] Parse **PitchPositions** + **Reading** for target mora  
- [ ] `POST /accent_phrases` → edit `accent` on matching **AccentPhrase** → `/synthesis`  
- [ ] Handle multi-word sentences (one mined word vs full sentence accent)  
- [ ] Fallback to VOICEVOX default accent when Kanjium missing  

**Exit:** Synthesized audio matches Kanjium display for single-word mines; documented limits for full sentences.

---

## VOICEVOX API sketch (phase 1)

```bash
# Engine must be running (VOICEVOX.app or voicevox_engine)
curl -s -X POST "http://127.0.0.1:50021/audio_query?text=学生&speaker=3" | \
  curl -s -H "Content-Type: application/json" -X POST \
    "http://127.0.0.1:50021/synthesis?speaker=3" -d @- -o out.wav
```

Store as `[sound:voicevox_{hash}.wav]` in **VoicevoxAudio**; set **VoicevoxSpeakerId** to `3` for reproducibility.

---

## Config (planned)

```json
"voicevox": {
  "engine_url": "http://127.0.0.1:50021",
  "default_speaker_id": 3,
  "synthesize_on_mine": false
}
```

---

## Related

- [yomitan_mining.md](yomitan_mining.md) — current mining setup  
- [wk_immersion_youtube_design.md](wk_immersion_youtube_design.md) — clip audio (different pipeline)  
- External: [Toocanzs/anki-voicevox](https://github.com/Toocanzs/anki-voicevox) — interim manual workflow (writes **Audio**, not **VoicevoxAudio**)

**Interim workaround:** Use third-party VOICEVOX add-ons targeting **Sentence** → **Audio**; after phase 1, switch destination to **VoicevoxAudio** so Yomitan clips and VOICEVOX can coexist.
