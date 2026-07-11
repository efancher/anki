"""
Cure Dolly–style gloss worksheets for Satori immersion sentences.

Not an SRS card — a practice sheet: Japanese → chunk/role/literal blanks →
Satori English kept separate so you map Japanese order before fluent English.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence
from urllib.parse import quote

DEFAULT_NOTE_TYPE = "WK Satori Immersion"
DEFAULT_DECK = "Immersion · Satori"
ICHI_MOE_BASE = "https://ichi.moe/cl/qr/"
ROLE_HINT = "Aが / engine / を・に・で car / time / topic は / …"
LIT_HINT = "Japanese-order sticky English (not fluent EN)"
CHUNK_HINT = "space particles / て links / clause boundaries"


@dataclass(frozen=True)
class GlossSentence:
    """One sentence to practice mapping Japanese → English."""

    japanese: str
    english: str = ""
    expression: str = ""
    reading: str = ""
    note_id: Optional[int] = None
    source: str = ""


def strip_anki_html(value: str) -> str:
    """Turn Anki field HTML into plain text for worksheets."""
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?div[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def ichi_moe_url(japanese: str) -> str:
    return f"{ICHI_MOE_BASE}?q={quote(japanese, safe='')}&r=kana"


def format_worksheet(item: GlossSentence, *, index: Optional[int] = None) -> str:
    """Render one worksheet block with blank CHUNK / ROLE / LIT lines."""
    header_bits: List[str] = ["Satori gloss worksheet"]
    if index is not None:
        header_bits.append(f"#{index}")
    if item.note_id is not None:
        header_bits.append(f"note {item.note_id}")
    header = " · ".join(header_bits)

    target = ""
    if item.expression:
        target = item.expression
        if item.reading:
            target = f"{item.expression} ({item.reading})"
        target = f"Target word: {target}"

    source = f"Source: {item.source}" if item.source else ""
    english = item.english or "(no English on this note — fill after you check Satori)"
    lines = [
        "═" * 64,
        header,
    ]
    if target:
        lines.append(target)
    if source:
        lines.append(source)
    lines.extend(
        [
            "",
            f"JP:    {item.japanese}",
            "",
            f"# CHUNK — {CHUNK_HINT}",
            "CHUNK:",
            "",
            f"# ROLE — {ROLE_HINT}",
            "ROLE:",
            "",
            f"# LIT — {LIT_HINT}",
            "LIT:",
            "",
            f"EN:    {english}",
            "",
            f"ichi.moe: {ichi_moe_url(item.japanese)}",
            "═" * 64,
        ]
    )
    return "\n".join(lines)


def format_worksheets(items: Sequence[GlossSentence]) -> str:
    blocks = [
        format_worksheet(item, index=i if len(items) > 1 else None)
        for i, item in enumerate(items, start=1)
    ]
    return "\n\n".join(blocks)


def gloss_from_anki_fields(
    fields: dict,
    *,
    note_id: Optional[int] = None,
) -> Optional[GlossSentence]:
    """Build a worksheet item from AnkiConnect notesInfo field map."""

    def field(name: str) -> str:
        raw = fields.get(name)
        if isinstance(raw, dict):
            return strip_anki_html(str(raw.get("value", "")))
        return strip_anki_html(str(raw or ""))

    japanese = field("Sentence") or field("ClozeSentence")
    if not japanese:
        return None
    # Cloze markup like {{c1::暖かい}} → 暖かい for the JP line.
    japanese = re.sub(r"\{\{c\d+::([^}]+)\}\}", r"\1", japanese)
    return GlossSentence(
        japanese=japanese,
        english=field("Translation"),
        expression=field("Expression"),
        reading=field("Reading"),
        note_id=note_id,
        source=field("SourceTitle") or field("SourceUrl"),
    )


def gloss_items_from_notes(notes: Iterable[dict]) -> List[GlossSentence]:
    items: List[GlossSentence] = []
    for note in notes:
        note_id = note.get("noteId")
        fields = note.get("fields") or {}
        item = gloss_from_anki_fields(fields, note_id=int(note_id) if note_id is not None else None)
        if item is not None:
            items.append(item)
    return items
