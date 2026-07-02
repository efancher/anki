"""Tests for wk_deck_config.json loading and CLI override behavior."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from grammar_decks import (
    GRAMMAR_DEFAULT_EXAMPLES_PER_POINT,
    GRAMMAR_DEFAULT_MAX_JLPT,
)
from wk_decks import (
    DEFAULT_GENERATE_DECKS,
    decks_need_wk_review_statistics,
    load_wk_deck_config,
    parse_args,
    parser_defaults_from_config,
    wanted_decks,
    wk_deck_config_path,
)


class WkDeckConfigTests(unittest.TestCase):
    def test_parser_defaults_from_config_maps_grammar_section(self) -> None:
        defaults = parser_defaults_from_config(
            {
                "deck": "grammar",
                "only_started": True,
                "grammar": {
                    "max_jlpt": "N5",
                    "max_tae_kim_section": 3,
                    "max_tae_kim_lesson": "expressing-state-of-being",
                    "max_examples": 5,
                    "max_unknown_kanji": 2,
                    "no_wk_filter": True,
                    "sentence_audio": False,
                },
                "vocab_cloze": {"sentence_audio": True},
            }
        )
        self.assertEqual(defaults["deck"], "grammar")
        self.assertTrue(defaults["only_started"])
        self.assertEqual(defaults["grammar_max_jlpt"], "N5")
        self.assertEqual(defaults["grammar_max_tae_kim_section"], 3)
        self.assertEqual(defaults["grammar_max_tae_kim_lesson"], "expressing-state-of-being")
        self.assertEqual(defaults["grammar_max_examples"], 5)
        self.assertEqual(defaults["grammar_max_unknown_kanji"], 2)
        self.assertTrue(defaults["grammar_no_wk_filter"])
        self.assertFalse(defaults["grammar_sentence_audio"])
        self.assertTrue(defaults["sentence_audio"])

    def test_parser_defaults_from_config_maps_dictation_section(self) -> None:
        defaults = parser_defaults_from_config(
            {
                "dictation": {
                    "min_srs": 5,
                    "voice": "Kenichi",
                    "refresh_audio": True,
                },
            }
        )
        self.assertEqual(defaults["dictation_min_srs"], 5)
        self.assertEqual(defaults["dictation_voice"], "Kenichi")
        self.assertTrue(defaults["refresh_dictation_audio"])

    def test_parser_defaults_from_config_maps_core_section(self) -> None:
        defaults = parser_defaults_from_config(
            {
                "core": {
                    "bootstrap_scheduling": True,
                    "reading_audio": True,
                    "reading_voice": "Kyoko",
                    "refresh_reading_audio": False,
                },
            }
        )
        self.assertTrue(defaults["bootstrap_wk_scheduling"])
        self.assertTrue(defaults["reading_audio"])
        self.assertEqual(defaults["reading_voice"], "Kyoko")
        self.assertFalse(defaults["refresh_reading_audio"])

    def test_parser_defaults_from_config_fetch_wk_review_statistics(self) -> None:
        defaults = parser_defaults_from_config({"fetch_wk_review_statistics": True})
        self.assertTrue(defaults["fetch_wk_review_statistics"])

    def test_decks_need_wk_review_statistics_only_for_legacy_decks(self) -> None:
        self.assertFalse(decks_need_wk_review_statistics({"core", "grammar"}))
        self.assertTrue(decks_need_wk_review_statistics({"leeches"}))
        self.assertTrue(decks_need_wk_review_statistics({"all"} | {"leeches"}))

    def test_load_wk_deck_config_missing_file_returns_empty(self) -> None:
        missing = Path(tempfile.gettempdir()) / "wk_deck_config_missing_test.json"
        self.assertFalse(missing.is_file())
        self.assertEqual(load_wk_deck_config(missing), {})

    def test_wk_deck_config_path_resolves_relative_to_script(self) -> None:
        self.assertEqual(
            wk_deck_config_path("wk_deck_config.json"),
            Path(__file__).resolve().parent.parent / "wk_deck_config.json",
        )

    def test_parse_args_applies_config_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "my_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "grammar": {
                            "max_jlpt": "N5",
                            "max_examples": 5,
                        },
                        "only_started": True,
                    }
                ),
                encoding="utf-8",
            )
            args = parse_args(["--config", str(config_path)])
            self.assertEqual(args.grammar_max_jlpt, "N5")
            self.assertEqual(args.grammar_max_examples, 5)
            self.assertTrue(args.only_started)

    def test_parse_args_cli_override_wins_over_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "my_config.json"
            config_path.write_text(
                json.dumps({"grammar": {"max_jlpt": "N5", "max_examples": 5}}),
                encoding="utf-8",
            )
            args = parse_args(
                [
                    "--config",
                    str(config_path),
                    "--grammar-max-jlpt",
                    "N3",
                    "--grammar-max-examples",
                    "2",
                ]
            )
            self.assertEqual(args.grammar_max_jlpt, "N3")
            self.assertEqual(args.grammar_max_examples, 2)

    def test_parse_args_without_config_uses_hardcoded_defaults(self) -> None:
        args = parse_args([])
        self.assertEqual(args.grammar_max_jlpt, GRAMMAR_DEFAULT_MAX_JLPT)
        self.assertEqual(args.grammar_max_examples, GRAMMAR_DEFAULT_EXAMPLES_PER_POINT)
        self.assertFalse(args.only_started)
        self.assertFalse(args.bootstrap_wk_scheduling)
        self.assertFalse(args.fetch_wk_review_statistics)

    def test_wanted_decks_uses_generate_decks_from_config(self) -> None:
        args = parse_args([])
        args.deck = "all"
        args.generate_decks = ["grammar", "vocab-cloze"]
        self.assertEqual(wanted_decks(args), {"grammar", "vocab-cloze"})

    def test_wanted_decks_all_without_config_uses_default_generate_list(self) -> None:
        args = parse_args([])
        args.deck = "all"
        args.generate_decks = None
        self.assertEqual(wanted_decks(args), set(DEFAULT_GENERATE_DECKS))


if __name__ == "__main__":
    unittest.main()
