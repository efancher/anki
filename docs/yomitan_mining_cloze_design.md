# Yomitan mining — sentence cloze redesign

**Status:** Implemented (template v10)  
**Last updated:** 2026-07-08  
**Replaces:** “Word → sentence” template in `mining_decks.py` (template v9+)

**Related:** [yomitan_mining.md](yomitan_mining.md) · [wk_unlock](../anki_addon/wk_unlock/) · Kanji Meaning Anchor · `wk_immersion`

---

## Goals

| Goal | How |
|------|-----|
| **Production in context** | Front = sentence with blank + type the target word in **kanji** |
| **Progressive hints** | Scaffolding fades as kanji meanings and WK vocab mature — **no card locking** |
| **WK-aware** | Link mined word to WK catalog when possible; kanji prereqs from target word |
| **Back = immersion** | Full sentence + VOICEVOX sentence audio always on back |
| **Late reveal of J–J** | Yomitan **Glossary / Synonyms / Antonyms** only after WK vocab is Guru+ in core |

---

## Card layout (single template)

### Front (all stages)

1. **Cloze sentence** — full line from reading, target replaced by `＿＿＿` (styled blank).
2. **Hint block** inside/near the blank — content depends on **HintStage** (see below).
3. **Type answer:** `{{type:Expression}}` — expected answer is WK surface form (kanji + okurigana).

Optional later: sentence audio on front (currently **back only** per below).

### Back (all stages)

1. Type comparison (Anki default for `{{type:…}}`).
2. **Full sentence** (kanji + furigana when **SentenceFurigana** exists).
3. **Sentence audio** — **SentenceAudio** (VOICEVOX via `wk_immersion`); fallbacks unchanged.

### Back (stage 2 only — vocab mastered)

