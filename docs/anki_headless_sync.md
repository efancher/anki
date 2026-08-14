# Headless Anki sync (server ↔ AnkiWeb)

Lets this server (and Claude, via the `anki-sync` skill) inspect, maintain,
and fix the user's real Anki collection **without ever contacting the
desktop Mac**. The Mac is normally off when the user is away; this tooling
doesn't need it to be on, at pull time or push time.

## Why AnkiWeb sync, not SSH to the Mac

Earlier design iterations considered SSHing into the Mac to copy
`collection.anki2` directly, and running a self-hosted Anki sync server.
Both were rejected:

- **SSH to the Mac** requires the Mac to be reachable and awake — exactly
  what the user said isn't reliably true. It also means the server reaching
  *into* a personal device, which the user asked to avoid.
- **Self-hosted sync server** would replace AnkiWeb as the sync target,
  changing the user's whole sync topology, and Anki's sync protocol can
  force a one-way full upload/download when histories diverge — a bigger
  "guess which copy wins" risk than what this tooling exists to avoid.

Instead, this server runs a **headless Anki client** (the official `anki`
PyPI package, Collection API only, no GUI) that logs into the user's own
**AnkiWeb** account and syncs like any other device — the same trust model
their phone already has. AnkiWeb is the hub; the Mac, phone, and this server
are all just clients of it. Nothing here is a new service exposed to
anything — it's outbound HTTPS to AnkiWeb, same as the desktop app.

## Layout

```
~/anki-data/
  profile/     collection.anki2 (+ collection.media/) — the local mirror of
               AnkiWeb's state. The only directory synced with AnkiWeb.
  working/     disposable copy, always re-derived from profile/ before use.
               Never treat it as persistent — the next pull overwrites it.
  backups/     timestamped, append-only. Created automatically before any
               operation that mutates profile/. Nothing here is ever deleted
               by this tooling.
  outgoing/    (optional) staged candidates + SUMMARY.txt for bigger changes
               pending review, via anki_headless.workspace.stage_outgoing().

~/.config/anki-headless/
  auth.json    AnkiWeb sync token (hkey), mode 0600. Never contains the raw
               password — scripts/anki_headless_login exchanges the
               password for this token once and discards the password
               immediately after.
```

Both directories live outside the git repo (`~/anki-data`,
`~/.config/anki-headless`) — real collection data and auth material don't
belong in version control. Override locations with `ANKI_HEADLESS_DATA_DIR`
/ `ANKI_HEADLESS_CONFIG_DIR` env vars if needed.

## Setup

```bash
cd ~/projects/anki
python3 -m venv .venv-headless
.venv-headless/bin/pip install -r requirements-headless.txt   # pins anki==25.9.5
scripts/anki_headless_login       # prompts for AnkiWeb email + password on this terminal
```

The login prompt runs on this server's terminal (not through Claude/chat) —
the password is never sent to or stored by Claude, never logged, never
written to disk. Only the resulting sync token is saved.

### Anki version alignment

Pinned to `anki==25.9.5` (PyPI), matching the user's real Anki 25.09.05
(build `217701ba`). The wheel is `cp39-abi3` (works on any Python ≥3.9,
confirmed against the server's Python 3.12 — no need to match the Mac's
bundled Python 3.13 exactly). **Do not bump this version** without
confirming the desktop/mobile Anki version first — AnkiWeb's sync protocol
does version compatibility checks, and collection schema can change between
releases. Confirmed compatible via `tests/test_anki_headless.py` and the
pre-existing `tests/test_anki25_collection_compat.py`, both of which pass
against `.venv-headless`.

## Scripts

| Script | What it does |
|---|---|
| `scripts/anki_headless_login` | One-time (or refresh) interactive AnkiWeb login |
| `scripts/anki_sync_pull` | AnkiWeb → `profile/`, refreshes `working/`. Incremental only by default. |
| `scripts/anki_run <ops...>` | Runs headless add-on passes (see below). Pulls first, backs up, runs, pushes — all by default. |
| `scripts/anki_sync_push` | `profile/` (or promoted `working/`) → AnkiWeb. Always backs up + integrity-checks first. |

