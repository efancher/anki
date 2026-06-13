# WK Filtered Deck Setup (Anki add-on)

Filtered decks cannot be included in `.apkg` imports. This add-on creates them in your
Anki profile after you import `out/wk_all.apkg`.

## Install once

1. Find Anki's add-ons folder:
   - macOS: `~/Library/Application Support/Anki2/addons21/`
   - Windows: `%APPDATA%/Anki2/addons21/`
   - Linux: `~/.local/share/Anki2/addons21/`

2. Copy the `wk_filtered_decks` folder into that directory.

3. Restart Anki.

## Weekly workflow

```bash
python wk_decks.py --deck all --only-started
```

1. Import `out/wk_all.apkg` into Anki (choose **Update** for note types).
2. In Anki: **Tools → WK Setup Filtered Decks**.
3. Select `out/anki_filtered_decks.json` if prompted (or set `WK_FILTERED_DECKS_JSON`).

This creates/rebuilds filtered decks under the **WK** deck group:

- WK::Daily Priority
- WK::Verb Contrasts
- WK::Leeches
- WK::Meaning Leeches
- WK::Reading Leeches
- WK::Radicals Preview
- WK::Confusables Light

## Optional: default JSON path

```bash
export WK_FILTERED_DECKS_JSON="$HOME/anki/out/anki_filtered_decks.json"
```

Then the menu command finds the file automatically.
