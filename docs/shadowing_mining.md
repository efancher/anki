# Shadowing project → Anki cloze import

Import a **shadowmine** project (`~/shadowing/cli/projects/<videoId>/`) into Anki as:

1. **Immersion · Shadowing** — one cloze card per matched **WaniKani vocabulary** word in each sentence (native clip audio).
2. **Immersion · Shadowing Candidates** — curated **non-WK** content-word lemmas for optional study (no fake WK IDs).

Matched WK subjects also seed **core new-card priority** (same mechanism as Satori) via the `shadowing-mining` tag.

## Prerequisites

- A finished shadowing project with `source.json`, `sentences.json`, and `clips/*.m4a`
- `out/wk_mining_vocab_index.json` (from a normal `wk_decks.py` generate run)
- Optional but recommended: `fugashi` + `unidic-lite` for better lemma/POS matching  
  (already installed in the shadowing CLI venv)

## Build packages

```bash
python3 scripts/import_shadowing.py ~/shadowing/cli/projects/VIDEO_ID
python3 scripts/import_shadowing.py ~/shadowing/cli/projects/VIDEO_ID -o out/
python3 scripts/import_shadowing.py ~/shadowing/cli/projects/VIDEO_ID --skip-auto-caption
```

Writes:

| File | Contents |
|------|----------|
| `out/wk_shadowing.apkg` | WK-linked sentence clozes (`WK Shadowing Immersion`) |
| `out/wk_shadowing_candidates.apkg` | Non-WK candidate clozes (`WK Shadowing Candidate`) |

## Import into Anki

1. Import both `.apkg` files (**Add** / update note types).
2. Do **not** enable **Update existing notes when first field matches** just to refresh templates — that can blank media.
3. Restart Anki, or run **Tools → WK Adjust New Limits**, so `shadowing-mining` subjects float to the front of core Radicals / Kanji / Vocabulary new queues.

## Card policy

| Kind | Behavior |
|------|----------|
| WK cloze | One note per `(sentence × matched WK subject)`. Same native clip; different cloze target. |
| Cloze style | Same as Satori: highlight kanji stem; blank hiragana-only targets. |
| English | Always on the front (`WkMeaning` / sentence translation on back). |
| Audio | Packaged clip in `SentenceAudio` as `[sound:…]` (autoplays). |
| Priority tag | `shadowing-mining` (seeds `wk_adaptive_new`) |
| Candidates | Content words only; excludes WK lemmas, particles/auxiliaries (with fugashi), stopwords. Tag `shadowing-candidate` does **not** seed core priority. |

Auto-caption sentences are imported by default and tagged `shadowing-auto-caption`. Pass `--skip-auto-caption` to omit them.

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

## Related

- [satori_mining.md](satori_mining.md) — Satori Reader CSV immersion
- [yomitan_mining.md](yomitan_mining.md) — browser/video mining
- Shadowing toolkit: `~/shadowing` (`shadowmine create` / `mine` / `export`)
