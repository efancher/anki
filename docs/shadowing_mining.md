# Shadowing project → Anki cloze import

Import Japanese video sentences into Anki as:

1. **Immersion · Shadowing** — one cloze card per **selected** (or auto-matched) **WaniKani vocabulary** word (native clip audio).
2. **Immersion · Shadowing Candidates** — **non-WK** content words for optional study (no fake WK IDs).

**Preferred path:** export the video with Shadowmine v2 (UniDic tokens) → review vocabulary in **Glossbook** → export a `.mining.zip` → import that ZIP here. Cards then follow your confirmed selections only (no `担任` → `担ぐ` false matches).

**Legacy path:** import a shadowmine project directory and let Anki auto-match WK vocabulary (still useful, but noisier).

Matched WK subjects also seed **core new-card priority** via the `shadowing-mining` tag.

Also see the short pointer in [wk_anki_runbook.md](../wk_anki_runbook.md) (§8 Topic guides).

---

## Correct workflow (checklist)

Do these in order. Anki should be **closed** for steps that write `.apkg` only; **open with AnkiConnect** for template / TTS / restore scripts.

### 1. Finish the shadowmine project and export a v2 package

```bash
# In ~/shadowing — mine/correct sentences, then export.
# Package v2 includes UniDic token spans for Glossbook's vocabulary picker.
shadowmine export ~/shadowing/cli/projects/VIDEO_ID
# → VIDEO_ID.shadowing.zip
```

### 2. Review vocabulary in Glossbook

