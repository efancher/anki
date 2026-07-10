"""
mining_logic.py — pure helpers for Yomitan mining cloze cards (add-on + tests).

Lives under wk_immersion for Anki sync; tests import from anki_addon/wk_immersion/.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

CLOZE_BLANK_DISPLAY = "＿＿＿"
GLOSSARY_SNIPPET_MAX_LEN = 80

_RUBY_WITH_RT = re.compile(r"<ruby>(.*?)<rt>(.*?)</rt></ruby>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_SCRIPT_RE = re.compile(
    r"<(style|script)\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_CSS_LIKE_RE = re.compile(r"[{}]|\.yomitan|data-|[a-z-]+\s*\{", re.IGNORECASE)
_DICT_NAME_PARENS_RE = re.compile(r"\([^)]*(?:例解|辞典|国語)[^)]*\)")
_SENSE_CIRCLED_RE = re.compile(r"(?:❶|❷|❸|❹|①|②|③|④)")
_SENSE_NUMBERED_RE = re.compile(r"(?:１|２|３|４|[0-9]+)\s*")


def strip_html(value: str) -> str:
    return _TAG_RE.sub("", value or "").strip()


def blank_targets_for_expression(expression: str, reading: str) -> List[str]:
    targets: List[str] = []
    expr = (expression or "").strip()
    read = (reading or "").strip()
    if expr:
        targets.append(expr)
        if expr.endswith("する") and len(expr) > 2:
            targets.append(expr[:-2])
    if read:
        targets.append(read)
    return sorted({target for target in targets if target}, key=len, reverse=True)


def build_cloze_sentence(sentence: str, targets: Sequence[str]) -> Tuple[str, str]:
    """Return (cloze_html, plain_sentence). Falls back to full sentence if no match."""
    plain = strip_html(sentence)
    if not plain:
        return "", ""
    for target in targets:
        idx = plain.find(target)
        if idx >= 0:
            before = html.escape(plain[:idx])
            after = html.escape(plain[idx + len(target):])
            blank = f'<span class="cloze-blank">{CLOZE_BLANK_DISPLAY}</span>'
            cloze_html = f"{before}{blank}{after}"
            return cloze_html, plain
    return html.escape(plain), plain


def ruby_html_to_kana_plain(value: str) -> str:
    if not (value or "").strip():
        return ""
    text = value
    while True:
        updated = _RUBY_WITH_RT.sub(
            lambda match: (match.group(2) or match.group(1)).strip(),
            text,
        )
        if updated == text:
            break
        text = updated
    return strip_html(text).strip()


def build_sentence_kana(sentence_furigana: str, sentence: str, reading: str) -> str:
    kana = ruby_html_to_kana_plain(sentence_furigana)
    if kana:
        return kana
    plain = strip_html(sentence)
    if plain and reading and reading in plain:
        return plain
    return ""


def _strip_yomitan_glossary_html(glossary: str) -> str:
    text = _STYLE_SCRIPT_RE.sub("", glossary or "")
    return strip_html(text)


def _extract_glossary_sense(plain: str) -> str:
    text = plain.replace("\n", " ").strip()
    text = re.sub(r"^\s*意味\s*", "", text)
    text = _DICT_NAME_PARENS_RE.sub("", text)

    circled = _SENSE_CIRCLED_RE.search(text)
    if circled:
        text = text[circled.end():]
    else:
        numbered = _SENSE_NUMBERED_RE.search(text)
        if numbered:
            text = text[numbered.end():]
        text = re.sub(r"【[^】]+】", "", text)
        text = re.sub(r"(?:名|動|形|副|接|連|感|代|助|補|句)\s*", " ", text)
        text = re.sub(r"[ァ-ヴー]+", " ", text)
        text = re.sub(r"^[^\u3040-\u9fff\u3400-\u4dbf]+", "", text)

    stop = re.search(r"(?:❷|❸|❹|例[ 　]|類[ 　]|対[ 　])", text)
    if stop and stop.start() > 0:
        text = text[: stop.start()]

    text = re.sub(r"\s+", " ", text).strip(" ・.。")
    return text


def _japanese_gloss_chunks(plain: str) -> List[str]:
    return re.findall(
        r"[\u3040-\u9fff\u3400-\u4dbf\u3000-\u303f]+(?:[。、]?[\u3040-\u9fff\u3400-\u4dbf\u3000-\u303f]*)*",
        plain,
    )


def glossary_snippet(glossary: str, *, max_len: int = GLOSSARY_SNIPPET_MAX_LEN) -> str:
    plain = _extract_glossary_sense(_strip_yomitan_glossary_html(glossary))
    if not plain or _CSS_LIKE_RE.search(plain):
        chunks = _japanese_gloss_chunks(_strip_yomitan_glossary_html(glossary))
        plain = chunks[0] if chunks else ""
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return ""
    if len(plain) <= max_len:
        return plain
    return plain[: max_len - 1].rstrip() + "…"


def dictionary_links_html(expression: str, reading: str) -> Tuple[str, str]:
    expr = (expression or "").strip()
    read = (reading or "").strip()
    query = expr or read
    if not query:
        return "", ""
    encoded = urllib.parse.quote(query)
    read_encoded = urllib.parse.quote(read) if read else encoded
    links_en = (
        '<div class="dict-links dict-links-en">'
        f'<span class="dict-label">英</span> '
        f'<a href="https://jisho.org/search/{encoded}">Jisho</a>'
        "</div>"
    )
    links_ja = (
        '<div class="dict-links dict-links-ja">'
        f'<span class="dict-label">和</span> '
        f'<a href="https://www.weblio.jp/content/{encoded}">Weblio</a> · '
        f'<a href="https://thesaurus.weblio.jp/content/{encoded}">類語</a>'
        "</div>"
    )
    if read and read != expr:
        links_ja += (
            f' <span class="dict-reading"><a href="https://www.weblio.jp/content/{read_encoded}">'
            f"{html.escape(read)}</a></span>"
        )
    return links_ja, links_en


def mining_hint_display_flags(hint_stage: int) -> Tuple[str, str, str, str]:
    stage = max(0, min(2, int(hint_stage)))
    return (
        str(stage),
        "1" if stage == 0 else "",
        "1" if stage < 2 else "",
        "1" if stage >= 2 else "",
    )


def compute_mining_hint_stage(
    wk_subject_id: Optional[int],
    prerequisite_ids: Sequence[int],
    *,
    kanji_meaning_mature_subject_ids: set[int],
    core_mature_subject_ids: set[int],
) -> int:
    stage = 0
    if not prerequisite_ids or all(
        kanji_id in kanji_meaning_mature_subject_ids for kanji_id in prerequisite_ids
    ):
        stage = 1
    if wk_subject_id is not None and wk_subject_id in core_mature_subject_ids:
        stage = 2
    return stage


@dataclass(frozen=True)
class MiningEnrichment:
    cloze_sentence: str
    wk_subject_id: str
    prerequisite_ids: str
    wk_meaning: str
    hint_stage: str
    show_english: str
    show_kana: str
    show_jj_back: str
    sentence_kana: str
    dict_links_ja: str
    dict_links_en: str
    hint_glossary: str


def enrich_mining_note_fields(
    *,
    expression: str,
    reading: str,
    sentence: str,
    sentence_furigana: str,
    glossary: str,
    wk_entry: Optional[dict],
) -> MiningEnrichment:
    targets = blank_targets_for_expression(expression, reading)
    cloze_html, _plain = build_cloze_sentence(sentence, targets)
    wk_subject_id = str(wk_entry["id"]) if wk_entry else ""
    prerequisite_ids = str(wk_entry.get("prerequisite_ids") or "") if wk_entry else ""
    wk_meaning = str(wk_entry.get("meaning") or "") if wk_entry else ""
    hint_stage, show_english, show_kana, show_jj_back = mining_hint_display_flags(0)
    sentence_kana = build_sentence_kana(sentence_furigana, sentence, reading)
    hint_glossary = glossary_snippet(glossary) if not wk_meaning else ""
    dict_ja, dict_en = dictionary_links_html(expression, reading)
    if wk_meaning:
        dict_en = ""
    if not cloze_html and sentence:
        cloze_html = html.escape(strip_html(sentence))
    return MiningEnrichment(
        cloze_sentence=cloze_html,
        wk_subject_id=wk_subject_id,
        prerequisite_ids=prerequisite_ids,
        wk_meaning=wk_meaning,
        hint_stage=hint_stage,
        show_english=show_english,
        show_kana=show_kana,
        show_jj_back=show_jj_back,
        sentence_kana=sentence_kana,
        dict_links_ja=dict_ja,
        dict_links_en=dict_en,
        hint_glossary=hint_glossary,
    )
