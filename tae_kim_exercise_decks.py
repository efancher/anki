"""
tae_kim_exercise_decks.py

Build Japanese grammar exercise cloze decks from Tae Kim practice pages on
guidetojapanese.org (answers are in-page; no JavaScript required to scrape).

Cards match the grammar deck UX: production cloze, meaning hint on front,
formation on back, full Japanese answer + sentence audio on back.
"""

from __future__ import annotations

import hashlib
import html as html_module
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Set, Tuple

import genanki

from grammar_decks import (
    GrammarCardItem,
    grammar_form_hint,
    make_grammar_model,
    prepare_grammar_sentence_for_tts,
    production_hint_from_english,
)
from tae_kim_mapping import (
    TaeKimLesson,
    TaeKimSection,
    parse_tae_kim_lesson_cap,
    tae_kim_card_tags,
    tae_kim_lesson_by_slug,
    tae_kim_section_by_num,
    tae_kim_section_within_cap,
)
from wk_decks import (
    CACHE_DIR,
    CLOZE_BLANK_DISPLAY,
    DECK_NAMES,
    DEFAULT_SENTENCE_AUDIO_VOICE,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WK_SHARED_MEDIA_SUBDIR,
    ensure_sentence_audio_file,
    require_edge_tts,
    stable_guid,
    tts_audio_basename,
    write_apkg,
)

TAE_KIM_EXERCISE_CACHE_DIR = CACHE_DIR / "tae_kim_exercises"
TAE_KIM_EXERCISES_REGISTRY_FILENAME = "tae_kim_exercises.json"
TAE_KIM_EXERCISE_MEDIA_SUBDIR = "media/tae_kim_exercise"
TAE_KIM_EXERCISE_BASE_URL = "https://guidetojapanese.org/"
TAE_KIM_EXERCISE_FETCH_TIMEOUT_SECONDS = 60
TAE_KIM_EXERCISE_POINT_PREFIX = "tk-ex"

EXERCISE_DECK_ID = 2059400126
EXERCISE_DECK_NAME = DECK_NAMES["tae-kim-exercises"]
EXERCISE_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["grammar_cloze"]
EXERCISE_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["grammar_cloze"]

_SKIP_ANSWERS = frozenset({"", "n/a", "●", "\u00a0", "&nbsp;"})
_ENGLISH_PROMPT_RE = re.compile(r"^\d+\.\s*(.+)$")
_CONJUGATION_LABELS = frozenset(
    {"declarative", "negative", "past", "negative-past", "plain"}
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_HIDE_ANSWER_RE = re.compile(
    r'<span class="answerline">\s*<span class="hide">([^<]*)</span>\s*</span>',
    re.IGNORECASE,
)
_H2_SECTION_RE = re.compile(
    r'<h2 id="(part\d+)">([^<]+)</h2>',
    re.IGNORECASE,
)
_EXERCISE_DIV_RE = re.compile(
    r'<div id="(exercise\d+)">(.*?)</div>\s*(?=<h2|<div class="botmenu">)',
    re.IGNORECASE | re.DOTALL,
)
_EN_TO_JP_ROW_RE = re.compile(
    r"<tr>\s*<td>(?P<prompt>[^<]+)</td>\s*<td>＝</td>\s*"
    r'<td class="answerline"><span class="hide">(?P<answer>[^<]*)</span></td>\s*</tr>',
    re.IGNORECASE | re.DOTALL,
)
_CONJUGATION_BLOCK_RE = re.compile(
    r"<tr>\s*<td colspan=\"3\">\s*(?:\d+\.\s*)?<b>(?P<noun>[^<]+)</b>\s*</td>\s*</tr>"
    r"(?P<rows>.*?)(?=<tr><td><br /></td></tr>|<tr>\s*<td colspan=\"3\">|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_CONJUGATION_FORM_ROW_RE = re.compile(
    r"<tr>\s*<td>(?P<label>[^<]+)</td>\s*<td>=</td>\s*"
    r'<td class="answerline"><span class="hide">(?P<answer>[^<]*)</span></td>\s*</tr>',
    re.IGNORECASE,
)
_GRID_HEADER_RE = re.compile(
    r"<tr[^>]*>\s*(?P<headers>(?:<td[^>]*>[^<]+</td>\s*)+)</tr>",
    re.IGNORECASE,
)
_GRID_ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>(?P<stem>[^<]+)</td>(?P<cells>.*?)</tr>",
    re.IGNORECASE | re.DOTALL,
)
_QA_PAIR_RE = re.compile(
    r"<tr>\s*<td>(?P<question>Ｑ[\s\S]*?)</td>\s*</tr>\s*"
    r"<tr>\s*<td>[^<]*?<span class=\"answerline\"><span class=\"hide\">"
    r"(?P<answer>[^<]*)</span></span>(?P<suffix>[\s\S]*?)</td>\s*</tr>",
    re.IGNORECASE,
)
_PART1_VOCABULARY_SECTION_RE = re.compile(
    r'<h2 id="part1">Vocabulary used in this section</h2>(.*?)(?=<h2 id="part2">)',
    re.IGNORECASE | re.DOTALL,
)
_VOCAB_LIST_ITEM_WITH_READING_RE = re.compile(r"^(.+?)【[^】]+】")
_VOCAB_LIST_ITEM_TERM_RE = re.compile(r"^(.+?)\s+-\s+")


