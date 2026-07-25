"""
Immersion lemmas → Immersion · Conjugations drills.

Sources: Satori CSV/notes, Shadowing, Yomitan. POS via Satori fields, WK index,
then offline JMDict. Reuses wk_decks conjugate_* engine.
"""

from __future__ import annotations

import html
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

import genanki

from jmdict_pos import (
    load_or_build_jmdict_pos_index,
    lookup_jmdict_word_class,
    pos_string_to_word_class,
)
from mining_vocab_index import load_mining_vocab_index, lookup_wk_vocab
from satori_conjugation_decks import (
    SATORI_CONJ_DECK_KEY,
    satori_pos_to_word_class,
)
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

IMMERSION_CONJ_KIND = "immersion-conjugation"
IMMERSION_CONJ_TAG = "immersion-conjugation"
IMMERSION_CONJ_EXPORT_FILENAME = "wk_immersion_conjugations.apkg"
# Reuse stable deck id from Satori conjugations pack.
IMMERSION_CONJ_DECK_KEY = SATORI_CONJ_DECK_KEY

SOURCE_TAG_SATORI = "satori-mining"
SOURCE_TAG_SHADOWING = "shadowing-mining"
SOURCE_TAG_YOMITAN = "yomitan-mining"

DEFAULT_ANKI_CONNECT = "http://127.0.0.1:8765"

_POS_LIST_FOR_MOCK = {
    "godan": ["godan verb"],
    "ichidan": ["ichidan verb"],
    "suru_verb": ["する verb"],
    "irregular_verb": ["intransitive verb"],
    "i_adjective": ["い adjective"],
    "na_adjective": ["な adjective"],
}


@dataclass(frozen=True)
class ImmersionLemma:
    expression: str
    reading: str
    meaning: str
    word_class: str
    source: str
    source_id: str
    wk_subject_id: str = ""
    prerequisite_ids: str = ""


@dataclass(frozen=True)
class ImmersionConjugationDrill:
    lemma_id: str
    form_key: str
    prompt: str
    dict_expr: str
    dict_reading: str
    conj_expr: str
    conj_reading: str
    word_class: str
    meaning: str
    source: str
    wk_subject_id: str = ""
    prerequisite_ids: str = ""


def lemma_key(expression: str, reading: str) -> Tuple[str, str]:
    return ((expression or "").strip(), (reading or "").strip())


def normalize_suru_lemma(
    expression: str,
    reading: str,
    word_class: str,
) -> Tuple[str, str, str]:
    """Ensure suru_verb lemmas end with する so conjugate_suru works."""
    expr = (expression or "").strip()
    read = (reading or "").strip()
    if word_class != "suru_verb":
        return expr, read, word_class
    if read.endswith("する"):
        if expr and not expr.endswith("する"):
            return expr + "する", read, word_class
        return expr or read, read, word_class
    if not read:
        return expr, read, word_class
    return (
        (expr + "する") if expr and not expr.endswith("する") else (expr or (read + "する")),
        read + "する",
        word_class,
    )


