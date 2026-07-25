"""Tests for immersion conjugation collector and form allowlist."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from immersion_conjugation_decks import (
    ImmersionLemma,
    collect_immersion_conjugation_drills,
    dedupe_lemmas,
    lemmas_from_anki_notes,
    lemmas_from_satori_cards,
    normalize_suru_lemma,
    resolve_word_class,
)
from jmdict_pos import build_jmdict_pos_index
from satori_decks import SatoriCard
from wk_decks import (
    conjugation_forms_for_class,
    set_conjugation_forms_allowlist,
)


SAMPLE_JMDICT = [
    {
        "id": "1",
        "kanji": [{"text": "食べる"}],
        "kana": [{"text": "たべる"}],
        "sense": [{"partOfSpeech": ["v1"]}],
    },
    {
        "id": "2",
        "kanji": [{"text": "書く"}],
        "kana": [{"text": "かく"}],
        "sense": [{"partOfSpeech": ["v5k"]}],
    },
]


class ImmersionConjugationTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_conjugation_forms_allowlist(None)

    def test_resolve_prefers_satori_then_jmdict(self) -> None:
        index = build_jmdict_pos_index(SAMPLE_JMDICT)
        self.assertEqual(
            resolve_word_class("食べる", "たべる", parts_of_speech="v1"),
            "ichidan",
        )
        self.assertEqual(
            resolve_word_class("書く", "かく", jmdict_index=index),
            "godan",
        )
        self.assertEqual(
            resolve_word_class(
                "食べる",
                "たべる",
                wk_parts_of_speech=["ichidan verb"],
            ),
            "ichidan",
        )

    def test_normalize_suru(self) -> None:
        expr, reading, word_class = normalize_suru_lemma("勉強", "べんきょう", "suru_verb")
        self.assertEqual((expr, reading, word_class), ("勉強する", "べんきょうする", "suru_verb"))

    def test_dedupe_prefers_wk_linked_satori(self) -> None:
        lemmas = dedupe_lemmas(
            [
                ImmersionLemma(
                    expression="食べる",
                    reading="たべる",
                    meaning="eat",
                    word_class="ichidan",
                    source="yomitan",
                    source_id="1",
                ),
                ImmersionLemma(
                    expression="食べる",
                    reading="たべる",
                    meaning="to eat",
                    word_class="ichidan",
                    source="satori",
                    source_id="2",
                    wk_subject_id="99",
                ),
            ]
        )
        self.assertEqual(len(lemmas), 1)
        self.assertEqual(lemmas[0].source, "satori")
        self.assertEqual(lemmas[0].wk_subject_id, "99")

    def test_satori_and_anki_lemmas_produce_new_forms(self) -> None:
        cards = [
            SatoriCard(
                card_id="eat",
                card_type="JE",
                expression="食べる",
                reading="たべる",
                expression_furigana="",
                english="to eat",
                parts_of_speech="v1",
                sentence="食べる。",
                sentence_furigana="",
                sentence_translation="",
                user_notes="",
            )
        ]
        lemmas = lemmas_from_satori_cards(cards)
        drills = collect_immersion_conjugation_drills(lemmas)
        form_keys = {drill.form_key for drill in drills}
        self.assertIn("potential", form_keys)
        self.assertIn("plain_past_negative", form_keys)
        self.assertIn("tara_form", form_keys)

    def test_anki_notes_use_jmdict(self) -> None:
        index = build_jmdict_pos_index(SAMPLE_JMDICT)
        notes = [
            {
                "noteId": 1,
                "tags": ["yomitan-mining"],
                "fields": {
                    "Expression": {"value": "書く"},
                    "Reading": {"value": "かく"},
                    "WkMeaning": {"value": "to write"},
                },
            }
        ]
        lemmas = lemmas_from_anki_notes(notes, jmdict_index=index)
        self.assertEqual(len(lemmas), 1)
        self.assertEqual(lemmas[0].word_class, "godan")
        self.assertEqual(lemmas[0].source, "yomitan")

    def test_form_allowlist_filters(self) -> None:
        set_conjugation_forms_allowlist({"verbs": ["te_form", "potential"]})
        forms = conjugation_forms_for_class("ichidan")
        self.assertEqual([key for key, _ in forms], ["te_form", "potential"])
        set_conjugation_forms_allowlist(None)
        self.assertGreater(len(conjugation_forms_for_class("ichidan")), 2)


if __name__ == "__main__":
    unittest.main()
