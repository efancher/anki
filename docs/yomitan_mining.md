# Yomitan immersion mining

Mine vocabulary from reading (web, ebooks, Satori Reader, etc.) into Anki with **word on the front** and **full sentence + audio on the back**. Cards are **not** gated by WK progress — study them whenever you mine them.

## What you get

| Piece | Role |
|-------|------|
| **Immersion · Yomitan Mining** deck | Home deck for mined cards |
| **WK Yomitan Immersion** note type | Recognition card; Yomitan sends notes here via AnkiConnect |
| **UserNotes** field | Empty at mine time; personal mnemonics (katakana bridges, etc.) |
| **Glossary / Synonyms / Antonyms** | J–J definition + thesaurus hooks on the card back (template **v9+**; see below) |
| **WK::Immersion · Yomitan** filtered deck | Optional daily queue (install `wk_filtered_decks`, then **Tools → WK Setup Filtered Decks**) |

## One-time setup

### 1. Import the note type

```bash
python wk_decks.py --deck mining
```

Import `out/wk_mining.apkg` (or `out/wk_all.apkg` from a normal regen — **mining is included** in the default bundle). Choose **Update** when re-importing after template changes.

The export includes one **suspended** setup card so Anki creates the deck (empty decks are skipped on import). Delete it in Browse after your first real mine, or leave it suspended.

### 2. AnkiConnect

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) in Anki. Keep Anki running while mining.

