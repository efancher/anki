"""
Satori Reader → Immersion · Satori Conjugations (forward drills).

Reuses wk_decks conjugate_* engine. Separate from WK conjugation packs.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import genanki

from satori_decks import SatoriCard, parse_satori_csv
from wk_decks import (
    ADJECTIVE_CONJUGATION_WORD_CLASSES,
    DECK_IDS,
    DECK_NAMES,
    MODEL_TEMPLATE_VERSIONS,
    conjugate_vocab_form,
    conjugation_build_html,
    conjugation_class_label,
    conjugation_forms_for_class,
    make_conjugation_model,
    mock_vocab_for_conjugation,
    stable_guid,
    write_apkg,
)

SATORI_CONJ_KIND = "satori-conjugation"
SATORI_CONJ_TAG = "satori-conjugation"
SATORI_CONJ_EXPORT_FILENAME = "wk_satori_conjugations.apkg"
SATORI_CONJ_DECK_KEY = "satori-conjugations"

_POS_SPLIT_RE = re.compile(r"[,;/|]+")


@dataclass(frozen=True)
class SatoriConjugationDrill:
    card_id: str
    form_key: str
    prompt: str
    dict_expr: str
    dict_reading: str
    conj_expr: str
    conj_reading: str
    word_class: str
    meaning: str


def _pos_tokens(raw: str) -> List[str]:
    text = (raw or "").strip().lower()
    if not text:
        return []
    tokens = [part.strip() for part in _POS_SPLIT_RE.split(text) if part.strip()]
    return tokens or [text]


def satori_pos_to_word_class(parts_of_speech: str) -> Optional[str]:
    """Map Satori/JMDict POS strings to internal conjugation word classes."""
    tokens = _pos_tokens(parts_of_speech)
    joined = " ".join(tokens)

    if any(token in {"adj-i", "adj-ix", "い adjective", "i-adjective", "i_adjective"} for token in tokens):
        return "i_adjective"
    if "い adjective" in joined or "i adjective" in joined:
        return "i_adjective"

    if any(token in {"adj-na", "な adjective", "na-adjective", "na_adjective"} for token in tokens):
        return "na_adjective"
    if "な adjective" in joined or "na adjective" in joined:
        return "na_adjective"

    if any(token in {"vk", "kuru", "irregular_verb"} for token in tokens) or "来る" in parts_of_speech:
        return "irregular_verb"

    if any(
        token.startswith("vs") or token in {"する verb", "suru", "suru_verb", "vs", "vs-i", "vs-s"}
        for token in tokens
    ):
        return "suru_verb"
    if "する verb" in joined or "suru verb" in joined:
        return "suru_verb"

    if any(token.startswith("v1") or token in {"ichidan", "ichidan verb"} for token in tokens):
        return "ichidan"
    if "ichidan" in joined:
        return "ichidan"

    if any(token.startswith("v5") or token in {"godan", "godan verb"} for token in tokens):
        return "godan"
    if "godan" in joined:
        return "godan"

    return None


def lemma_key(expression: str, reading: str) -> Tuple[str, str]:
    return ((expression or "").strip(), (reading or "").strip())


def load_wk_conjugation_lemmas(path: Optional[Path]) -> Set[Tuple[str, str]]:
    """Load optional JSON skip list: {"lemmas": [["食べる", "たべる"], ...]}."""
    if path is None or not path.is_file():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    lemmas = payload.get("lemmas") if isinstance(payload, dict) else payload
    out: Set[Tuple[str, str]] = set()
    for row in lemmas or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        out.add(lemma_key(str(row[0]), str(row[1])))
    return out


def collect_satori_conjugation_drills(
    cards: Sequence[SatoriCard],
    *,
    skip_lemmas: Optional[Set[Tuple[str, str]]] = None,
    max_cards: Optional[int] = None,
) -> List[SatoriConjugationDrill]:
    skip = skip_lemmas or set()
    drills: List[SatoriConjugationDrill] = []
    seen_guids: Set[str] = set()

    for card in cards:
        word_class = satori_pos_to_word_class(card.parts_of_speech)
        if not word_class:
            continue
        expr = (card.expression or "").strip()
        reading = (card.reading or "").strip()
        if not expr or not reading:
            continue
        if lemma_key(expr, reading) in skip:
            continue

        # Heuristic for する / くる when POS is generic irregular.
        if word_class == "irregular_verb" and reading not in {"する", "くる"} and not reading.endswith("する"):
            continue

        vocab = mock_vocab_for_conjugation(
            expr,
            reading,
            _pos_list_for_mock(word_class),
            vocab_id=abs(hash(card.card_id)) % (10**9),
        )
        meaning = (card.english or "").strip()
        for form_key, prompt in conjugation_forms_for_class(word_class):
            result = conjugate_vocab_form(vocab, word_class, form_key)
            if not result:
                continue
            conj_expr, conj_reading = result
            if conj_expr == expr and conj_reading == reading:
                continue
            guid = stable_guid(SATORI_CONJ_KIND, card.card_id or f"{expr}|{reading}", form_key)
            if guid in seen_guids:
                continue
            seen_guids.add(guid)
            drills.append(
                SatoriConjugationDrill(
                    card_id=card.card_id or f"{expr}|{reading}",
                    form_key=form_key,
                    prompt=prompt,
                    dict_expr=expr,
                    dict_reading=reading,
                    conj_expr=conj_expr,
                    conj_reading=conj_reading,
                    word_class=word_class,
                    meaning=meaning,
                )
            )
            if max_cards is not None and len(drills) >= max_cards:
                return drills
    return drills


def _pos_list_for_mock(word_class: str) -> List[str]:
    return {
        "godan": ["godan verb"],
        "ichidan": ["ichidan verb"],
        "suru_verb": ["する verb"],
        "irregular_verb": ["intransitive verb"],
        "i_adjective": ["い adjective"],
        "na_adjective": ["な adjective"],
    }.get(word_class, [])


def build_satori_conjugation_deck(
    drills: Sequence[SatoriConjugationDrill],
    output_dir: Path,
) -> Tuple[Path, genanki.Deck]:
    deck_id = DECK_IDS[SATORI_CONJ_DECK_KEY]
    deck_name = DECK_NAMES[SATORI_CONJ_DECK_KEY]
    deck = genanki.Deck(deck_id, deck_name)
    model = make_conjugation_model()
    template_label = MODEL_TEMPLATE_VERSIONS["conjugation"]

    for drill in drills:
        guid = stable_guid(SATORI_CONJ_KIND, drill.card_id, drill.form_key)
        class_label = conjugation_class_label(drill.word_class)
        tag_kind = (
            "conjugation-adjective"
            if drill.word_class in ADJECTIVE_CONJUGATION_WORD_CLASSES
            else "conjugation-verb"
        )
        meta = f"Satori · {class_label} · template {template_label} · {drill.form_key}"
        build_html = conjugation_build_html(
            drill.word_class,
            drill.form_key,
            drill.dict_expr,
            drill.dict_reading,
            drill.conj_expr,
            drill.conj_reading,
        )
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                "",  # WkSubjectId — none for Satori
                "",  # PrerequisiteIds
                html.escape(drill.prompt),
                html.escape(drill.dict_expr),
                html.escape(drill.dict_reading),
                html.escape(drill.meaning),
                html.escape(class_label),
                html.escape(drill.conj_expr),
                html.escape(drill.conj_reading),
                html.escape(drill.conj_reading),
                "",
                "",
                build_html,
                html.escape(meta),
            ],
            tags=[
                "immersion",
                SATORI_CONJ_TAG,
                tag_kind,
                drill.word_class.replace("_", "-"),
                drill.form_key,
            ],
            guid=guid,
        )
        deck.add_note(note)

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / SATORI_CONJ_EXPORT_FILENAME
    write_apkg(deck, out)
    return out, deck


def build_satori_conjugations_from_csv(
    csv_path: Path,
    output_dir: Path,
    *,
    skip_lemmas_path: Optional[Path] = None,
    max_cards: Optional[int] = None,
) -> Tuple[Path, genanki.Deck, List[SatoriConjugationDrill]]:
    cards = parse_satori_csv(csv_path, card_types=("JE",))
    skip = load_wk_conjugation_lemmas(skip_lemmas_path)
    drills = collect_satori_conjugation_drills(cards, skip_lemmas=skip, max_cards=max_cards)
    apkg_path, deck = build_satori_conjugation_deck(drills, output_dir)
    return apkg_path, deck, drills
