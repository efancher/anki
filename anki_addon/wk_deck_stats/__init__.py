"""
WK Deck Stats — per-deck progress summary for WK core and supplementary decks.

Tools → WK Deck Stats
"""

from __future__ import annotations

from typing import Dict, List

from aqt import gui_hooks, mw
from aqt.qt import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QAction,
)
from aqt.utils import showWarning

from .logic import (
    CORE_DECK_NAMES,
    CardRow,
    NoteRow,
    WK_CORE_TAG,
    build_deck_stats_report,
    field_flag_is_true,
    format_deck_stats_report,
    parse_prerequisite_ids,
    parse_wk_level_from_tags,
    parse_wk_subject_id,
)

ADDON_NAME = "WK Deck Stats"


def _home_deck_id(card) -> int:
    odid = int(getattr(card, "odid", 0) or 0)
    return odid if odid else int(card.did)


def _deck_name_for_card(col, card) -> str:
    return col.decks.name(_home_deck_id(card))


def _card_ids_of_note(col, note_id: int) -> List[int]:
    if hasattr(col, "card_ids_of_note"):
        return [int(card_id) for card_id in col.card_ids_of_note(note_id)]
    return [int(card_id) for card_id in col.cards_of_note(note_id)]


def gather_card_rows(col) -> List[CardRow]:
    rows: List[CardRow] = []
    for card_id in col.db.list("select id from cards"):
        card = col.get_card(int(card_id))
        rows.append(
            CardRow(
                card_id=int(card.id),
                note_id=int(card.nid),
                deck_name=_deck_name_for_card(col, card),
                card_type=int(card.type),
                queue=int(card.queue),
                ivl=int(card.ivl),
                reps=int(card.reps),
            )
        )
    return rows


def _note_field_map(note) -> Dict[str, int]:
    return {field["name"]: index for index, field in enumerate(note.note_type()["flds"])}


def _note_field_value(note, field_map: Dict[str, int], name: str) -> str:
    ord_index = field_map.get(name)
    if ord_index is None:
        return ""
    return note.fields[ord_index] or ""


def gather_note_rows(col, cards: List[CardRow]) -> List[NoteRow]:
    cards_by_note: Dict[int, List[CardRow]] = {}
    for card in cards:
        cards_by_note.setdefault(card.note_id, []).append(card)

    note_ids: set[int] = set()
    for note_id in col.find_notes(f"tag:{WK_CORE_TAG}"):
        note_ids.add(int(note_id))
    for card in cards:
        if card.deck_name in CORE_DECK_NAMES:
            note_ids.add(card.note_id)

    note_rows: List[NoteRow] = []
    for note_id in sorted(note_ids):
        note = col.get_note(note_id)
        field_map = _note_field_map(note)
        note_cards = tuple(cards_by_note.get(note_id, ()))
        if note_cards:
            deck_name = note_cards[0].deck_name
        else:
            card_ids = _card_ids_of_note(col, note_id)
            deck_name = (
                _deck_name_for_card(col, col.get_card(card_ids[0])) if card_ids else ""
            )
        tags = tuple(str(tag) for tag in note.tags)
        level_text = _note_field_value(note, field_map, "Level")
        wk_level = parse_wk_level_from_tags(tags)
        if wk_level is None and level_text.strip():
            try:
                wk_level = int(level_text.strip())
            except ValueError:
                wk_level = None
        note_rows.append(
            NoteRow(
                note_id=note_id,
                deck_name=deck_name,
                tags=tags,
                cards=note_cards,
                wk_subject_id=parse_wk_subject_id(
                    _note_field_value(note, field_map, "WkSubjectId")
                ),
                prerequisite_ids=parse_prerequisite_ids(
                    _note_field_value(note, field_map, "PrerequisiteIds")
                ),
                wk_level=wk_level,
                is_kanji=field_flag_is_true(_note_field_value(note, field_map, "IsKanji")),
                is_vocabulary=field_flag_is_true(
                    _note_field_value(note, field_map, "IsVocabulary")
                ),
                is_radical=deck_name == CORE_DECK_NAMES[0]
                or "radical" in tags,
            )
        )
    return note_rows