class ExercisePageSpec(NamedTuple):
    page: str
    chapter: str
    parent_lesson: str
    practice_lesson: str
    formation: str
    skip: bool


class ParsedExerciseItem(NamedTuple):
    exercise_id: str
    section_title: str
    formation: str
    cloze_sentence: str
    full_sentence: str
    sentence_en: str
    type_expression: str
    hint: str
    title: str


def tae_kim_exercises_registry_path() -> Path:
    return Path(__file__).resolve().parent / TAE_KIM_EXERCISES_REGISTRY_FILENAME


def load_tae_kim_exercise_page_specs() -> List[ExercisePageSpec]:
    payload = json.loads(tae_kim_exercises_registry_path().read_text(encoding="utf-8"))
    pages = payload.get("pages") or []
    specs: List[ExercisePageSpec] = []
    for entry in pages:
        specs.append(
            ExercisePageSpec(
                page=str(entry["page"]),
                chapter=str(entry["chapter"]),
                parent_lesson=str(entry["parent_lesson"]),
                practice_lesson=str(entry["practice_lesson"]),
                formation=str(entry.get("formation") or ""),
                skip=bool(entry.get("skip")),
            )
        )
    return specs


def exercise_cache_path(page: str) -> Path:
    stem = Path(page).stem
    return TAE_KIM_EXERCISE_CACHE_DIR / f"{stem}.json"


def fetch_tae_kim_exercise_html(page: str, *, refresh: bool = False) -> str:
    cache_path = exercise_cache_path(page)
    if cache_path.is_file() and not refresh:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return str(payload["html"])

    url = f"{TAE_KIM_EXERCISE_BASE_URL}{page}"
    try:
        with urllib.request.urlopen(url, timeout=TAE_KIM_EXERCISE_FETCH_TIMEOUT_SECONDS) as response:
            html_text = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        if cache_path.is_file():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return str(payload["html"])
        raise RuntimeError(
            f"Could not download Tae Kim exercise page {url}. "
            "Check network or use --refresh-cache after a successful download."
        ) from exc

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"page": page, "url": url, "html": html_text}, ensure_ascii=False),
        encoding="utf-8",
    )
    return html_text


def _strip_parenthetical_notes(text: str) -> str:
    return re.sub(r"\s*\([^)]+\)", "", text).strip()


def _qa_hint_from_question(question_html: str) -> str:
    question_plain = _plain_text(question_html)
    match = re.search(r"Ｑ\d+）\s*(.+)", question_plain)
    if match:
        return _strip_parenthetical_notes(match.group(1).strip())
    return _strip_parenthetical_notes(question_plain)


