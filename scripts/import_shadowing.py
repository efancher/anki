#!/usr/bin/env python3
"""
Build Immersion · Shadowing Anki packages from a shadowmine project or a
Glossbook mining ZIP.

Works from any clone of this repo:

  # Preferred: curated selections from Glossbook
  python3 scripts/import_shadowing.py ~/Downloads/fixture.mining.zip

  # Legacy: automatic WK matching from a shadowmine project directory
  python3 scripts/import_shadowing.py ~/shadowing/cli/projects/VIDEO_ID
  python3 scripts/import_shadowing.py /path/to/project -o out/
  python3 scripts/import_shadowing.py /path/to/project --skip-auto-caption

Requires out/wk_mining_vocab_index.json (or --wk-index) for WK matching.
Optional: install fugashi + unidic-lite for better morphology / candidate POS
filtering on legacy directory imports. Prefer the shadowing CLI venv:

  ~/shadowing/cli/.venv/bin/python scripts/import_shadowing.py ~/shadowing/cli/projects/VIDEO_ID

Then import the .apkg files in Anki. Do not enable "Update existing notes"
just to refresh templates — that can blank media fields. Full checklist:
docs/shadowing_mining.md
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

from shadowing_decks import (  # noqa: E402
    build_shadowing_decks,
    load_default_wk_index,
    load_shadowing_input,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "project",
        type=Path,
        help=(
            "Shadowing project directory (source.json + sentences.json) "
            "or a Glossbook .mining.zip package"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output directory for .apkg files (default: <repo>/out)",
    )
    parser.add_argument(
        "--wk-index",
        type=Path,
        default=REPO_ROOT / "out" / "wk_mining_vocab_index.json",
        help="WK mining vocab index JSON (default: out/wk_mining_vocab_index.json)",
    )
    parser.add_argument(
        "--skip-auto-caption",
        action="store_true",
        help="Skip sentences still labeled transcriptStatus=auto-caption",
    )
    args = parser.parse_args(argv)

    project_path = args.project.expanduser().resolve()
    try:
        project = load_shadowing_input(project_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Could not load project: {exc}", file=sys.stderr)
        return 1

    output_dir = (args.output or (REPO_ROOT / "out")).expanduser().resolve()
    wk_index_path = args.wk_index.expanduser().resolve()
    wk_index = load_default_wk_index(wk_index_path if wk_index_path.is_file() else None)
    if not (wk_index.get("by_expression") or {}):
        print(
            f"Warning: WK index empty or missing ({wk_index_path}). "
            "WK cloze matching will produce no cards until you generate "
            "out/wk_mining_vocab_index.json.",
            file=sys.stderr,
        )

    wk_path, cand_path, stats = build_shadowing_decks(
        project,
        output_dir,
        wk_index=wk_index,
        include_auto_caption=not args.skip_auto_caption,
    )

    mode = "curated mining package" if project.curated else "automatic project import"
    print(f"Source: {project.source.title} ({project.source.source_id}) [{mode}]")
    print(
        f"Sentences: {stats.sentences} · WK matches: {stats.wk_matches} · "
        f"WK notes: {stats.wk_notes} · candidates: {stats.candidate_notes}"
    )
    if stats.curated_selections:
        print(f"Curated selections: {stats.curated_selections}")
    if stats.missing_clips:
        print(f"Missing clips: {stats.missing_clips}", file=sys.stderr)
    if stats.skipped_auto_caption:
        print(f"Skipped auto-caption sentences: {stats.skipped_auto_caption}")
    print(f"Wrote {stats.wk_notes} notes → {wk_path}")
    print(f"Wrote {stats.candidate_notes} notes → {cand_path}")
    print("Import both .apkg files in Anki (Add / update note types only).")
    print("Then restart Anki or run Tools → WK Adjust New Limits for priority.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
