"""
Pure deck stats logic for wk_deck_stats (testable without Anki runtime).

WK core decks use note-level immersion-first buckets: Locked / New / Reviewed.
All other decks use card-level Anki queue counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

ANKI_CARD_TYPE_NEW = 0
ANKI_CARD_TYPE_LEARN = 1
ANKI_CARD_TYPE_REVIEW = 2
ANKI_CARD_TYPE_RELEARN = 3
ANKI_QUEUE_SUSPENDED = -1

CORE_RADICALS_DECK = "WaniKani Core · Radicals"
CORE_KANJI_DECK = "WaniKani Core · Kanji"
CORE_VOCABULARY_DECK = "WaniKani Core · Vocabulary"
CORE_DECK_NAMES = (CORE_RADICALS_DECK, CORE_KANJI_DECK, CORE_VOCABULARY_DECK)

WK_LOCKED_TAG = "wk-locked"
WK_CORE_TAG = "wk-core"
WK_LEVEL_TAG_PREFIX = "wk-level-"

SUBJECT_TAG_KANJI = "kanji"
SUBJECT_TAG_VOCABULARY = "vocabulary"
SUBJECT_TAG_RADICAL = "radical"

# Immersion decks that seed core subject progress tables.
IMMERSION_TAGS: Tuple[str, ...] = ("satori-mining", "shadowing-mining")

# Display order for non-core generated decks (matches wk_decks.py DECK_NAMES).
SUPPLEMENTARY_DECK_ORDER: Tuple[str, ...] = (
    "WaniKani Current and Next Radicals",
    "WaniKani Phonetic Families",
    "WaniKani Reading Keywords",
    "WaniKani Kanji Radical Breakdown",
    "WaniKani Verb Conjugation Practice",
    "WaniKani Adjective Conjugation Practice",
    "WaniKani Verb Conjugation Reverse",
    "WaniKani Verb Type Practice",
    "WaniKani Adjective Type Practice",
    "WaniKani Vocabulary Context",
    "Japanese Grammar Context",
    "WaniKani Dictation",
    "WaniKani Rendaku",
    "Immersion · Yomitan Mining",
    "Immersion · Migaku Mining",
    "Immersion · Satori",
    "Immersion · Shadowing",
    "Immersion · Shadowing Candidates",
    "WaniKani Leech Fixes",
    "WaniKani Pitch Leeches",
    "WaniKani Verb Pair Contrasts",
    "WaniKani Confusable Vocabulary",
)


@dataclass(frozen=True)
class CardRow:
    card_id: int
    note_id: int
    deck_name: str
    card_type: int
    queue: int
    ivl: int
    reps: int


@dataclass(frozen=True)
class NoteRow:
    note_id: int
    deck_name: str
    tags: Tuple[str, ...]
    cards: Tuple[CardRow, ...]
    wk_subject_id: Optional[int] = None
    prerequisite_ids: Tuple[int, ...] = ()
    wk_level: Optional[int] = None
    is_kanji: bool = False
    is_vocabulary: bool = False
    is_radical: bool = False


@dataclass(frozen=True)
class WkDeckRow:
    deck_name: str
    locked_count: int
    new_count: int
    reviewed_count: int
    total_notes: int


@dataclass(frozen=True)
class StandardDeckRow:
    deck_name: str
    new_count: int
    learning_count: int
    review_count: int
    suspended_count: int
    total_cards: int


@dataclass(frozen=True)
class ImmersionCoreProgressRow:
    """Core kanji/vocab linked from Satori/Shadowing immersion notes."""

    subject_kind: str
    locked_count: int
    new_count: int
    reviewed_count: int
    total_notes: int


@dataclass(frozen=True)
class DeckStatsReport:
    generated_at: str
    wk_rows: Tuple[WkDeckRow, ...]
    standard_rows: Tuple[StandardDeckRow, ...]
    immersion_kanji: Optional[ImmersionCoreProgressRow] = None
    immersion_vocab: Optional[ImmersionCoreProgressRow] = None


def is_active_card(card: CardRow) -> bool:
    return card.queue != ANKI_QUEUE_SUSPENDED


def is_core_deck(deck_name: str) -> bool:
    return deck_name in CORE_DECK_NAMES


def note_has_tag(note: NoteRow, tag: str) -> bool:
    return tag in note.tags or any(item.startswith(f"{tag}::") for item in note.tags)


def note_is_new(note: NoteRow) -> bool:
    """True when every active card is still in the Anki new queue (is:new)."""
    active = [card for card in note.cards if is_active_card(card)]
    if not active:
        return False
    return all(card.card_type == ANKI_CARD_TYPE_NEW for card in active)


def classify_wk_note(note: NoteRow) -> str:
    """Return one of: locked, new, reviewed (immersion-first core buckets)."""
    if note_has_tag(note, WK_LOCKED_TAG):
        return "locked"
    active = [card for card in note.cards if is_active_card(card)]
    if not active:
        return "locked"
    if note_is_new(note):
        return "new"
    return "reviewed"


def classify_immersion_core_note(note: NoteRow) -> str:
    """Return one of: locked, new, reviewed."""
    return classify_wk_note(note)


def parse_prerequisite_ids(value: Optional[str]) -> Tuple[int, ...]:
    """Mirror of wk_unlock.logic.parse_prerequisite_ids."""
    if not value:
        return ()
    ids: List[int] = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return tuple(ids)


def parse_wk_level_from_tags(tags: Sequence[str]) -> Optional[int]:
    for tag in tags:
        if tag.startswith(WK_LEVEL_TAG_PREFIX):
            try:
                return int(tag[len(WK_LEVEL_TAG_PREFIX) :])
            except ValueError:
                continue
    return None


def parse_wk_subject_id(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def field_flag_is_true(value: Optional[str]) -> bool:
    return str(value or "").strip() == "1"


def note_subject_kind(note: NoteRow) -> Optional[str]:
    if note.is_vocabulary or note.deck_name == CORE_VOCABULARY_DECK:
        return SUBJECT_TAG_VOCABULARY
    if note.is_kanji or note.deck_name == CORE_KANJI_DECK:
        return SUBJECT_TAG_KANJI
    if note.is_radical or note.deck_name == CORE_RADICALS_DECK:
        return SUBJECT_TAG_RADICAL
    if SUBJECT_TAG_VOCABULARY in note.tags:
        return SUBJECT_TAG_VOCABULARY
    if SUBJECT_TAG_KANJI in note.tags:
        return SUBJECT_TAG_KANJI
    if SUBJECT_TAG_RADICAL in note.tags:
        return SUBJECT_TAG_RADICAL
    return None


def collect_immersion_subject_ids(immersion_notes: Sequence[NoteRow]) -> Set[int]:
    """WkSubjectId + PrerequisiteIds from Satori/Shadowing immersion notes."""
    subject_ids: Set[int] = set()
    for note in immersion_notes:
        if note.wk_subject_id is not None:
            subject_ids.add(note.wk_subject_id)
        subject_ids.update(note.prerequisite_ids)
    return subject_ids


def build_immersion_core_progress(
    notes: Sequence[NoteRow],
    *,
    immersion_subject_ids: Set[int],
    subject_kind: str,
) -> Optional[ImmersionCoreProgressRow]:
    if not immersion_subject_ids:
        return None
    locked_count = 0
    new_count = 0
    reviewed_count = 0
    for note in notes:
        if note_subject_kind(note) != subject_kind:
            continue
        if note.wk_subject_id is None or note.wk_subject_id not in immersion_subject_ids:
            continue
        bucket = classify_immersion_core_note(note)
        if bucket == "locked":
            locked_count += 1
        elif bucket == "new":
            new_count += 1
        else:
            reviewed_count += 1
    total = locked_count + new_count + reviewed_count
    if total == 0:
        return None
    return ImmersionCoreProgressRow(
        subject_kind=subject_kind,
        locked_count=locked_count,
        new_count=new_count,
        reviewed_count=reviewed_count,
        total_notes=total,
    )


def build_notes_by_deck(notes: Sequence[NoteRow]) -> Dict[str, List[NoteRow]]:
    grouped: Dict[str, List[NoteRow]] = {}
    for note in notes:
        grouped.setdefault(note.deck_name, []).append(note)
    return grouped


def build_cards_by_deck(cards: Sequence[CardRow]) -> Dict[str, List[CardRow]]:
    grouped: Dict[str, List[CardRow]] = {}
    for card in cards:
        grouped.setdefault(card.deck_name, []).append(card)
    return grouped


def build_wk_deck_row(deck_name: str, notes: Sequence[NoteRow]) -> WkDeckRow:
    counts = {"locked": 0, "new": 0, "reviewed": 0}
    for note in notes:
        counts[classify_wk_note(note)] += 1
    return WkDeckRow(
        deck_name=deck_name,
        locked_count=counts["locked"],
        new_count=counts["new"],
        reviewed_count=counts["reviewed"],
        total_notes=len(notes),
    )


def build_standard_deck_row(deck_name: str, cards: Sequence[CardRow]) -> StandardDeckRow:
    new_count = 0
    learning_count = 0
    review_count = 0
    suspended_count = 0
    for card in cards:
        if not is_active_card(card):
            suspended_count += 1
            continue
        if card.card_type == ANKI_CARD_TYPE_NEW:
            new_count += 1
        elif card.card_type in (ANKI_CARD_TYPE_LEARN, ANKI_CARD_TYPE_RELEARN):
            learning_count += 1
        elif card.card_type == ANKI_CARD_TYPE_REVIEW:
            review_count += 1
    return StandardDeckRow(
        deck_name=deck_name,
        new_count=new_count,
        learning_count=learning_count,
        review_count=review_count,
        suspended_count=suspended_count,
        total_cards=len(cards),
    )


def sort_deck_names(deck_names: Iterable[str]) -> List[str]:
    names = set(deck_names)
    ordered: List[str] = []
    for name in CORE_DECK_NAMES:
        if name in names:
            ordered.append(name)
            names.discard(name)
    for name in SUPPLEMENTARY_DECK_ORDER:
        if name in names:
            ordered.append(name)
            names.discard(name)
    ordered.extend(sorted(names))
    return ordered


def build_deck_stats_report(
    *,
    cards: Sequence[CardRow],
    notes: Sequence[NoteRow],
    immersion_subject_ids: Optional[Set[int]] = None,
    generated_at: Optional[str] = None,
) -> DeckStatsReport:
    cards_by_deck = build_cards_by_deck(cards)
    notes_by_deck = build_notes_by_deck(notes)
    all_decks = sort_deck_names(set(cards_by_deck) | set(notes_by_deck))

    wk_rows: List[WkDeckRow] = []
    standard_rows: List[StandardDeckRow] = []

    for deck_name in all_decks:
        deck_cards = cards_by_deck.get(deck_name, [])
        deck_notes = notes_by_deck.get(deck_name, [])
        if is_core_deck(deck_name):
            if deck_notes:
                wk_rows.append(build_wk_deck_row(deck_name, deck_notes))
            continue
        if deck_cards:
            standard_rows.append(build_standard_deck_row(deck_name, deck_cards))

    timestamp = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    linked_ids = immersion_subject_ids or set()
    return DeckStatsReport(
        generated_at=timestamp,
        wk_rows=tuple(wk_rows),
        standard_rows=tuple(standard_rows),
        immersion_kanji=build_immersion_core_progress(
            notes,
            immersion_subject_ids=linked_ids,
            subject_kind=SUBJECT_TAG_KANJI,
        ),
        immersion_vocab=build_immersion_core_progress(
            notes,
            immersion_subject_ids=linked_ids,
            subject_kind=SUBJECT_TAG_VOCABULARY,
        ),
    )


def _pad(value: int, width: int) -> str:
    return str(value).rjust(width)


def _format_immersion_progress(title: str, row: ImmersionCoreProgressRow) -> List[str]:
    lines = [
        title,
        "=" * 48,
        f"{'Locked':>8} {'New':>8} {'Reviewed':>10} {'Total':>8}",
        "-" * 48,
        (
            f"{_pad(row.locked_count, 8)} "
            f"{_pad(row.new_count, 8)} "
            f"{_pad(row.reviewed_count, 10)} "
            f"{_pad(row.total_notes, 8)}"
        ),
        "",
    ]
    return lines


def format_deck_stats_report(report: DeckStatsReport) -> str:
    lines = [f"WK Deck Stats — {report.generated_at}", ""]

    if report.wk_rows:
        lines.append(
            "WaniKani core (notes — Locked / New is:new / Reviewed introduced)"
        )
        lines.append("=" * 72)
        header = (
            f"{'Deck':<30} {'Locked':>7} {'New':>6} {'Reviewed':>9} {'Total':>6}"
        )
        lines.append(header)
        lines.append("-" * 72)
        totals = {"locked": 0, "new": 0, "reviewed": 0, "total": 0}
        for row in report.wk_rows:
            lines.append(
                f"{row.deck_name:<30} "
                f"{_pad(row.locked_count, 7)} "
                f"{_pad(row.new_count, 6)} "
                f"{_pad(row.reviewed_count, 9)} "
                f"{_pad(row.total_notes, 6)}"
            )
            totals["locked"] += row.locked_count
            totals["new"] += row.new_count
            totals["reviewed"] += row.reviewed_count
            totals["total"] += row.total_notes
        lines.append("-" * 72)
        lines.append(
            f"{'Core total':<30} "
            f"{_pad(totals['locked'], 7)} "
            f"{_pad(totals['new'], 6)} "
            f"{_pad(totals['reviewed'], 9)} "
            f"{_pad(totals['total'], 6)}"
        )
        lines.append("")

    if report.immersion_kanji or report.immersion_vocab:
        lines.append(
            "Immersion-linked core (Satori/Shadowing WkSubjectId + PrerequisiteIds — "
            "Locked / New / Reviewed)"
        )
        lines.append("")
        if report.immersion_kanji:
            lines.extend(
                _format_immersion_progress(
                    "WK Core Kanji (in Satori or Shadowing)",
                    report.immersion_kanji,
                )
            )
        if report.immersion_vocab:
            lines.extend(
                _format_immersion_progress(
                    "WK Core Vocabulary (in Satori or Shadowing)",
                    report.immersion_vocab,
                )
            )

    if report.standard_rows:
        lines.append("Other decks (cards — Anki new / learning / review)")
        lines.append("=" * 72)
        header = (
            f"{'Deck':<34} {'New':>5} {'Learn':>6} {'Review':>7} "
            f"{'Susp':>6} {'Total':>6}"
        )
        lines.append(header)
        lines.append("-" * 72)
        for row in report.standard_rows:
            lines.append(
                f"{row.deck_name:<34} "
                f"{_pad(row.new_count, 5)} "
                f"{_pad(row.learning_count, 6)} "
                f"{_pad(row.review_count, 7)} "
                f"{_pad(row.suspended_count, 6)} "
                f"{_pad(row.total_cards, 6)}"
            )
        lines.append("")

    if not report.wk_rows and not report.standard_rows:
        lines.append("No cards found in the collection.")

    lines.append(
        "Core buckets: Locked = wk-locked/suspended; New = is:new; "
        "Reviewed = learning or review (including WK-seeded schedules). "
        "Cards in filtered queues count toward the home deck."
    )
    return "\n".join(lines)