def _plain_text(fragment: str) -> str:
    text = _TAG_RE.sub("", fragment)
    text = html_module.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def vocabulary_term_from_list_item(text: str) -> Optional[str]:
    """Extract the Japanese term from a part1 vocabulary list item."""
    cleaned = text.strip()
    if not cleaned:
        return None
    match = _VOCAB_LIST_ITEM_WITH_READING_RE.match(cleaned)
    if match:
        return match.group(1).strip()
    match = _VOCAB_LIST_ITEM_TERM_RE.match(cleaned)
    if match:
        return match.group(1).strip()
    return None


def parse_tae_kim_vocabulary_section(html_text: str) -> List[str]:
    """Return deduplicated Japanese terms from the part1 vocabulary list on a practice page."""
    match = _PART1_VOCABULARY_SECTION_RE.search(html_text)
    if not match:
        return []
    terms: List[str] = []
    seen: Set[str] = set()
    for li_html in re.findall(r"<li>(.*?)</li>", match.group(1), re.IGNORECASE | re.DOTALL):
        term = vocabulary_term_from_list_item(_plain_text(li_html))
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _normalize_answer(answer: str) -> str:
    return _WS_RE.sub("", answer.strip())


def _is_skipped_answer(answer: str) -> bool:
    plain = answer.strip()
    if plain in _SKIP_ANSWERS:
        return True
    if plain.replace("\u00a0", "").replace(" ", "") in {"", "●"}:
        return True
    return False


def _inline_cloze_items(
    td_html: str,
    *,
    page_stem: str,
    section_title: str,
    formation: str,
    block_id: str,
    start_index: int,
) -> Tuple[List[ParsedExerciseItem], int]:
    items: List[ParsedExerciseItem] = []
    index = start_index
    for match in _HIDE_ANSWER_RE.finditer(td_html):
        answer_raw = match.group(1)
        if _is_skipped_answer(answer_raw):
            continue
        answer = _normalize_answer(answer_raw)
        if not answer:
            continue
        full_html = (
            td_html[: match.start()]
            + answer_raw
            + td_html[match.end() :]
        )
        cloze_html = (
            td_html[: match.start()]
            + CLOZE_BLANK_DISPLAY
            + td_html[match.end() :]
        )
        full_sentence = _plain_text(full_html)
        cloze_sentence = _plain_text(cloze_html)
        if not full_sentence or CLOZE_BLANK_DISPLAY not in cloze_sentence:
            continue
        hint = full_sentence.replace(answer, "").strip(" 、，。.")
        if not hint:
            hint = section_title
        items.append(
            ParsedExerciseItem(
                exercise_id=f"{page_stem}-{block_id}-{index}",
                section_title=section_title,
                formation=formation,
                cloze_sentence=cloze_sentence,
                full_sentence=full_sentence,
                sentence_en=hint,
                type_expression=answer,
                hint=hint,
                title=f"{section_title} · {index}",
            )
        )
        index += 1
    return items, index


def _parse_en_to_jp_rows(
    block_html: str,
    *,
    page_stem: str,
    section_title: str,
    formation: str,
    block_id: str,
    start_index: int,
) -> Tuple[List[ParsedExerciseItem], int]:
    items: List[ParsedExerciseItem] = []
    index = start_index
    for match in _EN_TO_JP_ROW_RE.finditer(block_html):
        prompt = _plain_text(match.group("prompt"))
        answer = _normalize_answer(match.group("answer"))
        if not prompt or not answer or _is_skipped_answer(answer):
            continue
        prompt_match = _ENGLISH_PROMPT_RE.match(prompt)
        sentence_en = prompt_match.group(1).strip() if prompt_match else prompt
        hint = production_hint_from_english(sentence_en) or sentence_en
        cloze_sentence = CLOZE_BLANK_DISPLAY
        if answer.endswith("。"):
            cloze_sentence += "。"
        items.append(
            ParsedExerciseItem(
                exercise_id=f"{page_stem}-{block_id}-{index}",
                section_title=section_title,
                formation=formation,
                cloze_sentence=cloze_sentence,
                full_sentence=answer if answer.endswith("。") else f"{answer}。",
                sentence_en=sentence_en,
                type_expression=answer,
                hint=hint,
                title=f"{section_title} · {index}",
            )
        )
        index += 1
    return items, index


