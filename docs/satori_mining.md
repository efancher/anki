# Satori Reader immersion mining

Import vocabulary from a **Satori Reader** CSV export into Anki as sentence clozes under **Immersion · Satori**.

Same pedagogy as Migaku mining: blank the target word in context, type it in kanji. **Word English** and **sentence translation** always show on the back.

## Export from Satori

In Satori Reader, export your cards to CSV (includes `CardType`, `Expression`, `Context1`, translations, readings).

## Build the deck (any machine with this repo)

```bash
python3 scripts/import_satori.py /path/to/satori_export.csv
```

Writes `out/wk_satori.apkg` by default.

| Flag | Effect |
|------|--------|
| `-o path.apkg` | Custom output path |
| `--include-ej` | Also import EJ recognition cards (default: **JE only**) |
| `--wk-index path` | Optional `wk_mining_vocab_index.json` for WK linking |

Import the `.apkg` in Anki (**Add** first time only).

**Notes already exist?** Anki will report every note “could not be imported” / skipped — that is normal. Do **not** enable **Update existing notes when first field matches**: the package ships empty **SentenceAudio** fields and would wipe TTS you already generated.

**Import offers to create `WK Satori Immersion+`?** Stop — do not accept it. Anki
forks a note type (appending `+`) when the incoming `.apkg`'s field *order*
differs from your existing note type. Notes stuck under the fork are then skipped
on every future import (Anki dedups by GUID) and go invisible to the gloss
worksheet, audio backfill, and new-card prioritization — you'll see far fewer
sentences than you mined. Refresh templates with
`push_satori_template_ankiconnect.py` instead of importing. If a fork already
exists, consolidate it back (scheduling is preserved):

```bash
python3 scripts/consolidate_satori_note_types_ankiconnect.py --dry-run  # preview
python3 scripts/consolidate_satori_note_types_ankiconnect.py            # migrate
```

then delete the emptied `+` type via **Tools → Manage Note Types → Delete**, and
re-run the audio backfill for the migrated notes.

For template-only upgrades (Easy autoplay / Normal manual, template **v6**), push via AnkiConnect instead:

```bash
python3 scripts/push_satori_template_ankiconnect.py
```

Then (if Normal still autoplays) unwrap existing Normal fields:

```bash
python3 scripts/synthesize_immersion_sentence_audio.py --note-type "WK Satori Immersion"
```

## What you get

| Piece | Role |
|-------|------|
| **Immersion · Satori** | Home deck |
| **WK Satori Immersion** | Cloze + type-in; English always on back |
| Tag `satori-mining` | Marks immersion notes (English hint always on front) |

## Card layout

- **Front:** the `Context1` sentence + English word meaning + `{{type:Reading}}`. The target word is marked in-sentence:
  - **Has kanji** → the kanji stem is **highlighted** (blue), okurigana stays visible. You read the highlighted kanji in context. This works for conjugated verbs/adjectives too, since kanji don't change when a word inflects (e.g. `作る` highlights `作` in `…巣を作りました`).
  - **Hiragana-only** → the whole word is **blanked** (`＿＿＿`); produce it from context + the English hint.
- **Back:** expression + reading, **word English**, full sentence (+ furigana when present), **sentence translation**, Easy audio (autoplay) + Normal (manual)

Changing this layout on existing notes: `ClozeSentence` is a stored field, so run `python3 scripts/push_satori_template_ankiconnect.py` — it pushes the template and recomputes `ClozeSentence` on every live note (re-importing the `.apkg` skips existing notes).

## Sentence audio (VOICEVOX)

Satori’s CSV export has **no audio**. The **wk_immersion** add-on synthesizes:

| Field | Label on card | Speed |
|-------|---------------|-------|
| **SentenceAudio** | Normal | `voicevox_speed_scale` (default `1.0`) — **manual** replay only |
| **SentenceAudioEasy** | Easy | `voicevox_easy_speed_scale` (default `0.75`) — **autoplays** on the back |

1. Sync add-ons and restart Anki: `./scripts/sync_anki_addons.sh`
2. Start **VOICEVOX** — see [voicevox_setup.md](voicevox_setup.md)
3. Push the card template (Easy autoplay only — template **v6**):
   ```bash
   python3 scripts/push_satori_template_ankiconnect.py
   ```
   Do **not** re-import the `.apkg` just to refresh templates — existing notes are skipped, and “Update existing notes” would blank audio.
4. Backfill / unwrap Normal so it stops autoplaying:
   - **Tools → WK Synthesize Immersion Sentence Audio**, or
   - `python3 scripts/synthesize_immersion_sentence_audio.py --note-type "WK Satori Immersion"`
   - Use `--force` to regenerate both Normal and Easy after syncing a TTS fix.

