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
- WK::Radicals Preview
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
