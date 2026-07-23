#!/usr/bin/env python3
"""Suspend retired radical / kanji / phonetic study decks via AnkiConnect.

One-shot apply without waiting for WK Adjust New Limits / collection load.
Suspends cards in:

  - WaniKani Core · Radicals
  - WaniKani Core · Kanji
  - WaniKani Phonetic Families
  - Immersion Core · {Satori, Shadowing, Candidates} · Kanji

Usage:
  python scripts/retire_kanji_radical_study_ankiconnect.py

Requires Anki open with AnkiConnect.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

ANKI_CONNECT_URL = "http://localhost:8765"

RETIRED_DECKS = (
    "WaniKani Core · Radicals",
    "WaniKani Core · Kanji",
    "WaniKani Phonetic Families",
    "Immersion Core · Satori · Kanji",
    "Immersion Core · Shadowing · Kanji",
    "Immersion Core · Candidates · Kanji",
)


def anki_connect(action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        ANKI_CONNECT_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            "Could not reach AnkiConnect at "
            f"{ANKI_CONNECT_URL}. Is Anki open with AnkiConnect installed?\n"
            f"{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action} failed: {payload['error']}")
    return payload["result"]


def main() -> int:
    total = 0
    for deck_name in RETIRED_DECKS:
        query = f'deck:"{deck_name}" -is:suspended'
        card_ids = anki_connect("findCards", query=query)
        if not isinstance(card_ids, list):
            raise SystemExit(f"Unexpected findCards result for {deck_name!r}")
        if not card_ids:
            print(f"{deck_name}: already suspended (0 cards)")
            continue
        anki_connect("suspend", cards=card_ids)
        print(f"{deck_name}: suspended {len(card_ids)} card(s)")
        total += len(card_ids)
    print(f"Done. Suspended {total} card(s) across {len(RETIRED_DECKS)} deck(s).")
    print("Tip: Tools → WK Adjust New Limits also re-applies retire mode each run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
