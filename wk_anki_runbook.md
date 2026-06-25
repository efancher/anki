# WaniKani + Grammar → Anki Runbook

Generator: `wk_decks.py` (WaniKani decks) + `grammar_decks.py` (JLPT grammar from [Hanabira](https://hanabira.org/) open data).

**Recommended import:** `out/wk_all.apkg` — one file updates every active deck.

---

## One-time setup

```bash
cd /path/to/anki
python3 -m venv env_anki
source env_anki/bin/activate
pip install -r requirements.txt

export WANIKANI_API_TOKEN="your_token_here"
python wk_decks.py --version
```

Optional Anki add-ons (in `anki_addon/`):

- **wk_filtered_decks** — Tools → WK Setup Filtered Decks (reads `out/anki_filtered_decks.json`)
- **wk_deck_options** — Tools → WK Apply Deck Options (assigns WK FSRS preset)

---

## Active decks (`--deck all`)

| Deck | File | Purpose |
|------|------|---------|
| **WaniKani Current and Next Radicals** | `wk_radicals_current_next.apkg` | Radicals at current, next, and locked-next WK level |
| **WaniKani Phonetic Families** | `wk_phonetic_families.apkg` | On'yomi drills via Keisei phonetic components |
| **WaniKani Verb Conjugation Practice** | `wk_conjugations_verbs.apkg` | Type-in verb forms (Master+ default) |
| **WaniKani Adjective Conjugation Practice** | `wk_conjugations_adjectives.apkg` | Type-in adjective forms |
| **WaniKani Verb Conjugation Reverse** | `wk_conjugations_reverse.apkg` | Conjugated → dictionary form |
| **WaniKani Verb Type Practice** | `wk_verb_types.apkg` | Godan / ichidan / irregular |
| **WaniKani Adjective Type Practice** | `wk_adjective_types.apkg` | い vs な adjective |
| **WaniKani Vocabulary Context** | `wk_vocab_cloze.apkg` | Production cloze in WK sentences + TTS |
| **Japanese Grammar Context** | `wk_grammar.apkg` | Grammar cloze from Hanabira (JLPT order) |

### Removed from default bundle (still available individually)

These are no longer in `--deck all`. Regenerate only if you still want them:

- `wk_leeches.apkg`, `wk_verb_pairs.apkg`, `wk_confusables.apkg`
- `wk_reading_keywords.apkg`, `wk_kanji_radicals.apkg`, `wk_pitch_leeches.apkg`

Example: `python wk_decks.py --deck leeches --only-started`

---

## Recommended weekly workflow

```bash
source env_anki/bin/activate
python wk_decks.py --deck all --only-started
```

Import `out/wk_all.apkg` → choose **Update note types**.

After import:

1. Tools → **WK Apply Deck Options** (FSRS preset on all WK decks)
2. Tools → **WK Setup Filtered Decks** (daily queues)
3. Enable **FSRS** globally in Anki if prompted

---

## Common commands

```bash
# Preview counts without writing files
python wk_decks.py --deck all --only-started --dry-run

# Single deck
python wk_decks.py --deck vocab-cloze --only-started
python wk_decks.py --deck grammar
python wk_decks.py --deck phonetic-families --only-started

# Conjugation only (Master+ default)
python wk_decks.py --deck conjugations-verbs --only-started

# Radicals only (override WK level detection)
python wk_decks.py --deck radicals --radical-current-level 12

# Skip bundle (individual .apkg files only)
python wk_decks.py --deck all --only-started --no-bundle

# Force re-download WK / Hanabira / Keisei caches
python wk_decks.py --deck all --only-started --refresh-cache
```

---

## Key filters and defaults

| Flag | Default | Affects |
|------|---------|---------|
| `--only-started` | off | WK vocab/kanji in most decks |
| `--min-srs` | 1 | WK progress filter (Guru+ ≈ 5, Master+ ≈ 7) |
| `--vocab-cloze-min-srs` | 7 (Master+) | Vocab context deck only |
| `--conjugation-min-srs` | 7 (Master+) | Conjugation decks only |
| `--grammar-max-jlpt` | N2 | Grammar through this JLPT level |
| `--grammar-max-tae-kim-section` | 6 | Grammar through this Tae Kim section (3=Basic, 4=Essential, 5=Special, 6=Advanced) |
| `--grammar-max-examples` | 2 | Example cards per grammar point |
| `--grammar-max-unknown-kanji` | 5 | Skip examples with too many unknown WK kanji |
| `--grammar-no-wk-filter` | off | Include all Hanabira examples regardless of WK |
| `--max-level` | 60 | Cap WK subject level |
| `--sentence-audio` | on | TTS on vocab-cloze (edge-tts) |
| `--no-sentence-audio` | | Skip TTS generation |

Phonetic families always seed from **Apprentice+** kanji (`--min-srs` does not apply).

Radicals include **three levels**: current, next, and locked-next.

---

## Grammar deck (Bunpro replacement path)

**Source:** Hanabira JLPT grammar JSON (cached in `.wk_cache/hanabira_grammar/`).  
**Study path:** Read [Tae Kim Grammar Guide](https://guidetojapanese.org/learn/grammar) for explanations; use Anki for **production** in example sentences.

**Card type:** English hint + cloze sentence → type the missing grammar chunk (e.g. `けれども`).

**Ordering:** Tae Kim subsection (reading order on [Basic Grammar](https://guidetojapanese.org/learn/grammar/basic)), then JLPT within each lesson.

**Subsections use the page titles, not numbers.** After reading *Introduction to Particles*, review cards tagged:

`tag:tk-lesson-basic-introduction-to-particles`

| Subsection (Basic Grammar) | Anki tag |
|----------------------------|----------|
| Expressing state-of-being | `tag:tk-lesson-basic-expressing-state-of-being` |
| Introduction to Particles | `tag:tk-lesson-basic-introduction-to-particles` |
| Adjectives | `tag:tk-lesson-basic-adjectives` |
| Verb Basics | `tag:tk-lesson-basic-verb-basics` |
| … | (see `tae_kim_lessons.json`) |

Practice-exercise pages (*State-of-being Practice Exercises*, etc.) have no Hanabira cards — do those on the site.

**Read-then-review workflow:**

```bash
# After "Introduction to Particles" (includes that lesson and earlier ones)
python wk_decks.py --deck grammar --grammar-max-tae-kim-lesson introduction-to-particles

# Same thing, explicit chapter prefix
python wk_decks.py --deck grammar --grammar-max-tae-kim-lesson basic:introduction-to-particles
```

In Anki: **Browse → `tag:tk-lesson-basic-introduction-to-particles`**, or edit filtered deck **WK::Grammar · Current Tae Kim lesson** to match whatever subsection you just read.

Chapter-level caps (coarser, whole Basic Grammar at once) still work via `--grammar-max-tae-kim-section 3`.

```bash
# Grammar-only (no WK token required)
python wk_decks.py --deck grammar --dry-run

# N5–N4 grammar only, more examples
python wk_decks.py --deck grammar --grammar-max-jlpt N4 --grammar-max-examples 3

# Full N5–N2 with WK kanji filter (needs --only-started for vocab list)
python wk_decks.py --deck grammar --only-started
```

**Attribution:** Hanabira grammar content is CC-licensed. Read Tae Kim for pedagogy; Hanabira supplies structured examples for SRS.

---

## Vocab context cloze

Production practice in WK context sentences. Type **`TypeExpression`** (full kanji when WK uses early spellings like `ふじ山` → type `富士山`).

```bash
python wk_decks.py --deck vocab-cloze --only-started
python wk_decks.py --deck vocab-cloze --only-started --no-sentence-audio
```

---

## Conjugation decks

```bash
python wk_decks.py --deck conjugations-verbs --only-started
python wk_decks.py --deck conjugations-adjectives --only-started
python wk_decks.py --deck conjugations-reverse --only-started

# Verify conjugation rules against fixtures
python wk_decks.py --verify-conjugations-only --only-started
python -m unittest tests.test_conjugations
```

---

## Phonetic families

Requires Keisei DB (auto-downloaded to `.wk_cache/keisei/`). Skipped when no family has enough started kanji.

```bash
python wk_decks.py --deck phonetic-families --only-started
```

---

## Filtered decks (Anki)

Written to `out/anki_filtered_decks.json`:

| Name | Purpose |
|------|---------|
| **WK::Radicals Preview** | Current/next radicals |
| **WK::Vocab Context** | Daily vocab production |
| **WK::Grammar** | Early Basic subsections (state-of-being, particles, adjectives) |
| **WK::Grammar · Current Tae Kim lesson** | Edit search to match the subsection you just read |
| **WK::Phonetic Families** | Low-priority phonetic drill |

Rebuild filtered decks after each import.

---

## Output files

```text
out/
  wk_all.apkg                 ← import this
  wk_run_history.csv          ← per-run counts
  anki_import_instructions.txt
  anki_filtered_decks.json
  anki_deck_options.json
  wk_grammar.apkg             ← also in bundle
  …individual deck files…
.wk_cache/
  hanabira_grammar/           ← grammar JSON cache
  keisei/                     ← phonetic DB
  sentence_audio/             ← TTS cache
```

---

## Troubleshooting

**403 / Cloudflare on WK API:** Generator falls back to `.wk_cache/` if present. Run once on a network that can reach the API, or use existing cache.

**246 notes could not be imported:** This is exactly the conjugation deck count (168 verb/adj + 78 reverse). Anki kept an old note type without the type-in fields. Re-import `wk_all.apkg` and choose **Always update** for:

- `WK Update-Safe Conjugation` (template v3)
- `WK Update-Safe Conjugation Reverse` (template v3)

Also update if prompted: `WK Update-Safe Vocab Cloze` (v4), `WK Update-Safe Grammar Cloze` (v1).

Do **not** choose “Keep old note type” or “Create new note type”.

**Templates not updating:** Re-import with “Always update note type”. Check card Meta for template version (e.g. `v4` vocab-cloze).

**Grammar deck empty:** Run with network once to populate Hanabira cache, or `--grammar-no-wk-filter`.

**No phonetic families deck:** Normal if too few started kanji share a Keisei family.

**FSRS:** Apply via add-on after import; preset name is **WK FSRS**.

---

## Tests

```bash
python -m unittest discover -s tests -v
```

---

## Version

Check: `python wk_decks.py --version`

After template changes, re-import `wk_all.apkg` and update note types.
