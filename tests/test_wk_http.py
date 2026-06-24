"""Tests for WaniKani HTTP helpers in wk_decks.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import wk_is_cloudflare_block


class MockResponse:
    def __init__(self, status_code: int, text: str = "", headers: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class WkHttpTests(unittest.TestCase):
    def test_cloudflare_block_detects_challenge_page(self) -> None:
        response = MockResponse(
            403,
            "<!DOCTYPE html><html><title>Just a moment...</title></html>",
            {"Content-Type": "text/html"},
        )
        self.assertTrue(wk_is_cloudflare_block(response))

    def test_json_403_is_not_cloudflare(self) -> None:
        response = MockResponse(403, '{"error":"Forbidden"}', {"Content-Type": "application/json"})
        self.assertFalse(wk_is_cloudflare_block(response))


if __name__ == "__main__":
    unittest.main()
