# Satori Reader immersion mining

Import vocabulary from a **Satori Reader** CSV export into Anki as sentence clozes under **Immersion · Satori**.

Same pedagogy as Migaku mining: blank the target word in context, type it in kanji. **Word English** and **sentence translation** always show on the back.

## One-shot refresh

Live-import cloze notes, rebuild conjugations, push templates, regenerate TTS,
and unlock the immersion closure:

```bash
# Anki open with AnkiConnect; VOICEVOX running
python3 scripts/refresh_satori.py /path/to/satori_export.csv
python3 scripts/refresh_satori.py export.csv --from-anki   # also Shadowing/Yomitan lemmas
```

Useful flags: `--skip-tts`, `--no-force-tts` (fill missing only), `--skip-conjugations`,
`--skip-import-dialogs` (conjugations `.apkg` only), `--write-apkg`, `--skip-unlock`.

## Export from Satori

In Satori Reader, export your cards to CSV (includes `CardType`, `Expression`, `Context1`, translations, readings).

## Import into Anki (recommended)

Anki open with AnkiConnect:

```bash
python3 scripts/import_satori.py /path/to/satori_export.csv
```

Writes notes **directly** into **Immersion · Satori** (`WK Satori Immersion`): adds new cards,
updates existing ones by Satori CardID / DuplicateKey, and **preserves** SentenceAudio /
Target / Reading audio. No File → Import dialog and no `WK Satori Immersion+` forks.

| Flag | Effect |
|------|--------|
| `--apkg` | Also write `out/wk_satori.apkg` (backup / sharing) |
| `--apkg-only` | Package only; do not talk to Anki |
| `--dry-run` | Report adds/updates without writing |
| `--include-ej` | Also import EJ recognition cards (default: **JE only**) |
| `--wk-index path` | Optional `wk_mining_vocab_index.json` for WK linking |
| `-o path.apkg` | Custom `.apkg` path when `--apkg` / `--apkg-only` |

**Gloss worksheet:** unchanged — it already queries `note:"WK Satori Immersion"`. Live
import keeps notes on that type, so new sentences show up in the glossbook after import.

**Still have a `WK Satori Immersion+` / `++` fork from an old `.apkg` import?** Consolidate
(scheduling is preserved), then delete the empty fork types:

```bash
python3 scripts/consolidate_satori_note_types_ankiconnect.py --dry-run
python3 scripts/consolidate_satori_note_types_ankiconnect.py
```

For template-only upgrades, push via AnkiConnect:

```bash
python3 scripts/push_satori_template_ankiconnect.py
```

(Immersion decks use **WK Immersion Audio** options with autoplay off; Easy still autoplays via template JS.)

## What you get

| Piece | Role |
|-------|------|
| **Immersion · Satori** | Home deck |
| **WK Satori Immersion** | Cloze + type-in; English always on back |
| Tag `satori-mining` | Marks immersion notes (English hint always on front) |

## Card layout

- **Front:** the `Context1` sentence + English word meaning + `{{type:Reading}}`. The target word is marked in-sentence:
  - **Has kanji** → the surface form is marked in two tones: **blue** for the lemma core (what your reading answers), **purple dashed** for conjugated endings (e.g. `青` + `くて`; `やって来` + `ました`). Type the dictionary reading (`あおい`, `やってくる`).
  - **Hiragana-only** → the whole word is **blanked** (`＿＿＿`); produce it from context + the English hint.
- **Back:** expression + reading, **word English**, **Target** audio button (surface span via Voicevox), full sentence (+ furigana when present), **sentence translation**, Easy audio (autoplay) + Normal (manual)

Changing this layout on existing notes: `ClozeSentence` is a stored field, so run `python3 scripts/push_satori_template_ankiconnect.py` — it pushes the template and recomputes `ClozeSentence` on every live note (re-importing the `.apkg` skips existing notes). For Shadowing notes:

```bash
python3 scripts/push_satori_template_ankiconnect.py --cloze-only --model "WK Shadowing Immersion"
python3 scripts/push_satori_template_ankiconnect.py --cloze-only --model "WK Shadowing Candidate"
```

