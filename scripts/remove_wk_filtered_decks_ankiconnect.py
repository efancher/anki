#!/usr/bin/env python3
"""Return cards to home decks and remove legacy WK:: filtered decks.

AnkiConnect's deleteDecks action requires ``cardsToo=true``. To avoid deleting
cards, this script first calls ``changeDeck`` for every populated filtered deck;
AnkiConnect removes those cards from the filtered queue before moving them to
their known home deck. It verifies every move, then deletes only empty decks.

Usage (Anki open with AnkiConnect):
  python3 scripts/remove_wk_filtered_decks_ankiconnect.py --dry-run
  python3 scripts/remove_wk_filtered_decks_ankiconnect.py
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Dict, List, Sequence

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
FILTERED_DECK_PREFIX = "WK::"
FILTERED_DECK_PARENT = "WK"

# Includes current and historical generated names. Unknown empty WK:: decks are
# safe to delete; an unknown populated deck stops the run before any deletion.
HOME_DECK_BY_FILTERED_NAME: Dict[str, str] = {
    "WK::Core Radicals": "WaniKani Core · Radicals",
    "WK::Core Kanji": "WaniKani Core · Kanji",
    "WK::Core Vocabulary": "WaniKani Core · Vocabulary",
    "WK::Kanji Meaning": "WaniKani Kanji Meaning Anchor",
    "WK::N5 · Prereq Radicals": "WaniKani Core · Radicals",
    "WK::N5 · Prereq Kanji": "WaniKani Core · Kanji",
    "WK::N5 · Kanji": "WaniKani Core · Kanji",
    "WK::N5 · Vocabulary": "WaniKani Core · Vocabulary",
    "WK::Tae Kim · Grammar Prereq Radicals": "WaniKani Core · Radicals",
    "WK::Tae Kim · Grammar Prereq Kanji": "WaniKani Core · Kanji",
    "WK::Tae Kim · Grammar Vocab": "WaniKani Core · Vocabulary",
    "WK::Rendaku": "WaniKani Rendaku",
    "WK::Conjugations · Verbs": "WaniKani Verb Conjugation Practice",
    "WK::Conjugations · Adjectives": "WaniKani Adjective Conjugation Practice",
    "WK::Conjugations · Reverse": "WaniKani Verb Conjugation Reverse",
    "WK::Conjugations · Verb Types": "WaniKani Verb Type Practice",
    "WK::Conjugations · Adjective Types": "WaniKani Adjective Type Practice",
    "WK::Grammar": "Japanese Grammar Context",
    "WK::Grammar · Current Tae Kim lesson": "Japanese Grammar Context",
    "WK::Phonetic Families": "WaniKani Phonetic Families",
    "WK::Immersion · Yomitan": "Immersion · Yomitan Mining",
    "WK::Immersion · Migaku": "Immersion · Migaku Mining",
    "WK::Immersion · Satori": "Immersion · Satori",
    "WK::Immersion · Satori Conj": "Immersion · Satori Conjugations",
    "WK::Kanji Contrast": "WaniKani Kanji Contrast",
    "WK::Dictation": "WaniKani Dictation",
    "WK::Vocab Context": "WaniKani Vocabulary Cloze",
    "WK::Mining · Ready": "Immersion · Yomitan Mining",
}


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {base_url}. Is Anki open?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action}: {payload['error']}")
    return payload["result"]


def filtered_deck_names(base_url: str) -> List[str]:
    names = anki_connect(base_url, "deckNames")
    return sorted(name for name in names if name.startswith(FILTERED_DECK_PREFIX))


def card_ids_in_deck(base_url: str, deck_name: str) -> List[int]:
    ids = anki_connect(base_url, "findCards", query=f'deck:"{deck_name}"')
    return [int(card_id) for card_id in ids]


def verify_cards_moved(
    base_url: str, card_ids: Sequence[int], expected_deck: str
) -> None:
    infos = anki_connect(base_url, "cardsInfo", cards=list(card_ids))
    found = {int(info["cardId"]): info.get("deckName") for info in infos if info.get("cardId")}
    missing = set(card_ids) - set(found)
    wrong = {
        card_id: deck_name
        for card_id, deck_name in found.items()
        if deck_name != expected_deck
    }
    if missing or wrong:
        raise SystemExit(
            f"Move verification failed for {expected_deck}: "
            f"missing={sorted(missing)}, wrong_deck={wrong}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--anki-connect", default=DEFAULT_ANKI_CONNECT)
    parser.add_argument(
        "--dry-run", action="store_true", help="Report changes without applying them"
    )
    args = parser.parse_args(argv)

    names = filtered_deck_names(args.anki_connect)
    if not names:
        print("No WK:: filtered decks found.")
        deck_names = anki_connect(args.anki_connect, "deckNames")
        if FILTERED_DECK_PARENT in deck_names:
            parent_cards = card_ids_in_deck(args.anki_connect, FILTERED_DECK_PARENT)
            if parent_cards:
                raise SystemExit(
                    f"Refusing to remove {FILTERED_DECK_PARENT!r} parent: "
                    f"{len(parent_cards)} card(s) remain"
                )
            if args.dry_run:
                print(f"Dry run: would remove empty {FILTERED_DECK_PARENT!r} parent.")
            else:
                anki_connect(
                    args.anki_connect,
                    "deleteDecks",
                    decks=[FILTERED_DECK_PARENT],
                    cardsToo=True,
                )
                print(f"Removed empty {FILTERED_DECK_PARENT!r} parent.")
        return 0

    cards_by_deck = {
        name: card_ids_in_deck(args.anki_connect, name) for name in names
    }
    unknown_populated = {
        name: len(card_ids)
        for name, card_ids in cards_by_deck.items()
        if card_ids and name not in HOME_DECK_BY_FILTERED_NAME
    }
    if unknown_populated:
        raise SystemExit(
            "Refusing to delete: populated deck(s) have no known home mapping: "
            + ", ".join(f"{name} ({count})" for name, count in unknown_populated.items())
        )

    for name in names:
        card_ids = cards_by_deck[name]
        destination = HOME_DECK_BY_FILTERED_NAME.get(name)
        suffix = f" -> {destination}" if card_ids else ""
        print(f"{name}: {len(card_ids)} card(s){suffix}")

    if args.dry_run:
        print(f"\nDry run: would remove {len(names)} filtered deck(s).")
        return 0

    moved = 0
    for name, card_ids in cards_by_deck.items():
        if not card_ids:
            continue
        destination = HOME_DECK_BY_FILTERED_NAME[name]
        anki_connect(
            args.anki_connect, "changeDeck", cards=card_ids, deck=destination
        )
        verify_cards_moved(args.anki_connect, card_ids, destination)
        moved += len(card_ids)

    remaining_counts = {
        name: len(card_ids_in_deck(args.anki_connect, name)) for name in names
    }
    still_populated = {
        name: count for name, count in remaining_counts.items() if count
    }
    if still_populated:
        raise SystemExit(f"Refusing to delete non-empty deck(s): {still_populated}")

    # AnkiConnect requires cardsToo=true, but every target deck is now verified empty.
    anki_connect(args.anki_connect, "deleteDecks", decks=names, cardsToo=True)
    remaining = filtered_deck_names(args.anki_connect)
    if remaining:
        raise SystemExit(f"Some filtered decks remain: {remaining}")

    deck_names = anki_connect(args.anki_connect, "deckNames")
    if FILTERED_DECK_PARENT in deck_names:
        parent_cards = card_ids_in_deck(args.anki_connect, FILTERED_DECK_PARENT)
        if parent_cards:
            raise SystemExit(
                f"Refusing to remove {FILTERED_DECK_PARENT!r} parent: "
                f"{len(parent_cards)} card(s) remain"
            )
        anki_connect(
            args.anki_connect,
            "deleteDecks",
            decks=[FILTERED_DECK_PARENT],
            cardsToo=True,
        )

    print(f"\nMoved {moved} card(s) home and removed {len(names)} filtered deck(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
