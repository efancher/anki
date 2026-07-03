# Yomitan mining with WK decks

Mine vocabulary and example sentences from reading (web, ebooks, Satori Reader, etc.) into Anki while staying inside the WK unlock / FSRS ecosystem.

## What you get

| Piece | Role |
|-------|------|
| **Immersion · Yomitan Mining** deck | Home deck for mined cards (empty until you mine) |
| **WK Update-Safe Yomitan Mining** note type | Sentence cloze + term cards; Yomitan sends here via AnkiConnect |
| **`out/wk_vocab_lookup.json`** | Expression → WK subject id map (regenerated each run) |
| **`wk_mining` add-on** | Links `WkSubjectId`, applies `wk-locked` until core vocab matures |
| **WK::Mining · Ready** filtered deck | Unlocked mining cards only (install `wk_filtered_decks`) |

## One-time setup

### 1. Import the mining note type

Run `python wk_decks.py --from-config` (mining is in default `generate_decks`). Import `wk_all.apkg` or `wk_mining.apkg`. Choose **Update** for the note type.

### 2. Install add-ons

```bash
./scripts/sync_anki_addons.sh
```

Restart Anki. Confirm **Tools → WK Link Mining Notes** appears.

### 3. AnkiConnect

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) in Anki. Keep Anki running while mining.

### 4. Yomitan (formerly Yomichan)

1. Install [Yomitan](https://github.com/yomidevs/yomitan) + Japanese dictionaries.
2. Options → **Anki** → enable Anki integration.
3. **Configure Anki card format…** → Terms tab:
   - **Deck:** `Immersion · Yomitan Mining`
   - **Model:** `WK Update-Safe Yomitan Mining`
4. Map fields (order matters — **DuplicateKey must stay first**):

| Note field | Yomitan marker |
|------------|----------------|
| DuplicateKey | `{expression}\|{sentence}` |
| Expression | `{expression}` |
| Reading | `{reading}` |
| Glossary | `{glossary-first-brief}` |
| Sentence | `{sentence}` |
| ClozePrefix | `{cloze-prefix}` |
| ClozeBody | `{cloze-body}` |
| ClozeSuffix | `{cloze-suffix}` |
| TypeExpression | `{cloze-body}` |
| SentenceFurigana | `{sentence-furigana-plain}` |
| Audio | `{audio}` |
| SourceUrl | `{url}` |
| SourceTitle | `{document-title}` |
| WkSubjectId | *(leave empty)* |
| Meta | `yomitan` |

5. Duplicate settings (recommended):

| Setting | Value | Why |
|---------|-------|-----|
| Check for card duplicates | On | Gray out already-mined items |
| When a duplicate is detected | **Prevent adding** | Avoid double cards |
| Duplicate card scope | Deck root (or collection) | Match your workflow |
| Check for duplicates across all models | On | Also blocks if same key exists in another model |
| Add media to notes | On | Include `{audio}` when available |

## Duplicate avoidance

Anki deduplicates on the **first field** only.

- **DuplicateKey** = `{expression}|{sentence}` → same word in **different** sentences creates **different** notes (good for cloze mining).
- Same word, same sentence → blocked (good).
- **Term-only** mining (no sentence): key is just `{expression}` → one card per headword.
- Do **not** put `{reading}` first — 橋はし and 箸はし would collide.

### Overlap with WK Vocabulary Context

Generator-built **WaniKani Vocabulary Context** clozes use stable GUIDs per WK subject, not sentence text. A mined sentence for 食べる is **not** a duplicate of the WK cloze card. That is intentional: mined lines add real-world context.

To find duplicate **sentences** among mined notes: **Tools → WK Mining Duplicate Report**.

### Yomitan quirks

- **Slow AnkiConnect:** wait for the add icon to finish before clicking again — rapid clicks can create duplicates ([yomitan#1683](https://github.com/yomidevs/yomitan/issues/1683)).
- If “Prevent adding” seems ignored, toggle the duplicate behavior setting off and back on ([yomitan#1816](https://github.com/yomidevs/yomitan/issues/1816)).

## After mining

1. **Tools → WK Link Mining Notes** — fills `WkSubjectId` from `wk_vocab_lookup.json`, tags `yomitan-mining`, suspends with `wk-locked` if core vocab is not mature.
2. **Tools → WK Run Unlock Pass** — unsuspends when linked core vocab reaches Guru I (same as other supplementary decks).
3. Study via **WK::Mining · Ready** or the home deck.

The add-on also runs a light link pass when new mining cards are added (Anki GUI path; AnkiConnect may still need a manual link pass).

## Cloze vs term cards

| Source | Sentence field | Card style |
|--------|----------------|------------|
| Sentence from reader | filled | Type `{cloze-body}` in context |
| Dictionary popup only | empty | Recall reading + meaning |

Use `{cloze-body}` for **TypeExpression** so inflected forms in context are accepted.

## Non-WK vocabulary

Unknown words still mine normally; `WkSubjectId` stays empty and no `wk-locked` tag is applied. Consider a separate deck/model for non-WK mining if you want different scheduling.

## Regenerating

Each `wk_decks.py` run refreshes `wk_vocab_lookup.json`. Re-run **WK Link Mining Notes** after regen if you add new WK vocab to core.

## References

- [Yomitan Anki integration](https://yomitan.wiki/anki/)
- [YouTube immersion design (future)](wk_immersion_youtube_design.md) — clip audio + subs; mining note type is compatible