def resolve_word_class(
    expression: str,
    reading: str,
    *,
    parts_of_speech: str = "",
    wk_parts_of_speech: Optional[Sequence[str]] = None,
    jmdict_index: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    if parts_of_speech:
        word_class = satori_pos_to_word_class(parts_of_speech)
        if word_class:
            return word_class
    if wk_parts_of_speech:
        joined = ";".join(str(item) for item in wk_parts_of_speech if str(item).strip())
        word_class = pos_string_to_word_class(joined)
        if word_class:
            return word_class
    if jmdict_index is not None:
        return lookup_jmdict_word_class(expression, reading, dict(jmdict_index))
    return None


def _wk_entry_fields(
    expression: str,
    reading: str,
    wk_index: Optional[dict],
) -> Tuple[str, str, List[str], str]:
    if not wk_index:
        return "", "", [], ""
    entry = lookup_wk_vocab(expression, reading, wk_index)
    if not entry:
        return "", "", [], ""
    return (
        str(entry.get("id") or ""),
        str(entry.get("prerequisite_ids") or ""),
        list(entry.get("parts_of_speech") or []),
        str(entry.get("meaning") or ""),
    )


def lemmas_from_satori_cards(
    cards: Sequence[SatoriCard],
    *,
    wk_index: Optional[dict] = None,
    jmdict_index: Optional[Mapping[str, str]] = None,
) -> List[ImmersionLemma]:
    lemmas: List[ImmersionLemma] = []
    for card in cards:
        expr = (card.expression or "").strip()
        reading = (card.reading or "").strip()
        if not expr or not reading:
            continue
        wk_id, prereqs, wk_pos, wk_meaning = _wk_entry_fields(expr, reading, wk_index)
        word_class = resolve_word_class(
            expr,
            reading,
            parts_of_speech=card.parts_of_speech,
            wk_parts_of_speech=wk_pos,
            jmdict_index=jmdict_index,
        )
        if not word_class:
            continue
        if word_class == "irregular_verb" and reading not in {"する", "くる"} and not reading.endswith("する"):
            continue
        expr, reading, word_class = normalize_suru_lemma(expr, reading, word_class)
        meaning = (card.english or "").strip() or wk_meaning
        lemmas.append(
            ImmersionLemma(
                expression=expr,
                reading=reading,
                meaning=meaning,
                word_class=word_class,
                source="satori",
                source_id=card.card_id or f"{expr}|{reading}",
                wk_subject_id=wk_id,
                prerequisite_ids=prereqs,
            )
        )
    return lemmas


def lemmas_from_anki_notes(
    notes: Sequence[Mapping[str, object]],
    *,
    wk_index: Optional[dict] = None,
    jmdict_index: Optional[Mapping[str, str]] = None,
) -> List[ImmersionLemma]:
    lemmas: List[ImmersionLemma] = []
    for note in notes:
        fields = note.get("fields") if isinstance(note.get("fields"), dict) else {}
        tags = {str(tag) for tag in (note.get("tags") or [])}

        def field_value(name: str) -> str:
            raw = fields.get(name) if isinstance(fields, dict) else None
            if isinstance(raw, dict):
                return str(raw.get("value") or "").strip()
            return str(raw or "").strip()

        expr = field_value("Expression")
        reading = field_value("Reading")
        if not expr or not reading:
            continue
        if SOURCE_TAG_SATORI in tags:
            source = "satori"
        elif SOURCE_TAG_SHADOWING in tags:
            source = "shadowing"
        elif SOURCE_TAG_YOMITAN in tags:
            source = "yomitan"
        else:
            continue

        wk_id = field_value("WkSubjectId")
        prereqs = field_value("PrerequisiteIds")
        meaning = field_value("WkMeaning") or field_value("HintGlossary") or field_value("Glossary")
        wk_pos: List[str] = []
        if wk_index:
            linked_id, linked_prereqs, wk_pos, wk_meaning = _wk_entry_fields(expr, reading, wk_index)
            if not wk_id:
                wk_id = linked_id
            if not prereqs:
                prereqs = linked_prereqs
            if not meaning:
                meaning = wk_meaning

        parts = field_value("PartsOfSpeech")
        word_class = resolve_word_class(
            expr,
            reading,
            parts_of_speech=parts,
            wk_parts_of_speech=wk_pos,
            jmdict_index=jmdict_index,
        )
        if not word_class:
            continue
        if word_class == "irregular_verb" and reading not in {"する", "くる"} and not reading.endswith("する"):
            continue
        expr, reading, word_class = normalize_suru_lemma(expr, reading, word_class)
        note_id = str(note.get("noteId") or note.get("id") or f"{expr}|{reading}")
        lemmas.append(
            ImmersionLemma(
                expression=expr,
                reading=reading,
                meaning=meaning,
                word_class=word_class,
                source=source,
                source_id=note_id,
                wk_subject_id=wk_id,
                prerequisite_ids=prereqs,
            )
        )
    return lemmas


def dedupe_lemmas(lemmas: Sequence[ImmersionLemma]) -> List[ImmersionLemma]:
    """Prefer Satori POS richness, then WK-linked, then first seen."""
    source_rank = {"satori": 0, "shadowing": 1, "yomitan": 2}
    best: Dict[Tuple[str, str], ImmersionLemma] = {}
    for lemma in lemmas:
        key = lemma_key(lemma.expression, lemma.reading)
        existing = best.get(key)
        if existing is None:
            best[key] = lemma
            continue
        existing_score = (
            0 if existing.wk_subject_id else 1,
            source_rank.get(existing.source, 9),
        )
        new_score = (
            0 if lemma.wk_subject_id else 1,
            source_rank.get(lemma.source, 9),
        )
        if new_score < existing_score:
            best[key] = lemma
        elif new_score == existing_score and lemma.meaning and not existing.meaning:
            best[key] = lemma
    return list(best.values())


def collect_immersion_conjugation_drills(
    lemmas: Sequence[ImmersionLemma],
    *,
    max_cards: Optional[int] = None,
) -> List[ImmersionConjugationDrill]:
    drills: List[ImmersionConjugationDrill] = []
    seen_guids: Set[str] = set()
    for lemma in sorted(lemmas, key=lambda item: (item.expression, item.reading, item.source)):
        vocab = mock_vocab_for_conjugation(
            lemma.expression,
            lemma.reading,
            _POS_LIST_FOR_MOCK.get(lemma.word_class, []),
            vocab_id=abs(hash(lemma.source_id)) % (10**9),
        )
        for form_key, prompt in conjugation_forms_for_class(lemma.word_class):
            result = conjugate_vocab_form(vocab, lemma.word_class, form_key)
            if not result:
                continue
            conj_expr, conj_reading = result
            if conj_expr == lemma.expression and conj_reading == lemma.reading:
                continue
            lemma_id = f"{lemma.source}:{lemma.source_id}"
            guid = stable_guid(IMMERSION_CONJ_KIND, lemma_id, form_key)
            if guid in seen_guids:
                continue
            seen_guids.add(guid)
            drills.append(
                ImmersionConjugationDrill(
                    lemma_id=lemma_id,
                    form_key=form_key,
                    prompt=prompt,
                    dict_expr=lemma.expression,
                    dict_reading=lemma.reading,
                    conj_expr=conj_expr,
                    conj_reading=conj_reading,
                    word_class=lemma.word_class,
                    meaning=lemma.meaning,
                    source=lemma.source,
                    wk_subject_id=lemma.wk_subject_id,
                    prerequisite_ids=lemma.prerequisite_ids,
                )
            )
            if max_cards is not None and len(drills) >= max_cards:
                return drills
    return drills


def build_immersion_conjugation_deck(
    drills: Sequence[ImmersionConjugationDrill],
    output_dir: Path,
) -> Tuple[Path, object]:
    deck_id = DECK_IDS[IMMERSION_CONJ_DECK_KEY]
    deck_name = DECK_NAMES[IMMERSION_CONJ_DECK_KEY]
    deck = genanki.Deck(deck_id, deck_name)
    model = make_conjugation_model()
    template_label = MODEL_TEMPLATE_VERSIONS["conjugation"]

    for drill in drills:
        guid = stable_guid(IMMERSION_CONJ_KIND, drill.lemma_id, drill.form_key)
        class_label = conjugation_class_label(drill.word_class)
        tag_kind = (
            "conjugation-adjective"
            if drill.word_class in ADJECTIVE_CONJUGATION_WORD_CLASSES
            else "conjugation-verb"
        )
        meta = (
            f"Immersion · {drill.source} · {class_label} · "
            f"template {template_label} · {drill.form_key}"
        )
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
                html.escape(drill.wk_subject_id),
                html.escape(drill.prerequisite_ids),
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
                IMMERSION_CONJ_TAG,
                f"{drill.source}-conjugation",
                tag_kind,
                drill.word_class.replace("_", "-"),
                drill.form_key,
            ],
            guid=guid,
        )
        deck.add_note(note)

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / IMMERSION_CONJ_EXPORT_FILENAME
    write_apkg(deck, out)
    return out, deck


