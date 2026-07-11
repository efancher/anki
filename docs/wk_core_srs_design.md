# WaniKani → Anki Core SRS — Design & Implementation Tracker

**Status:** Meaning-anchor curriculum — core dual Review retired from default; conjugations unlock via kanji meaning  
**Last updated:** 2026-07-10  
**Owner intent:** Replace WaniKani’s review queue with Anki + FSRS. One-time WK schedule import. All unlock/availability logic runs **inside Anki** (no weekly Python script for progress).

### Current snapshot (2026-07-10)

| Area | State |
|------|--------|
| **Generator** | `python wk_decks.py --from-config` — default `generate_decks` uses `core-radical` + `kanji-meaning` (not core kanji/vocab Review) |
| **Kanji path** | **Kanji Meaning Anchor** (kanji → English); readings via cloze / phonetic / immersion |
| **Unlock** | `wk_unlock` — conjugations, verb/adj types, vocab cloze/dictation/sentence via kanji meaning `PrerequisiteIds` (Guru+); phonetic = reviewed once |
| **Immersion** | Migaku + Satori (`scripts/import_satori.py`) cloze decks |
| **User docs** | [wk_anki_runbook.md](../wk_anki_runbook.md), [satori_mining.md](satori_mining.md) |

**Not linked to core unlock:** grammar, Tae Kim exercises, leech decks (no `WkSubjectId` on leech note type).

**Supplementary gating (wk-locked + kanji `PrerequisiteIds`):** vocab-cloze, dictation, vocab-sentence, conjugations, conjugation-reverse, verb/adjective types. Phonetic families: family kanji reviewed once.

> **Agents:** Read this entire file before working on core SRS, unlock addon, or scheduling bootstrap. After any meaningful change to those areas, update **Last updated**, **Implementation status**, and **Session log** at the bottom.

---

## Agent resume checklist (read first after compaction / new session)

1. Read **Implementation status** — what’s done vs not.
2. Read **Session log** (last 3 entries) — recent decisions and blockers.
3. Skim **Open decisions** — don’t re-litigate settled items without user input.
4. If you changed behavior, update this doc before ending the turn:
   - bump **Last updated**
   - tick/untick checklist items
   - append one line to **Session log**

---

## Goals

| Goal | How |
|------|-----|
| FSRS instead of WK SRS | Review only in Anki after migration |
| One-time WK schedule import | Patch `.apkg` card `ivl`/`due`/`type` from assignments |
| Radical → kanji → vocab order | Prerequisites from `component_subject_ids`; enforced in Anki |
| WK level as metadata only | Tag `wk-level-N`, not unlock order |
| No external unlock script | `wk_unlock` Anki addon suspends/unsuspends + tags |
| Chain supplementary decks | Cloze/grammar/conjugation/dictation gated by core maturity in addon |
| Local content | `.wk_cache/` subjects; deps embedded on notes at import |

## Non-goals (for v1)

