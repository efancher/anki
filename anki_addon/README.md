# WK Filtered Deck Setup (Anki add-on)

Filtered decks cannot be included in `.apkg` imports. This add-on creates them in your
Anki profile after you import `out/wk_all.apkg`.

## Install once

1. Find Anki's add-ons folder:
   - macOS: `~/Library/Application Support/Anki2/addons21/`
   - Windows: `%APPDATA%/Anki2/addons21/`
   - Linux: `~/.local/share/Anki2/addons21/`

2. Copy the `wk_filtered_decks` folder into that directory.

3. Restart Anki.

## Weekly workflow

```bash
python wk_decks.py --deck all --only-started
```

1. Import `out/wk_all.apkg` into Anki (choose **Update** for note types).
2. In Anki: **Tools → WK Setup Filtered Decks**.
3. Select `out/anki_filtered_decks.json` if prompted (or set `WK_FILTERED_DECKS_JSON`).

This creates/rebuilds filtered decks under the **WK** deck group:

- WK::Daily Priority
- WK::Verb Contrasts
- WK::Leeches
- WK::Meaning Leeches
- WK::Reading Leeches
- WK::Core Radicals / Kanji / Vocabulary
- WK::Confusables Light

## Optional: default JSON path

```bash
export WK_FILTERED_DECKS_JSON="$HOME/anki/out/anki_filtered_decks.json"
```

Then the menu command finds the file automatically.

---

# WK Deck Options Setup (Anki add-on)

Each generated `.apkg` embeds a **WK FSRS** deck-options preset. This add-on assigns
that preset to every WaniKani deck in your profile and tries to enable FSRS if it is
not already on.

## Install once

Copy the `wk_deck_options` folder into Anki's add-ons folder (same path as above),
then restart Anki.

## Weekly workflow

After importing `out/wk_all.apkg`:

1. **Tools → WK Apply Deck Options**
2. Select `out/anki_deck_options.json` if prompted (or set `WK_DECK_OPTIONS_JSON`)

## Optional: default JSON path

```bash
export WK_DECK_OPTIONS_JSON="$HOME/anki/out/anki_deck_options.json"
```

---

# WK Unlock (core SRS prerequisites)

Enforces radical → kanji → vocab unlock order inside Anki. Unsuspends `wk-locked`
core notes when all `PrerequisiteIds` are mature; unsuspends supplementary notes
(vocab cloze, dictation, conjugation) when their linked `WkSubjectId` vocab is mature in core.
Tags `wk-mature` / `wk-deps-met`.

## Install once

Copy the `wk_unlock` folder into Anki's add-ons folder (same path as above),
then restart Anki.

## After core deck import

1. Import `out/wk_all.apkg` with `--bootstrap-wk-scheduling` (one-time migration).
2. **Tools → WK Run Unlock Pass** (or wait for automatic pass on collection load).

## Optional config

Create `out/wk_unlock_config.json` (or set `WK_UNLOCK_CONFIG`):

```json
{
  "mature_min_interval_days": 7,
  "mature_require_all_card_types": true,
  "burned_interval_days": 365
}
```

Design and implementation tracker: [docs/wk_core_srs_design.md](../docs/wk_core_srs_design.md)

