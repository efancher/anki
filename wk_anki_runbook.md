# WaniKani → Anki Deck Generator Runbook

This runbook is for `wk_decks.py`, a multi-deck generator that creates update-safe Anki `.apkg` files from your WaniKani account.

## What it generates

1. **WaniKani Leech Fixes** — items you repeatedly miss, using WaniKani review statistics.
2. **WaniKani Verb Pair Contrasts** — pairs like `上がる / 上げる`, `下がる / 下げる`, `閉まる / 閉める`.
3. **WaniKani Confusable Vocabulary** — vocabulary groups sharing kanji or reading cues.
4. **WaniKani Phonetic Families** — Keisei phonetic components → usual on'yomi + WK family kanji (skipped when no family has enough started kanji).
5. **WaniKani Pitch Leeches** — leech items with pitch accent data, if pitch data is supplied.
6. **WaniKani Current and Next Radicals** — radicals from your current and next WaniKani level.
7. **WaniKani Reading Keywords** — high-confidence WK mnemonic phonetic keywords (e.g. `き` → key).
8. **WaniKani Kanji Radical Breakdown** — kanji ↔ radical parts + meaning mnemonic.

**Recommended import:** one bundled file, `out/wk_all.apkg`, updates every deck in a single Anki import. Individual `.apkg` files are also written for one-off use.

## One-time setup

```bash
mkdir wk-anki
cd wk-anki

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install requests genanki
```

Save `wk_decks.py` in this folder.

Create a WaniKani API token from your WaniKani account settings, then:

```bash
export WANIKANI_API_TOKEN="your_token_here"
```

On macOS, to avoid re-exporting each time:

```bash
echo 'export WANIKANI_API_TOKEN="your_token_here"' >> ~/.zshrc
source ~/.zshrc
```

## Verify script version

Before generating decks, confirm you are running the current script:

```bash
python wk_decks.py --version
```

Expected:

```text
wk_decks.py v2.12.1 (2026-06-11)
```

A normal run should also print a startup banner with the same version.

## Recommended first run

Start with items you have actually started in WaniKani:

```bash
python wk_decks.py --deck all --only-started
```

The output appears in:

```text
out/
  wk_all.apkg                    ← import this (all decks in one file)
  wk_run_history.csv             ← appended each run (counts + bundle contents)
  anki_import_instructions.txt
  anki_filtered_decks.json
  wk_leeches.apkg                ← individual decks (optional)
  wk_verb_pairs.apkg
  wk_confusables.apkg
  wk_phonetic_families.apkg      ← only when phonetic families qualify
  wk_pitch_leeches.apkg
  wk_radicals_current_next.apkg
  wk_reading_keywords.apkg
  wk_kanji_radicals.apkg
```

Import **`out/wk_all.apkg`** into Anki. When Anki asks about existing note types, choose **Update** (or **Always update** if templates look stale). Do not choose **Create new note type**.

See `out/anki_import_instructions.txt` for current template versions and verification steps.

## Recommended weekly update

Once a week:

```bash
source venv/bin/activate
python wk_decks.py --deck all --only-started
```

Then import **`out/wk_all.apkg`** into Anki (note type **Update**).

The script syncs WaniKani cache incrementally on every run (`updated_after` when a prior cache exists). Each run appends one row to `out/wk_run_history.csv` with deck counts and which decks were bundled — use this to confirm progress before importing.

Preview without writing `.apkg` files:

```bash
python wk_decks.py --deck all --only-started --dry-run
```

The script uses stable note GUIDs. Regenerated notes should update existing notes rather than create duplicates, as long as you do not change the script's model IDs, field order, deck names, or GUID logic.

### Verifying updates

1. **Before import** — compare the latest `wk_run_history.csv` row to the previous row (counts should shift as you unlock WK content).
2. **Check `bundled_decks`** — lists decks actually in `wk_all.apkg`. If `phonetic_families` is `0`, phonetics is not in the bundle.
3. **After import** — Browse a deck and compare note count to the generator summary (e.g. `Kanji radical breakdown: 200`).
4. **Template check** — open a leech card back; meta line should show the current template version from `anki_import_instructions.txt`.

Re-importing `wk_all.apkg` adds new decks when they first qualify and updates existing notes. It does not remove cards that left a deck (e.g. leech fixed). Importing a standalone `.apkg` is only needed if that deck was skipped from `wk_all` at build time.

## Conservative mode

If you want fewer cards:

```bash
python wk_decks.py --deck all --only-started --min-srs 5 --max-cards 100
```

`--min-srs 5` roughly means Guru+.

## Leech-only mode

```bash
python wk_decks.py --deck leeches --only-started
```

Stricter leech threshold:

