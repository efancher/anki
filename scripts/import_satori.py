#!/usr/bin/env python3
"""
Build Immersion · Satori Anki packages from a Satori Reader CSV export.

Works from any clone of this repo (no Anki required at build time):

  python3 scripts/import_satori.py /path/to/satori_export.csv
  python3 scripts/import_satori.py /path/to/satori_export.csv -o out/wk_satori.apkg
  python3 scripts/import_satori.py export.csv --include-ej   # also EJ recognition cards
  python3 scripts/import_satori.py export.csv --conjugations

Then import the .apkg in Anki (Add or Update note type).
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

from satori_conjugation_decks import (  # noqa: E402
    SATORI_CONJ_EXPORT_FILENAME,
    build_satori_conjugations_from_csv,
)
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
        help=f"Output .apkg path (default: out/{SATORI_EXPORT_FILENAME} or conjugations filename)",
    )
    parser.add_argument(
        "--include-ej",
        action="store_true",
        help="Include EJ (English→Japanese) cards as well as JE (immersion deck only)",
    )
    parser.add_argument(
        "--conjugations",
        action="store_true",
        help="Build Immersion · Satori Conjugations instead of the immersion cloze deck",
    )
    parser.add_argument(
        "--skip-wk-lemmas",
        type=Path,
        default=REPO_ROOT / "out" / "wk_conjugation_lemmas.json",
        help="Optional JSON skip list of WK lemmas already in conjugation packs",
    )
    parser.add_argument(
        "--wk-index",
        type=Path,
        default=REPO_ROOT / "out" / "wk_mining_vocab_index.json",
        help="Optional WK vocab index for WkSubjectId / meaning linking (immersion deck)",
    )
    args = parser.parse_args(argv)

    csv_path = args.csv.expanduser().resolve()
    if not csv_path.is_file():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    default_name = SATORI_CONJ_EXPORT_FILENAME if args.conjugations else SATORI_EXPORT_FILENAME
    output = args.output
    if output is None:
        output_dir = REPO_ROOT / "out"
        output_path = output_dir / default_name
    else:
        output = output.expanduser().resolve()
        if output.suffix.lower() == ".apkg":
            output_dir = output.parent
            output_path = output
        else:
            output_dir = output
            output_path = output_dir / default_name

    if args.conjugations:
        skip_path = args.skip_wk_lemmas.expanduser().resolve()
        apkg_path, deck, drills = build_satori_conjugations_from_csv(
            csv_path,
            output_dir,
            skip_lemmas_path=skip_path if skip_path.is_file() else None,
        )
        if output_path != apkg_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            apkg_path.replace(output_path)
            apkg_path = output_path
        print(f"Wrote {len(deck.notes)} conjugation notes ({len(drills)} drills) → {apkg_path}")
        print("Import in Anki, then study from Immersion · Satori Conjugations.")
        return 0

    card_types = ("JE", "EJ") if args.include_ej else ("JE",)
    cards = parse_satori_csv(csv_path, card_types=card_types)
    if not cards:
        print("No cards matched (need Expression + Context1; default CardType=JE).", file=sys.stderr)
        return 1

    wk_index = load_wk_index(args.wk_index.expanduser().resolve())
    apkg_path, deck = build_satori_deck(cards, output_dir, wk_index=wk_index)
    if output_path != apkg_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        apkg_path.replace(output_path)
        apkg_path = output_path

    print(f"Wrote {len(deck.notes)} notes → {apkg_path}")
    print("First import: File → Import in Anki (Add note type).")
    print(
        "Notes already exist: they will be skipped — that is OK. "
        "Do not enable Update existing notes (it blanks SentenceAudio)."
    )
    print("Template-only refresh: python3 scripts/push_satori_template_ankiconnect.py")
    print("Then study from Immersion · Satori.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
