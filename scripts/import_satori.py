#!/usr/bin/env python3
"""
Build Immersion · Satori Anki package from a Satori Reader CSV export.

Works from any clone of this repo (no Anki required at build time):

  python3 scripts/import_satori.py /path/to/satori_export.csv
  python3 scripts/import_satori.py /path/to/satori_export.csv -o out/wk_satori.apkg
  python3 scripts/import_satori.py export.csv --include-ej   # also EJ recognition cards

Then import the .apkg in Anki (Add or Update note type WK Satori Immersion).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from satori_decks import (  # noqa: E402
    SATORI_EXPORT_FILENAME,
    build_satori_deck,
    parse_satori_csv,
)


def load_wk_index(path: Path) -> dict | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Satori Reader CSV export path")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=f"Output .apkg path (default: out/{SATORI_EXPORT_FILENAME})",
    )
    parser.add_argument(
        "--include-ej",
        action="store_true",
        help="Include EJ (English→Japanese) cards as well as JE",
    )
    parser.add_argument(
        "--wk-index",
        type=Path,
        default=REPO_ROOT / "out" / "wk_mining_vocab_index.json",
        help="Optional WK vocab index for WkSubjectId / meaning linking",
    )
    args = parser.parse_args(argv)

    csv_path = args.csv.expanduser().resolve()
    if not csv_path.is_file():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    card_types = ("JE", "EJ") if args.include_ej else ("JE",)
    cards = parse_satori_csv(csv_path, card_types=card_types)
    if not cards:
        print("No cards matched (need Expression + Context1; default CardType=JE).", file=sys.stderr)
        return 1

    output = args.output
    if output is None:
        output_dir = REPO_ROOT / "out"
        output_path = output_dir / SATORI_EXPORT_FILENAME
    else:
        output = output.expanduser().resolve()
        if output.suffix.lower() == ".apkg":
            output_dir = output.parent
            output_path = output
        else:
            output_dir = output
            output_path = output_dir / SATORI_EXPORT_FILENAME

    wk_index = load_wk_index(args.wk_index.expanduser().resolve())
    apkg_path, deck = build_satori_deck(cards, output_dir, wk_index=wk_index)
    if output_path != apkg_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        apkg_path.replace(output_path)
        apkg_path = output_path

    print(f"Wrote {len(deck.notes)} notes → {apkg_path}")
    print("Import in Anki, then review via filtered deck WK::Immersion · Satori.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
