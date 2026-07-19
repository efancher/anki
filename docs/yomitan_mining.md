# Yomitan immersion mining

Mine vocabulary from reading (web, ebooks, Satori Reader, etc.) into Anki with **sentence cloze on the front** (type the reading in kana (kanji still shown in the cloze)) and **full sentence + audio on the back**. Cards stay **unlocked** — hints fade as related kanji/vocab reach Guru+ in your WK core decks.

## What you get

| Piece | Role |
|-------|------|
| **Immersion · Yomitan Mining** deck | Home deck for mined cards |
| **WK Yomitan Immersion** note type | Sentence cloze + type-in; Yomitan sends notes here via AnkiConnect |
| **wk_immersion** add-on | Cloze blank, WK links, hint flags, **SentenceAudio** (VOICEVOX if empty) |
| **wk_unlock** add-on | **Tools → WK Run Unlock Pass** updates hint stages (no suspend) |
| **UserNotes** field | Empty at mine time; personal mnemonics (katakana bridges, etc.) |
| **Glossary / Synonyms / Antonyms** | J–J definition + thesaurus hooks on the card back (template **v14**; see below) |
| **Immersion · Yomitan Mining** | Home deck; study directly from this deck |

## One-time setup

### 1. Import the note type

```bash
python wk_decks.py --deck mining
```

Import `out/wk_mining.apkg` (or `out/wk_all.apkg` from a normal regen — **mining is included** in the default bundle). Choose **Update** when re-importing after template changes.

Sync add-ons: `./scripts/sync_anki_addons.sh` → restart Anki.

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

### 4. Update the note type (template v14)

If you already imported the mining deck, refresh the note type so cloze fields (**ClozeSentence**, **HintStage**, etc.) exist:

```bash
python3 wk_decks.py --deck mining
```

In Anki: **File → Import** → `out/wk_mining.apkg` → choose **Update** (not “Import as new”). Restart Anki, then run **Tools → WK Enrich Mining Notes** once to backfill cloze/WK fields on older notes.

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
| ClozeSentence, WkSubjectId, PrerequisiteIds, WkMeaning, HintGlossary, HintStage, ShowEnglish, ShowKana, ShowJjBack, SentenceKana, DictLinksJa, DictLinksEn | **wk_immersion** at mine time (needs `out/wk_mining_vocab_index.json` from a full regen or `--deck mining` with cached WK vocab) |
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

## Card layout (template v14)

- **Front:** sentence with blank (`ClozeSentence`) + progressive hints + `{{type:Reading}}`.
- **Hints:** stage 0 = kana + WK English + J–E links + pitch + J–J snippet; stage 1 = kana only; stage 2 = no hints.
- **Back (always):** typed answer, full sentence, VOICEVOX **SentenceAudio**.
- **Back (stage 2 only):** **SentenceKana** (speaking practice), pitch, full **Glossary / Synonyms / Antonyms**, JP dict links.

Hint stages update on **Tools → WK Run Unlock Pass** (no card locking). Post-mine enrichment runs in **wk_immersion** when Yomitan adds a note.

