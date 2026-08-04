"""
Pitch accent lookup for immersion notes (Satori / Shadowing) from Kanjium.

Fills PitchAccents / PitchPositions / PitchGraphs from a Yomitan-format pitch
dictionary zip (e.g. kanjium_pitch_accents.zip). Yomitan mining already gets
these from the browser; CSV/project imports need this backfill.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from shadowing_match import katakana_to_hiragana
from wk_decks import load_yomitan_pitch

REPO_ROOT = Path(__file__).resolve().parent

# Small kana that attach to the previous character as one mora (ゃゅょ…).
_SMALL_KANA = set("ゃゅょぁぃぅぇぉャュョァィゥェォゎヮ")


@dataclass(frozen=True)
class ImmersionPitchFields:
    accents: str
    positions: str
    graphs: str

    @property
    def has_data(self) -> bool:
        return bool(self.positions.strip())


def default_pitch_dict_paths() -> List[Path]:
    """Likely Kanjium / NHK Yomitan pitch dictionary locations."""
    env = (os.environ.get("WK_PITCH_DICT") or "").strip()
    candidates = [
        Path(env) if env else None,
        Path.home() / "Downloads" / "kanjium_pitch_accents.zip",
        Path.home() / "Downloads" / "03_[Pitch]_NHK2016.zip",
        Path.home() / "japanese-dicts" / "kanjium_pitch_accents.zip",
        REPO_ROOT / "dicts" / "kanjium_pitch_accents.zip",
        REPO_ROOT / "out" / "kanjium_pitch_accents.zip",
    ]
    return [path for path in candidates if path is not None]


def resolve_pitch_dict_path(explicit: Optional[Path] = None) -> Optional[Path]:
    if explicit is not None:
        path = explicit.expanduser().resolve()
        return path if path.is_file() or path.is_dir() else None
    for path in default_pitch_dict_paths():
        if path.is_file() or path.is_dir():
            return path.resolve()
    return None


def load_immersion_pitch_index(path: Optional[Path]) -> Dict[Tuple[str, str], dict]:
    if path is None:
        return {}
    return load_yomitan_pitch(str(path))


def split_morae(reading: str) -> List[str]:
    """Split a kana reading into morae (ゃ/ゅ/ょ attach to the previous kana)."""
    text = (reading or "").strip()
    if not text:
        return []
    morae: List[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if index + 1 < len(text) and text[index + 1] in _SMALL_KANA:
            morae.append(char + text[index + 1])
            index += 2
            continue
        morae.append(char)
        index += 1
    return morae


def pitch_pattern_label(position: int, mora_count: int) -> str:
    if position <= 0:
        return "平板"
    if position == 1:
        return "頭高"
    if mora_count > 0 and position >= mora_count:
        return "尾高"
    return "中高"


def downstep_reading(morae: Sequence[str], position: int) -> str:
    if not morae:
        return ""
    if position <= 0:
        return "".join(morae) + "￣"
    if position >= len(morae):
        return "".join(morae) + "↘"
    return "".join(morae[:position]) + "↓" + "".join(morae[position:])


def pitch_graph_html(morae: Sequence[str], position: int) -> str:
    """Compact high/low mora graph (heiban / atamadaka / nakadaka / odaka)."""
    if not morae:
        return ""
    count = len(morae)
    classes: List[str] = []
    if position <= 0:
        # Heiban: low then high for the rest.
        classes = ["l"] + ["h"] * (count - 1) if count > 1 else ["h"]
    elif position == 1:
        classes = ["h"] + ["l"] * (count - 1)
    else:
        drop_after = min(position, count)
        classes = []
        for index in range(count):
            mora_number = index + 1
            if mora_number == 1:
                classes.append("l")
            elif mora_number <= drop_after:
                classes.append("h")
            else:
                classes.append("l")
    spans: List[str] = []
    for index, mora in enumerate(morae):
        css = classes[index]
        drop = " drop" if position > 0 and index + 1 == position and index + 1 < count else ""
        if position > 0 and index + 1 == count and position >= count:
            drop = " drop"
        spans.append(f'<span class="pitch-mora {css}{drop}">{mora}</span>')
    label = pitch_pattern_label(position, count)
    return (
        f'<span class="pitch-graph" title="{label} ({position})">'
        f'{"".join(spans)}</span>'
    )


def sentence_pitch_graphs_html(accent_phrases: Sequence[Mapping[str, object]]) -> str:
    """High/low mora graphs for a full VOICEVOX ``accent_phrases`` list.

    Uses the same ``pitch-graph`` / ``pitch-mora`` markup as word PitchGraphs so
    existing card CSS applies. Mora text is shown in hiragana. Phrase breaks get a
    thin separator (particles usually stay attached to their content phrase).
    """
    parts: List[str] = []
    for phrase in accent_phrases:
        if not isinstance(phrase, Mapping):
            continue
        raw_moras = phrase.get("moras") or []
        if not isinstance(raw_moras, (list, tuple)):
            continue
        morae: List[str] = []
        for mora in raw_moras:
            if not isinstance(mora, Mapping):
                continue
            text = katakana_to_hiragana(str(mora.get("text") or "").strip())
            if text:
                morae.append(text)
        if not morae:
            continue
        try:
            position = int(phrase.get("accent") or 0)
        except (TypeError, ValueError):
            position = 0
        graph = pitch_graph_html(morae, position)
        if graph:
            parts.append(graph)
    return "".join(parts)


def _positions_from_entry(entry: Mapping[str, object]) -> List[int]:
    raw_positions = entry.get("positions")
    positions: List[int] = []
    if isinstance(raw_positions, (list, tuple)):
        for item in raw_positions:
            try:
                positions.append(int(item))
            except (TypeError, ValueError):
                continue
    if positions:
        return positions
    pitch_raw = str(entry.get("pitch") or "").strip()
    if not pitch_raw:
        return []
    for part in pitch_raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            positions.append(int(part))
        except ValueError:
            continue
    return positions


def lookup_pitch_entry(
    expression: str,
    reading: str,
    pitch_index: Mapping[Tuple[str, str], dict],
) -> Optional[dict]:
    expr = (expression or "").strip()
    reading_raw = (reading or "").strip()
    if not expr or not reading_raw or not pitch_index:
        return None
    reading_hira = katakana_to_hiragana(reading_raw)
    for key in (
        (expr, reading_hira),
        (expr, reading_raw),
        (katakana_to_hiragana(expr), reading_hira),
    ):
        entry = pitch_index.get(key)
        if entry:
            return entry
    return None


def format_immersion_pitch(
    expression: str,
    reading: str,
    pitch_index: Mapping[Tuple[str, str], dict],
) -> ImmersionPitchFields:
    entry = lookup_pitch_entry(expression, reading, pitch_index)
    if entry is None:
        return ImmersionPitchFields("", "", "")
    reading_hira = katakana_to_hiragana((reading or "").strip()) or str(entry.get("reading") or "")
    morae = split_morae(reading_hira)
    positions = _positions_from_entry(entry)
    if not positions:
        return ImmersionPitchFields("", "", "")

    accent_parts: List[str] = []
    graph_parts: List[str] = []
    for position in positions:
        label = pitch_pattern_label(position, len(morae))
        accent_parts.append(f"{downstep_reading(morae, position)} ({label})")
        graph_parts.append(pitch_graph_html(morae, position))

    return ImmersionPitchFields(
        accents=" · ".join(accent_parts),
        positions=", ".join(str(position) for position in positions),
        graphs=" ".join(graph_parts),
    )


def pitch_field_values(
    expression: str,
    reading: str,
    pitch_index: Optional[Mapping[Tuple[str, str], dict]],
) -> Dict[str, str]:
    if not pitch_index:
        return {"PitchAccents": "", "PitchPositions": "", "PitchGraphs": ""}
    fields = format_immersion_pitch(expression, reading, pitch_index)
    return {
        "PitchAccents": fields.accents,
        "PitchPositions": fields.positions,
        "PitchGraphs": fields.graphs,
    }