def _parse_conjugation_blocks(
    block_html: str,
    *,
    page_stem: str,
    section_title: str,
    formation: str,
    block_id: str,
    start_index: int,
) -> Tuple[List[ParsedExerciseItem], int]:
    items: List[ParsedExerciseItem] = []
    index = start_index
    for block in _CONJUGATION_BLOCK_RE.finditer(block_html):
        noun = _plain_text(block.group("noun"))
        for row in _CONJUGATION_FORM_ROW_RE.finditer(block.group("rows")):
            label = _plain_text(row.group("label")).lower()
            answer = _normalize_answer(row.group("answer"))
            if not noun or not answer or _is_skipped_answer(answer):
                continue
            if label not in _CONJUGATION_LABELS:
                continue
            full_sentence = answer if answer.endswith("。") else answer
            cloze_sentence = CLOZE_BLANK_DISPLAY
            if full_sentence.endswith("。"):
                cloze_sentence += "。"
            items.append(
                ParsedExerciseItem(
                    exercise_id=f"{page_stem}-{block_id}-{index}",
                    section_title=section_title,
                    formation=formation,
                    cloze_sentence=cloze_sentence,
                    full_sentence=full_sentence,
                    sentence_en=f"{noun} ({label})",
                    type_expression=full_sentence,
                    hint=f"{noun} · {label}",
                    title=f"{section_title} · {noun} · {label}",
                )
            )
            index += 1
    return items, index


def _parse_conjugation_grid(
    block_html: str,
    *,
    page_stem: str,
    section_title: str,
    formation: str,
    block_id: str,
    start_index: int,
) -> Tuple[List[ParsedExerciseItem], int]:
    items: List[ParsedExerciseItem] = []
    index = start_index
    header_match = _GRID_HEADER_RE.search(block_html)
    if not header_match:
        return items, index
    headers = [
        _plain_text(cell)
        for cell in re.findall(r"<td[^>]*>([^<]+)</td>", header_match.group("headers"), re.I)
    ]
    if not headers or headers[0].lower() in {"verb", "plain"}:
        labels = headers[1:] if headers and headers[0].lower() == "plain" else headers
        for row in _GRID_ROW_RE.finditer(block_html):
            stem = _plain_text(row.group("stem"))
            if not stem or stem.lower() in _CONJUGATION_LABELS:
                continue
            answers = _GRID_CELL_RE.findall(row.group("cells"))
            for label, answer_raw in zip(labels, answers):
                answer = _normalize_answer(answer_raw)
                if _is_skipped_answer(answer):
                    continue
                label_key = label.lower()
                if label_key not in _CONJUGATION_LABELS and label_key != "declarative":
                    continue
                if label_key == "declarative" and answer == "n/a":
                    continue
                full_sentence = answer
                cloze_sentence = CLOZE_BLANK_DISPLAY
                if full_sentence.endswith("。"):
                    cloze_sentence += "。"
                items.append(
                    ParsedExerciseItem(
                        exercise_id=f"{page_stem}-{block_id}-{index}",
                        section_title=section_title,
                        formation=formation,
                        cloze_sentence=cloze_sentence,
                        full_sentence=full_sentence,
                        sentence_en=f"{stem} ({label_key})",
                        type_expression=full_sentence,
                        hint=f"{stem} · {label_key}",
                        title=f"{section_title} · {stem} · {label_key}",
                    )
                )
                index += 1
    return items, index


_GRID_CELL_RE = re.compile(
    r'<td class="answerline"><span class="hide">([^<]*)</span></td>',
    re.IGNORECASE,
)


