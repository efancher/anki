# WaniKani + Grammar → Anki Runbook

Generator: `wk_decks.py` (WaniKani decks) + `grammar_decks.py` (JLPT grammar from [Hanabira](https://hanabira.org/) open data).

**Recommended import:** `out/wk_all.apkg` — one file updates every active deck.

### Implementation status

**Done — migration-ready.** WK reviews live in Anki + FSRS via:

- **Core SRS decks** — WaniKani Core · Radicals / Kanji / Vocabulary
- **One-time WK schedule bootstrap** — `core.bootstrap_scheduling` in `wk_deck_config.json`
- **`wk_unlock` add-on** — radical → kanji → vocab unlock + supplementary unsuspend
- **`no_wk_progress_filter`** — import full supplementary catalog; gate with `wk-locked` in Anki
- **Filtered core decks** — `WK::Core Radicals/Kanji/Vocabulary`

Follow [§2 First import](#2-first-import-migration) below. Architecture and tracker: [docs/wk_core_srs_design.md](docs/wk_core_srs_design.md).

**Not done yet:** grammar gated by core kanji maturity; YouTube immersion ([planned doc](docs/wk_immersion_youtube_design.md)).

---

## How to use this doc

| If you are… | Start here |
|-------------|------------|
| Setting up for the first time | [§1 One-time setup](#1-one-time-setup) → [§2 First import](#2-first-import-migration) |
| Studying day to day | [§3 Daily study](#3-daily-study) |
| Regenerating after config or code changes | [§4 Regenerate & re-import](#4-regenerate--re-import) |
| Tuning FSRS, unlocks, and study habits | [§12 Tips & tuning](#12-tips--tuning) |
| Changing Tae Kim / grammar scope | [§5 Configuration](#5-configuration) |
| Looking up a specific deck | [§6 Deck catalog](#6-deck-catalog) |
| Something broke on import | [§10 Troubleshooting](#10-troubleshooting) |

---

## 1. One-time setup

### Generator (Python)

```bash
cd /path/to/anki    # e.g. ~/anki
python3 -m venv env_anki
source env_anki/bin/activate
pip install -r requirements.txt

export WANIKANI_API_TOKEN="your_token_here"
python wk_decks.py --version
```

Also need **ffmpeg** on `PATH` for reading audio and dictation (macOS: `brew install ffmpeg`).

### Anki add-ons (desktop, required)

Six add-ons in `anki_addon/` are **not** in the `.apkg` and **not** on AnkiWeb. On macOS, **`python wk_decks.py --from-config` syncs them automatically** after each generate (`sync_anki_addons: true` in `wk_deck_config.json`). **Restart Anki** after sync so code changes load.

**Manual install or one-time setup** (any platform):

```bash
~/anki/scripts/sync_anki_addons.sh
# Quit Anki, then restart.
```

Disable auto-sync: `"sync_anki_addons": false` in config, or pass `--no-sync-addons`.

**Other platforms:** `%APPDATA%\Anki2\addons21\` (Windows) or `~/.local/share/Anki2/addons21/` (Linux).

**Verify** after restart — **Tools** menu should show:

| Folder | Menu item |
|--------|-----------|
| `wk_filtered_decks` | **WK Setup Filtered Decks** |
| `wk_deck_options` | **WK Apply Deck Options** |
| `wk_unlock` | **WK Run Unlock Pass** |
| `wk_adaptive_new` | **WK Adjust New Limits** |
| `wk_health_check` | **WK Health Check** |
| `wk_tae_kim_track` | **WK Sync Tae Kim Track**, **WK Bump Tae Kim Lesson** |

**Optional (dev):** symlink the six folders instead of `cp -R` so repo updates apply after restart. Details: [anki_addon/README.md](anki_addon/README.md).

### Second machine (work desktop, etc.)

AnkiWeb syncs your **collection** (cards, scheduling, deck options, filtered decks, tags) but **not** add-on code. Each desktop needs a **one-time** install of all six add-ons.

| Syncs via AnkiWeb | Local install required |
|-------------------|------------------------|
| Cards, due dates, `wk-locked` / unlock results | Add-on folders in `addons21/` |
| Deck option presets (`WK FSRS · New · …`) | **Tools → WK …** menu items |
| Filtered decks you already built | Auto unlock / adaptive new on that machine |

**On each additional desktop:**

1. Clone this repo (or copy `anki_addon/` and `scripts/sync_anki_addons.sh`).
2. Run the sync script (set `ANKI_ADDONS_DIR` on Windows/Linux):

   ```bash
   cd /path/to/anki
   ./scripts/sync_anki_addons.sh
   # Quit Anki on that machine, then restart.
   ```

   Windows (PowerShell):

   ```powershell
   $env:ANKI_ADDONS_DIR = "$env:APPDATA\Anki2\addons21"
   .\scripts\sync_anki_addons.sh
   ```

3. **Verify** the **Tools → WK …** menu items appear after restart (including **WK Sync Tae Kim Track**).

After that, use normal Anki sync. Unlock passes and adaptive new limits **run only on machines where the add-ons are installed** — run **WK Run Unlock Pass** / **WK Adjust New Limits** on any desktop before syncing if you want those effects everywhere without opening the other machine.

**Desktop Anki is required** for add-ons. AnkiMobile can review synced cards but cannot run unlock or build filtered decks.

---

## 2. First import (migration)

One-time path to move **WK reviews → Anki + FSRS**. After this, stop doing WK reviews; use Anki only.

This replaces the old “Phase 2 migration” — it **is implemented**; these are the steps to run it.

### Before you start

1. Export an Anki collection backup (File → Export, include scheduling).
2. Complete [§1 add-on install](#anki-add-ons-desktop-required).
3. Confirm `WANIKANI_API_TOKEN` is set (or `.wk_cache/` already populated from a prior run).

### Steps

1. **Backup again** immediately before import if anything changed.
2. **Generate** (defaults in `wk_deck_config.json`):

   ```bash
   source env_anki/bin/activate
   python wk_decks.py --from-config
   ```

   Equivalent flags: `--no-wk-progress-filter --bootstrap-wk-scheduling` with `core` in `generate_decks`.

   First run with `core.reading_audio: true` can take a long time (kanji TTS + WK vocab downloads). Progress bar on stderr; re-run fills failed clips.

3. **Import** `out/wk_all.apkg` → **Update note types** (Always update when prompted).
4. **Tools → WK Apply Deck Options** — assigns **WK FSRS** preset; enable FSRS globally if asked.
5. **Tools → WK Run Unlock Pass** — unsuspends level-1 radicals and eligible cards (also runs on later desktop opens).
6. **Tools → WK Setup Filtered Decks** — creates daily filtered decks from `out/anki_filtered_decks.json`.
7. **Tools → WK Health Check** — sanity stats (review history, filtered-deck reschedule, priority tags). Run again after import to compare against the saved snapshot.
8. **Verify** in Browse:
   - `tag:wk-core` — spot-check due dates vs WaniKani if you bootstrapped scheduling.
   - `tag:wk-locked` — supplementary suspended until linked subject is mature in core.
9. **Stop WK reviews.** Optional: keep WK **lessons** only until caught up in Anki.

### After migration

- Re-run the generator for **new WK catalog content** only — unlock state is handled by **wk_unlock** in Anki, not re-import.
- Set `"core.bootstrap_scheduling": false` in `wk_deck_config.json` after the one-time WK interval import (see [§12](#12-tips--tuning)).
- Routine sync: `python wk_decks.py --from-config`

---

## 3. Daily study

### Core SRS (main queue)

Use filtered decks:

| Filtered deck | Underlying deck |
|---------------|-----------------|
| **WK::Core Radicals** | WaniKani Core · Radicals |
| **WK::Core Kanji** | WaniKani Core · Kanji |
| **WK::Core Vocabulary** | WaniKani Core · Vocabulary |

Type **reading (kana)** on the front; meaning, reading audio, and mnemonics on the back. Kanji with multiple WK primary readings get multiple audio clips on the **back only**.

### Supplementary decks

Vocab cloze, dictation, conjugations, phonetic families, verb types, etc. Import with `tag:wk-locked`; **wk_unlock** unsuspends when linked **WkSubjectId** is mature in core (interval **≥ 7 days**, ≈ WK **Guru I**). **Grammar / Tae Kim exercises are not wk-locked** — see [Grammar gated by kanji](#grammar-gated-by-kanji-planned).

Open **desktop Anki periodically** if you study on mobile, so unlock passes sync.

### Grammar / Tae Kim

Read on guidetojapanese.org; review in grammar decks. Cap exercise deck scope in [§5 Configuration](#5-configuration). **Grammar role tags** (`tk-grammar-vocab`, `tk-grammar-prereq`) are applied at **runtime** by **wk_tae_kim_track** — not on each re-import. After your first regenerate with the track map, copy `out/wk_tae_kim_track_config.json` into your profile (the add-on does this on first sync), then use **Tools → WK Sync Tae Kim Track** or **WK Bump Tae Kim Lesson** when you finish a subsection (updates **WK::Grammar · Current Tae Kim lesson** and **WK::Grammar Exercises · Current Tae Kim lesson** automatically).

| Home deck | Filtered queue | Content |
|-----------|----------------|---------|
| **Japanese Grammar Context** | **WK::Grammar**, **WK::Grammar · Current Tae Kim lesson** | Hanabira / pattern clozes |
| **Japanese Grammar Exercises** | **WK::Grammar Exercises**, **WK::Grammar Exercises · Current Tae Kim lesson** | Tae Kim site practice (`copula_ex.html`, etc.) |
| **WaniKani Core *** | **WK::Tae Kim · Grammar Vocab / Prereq *** | WK kanji/vocab tagged for Tae Kim (not exercise cards) |

### Suggested daily order

1. **WK::Core** filtered decks until empty (Radicals → Kanji → Vocabulary).
2. **Tae Kim WK track:** **Grammar Prereq Radicals** → **Grammar Prereq Kanji** → **Grammar Vocab** (or **N5** equivalents) — these are **core** cards, not grammar exercises.
3. **WK::Grammar Exercises** (or **· Current Tae Kim lesson**) while doing Tae Kim practice pages.
4. **One** other supplementary filtered deck if you have energy (dictation → vocab context → conjugations).
5. **WK::Grammar** (Context deck) for Hanabira pattern review when useful.

Grammar is **not** gated by core kanji maturity today (see [§12](#12-tips--tuning)); use Tae Kim lesson caps and `max_unknown_kanji` instead.

## 4. Regenerate & re-import

```bash
source env_anki/bin/activate
python wk_decks.py --from-config
```

On macOS this also runs `scripts/sync_anki_addons.sh` (rsync + `__pycache__` cleanup). **Restart Anki** before using Tools menu add-ons if they changed.

Then in Anki:

1. Import `out/wk_all.apkg` → update note types / merge notes.
2. **Tools → WK Apply Deck Options** (if new decks appeared).
3. **Tools → WK Setup Filtered Decks**.
4. **Tools → WK Sync Tae Kim Track** (first time after track-map regenerate; also runs on collection load).
5. **Tools → WK Run Unlock Pass** (optional; also on collection load).

**Do not re-import to refresh unlock state** — that is **wk_unlock**’s job.

**Preview:** `python wk_decks.py --from-config --dry-run`

---

## 5. Configuration

Edit **`wk_deck_config.json`**, then `python wk_decks.py --from-config`.

| Key | Typical value | Effect |
|-----|---------------|--------|
| `generate_decks` | includes `core`, … | Decks in `wk_all.apkg` |
| `no_wk_progress_filter` | `true` | Full supplementary import + Anki gating |
| `core.bootstrap_scheduling` | `true` | One-time WK interval import |
| `core.reading_audio` | `true` | Vocab WK audio + kanji TTS |
| `grammar.max_tae_kim_section` | `3` | Tae Kim chapter cap |
| `grammar.max_tae_kim_lesson` | slug | Tae Kim subsection cap — see `tae_kim_lessons.json` |

Example lesson slugs: `expressing-state-of-being`, `introduction-to-particles`, `adjectives` → tags like `tag:tk-lesson-basic-introduction-to-particles`.

---

## 6. Deck catalog

### Core SRS

| Deck | Purpose |
|------|---------|
| **WaniKani Core · Radicals** | Meaning; root unlock via empty prereqs |
| **WaniKani Core · Kanji** | Type reading; multi-reading audio on back |
| **WaniKani Core · Vocabulary** | Type reading; WK native audio on back |

### Supplementary (default config)

| Deck | Gating |
|------|--------|
| Vocab Context, Dictation, Conjugations, Verb Types, Phonetic Families, … | `WkSubjectId` + `wk-locked` |
| Grammar / Tae Kim exercises | JLPT + Tae Kim caps only |
| Current and Next Radicals | *(removed from default — use core radicals; `--deck radicals` still builds)* |

Optional individual decks: leeches, verb pairs, confusables, etc. — `python wk_decks.py --deck leeches`

---

## 7. Filtered decks

From `out/anki_filtered_decks.json`. Rebuild via **Tools → WK Setup Filtered Decks** after import.

| Name | Purpose |
|------|---------|
| **WK::Core Radicals / Kanji / Vocabulary** | Daily core review |
| **WK::Tae Kim · Grammar Vocab** | Kanji/vocab in Tae Kim lesson text (`tag:tk-grammar-vocab`) |
| **WK::Tae Kim · Grammar Prereq Kanji** | Kanji still needed for grammar vocab (`tk-grammar-prereq`, not yet `wk-mature`) |
| **WK::Tae Kim · Grammar Prereq Radicals** | Radicals still needed for grammar chain (`tk-grammar-prereq`, not yet `wk-mature`) |
| **WK::N5 · Kanji & Vocab** | WK levels 1–10 band (`tag:jlpt-n5-vocab`) |
| **WK::N5 · Prereq Kanji** | Kanji still needed for N5 items (`jlpt-n5-prereq`, not yet `wk-mature`) |
| **WK::N5 · Prereq Radicals** | Radicals still needed for N5 items (`jlpt-n5-prereq`, not yet `wk-mature`) |
| **WK::Vocab Context** | Production cloze |
| **WK::Dictation** | Hear → type reading |
| **WK::Grammar** | Hanabira pattern clozes (**Japanese Grammar Context**) |
| **WK::Grammar · Current Tae Kim lesson** | Context cards for current reading lesson (from config cap) |
| **WK::Grammar Exercises** | Tae Kim practice type-in (**Japanese Grammar Exercises**, up to lesson cap) |
| **WK::Grammar Exercises · Current Tae Kim lesson** | Practice cards for current reading lesson only |
| **WK::Phonetic Families** | Phonetic on'yomi drills |

All searches use `-is:suspended`, `(is:due OR is:new)` (today’s workload only — no review-ahead), and **Relative overdueness** ordering. **Prereq** decks also use `-tag:wk-mature` so Guru I+ items (interval ≥ 7d on all card types, tagged by **wk_unlock**) drop out once they satisfy the chain.

---

## 8. Topic guides

**Grammar:** `python wk_decks.py --deck grammar` — Hanabira + Tae Kim ordering; browse by `tag:tk-lesson-basic-…`.

**Vocab cloze:** production in WK sentences; type full kanji when needed.

**Conjugation:** type-in forms; `--verify-conjugations-only` for rule checks.

**Phonetic families:** Keisei DB in `.wk_cache/keisei/`.

**Dictation:** WK native audio on front (intentional).

---

## 9. Backup

```bash
~/anki/scripts/backup_to_google_drive.sh          # quit Anki first
~/anki/scripts/install_backup_launchagent.sh install   # weekly Sunday 2:15 AM
```

Backups → `Google Drive/My Drive/anki/backups/`. See script headers for logs and retention.

---

## 10. Troubleshooting

**403 / Cloudflare:** Use existing `.wk_cache/` or run on a working network.

**Missing Tools menu items:** [§1 add-ons](#anki-add-ons-desktop-required) not installed or failed to load.

**wk_unlock failed to load on Anki 25+:** Update add-on files in `addons21/wk_unlock/` (or refresh symlink), then restart. Anki 25 removed `reviewer_did_end`; use `reviewer_will_end` (called with **no arguments** in 25.09). `main_window_did_init` no longer passes arguments to menu setup hooks.

**Templates not updating:** Always update note types on re-import. Current: `WK Core Item` v5, vocab cloze v7, conjugation v4, dictation v3, grammar cloze v4+.

**Cards stay suspended:** Run **WK Run Unlock Pass** on desktop; check core subject maturity (≥ **7** day interval, Guru I equivalent).

**Counts jumped after import / filtered-deck rebuild:** Usually **not** new unique cards — see [Filtered decks inflated counts](#filtered-decks-inflated-counts-after-import).

**Reading audio failures:** Re-run generator; optional `--refresh-reading-audio`.

**FSRS:** Preset **WK FSRS** via **WK Apply Deck Options**.

### Filtered decks inflated counts after import

You finished core for the day, then imported and ran **WK Setup Filtered Decks** — and suddenly many **New** / **Review** counts appear. Common causes:

| Cause | What happened |
|-------|----------------|
| **More filtered decks** | Each `WK::…` deck shows its own queue (up to its limit). Six Tae Kim/N5 decks can each list ~20 cards — often the **same** physical cards you already saw in `WK::Core *`, not six times more work. |
| **New tags on re-import** | `jlpt-n5-*` tags route cards into new filtered searches they did not match before. `tk-grammar-*` tags change via **wk_tae_kim_track**, not import. |
| **Unlock pass** | **wk_unlock** on load unsuspends eligible `wk-locked` cards → they become **New**. |
| **Bootstrap re-import** | If `"core.bootstrap_scheduling": true` in config, re-import can re-apply WK intervals and fight FSRS. Set it **`false`** after your one-time migration. |
| **Reschedule in filtered decks** | Must be **on** for daily WK filtered decks. If off, Good/Easy show **(end)** and FSRS does not update — see below. |
| **Review-ahead in filtered decks** | Searches use `(is:due OR is:new)` so rebuilds do not pull far-future reviews (little scheduling benefit per Anki manual). Order is **Relative overdueness** among that set. |

**What to do**

1. Set `"core.bootstrap_scheduling": false` in `wk_deck_config.json` before routine re-imports.
2. For today: study **one** track only — e.g. finish `WK::Core *` **or** the Tae Kim/N5 prereq chain, not both in parallel.
3. Check unique workload in Browse: `tag:wk-core is:due` and `tag:wk-core is:new` — that is the real due set, not the sum of every filtered deck badge.
4. If **Good / Easy show (end)**: filtered deck has **Reschedule cards based on my answers** disabled. Regenerate, run **WK Setup Filtered Decks**, or per deck: gear icon → Options → enable reschedule. Without it, filtered-deck reviews do not stick.

### Good / Easy show “(end)” in a filtered deck

Anki shows **1m · 10m · (end) · (end)** when the filtered deck is in **cram mode** (reschedule **off**). Again/Hard may still show learning-step times, but Good/Easy only remove the card from the filtered queue — **home-deck FSRS does not advance**.

WK core study is meant to run **through filtered decks with reschedule on**. After fixing, buttons show normal intervals (e.g. 10m / 4d / …).

**AnkiWeb sync fails mid-upload (~40k items, “network error”):** First sync with reading + grammar TTS media is large (often **500MB–1GB+**, tens of thousands of files). Try: **Preferences → Network → increase sync timeout** (e.g. 120s); stable Wi‑Fi, no VPN; **Sync → upload** on desktop first. On mobile, enable **sync without media** until desktop upload finishes. **Tools → Check Media → Delete Unused** after re-imports (orphans accumulate). Study on desktop only if sync keeps failing — add-ons require desktop anyway. Regenerate with latest generator to dedupe shared audio (see [Media reuse](#media-reuse)).

---

## 12. Tips & tuning

Practical improvements that do not require new features. Prefer these before adding decks or re-importing often.

### Post-migration

| Action | Why |
|--------|-----|
| Set `"core.bootstrap_scheduling": false` | Bootstrap patches WK `ivl`/`due` once. Re-importing with it on can fight FSRS. |
| Do **not** weekly re-import | Only when templates, audio, config, or new WK levels in cache change. Unlock state is **wk_unlock**, not import. |

### Adaptive new cards (`wk_adaptive_new`)

Automatically scales **new cards/day** based on how many **due reviews** you have (WK-style: heavy review days → fewer lessons). Remaining new budget fills in priority order:

1. **Radicals** → **Kanji** → **Vocabulary** → **Supplementary**

Runs on collection load; manual pass: **Tools → WK Adjust New Limits**. Requires **WK Apply Deck Options** first (clones per-tier presets from **WK FSRS**).

Optional config at `out/wk_adaptive_new_config.json` (or `WK_ADAPTIVE_NEW_CONFIG`):

```json
{
  "daily_workload_target": 200,
  "max_new_total": 15,
  "supplementary_max_new": 5,
  "review_count_scope": "tag:wk-core",
  "auto_run_on_load": true
}
```

Example: with defaults, **0 due reviews** → up to **15** new (radicals first); **100 due** → about **7** new; **200+ due** → **0** new until reviews shrink.

Study core via **WK::Core \*** filtered decks as usual; Anki’s per-deck **new/day** limits enforce the allocation.

**JLPT + Tae Kim priority:** regenerate writes `out/wk_study_priority.json` and `out/wk_tae_kim_track_map.json`. **Tae Kim links use the “Vocabulary used in this section” list on each practice page** (part1 of guidetojapanese `*_ex.html` pages through your section cap — not production-exercise context sentences or Hanabira grammar examples). Core notes get JLPT split tags at import; **Tae Kim grammar role tags are runtime-only**:

| Tag | Meaning | Applied |
|-----|---------|---------|
| `tk-grammar-vocab` | Kanji/vocab in Tae Kim section vocabulary lists | **wk_tae_kim_track** (profile `wk_tae_kim_track.json`) |
| `tk-grammar-prereq` | Radicals/kanji needed for those | **wk_tae_kim_track** |
| `jlpt-n5-vocab` | Kanji/vocab at WK levels 1–10 (N5 band) | import |
| `jlpt-n5-prereq` | Radicals/kanji needed for N5 items | import |

**WK Adjust New Limits** reorders new cards in all three core decks when that file is present.

### New cards: protect core (manual alternative)

If you are **not** using `wk_adaptive_new`, the **WK FSRS** preset defaults to **15 new/day** shared across all decks using that preset. Grammar and supplementary decks can steal capacity from core.

In Anki → **Deck options** → per-deck overrides on non-core decks:

- **Core** decks: keep new cards (e.g. 10–15/day combined, or set per deck).
- **Grammar, conjugations, phonetic families**: **0 new** or very low — study when you have time, not every morning.

### FSRS retention

Preset **desired retention** is **0.90**. After a few weeks:

- Reviews feel too easy → try **0.85–0.88** (more reps).
- Burden too high → try **0.92–0.93**.

Change in deck options on the **WK FSRS** preset; give FSRS ~a month before tweaking again.

### Unlock maturity (`wk_unlock`)

Supplementary decks unsuspend when a linked **WkSubjectId** is mature in core (default: interval **≥ 7 days**, WaniKani **Guru I** / srs_stage 5). Optional config at `out/wk_unlock_config.json` (or `WK_UNLOCK_CONFIG`):

```json
{
  "mature_min_interval_days": 7,
  "mature_require_all_card_types": true,
  "burned_interval_days": 365
}
```

Try **14** for Guru II–equivalent stricter gating; **21** for old Master-like behavior.

### Saved searches (Browse)

Save these for quick health checks:

| Search | Use |
|--------|-----|
| `tag:wk-core is:due` | Today’s core workload |
| `tag:wk-locked` | Still gated by unlock |
| `tag:wk-deps-met is:new` | Just unlocked — expect misses |
| `deck:"WaniKani Core · Kanji" prop:lapses>3` | Kanji worth re-reading mnemonics for |

### Mobile + desktop

**wk_unlock** runs on desktop collection load. If you review on AnkiMobile, open **desktop Anki once a week** so unlock passes sync.

### Media reuse

The generator **caches** TTS and WK pronunciation in `.wk_cache/`, but Anki stores media by **filename**. Older builds duplicated files:

| Before | After (current) |
|--------|-----------------|
| Core vocab: `wk_reading_vocabulary_*` + dictation: `wk_dictation_*` | Same `wk_reading_vocabulary_*` in `media/shared/` |
| Grammar/Tae Kim: one file per card (`wk_grammar_*`) | One file per **sentence** (`wk_tts_{hash}.mp3`) shared across decks |
| Separate folders per deck | Single **`media/shared/`** in the bundle |

After upgrading, **re-import `wk_all.apkg`**, then **Tools → Check Media → Delete Unused** to drop orphaned copies from prior imports.

### Leech handling

Dedicated leech decks are optional (legacy). Anki’s **Browse → `tag:leech`** or sort by lapses is enough unless the same reading fails repeatedly.

### Optional later

| Idea | When it’s worth it |
|------|---------------------|
| Pitch CSV / Yomitan dict (`--pitch-csv`, `--yomitan-dict`) | You care about accent, not just reading |
| **Grammar gated by kanji** (runtime, not built) | Grammar feels too hard before core kanji mature — [below](#grammar-gated-by-kanji-planned) |
| Conjugation filtered decks | You want **WK::Conjugations** in the filtered-deck workflow |
| YouTube immersion deck | [docs/wk_immersion_youtube_design.md](docs/wk_immersion_youtube_design.md) |

### Grammar gated by kanji (planned)

**Today:** grammar cards are **not** linked to **wk_unlock**. They import **active** (not `wk-locked`) subject only to **generator** filters:

| Filter | Where | What it does |
|--------|-------|--------------|
| `grammar.max_jlpt`, `max_tae_kim_section`, `max_tae_kim_lesson` | `wk_deck_config.json` | Caps which grammar points are generated at all |
| `grammar.max_unknown_kanji` (default 5) | Generator | Skips example sentences with too many kanji **not** in WK’s kanji+vocab character set |
| `grammar.no_wk_filter` | Config | If `true`, ignores WK kanji set when counting unknown kanji |

That WK kanji set is **everything in your WK cache up to `max_level`**, not what you have **mature in Anki core**. So a sentence can appear while you still struggle with half the kanji on the card — as long as those characters exist somewhere in WK’s catalog and the sentence has ≤ 5 “unknown” kanji by that definition.

**Planned (not implemented):** gate grammar **inside Anki**, like vocab cloze and dictation:

1. Import grammar notes with `tag:wk-locked` (and optionally a field listing required kanji or **WkSubjectId**s).
2. **wk_unlock** (or similar) unsuspends a grammar card only when every kanji in the sentence is **mature in core** (same ≥ 7-day Guru I rule by default).
3. New grammar drips in as your kanji knowledge grows — aligned with reading Tae Kim, not just with “WK has published this level.”

**Until that exists:** rely on **Tae Kim lesson caps** (`grammar.max_tae_kim_lesson`), **`max_unknown_kanji`**, and studying grammar when it matches what you are reading. Lower `max_unknown_kanji` (e.g. 3) for stricter sentences at generate time; it still won’t track live Anki maturity.

**Why it’s deferred:** grammar notes don’t carry **WkSubjectId** today, and sentences mix many kanji — the addon needs a “required kanji” list per note and a maturity check against core decks. Supplementary gating by single **WkSubjectId** was the simpler first step.

---

## 11. Reference

```bash
python wk_decks.py --from-config
python wk_decks.py --deck core
python -m pytest tests/ -q
```

**Related:** [docs/wk_core_srs_design.md](docs/wk_core_srs_design.md) · [docs/wk_immersion_youtube_design.md](docs/wk_immersion_youtube_design.md) · [anki_addon/README.md](anki_addon/README.md) · [§12 Tips & tuning](#12-tips--tuning)