1. Import the `.shadowing.zip` into [Satori Glossbook](https://github.com/efancher/jp_sentence_splits) (`jp_sentence_splits`).
2. Open each sentence on **Analyze**.
3. Suggestions start selected — uncheck false matches, combine adjacent tokens (e.g. やって + 来ました → やって来る), edit dictionary forms.
4. Click **Confirm vocabulary and next**.
5. On the book page: **Export Anki mining package** → `*.mining.zip`.

Unconfirmed sentences are omitted from the mining ZIP.

### 3. Ensure the WK vocab index exists

```bash
cd /path/to/anki   # this repo
python3 wk_decks.py --from-config   # or any generate that writes the mining index
ls out/wk_mining_vocab_index.json
```

### 4. Build Anki packages from the mining ZIP (preferred)

```bash
cd /path/to/anki
python3 scripts/import_shadowing.py ~/Downloads/VIDEO.mining.zip
```

Pitch accents (`PitchAccents` / graphs) are filled from Kanjium when available (auto-detect
`~/Downloads/kanjium_pitch_accents.zip`, or `--pitch-dict` / `WK_PITCH_DICT`). **WK Shadowing
Immersion** cards get pitch; candidate cards do not. To backfill existing notes:

```bash
python3 scripts/backfill_immersion_pitch_ankiconnect.py
python3 scripts/push_satori_template_ankiconnect.py --model "WK Shadowing Immersion"
```

### Legacy: build from a project directory (automatic matching)

Use the **shadowing CLI venv** so morphology matching works:

```bash
SHADOW_PY="${HOME}/shadowing/cli/.venv/bin/python"
"$SHADOW_PY" scripts/import_shadowing.py ~/shadowing/cli/projects/VIDEO_ID
# optional:
"$SHADOW_PY" scripts/import_shadowing.py ~/shadowing/cli/projects/VIDEO_ID --skip-auto-caption
```

Writes:

| File | Contents |
|------|----------|
| `out/wk_shadowing.apkg` | WK-linked sentence clozes (`WK Shadowing Immersion`) |
| `out/wk_shadowing_candidates.apkg` | Non-WK candidate clozes (`WK Shadowing Candidate`) |

### 5. Import into Anki

1. File → Import both `.apkg` files.
2. Allow **note type** updates if prompted.
3. Do **not** enable **Update existing notes when first field matches** just to refresh templates or re-import — the package can blank / overwrite media fields.
4. New notes only: fine. Existing notes: use the maintenance commands below instead of “update notes”.

### 6. After import (priority + optional Target TTS)

```bash
# In Anki: Tools → WK Adjust New Limits
# (or restart Anki so adaptive-new picks up shadowing-mining tags)

# Optional: Voicevox for Target (surface) + Reading (kana) buttons only.
# Never use plain --force on Shadowing note types for sentence audio.
python3 scripts/synthesize_immersion_sentence_audio.py \
  --surface-only --note-type "WK Shadowing Immersion"
python3 scripts/synthesize_immersion_sentence_audio.py \
  --surface-only --note-type "WK Shadowing Candidate"
```

`SentenceAudio` must stay the native `wk_shadowing_*.m4a` clip. Immersion TTS now **skips** Shadowing sentence fields even under `--force`; still prefer `--surface-only` so intent is obvious.

---

## Card policy

| Kind | Behavior |
|------|----------|
| WK cloze | One note per `(sentence × selected/matched WK subject)`. Same native clip; different cloze target. |
| Curated selections | Glossbook `.mining.zip` is authoritative — Anki does **not** run kanji-stem auto-match on those sentences. Exact WK lookup by expression/reading; otherwise a Candidate card. |
| Cloze style | Highlight/blank the **surface span** in the sentence; type the **dictionary reading** (e.g. 使う → つかう even when the sentence has 使って). |
| Conjugated-only lemmas | A lemma that never appears in dictionary form is still located by conjugating it (する → しました, できる → できませんでした, すごい → すごく, 来る → きました, わし → ワシ). A kana surface right after kanji is skipped, so する does not claim the しました of 電話しました. |
| English | Front hint: `WkMeaning` → `HintGlossary` → sentence `Translation`. Candidates often only have sentence English. |
| Audio | Native clip in `SentenceAudio` (autoplays via template JS). Optional Voicevox **Target** / **Reading** are Anki `[sound:]` replay buttons — they never replace the sentence clip. |
| Sentence furigana | Built from the project’s kana `reading` into Anki `漢字[かんじ]` markup (`SentenceFurigana`). Backfills: `scripts/backfill_shadowing_furigana_ankiconnect.py`. |
| Priority tag | `shadowing-mining` (seeds `wk_adaptive_new`) |
| Candidates | Non-WK content words only. Tag `shadowing-candidate` does **not** seed core priority. Prefer studying the WK cloze when both exist (e.g. 敬語 / 使う, not a glued `敬語使`). |

Auto-caption sentences import by default (`shadowing-auto-caption`). Pass `--skip-auto-caption` to omit them.

---

## Maintenance (Anki open + AnkiConnect)

### Push templates / CSS

```bash
python3 scripts/push_satori_template_ankiconnect.py \
  --model "WK Shadowing Immersion" --no-refresh-cloze
python3 scripts/push_satori_template_ankiconnect.py \
  --model "WK Shadowing Candidate" --no-refresh-cloze
```

### Recompute cloze HTML on live notes

`ClozeSentence` is a stored field — template pushes alone do not fix blanks/highlights.

```bash
python3 scripts/push_satori_template_ankiconnect.py \
  --cloze-only --model "WK Shadowing Immersion"
python3 scripts/push_satori_template_ankiconnect.py \
  --cloze-only --model "WK Shadowing Candidate"
```

### Restore native sentence audio

If Voicevox / an old `--force` pass replaced clips with `wk_immersion_sent_*.wav`:

```bash
python3 scripts/restore_shadowing_native_audio.py
# dry-run first:
python3 scripts/restore_shadowing_native_audio.py --dry-run
# limit to one note type:
python3 scripts/restore_shadowing_native_audio.py --note-type "WK Shadowing Candidate"
```

Looks up `wk_shadowing_{source}_{sentence}.*` in Anki media (and can re-copy from `~/shadowing/cli/projects` when missing). Clears `SentenceAudioEasy`.

### Backfill sentence furigana

Older imports left `SentenceFurigana` empty even when the project had a kana `reading`.

```bash
python3 scripts/backfill_shadowing_furigana_ankiconnect.py \
  ~/shadowing/cli/projects/FkX4A-ZLBrc
# or all projects under a parent:
python3 scripts/backfill_shadowing_furigana_ankiconnect.py ~/shadowing/cli/projects
```

### Delete a bad candidate

Browse → `note:"WK Shadowing Candidate"` → delete notes whose Expression looks mid-cut (e.g. ends before っ of a te-form) or whose Reading ends in っ. Re-import from a fugashi build if you need replacements — do not “update existing notes” on the whole deck.

---

## Do / don’t

| Do | Don’t |
|----|--------|
| Build with `~/shadowing/cli/.venv/bin/python` (fugashi) | Run `import_shadowing.py` with bare system Python if you can avoid it |
| Keep native `wk_shadowing_*.m4a` on `SentenceAudio` | Run `synthesize_immersion_sentence_audio.py --force` expecting to refresh Shadowing **sentence** audio |
| Use `--surface-only` for Target/Reading TTS | Enable **Update existing notes** on `.apkg` re-import to “fix” cards |
| Push templates / `--cloze-only` for live fixes | Expect re-import to update existing note fields safely |
| Study WK cloze for words WK already has | Keep glued candidates like `敬語使` / `けいごつかっ` |

---

## Prerequisites (detail)

- Finished shadowing project: `source.json`, `sentences.json`, `clips/*.m4a`
- `out/wk_mining_vocab_index.json` (from a normal `wk_decks.py` generate)
- **Recommended:** `fugashi` + `unidic-lite` (bundled in the shadowing CLI venv)

Without fugashi, imports fall back to kanji-run candidates. The generator carves WK spans out of those runs (so `敬語使って` should not become `敬語使`), but token POS filtering and name handling are still better with fugashi.

---

## Priority config

`out/wk_adaptive_new_config.json`:

```json
{
  "immersion_priority_enabled": true,
  "immersion_tags": ["satori-mining", "shadowing-mining"],
  "immersion_unsuspend": true
}
```

Legacy single-key `immersion_tag` still works if `immersion_tags` is omitted.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Answer reading ends in っ (e.g. `けいごつかっ`) | Bad candidate cut — delete the note; rebuild with fugashi venv |
| Front has no English on Candidates | Push candidate templates (v9+); field is `Translation` / `HintGlossary` |
| iPhone Target/Reading tap advances the card | Push templates (shadowing v8+ / candidate v11+ / satori v17+): `python3 scripts/push_satori_template_ankiconnect.py` then sync |
| iPhone Target/Reading button does nothing | Same push — uses Anki `[sound:]` (HTML5 `<audio>` does not play on AnkiMobile). Immersion decks get **WK Immersion Audio** options (autoplay off; sentence still autoplays via template JS) |
| Sentence plays Voicevox, not the video clip | `python3 scripts/restore_shadowing_native_audio.py` |
| WK cloze shows no blank/highlight | `push_satori_template_ankiconnect.py --cloze-only --model "WK Shadowing Immersion"` |
| Still no blank/highlight after that | The lemma is not in the sentence at all — a bad WK match (担ぐ/任す pulled out of 担任, 息/音 out of a sentence with neither). Delete the note; it is not a cloze bug |
| Answer belongs to a different word than the sentence (`え、同い年じゃないですか?` answered `２０１１年`) | Legacy kanji-stem mis-match. Audit and remove: `python3 scripts/audit_shadowing_wk_matches_ankiconnect.py` (add `--delete`), then live-add corrected notes: `python3 scripts/live_import_shadowing_ankiconnect.py ~/shadowing/cli/projects/VIDEO_ID` (or rebuild `.apkg` and import without updating existing notes) |
| Core new queue ignores shadowing vocab | Confirm `shadowing-mining` tag + **WK Adjust New Limits**; check `immersion_tags` in adaptive-new config |
| `fugashi ok` fails | Use `~/shadowing/cli/.venv/bin/python`, or `pip install fugashi unidic-lite` into the env you run imports with |

---

## Related

- [wk_anki_runbook.md](../wk_anki_runbook.md) — daily study + immersion overview
- [satori_mining.md](satori_mining.md) — Satori Reader CSV immersion
- [yomitan_mining.md](yomitan_mining.md) — browser/video mining
- [voicevox_setup.md](voicevox_setup.md) — TTS engines (Satori / Target buttons)
- Shadowing toolkit: `~/shadowing` (`shadowmine create` / `mine` / `export`)
