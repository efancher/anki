# Migaku mining — sentence cloze design

**Status:** Implemented (template v12)  
**Related:** [migaku_mining.md](migaku_mining.md) · [wk_unlock](../anki_addon/wk_unlock/) · Kanji Meaning Anchor · `wk_immersion`

## Goals

| Goal | How |
|------|-----|
| **Production in context** | Front = sentence with blank + type target word in **kanji** |
| **Progressive hints** | Scaffolding fades as kanji/vocab mature — **no card locking** |
| **Native media** | Migaku **Image** (screenshot) + **SentenceAudio** (clip from source) on back |
| **WK-aware** | Link mined word to WK catalog when possible |
| **Late J–J reveal** | Full **Glossary** on back only after vocab is Guru+ in core |

## Hint stages

| Stage | Front | Back extras |
|-------|-------|-------------|
| **0** | Kana + English (WK or Migaku Translation) + short J–J if no English | Screenshot + native audio + sentence |
| **1** | Kana only | Same |
| **2** | No hints | + SentenceKana, pitch, full glossary, JP dict links |

Updated on **Tools → WK Run Unlock Pass**. Tag: `migaku-mining`.

## Note type: `WK Migaku Immersion`

Migaku maps: **Expression**, **Sentence**, **Translation**, **Glossary**, **Image**, **SentenceAudio**, **Audio**.

Add-on fills: **ClozeSentence**, WK fields, hint flags, **DuplicateKey**. VOICEVOX only when **SentenceAudio** is empty.

## Export

`python3 wk_decks.py --deck mining` → `out/wk_migaku.apkg`
