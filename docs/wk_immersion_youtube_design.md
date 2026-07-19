# YouTube Immersion Mining — Design Plan

**Status:** Partial — clip extract CLI shipped (`scripts/extract_immersion_clip.py`); full auto-note builder still deferred  
**Last updated:** 2026-07-12  
**Scope:** YouTube only (no Netflix DRM pipeline in v1)

Use with **WK Yomitan Immersion** notes: mine the sentence in Yomitan, then attach native audio:

```bash
python3 scripts/extract_immersion_clip.py \
  --url 'https://www.youtube.com/watch?v=…' \
  --start 1:23.5 --end 1:26.8 \
  --selected
```

See [yomitan_mining.md](yomitan_mining.md).

> **Prerequisite:** [wk_core_srs_design.md](wk_core_srs_design.md) Phase 1–2 complete — core decks, `wk_unlock`, supplementary `WkSubjectId` gating, filtered daily queues.

---

## Goals

| Goal | How |
|------|-----|
| Mine a **specific sentence** from a YouTube video | User supplies URL + in/out timestamps (+ optional text) |
| **Native audio clip** on the card | `yt-dlp` + `ffmpeg` segment extract → bundled `.mp3` |
| **Japanese text** on the card | User paste, YouTube subs, or Whisper fallback |
| **Same SRS ecosystem** | FSRS, `wk_unlock`, filtered decks — not a separate silo |
| **WK-aware gating** | Link target vocab via `WkSubjectId`; `wk-locked` until mature in core |
| **Cloze production** | Same pedagogy as vocab-cloze — type the missing word in context |

## Non-goals (v1)

- Netflix / streaming DRM capture
- Auto-adding new kanji/vocab to **core** decks (catalog stays WK-shaped)
- Syncing immersion progress back to WaniKani
- Fully automated “watch whole video → thousands of cards” (subs2srs-style bulk)
- Public redistribution of clipped audio (personal SRS only)

---

## Ideal user workflow (target)

1. User finds a line in a YouTube video (e.g. `https://youtu.be/…` @ `1:23.5`–`1:26.8`).
2. User runs a CLI (or future Anki add-on) with URL, times, and optional transcript:

   ```bash
   python immersion_youtube.py add \
     --url 'https://www.youtube.com/watch?v=…' \
     --start 1:23.5 --end 1:26.8 \
     --text '学生が本を読んでいる。' \
     --target-vocab-id 1234   # optional WK subject id
   ```

3. Tool:
   - Downloads audio (or uses cached full-audio) and clips segment
   - Tokenizes Japanese, matches tokens against `.wk_cache/` WK subjects
   - Builds one **Immersion Sentence** note: cloze on target word, clip audio, source metadata
   - Tags `wk-locked` if target vocab not mature at import; links `WkSubjectId`
