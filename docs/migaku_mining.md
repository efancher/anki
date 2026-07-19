# Migaku immersion mining

> **Deprecated as primary path.** Prefer [yomitan_mining.md](yomitan_mining.md).
> Existing **WK Migaku Immersion** notes still enrich/unlock/synthesize via `wk_immersion`.
> For native YouTube clips without Migaku, use `scripts/extract_immersion_clip.py`.

Mine vocabulary from video and reading with **Migaku** into Anki: sentence cloze on the front, native **audio + screenshot** on the back when Migaku cooperates, progressive WK hints via **wk_unlock**.

**Mine on your laptop only** — other devices review via AnkiWeb sync.

## What you get

| Piece | Role |
|-------|------|
| **Immersion · Migaku Mining** deck | Home deck for mined cards |
| **WK Migaku Immersion** note type | Cloze + type-in; Migaku sends notes here |
| **wk_immersion** add-on | Cloze blank, WK links, hint flags; VOICEVOX fallback if no Migaku audio |
| **wk_unlock** add-on | **Tools → WK Run Unlock Pass** updates hint stages |
| **Immersion · Migaku Mining** | Home deck; study directly from this deck |

## One-time setup

### 1. Import the note type

```bash
python3 wk_decks.py --deck mining
```

Import `out/wk_migaku.apkg` (or `out/wk_all.apkg` from a full regen). Choose **Update** when re-importing after template changes, or **Add** if this is your first Migaku import (new note type — does not replace **WK Yomitan Immersion**).

If Anki reports **1 note could not be imported**, the old Yomitan setup card is conflicting — delete the suspended setup note in **Immersion · Yomitan Mining** (Browse → `tag:mining-setup`), then import again.

```bash
./scripts/sync_anki_addons.sh
```

Restart Anki. Delete the suspended setup card after your first real mine (or leave it suspended).

### 2. Migaku → Anki (not Migaku Memory)

In the Migaku browser extension **Card Creator**:

- Destination: **Anki** (not Migaku Memory)
- Card type: **Sentence** (recommended for cloze in context)

Keep **Anki open** on this laptop while mining.

Install the [Migaku Anki add-on](https://github.com/migaku-official/Migaku-Anki-Addon) if you have not already.

### 3. Map Fields (automatic)

**Recommended:** sync add-ons, restart Anki, then:

**Tools → WK Configure Migaku Field Map**

That writes Migaku’s internal `migakuFields` config (AnkiConnect cannot do this). It maps:

| Anki field | Migaku type (dropdown label) |
|------------|------------------------------|
| **Expression** | Target Word (no syntax) |
| **Reading** | Reading |
| **Sentence** | Sentence (no syntax) |
| **Translation** | Sentence Translation |
| **Glossary** | Definitions |
| **Image** | First Image |
| **SentenceAudio** | Sentence Audio |
| **Audio** | Word Audio |

Also sets default deck **Immersion · Migaku Mining** and note type **WK Migaku Immersion**. If you have **WK Migaku Immersion+**, it maps that too.

**Manual alternative:** Migaku → Map Fields opens Add Cards → click **Field Maps** → set each **Anki field name** (e.g. Expression) from the dropdown — you will not see a row labeled “Target Word”; pick **Target Word** on the **Expression** row.

**CLI (Anki must be quit):** `python3 scripts/configure_migaku_field_map.py --offline`

### 4. VOICEVOX fallback (optional)

Migaku normally fills **SentenceAudio** with the clip from the show. If a note has no sentence audio, **wk_immersion** can synthesize via VOICEVOX or edge-tts — see [voicevox_setup.md](voicevox_setup.md).

## Card layout (template v12)

- **Front:** sentence cloze + progressive hints + `{{type:Reading}}` (kana type-in; kanji still shown in cloze/expression)
- **Hints:** stage 0 = kana + English (WK or Migaku Translation) + short J–J if no English; stage 1 = kana only; stage 2 = no hints
- **Back (always):** typed answer, **screenshot**, **native sentence audio**, full sentence
- **Back (stage 2):** kana line, pitch, full glossary, JP dict links

Hint stages: **Tools → WK Run Unlock Pass** (no card locking).

> Design: [migaku_mining_design.md](migaku_mining_design.md)

## Review on other devices

Use **AnkiMobile / AnkiDroid** with the same AnkiWeb account. New mined cards and media sync automatically. Do not mine into Migaku Memory on other devices expecting a later export — Migaku only sends to Anki at creation time.

## Tools menu

- **WK Enrich Mining Notes (cloze + WK links)** — backfill cloze/WK fields
- **WK Synthesize Immersion Sentence Audio** — notes missing **SentenceAudio**

## Troubleshooting

### Card has no screenshot or audio

Mine from YouTube/Netflix with Migaku’s video mining enabled. Text-only mines may omit **Image** / **SentenceAudio**. Update the Migaku Anki add-on if YouTube cards fail silently (known issue with older add-on versions).

### Deck not found

Deck name must match exactly: `Immersion · Migaku Mining` (middle dot `·`).

Re-import `out/wk_migaku.apkg` if the deck is missing.

### Sentence shows Migaku syntax (`皆[みな;n2]`, `{、}`)

Re-run **Tools → WK Configure Migaku Field Map** so **Expression** and **Sentence** map to **Target Word (no syntax)** and **Sentence (no syntax)**. Then **Tools → WK Enrich Mining Notes** to clean existing cards. New mines are cleaned automatically on enrich.

### Old Yomitan mining cards

Existing **WK Yomitan Immersion** notes stay in your collection until you delete or migrate them. New mines use **WK Migaku Immersion** only.
