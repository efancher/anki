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

- **Front:** cloze in `Context1` + `{{type:Expression}}` (+ progressive kana/English hints)
- **Back:** expression + reading, **word English**, full sentence (+ furigana when present), **sentence translation**

## Related

- [migaku_mining.md](migaku_mining.md) — video/browser mining (same Immersion family)
- [wk_anki_runbook.md](../wk_anki_runbook.md) — daily queues and unlock
