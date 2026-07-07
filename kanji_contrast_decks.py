"""
Curated kanji contrast decks — side-by-side groups of 2–6 easily confused kanji.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import genanki

from wk_decks import (
    COMMON_CSS,
    DECK_IDS,
    DECK_NAMES,
    MODEL_IDS,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WK_MNEMONIC_CSS,
    WkModel,
    first_reading,
    kanji_radicals_back_html,
    pitch_for,
    primary_meanings,
    primary_readings,
    srs_stage,
    stable_guid,
    strip_html,
    versioned_css,
    write_apkg,
)

KANJI_CONTRAST_JSON = "kanji_contrast_groups.json"
KANJI_CONTRAST_KIND = "kanji-contrast"
MIN_KANJI_CONTRAST_GROUP_SIZE = 2
MAX_KANJI_CONTRAST_GROUP_SIZE = 6

KANJI_CONTRAST_CSS = """
.kanji-contrast-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 14px;
  align-items: start;
  max-width: 960px;
  margin: 0 auto;
  text-align: center;
}
.kanji-contrast-front-item .jp { font-size: 38px; margin: 4px 0; }
.kanji-contrast-front-item .reading { font-size: 20px; }
.kanji-contrast-back-item {
  text-align: left;
  border: 1px solid #444;
  border-radius: 8px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.03);
}
.kanji-contrast-back-item .jp { font-size: 34px; margin: 0 0 6px; text-align: center; }
.kanji-contrast-back-item .reading { font-size: 18px; text-align: center; }
.kanji-contrast-back-item .meaning { font-size: 17px; margin: 8px 0; }
.kanji-contrast-back-item .radical-breakdown { font-size: 14px; margin-top: 8px; }
.kanji-contrast-note { text-align: left; max-width: 820px; margin: 12px auto; color: #ccc; }
@media (max-width: 700px) {
  .kanji-contrast-grid { grid-template-columns: 1fr; }
}
"""


GROUP_ID_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class KanjiContrastGroup:
    kanji_chars: Tuple[str, ...]
    title: str = ""
    note: str = ""
    group_id: str = ""


def slugify_group_id(text: str) -> str:
    slug = GROUP_ID_RE.sub("-", text.strip().lower()).strip("-")
    return slug or "group"


def group_stable_key(group: KanjiContrastGroup) -> str:
    """Stable identity for re-import — survives adding/removing kanji in a group."""
    if group.group_id:
        return group.group_id
    if group.title:
        return slugify_group_id(group.title)
    return "-".join(group.kanji_chars)


def group_note_guid(group: KanjiContrastGroup, members: Sequence[dict]) -> str:
    if group.group_id or group.title:
        return stable_guid(KANJI_CONTRAST_KIND, group_stable_key(group))
    return stable_guid(KANJI_CONTRAST_KIND, *[item["id"] for item in members])


def default_groups_path() -> Path:
    return Path(__file__).resolve().parent / KANJI_CONTRAST_JSON


def load_kanji_contrast_groups(path: Optional[Path] = None) -> List[KanjiContrastGroup]:
    groups_path = path or default_groups_path()
    payload = json.loads(groups_path.read_text(encoding="utf-8"))
    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list):
        raise ValueError(f"{groups_path.name} must contain a top-level 'groups' list.")

    groups: List[KanjiContrastGroup] = []
    for index, entry in enumerate(raw_groups, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Group {index} must be an object.")
        kanji = entry.get("kanji")
        if not isinstance(kanji, list):
            raise ValueError(f"Group {index} must include a 'kanji' list.")
        chars = tuple(str(ch).strip() for ch in kanji if str(ch).strip())
        if len(chars) < MIN_KANJI_CONTRAST_GROUP_SIZE:
            raise ValueError(
                f"Group {index} needs at least {MIN_KANJI_CONTRAST_GROUP_SIZE} kanji "
                f"(got {len(chars)})."
            )
        if len(chars) > MAX_KANJI_CONTRAST_GROUP_SIZE:
            raise ValueError(
                f"Group {index} supports at most {MAX_KANJI_CONTRAST_GROUP_SIZE} kanji "
                f"(got {len(chars)})."
            )
        if len(set(chars)) != len(chars):
            raise ValueError(f"Group {index} has duplicate kanji.")
        title = str(entry.get("title") or "").strip()
        note = str(entry.get("note") or "").strip()
        group_id = str(entry.get("id") or "").strip()
        groups.append(
            KanjiContrastGroup(
                kanji_chars=chars,
                title=title,
                note=note,
                group_id=group_id,
            )
        )
    return groups


def resolve_kanji_contrast_groups(
    groups: Sequence[KanjiContrastGroup],
    kanji_by_char: Mapping[str, dict],
) -> Tuple[List[Tuple[KanjiContrastGroup, List[dict]]], List[str]]:
    resolved: List[Tuple[KanjiContrastGroup, List[dict]]] = []
    warnings: List[str] = []
    for group in groups:
        members: List[dict] = []
        missing: List[str] = []
        for char in group.kanji_chars:
            subject = kanji_by_char.get(char)
            if subject is None:
                missing.append(char)
                continue
            members.append(subject)
        if missing:
            warnings.append(
                f"Skipped group {group.title or ' / '.join(group.kanji_chars)}: "
                f"missing kanji {', '.join(missing)}"
            )
            continue
        resolved.append((group, members))
    return resolved, warnings


def group_display_title(group: KanjiContrastGroup, members: Sequence[dict]) -> str:
    if group.title:
        return group.title
    return " · ".join(item["data"].get("characters") or "?" for item in members)


def kanji_contrast_front_item_html(subject: dict) -> str:
    expr = html.escape(subject["data"].get("characters") or "")
    return f"<div class='kanji-contrast-front-item'><div class='jp'>{expr}</div></div>"


def kanji_contrast_back_item_html(
    subject: dict,
    assignment_index: Mapping[int, dict],
    pitch_index: Mapping[Tuple[str, str], dict],
    radical_index: Mapping[int, dict],
) -> str:
    data = subject["data"]
    expr = html.escape(data.get("characters") or "")
    reading = html.escape("、".join(primary_readings(subject)) or first_reading(subject))
    meanings = html.escape("; ".join(primary_meanings(subject)))
    pitch = pitch_for(subject, pitch_index)
    pitch_html = ""
    if pitch.get("pitch") or pitch.get("pattern"):
        pitch_html = (
            f"<div class='pitch'><b>Pitch:</b> "
            f"{html.escape(str(pitch.get('pitch') or ''))} "
            f"<span>{html.escape(str(pitch.get('pattern') or ''))}</span></div>"
        )
    radicals_html = kanji_radicals_back_html(subject, radical_index)
    mnemonic = strip_html(data.get("meaning_mnemonic") or "")
    mnemonic_html = ""
    if mnemonic:
        snippet = html.escape(mnemonic[:220] + ("…" if len(mnemonic) > 220 else ""))
        mnemonic_html = f"<div class='notes'><b>Mnemonic:</b> {snippet}</div>"
    meta = html.escape(
        f"WK Level {data.get('level', '?')} · SRS {srs_stage(subject, assignment_index)}"
    )
    return f"""
    <div class="kanji-contrast-back-item">
      <div class="jp">{expr}</div>
      <div class="reading">{reading}</div>
      <div class="meaning">{meanings}</div>
      {pitch_html}
      {radicals_html}
      {mnemonic_html}
      <div class="meta">{meta}</div>
    </div>
    """


def make_kanji_contrast_model() -> WkModel:
    return WkModel(
        MODEL_IDS["kanji_contrast"],
        NOTE_TYPE_NAMES["kanji_contrast"],
        template_key="kanji_contrast",
        fields=[
            {"name": "GuidKey"},
            {"name": "Title"},
            {"name": "Prompt"},
            {"name": "MembersFrontHtml"},
            {"name": "MembersBackHtml"},
            {"name": "Note"},
            {"name": "Meta"},
        ],
        templates=[
            {
                "name": "Compare Kanji",
                "qfmt": """
                <div class="prompt">{{Prompt}}</div>
                <div class="family-title">{{Title}}</div>
                <div class="kanji-contrast-grid">{{MembersFrontHtml}}</div>
                """,
                "afmt": """
                {{FrontSide}}
                <hr>
                <div class="kanji-contrast-grid">{{MembersBackHtml}}</div>
                {{#Note}}<div class="kanji-contrast-note">{{Note}}</div>{{/Note}}
                <div class="meta">{{Meta}}</div>
                """,
            }
        ],
        css=versioned_css(COMMON_CSS + KANJI_CONTRAST_CSS + WK_MNEMONIC_CSS, "kanji_contrast"),
    )


def build_kanji_contrast_deck(
    resolved_groups: Sequence[Tuple[KanjiContrastGroup, Sequence[dict]]],
    assignment_index: Mapping[int, dict],
    pitch_index: Mapping[Tuple[str, str], dict],
    radical_index: Mapping[int, dict],
    output_dir: Path,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(DECK_IDS["kanji-contrast"], DECK_NAMES["kanji-contrast"])
    model = make_kanji_contrast_model()
    deck.add_model(model)
    template_label = MODEL_TEMPLATE_VERSIONS["kanji_contrast"]

    for group, members in resolved_groups:
        title = group_display_title(group, members)
        members_front = "".join(kanji_contrast_front_item_html(item) for item in members)
        members_back = "".join(
            kanji_contrast_back_item_html(item, assignment_index, pitch_index, radical_index)
            for item in members
        )
        guid = group_note_guid(group, members)
        levels = sorted(int(item["data"].get("level") or 0) for item in members)
        meta = (
            f"{len(members)} kanji · WK levels {levels[0]}–{levels[-1]} · "
            f"template {template_label}"
        )
        note = genanki.Note(
            model=model,
            fields=[
                guid,
                html.escape(title),
                "What makes each kanji different? Name meaning and reading for each.",
                members_front,
                members_back,
                html.escape(group.note),
                html.escape(meta),
            ],
            tags=[
                "wanikani",
                "kanji-contrast",
                "priority-medium",
                f"wk-level-{levels[0]}",
            ],
            guid=guid,
        )
        deck.add_note(note)

    out = output_dir / "wk_kanji_contrast.apkg"
    write_apkg(deck, out)
    return out, deck