If audio sounds doubled or choppy (`親鳥おやどり…`), an older build was reading furigana brackets. Sync add-ons, restart Anki, then re-synthesize with `--force`.

New Satori notes added through AnkiConnect also get TTS when `on_mine` is enabled (CSV import still needs the backfill step above).

## Satori conjugations

Build **separate** conjugation drills from JE verbs/adjectives in the same CSV (not mixed into WK conjugation packs):

```bash
python3 scripts/import_satori.py /path/to/satori_export.csv --conjugations
```

Writes `out/wk_satori_conjugations.apkg`. Import it, then study directly from
**Immersion · Satori Conjugations**. Lemmas already covered by WK conjugations
are skipped when a WK index/cache is available.

## Gloss worksheet (Cure Dolly–style mapping practice)

Not an Anki card — a practice sheet so you map **Japanese order → sticky English** before looking at fluent English. CHUNK / ROLE / LIT are blanks; Satori’s translation stays on the EN line. Duplicate sentences (same JP mined for different target words) are collapsed.

Anki open with AnkiConnect:

```bash
python3 scripts/satori_gloss_worksheet.py
python3 scripts/satori_gloss_worksheet.py --limit 3
python3 scripts/satori_gloss_worksheet.py --selected
python3 scripts/satori_gloss_worksheet.py --note-id 2031086401000 -o /tmp/gloss.txt
python3 scripts/satori_gloss_worksheet.py -o /tmp/gloss.txt --answers-file /tmp/gloss-answers.txt
python3 scripts/satori_gloss_worksheet.py --no-answers
```

By default the blank worksheets are followed by an **answer key** (heuristic CHUNK/ROLE; LIT is Japanese-order sticky English via MT on each full chunk so particles/engines disambiguate senses — e.g. `空は` → sky-as-for, not empty). Use `--answers-file` for a separate answers-only file, or `--no-answers` to skip.

Generated answers are cached in `.wk_cache/satori_gloss/answers.json`, keyed by sentence + English, so re-runs reuse prior output and skip the MyMemory MT calls. Pass `--refresh-cache` to regenerate (e.g. after tweaking the heuristics) or `--no-cache` to bypass it. The cache auto-invalidates when the answer format version changes.

Ad-hoc (no Anki):

```bash
python3 scripts/satori_gloss_worksheet.py \
  --sentence '落ちる間にひまがたっぷりあってまわりをゆっくりみまわせた' \
  --translation 'There was plenty of time while falling, so I could look around at my leisure.'
```

Fill in:

1. **CHUNK** — space particles / て links / clause boundaries  
2. **ROLE** — Aが, engine, を-car, time, …  
3. **LIT** — Japanese-order sticky English (not fluent EN)  
4. Compare to **EN**, then optionally open the printed ichi.moe link

## Drives core new-card priority

Mined Satori vocab steers **which WK core cards you learn next**. The
**wk_adaptive_new** add-on reads every `satori-mining` note's `WkSubjectId` +
`PrerequisiteIds`, expands the prerequisite tree (vocab → kanji → radicals) over
the core deck graph, and floats those subjects to the **front of the core
new-card queues** (ahead of the JLPT/WK-level baseline). So a word you mine from
Satori — and every kanji/radical it needs — becomes your highest-priority new
cards in **WaniKani Core · Kanji / Vocabulary / Radicals**.

Because `core.suspend_unstarted` keeps subjects you haven't reached in WaniKani
suspended, the add-on also **unsuspends the immersion closure** (mined subjects
+ prerequisites) so they actually enter the new queue instead of only being
reordered among already-unlocked cards. Your per-tier **new/day** limits still
pace how many appear, so this never floods reviews. Like `wk_unlock`, it only
ever unsuspends — it never re-suspends — so the two add-ons don't fight. Toggle
with `immersion_unsuspend` in `out/wk_adaptive_new_config.json`.

This is recomputed live: on collection load, right after you **re-import** the
Satori `.apkg`, and after sync — no generator re-run needed. Toggle the whole
feature with `immersion_priority_enabled` in `out/wk_adaptive_new_config.json`.

To unlock an already-open collection immediately (no restart), run:

```bash
python3 scripts/unlock_satori_closure_ankiconnect.py   # --dry-run to preview
```

## Related

- [migaku_mining.md](migaku_mining.md) — video/browser mining (same Immersion family)
- [shadowing_mining.md](shadowing_mining.md) — shadowmine project → Immersion · Shadowing
- [wk_anki_runbook.md](../wk_anki_runbook.md) — daily queues and unlock