4. **SentenceKana** — kana-only line for speaking practice (derived from **SentenceFurigana** or TTS-friendly reading).
5. **Pitch** — **PitchAccents** / **PitchPositions** / **PitchGraphs** when present.
6. **J–J definitions** — **Glossary**, **Synonyms**, **Antonyms** (mined at add time, hidden until stage 2).
7. **Dictionary links** — labeled JP / EN / thesaurus (see [Dictionary links](#dictionary-links)).
8. **UserNotes**, source metadata — unchanged.

Word-level **Audio** (Yomitan clip) remains optional on back when stage ≥ 1; not required for v1.

---

## Hint stages (no locking)

Cards are **always reviewable**. An add-on updates **HintStage** (`0` | `1` | `2`) on each **WK Run Unlock Pass** (same cadence as supplementary unlocks).

| Stage | Name | Enter when | Front blank shows | Front also shows | Back extras |
|-------|------|------------|-------------------|------------------|-------------|
| **0** | Scaffold | Default at mine | *(blank for typing)* | **Kana** (**Reading**) · **English** (**WkMeaning** or fallback) · **pitch** · **J–E link** · **J–J** (Glossary snippet if mined) | Sentence + sentence audio only |
| **1** | Kanji anchored | All kanji in **PrerequisiteIds** are Guru+ (≥7d) in **Kanji Meaning Anchor** | *(blank)* | **Kana** only | Sentence + sentence audio only |
| **2** | Vocab mastered | **WkSubjectId** is Guru+ (≥7d) in **WaniKani Core · Vocabulary** | *(blank)* — no hints | Sentence + sentence audio + **SentenceKana** + pitch + full J–J blocks + dict links |

**English removal (0 → 1):** Once you know kanji meanings from the anchor deck, English gloss in the blank is redundant — drop **WkMeaning** and **J–E** links; keep kana until the word itself is mature in core.

**Kana removal (1 → 2):** Once the vocabulary item is Guru+ in core, drop kana from the blank; reveal J–J and reference material on the back.

**No WK match:** Use Yomitan-mined **Glossary** (J–J) for stage-0 J–J snippet if present; no **WkMeaning**. Stage transitions still apply if **PrerequisiteIds** / manual **WkSubjectId** are set; otherwise card can stay at stage 0 until user links WK id in Browse (optional v2).

---

## Maturity sources

Same intervals as `wk_unlock` today (`mature_min_interval_days` = 7):

| Check | Collection query |
|-------|------------------|
| Kanji anchored | Each id in **PrerequisiteIds** → mature in notes `tag:kanji-meaning` |
| Vocab mastered | **WkSubjectId** → mature in notes `tag:wk-core` on **WaniKani Core · Vocabulary** |

No `wk-locked` tag on mining notes.

---

## Fields (note type `WK Yomitan Immersion`)

### Existing (keep)

| Field | Source |
|-------|--------|
| DuplicateKey | Yomitan / first field |
| Expression, Reading, Furigana | Yomitan |
| Sentence, SentenceFurigana | Yomitan `{cloze-prefix}…` |
| Glossary, Synonyms, Antonyms | Yomitan dictionaries |
| PitchAccents, PitchPositions, PitchGraphs | Yomitan + pitch dict |
| Audio | Yomitan `{audio}` (optional) |
| SentenceAudio, VoicevoxSpeakerId | `wk_immersion` |
| UserNotes, SourceUrl, SourceTitle, Meta | User / Yomitan |

### New

| Field | Set by | Purpose |
|-------|--------|---------|
| **ClozeSentence** | Post-mine add-on | Sentence HTML with target → `＿＿＿` |
| **WkSubjectId** | Post-mine add-on | WK vocabulary id when matched |
| **PrerequisiteIds** | Post-mine add-on | Comma-separated kanji component ids for target word |
| **WkMeaning** | Post-mine add-on | WK primary meaning(s) for stage-0 English |
| **HintStage** | Post-mine (`0`); unlock pass (`1`, `2`) | Drives template conditionals |
| **SentenceKana** | Post-mine add-on | Plain kana sentence for speaking (stage 2 back) |
| **DictLinksJa** | Post-mine add-on | HTML links — JP dictionaries + thesaurus |
| **DictLinksEn** | Post-mine add-on | HTML links — EN dictionaries (stage 0 only) |

Template uses `{{#HintStage0}}` … or numeric compare via three wrapper fields updated by add-on:

- **ShowEnglish**, **ShowKana**, **ShowJjBack** (boolean-ish empty/non-empty) — easier than parsing numbers in Anki conditionals.

Recommended: add-on sets **ShowEnglish** / **ShowKana** / **ShowJjBack** when it updates **HintStage** so templates stay simple.

---

## Post-mine pipeline (`wk_immersion` extension or `wk_mining` add-on)

On **AnkiConnect addNote** (after Yomitan creates the note):

1. **Match WK vocab** — normalize **Expression** + **Reading** against `.wk_cache` subjects; set **WkSubjectId**, **WkMeaning**, **PrerequisiteIds** (`vocab_kanji_prerequisite_ids`).
2. **Build ClozeSentence** — locate target token in **Sentence** (reuse `highlight_target_in_sentence` / vocab-cloze logic); replace with blank markup.
3. **Build SentenceKana** — strip ruby to reading line from **SentenceFurigana**, or reading-only fallback.
4. **Dictionary links** — generate static URLs from **Expression** / **Reading** (no network at review time).
5. **HintStage** — `0`; set **ShowEnglish=1**, **ShowKana=1**, **ShowJjBack=0**.
6. **Sentence TTS** — existing `wk_immersion` VOICEVOX path (unchanged).

Yomitan mapping changes: **minimal** — still send sentence, expression, reading, glossary fields. Do **not** map cloze or WK fields from Yomitan.

---

## Dictionary links

Generated once at mine time; shown in front hint area (stage 0) or back (stage 2).

| Label | Example target | When visible |
|-------|----------------|--------------|
| **和** (JP) | Weblio / Goo辞書 search URL | Stage 0 (with English); stage 2 back |
| **英** (EN) | Jisho / Weblio EN | Stage 0 only |
| **類** (thesaurus) | Goo 類語 / Synonyms field link | Stage 2 back (plus mined **Synonyms**) |

Exact URL templates TBD in implementation; keep labels visible so user knows dictionary language.

---

## Template conditionals (sketch)

```html
<!-- Front -->
<div class="cloze-sentence">{{ClozeSentence}}</div>
<div class="hint-block">
  {{#ShowKana}}<div class="hint-reading">{{Reading}}</div>{{/ShowKana}}
  {{#ShowEnglish}}{{#WkMeaning}}<div class="hint-meaning">{{WkMeaning}}</div>{{/WkMeaning}}{{/ShowEnglish}}
  {{#ShowEnglish}}{{DictLinksEn}}{{/ShowEnglish}}
  {{#HintStage0}}
    {{#PitchAccents}}<div class="pitch">…</div>{{/PitchAccents}}
    {{#Glossary}}<div class="hint-glossary">…</div>{{/Glossary}}
  {{/HintStage0}}
</div>
<div class="type-prompt">{{type:Expression}}</div>
```

```html
<!-- Back -->
{{FrontSide}}
<hr>
<div class="context">… Sentence … {{SentenceAudio}}</div>
{{#ShowJjBack}}
  {{#SentenceKana}}<div class="sentence-kana">…</div>{{/SentenceKana}}
  … pitch, Glossary, Synonyms, Antonyms, DictLinksJa …
{{/ShowJjBack}}
```

---

## Unlock pass extension

In `wk_unlock` (or sibling **wk_mining** module):

```text
for each note tag:yomitan-mining:
  stage = 0
  if kanji_prereqs_mature_in_kanji_meaning_anchor(note.prerequisite_ids):
    stage = max(stage, 1)
  if note.wk_subject_id mature in core_vocab:
    stage = max(stage, 2)
  update HintStage + ShowEnglish / ShowKana / ShowJjBack fields
```

No suspend/unsuspend for mining notes.

---

## Implementation phases

| Phase | Deliverable |
|-------|-------------|
| **A** | New fields + replaced template in `mining_decks.py`; import **Update** path; tests |
| **B** | Post-mine enricher: WK match, cloze, SentenceKana, dict links, HintStage init |
| **C** | Unlock pass: recompute HintStage from Kanji Meaning + core vocab maturity |
| **D** | Docs: update [yomitan_mining.md](yomitan_mining.md); runbook; Yomitan checklist |

---

## Decisions log

| # | Decision |
|---|----------|
| 1 | **Replace** existing “Word → sentence” template (no second card type) |
| 2 | Type target = **kanji** (**Expression**); hints gated by stage |
| 3 | No WK match: stage-0 J–J from Yomitan **Glossary**; no WK English |
| 4 | Hide full J–J blocks on back until **vocab mastered** (stage 2) |
| 5 | **No locking** — only hint depth changes |
| 6 | Stage 0: kana + English + J–E + J–J snippet + pitch; drop English + J–E at stage 1 |
| 7 | Stage 2 back: **SentenceKana** for speaking practice |
| 8 | Back always includes full sentence + VOICEVOX **SentenceAudio** |

---

## Open questions (minor)

- **Homographs:** WK match by reading + expression; manual override field in Browse if wrong.
- **Target not found in sentence:** Fall back to full sentence + bold prompt “type: {{Expression}}” without inline blank.
- **Stage-0 J–J on front:** Show truncated Glossary (first N chars) vs full — prefer **one line** on front, full on back at stage 2.
