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

**Immersion-driven new order:** within each core deck, vocabulary mined from
immersion (Satori, tag `satori-mining`) and its full prerequisite tree
(vocab → kanji → radicals) lead the new-card queue, ahead of the JLPT/WK-level
baseline. The set is read **live from the collection** on load, after apkg
import, and after sync — so re-importing or newly mining Satori cards
reprioritizes automatically (no generator re-run).

## Install once

Copy the `wk_adaptive_new` folder into Anki's add-ons folder (same path as above),
then restart Anki.

## Setup

1. **Tools → WK Apply Deck Options** (creates the base **WK FSRS** preset).
2. **Tools → WK Adjust New Limits** — creates per-tier presets and assigns decks.

Runs automatically on collection load, after apkg import, and after sync when
`auto_run_on_load` is true (default). The Tools menu is always a manual backstop.

## Optional config

| Key | Default | Effect |
|-----|---------|--------|
| `immersion_priority_enabled` | `true` | Float immersion-mined subjects + prereqs to the front of the core new queue |
| `immersion_tags` | `["satori-mining", "shadowing-mining"]` | Priority-ordered tags whose subjects/prerequisites seed the boost (Satori leads Shadowing by default) |
| `immersion_tag` | `satori-mining` | Legacy single-tag fallback when `immersion_tags` is absent |


Create `out/wk_adaptive_new_config.json` (or set `WK_ADAPTIVE_NEW_CONFIG`):

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

---

# WK Immersion (Yomitan mining)

Enriches **WK Yomitan Immersion** notes at mine time (cloze, WK links, hints, SentenceKana) and synthesizes **SentenceAudio** when empty (VOICEVOX / edge-tts). Also still supports legacy **WK Migaku Immersion** notes.

## Install once

Copy `wk_immersion` into Anki's add-ons folder (or run `./scripts/sync_anki_addons.sh`), then restart Anki.

## At mine time

1. Keep **Anki open** — Yomitan sends notes via AnkiConnect.
2. Map pitch + glossary fields in Yomitan (see [docs/yomitan_mining.md](../docs/yomitan_mining.md)).
3. **wk_immersion** enriches cloze/WK fields and fills missing sentence audio.

## Cards

1. **Sentence cloze → word** — progressive hints; type Reading (kana).
2. **Shadow → pitch** — listen and speak; pitch graphs on the back.

## Native clips

```bash
python3 scripts/extract_immersion_clip.py --url '…' --start 1:20 --end 1:24 --selected
```

## Backfill / CLI

- **Tools → WK Enrich Mining Notes (cloze + WK links)**
- **Tools → WK Synthesize Immersion Sentence Audio**
- **Tools → WK Configure Migaku Field Map** (legacy Migaku only)
- `python3 scripts/synthesize_immersion_sentence_audio.py`

Hint stages update on **Tools → WK Run Unlock Pass**.

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

### Immersion-linked core (Satori / Shadowing)

Two summary tables for **WK Core Kanji** and **WK Core Vocabulary** whose
`WkSubjectId` appears on a Satori (`satori-mining`) or Shadowing
(`shadowing-mining`) note — either as `WkSubjectId` or in `PrerequisiteIds`:

| Column | Meaning |
|--------|---------|
| **Locked** | `wk-locked` or all cards suspended |
| **Unseen** | Unlocked, active, **reps = 0** |
| **Reviewed** | Reviewed at least once (apprentice / guru / master) |
| **Total** | Immersion-linked notes of that kind |

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
- Any retired `WK::` filtered decks still present
- `wk_study_priority.json` found on disk

Each run saves `wk_health_snapshot.json` in your Anki profile folder. The next run compares review-card and reps totals to that snapshot — **sharp drops** after re-import may mean scheduling was reset (check `core.bootstrap_scheduling` in config).

## Suggested workflow

1. Run **WK Health Check** before re-import (baseline snapshot).
2. Import `out/wk_all.apkg` with **Update** (not replace).
3. Run **WK Health Check** again — review cards and total reps should not fall sharply.
4. Run **WK Adjust New Limits** — run health check once more; reps/review counts should stay stable (only new-card order / limits change).

