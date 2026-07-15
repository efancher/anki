#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_SCRIPT = REPO_ROOT / "scripts" / "extract_immersion_clip.py"
_SPEC = importlib.util.spec_from_file_location("extract_immersion_clip", _SCRIPT)
assert _SPEC and _SPEC.loader
_CLIP = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLIP)
parse_timestamp = _CLIP.parse_timestamp


class ExtractImmersionClipTests(unittest.TestCase):
    def test_parse_timestamp_seconds(self) -> None:
        self.assertEqual(parse_timestamp("83.5"), 83.5)

    def test_parse_timestamp_mm_ss(self) -> None:
        self.assertEqual(parse_timestamp("1:23.5"), 83.5)

    def test_parse_timestamp_hh_mm_ss(self) -> None:
        self.assertEqual(parse_timestamp("1:02:03"), 3723.0)


if __name__ == "__main__":
    unittest.main()