All are thin wrappers around `python3 -m anki_headless.cli <command>` using
`.venv-headless`; run `--help` on any subcommand for full options.

## A. Normal safe workflow

**Routine maintenance** (unlock pass, adjust new limits, health check, apply
deck options) — these already run automatically on the desktop today
(`collection_did_load`, `reviewer_will_end` hooks); running them headlessly
here is not a new risk:

```bash
scripts/anki_run health-check unlock-pass adjust-new-limits
```

Pulls from AnkiWeb → backs up `profile/` → runs the passes against
`profile/` → prints a before/after count diff → pushes back to AnkiWeb.
Phone picks it up on its next sync; Mac picks it up whenever it's next on.

**Bigger changes** (add cards, fix note data, anything not covered by the
four passes above) use the working-copy flow instead, and require explicit
approval before touching `profile/`:

```
AnkiWeb → scripts/anki_sync_pull → working/ → (edit + test) → validate
        → show the user exactly what changed → explicit go-ahead
        → scripts/anki_sync_push --promote-working → AnkiWeb
```

`working/` is never the thing that gets synced directly — `--promote-working`
backs up the current `profile/`, replaces it with the validated `working/`,
*then* syncs. Nothing reaches AnkiWeb without that explicit promotion step.

## B. If the desktop collection changed after pull (divergence)

AnkiWeb's sync protocol reports one of `NO_CHANGES`, `NORMAL_SYNC` (both
safe, handled automatically), or `FULL_SYNC` / `FULL_DOWNLOAD` /
`FULL_UPLOAD` when the local and AnkiWeb collections have diverged too far
to merge incrementally — typically because another device (the Mac, phone)
made changes that didn't get a chance to interleave normally, or a
collection was reset/imported wholesale somewhere.

**This tooling refuses automatically** in that case
(`anki_headless.sync.FullSyncRequired`) — it will not guess whether to
upload (overwrite AnkiWeb with the local copy) or download (overwrite the
local copy with AnkiWeb). Every script prints which direction is being
requested and exits non-zero. To proceed, a human must explicitly choose:

```bash
scripts/anki_sync_pull --allow-full-sync download   # discard local profile/, take AnkiWeb's version
scripts/anki_sync_push --allow-full-sync upload      # discard AnkiWeb's version, push local profile/
```

Before doing either: `profile/` is always backed up automatically before any
mutating operation, so "discard local profile/" is recoverable (see below) —
but "discard AnkiWeb's version" is **not** something this tooling can
undo; AnkiWeb doesn't hand back what it had before an upload. If unsure,
choose `download` (safer default) and re-apply any local server-side work
by hand afterward.

## C. Recovering from a bad candidate

Every mutation of `profile/` is preceded by an automatic backup in
`~/anki-data/backups/<timestamp>-<label>/`, and nothing in this tooling
ever deletes a backup. To recover:

```bash
ls -t ~/anki-data/backups/                     # find the backup to restore
.venv-headless/bin/python3 -c "
from anki_headless import paths, workspace
workspace._copy_profile_dir(paths.BACKUPS_DIR / '<timestamp>-<label>', paths.PROFILE_DIR)
"
```

Then validate it (§D) before syncing. If the bad state already reached
AnkiWeb (i.e. you already ran `anki_sync_push`), restoring `profile/` alone
isn't enough — you'll also need `scripts/anki_sync_push --allow-full-sync
upload` after restoring, since AnkiWeb still has the bad version until you
explicitly overwrite it. Treat that as a deliberate, confirmed action, not
a routine fix.

## D. Verifying a (restored) collection

```bash
.venv-headless/bin/python3 -m anki_headless.cli status
```

Or directly:

```python
from anki_headless import paths, validate
snap = validate.snapshot(paths.PROFILE_DIR)
print(snap)
```