class DeckStatsDialog(QDialog):
    def __init__(self, report_text: str, report, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(ADDON_NAME)
        self.resize(920, 720)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Generated {report.generated_at}"))

        if report.wk_rows:
            layout.addWidget(
                QLabel(
                    "WaniKani core (notes — Unseen reps=0 · Apprentice <7d · "
                    "Guru 7–29d · Master ≥30d)"
                )
            )
            layout.addWidget(_make_table(
                ["Deck", "Unseen", "Appr", "Guru", "Master", "Locked", "Total"],
                [
                    [
                        row.deck_name,
                        row.unseen_count,
                        row.apprentice_count,
                        row.guru_count,
                        row.master_count,
                        row.locked_count,
                        row.total_notes,
                    ]
                    for row in report.wk_rows
                ],
                total_row=_sum_wk_rows(report.wk_rows),
            ))

        if report.vocab_locked_by_wk_level:
            layout.addWidget(
                QLabel(
                    "Vocabulary locked by unmet kanji prerequisites "
                    "(wk-locked/suspended with immature PrerequisiteIds)"
                )
            )
            layout.addWidget(_make_table(
                ["WK Level", "Locked"],
                [
                    [row.wk_level, row.locked_count]
                    for row in report.vocab_locked_by_wk_level
                ],
                total_row=[
                    "Total",
                    sum(row.locked_count for row in report.vocab_locked_by_wk_level),
                ],
            ))

        for title, rows in (
            ("JLPT · Kanji", report.jlpt_kanji_rows),
            ("JLPT · Vocabulary", report.jlpt_vocab_rows),
        ):
            if not rows:
                continue
            layout.addWidget(QLabel(f"{title} (WK level → JLPT band)"))
            layout.addWidget(_make_table(
                ["JLPT", "Unseen", "Appr", "Guru", "Master", "Locked", "Total"],
                [
                    [
                        row.jlpt,
                        row.unseen_count,
                        row.apprentice_count,
                        row.guru_count,
                        row.master_count,
                        row.locked_count,
                        row.total_notes,
                    ]
                    for row in rows
                ],
            ))

        if report.standard_rows:
            layout.addWidget(QLabel("Other decks (cards — Anki new / learning / review)"))
            layout.addWidget(_make_table(
                ["Deck", "New", "Learn", "Review", "Susp", "Total"],
                [
                    [
                        row.deck_name,
                        row.new_count,
                        row.learning_count,
                        row.review_count,
                        row.suspended_count,
                        row.total_cards,
                    ]
                    for row in report.standard_rows
                ],
            ))

        footer = (
            f"Guru ≥ 7d interval; Master ≥ 30d. "
            "Cards in WK:: filtered queues count toward home deck."
        )
        layout.addWidget(QLabel(footer))
        self._report_text = report_text

    def report_text(self) -> str:
        return self._report_text


def _sum_wk_rows(rows) -> List[object]:
    return [
        "Core total",
        sum(row.unseen_count for row in rows),
        sum(row.apprentice_count for row in rows),
        sum(row.guru_count for row in rows),
        sum(row.master_count for row in rows),
        sum(row.locked_count for row in rows),
        sum(row.total_notes for row in rows),
    ]


def _make_table(
    headers: List[str],
    rows: List[List[object]],
    *,
    total_row: List[object] | None = None,
) -> QTableWidget:
    table = QTableWidget()
    body = list(rows)
    if total_row is not None:
        body.append(total_row)
    table.setRowCount(len(body))
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for column in range(1, len(headers)):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

    for row_index, row in enumerate(body):
        for column_index, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            if column_index > 0:
                item.setTextAlignment(int(0x0004 | 0x0080))  # AlignRight | AlignVCenter
            if total_row is not None and row_index == len(body) - 1:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            table.setItem(row_index, column_index, item)
    return table


def run_deck_stats() -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return

    col = mw.col
    cards = gather_card_rows(col)
    notes = gather_note_rows(col, cards)
    report = build_deck_stats_report(cards=cards, notes=notes)
    text = format_deck_stats_report(report)
    dialog = DeckStatsDialog(text, report, mw)
    dialog.exec()


def add_menu_action() -> None:
    action = QAction("WK Deck Stats", mw)
    action.triggered.connect(run_deck_stats)
    mw.form.menuTools.addAction(action)


gui_hooks.main_window_did_init.append(add_menu_action)
