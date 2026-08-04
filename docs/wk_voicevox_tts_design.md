# VOICEVOX TTS for immersion cards — design plan (deferred)

**Status:** Partial — Target/Reading TTS and **sentence** TTS can override VOICEVOX accent from Kanjium `PitchPositions` when the word’s reading aligns to an accent phrase  
**Last updated:** 2026-08-01  
**Scope v1:** Migaku immersion deck (`WK Migaku Immersion`); extend to grammar cloze later if useful

> **Prerequisite:** [Migaku immersion mining](migaku_mining.md) deck imported.

---

## Goals

| Goal | How |
|------|-----|
| High-quality Japanese sentence audio | Local [VOICEVOX](https://voicevox.hiroshiba.jp/) engine (`http://127.0.0.1:50021`) |
| Cards ready before tooling exists | **VoicevoxAudio** + **VoicevoxSpeakerId** fields; template prefers VOICEVOX over mined/TTS |
| Optional Kanjium pitch alignment | **Word-level done**; **sentence-level done** when `Reading` aligns to a VOICEVOX phrase (see Phase 3) |
| No breakage today | Empty **VoicevoxAudio** → existing **Audio** (Yomitan) → Anki `{{tts}}` fallback |

## Sentence accents (done 2026-08-01)

Sentence / Easy TTS passes `PitchPositions` plus the note `Reading`. The synthesizer finds the accent phrase whose morae match that reading (noun+particle prefixes like トモダチガ count; ぎんこう≈ギンコオ long-vowel folding). Limits:

1. **Conjugated surfaces:** dictionary `くる` will not match キマシタ — keep VOICEVOX default for that phrase.
2. **Heiban mid-phrase:** if the word is not phrase-initial, heiban (0) cannot be encoded; leave default.
3. **No match:** leave the whole query unchanged.
4. Regenerate Satori sentence audio with `python3 scripts/synthesize_immersion_sentence_audio.py --note-type "WK Satori Immersion" --force` (not `--surface-only`). Shadowing keeps native clips for `SentenceAudio`.

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
- [x] Handle multi-word **Sentence** audio (align word reading inside multi-phrase queries)
- [x] Fallback to VOICEVOX default accent when Kanjium / PitchPositions missing or unaligned  

**Exit (word-level):** ReadingAudio (and lemma Target) follow Kanjium; conjugated surface Target keeps VOICEVOX default.

**Exit (sentence-level):** SentenceAudio / Easy override the phrase matching `Reading` when possible; otherwise VOICEVOX default. Card backs show **SentencePitchGraphs** (mora charts from the same post-override `accent_phrases`) under the word pitch chart.
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
