---
name: anki-sync
description: Use when the user asks to sync, check, fix, or add cards to their real Anki collection from this server — e.g. "run my anki unlock pass", "check anki health", "sync my anki changes", "add these cards to my deck", "why did my WK unlock pass not work", "pull my anki collection so we can debug it". Operates entirely via AnkiWeb sync (anki_headless/); never touches the user's Mac directly, and the Mac does not need to be on.
---

# Anki headless sync

This repo has headless tooling (`anki_headless/`, `scripts/anki_*`) that syncs
directly with the user's **AnkiWeb** account — the same account their Mac and
phone already sync to — from this server. It never contacts the desktop
Mac, which is normally off when the user is away. Full design and safety
rules: `docs/anki_headless_sync.md`. Read it before doing anything beyond
routine maintenance (see below) — especially before touching `working/` or
pushing anything non-routine.

## Preconditions

- `.venv-headless/` must exist with `anki==25.9.5` installed (`requirements-headless.txt`).
- The user must have already run `scripts/anki_headless_login` once (stores
  an AnkiWeb sync token at `~/.config/anki-headless/auth.json`, 0600). If
  `scripts/anki_run` or `scripts/anki_sync_pull` fail with "Not logged in",
  tell the user to run `scripts/anki_headless_login` themselves — it prompts
  for their AnkiWeb password interactively and this skill must never ask
  for or handle that password itself.

## Routine maintenance (safe to run directly)

These mirror Tools-menu add-ons the user's desktop Anki already runs
automatically — running them here is not a new risk, just doing it without
the Mac:

```bash
scripts/anki_run health-check                       # read-only report
scripts/anki_run unlock-pass                         # unsuspend matured cards
scripts/anki_run adjust-new-limits                    # rebalance new-card budget
scripts/anki_run apply-deck-options                    # assign WK FSRS presets
scripts/anki_run all                                    # all four, in a sensible order
```

By default `anki_run` pulls fresh from AnkiWeb first, backs up `profile/`,
runs against `profile/` directly, and syncs the result back to AnkiWeb —
report the printed `--- changes ---` diff back to the user. If it refuses
with `FullSyncRequired` (AnkiWeb and the local profile have diverged), stop
and follow `docs/anki_headless_sync.md` — do not pass `--allow-full-sync`
without the user explicitly confirming the direction.

## Adding cards / bigger fixes (needs a working copy + explicit approval)

For anything beyond the four routine passes — adding cards, editing note
fields, repairing data — use the working-copy flow, not `profile/` directly:

1. `scripts/anki_sync_pull` — refreshes `profile/` and `working/` from AnkiWeb.
2. Make the change against `~/anki-data/working/collection.anki2` via the
   `anki.collection.Collection` API (open, edit, close) — never hand-edit
   the SQLite file directly unless `docs/anki_headless_sync.md` says direct
   SQLite access is warranted for this specific case, and only on a copy.
3. Validate: `anki_headless.validate.snapshot()` before/after, confirm
   `sqlite_integrity_ok`, and show the user the note/card count diff.
4. Show the user exactly what changed before going further.
5. Only after the user approves: `scripts/anki_sync_push --promote-working`
   to replace `profile/` with the validated `working/` (auto-backed-up
   first) and sync it to AnkiWeb. Never run this step without an explicit
   go-ahead in the conversation.

## Hard rules

- Never pass `--allow-full-sync` without the user explicitly confirming the
  upload/download direction in the conversation — a refusal here means the
  local and AnkiWeb collections disagree and guessing is exactly what this
  tooling exists to avoid.
- Never ask the user for their AnkiWeb password, and never put it in a
  script argument, file, or command — only `scripts/anki_headless_login`
  (interactive, on their terminal) handles it.
- `working/` is disposable and gets overwritten by the next
  `scripts/anki_sync_pull` — don't treat it as persistent storage.