def _parse_qa_pairs(
    block_html: str,
    *,
    page_stem: str,
    section_title: str,
    formation: str,
    block_id: str,
    start_index: int,
) -> Tuple[List[ParsedExerciseItem], int]:
    items: List[ParsedExerciseItem] = []
    index = start_index
    for match in _QA_PAIR_RE.finditer(block_html):
        question = _plain_text(match.group("question"))
        answer = _normalize_answer(match.group("answer"))
        suffix = _plain_text(match.group("suffix"))
        if not question or not answer:
            continue
        row_html = match.group(0)
        if "ううん、" in row_html:
            yes_no = "ううん"
        elif "うん、" in row_html:
            yes_no = "うん"
        else:
            yes_no = ""
        prefix = f"{yes_no}、" if yes_no else ""
        full_sentence = _strip_parenthetical_notes(f"{prefix}{answer}{suffix}")
        cloze_sentence = _strip_parenthetical_notes(f"{prefix}{CLOZE_BLANK_DISPLAY}{suffix}")
        hint = _qa_hint_from_question(match.group("question"))
        sentence_en = (
            f"{hint} — Yes"
            if yes_no == "うん"
            else f"{hint} — No"
            if yes_no == "ううん"
            else hint
        )
        items.append(
            ParsedExerciseItem(
                exercise_id=f"{page_stem}-{block_id}-{index}",
                section_title=section_title,
                formation=formation,
                cloze_sentence=cloze_sentence,
                full_sentence=full_sentence,
                sentence_en=sentence_en,
                type_expression=answer,
                hint=hint,
                title=f"{section_title} · {hint}",
            )
        )
        index += 1
    return items, index


def _parse_exercise_block(
    block_html: str,
    *,
    page_stem: str,
    section_title: str,
    formation: str,
    block_id: str,
) -> List[ParsedExerciseItem]:
    items: List[ParsedExerciseItem] = []
    index = 0

    en_items, index = _parse_en_to_jp_rows(
        block_html,
        page_stem=page_stem,
        section_title=section_title,
        formation=formation,
        block_id=block_id,
        start_index=index,
    )
    items.extend(en_items)

    conj_items, index = _parse_conjugation_blocks(
        block_html,
        page_stem=page_stem,
        section_title=section_title,
        formation=formation,
        block_id=block_id,
        start_index=index,
    )
    items.extend(conj_items)

    grid_items, index = _parse_conjugation_grid(
        block_html,
        page_stem=page_stem,
        section_title=section_title,
        formation=formation,
        block_id=block_id,
        start_index=index,
    )
    items.extend(grid_items)

    qa_items, index = _parse_qa_pairs(
        block_html,
        page_stem=page_stem,
        section_title=section_title,
        formation=formation,
        block_id=block_id,
        start_index=index,
    )
    items.extend(qa_items)

    for row_match in re.finditer(r"<tr>\s*<td>(.*?)</td>\s*</tr>", block_html, re.I | re.S):
        td_html = row_match.group(1)
        if "answerline" not in td_html:
            continue
        if _EN_TO_JP_ROW_RE.search(row_match.group(0)):
            continue
        plain_row = _plain_text(td_html)
        if plain_row.startswith(("Ｑ", "Ａ", "Q", "A")):
            continue
        inline_items, index = _inline_cloze_items(
            td_html,
            page_stem=page_stem,
            section_title=section_title,
            formation=formation,
            block_id=block_id,
            start_index=index,
        )
        items.extend(inline_items)

    return items


def _section_title_for_exercise_block(html_text: str, block_start: int) -> str:
    """Return the nearest preceding h2 section title (skip vocabulary-only part1)."""
    best = ""
    for match in _H2_SECTION_RE.finditer(html_text):
        if match.start() >= block_start:
            break
        part_id = match.group(1)
        if part_id == "part1":
            continue
        best = _plain_text(match.group(2))
    return best or "Exercise"


def parse_tae_kim_exercise_page(
    html_text: str,
    *,
    page: str,
    formation: str,
) -> List[ParsedExerciseItem]:
    page_stem = Path(page).stem
    items: List[ParsedExerciseItem] = []
    for match in _EXERCISE_DIV_RE.finditer(html_text):
        block_id = match.group(1)
        block_html = match.group(2)
        section_title = _section_title_for_exercise_block(html_text, match.start())
        parsed = _parse_exercise_block(
            block_html,
            page_stem=page_stem,
            section_title=section_title,
            formation=formation,
            block_id=block_id,
        )
        items.extend(parsed)
    return items