4. Output: row in a queue file and/or `.apkg` snippet merged into weekly `wk_all.apkg`
5. User imports → **Tools → WK Run Unlock Pass** (or wait for desktop open) → card appears when ready

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ INPUT — user or batch file                                       │
│  • youtube_url, start_sec, end_sec                               │
│  • sentence text (optional → Whisper if missing)                 │
│  • target: WkSubjectId and/or surface substring for cloze        │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ immersion_youtube.py (new)                                       │
│  • yt-dlp: fetch audio (cache by video id in .wk_cache/youtube/) │
│  • ffmpeg: clip [start, end] → mp3                               │
│  • tokenizer: Sudachi/fugashi → lemmas                           │
│  • wk_match.py: map tokens → WK vocab/kanji ids (read-only cache)│
│  • build_immersion_note() → genanki note                         │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ DECK — supplementary (like vocab-cloze)                          │
│  • Deck: "Immersion · YouTube Sentences"                         │
│  • Note type: WK Update-Safe Immersion Cloze (new)               │
│  • Fields: WkSubjectId, Sentence, Cloze, Reading, ClipAudio,     │
│            SourceUrl, ClipStart, ClipEnd, Meta, GuidKey          │
│  • Tags: immersion-youtube, wk-locked (if not mature), …         │
└────────────────────────────┬────────────────────────────────────┘
                             │ import with wk_all.apkg or standalone
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ ONGOING — existing Anki addons                                   │
│  • wk_unlock: unsuspend when WkSubjectId mature in core          │
│  • Study directly from the Immersion home deck                    │
│  • FSRS via wk_deck_options                                      │
└─────────────────────────────────────────────────────────────────┘
```

**Core principle:** Immersion cards are **supplementary**, not new core catalog entries. They **reference** WK subjects already in `WaniKani Core · Vocabulary` (primary) or kanji for reading-heavy lines.

---

## Note type sketch

| Field | Purpose |
|-------|---------|
| `GuidKey` | Stable id: hash(url, start, end, cloze) |
| `WkSubjectId` | Primary unlock target (usually one vocab id) |
| `WkSubjectIds` | Optional comma-list of all WK ids in sentence (Browse/filter) |
| `Sentence` | Full line with `{{c1::target}}` cloze markup |
| `Reading` | Furigana / reading line for cloze target |
| `Meaning` | English hint (optional, user or WK primary meaning) |
| `ClipAudio` | `[sound:immersion_yt_{videoId}_{start}_{end}.mp3]` |
| `SourceUrl` | Canonical YouTube URL |
| `SourceTitle` | Video title (yt-dlp metadata) |
| `ClipStart` / `ClipEnd` | Seconds (for re-clip / attribution) |
| `Meta` | Template version, channel, date added |

Template: one **Cloze** card — hear clip + see sentence with blank → type answer (mirror vocab-cloze type-in).

---

## WK matching rules (v1)

1. Load vocab/kanji from existing `.wk_cache/subjects` (same index as `wk_decks.py`).
2. Tokenize sentence; for each token, try:
   - exact `characters` match on vocabulary
   - lemma match via Sudachi dictionary form
3. **Target vocab selection:**
   - If user passed `--target-vocab-id`, use it
   - Else if one WK vocab appears only once and is “content word”, suggest it
   - Else prompt / write to review queue JSON for manual pick
4. **Gating:** reuse `supplementary_import_tags()` + `wk_unlock` supplementary path (same 7-day / Guru I rule at import).
5. Do **not** create core kanji/vocab notes — only link ids on the immersion note.

---

## Implementation phases

Pick up in order. Each phase should ship tests + a small manual test clip.

### Phase 0 — Spike (½ day)

- [ ] Manual: `yt-dlp -x` + `ffmpeg -ss -to` on one known URL; confirm clip quality
- [ ] Confirm Japanese subs availability (`yt-dlp --list-subs`) vs need for Whisper
- [ ] Document dependency versions in `requirements.txt` (`yt-dlp`, optional `openai-whisper` or faster-whisper)

**Exit:** One `.mp3` clip on disk from a timestamp range.

### Phase 1 — Clip + catalog (CLI only)

- [ ] `immersion_youtube.py` — subcommands: `clip`, `info` (title, subs langs)
- [ ] Cache layout: `.wk_cache/youtube/{video_id}/audio.m4a`, `metadata.json`
- [ ] `clip` writes `out/media/immersion_youtube/…mp3`
- [ ] Tests with mocked yt-dlp/ffmpeg (no network in CI)

**Exit:** `python immersion_youtube.py clip --url … --start … --end …` → mp3 file.

### Phase 2 — WK matcher + queue file

- [ ] `wk_match.py` — `match_sentence_to_wk(text) -> MatchResult(target_id, all_ids, unmatched_tokens)`
- [ ] `immersion_queue.jsonl` — one JSON object per mined sentence (url, times, text, target_id, mp3 path)
- [ ] CLI `add` appends to queue; `list` / `edit-target` for manual fixes

**Exit:** Sentence → suggested WkSubjectId with test fixtures.

### Phase 3 — Deck builder + import

- [ ] `immersion_decks.py` — `build_immersion_youtube_deck(queue, assignment_index, …)`
- [ ] Note type + template v1; wire into `wk_decks.py` as optional `--deck immersion-youtube` or separate `python immersion_youtube.py build`
- [ ] `patch_apkg_supplementary_suspend` for `wk-locked`
- [ ] Add `WK::Immersion · YouTube` to `FILTERED_DECK_DEFINITIONS`
- [ ] Runbook section (when implemented)

**Exit:** `.apkg` imports; card suspended until vocab mature; unlock via desktop `wk_unlock`.

### Phase 4 — Polish (optional)

- [ ] Whisper auto-transcribe when `--text` omitted and no JP subs
- [ ] Anki add-on: paste URL + times from clipboard (thin wrapper calling CLI)
- [ ] Furigana generation (MeCab + ipadic or existing project helper)
- [ ] Duplicate detection (same url+start+end)

---

## Dependencies

| Tool | Role |
|------|------|
| **yt-dlp** | Download audio; read metadata and subtitles |
| **ffmpeg** | Clip segment (must be on PATH) |
| **Sudachi** or **fugashi** | Tokenization / lemma for WK matching |
| **Whisper** (optional) | ASR when subs missing or wrong |

Add to `requirements.txt` only when Phase 1 starts. System binaries: document in runbook (`brew install ffmpeg`).

---

## Open decisions (resolve at Phase 2–3)

| # | Question | Default proposal |
|---|----------|------------------|
| I1 | One target vocab vs multiple cloze cards per sentence? | **One card, one target** in v1 |
| I2 | Unlock on single target vs all WK tokens in sentence? | **Single `WkSubjectId`** (same as dictation/cloze) |
| I3 | Separate deck vs extend vocab-cloze note type? | **Separate note type** — different fields (SourceUrl, clip) |
| I4 | Bundle in `wk_all.apkg` vs standalone import? | **Optional in config** `generate_decks: […, "immersion-youtube"]` |
| I5 | Whisper local vs API? | **Local faster-whisper** default; no cloud requirement |
| I6 | Copyright / ToS reminder in CLI? | One-line “personal use only” on `add` |

---

## Testing map (when built)

| Test | Proves |
|------|--------|
| `test_immersion_youtube_clip.py` | ffmpeg args, cache paths, mock yt-dlp |
| `test_wk_match.py` | Token → WK id, conjugated verb → lemma vocab |
| `test_immersion_decks.py` | Note fields, wk-locked tags, guid stability |
| `test_wk_unlock_logic.py` (extend) | Immersion note unsuspends when linked vocab mature |

---

## File map (planned)

| File | Role |
|------|------|
| `docs/wk_immersion_youtube_design.md` | **This plan** |
| `immersion_youtube.py` | CLI: clip, add, build |
| `immersion_decks.py` | genanki deck + note type |
| `wk_match.py` | Sentence ↔ WK subject matcher |
| `immersion_queue.jsonl` | User queue (gitignored) |
| `.wk_cache/youtube/` | Per-video audio + metadata (gitignored) |
| `wk_decks.py` | Optional `--deck immersion-youtube` wiring |
| `tests/test_immersion_*.py` | Unit tests |

---

## Pickup checklist (for future you / agents)

1. Confirm core SRS stable: daily reviews only in Anki, unlock working, no WK review debt.
2. Read **Implementation phases** — start Phase 0 spike on one URL.
3. Resolve open decisions I1–I3 before note type freeze.
4. Reuse `supplementary_import_tags`, `WkSubjectId`, `wk_unlock` — do not fork gating logic.
5. Update [wk_core_srs_design.md](wk_core_srs_design.md) implementation table when Phase 3 lands.

---

## Related docs

- [wk_core_srs_design.md](wk_core_srs_design.md) — core SRS + supplementary gating
- [wk_anki_runbook.md](../wk_anki_runbook.md) — import / addon workflow
