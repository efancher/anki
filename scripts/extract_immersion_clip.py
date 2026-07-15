#!/usr/bin/env python3
"""
Extract a native audio clip from YouTube (or any yt-dlp URL) and optionally
attach it to an immersion note's SentenceAudio field via AnkiConnect.

Examples:
  # Write a clip only
  python3 scripts/extract_immersion_clip.py \\
    --url 'https://www.youtube.com/watch?v=…' \\
    --start 1:23.5 --end 1:26.8 \\
    -o /tmp/clip.mp3

  # Attach to a specific note
  python3 scripts/extract_immersion_clip.py \\
    --url 'https://www.youtube.com/watch?v=…' \\
    --start 83.5 --end 86.8 \\
    --note-id 1783784549740

  # Attach to the note selected in the Anki browser
  python3 scripts/extract_immersion_clip.py \\
    --url '…' --start 1:20 --end 1:24 --selected

Requires: yt-dlp, ffmpeg, Anki + AnkiConnect (for --note-id / --selected).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Sequence

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"
SENTENCE_AUDIO_FIELD = "SentenceAudio"
CLIP_FILENAME_PREFIX = "wk_immersion_clip_"


def parse_timestamp(value: str) -> float:
    """Parse seconds or m:ss / h:mm:ss (optional fractional seconds)."""
    text = value.strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = text.split(":")
    if not 2 <= len(parts) <= 3:
        raise argparse.ArgumentTypeError(f"Bad timestamp: {value!r}")
    try:
        nums = [float(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Bad timestamp: {value!r}") from exc
    if len(nums) == 2:
        minutes, seconds = nums
        return minutes * 60.0 + seconds
    hours, minutes, seconds = nums
    return hours * 3600.0 + minutes * 60.0 + seconds


def anki_connect(base_url: str, action: str, **params: object) -> object:
    request = urllib.request.Request(
        base_url,
        data=json.dumps({"action": action, "version": 6, "params": params}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach AnkiConnect at {base_url}. "
            f"Is Anki open with AnkiConnect installed?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise SystemExit(f"AnkiConnect {action}: {payload['error']}")
    return payload.get("result")


def require_binaries() -> None:
    missing = [name for name in ("yt-dlp", "ffmpeg") if shutil.which(name) is None]
    if missing:
        raise SystemExit(
            "Missing required tool(s): "
            + ", ".join(missing)
            + "\nInstall yt-dlp and ffmpeg, then retry."
        )


def download_and_clip(
    *,
    url: str,
    start: float,
    end: float,
    output: Path,
    cache_dir: Path,
) -> Path:
    if end <= start:
        raise SystemExit(f"--end ({end}) must be greater than --start ({start})")
    duration = end - start
    cache_dir.mkdir(parents=True, exist_ok=True)
    url_key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    full_audio = cache_dir / f"{url_key}_full.m4a"

    if not full_audio.is_file():
        print(f"Downloading audio via yt-dlp → {full_audio}", file=sys.stderr)
        subprocess.run(
            [
                "yt-dlp",
                "-f",
                "bestaudio/best",
                "-x",
                "--audio-format",
                "m4a",
                "--audio-quality",
                "0",
                "-o",
                str(full_audio),
                "--no-playlist",
                url,
            ],
            check=True,
        )
    else:
        print(f"Using cached audio {full_audio}", file=sys.stderr)

    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Clipping {start:.3f}s–{end:.3f}s → {output}", file=sys.stderr)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(full_audio),
            "-t",
            f"{duration:.3f}",
            "-vn",
            "-acodec",
            "libmp3lame",
            "-q:a",
            "2",
            str(output),
        ],
        check=True,
        capture_output=True,
    )
    return output


def attach_to_note(
    *,
    base_url: str,
    note_id: int,
    clip_path: Path,
) -> None:
    notes = anki_connect(base_url, "notesInfo", notes=[note_id]) or []
    if not notes:
        raise SystemExit(f"Note {note_id} not found")
    fields = (notes[0].get("fields") or {})
    if SENTENCE_AUDIO_FIELD not in fields:
        raise SystemExit(
            f"Note {note_id} has no {SENTENCE_AUDIO_FIELD} field "
            "(use WK Yomitan Immersion / WK Migaku Immersion)."
        )
    digest = hashlib.sha1(clip_path.read_bytes()).hexdigest()[:10]
    filename = f"{CLIP_FILENAME_PREFIX}{note_id}_{digest}.mp3"
    anki_connect(
        base_url,
        "storeMediaFile",
        filename=filename,
        path=str(clip_path.resolve()),
    )
    anki_connect(
        base_url,
        "updateNoteFields",
        note={
            "id": note_id,
            "fields": {SENTENCE_AUDIO_FIELD: f"[sound:{filename}]"},
        },
    )
    print(f"Attached {filename} to note {note_id} → {SENTENCE_AUDIO_FIELD}")


def resolve_note_id(base_url: str, note_id: Optional[int], selected: bool) -> Optional[int]:
    if note_id is not None:
        return note_id
    if not selected:
        return None
    ids = anki_connect(base_url, "guiSelectedNotes") or []
    if not ids:
        raise SystemExit("No notes selected in the Anki browser.")
    if len(ids) > 1:
        print(
            f"Multiple notes selected; attaching to the first ({ids[0]}).",
            file=sys.stderr,
        )
    return int(ids[0])


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", required=True, help="YouTube / yt-dlp URL")
    parser.add_argument("--start", required=True, type=parse_timestamp, help="Clip start")
    parser.add_argument("--end", required=True, type=parse_timestamp, help="Clip end")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write clip here (default: temp file, kept if not attaching)",
    )
    parser.add_argument("--note-id", type=int, default=None, help="Anki note id")
    parser.add_argument(
        "--selected",
        action="store_true",
        help="Use note(s) selected in the Anki browser",
    )
    parser.add_argument(
        "--anki-connect",
        default=DEFAULT_ANKI_CONNECT,
        help=f"AnkiConnect URL (default: {DEFAULT_ANKI_CONNECT})",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".wk_cache") / "youtube_audio",
        help="Cache directory for full downloaded audio",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    require_binaries()
    note_id = resolve_note_id(args.anki_connect, args.note_id, args.selected)

    with tempfile.TemporaryDirectory(prefix="wk_immersion_clip_") as tmp:
        default_out = Path(tmp) / "clip.mp3"
        clip_path = args.output or default_out
        download_and_clip(
            url=args.url,
            start=args.start,
            end=args.end,
            output=clip_path,
            cache_dir=args.cache_dir,
        )
        if note_id is not None:
            attach_to_note(
                base_url=args.anki_connect,
                note_id=note_id,
                clip_path=clip_path,
            )
        elif args.output is None:
            kept = Path.cwd() / f"immersion_clip_{int(args.start)}_{int(args.end)}.mp3"
            shutil.copy2(clip_path, kept)
            print(f"Wrote {kept}")
        else:
            print(f"Wrote {clip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