def exercise_point_id(page: str, exercise_id: str) -> str:
    stem = Path(page).stem
    return f"{TAE_KIM_EXERCISE_POINT_PREFIX}-{stem}-{exercise_id}"


def exercise_audio_basename(point_id: str) -> str:
    safe = hashlib.sha1(point_id.encode("utf-8")).hexdigest()[:16]
    return f"wk_tk_ex_{safe}.mp3"


def exercise_page_within_cap(
    spec: ExercisePageSpec,
    *,
    max_tae_kim_section: int,
    lesson_cap: Optional[Tuple[str, int]],
) -> bool:
    parent = tae_kim_lesson_by_slug(spec.chapter, spec.parent_lesson)
    if parent is None:
        return False
    section = tae_kim_section_by_num(parent.section_num)
    if section is None or not tae_kim_section_within_cap(section.num, max_tae_kim_section):
        return False
    if lesson_cap is None:
        return True
    max_chapter, max_lesson_num = lesson_cap
    if max_chapter != "basic":
        return True
    return parent.num <= max_lesson_num


def collect_tae_kim_section_vocabulary_entries(
    *,
    max_tae_kim_section: int = 6,
    max_tae_kim_lesson: Optional[str] = None,
    refresh: bool = False,
) -> List[Tuple[int, str]]:
    """Map Tae Kim practice-page vocabulary lists to (lesson_order, term) pairs for core priority."""
    from wk_study_priority import lesson_sort_key

    lesson_cap: Optional[Tuple[str, int]] = None
    if max_tae_kim_lesson:
        lesson_cap = parse_tae_kim_lesson_cap(max_tae_kim_lesson)

    entries: List[Tuple[int, str]] = []
    for spec in load_tae_kim_exercise_page_specs():
        if spec.skip:
            continue
        if not exercise_page_within_cap(
            spec,
            max_tae_kim_section=max_tae_kim_section,
            lesson_cap=lesson_cap,
        ):
            continue
        parent = tae_kim_lesson_by_slug(spec.chapter, spec.parent_lesson)
        practice = tae_kim_lesson_by_slug(spec.chapter, spec.practice_lesson)
        if parent is None:
            continue
        section = tae_kim_section_by_num(parent.section_num)
        if section is None:
            continue
        lesson = practice or parent
        order = lesson_sort_key(section.num, lesson.num)
        html_text = fetch_tae_kim_exercise_html(spec.page, refresh=refresh)
        for term in parse_tae_kim_vocabulary_section(html_text):
            entries.append((order, term))
    return entries


def collect_tae_kim_exercise_cards(
    *,
    max_tae_kim_section: int = 6,
    max_tae_kim_lesson: Optional[str] = None,
    refresh: bool = False,
) -> List[GrammarCardItem]:
    lesson_cap: Optional[Tuple[str, int]] = None
    if max_tae_kim_lesson:
        lesson_cap = parse_tae_kim_lesson_cap(max_tae_kim_lesson)

    cards: List[GrammarCardItem] = []
    for spec in load_tae_kim_exercise_page_specs():
        if spec.skip:
            continue
        if not exercise_page_within_cap(
            spec,
            max_tae_kim_section=max_tae_kim_section,
            lesson_cap=lesson_cap,
        ):
            continue
        parent = tae_kim_lesson_by_slug(spec.chapter, spec.parent_lesson)
        practice = tae_kim_lesson_by_slug(spec.chapter, spec.practice_lesson)
        if parent is None:
            continue
        section = tae_kim_section_by_num(parent.section_num)
        if section is None:
            continue

        html_text = fetch_tae_kim_exercise_html(spec.page, refresh=refresh)
        parsed_items = parse_tae_kim_exercise_page(
            html_text,
            page=spec.page,
            formation=spec.formation,
        )
        for item in parsed_items:
            point_id = exercise_point_id(spec.page, item.exercise_id)
            cards.append(
                GrammarCardItem(
                    point_id=point_id,
                    jlpt="N5",
                    order=parent.num,
                    title=item.title,
                    short_explanation=item.section_title,
                    formation=item.formation or spec.formation,
                    cloze_sentence=item.cloze_sentence,
                    full_sentence=item.full_sentence,
                    sentence_en=item.sentence_en,
                    type_expression=item.type_expression,
                    hint=item.hint,
                    tae_kim_section=section,
                    tae_kim_lesson=practice or parent,
                )
            )

    cards.sort(
        key=lambda card: (
            card.tae_kim_section.num,
            card.tae_kim_lesson.num if card.tae_kim_lesson else 999,
            card.order,
            card.title,
            card.point_id,
        )
    )
    return cards