Migration playbook (one-time WK → Anki core SRS): [wk_anki_runbook.md](../wk_anki_runbook.md#core-srs-migration-wk--anki)

---

# WK Adaptive New (review-aware lesson limits)

Scales daily **new cards/day** per deck tier based on due review load. Priority:
radicals → kanji → vocabulary → supplementary.

## Install once

Copy the `wk_adaptive_new` folder into Anki's add-ons folder (same path as above),
then restart Anki.

## Setup

1. **Tools → WK Apply Deck Options** (creates the base **WK FSRS** preset).
2. **Tools → WK Adjust New Limits** — creates per-tier presets and assigns decks.

Runs automatically on collection load when `auto_run_on_load` is true (default).

## Optional config

Create `out/wk_adaptive_new_config.json` (or set `WK_ADAPTIVE_NEW_CONFIG`):

```json
{
  "daily_workload_target": 200,
  "max_new_total": 15,
  "supplementary_max_new": 5,
  "review_count_scope": "tag:wk-core",
  "auto_run_on_load": true
}
```

---

# WK Health Check (collection sanity stats)

Read-only checks you can run in desktop Anki after import, **WK Adjust New Limits**, or anytime you want confidence that scheduling was not wiped.

## Install once

Copy the `wk_health_check` folder into Anki's add-ons folder (same path as above),
then restart Anki.

## Usage

**Tools → WK Health Check**

The report includes:

- Core deck counts (new / learn / review / mature / reps)
- Whether any core cards have review history (`reps > 0`)
- Suspicious cards (e.g. reps > 0 but still `new`)
- Priority tags (`tk-grammar-*`, `jlpt-n5-*`)
- WK FSRS preset on core decks
- WK:: filtered decks present and **reschedule** enabled
- `wk_study_priority.json` found on disk

Each run saves `wk_health_snapshot.json` in your Anki profile folder. The next run compares review-card and reps totals to that snapshot — **sharp drops** after re-import may mean scheduling was reset (check `core.bootstrap_scheduling` in config).

## Suggested workflow

1. Run **WK Health Check** before re-import (baseline snapshot).
2. Import `out/wk_all.apkg` with **Update** (not replace).
3. Run **WK Health Check** again — review cards and total reps should not fall sharply.
4. Run **WK Adjust New Limits** — run health check once more; reps/review counts should stay stable (only new-card order / limits change).

---

# WK Tae Kim Track (runtime grammar role tags)

`tk-grammar-vocab` and `tk-grammar-prereq` tags are **not** baked into core notes at import. Regenerate once to write the track map; the add-on applies role tags from your current lesson cap at runtime.

## Install once

Copy the `wk_tae_kim_track` folder into Anki's add-ons folder (same path as above),
then restart Anki.

## After core deck import

1. Regenerate: `python wk_decks.py --from-config` (writes `out/wk_tae_kim_track_map.json` and `out/wk_tae_kim_track_config.json`).
2. Import `out/wk_all.apkg` with **Update**.
3. Sync add-ons: `./scripts/sync_anki_addons.sh` (or auto-sync on macOS), then restart Anki.
4. On first run, the add-on copies `out/wk_tae_kim_track_config.json` into your profile as `wk_tae_kim_track.json` (edit lesson cap there — not in `wk_deck_config.json` for day-to-day bumps).
5. **Tools → WK Sync Tae Kim Track** — applies grammar role tags and rebuilds **WK::Grammar · Current Tae Kim lesson** filtered decks.
6. When you finish a subsection: **Tools → WK Bump Tae Kim Lesson** (or edit `wk_tae_kim_track.json` and sync again).

Runs automatically on collection load when `auto_run_on_load` is true (default).

## Profile config

`~/Library/Application Support/Anki2/[profile]/wk_tae_kim_track.json`:

```json
{
  "max_tae_kim_lesson": "expressing-state-of-being",
  "ahead_prereq_lessons": 1,
  "auto_run_on_load": true,
  "auto_update_filtered_decks": true
}
```

Track map path: set `WK_TAE_KIM_TRACK_MAP` or place `wk_tae_kim_track_map.json` in `out/` (default after regenerate).

---

# WK Mining (Yomitan integration)

Links mined notes to **WkSubjectId**, applies **wk-locked** until core vocab matures, and reports duplicate sentences.

## Install once

Copy the `wk_mining` folder into Anki's add-ons folder (same path as above),
then restart Anki.

## After regenerate

1. `python wk_decks.py --from-config` writes `out/wk_vocab_lookup.json`.
2. Import `out/wk_all.apkg` (includes empty **Immersion · Yomitan Mining** deck + note type).
3. Configure Yomitan: [docs/yomitan_mining.md](../docs/yomitan_mining.md).

## Tools

- **WK Link Mining Notes** — match expressions to WK ids; suspend until mature.
- **WK Mining Duplicate Report** — same normalized sentence mined twice.

Optional: `WK_VOCAB_LOOKUP=/path/to/wk_vocab_lookup.json`

Full setup: [docs/yomitan_mining.md](../docs/yomitan_mining.md)

