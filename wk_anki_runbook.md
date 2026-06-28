# WaniKani + Grammar → Anki Runbook

Generator: `wk_decks.py` (WaniKani decks) + `grammar_decks.py` (JLPT grammar from [Hanabira](https://hanabira.org/) open data).

**Recommended import:** `out/wk_all.apkg` — one file updates every active deck.

**Planned (not yet implemented):** Full WK review replacement with Anki + FSRS — see [docs/wk_core_srs_design.md](docs/wk_core_srs_design.md) for architecture, implementation tracker, and agent resume checklist.

**Core SRS migration (Phase 2):** See [Core SRS migration](#core-srs-migration-wk--anki) below — one-time import with `--bootstrap-wk-scheduling`, `wk_unlock` addon, and `--no-wk-progress-filter` for supplementary decks.

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
- **wk_unlock** — unsuspend core + supplementary cards when prerequisites / linked vocab mature

---

## Core SRS migration (WK → Anki)

One-time workflow to move WaniKani reviews into Anki + FSRS. After this, stop doing WK reviews; use Anki daily queues only.

### Before you start

1. **Export a full Anki collection backup** (File → Export → include scheduling information).
2. Install add-ons: `wk_deck_options`, `wk_filtered_decks`, `wk_unlock` (copy folders from `anki_addon/`).
3. Confirm `WANIKANI_API_TOKEN` is set and `.wk_cache/` can sync (or refresh once on a working network).

### Migration steps

1. **Export Anki collection backup** (again immediately before import if you changed anything).
2. **Generate decks** with core + bootstrap scheduling and import-all supplementary gating:

   ```bash
   python wk_decks.py --from-config
   # equivalent to:
   # python wk_decks.py --deck all --no-wk-progress-filter --bootstrap-wk-scheduling
   ```

   Config defaults live in `wk_deck_config.json` (`core`, `no_wk_progress_filter`, `generate_decks` includes `core`).

3. **Import** `out/wk_all.apkg` into Anki → choose **Update note types** (Always update for `WK Core *`, vocab cloze v7+, conjugation v4+, dictation v3+).
4. **Tools → WK Apply Deck Options** — assign WK FSRS preset; enable FSRS globally if prompted.
5. **Install / enable wk_unlock** → **Tools → WK Run Unlock Pass** once (also runs automatically after reviews).
6. **Tools → WK Setup Filtered Decks** — rebuild daily queues (searches include `-is:suspended`).
7. **Verify in Browse:** `tag:wk-core` — spot-check due dates vs WaniKani; supplementary cards with `tag:wk-locked` should be suspended until linked vocab is Master+ in core.
8. **Stop WK reviews.** Optional: continue WK lessons only for new unlocks until fully Anki-gated.

### After migration

- Re-run the generator only for **new WK catalog content** (new subjects), not to refresh unlock state — that is handled by `wk_unlock` inside Anki.
- Weekly content sync: `python wk_decks.py --from-config` (without re-bootstrap if notes already have `wk-schedule-bootstrapped`).

Design details: [docs/wk_core_srs_design.md](docs/wk_core_srs_design.md)

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
  pronunciation_audio/        ← WK vocab reading clips
```

---

## Backup (Google Drive + launchd)

Back up **two things**: your **Anki profile** (SRS progress — irreplaceable) and the **generator repo** (config, `out/`, `.wk_cache/` — saves hours of re-download and reading-audio generation).

Google Drive for Desktop mounts under **Finder → Locations → Google Drive**. On disk that is usually:

```text
~/Google Drive/My Drive/
```

Backups land in:

```text
Google Drive/My Drive/anki/
  backup.log
  backups/
    YYYY-MM-DD/
      anki-repo/      ← ~/anki (includes .wk_cache, out/; excludes venv, gen_all.sh)
      anki-profile/   ← ~/Library/Application Support/Anki2/User 1
    latest/           ← symlink to most recent dated backup
```

Dated backups older than **14 days** are pruned automatically (`BACKUP_RETENTION_DAYS=0` keeps all).

### Manual backup

**Quit Anki first** (open collection = inconsistent backup).

```bash
~/anki/scripts/backup_to_google_drive.sh --dry-run   # preview
~/anki/scripts/backup_to_google_drive.sh             # run
```

Options: `--repo-only`, `--anki-only`, `--force` (continue if Anki appears running — not recommended).

### Scheduled backup (launchd, recommended on macOS)

Install a **LaunchAgent** that runs every **Sunday at 2:15 AM** (local time; Mac must be awake):

```bash
~/anki/scripts/install_backup_launchagent.sh install
~/anki/scripts/install_backup_launchagent.sh status
~/anki/scripts/install_backup_launchagent.sh uninstall   # remove
```

**Logs:**

| Location | Contents |
|----------|----------|
| `Google Drive/My Drive/anki/backup.log` | Backup script log (also synced to Drive) |
| `~/Library/Logs/anki-backup/backup.stdout.log` | launchd stdout |
| `~/Library/Logs/anki-backup/backup.stderr.log` | launchd stderr |

If the scheduled run finds Anki still open, it **skips the entire backup** (repo and profile). Close Anki before Sunday 2:15, or run a manual backup when Anki is quit.

**Change the schedule:** edit `START_WEEKDAY`, `START_HOUR`, and `START_MINUTE` at the top of `scripts/install_backup_launchagent.sh`, then run `install` again.

**Override Drive path:** set `GOOGLE_DRIVE_ROOT` before running the backup script (auto-detected if unset).

**First-time tip:** after a long `wk_decks.py` run finishes reading audio, run one manual backup so `.wk_cache/` is on Drive before you rely on the weekly job.

---

## Troubleshooting

**403 / Cloudflare on WK API:** Generator falls back to `.wk_cache/` if present. Run once on a network that can reach the API, or use existing cache.

**246 notes could not be imported:** This is exactly the conjugation deck count (168 verb/adj + 78 reverse). Anki kept an old note type without the type-in fields. Re-import `wk_all.apkg` and choose **Always update** for:

- `WK Update-Safe Conjugation` (template v3)
- `WK Update-Safe Conjugation Reverse` (template v3)

Also update if prompted: `WK Update-Safe Vocab Cloze`, `WK Update-Safe Grammar Cloze`.

Do **not** choose “Keep old note type” or “Create new note type”.

**40 notes could not be imported:** This matches **Japanese Grammar Exercises** (Tae Kim practice) at your current grammar lesson cap. Those 40 cards use the same note type as **Japanese Grammar Context** (`WK Update-Safe Grammar Cloze`). Fix:

1. Re-import `wk_all.apkg`.
2. When prompted about note types, choose **Always update** for `WK Update-Safe Grammar Cloze` (needs FormHint field — template v4+).
3. When prompted about **existing notes**, choose update/merge as well (Anki asks separately).
4. In Browse, check deck **Japanese Grammar Exercises** — if it has 0 cards, delete that deck (notes only) and re-import once more.

If Manage Note Types shows two grammar cloze types (e.g. from an old “Create new note type”), remove the stray one after moving any cards out of it.

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