def build_tae_kim_exercise_deck(
    cards: Sequence[GrammarCardItem],
    output_dir: Path,
    *,
    sentence_audio: bool = True,
    sentence_audio_voice: str = DEFAULT_SENTENCE_AUDIO_VOICE,
    refresh_sentence_audio: bool = False,
) -> Tuple[Path, genanki.Deck, List[str]]:
    deck = genanki.Deck(EXERCISE_DECK_ID, EXERCISE_DECK_NAME)
    model = make_grammar_model()
    template_label = EXERCISE_TEMPLATE_VERSION
    media_dir = output_dir / WK_SHARED_MEDIA_SUBDIR
    media_files: List[str] = []
    audio_ok = 0
    audio_cached = 0
    audio_new = 0
    if sentence_audio:
        require_edge_tts()
        print(f"Tae Kim exercise sentence audio (voice={sentence_audio_voice})...")
    for item in cards:
        guid = stable_guid("tk-exercise", item.point_id)
        lesson = item.tae_kim_lesson
        tk = item.tae_kim_section
        if lesson is not None:
            meta = (
                f"Tae Kim {lesson.chapter_name} · {lesson.num:02d} {lesson.name} · "
                f"exercise · template {template_label}"
            )
        else:
            meta = (
                f"Tae Kim §{tk.num} {tk.name} · exercise · template {template_label}"
            )
        sentence_audio_field = ""
        if sentence_audio:
            tts_text = prepare_grammar_sentence_for_tts(item.full_sentence)
            basename = tts_audio_basename(tts_text, sentence_audio_voice)
            if basename:
                dest = media_dir / basename
                ok, was_cached = ensure_sentence_audio_file(
                    tts_text,
                    sentence_audio_voice,
                    dest,
                    refresh=refresh_sentence_audio,
                )
                if ok:
                    sentence_audio_field = f"[sound:{basename}]"
                    media_files.append(str(dest.resolve()))
                    audio_ok += 1
                    if was_cached:
                        audio_cached += 1
                    else:
                        audio_new += 1
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                html_module.escape(item.cloze_sentence),
                html_module.escape(item.hint),
                html_module.escape(grammar_form_hint(item.title)),
                html_module.escape(item.formation),
                html_module.escape(item.title),
                html_module.escape(item.type_expression),
                html_module.escape(item.full_sentence),
                html_module.escape(item.sentence_en),
                sentence_audio_field,
                html_module.escape(meta),
            ],
            tags=[
                "grammar",
                "tae-kim-exercise",
                "tae-kim",
                "priority-medium",
                *tae_kim_card_tags(tk, lesson),
            ],
            guid=guid,
        )
        deck.add_note(note)
    if sentence_audio:
        print(
            f"Tae Kim exercise sentence audio: {audio_ok}/{len(cards)} cards "
            f"({audio_new} new, {audio_cached} cached)"
        )
        if cards and audio_ok == 0:
            print(
                "  Warning: no exercise sentence audio was generated. "
                "Install edge-tts, check network, or pass --no-grammar-sentence-audio to skip.",
                file=sys.stderr,
            )
    deck.wk_media_files = media_files
    out = output_dir / "wk_tae_kim_exercises.apkg"
    write_apkg(deck, out, media_files=media_files or None)
    return out, deck, media_files