> Design reference: [yomitan_mining_cloze_design.md](yomitan_mining_cloze_design.md).

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
| **This deck + Yomitan** | Reading, web, ebooks — sentence cloze + pitch from Kanjium |
| **[ASB Player](https://github.com/asbplayer/asbplayer)** | YouTube / streaming video — native clip + screenshot onto Yomitan cards |
| **Migaku** | Legacy; same idea as ASB but clunkier in practice |
| **WK Vocabulary Context** | WK sentence clozes (generator-built, type-in production) |

## Video mining with ASB Player (recommended)

[ASB Player](https://app.asbplayer.dev/) + Yomitan is the usual video workflow: Yomitan builds the card (word, sentence, pitch, J–J); ASB clips the **exact subtitle window** from the video and attaches **SentenceAudio** + **Image** to the note you just created.

### Install

1. [ASB Player browser extension](https://github.com/asbplayer/asbplayer/releases/latest)
2. Anki + AnkiConnect (already required for Yomitan)
3. Import **WK Yomitan Immersion** (`out/wk_mining.apkg`) — see setup above

### Configure ASB → Anki

Open [ASB Player settings](https://app.asbplayer.dev/?view=settings) → **Anki**:

| ASB setting | WK Yomitan Immersion field |
|-------------|----------------------------|
| Deck | `Immersion · Yomitan Mining` |
| Note type | `WK Yomitan Immersion` |
| Sentence | `Sentence` |
| Word | `Expression` |
| Audio | `SentenceAudio` |
| Image | `Image` *(see below if missing from dropdown)* |
| Definition | *(optional — leave blank or `Glossary`; Yomitan fills J–J better)* |

AnkiConnect URL must match Anki (**127.0.0.1:8765** by default). Export audio as **mp3** if you sync to AnkiMobile.

**Image not in the ASB dropdown?** ASB only lists fields that already exist on the note type you selected. Older **WK Yomitan Immersion** installs (pre–Migaku era) did not include **Image** — only **SentenceAudio** and the text fields.

Fix (pick one):

1. **Re-import** (recommended): `python3 wk_decks.py --deck mining` → Anki **File → Import** → `out/wk_mining.apkg` → **Update** `WK Yomitan Immersion`.
2. **Add-on on startup**: sync `./scripts/sync_anki_addons.sh`, restart Anki — **WK Immersion** adds **Image** automatically to mining note types.
3. **Manual**: Anki → **Tools → Manage Note Types** → **WK Yomitan Immersion** → **Fields** → **Add** → name it exactly `Image`.

Then reload [ASB settings](https://app.asbplayer.dev/?view=settings), re-select **WK Yomitan Immersion**, and **Image** should appear. If you only care about audio for now, leave **Image Field** blank — **Ctrl+Shift+U** still attaches **SentenceAudio**.

### Workflow (two-step)

**Before mining:** ASB must be “on” for that YouTube tab — you need **text-selectable ASB subtitles** on screen (not just YouTube’s native CC). If you skip this, **Ctrl+Shift+U** often does nothing.

1. On the YouTube watch page, press **Ctrl+Shift+F** (default) → pick the **Japanese** track → confirm. You should see ASB’s subtitle overlay (selectable text, optional auto-pause).
   - Or drag a `.srt` / `.ass` onto the video tab.
   - Adjust offset if needed ([timing guide](https://docs.asbplayer.dev/docs/guides/subtitle-timing)).
2. **Yomitan** — scan the subtitle line, click **+** to send the card to Anki (pitch, glossary, cloze enrichment via **wk_immersion**). Confirm the note appears in **Immersion · Yomitan Mining**.
3. **ASB hotkey** — with the **same subtitle still on screen**, focus the YouTube tab and press **Update last card** (default **Ctrl+Shift+U**). You should hear a brief clip capture; **SentenceAudio** and **Image** update on that note.

**Close Anki’s card browser** before step 3 if the note is open there — a known AnkiConnect quirk can make the first **Ctrl+Shift+U** appear to do nothing.

For streaming video you must use an **extension hotkey** (not plain copy) — otherwise audio/image stay empty. Common defaults:

| Hotkey | Action |
|--------|--------|
| **Ctrl+Shift+U** | Update **last created** Anki card with clip + screenshot |
| **Ctrl+Shift+X** | Copy subtitle + open ASB Anki export dialog (streaming tab) |
| **Ctrl+Shift+Q** | Same for **local** files on [app.asbplayer.dev](https://app.asbplayer.dev) |

Prefer **Yomitan first → ASB update** so pitch, glossary, and cloze fields stay on the WK note type. **Ctrl+Shift+X** alone can create a bare card without Yomitan’s pitch/J–J unless you fill fields manually.

If **SentenceAudio** was already filled by VOICEVOX at mine time, the ASB update overwrites it with the native clip. For video-only mining you can set `"on_mine": false` in `wk_immersion_config.json` to skip TTS until ASB runs.

## Cards (template v14)

1. **Sentence cloze → word** — progressive hints; type **Reading** (kana).
2. **Shadow → pitch** — listen to **SentenceAudio** and speak along; back shows **SentenceKana**, **PitchAccents** / **PitchGraphs**, and optional word **Audio**.

Pitch fields fill from Yomitan when Kanjium (or similar) is installed and mapped.

## Native sentence audio (clips)

Yomitan does not grab video audio. Options (best first for video):

1. **ASB Player** — see [Video mining with ASB Player](#video-mining-with-asb-player-recommended) above (**Ctrl+Shift+U** after Yomitan **+**).
2. **VOICEVOX / edge-tts** — `wk_immersion` synthesizes **SentenceAudio** when empty (text mines; see [voicevox_setup.md](voicevox_setup.md)).
3. **Manual YouTube clip** — attach a native clip to an existing note:

```bash
python3 scripts/extract_immersion_clip.py \
  --url 'https://www.youtube.com/watch?v=…' \
  --start 1:23.5 --end 1:26.8 \
  --note-id 1783784549740
# or: --selected   (note selected in Anki browser)
```

Requires `yt-dlp` and `ffmpeg`. Full audio is cached under `.wk_cache/youtube_audio/`.

## Troubleshooting

### `ExtensionError: Could not download audio` (browser console)

Yomitan logs this when it tries to fetch a **dictionary word clip** for the **Audio** field (`{audio}`) after the card is created. It is **not** **SentenceAudio** (that comes from **wk_immersion** / VOICEVOX or ASB **Ctrl+Shift+U**).

**Check first:** did the note appear in **Immersion · Yomitan Mining** anyway? Mining often succeeds; only **Audio** stays empty.

**If you do not need word clips** (ASB + sentence audio is enough):

1. Yomitan **Settings → Anki → Configure Anki card format…**
2. Clear the **Audio** row (remove `{audio}`) or leave **Audio** unmapped.
3. Mine again — the console error should stop.

**If you want word audio:**

1. Yomitan **Settings → Audio → Configure audio playback sources…** — confirm a Japanese source is enabled (e.g. JPod101, Jisho, or a local JSON server).
2. Hover the word in Yomitan — if the speaker icon fails in the popup too, the source has no clip for that term (try another dictionary or add [Forvo / local audio](https://yomitan.wiki/audio/)).
3. Chrome: **Extensions → Yomitan → Details** → enable **Allow access to all sites** (required for audio download).

**Ignore the rest of a noisy YouTube console:** Migaku (`player-store-*.js`, `migaku.com`), YouTube preload/CORS/ad warnings, and `message channel closed` are unrelated. Disable the Migaku extension if you are not using it.

### ASB **Ctrl+Shift+U** does nothing / no **SentenceAudio**

Work through in order:

1. **ASB subtitles active?** On YouTube, **Ctrl+Shift+F** → Japanese track. You must see ASB’s overlay (selectable subtitle text). Plain YouTube CC alone is not enough.
2. **Yomitan card first?** **+** must create a note in **Immersion · Yomitan Mining** before **Ctrl+Shift+U** — ASB updates the **last created** card, it does not create one.
3. **Close Anki card browser** if that note is open, then press **Ctrl+Shift+U** again on the YouTube tab (not the ASB settings tab).
4. **Field mapping** — [ASB settings](https://app.asbplayer.dev/?view=settings) → **Anki** → **Audio Field** = `SentenceAudio` (not `Audio`). Deck and note type must match exactly.
5. **AnkiConnect** — Anki open; ASB settings show the same URL as AnkiConnect (**127.0.0.1:8765**). Grant access when the browser asks.
6. **Hotkey bound?** Chrome → **Extensions** → **ASB Player** → **Keyboard shortcuts** → confirm **Update last card** is **Ctrl+Shift+U** (use **Ctrl**, not **Cmd**, on Mac).
7. **Try Ctrl+Shift+X** instead — opens ASB’s export dialog with more feedback; click **Update last card** in the dialog. If that works but **U** does not, re-bind the hotkey.
8. **YouTube-only glitches** — update the ASB extension; try disabling **Experimental Web Platform features** at `chrome://flags/`; or mine with a downloaded `.srt` instead of auto-detected subs.

**“Multiple video elements detected” (two `blob:https://www.youtube.com/…` choices):** YouTube often has a hidden second `<video>` (mini-player, ad slot, etc.). ASB cannot tell them apart by name.

1. **Prefer syncing first:** press **Ctrl+Shift+F** → pick Japanese subs → confirm. That usually binds the main player without guessing blob IDs.
2. **If forced to pick:** try the **first** entry, or try each once — after a good pick, ASB subtitles appear on the **big** player and **←/→** steps subtitle lines. Wrong pick = no overlay, frozen video, or silent clips → refresh and try the other blob.
3. **Reduce duplicates:** close YouTube mini-player, use normal watch page (not embed), refresh before **Ctrl+Shift+F**.

**Subtitle tracks 1 / 2 / 3 all show “Empty”:** ASB is bound to a video, but **YouTube caption auto-detect failed** (common — YouTube often blocks or changes subtitle APIs). The blob pick is separate from this.

Fix in order:

1. **Update ASB** to the latest [extension release](https://github.com/asbplayer/asbplayer/releases/latest) and restart Chrome.
2. **Confirm the video has Japanese subs** on YouTube itself (CC button → 日本語). ASB cannot invent tracks YouTube does not expose.
3. **Load subs manually** — in the **Ctrl+Shift+F** dialog, use **Open file** on track 1 (or drag a `.srt` / `.ass` onto the YouTube tab). ASB overlays those even when auto-detect is empty.
4. **Download subs with yt-dlp** (same tools as `extract_immersion_clip.py`):
   ```bash
   yt-dlp --write-auto-subs --sub-lang ja --convert-subs srt --skip-download 'https://www.youtube.com/watch?v=VIDEO_ID'
   ```
   Drag the generated `.ja.srt` onto the watch page, then align timing if needed.
5. **Still empty after auto-detect?** Try the **other** blob once (first vs second), refresh, disable **Experimental Web Platform features** at `chrome://flags/`, or stay **logged into YouTube** (some users only get working caption URLs when signed in).

Until a track shows real lines (not Empty) and ASB’s overlay appears on the main player, **Ctrl+Shift+U** has no subtitle window to clip — only wrong or silent audio.

If another add-on creates a card between Yomitan **+** and ASB (e.g. auto kanji decks), ASB may update the wrong note — mine again with those add-ons disabled for a test.

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
