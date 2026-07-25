#!/usr/bin/env python3
"""
One-shot Satori refresh: build cloze + conjugations, push templates, regenerate TTS.

Typical use (Anki open with AnkiConnect; VOICEVOX running for TTS):

  python3 scripts/refresh_satori.py /path/to/satori_export.csv
  python3 scripts/refresh_satori.py export.csv --from-anki
  python3 scripts/refresh_satori.py export.csv --skip-tts
  python3 scripts/refresh_satori.py export.csv --no-force-tts   # only fill missing audio

Steps:
  1. Build Immersion · Satori cloze .apkg
  2. Build Immersion · Conjugations .apkg (CSV ± live Anki mines)
  3. Optionally open Anki import dialogs for those packages
  4. Push Satori card templates via AnkiConnect
  5. Synthesize / regenerate sentence + target TTS for WK Satori Immersion
  6. Unlock Satori immersion closure in core new queues
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"


def run_step(label: str, argv: list[str]) -> None:
    print(f"\n=== {label} ===")
    print("+", " ".join(argv))
    result = subprocess.run(argv, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        raise SystemExit(f"Step failed ({label}) with exit {result.returncode}")


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode())
    if payload.get("error"):
        raise RuntimeError(f"AnkiConnect {action}: {payload['error']}")
    return payload.get("result")


def anki_reachable(base_url: str) -> bool:
    try:
        anki_connect(base_url, "version")
        return True
    except (urllib.error.URLError, RuntimeError, TimeoutError, json.JSONDecodeError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Satori Reader CSV export")
    parser.add_argument(
        "--from-anki",
        action="store_true",
        help="Also pull Shadowing/Yomitan/Satori lemmas from the live collection for conjugations",
    )
    parser.add_argument(
        "--anki-connect",
        default=DEFAULT_ANKI_CONNECT,
        help=f"AnkiConnect URL (default: {DEFAULT_ANKI_CONNECT})",
    )
    parser.add_argument(
        "--skip-import-dialogs",
        action="store_true",
        help="Do not open Anki's import dialog for the built .apkg files",
    )
    parser.add_argument(
        "--skip-conjugations",
        action="store_true",
        help="Skip Immersion · Conjugations rebuild",
    )
    parser.add_argument(
        "--skip-tts",
        action="store_true",
        help="Skip sentence/target TTS synthesis",
    )
    parser.add_argument(
        "--no-force-tts",
        action="store_true",
        help="Only synthesize missing audio (default is --force regenerate)",
    )
    parser.add_argument(
        "--skip-template",
        action="store_true",
        help="Skip pushing Satori card templates",
    )
    parser.add_argument(
        "--skip-unlock",
        action="store_true",
        help="Skip unlocking the Satori immersion closure",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "out",
        help="Directory for built .apkg files (default: out/)",
    )
    args = parser.parse_args(argv)

    csv_path = args.csv.expanduser().resolve()
    if not csv_path.is_file():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cloze_apkg = output_dir / "wk_satori.apkg"
    conj_apkg = output_dir / "wk_immersion_conjugations.apkg"
    py = sys.executable

    run_step(
        "Build Immersion · Satori cloze deck",
        [
            py,
            str(SCRIPT_DIR / "import_satori.py"),
            str(csv_path),
            "-o",
            str(cloze_apkg),
        ],
    )

    if not args.skip_conjugations:
        conj_cmd = [
            py,
            str(SCRIPT_DIR / "import_immersion_conjugations.py"),
            "--satori",
            str(csv_path),
            "-o",
            str(conj_apkg),
        ]
        if args.from_anki:
            conj_cmd.append("--from-anki")
            conj_cmd.extend(["--anki-connect", args.anki_connect])
        run_step("Build Immersion · Conjugations deck", conj_cmd)

    anki_up = anki_reachable(args.anki_connect)
    if not anki_up:
        print(
            "\nAnkiConnect not reachable — packages are built; import them in Anki, then re-run "
            "with the same CSV and --skip-conjugations if you only need TTS/templates:\n"
            f"  {cloze_apkg}\n"
            + (f"  {conj_apkg}\n" if not args.skip_conjugations else "")
            + f"  AnkiConnect URL: {args.anki_connect}"
        )
        return 0

    if not args.skip_import_dialogs:
        for path, label in (
            (cloze_apkg, "Satori cloze"),
            (None if args.skip_conjugations else conj_apkg, "Immersion conjugations"),
        ):
            if path is None or not path.is_file():
                continue
            print(f"\n=== Open Anki import dialog ({label}) ===")
            print(f"  {path}")
            try:
                anki_connect(args.anki_connect, "guiImportFile", path=str(path))
            except RuntimeError as exc:
                print(f"  Warning: could not open import dialog: {exc}")
                print("  Import the file manually (File → Import), then continue.")

    if not args.skip_template:
        run_step(
            "Push Satori card templates",
            [
                py,
                str(SCRIPT_DIR / "push_satori_template_ankiconnect.py"),
                "--anki-connect",
                args.anki_connect,
            ],
        )

    if not args.skip_tts:
        tts_cmd = [
            py,
            str(SCRIPT_DIR / "synthesize_immersion_sentence_audio.py"),
            "--anki-connect",
            args.anki_connect,
            "--note-type",
            "WK Satori Immersion",
        ]
        if not args.no_force_tts:
            tts_cmd.append("--force")
        run_step("Synthesize Satori sentence/target TTS", tts_cmd)

    if not args.skip_unlock:
        run_step(
            "Unlock Satori immersion closure",
            [py, str(SCRIPT_DIR / "unlock_satori_closure_ankiconnect.py")],
        )

    print("\nDone.")
    print(f"  Cloze package:         {cloze_apkg}")
    if not args.skip_conjugations:
        print(f"  Conjugations package:  {conj_apkg}")
    print("  Study: Immersion · Satori / Immersion · Conjugations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
