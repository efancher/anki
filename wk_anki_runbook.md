# WaniKani → Anki Deck Generator Runbook

This runbook is for `wk_decks.py`, a multi-deck generator that creates update-safe Anki `.apkg` files from your WaniKani account.

## What it generates

1. **WaniKani Leech Fixes** — items you repeatedly miss, using WaniKani review statistics.
2. **WaniKani Verb Pair Contrasts** — pairs like `上がる / 上げる`, `下がる / 下げる`, `閉まる / 閉める`.
3. **WaniKani Confusable Vocabulary** — vocabulary groups sharing kanji or reading cues.
4. **WaniKani Phonetic Families** — kanji grouped by likely phonetic components and shared on'yomi.
5. **WaniKani Pitch Leeches** — leech items with pitch accent data, if pitch data is supplied.

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
python wk_decks_v2_2_0_real.py --version
```

Expected:

```text
wk_decks.py v2.2.0 (2026-06-09)
```

A normal run should also print a startup banner with the same version.

## Recommended first run

Start with items you have actually started in WaniKani:

```bash
python wk_decks_v2_2_0_real.py --deck all --only-started
```

The output appears in:

```text
out/
  wk_leeches.apkg
  wk_verb_pairs.apkg
  wk_confusables.apkg
  wk_phonetic_families.apkg
  wk_pitch_leeches.apkg
```

Import each `.apkg` into Anki.

## Recommended weekly update

Once a week:

```bash
source venv/bin/activate
python wk_decks_v2_2_0_real.py --deck all --only-started
```

Then import the regenerated `.apkg` files into Anki.

The script uses stable note GUIDs. Regenerated notes should update existing notes rather than create duplicates, as long as you do not change the script's model IDs, field order, deck names, or GUID logic.

## Conservative mode

If you want fewer cards:

```bash
python wk_decks_v2_2_0_real.py --deck all --only-started --min-srs 5 --max-cards 100
```

`--min-srs 5` roughly means Guru+.

## Leech-only mode

```bash
python wk_decks_v2_2_0_real.py --deck leeches --only-started
```

Stricter leech threshold:

```bash
python wk_decks_v2_2_0_real.py --deck leeches --only-started \
  --leech-incorrect-min 12 \
  --leech-streak-max 1
```

Looser threshold:

```bash
python wk_decks_v2_2_0_real.py --deck leeches --only-started \
  --leech-incorrect-min 5 \
  --leech-streak-max 3
```

## Verb pairs only

```bash
python wk_decks_v2_2_0_real.py --deck verb-pairs --only-started
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
python wk_decks_v2_2_0_real.py --deck confusables --only-started
```

If groups are too large:

```bash
python wk_decks_v2_2_0_real.py --deck confusables --only-started \
  --max-confusable-group-size 4
```

## Phonetic families only

```bash
python wk_decks_v2_2_0_real.py --deck phonetic-families --only-started --min-srs 5
```

If you want only stronger patterns:

```bash
python wk_decks_v2_2_0_real.py --deck phonetic-families --only-started \
  --min-family-size 4
```

## Cache behavior

The script caches WaniKani data in:

```text
.wk_cache/
```

It caches:

```text
subjects_vocabulary_kanji.json
assignments_all.json
review_statistics_all.json
study_materials_all.json
```

To force fresh WaniKani data:

```bash
python wk_decks_v2_2_0_real.py --deck all --only-started --refresh-cache
```

## Pitch accent integration

WaniKani does not provide pitch accent through its API. You have three practical options.

### Option A: No pitch data

```bash
python wk_decks_v2_2_0_real.py --deck all --only-started
```

Pitch fields will be blank.

### Option B: Simple CSV

Generate a blank pitch template from your eligible WaniKani vocabulary:

```bash
python wk_decks_v2_2_0_real.py --only-started --write-pitch-template pitch_template.csv
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
python wk_decks_v2_2_0_real.py --deck all --only-started --pitch-csv pitch_template.csv
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
python wk_decks_v2_2_0_real.py --deck all --only-started \
  --yomitan-dict ~/japanese-dicts/kanjium_pitch_accents.zip
```

You can also pass an extracted dictionary folder:

```bash
python wk_decks_v2_2_0_real.py --deck all --only-started \
  --yomitan-dict ~/japanese-dicts/kanjium_pitch_accents/
```

Recommended pitch-specific run:

```bash
python wk_decks_v2_2_0_real.py --deck pitch-leeches --only-started \
  --yomitan-dict ~/japanese-dicts/kanjium_pitch_accents.zip
```

## Changing computers

To avoid breaking update behavior:

1. Sync AnkiWeb on the old computer.
2. Install Anki and sync the same Anki profile on the new computer.
3. Copy or git-clone the exact same `wk_decks.py`.
4. Copy your pitch CSV or pitch dictionary zip if you use one.
5. `.wk_cache/` is optional; copying it avoids re-downloading but is not required.

Recommended:

```bash
git init
git add wk_decks.py pitch_template.csv
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
python wk_decks_v2_2_0_real.py --deck all --only-started --min-srs 3 --max-cards 150
```

If it feels like too many cards:

```bash
python wk_decks_v2_2_0_real.py --deck all --only-started --min-srs 5 --max-cards 100
```

If you want only high-value fixes:

```bash
python wk_decks_v2_2_0_real.py --deck leeches --only-started
python wk_decks_v2_2_0_real.py --deck verb-pairs --only-started --min-srs 3
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
python wk_decks_v2_2_0_real.py --deck all --only-started --min-srs 1 --max-cards 300
```

Or refresh cache:

```bash
python wk_decks_v2_2_0_real.py --deck all --only-started --refresh-cache
```

### Duplicate notes appear in Anki

Usually this means the script's GUID/model constants changed, or you imported into a different Anki profile.

Use the same script, same profile, and same deck/model constants.


## v2.2.0 note

Confusable-family card fronts now show the vocabulary items and readings, not just the shared kanji. This makes the prompt useful for active comparison while keeping meanings/explanations on the back.


## v2.2.0 implemented changes

### Verb contrast cards are less revealing

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
- Better phonetic-family generation using a real component table.

### Probably not worth it yet

- A dedicated Godan/Ichidan deck.
- A giant pitch-only deck.
- A duplicate general vocabulary deck.
