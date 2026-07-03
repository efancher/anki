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

Run `python wk_decks.py --from-config` (mining is in default `generate_decks`). Import `wk_all.apkg` or **`wk_mining.apkg`** (smaller, mining only). Choose **Update** for the note type.

The export includes one **suspended** setup card so Anki actually creates the deck (empty decks are skipped on import). Delete it in Browse after your first real Yomitan mine, or leave it suspended.

### 2. Install add-ons

```bash
./scripts/sync_anki_addons.sh
```

Restart Anki. Confirm **Tools → WK Link Mining Notes** appears.

### 3. AnkiConnect

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) in Anki. Keep Anki running while mining.

**Test:** with Anki open, visit [http://127.0.0.1:8765](http://127.0.0.1:8765) in your browser. You should see an AnkiConnect version banner (not an error page).

### 4. Yomitan (formerly Yomichan)

#### Connect Yomitan to Anki (empty Deck/Model dropdowns)

If **Configure Anki flashcards** shows empty Deck and Model dropdowns, Yomitan is not connected yet. Work through this in order:

1. **Anki must be running** (with AnkiConnect installed) before you open Yomitan settings.
2. In Yomitan **Settings**, turn on **Advanced** (toggle at the bottom-left of the settings page).
3. In the **Anki** section, enable **Anki integration** / connect to Anki (exact label varies by version — there must be an enable/connect toggle, not just the server field).
4. Set **AnkiConnect server address** to exactly:
   ```
   http://127.0.0.1:8765
   ```
   Leave it blank or wrong → dropdowns stay empty.
5. **Grant permission in Anki:** on a Japanese web page, look up any word with Yomitan and click the green **+** (or try to add a card). Anki should pop up *“A website wants to access Anki through AnkiConnect”* — click **Yes**. Until you approve this once, deck/model lists often stay empty.
6. Close **Configure Anki flashcards**, reopen it. Open the **Expression** tab (that's vocabulary/sentence mining — you can ignore **Reading** and **Kanji** for this workflow).
7. Deck and Model dropdowns should now list your Anki decks. Pick:
   - **Deck:** `Immersion · Yomitan Mining`
   - **Model:** `WK Update-Safe Yomitan Mining`

If dropdowns are still empty after step 5, check AnkiConnect **Config** (Tools → Add-ons → AnkiConnect → Config) — `webCorsOriginList` should include `"http://localhost"` (default). Restart Anki after config changes.

#### Field mapping (Expression tab)

After deck + model are selected, map note fields:

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

**Audio / media:** there is no separate “Add media to notes” toggle for normal mining (green **+** on a lookup). Map **Audio** → `{audio}` in **Configure Anki flashcards**; Yomitan attaches word audio automatically when a downloadable source exists (e.g. Jisho, JapanesePod101 — see Yomitan **Settings → Audio**). That option only appears in **Generate Anki Notes (Experimental)…**, not in everyday mining. Browser TTS playback in the popup cannot be exported to Anki.

**Sentence TTS on card back:** template v2 adds `{{tts ja_JP:Sentence}}` — a speaker control on the answer side that reads the full **Sentence** field using your system Japanese voice (not YouTube audio). Re-import `wk_mining.apkg` or `wk_all.apkg` and choose **Update** for the note type.

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

The add-on links notes on add via `note_will_be_added` (Yomitan/AnkiConnect) and `add_cards_did_add_note` (Add dialog). Run **Tools → WK Link Mining Notes** if a card was added before the add-on was installed.

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
