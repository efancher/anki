#!/usr/bin/env python3
"""
One-shot Satori refresh: live-import cloze notes, conjugations, TTS, unlock.

Typical use (Anki open with AnkiConnect; VOICEVOX running for TTS):

  python3 scripts/refresh_satori.py /path/to/satori_export.csv
  python3 scripts/refresh_satori.py export.csv --from-anki
  python3 scripts/refresh_satori.py export.csv --skip-tts
  python3 scripts/refresh_satori.py export.csv --no-force-tts   # only fill missing audio
  python3 scripts/refresh_satori.py export.csv --write-apkg    # also emit out/wk_satori.apkg

Steps:
  1. Live-import Immersion · Satori cloze notes via AnkiConnect (preserve audio)
  2. Build Immersion · Conjugations .apkg (CSV ± live Anki mines)
  3. Optionally open Anki import dialog for conjugations only
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
        help="Do not open Anki's import dialog for the conjugations .apkg",
    )
    parser.add_argument(
        "--write-apkg",
        action="store_true",
        help="Also write out/wk_satori.apkg (live import is still the source of truth)",
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

    anki_up = anki_reachable(args.anki_connect)
    if not anki_up:
        print(
            "\nAnkiConnect not reachable — open Anki with AnkiConnect, then re-run.\n"
            f"  AnkiConnect URL: {args.anki_connect}",
            file=sys.stderr,
        )
        return 1

    live_cmd = [
        py,
        str(SCRIPT_DIR / "import_satori.py"),
        str(csv_path),
        "--anki-connect",
        args.anki_connect,
    ]
    if args.write_apkg:
        live_cmd.extend(["--apkg", "-o", str(cloze_apkg)])
    run_step("Live-import Immersion · Satori cloze notes", live_cmd)

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

        if not args.skip_import_dialogs and conj_apkg.is_file():
            print("\n=== Open Anki import dialog (Immersion conjugations) ===")
            print(f"  {conj_apkg}")
            try:
                anki_connect(args.anki_connect, "guiImportFile", path=str(conj_apkg))
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
    print("  Cloze notes: live in Immersion · Satori (WK Satori Immersion)")
    if args.write_apkg:
        print(f"  Cloze package:         {cloze_apkg}")
    if not args.skip_conjugations:
        print(f"  Conjugations package:  {conj_apkg}")
    print("  Study: Immersion · Satori / Immersion · Conjugations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
