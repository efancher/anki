"""
Pure health-check logic for WK Anki collections (testable without Anki runtime).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ANKI_CARD_TYPE_NEW = 0
ANKI_CARD_TYPE_LEARN = 1
ANKI_CARD_TYPE_REVIEW = 2
ANKI_CARD_TYPE_RELEARN = 3
ANKI_QUEUE_SUSPENDED = -1

CORE_RADICALS_DECK = "WaniKani Core · Radicals"
CORE_KANJI_DECK = "WaniKani Core · Kanji"
CORE_VOCABULARY_DECK = "WaniKani Core · Vocabulary"
CORE_DECK_NAMES = (CORE_RADICALS_DECK, CORE_KANJI_DECK, CORE_VOCABULARY_DECK)

WK_CORE_TAG = "wk-core"
WK_LOCKED_TAG = "wk-locked"
MATURE_MIN_INTERVAL_DAYS = 7

TK_GRAMMAR_VOCAB_TAG = "tk-grammar-vocab"
TK_GRAMMAR_PREREQ_TAG = "tk-grammar-prereq"
JLPT_N5_VOCAB_TAG = "jlpt-n5-vocab"
JLPT_N5_PREREQ_TAG = "jlpt-n5-prereq"

EXPECTED_WK_FILTERED_DECK_NAMES = (
    "WK::Core Radicals",
    "WK::Core Kanji",
    "WK::Core Vocabulary",
    "WK::Tae Kim · Grammar Vocab",
    "WK::Tae Kim · Grammar Prereq Kanji",
    "WK::Tae Kim · Grammar Prereq Radicals",
    "WK::N5 · Kanji",
    "WK::N5 · Vocabulary",
    "WK::N5 · Prereq Kanji",
    "WK::N5 · Prereq Radicals",
    "WK::Vocab Context",
    "WK::Dictation",
    "WK::Conjugations · Verbs",
    "WK::Conjugations · Adjectives",
    "WK::Conjugations · Reverse",
    "WK::Conjugations · Verb Types",
    "WK::Conjugations · Adjective Types",
    "WK::Grammar",
    "WK::Grammar · Current Tae Kim lesson",
    "WK::Phonetic Families",
)

SEVERITY_OK = "ok"
SEVERITY_WARN = "warn"
SEVERITY_FAIL = "fail"
SEVERITY_INFO = "info"


@dataclass(frozen=True)
class CardSnapshot:
    card_id: int
    note_id: int
    deck_name: str
    card_type: int
    queue: int
    due: int
    ivl: int
    reps: int
    lapses: int
    filtered_queue_deck_name: Optional[str] = None


@dataclass(frozen=True)
class NoteSnapshot:
    note_id: int
    guid: str
    deck_name: str
    tags: Tuple[str, ...]
    wk_subject_id: Optional[int]


@dataclass(frozen=True)
class DeckPresetInfo:
    deck_name: str
    preset_name: str


@dataclass(frozen=True)
class FilteredDeckInfo:
    name: str
    reschedule: bool
    card_count: int


@dataclass
class DeckCardCounts:
    deck_name: str
    new: int = 0
    learn: int = 0
    review: int = 0
    relearning: int = 0
    suspended: int = 0
    mature: int = 0
    reps_total: int = 0
    reviewed_once: int = 0


@dataclass(frozen=True)
class CollectionMetrics:
    core_review_cards: int
    core_reps_total: int
    core_mature: int
    core_learn: int
    core_new: int
    core_reviewed_once: int


@dataclass(frozen=True)
class HealthLine:
    severity: str
    message: str


@dataclass
class HealthReport:
    generated_at: str
    lines: List[HealthLine] = field(default_factory=list)
    metrics: Optional[CollectionMetrics] = None

    def add(self, severity: str, message: str) -> None:
        self.lines.append(HealthLine(severity=severity, message=message))


def _tag_set(tags: Sequence[str]) -> set[str]:
    return {tag for tag in tags if tag}


def note_has_tag(note: NoteSnapshot, tag: str) -> bool:
    return tag in note.tags or any(item.startswith(f"{tag}::") for item in note.tags)


def is_core_card(card: CardSnapshot) -> bool:
    return card.deck_name in CORE_DECK_NAMES


def count_core_cards_in_filtered_queues(cards: Sequence[CardSnapshot]) -> int:
    return sum(
        1
        for card in cards
        if is_core_card(card) and card.filtered_queue_deck_name is not None
    )


def is_active_card(card: CardSnapshot) -> bool:
    return card.queue != ANKI_QUEUE_SUSPENDED


def is_mature_card(card: CardSnapshot, *, min_interval_days: int = MATURE_MIN_INTERVAL_DAYS) -> bool:
    return is_active_card(card) and card.ivl >= min_interval_days


def deck_counts_from_cards(cards: Sequence[CardSnapshot], deck_name: str) -> DeckCardCounts:
    counts = DeckCardCounts(deck_name=deck_name)
    for card in cards:
        if card.deck_name != deck_name:
            continue
        if card.queue == ANKI_QUEUE_SUSPENDED:
            counts.suspended += 1
            continue
        if card.reps > 0:
            counts.reviewed_once += 1
        counts.reps_total += card.reps
        if is_mature_card(card):
            counts.mature += 1
        if card.card_type == ANKI_CARD_TYPE_NEW:
            counts.new += 1
        elif card.card_type == ANKI_CARD_TYPE_LEARN:
            counts.learn += 1
        elif card.card_type == ANKI_CARD_TYPE_REVIEW:
            counts.review += 1
        elif card.card_type == ANKI_CARD_TYPE_RELEARN:
            counts.relearning += 1
    return counts


def find_duplicate_wk_subject_ids(notes: Sequence[NoteSnapshot]) -> Dict[int, List[int]]:
    by_subject: Dict[int, List[int]] = {}
    for note in notes:
        if note.wk_subject_id is None:
            continue
        by_subject.setdefault(note.wk_subject_id, []).append(note.note_id)
    return {subject_id: ids for subject_id, ids in by_subject.items() if len(ids) > 1}


def find_suspicious_scheduling_cards(cards: Sequence[CardSnapshot]) -> List[CardSnapshot]:
    suspicious: List[CardSnapshot] = []
    for card in cards:
        if not is_core_card(card) or not is_active_card(card):
            continue
        if card.reps > 0 and card.card_type == ANKI_CARD_TYPE_NEW:
            suspicious.append(card)
            continue
        if card.reps > 5 and card.ivl <= 0 and card.card_type == ANKI_CARD_TYPE_REVIEW:
            suspicious.append(card)
    return suspicious


def count_priority_tagged_notes(notes: Sequence[NoteSnapshot]) -> Dict[str, int]:
    tags = (
        TK_GRAMMAR_VOCAB_TAG,
        TK_GRAMMAR_PREREQ_TAG,
        JLPT_N5_VOCAB_TAG,
        JLPT_N5_PREREQ_TAG,
    )
    counts = {tag: 0 for tag in tags}
    for note in notes:
        for tag in tags:
            if note_has_tag(note, tag):
                counts[tag] += 1
    return counts


def build_collection_metrics(cards: Sequence[CardSnapshot]) -> CollectionMetrics:
    core_cards = [card for card in cards if is_core_card(card) and is_active_card(card)]
    return CollectionMetrics(
        core_review_cards=sum(1 for card in core_cards if card.card_type == ANKI_CARD_TYPE_REVIEW),
        core_reps_total=sum(card.reps for card in core_cards),
        core_mature=sum(1 for card in core_cards if is_mature_card(card)),
        core_learn=sum(
            1
            for card in core_cards
            if card.card_type in (ANKI_CARD_TYPE_LEARN, ANKI_CARD_TYPE_RELEARN)
        ),
        core_new=sum(1 for card in core_cards if card.card_type == ANKI_CARD_TYPE_NEW),
        core_reviewed_once=sum(1 for card in core_cards if card.reps > 0),
    )


def snapshot_payload(metrics: CollectionMetrics, *, generated_at: Optional[str] = None) -> dict:
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": timestamp,
        "metrics": {
            "core_review_cards": metrics.core_review_cards,
            "core_reps_total": metrics.core_reps_total,
            "core_mature": metrics.core_mature,
            "core_learn": metrics.core_learn,
            "core_new": metrics.core_new,
            "core_reviewed_once": metrics.core_reviewed_once,
        },
    }


def compare_metric_snapshots(
    previous: Mapping[str, int],
    current: Mapping[str, int],
) -> List[HealthLine]:
    lines: List[HealthLine] = []
    labels = {
        "core_review_cards": "Core review cards",
        "core_reps_total": "Core total reps",
        "core_mature": "Core mature (≥7d)",
        "core_learn": "Core learning",
        "core_new": "Core new",
        "core_reviewed_once": "Core cards reviewed at least once",
    }
    for key, label in labels.items():
        before = int(previous.get(key, 0))
        after = int(current.get(key, 0))
        delta = after - before
        if delta == 0:
            lines.append(HealthLine(SEVERITY_OK, f"{label}: {after} (unchanged)"))
            continue
        sign = "+" if delta > 0 else ""
        severity = SEVERITY_OK
        if key in {"core_review_cards", "core_reps_total", "core_mature", "core_reviewed_once"} and delta < 0:
            severity = SEVERITY_WARN
        lines.append(HealthLine(severity, f"{label}: {before} → {after} ({sign}{delta})"))
    return lines


def build_health_report(
    *,
    cards: Sequence[CardSnapshot],
    notes: Sequence[NoteSnapshot],
    deck_presets: Sequence[DeckPresetInfo],
    filtered_decks: Sequence[FilteredDeckInfo],
    study_priority_path: Optional[str],
    study_priority_subject_count: int,
    collection_mod: Optional[int],
    locked_note_count: Optional[int] = None,
    previous_snapshot: Optional[Mapping[str, object]] = None,
) -> HealthReport:
    report = HealthReport(generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    core_notes = [note for note in notes if note_has_tag(note, WK_CORE_TAG)]
    core_cards = [card for card in cards if is_core_card(card)]

    if collection_mod is not None:
        report.add(SEVERITY_INFO, f"Collection last modified: {collection_mod}")

    report.add(SEVERITY_INFO, f"Core notes (tag:wk-core): {len(core_notes)}")
    report.add(SEVERITY_INFO, f"Core cards: {len(core_cards)}")

    in_filtered = count_core_cards_in_filtered_queues(cards)
    if in_filtered:
        report.add(
            SEVERITY_INFO,
            f"{in_filtered} core cards currently in WK filtered queues (scheduling unchanged).",
        )

    for deck_name in CORE_DECK_NAMES:
        counts = deck_counts_from_cards(cards, deck_name)
        if counts.new + counts.learn + counts.review + counts.relearning + counts.suspended == 0:
            report.add(SEVERITY_FAIL, f"Missing or empty deck: {deck_name}")
            continue
        report.add(
            SEVERITY_INFO,
            (
                f"{deck_name}: new {counts.new}, learn {counts.learn}, "
                f"review {counts.review}, relearning {counts.relearning}, "
                f"suspended {counts.suspended}, mature {counts.mature}, "
                f"reps {counts.reps_total}"
            ),
        )

    metrics = build_collection_metrics(cards)
    report.metrics = metrics

    if metrics.core_reviewed_once == 0:
        report.add(
            SEVERITY_WARN,
            "No core cards have reps > 0 — scheduling may not have started or was reset.",
        )
    else:
        report.add(
            SEVERITY_OK,
            f"{metrics.core_reviewed_once} core cards have review history (reps > 0).",
        )

    if metrics.core_review_cards == 0 and metrics.core_reviewed_once > 50:
        report.add(
            SEVERITY_WARN,
            "Many core cards were reviewed before but none are in review state now.",
        )

    suspicious = find_suspicious_scheduling_cards(cards)
    if suspicious:
        report.add(
            SEVERITY_WARN,
            f"{len(suspicious)} core cards look mis-scheduled (reps>0 but still new, or review with ivl=0).",
        )
    else:
        report.add(SEVERITY_OK, "No obvious mis-scheduled core cards detected.")

    duplicates = find_duplicate_wk_subject_ids(core_notes)
    if duplicates:
        sample = next(iter(duplicates.items()))
        report.add(
            SEVERITY_WARN,
            f"{len(duplicates)} duplicate WkSubjectId values in core notes (e.g. {sample[0]} → {len(sample[1])} notes).",
        )
    else:
        report.add(SEVERITY_OK, "WkSubjectId values are unique across core notes.")

    priority_counts = count_priority_tagged_notes(core_notes)
    for tag, count in priority_counts.items():
        report.add(SEVERITY_INFO, f"tag:{tag}: {count} core notes")

    if locked_note_count is not None:
        report.add(SEVERITY_INFO, f"tag:wk-locked notes: {locked_note_count}")

    for preset in deck_presets:
        if "WK FSRS" in preset.preset_name:
            report.add(SEVERITY_OK, f"{preset.deck_name}: preset “{preset.preset_name}”")
        else:
            report.add(
                SEVERITY_WARN,
                f"{preset.deck_name}: expected WK FSRS preset, got “{preset.preset_name}”.",
            )

    filtered_by_name = {deck.name: deck for deck in filtered_decks}
    missing_filtered = [
        name for name in EXPECTED_WK_FILTERED_DECK_NAMES if name not in filtered_by_name
    ]
    for name in missing_filtered:
        report.add(SEVERITY_WARN, f"Filtered deck missing: {name}")

    reschedule_off = [deck.name for deck in filtered_decks if not deck.reschedule]
    if reschedule_off:
        report.add(
            SEVERITY_FAIL,
            f"{len(reschedule_off)} WK filtered decks have reschedule OFF (Good/Easy will show “end”): "
            + ", ".join(reschedule_off[:5])
            + ("…" if len(reschedule_off) > 5 else ""),
        )
    elif filtered_decks:
        report.add(SEVERITY_OK, f"{len(filtered_decks)} WK:: filtered decks; reschedule enabled on all checked.")

    if study_priority_path:
        report.add(
            SEVERITY_OK,
            f"wk_study_priority.json: {study_priority_path} ({study_priority_subject_count} subjects).",
        )
    else:
        report.add(
            SEVERITY_WARN,
            "wk_study_priority.json not found — adaptive new reordering may be inactive.",
        )

    if previous_snapshot:
        previous_metrics = previous_snapshot.get("metrics") or {}
        if isinstance(previous_metrics, dict):
            generated = str(previous_snapshot.get("generated_at") or "previous run")
            report.add(SEVERITY_INFO, f"Compared to snapshot from {generated}:")
            for line in compare_metric_snapshots(previous_metrics, snapshot_payload(metrics)["metrics"]):
                report.lines.append(line)

    return report


def format_health_report(report: HealthReport) -> str:
    icon = {
        SEVERITY_OK: "✓",
        SEVERITY_WARN: "⚠",
        SEVERITY_FAIL: "✗",
        SEVERITY_INFO: "·",
    }
    header = f"WK Health Check — {report.generated_at}\n{'=' * 60}\n"
    body = "\n".join(f"{icon.get(line.severity, '?')} {line.message}" for line in report.lines)
    footer = (
        "\n\nTip: run again after import or WK Adjust New Limits. "
        "Review-card and reps totals should not drop sharply unless you reset scheduling. "
        "After WK Setup Filtered Decks, home deck counts may look lower while cards sit in "
        "WK:: queues — metrics here use home decks and should stay stable."
    )
    return header + body + footer
