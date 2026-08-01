# VOICEVOX TTS for immersion cards — design plan (deferred)

**Status:** Partial — immersion Target/Reading TTS can override VOICEVOX accent from Kanjium `PitchPositions`; full-sentence accent alignment still deferred  
**Last updated:** 2026-07-30  
**Scope v1:** Migaku immersion deck (`WK Migaku Immersion`); extend to grammar cloze later if useful

> **Prerequisite:** [Migaku immersion mining](migaku_mining.md) deck imported.

---

## Goals

| Goal | How |
|------|-----|
| High-quality Japanese sentence audio | Local [VOICEVOX](https://voicevox.hiroshiba.jp/) engine (`http://127.0.0.1:50021`) |
| Cards ready before tooling exists | **VoicevoxAudio** + **VoicevoxSpeakerId** fields; template prefers VOICEVOX over mined/TTS |
| Optional Kanjium pitch alignment | **Word-level done** (Target/Reading). **Sentence-level still open** — see Phase 3 revisit |
| No breakage today | Empty **VoicevoxAudio** → existing **Audio** (Yomitan) → Anki `{{tts}}` fallback |

## Revisit — sentence accents (~mid-August 2026)

**Reminder (set 2026-07-30):** around **2026-08-13**, pick up multi-word **Sentence** / Easy/Normal TTS pitch.

Word TTS already overrides `accent_phrases[].accent` from note `PitchPositions`. What’s left:

1. Map the mined word’s Kanjium position onto the matching phrase inside a multi-phrase `/audio_query` for the full sentence.
2. Decide fallback when the surface is conjugated or the word spans multiple VOICEVOX phrases.
3. Wire through `synthesize_immersion_sentence_audio.py` (not only `--surface-only`).
4. Document limits when alignment fails (keep VOICEVOX default).

Tracker: Phase 3 checkbox “Handle multi-word **Sentence** audio” below.

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
- [x] Document in [migaku_mining.md](migaku_mining.md)  
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

- [x] Parse **PitchPositions** + apply to Target / Reading word TTS via `accent_phrases[].accent`
- [ ] Handle multi-word **Sentence** audio (align word pitch inside multi-phrase queries)
- [x] Fallback to VOICEVOX default accent when Kanjium / PitchPositions missing  

**Exit (word-level):** ReadingAudio (and lemma Target) follow Kanjium; conjugated surface Target keeps VOICEVOX default.

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

- [migaku_mining.md](migaku_mining.md) — current mining setup  
- [wk_immersion_youtube_design.md](wk_immersion_youtube_design.md) — clip audio (different pipeline)  
- External: [Toocanzs/anki-voicevox](https://github.com/Toocanzs/anki-voicevox) — interim manual workflow (writes **Audio**, not **VoicevoxAudio**)

**Interim workaround:** Use third-party VOICEVOX add-ons targeting **Sentence** → **Audio**; after phase 1, switch destination to **VoicevoxAudio** so Yomitan clips and VOICEVOX can coexist.