Checks, in order: (1) read-only SQLite `PRAGMA integrity_check` on the raw
file — the strongest *structural* signal without needing Anki's full stack;
(2) successfully opening it with the real `anki.collection.Collection` API
— proves it's not just structurally sound but actually loadable by the
matching Anki version; (3) deck/note/card counts and `tag:wk-core` /
`tag:wk-locked` counts, diffable against a prior snapshot via
`validate.diff()`. Anki's own repair pass (`Collection.fix_integrity()`,
equivalent to Tools → Check Database) is available as
`anki_headless.validate.run_check_database()` but is **not** run as part of
routine validation since it can rewrite the file — call it explicitly only
when actually repairing.

## E/F. Anki open or closed?

None of this tooling requires desktop Anki to be open or closed — it never
touches the Mac. The only thing that matters is AnkiWeb's own multi-device
rule of thumb: if the Mac has local unsynced changes sitting in its Anki
window when this tooling pushes, that's the same "two devices with pending
changes" situation Anki already handles for phone + desktop today — normal
incremental merge in the common case, or the divergence handling in §B in
the uncommon case.

## G. Database sync vs. AnkiConnect

This design does not use AnkiConnect. Database sync (this tooling) talks to
**AnkiWeb** via the Collection API's own sync methods — safe for anything
expressible as collection edits (add/edit notes, adjust decks, run the WK
maintenance passes), and works whether or not the Mac is running. AnkiConnect
would instead mean a script sending HTTP requests to `127.0.0.1:8765` on a
machine with **desktop Anki open** — none of that applies here, since the
whole point was removing the Mac from the loop. If a future case specifically
needs an AnkiConnect-style live edit on the Mac, that's a different,
explicitly-scoped decision requiring desktop Anki to be running at that
moment, not something this tooling does implicitly.

## H. Media sync

Off by default, kept deliberately separate from collection sync — a
`--media` flag on `scripts/anki_sync_pull` / `scripts/anki_sync_push`
triggers `Collection.sync_media()` as an explicit, separate call. Anki's
media sync is already incremental and additive (it doesn't delete local
media on a pull), so no extra logic was needed there — the separation here
is purely about not silently pulling potentially large media on every
routine `anki_run` call.

## Headless add-on passes — what they actually run

`anki_headless/addons.py` does not reimplement any WK add-on logic — it
installs a minimal fake `aqt` module (just enough surface: `mw.col`,
`mw.reset()`, `mw.pm.profileFolder()`, `gui_hooks.*.append()`, `QAction`,
`QFileDialog`, `showInfo`/`showWarning`/`showText`/`tooltip`) and then calls
the real `anki_addon/wk_*/__init__.py` entry points directly — the exact
same code path as the Tools-menu items on the desktop. This is the same
technique `tests/test_anki25_collection_compat.py` already uses to test
`wk_deck_options` outside Anki's GUI.

| `anki_run` operation | Desktop equivalent |
|---|---|
| `health-check` | Tools → WK Health Check |
| `unlock-pass` | Tools → WK Run Unlock Pass |
| `adjust-new-limits` | Tools → WK Adjust New Limits |
| `apply-deck-options` | Tools → WK Apply Deck Options |

`apply-deck-options` and `adjust-new-limits` both depend on
`out/anki_deck_options.json` / deck-options presets existing — same
prerequisite as on desktop (run the generator, or `apply-deck-options`
before `adjust-new-limits` on a fresh collection).

## Tests

```bash
.venv-headless/bin/python3 -m pytest tests/test_anki_headless.py -v
```

Covers paths, auth token storage (round-trip + 0600 permission check, never
persists the raw password), validation (integrity check + count diffs),
workspace backup/promote/never-overwrite behavior, and the headless add-on
runner — all against real (throwaway) `Collection` instances, no AnkiWeb
account needed. Skips cleanly (not an error) under the main `.venv`, which
doesn't have `anki` installed — same reasoning as the pre-existing
`tests/test_anki25_collection_compat.py`.