**Test:** with Anki open, visit [http://127.0.0.1:8765](http://127.0.0.1:8765) — you should see an AnkiConnect version banner.

### 3. Yomitan dictionaries (J–J + thesaurus for cards)

Dictionary zips for this workflow live in **`out/yomitan_dictionaries/`** (see that folder’s `README.md`). Import into Yomitan (**Settings → Dictionaries → Import**; do not unzip).

**Minimum for word definitions on cards:**

| Import | Dictionary | On card |
|--------|------------|---------|
| `04_…例解…zip` | 小学館例解学習国語 第十二版 | **Glossary** (意味) |
| `05_…実用…zip` | 実用日本語表現辞典 | *(popup helper; optional on card)* |
| `06_…対義語…zip` | 対義語辞典オンライン | **Antonyms** (対) |
| `07_…類語例解…zip` | 使い方の分かる 類語例解辞典 | **Synonyms** (類) |

Also keep **Jitendex**, **Kanjium** (pitch), and **DOJG** from your existing setup.

**Reading popup order** (top → bottom): 例解 → 実用 → Jitendex → Kanjium → DOJG → JMnedict → **類語例解 → 対義語** (last so you rarely scroll to them while reading).

**Thesaurus dicts must stay enabled** so Yomitan can fill **Synonyms** / **Antonyms** at mine time, even though you mostly read 例解 + Jitendex in the popup.

**Yomitan → Appearance → Result display:** enable **Group term-reading pairs** (or **Group related terms**) so `{single-glossary-…}` markers work reliably.

**Yomitan → Popup behavior:** enable **Allow scanning popup content** — you will look up words inside J–J definitions.

### 4. Update the note type (template v9)

If you already imported the mining deck, refresh the note type so **Synonyms** and **Antonyms** fields exist:

```bash
python3 wk_decks.py --deck mining
```

In Anki: **File → Import** → `out/wk_mining.apkg` → choose **Update** (not “Import as new”). Restart Anki (or mine once so **wk_immersion** can patch fields in-place).

### 5. Yomitan field mapping

In Yomitan **Settings → Anki** (enable Advanced if needed):

1. Connect to Anki and approve the AnkiConnect permission prompt once.
2. Open **Configure Anki flashcards** → **Expression** tab.
3. Select:
   - **Deck:** `Immersion · Yomitan Mining`
   - **Model:** `WK Yomitan Immersion`

| Note field | Yomitan marker |
|------------|----------------|
| DuplicateKey | `{expression}\|{sentence}` |
| Expression | `{expression}` |
| Reading | `{reading}` |
| Furigana | `{furigana}` |
| PitchAccents | `{pitch-accents}` |
| PitchPositions | `{pitch-accent-positions}` |
| PitchGraphs | `{pitch-accent-graphs}` |
| **Glossary** | `{single-glossary-小学館例解学習国語 第十二版-no-dictionary-first-brief}` |
| **Synonyms** | `{single-glossary-使い方の分かる 類語例解辞典-no-dictionary-brief}` |
| **Antonyms** | `{single-glossary-対義語辞典オンライン-no-dictionary-brief}` |
| Sentence | `{cloze-prefix}{cloze-body}{cloze-suffix}` |
| SentenceFurigana | `{sentence-furigana}` |
| Audio | `{audio}` *(optional word clip from dictionary)* |
| SourceUrl | `{url}` |
| SourceTitle | `{document-title}` |

**Important:** use the **▼ dropdown** next to each field in Yomitan — dictionary names must match your installed revision (e.g. `rev.rgko12;2025-08-18`). The strings above are examples; pick the matching entry from the menu.

**Do not map in Yomitan** (leave these as Anki-only fields; Yomitan may not list them, and that is fine):

| Note field | Who fills it |
|------------|----------------|
| SentenceAudio | **wk_immersion** add-on at mine time (full-sentence TTS) |
| VoicevoxAudio | *(reserved — future tooling)* |
| VoicevoxSpeakerId | *(reserved)* |
| UserNotes | You — katakana bridges, personal hooks, extra glosses |
| Meta | Optional — add `yomitan` only if Yomitan shows an empty row for it |

**Card-only thesaurus:** only **Synonyms** and **Antonyms** (and **Glossary**) appear on the card. Other enabled dictionaries affect the **browser popup** only unless you add more `{single-glossary-…}` mappings.

**Empty sections:** many words have no thesaurus or antonym entry — **類** and **対** blocks are hidden when the field is empty.

**Furigana vs plain kana:** **Furigana** uses `{furigana}` (ruby over kanji on the card). **Reading** is plain kana — shown under the word on the front and again on the back. For kana-only terms, **Reading** may match **Expression**; that is fine.

**Pitch accent:** map the three pitch fields above. Yomitan fills them only when you have a **pitch accent dictionary** installed (e.g. [Kanjium](https://github.com/mifunetori/Kanjium) or NHK-style pitch in Yomitan **Settings → Dictionaries**). **PitchGraphs** is optional HTML from Yomitan; leave blank if you prefer text only (`{pitch-accents}`).

**Sentence from your reading (important):** map **Sentence** to `{cloze-prefix}{cloze-body}{cloze-suffix}` — the full line from the page you scanned. Plain `{sentence}` is fine when mining directly from scanned text, but if you click **+** on a **dictionary example** (Tatoeba line under a definition), `{sentence}` is only that short example (e.g. 頭痛がします), not the paragraph you were reading. The cloze markers always reconstruct the scanned sentence.

**Verify after mining:** Browse → your note → **Sentence** must be the full line from your reading. If it is a short example sentence, Yomitan did not attach page context (wrong **+** button, or no scanned sentence on that page).

**Sentence kana:** **SentenceFurigana** uses `{sentence-furigana}`. wk_immersion synthesizes from **Sentence** (kanji); it uses **SentenceFurigana** only when that field contains a **longer** line than **Sentence**.

**Duplicate settings (recommended):**

| Setting | Value |
|---------|-------|
| Check for card duplicates | On |
| When a duplicate is detected | **Prevent adding** |
| Duplicate card scope | Deck root (or collection) |
| Check for duplicates across all models | On |

**Audio:** map **Audio** → `{audio}` when a dictionary provides a **word** clip (optional). You do **not** configure **SentenceAudio** in Yomitan — the **wk_immersion** add-on synthesizes the full sentence when you click **+** (see below).

### 6. Sentence audio at mine time (wk_immersion add-on)

Yomitan does not export full-sentence TTS. The **wk_immersion** add-on runs during **AnkiConnect addNote** and fills **SentenceAudio** automatically.

1. Sync add-ons: `./scripts/sync_anki_addons.sh` → restart Anki.
2. Start **VOICEVOX** and leave it open — see **[VOICEVOX setup](voicevox_setup.md)** (English guide; you do not need VOICEVOX’s Japanese UI).
3. Mine a word with **+** as usual. After a short pause, the note should have **SentenceAudio** = `[sound:…]`.

Config, voice selection, edge-tts fallback, backfill, and troubleshooting: **[docs/voicevox_setup.md](voicevox_setup.md)**.

**Backfill** notes mined before this add-on: **Tools → WK Synthesize Immersion Sentence Audio**.

To replace audio synthesized from a short dictionary example, re-run with `--force` after fixing **Sentence** in Yomitan:

```bash
python3 scripts/synthesize_immersion_sentence_audio.py --force
```

CLI (Anki + AnkiConnect running): `python3 scripts/synthesize_immersion_sentence_audio.py`

**Playback on the card back (template v7+):**

| Label | Source | Fallback |
|-------|--------|----------|
| **Word** | Yomitan **Audio** (`{audio}` dictionary clip) | Anki TTS on **Reading**, then **Expression** |
| **Sentence** | **SentenceAudio** (wk_immersion / VOICEVOX) | **VoicevoxAudio** → TTS on **Sentence** |

Both play buttons appear on the back — word audio near the definition, sentence audio above the context line.

## Card layout (template v9)

- **Front:** mined word — kanji with ruby (**Furigana**) when Yomitan provides it, otherwise **Expression**; **Reading** (kana) shown underneath.
- **Back:** word + **Reading** + **Pitch** → **意味** (**Glossary**, J–J from 例解) → **類** / **対** when present → **WORD** / **SENTENCE** audio → full sentence → optional **Your notes** → source link.

Sections **意味 / 類 / 対** only appear when Yomitan filled that field at mine time.

## Quick checklist (definitions + thesaurus on cards)

1. Import dictionary zips from `out/yomitan_dictionaries/` (at least **04**, **06**, **07**).
2. Set dictionary order in Yomitan (例解 and Jitendex on top; thesaurus dicts at the bottom).
3. Enable **Group term-reading pairs** and **Allow scanning popup content**.
4. Run `python3 wk_decks.py --deck mining` → import `out/wk_mining.apkg` with **Update**.
5. Map **Glossary**, **Synonyms**, **Antonyms** in Yomitan (use ▼ dropdown for exact `{single-glossary-…}` names).
6. Mine with the green **+** on the headword; check Browse: **Glossary** / **Synonyms** / **Antonyms** populated when the dict has an entry.

## Adding your own notes (mnemonics, katakana bridges)

The **UserNotes** field is for personal material Yomitan does not export — katakana bridges (嬉しい → ハッピー), your own “known word” hook, grammar reminders, etc. **Glossary / Synonyms / Antonyms** are filled automatically when the dictionaries have entries.

### After mining (Browse)

1. **Browse** → deck `Immersion · Yomitan Mining`.
2. Select a note → **Fields** (or double-click the note).
3. Type into **UserNotes**. Line breaks are preserved.
4. Save. On review, a **Your notes** block appears on the back only when the field is non-empty.

Example:

```
別の言い方：〜という意味
関連：食べる（同じ語族）
```

### While reviewing

On desktop, press **E** (Edit) during review, add text to **UserNotes**, save — useful when you look something up mid-session.

### Bulk edit

Browse → select multiple notes → **Notes → Find and Replace** or **Bulk edit** if you use an add-on; otherwise edit individually.

**Tip:** Use **UserNotes** for Cure Dolly-style hooks Yomitan cannot guess (e.g. カタ：ハッピー). Use **類** / **対** on the card for dictionary thesaurus data.

## Duplicate keys

Anki deduplicates on the **first field** only.

- **DuplicateKey** = `{expression}|{sentence}` → same word in **different** sentences creates **different** notes.
- Same word, same sentence → blocked.
- Term-only mining (no sentence): key is just `{expression}`.
- Do **not** put `{reading}` first — homographs would collide.

## vs other immersion tools

| Tool | Best for |
|------|----------|
| **This deck + Yomitan** | Reading, web, ebooks — word → sentence recognition |
| **Migaku** | Video clips with timestamp audio |
| **WK Vocabulary Context** | WK sentence clozes (generator-built, type-in production) |

## Troubleshooting

### `on_note_will_be_added() takes 2 positional arguments but 3 were given`

An old **WK Mining** add-on (`wk_mining`) is still installed. It was replaced by **wk_immersion** and breaks Yomitan mining on Anki 25+.

1. **Tools → Add-ons** → disable or delete **WK Mining** (`wk_mining`).
2. Or run `./scripts/sync_anki_addons.sh` (removes deprecated `wk_mining` automatically).
3. Restart Anki and mine again.

### `deck was not found: Immersion · Yomitan Mining`

Anki does not have that deck yet. Yomitan sends notes via AnkiConnect to a deck that must **already exist** in your profile.

1. Generate the package (if you have not recently):
   ```bash
   python3 wk_decks.py --deck mining
   ```
2. In Anki: **File → Import** → select `out/wk_mining.apkg`.
3. Confirm **Immersion · Yomitan Mining** appears in the deck list (one suspended setup card is normal).
4. In Yomitan **Configure Anki flashcards**, deck name must match **exactly** — including the middle dot `·` (not `-` or `.`):
   `Immersion · Yomitan Mining`
5. Retry the green **+** in Yomitan (Anki must stay open).

If you imported on desktop but mine on a laptop, import `wk_mining.apkg` on that profile too (or sync after import).

### Synonyms / Antonyms missing in Yomitan field list

Yomitan **caches** the Anki note type field list. After template **v9** adds **Synonyms** and **Antonyms**, those rows often **do not appear** until you refresh.

**1. Confirm the fields exist in Anki**

- **Tools → Manage Note Types** → **WK Yomitan Immersion** → **Fields…**
- You should see **Glossary**, then **Synonyms**, then **Antonyms**, then **Sentence** (in that order).
- If **Synonyms** / **Antonyms** are missing:
  ```bash
  python3 wk_decks.py --deck mining
  ```
  **File → Import** → `out/wk_mining.apkg` → **Update** → restart Anki.

**2. Refresh Yomitan’s field list**

- Yomitan **Settings → Anki → Configure Anki card format…**
- Deck: `Immersion · Yomitan Mining` (middle dot **·**, not hyphen)
- Model: `WK Yomitan Immersion` (spelling **Immersion**)
- Change **Model** to **Basic** (or any other type), then change it **back** to **WK Yomitan Immersion**.
- **Synonyms** and **Antonyms** rows should appear. Map them:

  | Field | Marker (use ▼ dropdown) |
  |-------|-------------------------|
  | Synonyms | `{single-glossary-使い方の分かる 類語例解辞典-no-dictionary-brief}` |
  | Antonyms | `{single-glossary-対義語辞典オンライン-no-dictionary-brief}` |

**3. If rows still missing**

- Enable **Advanced** (bottom of Yomitan settings) → **Configure Anki card format** → **+** to duplicate the format and pick **WK Yomitan Immersion** again.
- Or close and reopen the Yomitan options tab with Anki running.

**4. Verify mining**

Browse a newly mined note → **Fields** tab. **Synonyms** and **Antonyms** should contain HTML when the thesaurus dicts have an entry. Cards mined **before** mapping stay empty in those fields — re-mine or edit manually.

**Note:** If **類** / **対** appear on the card but those Anki fields are empty, you may be seeing content inside **Glossary** only (e.g. from a broad `{glossary}` mapping). Split into the three `{single-glossary-…}` fields above.

## Template updates

When the generator bumps the mining template (check **Meta** on card back), re-run `python wk_decks.py --deck mining` and import with **Update** on the note type. Your **UserNotes** and mined field content are preserved; only templates/CSS change.
