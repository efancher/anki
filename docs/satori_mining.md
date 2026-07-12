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

Import the `.apkg` in Anki (**Add** first time, **Update** for note-type template changes).

## What you get

| Piece | Role |
|-------|------|
| **Immersion · Satori** | Home deck |
| **WK Satori Immersion** | Cloze + type-in; English always on back |
| **WK::Immersion · Satori** | Filtered daily queue |
| Tag `satori-mining` | Unlock pass updates progressive hints |

## Card layout

- **Front:** cloze in `Context1` + `{{type:Reading}}` (+ progressive kana/English hints)
- **Back:** expression + reading, **word English**, full sentence (+ furigana when present), **sentence translation**

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

## Related

- [migaku_mining.md](migaku_mining.md) — video/browser mining (same Immersion family)
- [wk_anki_runbook.md](../wk_anki_runbook.md) — daily queues and unlock