- Syncing Anki progress back to WaniKani
- Ongoing WK assignment → Anki rescheduling on re-import
- Importing FSRS stability/difficulty from WK (impossible — approximate only)
- Replacing WK lesson/unlock UI (user stops using WK reviews manually)
- Goal pacing / “burned by August 2027” automation (future: daily new caps)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ ONE-TIME (or rare content sync) — wk_decks.py                   │
│  • Fetch/cache subjects + assignments + review_statistics       │
│  • Build core decks: ALL radicals, kanji, vocab                 │
│  • Embed WkSubjectId, PrerequisiteIds on every note             │
│  • patch_apkg_wk_scheduling() from assignments (bootstrap flag) │
│  • Supplementary decks: ALL cards, suspended if deps unmet      │
│  • write_apkg → patch_apkg_deck_options (existing)              │
└────────────────────────────┬────────────────────────────────────┘
                             │ import wk_all.apkg once
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ ONGOING — Anki profile                                          │
│  • FSRS reviews on core + supplementary cards                   │
│  • wk_unlock addon: mature check, unsuspend, wk-mature tags     │
│  • wk_deck_options addon: WK FSRS preset (existing)             │
│  • wk_filtered_decks addon: daily queues (existing, update searches) │
└─────────────────────────────────────────────────────────────────┘
```

**Rule:** After migration, do **not** re-run the generator to refresh “what’s available.” Re-run only for **new WK catalog content** (new subjects in API cache).

---

## Deck structure (target)

```
WK::Core::Radicals
WK::Core::Kanji
WK::Core::Vocabulary
WK::Production::Vocab Cloze
WK::Production::Dictation
WK::Production::Conjugations …
WK::Production::Grammar …
WK::Filtered::…  (existing addon pattern)
```

Current generator uses flat deck names (`WaniKani Current and Next Radicals`, etc.). v1 may keep flat names and add hierarchy later — **open decision**.

---

## Note types & fields

### Core — existing models, extended

**Radical** — `make_radical_model()` / `NOTE_TYPE_NAMES["radical"]`

| New field | Purpose |
|-----------|---------|
| `WkSubjectId` | WK subject id (int as string) |
| `PrerequisiteIds` | Empty for radicals (or comma-separated if any) |

**Kanji / Vocab** — `make_item_model()` / `NOTE_TYPE_NAMES["item"]`

| New field | Purpose |
|-----------|---------|
| `WkSubjectId` | WK subject id |
| `PrerequisiteIds` | Comma-separated WK ids from `component_subject_ids` |

**Core item (`WK Core Item` v5):** single **Review** template — recall meaning mentally, `{{type:Reading}}` on front (no audio); meaning + reading + `ReadingAudio` + mnemonics on back.

**Leech item model (`WK Update-Safe Item` v7):** Meaning / Reading / Pitch; optional `ReadingAudio` on **back only** when leech decks are built with `--reading-audio`.

Radicals: meaning-only (`WK Core Radical` v2), no reading audio. Kanji audio: edge-tts for **each primary reading** on the back; vocab: one WK native clip.

**Guid:** Keep `stable_guid("core-radical", id)` / `stable_guid("core-item", id)` — distinct from leech deck guids if both coexist during transition.

### Supplementary — add link field

| Deck type | Link field | Prerequisite rule |
|-----------|------------|-------------------|
| vocab-cloze | `WkSubjectId` | That vocab mature |
| dictation | `WkSubjectId` | That vocab mature |
| conjugations-verbs/adjectives | `WkSubjectId` + `PrerequisiteIds` | Kanji components Guru+ in Kanji Meaning Anchor |
| conjugations-reverse | `WkSubjectId` + `PrerequisiteIds` | Kanji components Guru+ in Kanji Meaning Anchor |
| phonetic families | `WkSubjectId` + `PrerequisiteIds` | Any family kanji reviewed once (meaning anchor or core) |
| verb/adjective types | `WkSubjectId` + `PrerequisiteIds` | Kanji components Guru+ in Kanji Meaning Anchor |
| grammar | — | **Not gated** — import caps only (`max_jlpt`, etc.) |
| tae-kim-exercises | — | **Not gated** — lesson cap at import only |

---

## Tags (Anki)

| Tag | Set by | Meaning |
|-----|--------|---------|
| `wk-core` | Generator | Core SRS note |
| `wk-locked` | Generator or addon | Suspended pending prerequisites |
| `wk-deps-met` | Addon | Prerequisites satisfied; card eligible |
| `wk-mature` | Addon | Meets maturity threshold (unlocks downstream) |
| `wk-schedule-bootstrapped` | Generator (once) | WK interval/due was applied — do not re-apply |
| `wk-level-N` | Generator | WK level metadata |
| `wanikani` | Generator | Existing |

---

## WK assignment → Anki scheduling (one-time bootstrap)

**Source:** `.wk_cache/assignments*.json` via `assignment_index[subject_id]`.

**Fields used:**

| WK field | Use |
|----------|-----|
| `unlocked_at` | If null → suspend + `wk-locked` (or omit from import — prefer import all, suspend) |
| `started_at` | If null → suspend + `wk-locked` (not in lesson queue yet) |
| `srs_stage` | Map to interval / card type |
| `available_at` | Set `due` to match next review (epoch → Anki day number) |
| `burned_at` | Interval ≥ 365 or suspend per config |

**SRS stages (WK API):** 0 = locked, 1–4 Apprentice, 5–6 Guru, 7–8 Master/Enlightened, 9 Burned.

**Kanji/vocab:** One **Review** card per note (reading type-in; meaning on back). WK bootstrap applies one schedule per note.

**Implementation:** New `patch_apkg_wk_scheduling(apkg_path, assignment_index, *, bootstrap=True)` called from `write_apkg` / `write_bundled_apkg` when `--bootstrap-wk-scheduling` is set. Patches `cards` table in SQLite (same pattern as `patch_apkg_deck_options`).

**FSRS note:** Bootstrap sets initial `ivl`/`due`/`type`. FSRS recalibrates on next reviews. Collection must have FSRS enabled (`wk_deck_options` addon).

**Re-import safety:** If note/card already has `wk-schedule-bootstrapped` tag or `mod` newer than bootstrap run, skip scheduling patch.

### Interval mapping (v1 default — tune in config)

Fetch exact stage seconds from WK `/v2/spaced_repetition_systems` once into `.wk_cache/spaced_repetition_systems.json`. Fallback table if missing:

| srs_stage | Approx interval (days) | Anki type |
|-----------|--------------------------|-----------|
| 1 | 0 (same day) | learning/review |
| 2 | 1 | review |
| 3 | 1 | review |
| 4 | 2 | review |
| 5 | 7 | review |
| 6 | 14 | review |
| 7 | 30 | review |
| 8 | 120 | review |
| 9 | 365 | review (or suspend) |

Prefer **`available_at`** for `due` when present; use stage table for `ivl` when `available_at` is in the future.

---

## Maturity & unlock (Anki addon only)

**Addon name:** `wk_unlock` (new folder under `anki_addon/`)

**Triggers:**

- `gui_hooks.collection_did_load`
- `gui_hooks.reviewer_will_end` (after review session; Anki 25+; was `reviewer_did_end`)
- Tools → **WK Run Unlock Pass** (manual)
- Optional: timer every 24h

**Algorithm:**

```
1. Index notes: WkSubjectId → list of card ids + note
2. For each WkSubjectId, compute mature(subject):
     - All non-suspended cards for that note meet maturity rule
