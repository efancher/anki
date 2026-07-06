"""
Pure deck stats logic for wk_deck_stats (testable without Anki runtime).

WK core decks use note-level WaniKani-style buckets (interval thresholds).
All other decks use card-level Anki queue counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ANKI_CARD_TYPE_NEW = 0
ANKI_CARD_TYPE_LEARN = 1
ANKI_CARD_TYPE_REVIEW = 2
ANKI_CARD_TYPE_RELEARN = 3
ANKI_QUEUE_SUSPENDED = -1

GURU_MIN_INTERVAL_DAYS = 7  # WaniKani Guru I (srs_stage 5)
MASTER_MIN_INTERVAL_DAYS = 30  # WaniKani Master (srs_stage 7)

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

JLPT_LEVELS: Tuple[str, ...] = ("N5", "N4", "N3", "N2", "N1")
WK_LEVEL_JLPT_THRESHOLDS: Tuple[Tuple[int, str], ...] = (
    (10, "N5"),
    (20, "N4"),
    (35, "N3"),
    (45, "N2"),
    (60, "N1"),
)
BURNED_INTERVAL_DAYS = 365  # WaniKani burned — mirrors wk_unlock.logic

WK_BUCKET_NAMES: Tuple[str, ...] = ("unseen", "apprentice", "guru", "master", "locked")

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
    unseen_count: int
    apprentice_count: int
    guru_count: int
    master_count: int
    locked_count: int
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
class VocabLockedByLevelRow:
    wk_level: int
    locked_count: int


@dataclass(frozen=True)
class JlptBucketRow:
    jlpt: str
    subject_kind: str
    unseen_count: int
    apprentice_count: int
    guru_count: int
    master_count: int
    locked_count: int
    total_notes: int


@dataclass(frozen=True)
class DeckStatsReport:
    generated_at: str
    wk_rows: Tuple[WkDeckRow, ...]
    standard_rows: Tuple[StandardDeckRow, ...]
    vocab_locked_by_wk_level: Tuple[VocabLockedByLevelRow, ...] = ()
    jlpt_kanji_rows: Tuple[JlptBucketRow, ...] = ()
    jlpt_vocab_rows: Tuple[JlptBucketRow, ...] = ()


def is_active_card(card: CardRow) -> bool:
    return card.queue != ANKI_QUEUE_SUSPENDED


def is_core_deck(deck_name: str) -> bool:
    return deck_name in CORE_DECK_NAMES


def note_has_tag(note: NoteRow, tag: str) -> bool:
    return tag in note.tags or any(item.startswith(f"{tag}::") for item in note.tags)


def note_never_reviewed(note: NoteRow) -> bool:
    active = [card for card in note.cards if is_active_card(card)]
    if not active:
        return False
    return all(card.reps <= 0 for card in active)


def classify_wk_note(note: NoteRow) -> str:
    """Return one of: locked, unseen, apprentice, guru, master."""
    if note_has_tag(note, WK_LOCKED_TAG):
        return "locked"
    active = [card for card in note.cards if is_active_card(card)]
    if not active:
        return "locked"
    if note_never_reviewed(note):
        return "unseen"
    max_ivl = max(card.ivl for card in active)
    if max_ivl >= MASTER_MIN_INTERVAL_DAYS:
        return "master"
    if max_ivl >= GURU_MIN_INTERVAL_DAYS:
        return "guru"
    return "apprentice"


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


def wk_level_to_jlpt(level: int) -> str:
    """Mirror of wk_study_priority.wk_level_to_jlpt."""
    for threshold, jlpt in WK_LEVEL_JLPT_THRESHOLDS:
        if level <= threshold:
            return jlpt
    return JLPT_LEVELS[-1]


def note_wk_level(note: NoteRow) -> int:
    if note.wk_level is not None:
        return note.wk_level
    from_tags = parse_wk_level_from_tags(note.tags)
    if from_tags is not None:
        return from_tags
    return WK_LEVEL_JLPT_THRESHOLDS[-1][0]


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


def card_meets_maturity(card: CardRow) -> bool:
    if not is_active_card(card):
        return False
    if card.ivl >= BURNED_INTERVAL_DAYS:
        return True
    return card.ivl >= GURU_MIN_INTERVAL_DAYS


def subject_is_mature(note: NoteRow) -> bool:
    """Mature when every active card meets Guru I threshold (mirrors wk_unlock)."""
    active = [card for card in note.cards if is_active_card(card)]
    if not active:
        return False
    return all(card_meets_maturity(card) for card in active)


def build_mature_subject_ids(notes: Sequence[NoteRow]) -> set[int]:
    mature: set[int] = set()
    for note in notes:
        if note.wk_subject_id is None:
            continue
        if subject_is_mature(note):
            mature.add(note.wk_subject_id)
    return mature


def prerequisites_met(
    prerequisite_ids: Sequence[int],
    mature_subject_ids: set[int],
) -> bool:
    if not prerequisite_ids:
        return True
    return all(prerequisite_id in mature_subject_ids for prerequisite_id in prerequisite_ids)


def is_vocab_locked_by_kanji_prereq(
    note: NoteRow,
    *,
    mature_subject_ids: set[int],
) -> bool:
    """Vocab locked because at least one kanji prerequisite is not yet mature."""
    if note_subject_kind(note) != SUBJECT_TAG_VOCABULARY:
        return False
    if classify_wk_note(note) != "locked":
        return False
    if not note.prerequisite_ids:
        return False
    return not prerequisites_met(note.prerequisite_ids, mature_subject_ids)


def build_vocab_locked_by_wk_level(
    notes: Sequence[NoteRow],
    *,
    mature_subject_ids: set[int],
) -> Tuple[VocabLockedByLevelRow, ...]:
    counts: Dict[int, int] = {}
    for note in notes:
        if not is_vocab_locked_by_kanji_prereq(note, mature_subject_ids=mature_subject_ids):
            continue
        level = note_wk_level(note)
        counts[level] = counts.get(level, 0) + 1
    return tuple(
        VocabLockedByLevelRow(wk_level=level, locked_count=counts[level])
        for level in sorted(counts)
    )


def _empty_jlpt_counts() -> Dict[str, int]:
    return {bucket: 0 for bucket in WK_BUCKET_NAMES}


def build_jlpt_bucket_rows(
    notes: Sequence[NoteRow],
    *,
    subject_kind: str,
) -> Tuple[JlptBucketRow, ...]:
    grouped: Dict[str, Dict[str, int]] = {jlpt: _empty_jlpt_counts() for jlpt in JLPT_LEVELS}
    for note in notes:
        if note_subject_kind(note) != subject_kind:
            continue
        jlpt = wk_level_to_jlpt(note_wk_level(note))
        bucket = classify_wk_note(note)
        grouped[jlpt][bucket] += 1

    rows: List[JlptBucketRow] = []
    for jlpt in JLPT_LEVELS:
        counts = grouped[jlpt]
        total = sum(counts.values())
        if total == 0:
            continue
        rows.append(
            JlptBucketRow(
                jlpt=jlpt,
                subject_kind=subject_kind,
                unseen_count=counts["unseen"],
                apprentice_count=counts["apprentice"],
                guru_count=counts["guru"],
                master_count=counts["master"],
                locked_count=counts["locked"],
                total_notes=total,
            )
        )
    return tuple(rows)


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
    counts = {"unseen": 0, "apprentice": 0, "guru": 0, "master": 0, "locked": 0}
    for note in notes:
        bucket = classify_wk_note(note)
        counts[bucket] += 1
    total = len(notes)
    return WkDeckRow(
        deck_name=deck_name,
        unseen_count=counts["unseen"],
        apprentice_count=counts["apprentice"],
        guru_count=counts["guru"],
        master_count=counts["master"],
        locked_count=counts["locked"],
        total_notes=total,
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
    core_notes = [note for note in notes if note_subject_kind(note) is not None]
    mature_subject_ids = build_mature_subject_ids(core_notes)
    return DeckStatsReport(
        generated_at=timestamp,
        wk_rows=tuple(wk_rows),
        standard_rows=tuple(standard_rows),
        vocab_locked_by_wk_level=build_vocab_locked_by_wk_level(
            core_notes,
            mature_subject_ids=mature_subject_ids,
        ),
        jlpt_kanji_rows=build_jlpt_bucket_rows(core_notes, subject_kind=SUBJECT_TAG_KANJI),
        jlpt_vocab_rows=build_jlpt_bucket_rows(core_notes, subject_kind=SUBJECT_TAG_VOCABULARY),
    )


def _pad(value: int, width: int) -> str:
    return str(value).rjust(width)


def format_deck_stats_report(report: DeckStatsReport) -> str:
    lines = [f"WK Deck Stats — {report.generated_at}", ""]

    if report.wk_rows:
        lines.append(
            "WaniKani core (notes — Unseen reps=0 · Apprentice <7d · Guru 7–29d · Master ≥30d)"
        )
        lines.append("=" * 84)
        header = (
            f"{'Deck':<30} {'Unseen':>6} {'Appr':>5} {'Guru':>6} "
            f"{'Master':>7} {'Locked':>7} {'Total':>6}"
        )
        lines.append(header)
        lines.append("-" * 84)
        totals = {
            "unseen": 0,
            "apprentice": 0,
            "guru": 0,
            "master": 0,
            "locked": 0,
            "total": 0,
        }
        for row in report.wk_rows:
            lines.append(
                f"{row.deck_name:<30} "
                f"{_pad(row.unseen_count, 6)} "
                f"{_pad(row.apprentice_count, 5)} "
                f"{_pad(row.guru_count, 6)} "
                f"{_pad(row.master_count, 7)} "
                f"{_pad(row.locked_count, 7)} "
                f"{_pad(row.total_notes, 6)}"
            )
            totals["unseen"] += row.unseen_count
            totals["apprentice"] += row.apprentice_count
            totals["guru"] += row.guru_count
            totals["master"] += row.master_count
            totals["locked"] += row.locked_count
            totals["total"] += row.total_notes
        lines.append("-" * 84)
        lines.append(
            f"{'Core total':<30} "
            f"{_pad(totals['unseen'], 6)} "
            f"{_pad(totals['apprentice'], 5)} "
            f"{_pad(totals['guru'], 6)} "
            f"{_pad(totals['master'], 7)} "
            f"{_pad(totals['locked'], 7)} "
            f"{_pad(totals['total'], 6)}"
        )
        lines.append("")

    if report.vocab_locked_by_wk_level:
        lines.append(
            "Vocabulary locked by unmet kanji prerequisites (wk-locked/suspended, PrerequisiteIds not mature)"
        )
        lines.append("=" * 40)
        lines.append(f"{'WK Level':>8} {'Locked':>8}")
        lines.append("-" * 40)
        total_locked = 0
        for row in report.vocab_locked_by_wk_level:
            lines.append(f"{_pad(row.wk_level, 8)} {_pad(row.locked_count, 8)}")
            total_locked += row.locked_count
        lines.append("-" * 40)
        lines.append(f"{'Total':>8} {_pad(total_locked, 8)}")
        lines.append("")

    if report.jlpt_kanji_rows or report.jlpt_vocab_rows:
        lines.append("JLPT breakdown — kanji and vocabulary core (by WK level → JLPT band)")
        lines.append("=" * 84)
        for title, rows in (
            ("Kanji", report.jlpt_kanji_rows),
            ("Vocabulary", report.jlpt_vocab_rows),
        ):
            if not rows:
                continue
            lines.append(title)
            header = (
                f"{'JLPT':<5} {'Unseen':>6} {'Appr':>5} {'Guru':>6} "
                f"{'Master':>7} {'Locked':>7} {'Total':>6}"
            )
            lines.append(header)
            lines.append("-" * 84)
            for row in rows:
                lines.append(
                    f"{row.jlpt:<5} "
                    f"{_pad(row.unseen_count, 6)} "
                    f"{_pad(row.apprentice_count, 5)} "
                    f"{_pad(row.guru_count, 6)} "
                    f"{_pad(row.master_count, 7)} "
                    f"{_pad(row.locked_count, 7)} "
                    f"{_pad(row.total_notes, 6)}"
                )
            lines.append("")

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
        "Core buckets use home deck (cards in WK:: filtered queues count toward core). "
        f"Guru ≥ {GURU_MIN_INTERVAL_DAYS}d interval; Master ≥ {MASTER_MIN_INTERVAL_DAYS}d."
    )
    return "\n".join(lines)
