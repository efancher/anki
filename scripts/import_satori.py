#!/usr/bin/env python3
"""
Import a Satori Reader CSV into Anki (live via AnkiConnect) and/or build an .apkg.

Default: write notes directly into Immersion · Satori through AnkiConnect
(add new, update existing, preserve audio). No File → Import dialog, no note-type forks.

  python3 scripts/import_satori.py /path/to/satori_export.csv
  python3 scripts/import_satori.py export.csv --apkg          # also write out/wk_satori.apkg
  python3 scripts/import_satori.py export.csv --apkg-only     # package only (no Anki)
  python3 scripts/import_satori.py export.csv --include-ej
  python3 scripts/import_satori.py export.csv --conjugations  # legacy; prefer import_immersion_conjugations.py
  python3 scripts/import_satori.py export.csv --dry-run
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
from satori_live_import import (  # noqa: E402
    DEFAULT_ANKI_CONNECT,
    anki_reachable,
    format_live_import_summary,
    import_satori_cards_to_anki,
)
from immersion_pitch import (  # noqa: E402
    load_immersion_pitch_index,
    resolve_pitch_dict_path,
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
        help=f"Output .apkg path when writing a package (default: out/{SATORI_EXPORT_FILENAME})",
    )
    parser.add_argument(
        "--include-ej",
        action="store_true",
        help="Include EJ (English→Japanese) cards as well as JE (immersion deck only)",
    )
    parser.add_argument(
        "--conjugations",
        action="store_true",
        help="Build Immersion · Conjugations from this CSV only (prefer scripts/import_immersion_conjugations.py)",
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
    parser.add_argument(
        "--anki-connect",
        default=DEFAULT_ANKI_CONNECT,
        help=f"AnkiConnect URL (default: {DEFAULT_ANKI_CONNECT})",
    )
    parser.add_argument(
        "--apkg",
        action="store_true",
        help="Also write out/wk_satori.apkg (backup / sharing)",
    )
    parser.add_argument(
        "--apkg-only",
        action="store_true",
        help="Only write .apkg; do not talk to Anki",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With live import: report adds/updates without writing",
    )
    parser.add_argument(
        "--pitch-dict",
        type=Path,
        default=None,
        help="Yomitan pitch dict zip/folder (default: auto-detect Kanjium in Downloads)",
    )
    parser.add_argument(
        "--no-pitch",
        action="store_true",
        help="Skip pitch accent lookup",
    )
    args = parser.parse_args(argv)

    if args.apkg_only and args.dry_run:
        print("--dry-run only applies to live Anki import", file=sys.stderr)
        return 2

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
        print("Import in Anki, then study from Immersion · Conjugations.")
        print("Tip: scripts/import_immersion_conjugations.py also pulls Shadowing/Yomitan lemmas.")
        return 0

    card_types = ("JE", "EJ") if args.include_ej else ("JE",)
    cards = parse_satori_csv(csv_path, card_types=card_types)
    if not cards:
        print("No cards matched (need Expression + Context1; default CardType=JE).", file=sys.stderr)
        return 1

    wk_index = load_wk_index(args.wk_index.expanduser().resolve())
    pitch_index = None
    if not args.no_pitch:
        pitch_path = resolve_pitch_dict_path(
            args.pitch_dict.expanduser().resolve() if args.pitch_dict else None
        )
        if pitch_path is None:
            print(
                "Pitch dict not found (set --pitch-dict or WK_PITCH_DICT); "
                "continuing without pitch.",
                file=sys.stderr,
            )
        else:
            print(f"Loading pitch dictionary: {pitch_path}")
            pitch_index = load_immersion_pitch_index(pitch_path)
    wrote_apkg = False
    live_ok = False

    if not args.apkg_only:
        if not anki_reachable(args.anki_connect):
            print(
                f"AnkiConnect not reachable at {args.anki_connect}. "
                "Open Anki with AnkiConnect, or pass --apkg-only.",
                file=sys.stderr,
            )
            return 1
        result = import_satori_cards_to_anki(
            cards,
            base_url=args.anki_connect,
            wk_index=wk_index,
            pitch_index=pitch_index,
            dry_run=bool(args.dry_run),
        )
        live_ok = True
        prefix = "DRY RUN — would have " if args.dry_run else "Live import: "
        print(f"{prefix}{format_live_import_summary(result)}")
        if not args.dry_run:
            print("Study from Immersion · Satori. Gloss worksheet uses the same note type.")
            print(
                "TTS if needed: python3 scripts/synthesize_immersion_sentence_audio.py "
                '--note-type "WK Satori Immersion"'
            )

    if args.apkg_only or args.apkg:
        apkg_path, deck = build_satori_deck(
            cards, output_dir, wk_index=wk_index, pitch_index=pitch_index
        )
        if output_path != apkg_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            apkg_path.replace(output_path)
            apkg_path = output_path
        wrote_apkg = True
        print(f"Wrote {len(deck.notes)} notes → {apkg_path}")
        if args.apkg_only:
            print(
                "Package-only mode: import with File → Import only if you need a cold start. "
                "Prefer live import next time (default) so audio is not wiped."
            )

    if not live_ok and not wrote_apkg:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