3. For each note tagged wk-locked (or suspended with PrerequisiteIds):
     - Parse PrerequisiteIds
     - If every id is mature → unsuspend, remove wk-locked, add wk-deps-met
4. For each note just became mature → add wk-mature
5. For supplementary notes with WkSubjectId link:
     - If linked subject mature → unsuspend (if was waiting on core)
```

**Default maturity rule (configurable in addon JSON):**

```json
{
  "mature_min_interval_days": 7,
  "mature_require_all_card_types": true,
  "burned_interval_days": 365
}
```

Radicals: only Meaning card exists — one card interval ≥ threshold.

**No file I/O required** for unlock state. Optional config path: `~/anki/out/wk_unlock_config.json` or env `WK_UNLOCK_CONFIG`.

---

## Supplementary deck gating (replace `--only-started` / `--min-srs`)

**Today:** Generator filters at build time using WK `assignments`. User must re-run to refresh.

**Target:** Generator emits **all** eligible cards (respecting grammar lesson caps, etc.). Cards start **suspended** unless linked core item already mature at import time (bootstrap pass sets initial suspend from WK `srs_stage >= 7` equivalent).

**After migration:** Addon unsuspends when core matures. Filtered decks use:

```
deck:"WaniKani Vocabulary Context" -is:suspended
```

Update `FILTERED_DECK_DEFINITIONS` and `anki_filtered_decks.json` accordingly.

---

## Dependency graph (WK cache)

- **Kanji → radicals:** `kanji.data.component_subject_ids` (may include kanji-as-radical ids)
- **Vocab → kanji:** `vocab.data.component_subject_ids` (kanji ids used in word)

Existing helper: `kanji_has_unlocked_radicals_only()` in `wk_decks.py` — reference for addon logic, not sufficient alone (uses WK unlock state).

Recursive rule: prerequisite id can be radical **or** kanji; maturity check is always by `WkSubjectId`.

---

## Generator CLI

| Flag | Purpose |
|------|---------|
| `--deck core` | Build `WaniKani Core · Radicals/Kanji/Vocabulary` |
| `--bootstrap-wk-scheduling` | Patch card scheduling from WK assignments (one-time) |
| `--no-wk-progress-filter` | Import full supplementary catalog; gate via `wk-locked` + addon |
| `--reading-audio` / `--no-reading-audio` | WK native audio (vocab) + TTS (kanji) on core/leech cards |
| `--reading-voice` | Kyoko or Kenichi for vocab native audio |
| `--core-suspend-unstarted` | Suspend core notes without WK `started_at` (default: on) |

Legacy: `--only-started` still exists; **do not use** for daily workflow after migration.

**Config (`wk_deck_config.json`) — current defaults:**

```json
"generate_decks": ["core", "phonetic-families", "radicals", "conjugations-verbs", ...],
"only_started": false,
"no_wk_progress_filter": true,
"reading_audio": true,
"reading_voice": "Kyoko",
"core": {
  "bootstrap_scheduling": true,
  "import_all_subjects": true,
  "suspend_unstarted": true,
  "reading_audio": true,
  "reading_voice": "Kyoko"
}
```

---

## How decks stay linked (runtime)

Decks are **not** nested in Anki. Linking is **logical**, within one collection:

| Link | Where | Purpose |
|------|-------|---------|
| `WkSubjectId` | Core + gated supplementary notes | Same integer = same WK item across decks |
| `PrerequisiteIds` | Core notes only | Comma-separated WK ids from `component_subject_ids` |
| Stable note GUID | All update-safe note types | Re-import updates same note (`stable_guid("core-item", id)`, etc.) |
| Tags | Anki | `wk-core`, `wk-locked`, `wk-mature`, `wk-deps-met`, `wk-schedule-bootstrapped` |

**`wk_unlock` addon** (runs on collection load, after reviews, Tools menu):

1. **Mature** = core note’s active card interval ≥ 7 days (Guru I; or burned ≥ 365).
2. **Core unsuspend** — if `wk-locked` and every `PrerequisiteIds` entry is mature → unsuspend, tag `wk-deps-met`.
3. **Supplementary unsuspend** — if `tag:wk-locked -tag:wk-core` and linked `WkSubjectId` is mature in core → unsuspend.

**Import-time (one-time):**

- Core: `patch_apkg_wk_scheduling()` suspends + `wk-locked` when WK assignment has no `unlocked_at` / `started_at`.
- Supplementary: `supplementary_import_tags()` + `patch_apkg_supplementary_suspend()` when vocab not WK-mature (stage &lt; 5 and interval &lt; 7 days).

**Filtered daily decks** (`wk_filtered_decks` addon): searches include `-is:suspended` so locked cards never appear. Core filtered decks (`WK::Core Radicals/Kanji/Vocabulary`) included in default JSON.

**Re-import:** Generator refreshes note **content** and templates; does **not** re-sync unlock state. Protect scheduling when `wk-schedule-bootstrapped` is set.

---

## Generator CLI

## Migration playbook (user)

1. Export Anki collection backup.
2. Run generator with `--bootstrap-wk-scheduling` and core decks.
3. Import `out/wk_all.apkg` — update note types.
4. Tools → WK Apply Deck Options; enable FSRS.
5. Install **wk_unlock** addon; run unlock pass once.
6. Tools → WK Setup Filtered Decks.
7. Verify Browse: `tag:wk-core`, spot-check due dates vs WK.
8. Stop doing WK reviews; optional: WK lessons only for new unlocks until fully Anki-gated.

---

## Implementation status

| # | Component | Status | Notes |
|---|-----------|--------|-------|
| 1 | Design doc | **Done** | This file |
| 2 | Cursor rule `.cursor/rules/wk-core-srs-design.mdc` | **Done** | |
| 3 | Core deck builder (`--deck core`) | **Done** | `core_decks.py` |
| 4 | Core note types + fields | **Done** | `WK Core Radical` v2, `WK Core Item` v5 (Review + type-in + mnemonics + audio on back) |
| 5 | `patch_apkg_wk_scheduling()` | **Done** | `wk_scheduling.py` |
| 6 | SRS stage intervals from WK API | **Done** | `.wk_cache/spaced_repetition_systems.json` |
| 7 | `wk_unlock` addon | **Done** | Core prereqs + supplementary unsuspend |
| 8 | Supplementary gating | **Done** | vocab-cloze v7, dictation v3, conjugation v4, conjugation-reverse v4, phonetic_drill v5, word_class v2 |
| 9 | Filtered deck `-is:suspended` | **Done** | Core + supplementary filtered decks |
| 10 | Hidden WK subjects excluded | **Done** | 13 radicals + 25 vocab (`subject_is_hidden`) |
| 11 | WK mnemonic HTML highlights | **Done** | `wk_mnemonic_html()` — radical blue, kanji/vocab red, reading purple |
| 12 | Reading audio on cards | **Done** | `wk_reading_audio.py`; core + leech item v6 |
| 13 | Config defaults for migration | **Done** | `wk_deck_config.json` |
| 14 | Runbook migration section | **Done** | `wk_anki_runbook.md` |
| 15 | Tests | **Done** | 158 tests (see testing map) |
| 16 | Root radical auto-unlock | **Done** | Empty `PrerequisiteIds` → `prerequisites_met()` returns True |
| 17 | Grammar / Tae Kim core gating | **Not started** | Import caps only; O4 deferred |
| 18 | Filtered decks for core SRS | **Done** | `WK::Core Radicals/Kanji/Vocabulary` in `FILTERED_DECK_DEFINITIONS` |
| 19 | `WK::Core::` deck hierarchy | **Not started** | Flat names (O1) |
| 20 | YouTube immersion mining | **Planned** | [wk_immersion_youtube_design.md](wk_immersion_youtube_design.md) — after core stable |
| 21 | Migaku immersion (open deck) | **Done** | [migaku_mining.md](migaku_mining.md) — template v12+ |
| 22 | VOICEVOX TTS for immersion | **Planned** | [wk_voicevox_tts_design.md](wk_voicevox_tts_design.md) — fields reserved; synthesis deferred |

---

## File map

| File | Role |
|------|------|
| `docs/wk_core_srs_design.md` | **This doc** — design + tracker |
| `.cursor/rules/wk-core-srs-design.mdc` | Agent: read doc first |
| `core_decks.py` | Core radical/kanji/vocab deck builder |
| `wk_scheduling.py` | Assignment → scheduling + supplementary suspend patch |
| `wk_reading_audio.py` | WK native vocab audio + kanji TTS for reading fields |
| `wk_decks.py` | CLI, models, supplementary gating, filtered deck defs |
| `wk_deck_config.json` | Default `generate_decks`, core, reading audio |
| `dictation_decks.py` | Dictation deck (imports audio helpers from `wk_reading_audio`) |
| `mining_decks.py` | Migaku immersion note type (open deck, progressive hints) |
| `docs/migaku_mining.md` | Migaku → Anki Map Fields setup |
| `docs/wk_voicevox_tts_design.md` | **Planned** VOICEVOX synthesis for immersion cards |
| `anki_addon/wk_unlock/` | Unlock + mature tags (core + supplementary) |
| `anki_addon/wk_filtered_decks/` | Daily filtered decks |
| `anki_addon/wk_deck_options/` | WK FSRS preset |
| `wk_anki_runbook.md` | User workflow + migration playbook |
| `tests/test_wk_*.py` | Scheduling, unlock, supplementary, mnemonics, reading audio, config |

---

## Key decisions (settled)

1. **One-time WK schedule import** — yes; no ongoing sync.
2. **Unlock in Anki addon** — yes; no Python progress export loop.
3. **Import full catalog** — suspend unready items; don’t omit notes. **Exclude WK-hidden subjects** (`hidden_at` set): 13 retired radicals, 25 retired vocab, 0 hidden kanji (as of cache audit).
4. **One Review card per kanji/vocab** — reading type-in on front; meaning on back (`WK Core Item` v4).
5. **Prerequisites from `component_subject_ids`** — kanji→radicals, vocab→kanji.
6. **Supplementary waits on core vocab maturity** — `WkSubjectId` link + 7-day (Guru I) interval rule in addon.
7. **No ongoing WK sync** — re-import for catalog/template updates only.

## Open decisions / Phase 3

| # | Question | Status |
|---|----------|--------|
| O1 | Flat deck names vs `WK::Core::` hierarchy? | Open — flat names in use |
| O2 | Burned items: long interval vs suspended? | Settled — 365d interval |
| O3 | Unstarted WK items: suspend or omit? | Settled — suspend + `wk-locked` |
| O4 | Grammar gating by core kanji maturity? | **Deferred** — JLPT/Tae Kim caps only |
| O5 | Re-import scheduling merge? | Settled — protect if `wk-schedule-bootstrapped` |
| O6 | Root radicals (empty `PrerequisiteIds`) auto-unlock? | **Done** — `prerequisites_met()` returns True when empty |
| O7 | Filtered decks for core daily review? | **Done** — `WK::Core Radicals/Kanji/Vocabulary` |
| O8 | YouTube immersion sentence mining? | **Planned** — [wk_immersion_youtube_design.md](wk_immersion_youtube_design.md); YouTube-only v1 |
| O9 | VOICEVOX TTS + Kanjium pitch on immersion cards? | **Planned** — [wk_voicevox_tts_design.md](wk_voicevox_tts_design.md); **VoicevoxAudio** field reserved (v5) |

---

## Testing map

| Test file | Proves |
|-----------|--------|
| `test_wk_scheduling.py` | Stage→interval, bootstrap due dates, suspend rules |
| `test_core_decks.py` | Prerequisite ids, Review template, hidden-subject filter |
| `test_wk_unlock_logic.py` | Core + supplementary unlock actions |
| `test_wk_supplementary_gating.py` | `wk-locked` tags, mature-at-import, apkg suspend |
| `test_wk_mnemonic_html.py` | WK tag → colored spans |
| `test_wk_reading_audio.py` | Vocab native + kanji TTS field prep |
| `test_wk_deck_config.py` | Config parsing (incl. `reading_voice` string, not bool) |

---

## Session log

| Date | Summary |
|------|---------|
| 2026-06-25 | Initial design doc created from conversation: FSRS migration, one-time schedule import, wk_unlock addon, prerequisite graph, supplementary gating without external scripts. |
| 2026-06-28 | Phase 1: `core_decks.py`, `--deck core`, `--bootstrap-wk-scheduling`, `wk_unlock` addon v1, unit tests. Supplementary gating + filtered deck updates deferred to Phase 2. |
| 2026-06-28 | Phase 2: `--no-wk-progress-filter`, supplementary `WkSubjectId` + `wk-locked` suspend, SRS API interval cache, filtered deck `-is:suspended`, wk_unlock supplementary unsuspend, migration runbook. |
| 2026-06-25 | Core item: merged Meaning + Reading into single **Review** card (`core_item` v2) — type reading (kana) on front, meaning on back. |
| 2026-06-25 | Exclude WK-hidden subjects (`hidden_at`): 13 retired radicals, 25 retired vocab. |
| 2026-06-28 | WK mnemonic highlights (`wk_mnemonic_html`); `WK Core Item` v3→v4 reading audio (`wk_reading_audio.py`); config `reading_voice` bool-coercion bugfix. |
| 2026-06-28 | Doc sync: migration-ready status, deck-linking section, Phase 3 gaps (root radicals, core filtered decks, grammar gating). |
| 2026-06-28 | Phase 3: root radical auto-unlock (`prerequisites_met` empty→True), core filtered decks, phonetic/verb-type/conjugation-reverse on wk-locked gating + `WkSubjectId`. |
| 2026-07-10 | Retire default core kanji/vocab dual Review; conjugations + verb/adj types unlock via kanji meaning `PrerequisiteIds`; add Immersion · Satori CSV import. |

## Related docs

- [wk_anki_runbook.md](../wk_anki_runbook.md) — current weekly import workflow
- [wk_immersion_youtube_design.md](wk_immersion_youtube_design.md) — **planned** YouTube sentence mining (deferred)
- [migaku_mining.md](migaku_mining.md) — Migaku immersion deck
- [wk_voicevox_tts_design.md](wk_voicevox_tts_design.md) — **planned** VOICEVOX TTS for immersion cards
- [anki_addon/README.md](../anki_addon/README.md) — filtered decks + FSRS preset addons
- `.cursor/rules/wk-anki-template-versions.mdc` — bump templates when changing note types
