# Yomitan mining — sentence cloze + shadow

**Status:** Implemented (template v14)  
**Last updated:** 2026-07-12  

**Related:** [yomitan_mining.md](yomitan_mining.md) · [wk_unlock](../anki_addon/wk_unlock/) · Kanji Meaning Anchor · `wk_immersion` · [extract_immersion_clip.py](../scripts/extract_immersion_clip.py)

---

## Goals

| Goal | How |
|------|-----|
| **Production in context** | Front = sentence with blank + type the **reading** in kana |
| **Progressive hints** | Scaffolding fades as kanji meanings and WK vocab mature — **no card locking** |
| **WK-aware** | Link mined word to WK catalog when possible; kanji prereqs from target word |
| **Back = immersion** | Full sentence + sentence audio (clip or VOICEVOX) |
| **Shadowing + pitch** | Second card: listen → speak; back shows kana + pitch graphs |
| **Late reveal of J–J** | Yomitan **Glossary / Synonyms / Antonyms** only after WK vocab is Guru+ in core |

---

## Card templates

### 1. Sentence cloze → word

| Side | Content |
|------|---------|
| **Front** | Cloze sentence + hint block (stage-dependent) + `{{type:Reading}}` |
| **Back (always)** | Typed answer, full sentence, **SentenceAudio** |
| **Back (stage 2)** | **SentenceKana**, pitch, full J–J, dict links, word **Audio** |

### 2. Shadow → pitch

| Side | Content |
|------|---------|
| **Front** | **SentenceAudio** (listen) + target word — speak along |
| **Back** | **SentenceKana**, sentence (furigana), **PitchAccents** / **PitchGraphs**, word **Audio** |

Available as soon as the note has audio + pitch from Yomitan (does not wait for stage 2).

---

## Hint stages (no locking)

Updated on **Tools → WK Run Unlock Pass**. Tag: `yomitan-mining`.

| Stage | Enter when | Front hints | Back extras |
|-------|------------|-------------|-------------|
| **0** | Default at mine | Kana + English + pitch + links | Sentence + audio |
| **1** | Kanji prereqs Guru+ in Meaning Anchor | Kana only | Sentence + audio |
| **2** | WK vocab Guru+ in core | None | + SentenceKana + pitch + full J–J |

**No WK match:** stage-0 English may come from Yomitan glossary snippet; card can stay at stage 0 until linked.

---

## Maturity sources

Same intervals as `wk_unlock` (`mature_min_interval_days` = 7):

| Check | Collection query |
|-------|------------------|
| Kanji anchored | Each id in **PrerequisiteIds** → mature in `tag:kanji-meaning` |
| Vocab mastered | **WkSubjectId** → mature in core vocabulary |

No `wk-locked` tag on mining notes.

---

## Fields (`WK Yomitan Immersion`)

| Field | Source |
|-------|--------|
| Expression, Reading, Furigana, Sentence*, Glossary, Synonyms, Antonyms | Yomitan |
| PitchAccents, PitchPositions, PitchGraphs | Yomitan + Kanjium |
| Audio | Yomitan `{audio}` (word clip) |
| SentenceAudio | ASB Player clip, `extract_immersion_clip.py`, or VOICEVOX |
| ClozeSentence, Wk*, Hint*, SentenceKana, DictLinks* | `wk_immersion` at mine time |
| Image, Translation | Optional (empty for text mines) |

---

## Native audio

1. **Word Audio** — Yomitan `{audio}` when a dictionary provides a clip.
2. **ASB Player** — Yomitan **+** then **Ctrl+Shift+U** (video; see [yomitan_mining.md](yomitan_mining.md)).
3. **SentenceAudio TTS** — `wk_immersion` when the field is empty (text mines).
4. **Manual clip** — `scripts/extract_immersion_clip.py` (yt-dlp + ffmpeg → AnkiConnect).

---

## Decisions (v14)

| # | Decision |
|---|----------|
| 1 | Primary mining path is **Yomitan** (Migaku legacy still unlocks) |
| 2 | Type-in = **Reading** (kana) |
| 3 | Second card template for **shadowing + pitch** |
| 4 | No locking — only hint depth changes |
| 5 | Native video audio via **ASB Player** (or manual clip script), not Migaku |