```bash
python wk_decks.py --deck leeches --only-started \
  --leech-incorrect-min 12 \
  --leech-streak-max 1
```

Looser threshold:

```bash
python wk_decks.py --deck leeches --only-started \
  --leech-incorrect-min 5 \
  --leech-streak-max 3
```

## Verb pairs only

```bash
python wk_decks.py --deck verb-pairs --only-started
```

This is the best deck for problems like:

```text
上がる vs 上げる
下がる vs 下げる
始まる vs 始める
閉まる vs 閉める
```

## Confusables only

```bash
python wk_decks.py --deck confusables --only-started
```

If groups are too large:

```bash
python wk_decks.py --deck confusables --only-started \
  --max-confusable-group-size 4
```

## Phonetic families only

Uses the [Keisei phonetic DB](https://github.com/mwil/wanikani-userscripts) (auto-downloaded to `.wk_cache/keisei/` on first run). One card per phonetic component:

- **Front:** phonetic piece (e.g. 化) — what on'yomi does it signal?
- **Back:** Keisei usual readings + WK family kanji with meanings

Families need at least `--min-family-size` started kanji in the same Keisei family (default 3). Early WK progress may produce **zero** families until more kanji unlock.

```bash
python wk_decks.py --deck phonetic-families --only-started
```

If you want partial families sooner:

```bash
python wk_decks.py --deck phonetic-families --only-started --min-family-size 2
```

If phonetics is missing from `wk_all.apkg`, check `phonetic_families` in `wk_run_history.csv` or import `wk_phonetic_families.apkg` separately.

## Cache behavior

The script caches WaniKani data in:

```text
.wk_cache/
  user.json
  subjects_vocabulary_kanji_radical.json
  assignments_*.json
  review_statistics_*.json
  study_materials.json
  keisei/                         ← Keisei phonetic JSON (auto-downloaded)
```

After the first full download, each run syncs assignments, subjects, and review statistics with `updated_after` (not only when the cache is older than 24 hours).

To force fresh WaniKani and Keisei data:

```bash
python wk_decks.py --deck all --only-started --refresh-cache
```

## Pitch accent integration

WaniKani does not provide pitch accent through its API. You have three practical options.

### Option A: No pitch data

```bash
python wk_decks.py --deck all --only-started
```

Pitch fields will be blank.

### Option B: Simple CSV

Generate a blank pitch template from your eligible WaniKani vocabulary:

```bash
python wk_decks.py --only-started --write-pitch-template pitch_template.csv
```

This creates:

```csv
expression,reading,pitch,pattern
上がる,あがる,,
上げる,あげる,,
```

Fill in pitch only for words you care about:

```csv
expression,reading,pitch,pattern
上がる,あがる,あがるꜜ,nakadaka
上げる,あげる,あげꜜる,nakadaka
```

Then run:

```bash
python wk_decks.py --deck all --only-started --pitch-csv pitch_template.csv
```

### Option C: Yomitan pitch dictionary

This is the better long-term option.

1. Install Yomitan in your browser.
2. Find a Yomitan-format pitch accent dictionary, commonly Kanjium pitch accents or another community pitch dictionary.
3. Keep the `.zip` file locally.

Example folder:

```bash
mkdir -p ~/japanese-dicts
```

Put the pitch dictionary zip there, for example:

```text
~/japanese-dicts/kanjium_pitch_accents.zip
```

Then run:

```bash
python wk_decks.py --deck all --only-started \
  --yomitan-dict ~/japanese-dicts/kanjium_pitch_accents.zip
```

You can also pass an extracted dictionary folder:

```bash
python wk_decks.py --deck all --only-started \
  --yomitan-dict ~/japanese-dicts/kanjium_pitch_accents/
```

Recommended pitch-specific run:

```bash
python wk_decks.py --deck pitch-leeches --only-started \
  --yomitan-dict ~/japanese-dicts/kanjium_pitch_accents.zip
```

## Changing computers

To avoid breaking update behavior:

1. Sync AnkiWeb on the old computer.
2. Install Anki and sync the same Anki profile on the new computer.
3. Copy or git-clone the exact same `wk_decks.py`.
4. Copy your pitch CSV or pitch dictionary zip if you use one.
5. `.wk_cache/` is optional; copying it avoids re-downloading but is not required. Keisei phonetic JSON is re-downloaded automatically if missing.

Recommended:

```bash
git init
git add wk_decks.py wk_anki_runbook.md pitch_template.csv
git commit -m "WaniKani Anki generator"
```

Do not edit these unless intentionally making a new deck/model:

```text
DECK_IDS
MODEL_IDS
DECK_NAMES
field order in the model definitions
stable_guid()
```

## Recommended personal workflow

For your use case, start with:

```bash
python wk_decks.py --deck all --only-started --min-srs 3 --max-cards 150
```

If it feels like too many cards:

```bash
python wk_decks.py --deck all --only-started --min-srs 5 --max-cards 100
```

If you want only high-value fixes:

```bash
python wk_decks.py --deck leeches --only-started
python wk_decks.py --deck verb-pairs --only-started --min-srs 3
```

## Troubleshooting

### `RuntimeError: Set WANIKANI_API_TOKEN first.`

Run:

```bash
export WANIKANI_API_TOKEN="your_token_here"
```

### `ModuleNotFoundError: No module named 'genanki'`

Run:

```bash
pip install genanki requests
```

### No decks created

Try relaxing filters:

```bash
python wk_decks.py --deck all --only-started --min-srs 1 --max-cards 300
```

Or refresh cache:

```bash
python wk_decks.py --deck all --only-started --refresh-cache
```

### Duplicate notes appear in Anki

Usually this means the script's GUID/model constants changed, you imported into a different Anki profile, or you chose **Create new note type** on import. Use stable note type names (`WK Update-Safe Item`, etc.) and **Update** on re-import.

### Phonetic families missing after importing wk_all.apkg

Check `phonetic_families` in `wk_run_history.csv`. If it is `0`, the deck was not built (not an Anki import issue). Import `wk_phonetic_families.apkg` separately after families qualify, or lower `--min-family-size`.


## v2.12.1 — Keisei phonetic families, run history, bundled import

### Phonetic families (Keisei-backed)

Replaces the old substring heuristic (which often produced zero families). Uses Keisei `phonetic_esc.json` + your eligible WK kanji. GPL-3.0 data from mwil/wanikani-userscripts; auto-downloaded to `.wk_cache/keisei/`.

### Run history CSV

Each run appends a row to `out/wk_run_history.csv`:

- WK level, filter flags, per-deck counts
- `bundled_in_wk_all` and `bundled_decks` (what is actually in `wk_all.apkg`)

Dry-runs also append a row (`dry_run=1`).

### Bundled import

`out/wk_all.apkg` is the recommended weekly import. Only decks with notes are included; empty decks (e.g. phonetics at low WK level) are omitted from the bundle.


## v2.4.1 note

Confusable-family card fronts now show the vocabulary items and readings, not just the shared kanji. This makes the prompt useful for active comparison while keeping meanings/explanations on the back.

## v2.4.1 implemented changes

The front now shows only the two written forms and readings, plus a prompt to explain the relationship. Meanings, WaniKani level, SRS, leech information, relationship labels, verb-type notes, and examples are on the back.

### Relationship labels

The script now attempts to label contrast pairs as:

- `INTRANSITIVE ↔ TRANSITIVE`
- `BASE ↔ CAUSATIVE / CAUSATIVE-LIKE`
- `BASE ↔ POTENTIAL / PERCEPTION`
- `MOVE ↔ CAUSE TO MOVE`
- `RELATED VERB CONTRAST`

These are learner-facing labels, not formal dictionary classifications.

### Verb type metadata

The back of contrast cards now includes a best-effort verb type:

- `Likely Godan`
- `Likely Ichidan`
- `Irregular`

This is intentionally metadata, not a separate drill deck.

### Example sentences

Curated examples are included for common pairs such as:

- `上がる / 上げる`
- `下がる / 下げる`
- `見る / 見せる`
- `聞く / 聞こえる`
- `出る / 出す`
- `入る / 入れる`

Pairs without curated examples still generate normally.

## Future enhancements

### High value

- Add more curated contrast groups:
  - `上がる / 上げる / 上る / 登る / 昇る`
  - `見る / 見える / 見せる`
  - `聞く / 聞こえる / 聞かせる`
- Improve leech scoring using error rate and recency instead of simple thresholds.
- Add a preview/report mode that lists generated groups before creating decks.
- Add a local `custom_pairs.csv` so new contrast pairs can be added without editing Python.

### Medium value

- Yomitan pitch dictionary integration for leeches and confusables.
- Frequency data from a local frequency dictionary.

### Probably not worth it yet

- A dedicated Godan/Ichidan deck.
- A giant pitch-only deck.
- A duplicate general vocabulary deck.


## v2.4.1 styling update

Kana/readings are now brighter for Anki dark mode/night mode.

Changed:
- `.reading`
- `.front-reading`
- dark-mode overrides for reading, meaning, metadata, and relationship prompts

This is a styling-only update. Deck IDs, model IDs, and note GUID logic are unchanged.


## v2.4.1 priority tags and filtered decks

The generator now tags notes with:

```text
priority-high
priority-medium
priority-low
```

### Suggested filtered deck: WK Daily Priority

Create a filtered deck in Anki with this search:

```text
(tag:priority-high) AND (deck:"WaniKani Leech Fixes" OR deck:"WaniKani Verb Pair Contrasts")
```

Limit: `30`

Order: `Relative overdueness`

### Suggested filtered deck: WK Verb Contrasts

```text
deck:"WaniKani Verb Pair Contrasts" AND (tag:priority-high OR tag:priority-medium)
```

Limit: `30`

### Suggested filtered deck: WK Leeches

```text
deck:"WaniKani Leech Fixes"
```

Limit: `50`

### Suggested filtered deck: WK Confusables Light

```text
deck:"WaniKani Confusable Vocabulary" AND tag:priority-high
```

Limit: `20`

### How filtered decks behave

Reviews in filtered decks update the original cards' scheduling, ease, intervals, and review history.

After regenerating and importing decks, click **Rebuild** on the filtered deck so Anki reruns the search.

The script also writes:

```text
out/anki_filtered_decks.txt
```

with these suggestions.


## v2.4.1 radical preview deck

The generator now creates:

```text
out/wk_radicals_current_next.apkg
```

Deck name in Anki:

```text
WaniKani Current and Next Radicals
```

It includes radicals from:

- your detected current WaniKani level
- the next WaniKani level

Each radical card includes:

- radical form or slug
- WaniKani meaning
- current/next level status
- preview kanji that use the radical, when available in cached subjects

### Run all decks

```bash
python wk_decks.py --deck all --only-started --min-srs 3 --max-cards 150
```

### Run radicals only

```bash
python wk_decks.py --deck radicals
```

### Override current level

If the detected level seems wrong:

```bash
python wk_decks.py --deck radicals --radical-current-level 12
```

This will generate level 12 and level 13 radicals.

### Suggested filtered deck

```text
deck:"WaniKani Current and Next Radicals"
```

Limit: `20`

Order: `Relative overdueness`


## v2.4.1 bug fix

Fixes a `NameError: review_index is not defined` crash when generating leech cards with priority tags.


## v2.6.0 improvements

### WaniKani-style leech cards

Leech items now generate separate **Meaning** and **Reading** cards:

- Front: kanji or vocabulary only
- Back: meaning or reading, plus the relevant mnemonic and stats

Reading cards for vocabulary also include WaniKani context sentences when available.

### Smarter leech scoring

Leeches are ranked by a composite score using:

- total meaning/reading misses
- WaniKani `percentage_correct`
- current streak (lower streak = higher priority)
- recency of last review (`updated_at`)

Tune with:

```bash
python wk_decks.py --deck leeches --only-started --leech-score-min 2.5
```

The default `--leech-score-min 1.0` keeps behavior close to earlier versions while improving sort order.

### Meaning vs reading weakness tags

Notes are tagged when one review side is clearly weaker:

- `leech-meaning`
- `leech-reading`

Suggested filtered decks:

```text
deck:"WaniKani Leech Fixes" AND tag:leech-meaning
deck:"WaniKani Leech Fixes" AND tag:leech-reading
```

Weak-side cards also show a small front hint: "Meaning side needs work" or "Reading side needs work".

### Preview mode

List what would be generated without writing `.apkg` files:

```bash
python wk_decks.py --deck all --only-started --dry-run
```

Use this to tune `--max-cards`, `--leech-incorrect-min`, and `--leech-score-min` before importing.


## v2.7.0 API improvements

### Incremental sync

User-specific collections now cache as:

```json
{
  "synced_at": "2026-06-11T12:00:00Z",
  "items": [ ... ]
}
```

After the cache age expires (24 hours by default), the script fetches only records changed since `synced_at` using the API's `updated_after` filter, then merges them into the local cache. As of v2.11+, assignments, subjects, and review statistics sync on **every run** when a prior cache exists (not only after 24 hours).

Use `--refresh-cache` when you want a full re-download instead of an incremental update.

### Server-side assignment filtering

Assignment downloads now honor your CLI filters on the API side:

- `--only-started` → `started=true`
- `--only-unlocked` → `unlocked=true`
- `--only-burned` → `burned=true`
- `--min-srs` → `srs_stages=...`
- `--max-level` → `levels=...`

Review statistics are fetched in batches for the filtered assignment subject IDs, so weekly runs transfer much less data.

### Current level from `/user`

Radical preview levels now come from `GET /user` (`data.level`) instead of inferring level from unlocked assignments.

You can still override with `--radical-current-level`.

### WaniKani-native confusables

Confusable vocabulary groups now use WaniKani's `component_subject_ids` when available, with the previous shared-kanji-string grouping kept as a fallback.

### Cache note after upgrading

The first run after upgrading may re-download assignments/review statistics because cache filenames now include your filter settings (for example `assignments_started_true_srs_stages_1-9_...json`). This is expected once.
