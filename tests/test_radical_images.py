"""Tests for WaniKani image-only radical download URL selection."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wk_decks import (
    WANIKANI_CDN_SUBJECT_IMAGE_URL,
    ensure_radical_image_media,
    radical_image_download_candidates,
    wanikani_files_url_is_downloadable,
)

YURT_RADICAL = {
    "id": 8787,
    "object": "radical",
    "data": {
        "characters": None,
        "slug": "yurt",
        "character_images": [
            {
                "url": "https://files.wanikani.com/vf859kbh7qlommu4w46t7d9fqjdz",
                "content_type": "image/png",
                "metadata": {"style_name": "128px"},
            },
            {
                "url": "https://files.wanikani.com/15z81qc4c77tmjeypri69yrtipgd",
                "content_type": "image/svg+xml",
                "metadata": {"style_name": "128px"},
            },
        ],
    },
}


class RadicalImageCandidatesTest(unittest.TestCase):
    def test_skips_blocked_png_files_wanikani_url(self) -> None:
        png_url = "https://files.wanikani.com/vf859kbh7qlommu4w46t7d9fqjdz"
        self.assertFalse(
            wanikani_files_url_is_downloadable(png_url, "image/png"),
        )

    def test_allows_svg_files_wanikani_url(self) -> None:
        svg_url = "https://files.wanikani.com/15z81qc4c77tmjeypri69yrtipgd"
        self.assertTrue(
            wanikani_files_url_is_downloadable(svg_url, "image/svg+xml"),
        )

    def test_yurt_prefers_svg_then_cdn(self) -> None:
        candidates = radical_image_download_candidates(YURT_RADICAL)
        urls = [url for url, _ext in candidates]
        self.assertEqual(
            urls[0],
            "https://files.wanikani.com/15z81qc4c77tmjeypri69yrtipgd",
        )
        self.assertIn(
            WANIKANI_CDN_SUBJECT_IMAGE_URL.format(subject_id=8787, slug="yurt"),
            urls,
        )
        self.assertNotIn(
            "https://files.wanikani.com/vf859kbh7qlommu4w46t7d9fqjdz",
            urls,
        )


class EnsureRadicalImageMediaTest(unittest.TestCase):
    @patch("wk_decks.requests.get")
    def test_downloads_first_working_candidate(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.content = b"<svg></svg>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        cache_dir = REPO_ROOT / ".wk_cache" / "radical_media_test"
        if cache_dir.exists():
            for path in cache_dir.glob("wk-radical-8787.*"):
                path.unlink()

        with patch("wk_decks.RADICAL_MEDIA_CACHE_DIR", cache_dir):
            result = ensure_radical_image_media(YURT_RADICAL)

        self.assertIsNotNone(result)
        media_name, path = result  # type: ignore[misc]
        self.assertEqual(media_name, "wk-radical-8787.svg")
        self.assertTrue(path.exists())
        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        self.assertIn("15z81qc4c77tmjeypri69yrtipgd", called_url)


if __name__ == "__main__":
    unittest.main()
