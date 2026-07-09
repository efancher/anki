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
- WK::Immersion · Yomitan (optional — Yomitan mining queue)
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

# WK Immersion (Yomitan sentence audio)

Synthesizes **full-sentence audio** for **WK Yomitan Immersion** notes when Yomitan adds them via AnkiConnect, and can backfill older notes.

## Install once

Copy `wk_immersion` into Anki's add-ons folder (or run `./scripts/sync_anki_addons.sh`), then restart Anki.

## At mine time

1. Start **VOICEVOX** — see [docs/voicevox_setup.md](../docs/voicevox_setup.md) (English; no need to use VOICEVOX’s Japanese UI). Or set `"engine": "edge"` in `out/wk_immersion_config.json`.
2. Mine with Yomitan **+** — **wk_immersion** enriches cloze/WK fields and fills **SentenceAudio** before the note is saved.

## Backfill / CLI

- **Tools → WK Enrich Mining Notes (cloze + WK links)** — backfill cloze blank, WK ids, hint flags on existing notes
- **Tools → WK Synthesize Immersion Sentence Audio** — notes missing **SentenceAudio**
- `python3 scripts/synthesize_immersion_sentence_audio.py` — via AnkiConnect (Anki must be open)

Hint stages (English → kana-only → full J–J on back) update on **Tools → WK Run Unlock Pass** in **wk_unlock** (no suspend/lock).

See [docs/yomitan_mining.md](../docs/yomitan_mining.md) and [docs/voicevox_setup.md](../docs/voicevox_setup.md).

---

# WK Deck Stats (per-deck progress)

Summary table of SRS progress by deck — separate from **WK Health Check** (sanity checks).

## Install once

Copy `wk_deck_stats` into Anki's add-ons folder (or run `./scripts/sync_anki_addons.sh`),
then restart Anki.

## Usage

**Tools → WK Deck Stats**

### WaniKani core (Radicals / Kanji / Vocabulary)

Note-level buckets aligned with WaniKani intervals:

| Column | Meaning |
|--------|---------|
| **Unseen** | Unlocked, active, **reps = 0** (never reviewed) |
| **Appr** | Reviewed at least once, max interval &lt; 7 days (apprentice) |
| **Guru** | Interval 7–29 days |
| **Master** | Interval ≥ 30 days |
| **Locked** | `wk-locked` or all cards suspended |
| **Total** | Notes in that home deck |

Cards studied in **WK::** filtered queues still count toward the core home deck.

### Other decks (grammar, conjugations, immersion, …)

Card-level Anki counts: **New / Learn / Review / Susp / Total**.

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
- Priority tags (`jlpt-n5-*`)
- WK FSRS preset on core decks
- WK:: filtered decks present and **reschedule** enabled
- `wk_study_priority.json` found on disk

Each run saves `wk_health_snapshot.json` in your Anki profile folder. The next run compares review-card and reps totals to that snapshot — **sharp drops** after re-import may mean scheduling was reset (check `core.bootstrap_scheduling` in config).

## Suggested workflow

1. Run **WK Health Check** before re-import (baseline snapshot).
2. Import `out/wk_all.apkg` with **Update** (not replace).
3. Run **WK Health Check** again — review cards and total reps should not fall sharply.
4. Run **WK Adjust New Limits** — run health check once more; reps/review counts should stay stable (only new-card order / limits change).

