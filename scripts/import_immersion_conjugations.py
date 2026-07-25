#!/usr/bin/env python3
"""
Build Immersion · Conjugations from Satori CSV and/or live Anki immersion notes.

Examples:
  python3 scripts/import_immersion_conjugations.py --satori export.csv
  python3 scripts/import_immersion_conjugations.py --from-anki
  python3 scripts/import_immersion_conjugations.py --satori export.csv --from-anki
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from immersion_conjugation_decks import (  # noqa: E402
    DEFAULT_ANKI_CONNECT,
    IMMERSION_CONJ_EXPORT_FILENAME,
    build_immersion_conjugations,
)
from jmdict_pos import (  # noqa: E402
    default_jmdict_index_path,
    default_jmdict_json_path,
)
from wk_decks import (  # noqa: E402
    apply_conjugation_forms_from_config,
    load_wk_deck_config,
    wk_deck_config_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--satori",
        type=Path,
        default=None,
        help="Satori Reader CSV export (JE verbs/adjectives)",
    )
    parser.add_argument(
        "--from-anki",
        action="store_true",
        help="Also (or only) pull satori/shadowing/yomitan immersion notes via AnkiConnect",
    )
    parser.add_argument(
        "--anki-connect",
        default=DEFAULT_ANKI_CONNECT,
        help=f"AnkiConnect URL (default: {DEFAULT_ANKI_CONNECT})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=f"Output .apkg path (default: out/{IMMERSION_CONJ_EXPORT_FILENAME})",
    )
    parser.add_argument(
        "--wk-index",
        type=Path,
        default=REPO_ROOT / "out" / "wk_mining_vocab_index.json",
        help="WK mining vocab index for WkSubjectId / POS linking",
    )
    parser.add_argument(
        "--jmdict",
        type=Path,
        default=None,
        help="Path to jmdict-simplified eng JSON (default: out/jmdict-eng.json)",
    )
    parser.add_argument(
        "--jmdict-index",
        type=Path,
        default=None,
        help="Cached POS index JSON (default: out/jmdict_pos_index.json)",
    )
    parser.add_argument(
        "--no-download-jmdict",
        action="store_true",
        help="Do not download JMDict if missing (fail or rely on Satori/WK POS)",
    )
    parser.add_argument(
        "--max-cards",
        type=int,
        default=None,
        help="Optional cap on generated drills",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="wk_deck_config.json for conjugation_forms allowlist",
    )
    args = parser.parse_args(argv)

    if args.satori is None and not args.from_anki:
        parser.error("Provide --satori and/or --from-anki")

    config_path = args.config.expanduser().resolve() if args.config else wk_deck_config_path()
    apply_conjugation_forms_from_config(load_wk_deck_config(config_path))

    if args.output is None:
        output_dir = REPO_ROOT / "out"
        output_path = output_dir / IMMERSION_CONJ_EXPORT_FILENAME
    else:
        output = args.output.expanduser().resolve()
        if output.suffix.lower() == ".apkg":
            output_dir = output.parent
            output_path = output
        else:
            output_dir = output
            output_path = output_dir / IMMERSION_CONJ_EXPORT_FILENAME

    satori_csv = args.satori.expanduser().resolve() if args.satori else None
    if satori_csv is not None and not satori_csv.is_file():
        print(f"Satori CSV not found: {satori_csv}", file=sys.stderr)
        return 1

    apkg_path, deck, drills, lemmas = build_immersion_conjugations(
        output_dir,
        satori_csv=satori_csv,
        anki_connect_url=args.anki_connect if args.from_anki else None,
        wk_index_path=args.wk_index.expanduser().resolve(),
        jmdict_index_path=(
            args.jmdict_index.expanduser().resolve()
            if args.jmdict_index
            else default_jmdict_index_path()
        ),
        jmdict_json_path=(
            args.jmdict.expanduser().resolve() if args.jmdict else default_jmdict_json_path()
        ),
        download_jmdict=not args.no_download_jmdict,
        max_cards=args.max_cards,
    )
    if output_path != apkg_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        apkg_path.replace(output_path)
        apkg_path = output_path

    sources = sorted({lemma.source for lemma in lemmas})
    print(
        f"Wrote {len(deck.notes)} conjugation notes "
        f"({len(drills)} drills from {len(lemmas)} lemmas; sources={sources}) → {apkg_path}"
    )
    print("Import in Anki, then study from Immersion · Conjugations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