## Sentence audio (VOICEVOX)

Satori’s CSV export has **no audio**. The **wk_immersion** add-on synthesizes:

| Field | Label on card | Speed |
|-------|---------------|-------|
| **SentenceAudio** | Normal | `voicevox_speed_scale` (default `1.0`) — **manual** replay only |
| **SentenceAudioEasy** | Easy | `voicevox_easy_speed_scale` (default `0.75`) — **autoplays** on the back |

1. Sync add-ons and restart Anki: `./scripts/sync_anki_addons.sh`
2. Start **VOICEVOX** — see [voicevox_setup.md](voicevox_setup.md)
3. Push templates + wrap bare audio as `[sound:]` + assign **WK Immersion Audio** (autoplay off; Easy autoplays via JS):
   ```bash
   python3 scripts/push_satori_template_ankiconnect.py
   ```
   Do **not** re-import the `.apkg` just to refresh templates — existing notes are skipped, and “Update existing notes” would blank audio.
4. Backfill audio if needed:
   - **Tools → WK Synthesize Immersion Sentence Audio**, or
   - `python3 scripts/synthesize_immersion_sentence_audio.py --note-type "WK Satori Immersion"`
   - Use `--force` to regenerate both Normal and Easy after syncing a TTS fix.

If audio sounds doubled or choppy (`親鳥おやどり…`), an older build was reading furigana brackets. Sync add-ons, restart Anki, then re-synthesize with `--force`.

New Satori notes added through AnkiConnect (live import or Migaku mine) also get TTS when
`on_mine` is enabled. After a live CSV import, run synthesize (or `refresh_satori.py`) if
audio fields are still empty.

## Immersion conjugations

Drive verb/adjective conjugation drills from **immersion lemmas** (Satori CSV
and/or live Anki notes tagged `satori-mining`, `shadowing-mining`,
`yomitan-mining`). Part of speech comes from Satori CSV fields, WK vocab POS
when `WkSubjectId` links, then an offline **JMDict** index
(`out/jmdict-eng.json` / `out/jmdict_pos_index.json`, auto-downloaded on first
build).

```bash
# Satori CSV only
python3 scripts/import_immersion_conjugations.py --satori /path/to/satori_export.csv

# Live Anki immersion notes (requires AnkiConnect)
python3 scripts/import_immersion_conjugations.py --from-anki

# Both
python3 scripts/import_immersion_conjugations.py --satori export.csv --from-anki
```

Writes `out/wk_immersion_conjugations.apkg`. Import it, then study from
**Immersion · Conjugations**.

Forms are the full set (polite/plain, past, negatives, te, potential, passive,
causative, 〜ば / 〜たら). Trim via `conjugation_forms` in
`wk_deck_config.json`. WK conjugation packs are no longer in the default
`generate_decks` list.

Legacy Satori-only builder still works:

```bash
python3 scripts/import_satori.py /path/to/satori_export.csv --conjugations
```

## Pitch accent (Satori / Shadowing)

Immersion notes include `PitchAccents` / `PitchPositions` / `PitchGraphs`. Yomitan mining
fills these when Kanjium is installed in Yomitan. **Satori CSV** and **Shadowing** imports
fill them from the same Kanjium zip (auto-detected under `~/Downloads/kanjium_pitch_accents.zip`,
or pass `--pitch-dict` / set `WK_PITCH_DICT`).

Backfill existing notes (Anki open):

```bash
python3 scripts/backfill_immersion_pitch_ankiconnect.py
python3 scripts/push_satori_template_ankiconnect.py
python3 scripts/push_satori_template_ankiconnect.py --model "WK Shadowing Immersion"
```

**VOICEVOX:** Target/Reading TTS uses `PitchPositions` when present (dictionary form). Regenerate with:

```bash
python3 scripts/synthesize_immersion_sentence_audio.py --surface-only --force
```

Full-sentence Easy/Normal audio still uses VOICEVOX’s default accent (multi-word alignment is harder).

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