def anki_connect(base_url: str, action: str, **params: object) -> object:
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach AnkiConnect at {base_url}. "
            f"Is Anki open with AnkiConnect installed?\n{exc}"
        ) from exc
    if payload.get("error"):
        raise RuntimeError(f"AnkiConnect {action}: {payload['error']}")
    return payload.get("result")


def fetch_immersion_notes_from_anki(
    base_url: str = DEFAULT_ANKI_CONNECT,
    *,
    tags: Sequence[str] = (SOURCE_TAG_SATORI, SOURCE_TAG_SHADOWING, SOURCE_TAG_YOMITAN),
) -> List[dict]:
    clauses = [f"tag:{tag}" for tag in tags if tag]
    if not clauses:
        return []
    query = " OR ".join(clauses)
    note_ids = anki_connect(base_url, "findNotes", query=query) or []
    if not note_ids:
        return []
    notes: List[dict] = []
    batch_size = 50
    for start in range(0, len(note_ids), batch_size):
        chunk = note_ids[start : start + batch_size]
        notes.extend(anki_connect(base_url, "notesInfo", notes=chunk) or [])
    return notes


def build_immersion_conjugations(
    output_dir: Path,
    *,
    satori_csv: Optional[Path] = None,
    anki_connect_url: Optional[str] = None,
    wk_index_path: Optional[Path] = None,
    jmdict_index_path: Optional[Path] = None,
    jmdict_json_path: Optional[Path] = None,
    download_jmdict: bool = True,
    max_cards: Optional[int] = None,
) -> Tuple[Path, object, List[ImmersionConjugationDrill], List[ImmersionLemma]]:
    wk_index = None
    if wk_index_path and wk_index_path.is_file():
        wk_index = load_mining_vocab_index(wk_index_path)

    jmdict_index: Dict[str, str] = {}
    try:
        jmdict_index = load_or_build_jmdict_pos_index(
            index_path=jmdict_index_path,
            json_path=jmdict_json_path,
            download=download_jmdict,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        # CSV/Satori POS + WK may still be enough; surface warning via empty index.
        if not satori_csv and not anki_connect_url:
            raise
        print(f"Warning: JMDict POS index unavailable ({exc}); using Satori/WK POS only.")

    lemmas: List[ImmersionLemma] = []
    if satori_csv is not None:
        cards = parse_satori_csv(satori_csv, card_types=("JE",))
        lemmas.extend(
            lemmas_from_satori_cards(
                cards, wk_index=wk_index, jmdict_index=jmdict_index or None
            )
        )
    if anki_connect_url is not None:
        notes = fetch_immersion_notes_from_anki(anki_connect_url)
        lemmas.extend(
            lemmas_from_anki_notes(
                notes, wk_index=wk_index, jmdict_index=jmdict_index or None
            )
        )

    unique = dedupe_lemmas(lemmas)
    drills = collect_immersion_conjugation_drills(unique, max_cards=max_cards)
    apkg_path, deck = build_immersion_conjugation_deck(drills, output_dir)
    return apkg_path, deck, drills, unique
