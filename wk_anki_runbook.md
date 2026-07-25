# WaniKani + Grammar → Anki Runbook

Generator: `wk_decks.py` (WaniKani decks) + `grammar_decks.py` (JLPT grammar from [Hanabira](https://hanabira.org/) open data) + immersion mining (Yomitan / Satori / Shadowing).

**Recommended import:** `out/wk_all.apkg` — one file updates every active deck.

### Implementation status

**Done — meaning-anchor curriculum.** WK study lives in Anki + FSRS via:

- **Kanji Meaning Anchor** — primary kanji path (kanji → English); no import lock
- **Core · Vocabulary** — immersion-first study (radicals/kanji/phonetic decks suspended by default retire mode); reading audio on
- `wk_unlock` **add-on** — vocab unlocks without Core Kanji maturity under retire mode; conjugations unlock when linked Core Vocabulary is Guru+
- `no_wk_progress_filter` — import full supplementary catalog; gate with `wk-locked` in Anki
- **Immersion** — Yomitan mining + Satori Reader CSV (`scripts/import_satori.py`) + Shadowing projects (`scripts/import_shadowing.py`)
- **TTS on for core readings** — `reading_audio: true` (vocab = WK native clips; kanji = Voicevox when the engine is running, else edge-tts)

Architecture and tracker: [docs/wk_core_srs_design.md](docs/wk_core_srs_design.md). Yomitan: [docs/yomitan_mining.md](docs/yomitan_mining.md). Satori: [docs/satori_mining.md](docs/satori_mining.md). Shadowing: [docs/shadowing_mining.md](docs/shadowing_mining.md).

**Off by default** (suspended / not in `generate_decks`): vocab-cloze, vocab-sentence, dictation, leeches.

**Not done yet:** grammar gated by kanji maturity; YouTube immersion ([planned doc](docs/wk_immersion_youtube_design.md)).

---



## How to use this doc


| If you are…                               | Start here                                                                            |
| ----------------------------------------- | ------------------------------------------------------------------------------------- |
| Setting up for the first time             | [§1 One-time setup](#1-one-time-setup) → [§2 First import](#2-first-import-migration) |
| Studying day to day                       | [§3 Daily study](#3-daily-study)                                                      |
| Regenerating after config or code changes | [§4 Regenerate & re-import](#4-regenerate--re-import)                                 |
| Importing a Shadowing / Satori project    | [§8 Topic guides](#8-topic-guides) → Shadowing / Satori                               |
| Tuning FSRS, unlocks, and study habits    | [§12 Tips & tuning](#12-tips--tuning)                                                 |
| Changing grammar scope                    | [§5 Configuration](#5-configuration)                                                  |
| Looking up a specific deck                | [§6 Deck catalog](#6-deck-catalog)                                                    |
| Something broke on import                 | [§10 Troubleshooting](#10-troubleshooting)                                            |


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

Five add-ons in `anki_addon/` are **not** in the `.apkg` and **not** on AnkiWeb. On macOS, `python wk_decks.py --from-config` **syncs them automatically** after each generate (`sync_anki_addons: true` in `wk_deck_config.json`). **Restart Anki** after sync so code changes load.

**Manual install or one-time setup** (any platform):

```bash
~/anki/scripts/sync_anki_addons.sh
# Quit Anki, then restart.
```

Disable auto-sync: `"sync_anki_addons": false` in config, or pass `--no-sync-addons`.

**Other platforms:** `%APPDATA%\Anki2\addons21\` (Windows) or `~/.local/share/Anki2/addons21/` (Linux).

**Verify** after restart — **Tools** menu should show:


| Folder              | Menu item                   |
| ------------------- | --------------------------- |
| `wk_deck_options`   | **WK Apply Deck Options**   |
| `wk_unlock`         | **WK Run Unlock Pass**      |
| `wk_adaptive_new`   | **WK Adjust New Limits**    |
| `wk_health_check`   | **WK Health Check**         |


**Optional (dev):** symlink the add-on folders instead of `cp -R` so repo updates apply after restart. Details: [anki_addon/README.md](anki_addon/README.md).

### Second machine (work desktop, etc.)

AnkiWeb syncs your **collection** (cards, scheduling, deck options, tags) but **not** add-on code. Each desktop needs a one-time add-on install.


| Syncs via AnkiWeb                              | Local install required                     |
| ---------------------------------------------- | ------------------------------------------ |
| Cards, due dates, `wk-locked` / unlock results | Add-on folders in `addons21/`              |
| Deck option presets (`WK FSRS · New · …`)      | **Tools → WK …** menu items                |
| Home decks and their scheduling                | Auto unlock / adaptive new on that machine |


**On each additional desktop:**

1. Clone this repo (or copy `anki_addon/` and `scripts/sync_anki_addons.sh`).
2. Run the sync script (set `ANKI_ADDONS_DIR` on Windows/Linux):
  ```bash
   cd /path/to/anki
   ./scripts/sync_anki_addons.sh
   # Quit Anki on that machine, then restart.
  ```
   Windows (PowerShell):
3. **Verify** the **Tools → WK …** menu items appear after restart.

After that, use normal Anki sync. Unlock passes and adaptive new limits **run only on machines where the add-ons are installed** — run **WK Run Unlock Pass** / **WK Adjust New Limits** on any desktop before syncing if you want those effects everywhere without opening the other machine.

**Desktop Anki is required** for add-ons. AnkiMobile can review synced cards but cannot run unlock or adaptive-new refreshes.

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
   Equivalent flags for first migration: `--no-wk-progress-filter --bootstrap-wk-scheduling` with `core` in `generate_decks`. Set `"core.bootstrap_scheduling": true` in config for that one run only.
   First run with `core.reading_audio: true` can take a long time (kanji TTS + WK vocab downloads). Progress bar on stderr; re-run fills failed clips.
3. **Import** `out/wk_all.apkg` → **Update note types** (Always update when prompted).
4. **Tools → WK Apply Deck Options** — assigns **WK FSRS** preset; enable FSRS globally if asked.
5. **Tools → WK Run Unlock Pass** — unsuspends level-1 radicals and eligible cards (also runs on later desktop opens).
6. **Tools → WK Health Check** — sanity stats (review history and priority tags). Run again after import to compare against the saved snapshot.
7. **Verify** in Browse:
  - `tag:wk-core` — spot-check due dates vs WaniKani if you bootstrapped scheduling.
  - `tag:wk-locked` — supplementary suspended until linked subject is mature in core.
8. **Stop WK reviews.** Optional: keep WK **lessons** only until caught up in Anki.



### After migration

- Re-run the generator for **new WK catalog content** only — unlock state is handled by **wk_unlock** in Anki, not re-import.
- Set `"core.bootstrap_scheduling": false` in `wk_deck_config.json` after the one-time WK interval import (see [§12](#12-tips--tuning)).
- Routine sync: `python wk_decks.py --from-config`

---



## 3. Daily study



### Core SRS (main queue)

**Active study decks** (retire mode on by default):

- **WaniKani Core · Vocabulary** — immersion-linked new cards first; other vocab at lowest priority
- **WaniKani Kanji Meaning Anchor** — ungated meaning-only kanji path (primary for kanji)

**Suspended (not studied):** Core · Radicals, Core · Kanji, and **WaniKani Phonetic
Families**. **WK Adjust New Limits** re-suspends them each run so rebuilds cannot
sneak cards back. One-shot without waiting:
`python scripts/retire_kanji_radical_study_ankiconnect.py`.

**No filtered decks.** The `Immersion Core · …` decks are retired — study Core ·
Vocabulary directly, where immersion priority already puts mined words first.
Browse the same sets with `tag:immersion-core::satori` / `::shadowing` /
`::candidates` (those tags are still maintained).

Set `retire_kanji_radical_phonetic_study: false` in `wk_adaptive_new_config.json` /
`wk_unlock_config.json` to restore classic radical→kanji→vocab study.

**WK Adjust New Limits** puts the full core new budget on Vocabulary and places
Satori/Shadowing-linked subjects first in that queue.

### Supplementary decks

**Conjugations** and **verb/adjective types** import with `tag:wk-locked` and `WkSubjectId` pointing at the vocab word (kanji ids may still appear in `PrerequisiteIds` for reference). **wk_unlock** unsuspends them when that vocab is Guru I+ (≥ 7 day interval) in **WaniKani Core · Vocabulary**. **Phonetic families** unlock when any family kanji has been reviewed once in the meaning anchor (deck stays suspended under retire mode). **Grammar context** is not `wk-locked` — see [Grammar gated by kanji](#grammar-gated-by-kanji-planned).

**Kanji Meaning Anchor** has **no** import-time lock — study any kanji freely. It is the primary kanji path.

With retire mode on, **Core Vocabulary** unlocks without waiting for Core Kanji maturity
(classic radical→kanji gating is skipped for vocab only).

Open **desktop Anki periodically** if you study on mobile, so unlock passes sync.

### Grammar

Review in **Japanese Grammar Context** when useful — Hanabira pattern clozes filtered by JLPT cap at generate time.


Study directly from **Japanese Grammar Context**.

**Conjugation drills** use separate home decks:


| Home deck                                   | Content                         |
| ------------------------------------------- | ------------------------------- |
| **WaniKani Verb Conjugation Practice**      | Forward verb forms              |
| **WaniKani Adjective Conjugation Practice** | Forward adjective forms         |
| **WaniKani Verb Conjugation Reverse**       | Reverse verb forms              |
| **WaniKani Verb Type Practice**             | Verb type recognition           |
| **WaniKani Adjective Type Practice**        | Adjective type recognition      |




### Suggested daily order

1. **WaniKani Kanji Meaning Anchor** — primary kanji (meaning-only).
2. **WaniKani Core · Vocabulary** — immersion-first ordering, no filtered deck needed.
3. Conjugation home decks (verbs → adjectives → reverse/types as you like).
4. **Immersion · Yomitan Mining** / **Immersion · Satori** / **Immersion · Shadowing** for cloze reading practice (Shadowing = native clip; Candidates optional).
5. **Japanese Grammar Context** when you have energy.

Grammar is **not** gated by kanji maturity today (see [§12](#12-tips--tuning)); use `grammar.max_jlpt` and `max_unknown_kanji` at generate time instead.

## 4. Regenerate & re-import

```bash
source env_anki/bin/activate
python wk_decks.py --from-config
```

On macOS this also runs `scripts/sync_anki_addons.sh` (rsync + `__pycache__` cleanup). **Restart Anki** before using Tools menu add-ons if they changed.

Then in Anki:

1. Import `out/wk_all.apkg` → update note types / merge notes.
2. **Tools → WK Apply Deck Options** (if new decks appeared).
3. **Tools → WK Run Unlock Pass** (optional; also on collection load).

**Do not re-import to refresh unlock state** — that is **wk_unlock**’s job.

**Preview:** `python wk_decks.py --from-config --dry-run`

---



## 5. Configuration

Edit `wk_deck_config.json`, then `python wk_decks.py --from-config`.


| Key                          | Typical value      | Effect                                                     |
| ---------------------------- | ------------------ | ---------------------------------------------------------- |
| `generate_decks`             | `core-radical`, `kanji-meaning`, verb/adjective types, … | Decks in `wk_all.apkg` (WK conjugation packs off by default) |
| `no_wk_progress_filter`      | `true`             | Full supplementary import + Anki gating                    |
| `fetch_wk_review_statistics` | `false`            | Skip WK review_statistics API (leech decks only)           |
| `core.bootstrap_scheduling`  | `false`            | **Off by default.** Set `true` once for WK interval import |
| `core.reading_audio`         | `true`             | Vocab WK audio + kanji Voicevox/edge TTS                                 |
| `grammar.max_jlpt`           | `N5`               | Include Hanabira points through this JLPT level            |
| `grammar.max_unknown_kanji`  | `5`                | Skip example sentences with too many unknown WK kanji      |


---



## 6. Deck catalog



### Core SRS


| Deck                           | Purpose                                   |
| ------------------------------ | ----------------------------------------- |
| **WaniKani Kanji Meaning Anchor** | Kanji → English only (primary kanji path) |
| **WaniKani Core · Vocabulary** | Immersion-first new; non-immersion lowest priority |
| **WaniKani Core · Radicals / Kanji** | Suspended under retire mode (not studied) |
| **WaniKani Phonetic Families** | Suspended under retire mode (not studied) |




### Supplementary (default config)


| Deck                                                                     | Gating                                                                         |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| Conjugations, Verb/Adj Types | `WkSubjectId` + `wk-locked` until linked Core Vocabulary Guru+ |
| Kanji Meaning Anchor | `WkSubjectId` only — no `wk-locked` |
| Phonetic Families | `PrerequisiteIds` (family kanji) + `wk-locked` until any family kanji reviewed once |
| Grammar Context                                                          | JLPT cap only at generate time; sentence TTS off                               |
| Immersion · Yomitan / Immersion · Satori / Immersion · Shadowing | Cloze production; Yomitan progressive hints via unlock; Satori/Shadowing English always on |

Off by default (not in `generate_decks`): vocab-cloze, vocab-sentence, dictation, leeches. Core reading audio is on (`reading_audio: true`).


Optional individual decks: leeches, verb pairs, confusables, etc. — `python wk_decks.py --deck leeches`

---



## 7. Home-deck study

Filtered decks are retired. Study from the generated home decks directly.
**WK Adjust New Limits** assigns per-tier new/day limits and reprioritizes the
core Radicals, Kanji, and Vocabulary queues; **wk_unlock** controls eligibility
by suspending or unsuspending prerequisite-gated cards.

---



## 8. Topic guides

**Grammar:** `python wk_decks.py --deck grammar` — Hanabira clozes ordered by JLPT; browse by `tag:jlpt-n5`, etc.

**Conjugation:** immersion-driven drills via `python3 scripts/import_immersion_conjugations.py` → **Immersion · Conjugations**. Forms allowlist in `wk_deck_config.json` → `conjugation_forms`. `--verify-conjugations-only` for rule checks. WK-linked notes unlock when Core Vocabulary is Guru+.

**Phonetic families:** Keisei DB in `.wk_cache/keisei/`. Unlock when any family kanji reviewed once in the meaning anchor. Card backs lead with the phonetic component, then “usually signals” ordered most→least (with WK mnemonic keywords, e.g. `しょ - Show`), then a focus table of Reading / Started / Total by each family kanji’s primary on’yomi (rows sum to the footer). Regen: `python wk_decks.py --deck phonetic-families`. Live patch: `python3 scripts/patch_phonetic_readings_ankiconnect.py --from-cache`.

**Core Item phonetic hint:** when a Core Kanji (or single-kanji vocab) card tests an on’yomi that the kanji’s phonetic component usually signals, the back shows e.g. `Phonetic 寺 → じ`. Multi-kanji vocab is skipped. Regen with core decks, or live patch: `python3 scripts/patch_core_phonetic_hint_ankiconnect.py --from-cache`.

**Kanji meaning anchor:** kanji character on front, primary WK meaning(s) on back — no reading required, **no import lock**. Primary kanji path. `--deck kanji-meaning` to build standalone.

**Yomitan immersion:** Sentence cloze on front — type the reading in kana; sentence audio + pitch on back; second **Shadow → pitch** card for speaking practice. Native YouTube clips via `scripts/extract_immersion_clip.py`. Setup: [docs/yomitan_mining.md](docs/yomitan_mining.md).

**Satori immersion:** One-shot refresh: `python3 scripts/refresh_satori.py export.csv` (cloze + conjugations + template push + TTS + unlock). Or import CSV alone with `python3 scripts/import_satori.py export.csv` → `out/wk_satori.apkg`. Conjugations only: `python3 scripts/import_immersion_conjugations.py --satori export.csv`. Setup: [docs/satori_mining.md](docs/satori_mining.md).

**Shadowing immersion:** Full checklist: [docs/shadowing_mining.md](docs/shadowing_mining.md). **Preferred:** Glossbook vocabulary review → `.mining.zip`. Short version:

```bash
# Preferred: curated selections from Glossbook
python3 scripts/import_shadowing.py ~/Downloads/VIDEO.mining.zip

# Legacy: automatic matching from a shadowmine project (use fugashi venv)
SHADOW_PY="$HOME/shadowing/cli/.venv/bin/python"
"$SHADOW_PY" scripts/import_shadowing.py ~/shadowing/cli/projects/VIDEO_ID
# → out/wk_shadowing.apkg + out/wk_shadowing_candidates.apkg

# Import both .apkg files. Do NOT enable "Update existing notes".
# Tools → WK Adjust New Limits (priority for shadowing-mining)

# Optional Target/Reading TTS only (keep native sentence clips):
python3 scripts/synthesize_immersion_sentence_audio.py \
  --surface-only --note-type "WK Shadowing Immersion"
```

| Task | Command |
|------|---------|
| Push templates | `python3 scripts/push_satori_template_ankiconnect.py --model "WK Shadowing Candidate" --no-refresh-cloze` |
| Fix cloze HTML on live notes | `… --cloze-only --model "WK Shadowing Immersion"` (and Candidate) |
| Restore native `SentenceAudio` | `python3 scripts/restore_shadowing_native_audio.py` |

**Do not** run immersion TTS `--force` to “refresh” Shadowing sentence audio — use `--surface-only` or the restore script. Prefer WK clozes over glued candidates (readings ending in っ are almost always bad).

**Off by default:** vocab-cloze, vocab-sentence, dictation, leeches (opt-in `--deck …`). Core `reading_audio` is on (WK vocab clips + Voicevox/edge for kanji).

**Rendaku:** Two-kanji WK compounds where the second morpheme voices (e.g. やま + かわ → やま**が**わ). Card shows morpheme hint → type full reading. Study from **WaniKani Rendaku**. Default min SRS Master+ (`--rendaku-min-srs 7`).

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

**Templates not updating:** Always update note types on re-import. Current: conjugation v7, word class v5, kanji meaning v1, grammar cloze v4+, mining v14. If Anki reports thousands of notes could not be imported, live cards are on `NoteType+++` variants — see `scripts/patch_kanji_prereqs_ankiconnect.py`.

**Cards stay suspended:** Run **WK Run Unlock Pass** on desktop; conjugations/types need linked Core Vocabulary maturity (≥ **7** day interval, Guru I equivalent).

**Filtered decks reappear (`WK::…` or `Immersion Core · …`):** Sync add-ons and
**restart Anki** (the running add-on recreates them until new code loads), then run
`python3 scripts/remove_wk_filtered_decks_ankiconnect.py`; it returns queued cards
to their home decks before removing the retired decks. Keep
`immersion_core_filtered_decks_enabled: false` in `out/wk_adaptive_new_config.json`.

**Cards stuck in a deleted filtered deck** (blank deck in Browse, or `deck:filtered`
finds cards with no deck): Browse → select → **Change Deck** → home deck, or run
**Tools → Check Database**.

**Reading audio failures:** Re-run generator; optional `--refresh-reading-audio`.

**Shadowing sentence plays Voicevox / wrong clip:** Native clips belong in `SentenceAudio` as `wk_shadowing_*.m4a`. Restore with `python3 scripts/restore_shadowing_native_audio.py`. For Target/Reading buttons only: `python3 scripts/synthesize_immersion_sentence_audio.py --surface-only --note-type "WK Shadowing Immersion"`.

**Shadowing candidate answer ends in っ / looks cut off:** Usually a bad lemma (e.g. `敬語使`). Delete the note; rebuild with the shadowing CLI venv (`fugashi`). See [docs/shadowing_mining.md](docs/shadowing_mining.md).

**Shadowing / Satori cloze blank missing after a code change:** `ClozeSentence` is stored — run `python3 scripts/push_satori_template_ankiconnect.py --cloze-only --model "…"`. Do not re-import with **Update existing notes** just to refresh templates (can wipe media).

**FSRS:** Preset **WK FSRS** via **WK Apply Deck Options**.

**AnkiWeb sync fails mid-upload (~40k items, “network error”):** First sync with reading + grammar TTS media is large (often **500MB–1GB+**, tens of thousands of files). Try: **Preferences → Network → increase sync timeout** (e.g. 120s); stable Wi‑Fi, no VPN; **Sync → upload** on desktop first. On mobile, enable **sync without media** until desktop upload finishes. **Tools → Check Media → Delete Unused** after re-imports (orphans accumulate). Study on desktop only if sync keeps failing — add-ons require desktop anyway. Regenerate with latest generator to dedupe shared audio (see [Media reuse](#media-reuse)).

---



## 12. Tips & tuning

Practical improvements that do not require new features. Prefer these before adding decks or re-importing often.

### Post-migration


| Action                                   | Why                                                                                                              |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Set `"core.bootstrap_scheduling": false` | Default in config. Bootstrap patches WK `ivl`/`due` once; only enable for first migration.                       |
| Do **not** weekly re-import              | Only when templates, audio, config, or new WK levels in cache change. Unlock state is **wk_unlock**, not import. |




### Adaptive new cards (`wk_adaptive_new`)

Automatically scales **new cards/day** based on how many **due reviews** you have (WK-style: heavy review days → fewer lessons). Remaining new budget fills in priority order:

1. **Radicals** → **Kanji** → **Vocabulary** → **Supplementary**

Runs on collection load, right after apkg **import**, and after **sync**; manual pass: **Tools → WK Adjust New Limits**. Requires **WK Apply Deck Options** first (clones per-tier presets from **WK FSRS**).

Optional config at `out/wk_adaptive_new_config.json` (or `WK_ADAPTIVE_NEW_CONFIG`):

```json
{
  "daily_workload_target": 200,
  "max_new_total": 15,
  "supplementary_max_new": 5,
  "review_count_scope": "tag:wk-core",
  "auto_run_on_load": true,
  "immersion_priority_enabled": true,
  "immersion_tags": ["satori-mining", "shadowing-mining"],
  "immersion_unsuspend": true
}
```

Example: with defaults, **0 due reviews** → up to **15** new (radicals first); **100 due** → about **7** new; **200+ due** → **0** new until reviews shrink.

Study core from the three **WaniKani Core ·** home decks; Anki’s per-deck
**new/day** limits enforce the allocation.

**JLPT priority:** regenerate writes `out/wk_study_priority.json`. Core notes get JLPT split tags at import:


| Tag              | Meaning                                 | Applied |
| ---------------- | --------------------------------------- | ------- |
| `jlpt-n5-vocab`  | Kanji/vocab at WK levels 1–10 (N5 band) | import  |
| `jlpt-n5-prereq` | Radicals/kanji needed for N5 items      | import  |


**WK Adjust New Limits** reorders new cards in Core Vocabulary when that file is present
(radicals/kanji decks are suspended under retire mode).

**Immersion priority (overrides JLPT order):** when `immersion_priority_enabled` is on (default), vocab tagged `satori-mining` or `shadowing-mining` plus its prerequisite tree jump to the **front** of the Core Vocabulary new queue, ahead of the JLPT/level baseline. Non-immersion vocab stays available at lowest priority. The set is read live from the collection, so **re-importing** immersion `.apkg` files re-checks and updates priority automatically on the next collection load / import / sync. Set `immersion_priority_enabled: false` to fall back to pure JLPT/level order.

**Immersion core tags (no filtered decks):** the same refresh tags Core
Kanji/Vocabulary linked from immersion with `immersion-core::satori` /
`::shadowing` / `::candidates`, so you can Browse or search each source inside the
home decks. **Tools → WK Rebuild Immersion Core Decks** now only refreshes those
tags.

`Immersion Core · … · {Kanji,Vocabulary}` **filtered decks are retired**
(`immersion_core_filtered_decks_enabled: false`, the default). To remove any that
still exist and return their cards home:

```bash
python3 scripts/remove_wk_filtered_decks_ankiconnect.py --dry-run
python3 scripts/remove_wk_filtered_decks_ankiconnect.py
```

**Restart Anki after syncing add-ons** before running the cleanup — the running
add-on recreates the decks until the new code loads.

<details>
<summary>Re-enabling filtered decks (not recommended)</summary>

Set `"immersion_core_filtered_decks_enabled": true` in
`out/wk_adaptive_new_config.json`, restart Anki, then **Tools → WK Rebuild
Immersion Core Decks**. Kanji filtered decks stay unbuilt while retire mode is on.

Keep **Reschedule cards based on my answers** on (the addon sets this). Do not
rebuild/empty while cards are still in learning — Anki turns those back into
**new**. If that already happened: Browse the cards → **Cards → Set Due Date → 0**
(converts new → review due today). The addon also salvages graduated-but-new
cards before rebuild and skips rebuild while learning cards are present.

</details>

**Unseen vs new limit:** in WK Deck Stats, core tables use **Locked / New / Reviewed**
(New = `is:new`). Locked counts rise for suspended radicals/kanji under retire mode.

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

**Conjugations / verb·adj types** unsuspend when linked Core Vocabulary is Guru+ (default: interval **≥ 7 days**). Other supplementary notes with `PrerequisiteIds` still use **Kanji Meaning Anchor** Guru+. Phonetic families use **reviewed once**. Optional config at `out/wk_unlock_config.json` (or `WK_UNLOCK_CONFIG`):

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


| Search                                       | Use                                  |
| -------------------------------------------- | ------------------------------------ |
| `tag:wk-core is:due`                         | Today’s core workload                |
| `tag:wk-locked`                              | Still gated by unlock                |
| `tag:wk-deps-met is:new`                     | Just unlocked — expect misses        |
| `deck:"WaniKani Core · Kanji" prop:lapses>3` | Kanji worth re-reading mnemonics for |




### Mobile + desktop

**wk_unlock** runs on desktop collection load. If you review on AnkiMobile, open **desktop Anki once a week** so unlock passes sync.

### Media reuse

The generator **caches** TTS and WK pronunciation in `.wk_cache/`, but Anki stores media by **filename**. Older builds duplicated files:


| Before                                                              | After (current)                                                     |
| ------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Core vocab: `wk_reading_vocabulary_*` + dictation: `wk_dictation_*` | Same `wk_reading_vocabulary_*` in `media/shared/`                   |
| Grammar/Tae Kim: one file per card (`wk_grammar_*`)                 | One file per **sentence** (`wk_tts_{hash}.mp3`) shared across decks |
| Separate folders per deck                                           | Single `media/shared/` in the bundle                                |


After upgrading, **re-import** `wk_all.apkg`, then **Tools → Check Media → Delete Unused** to drop orphaned copies from prior imports.

### Leech handling

Dedicated leech decks are optional (legacy). Anki’s **Browse →** `tag:leech` or sort by lapses is enough unless the same reading fails repeatedly.

### Optional later


| Idea                                                       | When it’s worth it                                                                                               |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Pitch CSV / Yomitan dict (`--pitch-csv`, `--yomitan-dict`) | You care about accent, not just reading                                                                          |
| **Yomitan immersion deck**                                 | [docs/yomitan_mining.md](docs/yomitan_mining.md) — cloze + shadow/pitch + clip audio |
| **Satori immersion import**                                | [docs/satori_mining.md](docs/satori_mining.md) — CSV → Immersion · Satori                                        |
| **Shadowing immersion import**                             | [docs/shadowing_mining.md](docs/shadowing_mining.md) — project → Immersion · Shadowing (+ candidates)          |
| YouTube immersion deck                                     | [docs/wk_immersion_youtube_design.md](docs/wk_immersion_youtube_design.md) (deferred)                            |




### Grammar gated by kanji (planned)

**Today:** grammar cards are **not** linked to **wk_unlock**. They import **active** (not `wk-locked`) subject only to **generator** filters:


| Filter                                  | Where                 | What it does                                                                          |
| --------------------------------------- | --------------------- | ------------------------------------------------------------------------------------- |
| `grammar.max_jlpt`                      | `wk_deck_config.json` | Caps which grammar points are generated at all                                        |
| `grammar.max_unknown_kanji` (default 5) | Generator             | Skips example sentences with too many kanji **not** in WK’s kanji+vocab character set |
| `grammar.no_wk_filter`                  | Config                | If `true`, ignores WK kanji set when counting unknown kanji                           |


That WK kanji set is **everything in your WK cache up to** `max_level`, not what you have **mature in Anki core**. So a sentence can appear while you still struggle with half the kanji on the card — as long as those characters exist somewhere in WK’s catalog and the sentence has ≤ 5 “unknown” kanji by that definition.

**Planned (not implemented):** gate grammar **inside Anki**, like vocab cloze and dictation:

1. Import grammar notes with `tag:wk-locked` (and optionally a field listing required kanji or **WkSubjectId**s).
2. **wk_unlock** (or similar) unsuspends a grammar card only when every kanji in the sentence is **mature in core** (same ≥ 7-day Guru I rule by default).
3. New grammar drips in as your kanji knowledge grows — aligned with what you can read in core, not just with “WK has published this level.”

**Until that exists:** rely on `grammar.max_jlpt`, `max_unknown_kanji`, and studying grammar when it matches what you are reading. Lower `max_unknown_kanji` (e.g. 3) for stricter sentences at generate time; it still won’t track live Anki maturity.

**Why it’s deferred:** grammar notes don’t carry **WkSubjectId** today, and sentences mix many kanji — the addon needs a “required kanji” list per note and a maturity check against core decks. Supplementary gating by single **WkSubjectId** was the simpler first step.

---



## 11. Reference

```bash
python wk_decks.py --from-config
python wk_decks.py --deck core
python -m pytest tests/ -q
```

**Related:** [docs/wk_core_srs_design.md](docs/wk_core_srs_design.md) · [docs/wk_immersion_youtube_design.md](docs/wk_immersion_youtube_design.md) · [anki_addon/README.md](anki_addon/README.md) · [§12 Tips & tuning](#12-tips--tuning)