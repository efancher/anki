#!/usr/bin/env python3
"""One-shot edge-tts synthesis for wk_immersion (run with system python3 + edge-tts)."""

from __future__ import annotations

import asyncio
import sys


async def _main(text: str, voice: str, out_path: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: edge_tts_once.py TEXT VOICE OUT.mp3")
    asyncio.run(_main(sys.argv[1], sys.argv[2], sys.argv[3]))
