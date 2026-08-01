"""
shadowing_decks.py

Immersion · Shadowing — sentence cloze cards from a shadowmine project.

One WK-linked cloze note per matched vocabulary word in a sentence (native clip
audio). Separate curated candidate deck for non-WK content words.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import genanki

from mining_vocab_index import load_mining_vocab_index, lookup_wk_vocab
from shadowing_match import (
    CandidateLemma,
    WkMatch,
    candidate_lemmas_in_sentence,
    candidate_reading_looks_truncated,
    match_wk_vocab_in_sentence,
    name_surface_for_shogo,
    reading_for_candidate_lemma,
    reading_for_surface_in_sentence,
)
from satori_decks import build_satori_cloze_sentence, should_skip_copula_cloze
from immersion_pitch import pitch_field_values
from wk_decks import (
    COMMON_CSS,
    DECK_IDS,
    DECK_NAMES,
    MODEL_IDS,
    MODEL_TEMPLATE_VERSIONS,
    NOTE_TYPE_NAMES,
    WkModel,
    stable_guid,
    versioned_css,
    write_apkg,
)

REPO_ROOT = Path(__file__).resolve().parent
IMMERSION_LOGIC = REPO_ROOT / "anki_addon" / "wk_immersion"
if str(IMMERSION_LOGIC) not in sys.path:
    sys.path.insert(0, str(IMMERSION_LOGIC))

from mining_logic import enrich_mining_note_fields  # noqa: E402

SHADOWING_KIND = "shadowing-mining"
SHADOWING_TAG = "shadowing-mining"
SHADOWING_CANDIDATE_KIND = "shadowing-candidate"
SHADOWING_CANDIDATE_TAG = "shadowing-candidate"

SHADOWING_DECK_ID = DECK_IDS["shadowing"]
SHADOWING_MODEL_ID = MODEL_IDS["shadowing"]
SHADOWING_DECK_NAME = DECK_NAMES["shadowing"]
SHADOWING_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["shadowing"]
SHADOWING_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["shadowing"]
SHADOWING_MODEL_TEMPLATE_KEY = "shadowing"
SHADOWING_EXPORT_FILENAME = "wk_shadowing.apkg"

SHADOWING_CANDIDATE_DECK_ID = DECK_IDS["shadowing-candidates"]
SHADOWING_CANDIDATE_MODEL_ID = MODEL_IDS["shadowing_candidate"]
SHADOWING_CANDIDATE_DECK_NAME = DECK_NAMES["shadowing-candidates"]
SHADOWING_CANDIDATE_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["shadowing_candidate"]
SHADOWING_CANDIDATE_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["shadowing_candidate"]
SHADOWING_CANDIDATE_MODEL_TEMPLATE_KEY = "shadowing_candidate"
SHADOWING_CANDIDATE_EXPORT_FILENAME = "wk_shadowing_candidates.apkg"

# Same field *names* as other immersion types; distinct *order* avoids Anki forks.
SHADOWING_FIELD_NAMES: Tuple[str, ...] = (
    "DuplicateKey",
    "Expression",
    "Reading",
    "Translation",
    "Furigana",
    "PitchAccents",
    "PitchPositions",
    "PitchGraphs",
    "Glossary",
    "Synonyms",
    "Antonyms",
    "Image",
    "ClozeSentence",
    "WkSubjectId",
    "PrerequisiteIds",
    "WkMeaning",
    "HintGlossary",
    "HintStage",
    "ShowEnglish",
    "ShowKana",
    "ShowJjBack",
    "SentenceKana",
    "DictLinksJa",
    "DictLinksEn",
    "Sentence",
    "SentenceFurigana",
    "SentenceAudio",
    "SentenceAudioEasy",
    "Audio",
    "ReadingAudio",
    "VoicevoxAudio",
    "VoicevoxSpeakerId",
    "UserNotes",
    "SourceUrl",
    "SourceTitle",
    "Meta",
)

SHADOWING_CANDIDATE_FIELD_NAMES: Tuple[str, ...] = (
    "DuplicateKey",
    "Expression",
    "Reading",
    "Translation",
    "ClozeSentence",
    "Sentence",
    "SentenceAudio",
    "Audio",
    "ReadingAudio",
    "Glossary",
    "UserNotes",
    "SourceUrl",
    "SourceTitle",
    "Meta",
)

_SAFE_MEDIA_RE = re.compile(r"[^A-Za-z0-9._-]+")

# AnkiMobile only plays collection media via [sound:], not HTML5 <audio>.
# Manual Target/Reading/Normal fields store [sound:…]; immersion decks use a
# dedicated options group with autoplay off; JS clicks .autoplay-audio on reveal.
_MANUAL_TTS_BIND_SCRIPT = """
<script>
(function () {
  function playAutoplayAudio() {
    var node = document.querySelector(
      ".autoplay-audio .replay-button, .autoplay-audio .replaybutton, .autoplay-audio a.soundLink"
    );
    if (node) node.click();
  }
  if (typeof onShownHook !== "undefined") {
    onShownHook.push(playAutoplayAudio);
  } else {
    setTimeout(playAutoplayAudio, 50);
  }
})();
</script>
"""


SHADOWING_FRONT = """
<div class="mining-card">
  {{#ClozeSentence}}<div class="cloze-sentence jp">{{ClozeSentence}}</div>{{/ClozeSentence}}
  {{^ClozeSentence}}{{#Sentence}}<div class="cloze-sentence jp">{{Sentence}}</div>{{/Sentence}}{{/ClozeSentence}}
  <div class="hint-block">
    {{#WkMeaning}}<div class="hint-meaning">{{WkMeaning}}</div>{{/WkMeaning}}
    {{^WkMeaning}}
      {{#HintGlossary}}<div class="hint-meaning">{{HintGlossary}}</div>{{/HintGlossary}}
      {{^HintGlossary}}{{{DictLinksEn}}}{{/HintGlossary}}
    {{/WkMeaning}}
  </div>
  <div class="type-prompt">{{type:Reading}}</div>
</div>
"""

SHADOWING_BACK = """
{{FrontSide}}
<hr>
<div class="answer-word jp">
  {{#Furigana}}{{furigana:Furigana}}{{/Furigana}}
  {{^Furigana}}{{Expression}}{{#Reading}} <span class="reading answer">{{Reading}}</span>{{/Reading}}{{/Furigana}}
</div>
{{#WkMeaning}}<div class="meaning answer">{{WkMeaning}}</div>{{/WkMeaning}}
{{#PitchAccents}}
<div class="pitch"><b>Pitch:</b> {{PitchAccents}}{{#PitchPositions}} <span class="pitch-pos">({{PitchPositions}})</span>{{/PitchPositions}}</div>
{{/PitchAccents}}
{{#PitchGraphs}}<div class="pitch-graphs">{{PitchGraphs}}</div>{{/PitchGraphs}}
{{#Audio}}
<div class="audio-row surface-audio-row">
  <div class="audio-label meta">Target</div>
  <div class="manual-tts-sound">{{Audio}}</div>
</div>
{{/Audio}}
{{#ReadingAudio}}
<div class="audio-row surface-audio-row">
  <div class="audio-label meta">Reading</div>
  <div class="manual-tts-sound">{{ReadingAudio}}</div>
</div>
{{/ReadingAudio}}
{{#Sentence}}
<div class="context">
  {{#SentenceAudio}}
  <div class="sentence-audio sentence-tts-file autoplay-audio">{{SentenceAudio}}</div>
  {{/SentenceAudio}}
  {{#SentenceFurigana}}<div class="jp context-furigana">{{furigana:SentenceFurigana}}</div>{{/SentenceFurigana}}
  {{^SentenceFurigana}}<div class="jp">{{Sentence}}</div>{{/SentenceFurigana}}
  {{#Translation}}<div class="sentence-en">{{Translation}}</div>{{/Translation}}
</div>
{{/Sentence}}
{{#Glossary}}
<div class="word-def word-def-glossary">
  <div class="meta word-def-label">Notes</div>
  <div class="word-def-body">{{Glossary}}</div>
</div>
{{/Glossary}}
{{#UserNotes}}
<div class="user-notes">
  <div class="meta user-notes-label">Your notes</div>
  <div class="user-notes-body">{{UserNotes}}</div>
</div>
{{/UserNotes}}
{{#SourceTitle}}<div class="source">{{SourceTitle}}</div>{{/SourceTitle}}
{{#SourceUrl}}<div class="source"><a href="{{SourceUrl}}">{{SourceUrl}}</a></div>{{/SourceUrl}}
<div class="meta">{{Meta}}</div>
""" + _MANUAL_TTS_BIND_SCRIPT + """
"""

SHADOWING_CANDIDATE_FRONT = """
<div class="mining-card">
  {{#ClozeSentence}}<div class="cloze-sentence jp">{{ClozeSentence}}</div>{{/ClozeSentence}}
  {{^ClozeSentence}}{{#Sentence}}<div class="cloze-sentence jp">{{Sentence}}</div>{{/Sentence}}{{/ClozeSentence}}
  <div class="hint-block">
    {{#WkMeaning}}<div class="hint-meaning">{{WkMeaning}}</div>{{/WkMeaning}}
    {{^WkMeaning}}
      {{#HintGlossary}}<div class="hint-meaning">{{HintGlossary}}</div>{{/HintGlossary}}
      {{^HintGlossary}}
        {{#Translation}}<div class="hint-meaning">{{Translation}}</div>{{/Translation}}
      {{/HintGlossary}}
    {{/WkMeaning}}
  </div>
  <div class="type-prompt">{{type:Reading}}</div>
</div>
"""

SHADOWING_CANDIDATE_BACK = """
{{FrontSide}}
<hr>
<div class="answer-word jp">
  {{Expression}}{{#Reading}} <span class="reading answer">{{Reading}}</span>{{/Reading}}
</div>
{{#Audio}}
<div class="audio-row surface-audio-row">
  <div class="audio-label meta">Target</div>
  <div class="manual-tts-sound">{{Audio}}</div>
</div>
{{/Audio}}
{{#ReadingAudio}}
<div class="audio-row surface-audio-row">
  <div class="audio-label meta">Reading</div>
  <div class="manual-tts-sound">{{ReadingAudio}}</div>
</div>
{{/ReadingAudio}}
{{#Sentence}}
<div class="context">
  {{#SentenceAudio}}
  <div class="sentence-audio sentence-tts-file autoplay-audio">{{SentenceAudio}}</div>
  {{/SentenceAudio}}
  <div class="jp">{{Sentence}}</div>
  {{#Translation}}<div class="sentence-en">{{Translation}}</div>{{/Translation}}
</div>
{{/Sentence}}
{{#Glossary}}
<div class="word-def word-def-glossary">
  <div class="meta word-def-label">Notes</div>
  <div class="word-def-body">{{Glossary}}</div>
</div>
{{/Glossary}}
{{#SourceTitle}}<div class="source">{{SourceTitle}}</div>{{/SourceTitle}}
<div class="meta">{{Meta}}</div>
""" + _MANUAL_TTS_BIND_SCRIPT + """
"""

SHADOWING_CSS = """
.mining-card { max-width: 760px; margin: 0 auto; }
.cloze-sentence { font-size: 34px; line-height: 1.55; margin: 16px 0; }
.cloze-blank {
  display: inline-block;
  min-width: 3em;
  border-bottom: 3px solid #fbc02d;
  color: #fbc02d;
  letter-spacing: 0.08em;
  padding: 0 4px;
}
.cloze-target {
  color: #4fc3f7;
  border-bottom: 3px solid #4fc3f7;
  padding: 0 2px;
  font-weight: 600;
}
.cloze-inflection {
  color: #ce93d8;
  border-bottom: 2px dashed #ce93d8;
  padding: 0 1px;
  font-weight: 500;
}
.hint-block { margin: 12px auto; max-width: 640px; font-size: 20px; line-height: 1.5; }
.hint-meaning { color: #c8e6c9; margin-bottom: 6px; }
.pitch { margin: 8px auto; max-width: 640px; font-size: 18px; color: #ffe0b2; }
.pitch-pos { color: #b0bec5; font-size: 15px; }
.pitch-graphs { margin: 8px auto; max-width: 760px; }
.pitch-graph { display: inline-flex; gap: 2px; margin-right: 10px; vertical-align: middle; }
.pitch-mora { display: inline-block; min-width: 1.1em; text-align: center; font-size: 20px; line-height: 1.2; padding: 2px 3px; border-radius: 3px; }
.pitch-mora.h { background: #37474f; color: #fff; border-bottom: 3px solid #ffcc80; }
.pitch-mora.l { background: transparent; color: #cfd8dc; border-bottom: 3px solid #546e7a; }
.pitch-mora.drop { box-shadow: inset 0 -2px 0 #ef5350; }
.type-prompt { margin: 18px auto; max-width: 520px; font-size: 28px; }
.answer-word { font-size: 36px; margin: 12px auto; line-height: 1.8; }
.answer-word ruby rt { font-size: 14px; color: #d8d8d8; }
.context { font-size: 28px; margin: 12px auto; max-width: 760px; line-height: 1.6; }
.context-furigana { line-height: 2.1; }
.context-furigana ruby rt { font-size: 14px; color: #d8d8d8; }
.sentence-audio { margin: 8px 0 12px; }
.audio-row { margin: 6px 0; }
.audio-label { font-size: 13px; margin-bottom: 2px; opacity: 0.85; }
.surface-audio-row { margin: 10px auto; max-width: 520px; }
.manual-tts-sound { margin: 2px 0 8px; }
.manual-tts-sound .replay-button,
.manual-tts-sound .replaybutton,
.manual-tts-sound .soundLink {
  vertical-align: middle;
}
.sentence-en { font-size: 18px; color: #c8e6c9; margin-top: 10px; }
.word-def {
  text-align: left;
  margin: 12px auto;
  max-width: 760px;
  padding: 10px 12px;
  border-left: 3px solid #5a7a5a;
  background: rgba(90, 122, 90, 0.08);
  font-size: 18px;
  line-height: 1.55;
}
.user-notes { text-align: left; margin: 12px auto; max-width: 760px; }
.source { font-size: 14px; color: #aaa; margin-top: 8px; }
"""


@dataclass(frozen=True)
class SelectedVocabulary:
    """Authoritative human selection from Glossbook mining export."""

    surface: str
    start: int
    end: int
    expression: str
    reading: str
    english: str = ""
    pos: str = ""


@dataclass(frozen=True)
class ShadowingSource:
    source_id: str
    title: str
    url: str
    video_id: str
    channel: str


@dataclass(frozen=True)
class ShadowingSentence:
    sentence_id: str
    japanese: str
    reading: str
    english: str
    transcript_status: str
    tags: Tuple[str, ...]
    notes: str
    clip_path: str
    start_ms: int
    end_ms: int
    # When non-empty, Anki builds cards only from these selections (no auto-match).
    selected_vocabulary: Tuple[SelectedVocabulary, ...] = ()


@dataclass(frozen=True)
class ShadowingProject:
    root: Path
    source: ShadowingSource
    sentences: Tuple[ShadowingSentence, ...]
    # True when loaded from a Glossbook japanese-shadowing-mining-package.
    curated: bool = False


@dataclass(frozen=True)
class ShadowingBuildStats:
    sentences: int
    wk_matches: int
    wk_notes: int
    candidate_notes: int
    missing_clips: int
    skipped_auto_caption: int
    curated_selections: int = 0


MINING_PACKAGE_FORMAT = "japanese-shadowing-mining-package"
MINING_PACKAGE_VERSION = 1


def validate_selected_vocabulary(
    japanese: str,
    selection: SelectedVocabulary,
    *,
    sentence_id: str = "",
) -> None:
    """Raise ValueError when the selection span does not match the sentence."""
    if selection.end <= selection.start:
        raise ValueError(
            f"Invalid selection span for {sentence_id or 'sentence'}: "
            f"{selection.start}:{selection.end}"
        )
    if japanese[selection.start : selection.end] != selection.surface:
        raise ValueError(
            f"Selection surface {selection.surface!r} does not match "
            f"{japanese[selection.start:selection.end]!r} in "
            f"{sentence_id or 'sentence'} at {selection.start}:{selection.end}"
        )
    if not selection.expression.strip():
        raise ValueError(
            f"Selection in {sentence_id or 'sentence'} is missing an expression"
        )


def parse_selected_vocabulary(
    japanese: str,
    rows: object,
    *,
    sentence_id: str = "",
) -> Tuple[SelectedVocabulary, ...]:
    if not rows:
        return ()
    if not isinstance(rows, list):
        raise ValueError(f"selectedVocabulary must be an array on {sentence_id}")
    out: List[SelectedVocabulary] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        selection = SelectedVocabulary(
            surface=str(row.get("surface") or "").strip(),
            start=int(row.get("start") or 0),
            end=int(row.get("end") or 0),
            expression=str(row.get("expression") or "").strip(),
            reading=str(row.get("reading") or "").strip(),
            english=str(row.get("english") or "").strip(),
            pos=str(row.get("pos") or "").strip(),
        )
        validate_selected_vocabulary(japanese, selection, sentence_id=sentence_id)
        out.append(selection)
    return tuple(out)


def make_shadowing_model() -> WkModel:
    return WkModel(
        SHADOWING_MODEL_ID,
        SHADOWING_NOTE_TYPE_NAME,
        template_key=SHADOWING_MODEL_TEMPLATE_KEY,
        fields=[{"name": name} for name in SHADOWING_FIELD_NAMES],
        templates=[
            {
                "name": "Sentence cloze → word",
                "qfmt": SHADOWING_FRONT,
                "afmt": SHADOWING_BACK,
            },
        ],
        css=versioned_css(COMMON_CSS + SHADOWING_CSS, SHADOWING_MODEL_TEMPLATE_KEY),
    )


def make_shadowing_candidate_model() -> WkModel:
    return WkModel(
        SHADOWING_CANDIDATE_MODEL_ID,
        SHADOWING_CANDIDATE_NOTE_TYPE_NAME,
        template_key=SHADOWING_CANDIDATE_MODEL_TEMPLATE_KEY,
        fields=[{"name": name} for name in SHADOWING_CANDIDATE_FIELD_NAMES],
        templates=[
            {
                "name": "Sentence cloze → candidate",
                "qfmt": SHADOWING_CANDIDATE_FRONT,
                "afmt": SHADOWING_CANDIDATE_BACK,
            },
        ],
        css=versioned_css(COMMON_CSS + SHADOWING_CSS, SHADOWING_CANDIDATE_MODEL_TEMPLATE_KEY),
    )


def _safe_media_stem(*parts: object) -> str:
    raw = "_".join(str(part) for part in parts if str(part))
    cleaned = _SAFE_MEDIA_RE.sub("_", raw).strip("._")
    return cleaned[:80] or "clip"


def native_shadowing_media_stem_from_duplicate_key(duplicate_key: str) -> str:
    """Return media stem ``wk_shadowing_{source}_{sentence}`` from DuplicateKey."""
    parts = [p.strip() for p in (duplicate_key or "").split("|") if p.strip()]
    if len(parts) < 2:
        return ""
    return f"wk_shadowing_{_safe_media_stem(parts[0], parts[1])}"


def find_native_shadowing_media(
    media_dir: Path,
    *,
    duplicate_key: str = "",
    stem: str = "",
) -> Optional[Path]:
    """Locate an existing ``wk_shadowing_*.{m4a,mp3,wav,ogg,opus}`` in media_dir."""
    resolved_stem = (stem or native_shadowing_media_stem_from_duplicate_key(duplicate_key)).strip()
    if not resolved_stem:
        return None
    for ext in (".m4a", ".mp3", ".wav", ".ogg", ".opus"):
        candidate = media_dir / f"{resolved_stem}{ext}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    matches = sorted(media_dir.glob(f"{resolved_stem}.*"))
    for path in matches:
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def load_shadowing_project(project_dir: Path) -> ShadowingProject:
    root = project_dir.expanduser().resolve()
    source_path = root / "source.json"
    sentences_path = root / "sentences.json"
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing source.json in {root}")
    if not sentences_path.is_file():
        raise FileNotFoundError(f"Missing sentences.json in {root}")

    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    sentences_payload = json.loads(sentences_path.read_text(encoding="utf-8"))
    if not isinstance(source_payload, dict):
        raise ValueError("source.json must be an object")
    if not isinstance(sentences_payload, list) or not sentences_payload:
        raise ValueError("sentences.json must be a non-empty array")

    source = ShadowingSource(
        source_id=str(source_payload.get("id") or "").strip()
        or f"source-{source_payload.get('videoId') or root.name}",
        title=str(source_payload.get("title") or root.name).strip(),
        url=str(source_payload.get("url") or source_payload.get("webpageUrl") or "").strip(),
        video_id=str(source_payload.get("videoId") or "").strip(),
        channel=str(source_payload.get("channel") or "").strip(),
    )

    sentences: List[ShadowingSentence] = []
    seen_ids: Set[str] = set()
    for row in sentences_payload:
        if not isinstance(row, dict):
            continue
        sentence_id = str(row.get("id") or "").strip()
        japanese = str(row.get("japanese") or "").strip()
        if not sentence_id or not japanese:
            continue
        if sentence_id in seen_ids:
            raise ValueError(f"Duplicate sentence id: {sentence_id}")
        seen_ids.add(sentence_id)
        clip_path = str(row.get("clipPath") or "").strip()
        tags = tuple(
            str(tag).strip()
            for tag in (row.get("tags") or [])
            if str(tag).strip()
        )
        sentences.append(
            ShadowingSentence(
                sentence_id=sentence_id,
                japanese=japanese,
                reading=str(row.get("reading") or "").strip(),
                english=str(row.get("english") or "").strip(),
                transcript_status=str(row.get("transcriptStatus") or "unverified").strip(),
                tags=tags,
                notes=str(row.get("notes") or "").strip(),
                clip_path=clip_path,
                start_ms=int(row.get("startMs") or 0),
                end_ms=int(row.get("endMs") or 0),
                selected_vocabulary=parse_selected_vocabulary(
                    japanese,
                    row.get("selectedVocabulary"),
                    sentence_id=sentence_id,
                ),
            )
        )
    if not sentences:
        raise ValueError(f"No usable sentences in {sentences_path}")
    curated = any(sentence.selected_vocabulary for sentence in sentences)
    return ShadowingProject(
        root=root,
        source=source,
        sentences=tuple(sentences),
        curated=curated,
    )


def load_mining_package(package_path: Path) -> ShadowingProject:
    """Load a Glossbook ``japanese-shadowing-mining-package`` ZIP.

    Extracts into a temp directory under the system temp folder and returns a
    curated ShadowingProject whose clip paths point at the extracted audio.
    """
    path = package_path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Mining package not found: {path}")

    staging = Path(tempfile.mkdtemp(prefix="wk_mining_pkg_"))
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            normalized = name.replace("\\", "/")
            if normalized.startswith("/") or ".." in normalized.split("/"):
                raise ValueError(f"Unsafe path in mining package: {name}")
        required = ("manifest.json", "source.json", "sentences.json")
        for name in required:
            if name not in zf.namelist():
                raise ValueError(f"Mining package missing {name}")
        zf.extractall(staging)

    manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != MINING_PACKAGE_FORMAT
        or int(manifest.get("version") or 0) != MINING_PACKAGE_VERSION
    ):
        raise ValueError(
            "Not a supported japanese-shadowing-mining-package v1 file"
        )

    source_payload = json.loads((staging / "source.json").read_text(encoding="utf-8"))
    sentences_payload = json.loads(
        (staging / "sentences.json").read_text(encoding="utf-8")
    )
    if not isinstance(source_payload, dict):
        raise ValueError("source.json must be an object")
    if not isinstance(sentences_payload, list) or not sentences_payload:
        raise ValueError("sentences.json must be a non-empty array")

    source = ShadowingSource(
        source_id=str(source_payload.get("id") or "").strip() or f"source-{path.stem}",
        title=str(source_payload.get("title") or path.stem).strip(),
        url=str(source_payload.get("url") or "").strip(),
        video_id=str(source_payload.get("videoId") or "").strip(),
        channel=str(source_payload.get("channel") or "").strip(),
    )

    sentences: List[ShadowingSentence] = []
    seen_ids: Set[str] = set()
    for row in sentences_payload:
        if not isinstance(row, dict):
            continue
        sentence_id = str(row.get("id") or "").strip()
        japanese = str(row.get("japanese") or "").strip()
        if not sentence_id or not japanese:
            continue
        if sentence_id in seen_ids:
            raise ValueError(f"Duplicate sentence id: {sentence_id}")
        seen_ids.add(sentence_id)
        audio = row.get("audio") or {}
        if not isinstance(audio, dict):
            raise ValueError(f"Sentence {sentence_id} is missing audio metadata")
        audio_rel = str(audio.get("path") or "").strip()
        if not audio_rel:
            raise ValueError(f"Sentence {sentence_id} is missing audio.path")
        audio_path = (staging / audio_rel).resolve()
        try:
            audio_path.relative_to(staging.resolve())
        except ValueError as exc:
            raise ValueError(f"Unsafe audio path: {audio_rel}") from exc
        if not audio_path.is_file():
            raise FileNotFoundError(
                f"Mining package missing audio for {sentence_id}: {audio_rel}"
            )
        selections = parse_selected_vocabulary(
            japanese,
            row.get("selectedVocabulary"),
            sentence_id=sentence_id,
        )
        tags = tuple(
            str(tag).strip()
            for tag in (row.get("tags") or [])
            if str(tag).strip()
        )
        sentences.append(
            ShadowingSentence(
                sentence_id=sentence_id,
                japanese=japanese,
                reading=str(row.get("reading") or "").strip(),
                english=str(row.get("english") or "").strip(),
                transcript_status=str(
                    row.get("transcriptStatus") or "verified"
                ).strip(),
                tags=tags,
                notes=str(row.get("notes") or "").strip(),
                clip_path=audio_rel,
                start_ms=int(row.get("startMs") or 0),
                end_ms=int(row.get("endMs") or 0),
                selected_vocabulary=selections,
            )
        )
    if not sentences:
        raise ValueError("Mining package contains no usable sentences")
    return ShadowingProject(
        root=staging,
        source=source,
        sentences=tuple(sentences),
        curated=True,
    )


def load_shadowing_input(path: Path) -> ShadowingProject:
    """Load either a legacy project directory or a Glossbook mining ZIP."""
    target = path.expanduser().resolve()
    if target.is_file() and target.suffix.lower() == ".zip":
        return load_mining_package(target)
    if target.is_dir():
        return load_shadowing_project(target)
    raise FileNotFoundError(f"Expected a project directory or .zip: {target}")


def resolve_clip_path(project: ShadowingProject, sentence: ShadowingSentence) -> Optional[Path]:
    if not sentence.clip_path:
        return None
    clip = Path(sentence.clip_path)
    if clip.is_absolute():
        return clip if clip.is_file() else None
    root = project.root.expanduser().resolve()
    candidate = (root / clip).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def stage_clip_media(
    project: ShadowingProject,
    sentence: ShadowingSentence,
    media_dir: Path,
) -> Tuple[str, Optional[Path]]:
    """Copy clip to media_dir; return (anki_filename, absolute_path or None)."""
    source_clip = resolve_clip_path(project, sentence)
    if source_clip is None:
        return "", None
    suffix = source_clip.suffix.lower() or ".m4a"
    filename = (
        f"wk_shadowing_{_safe_media_stem(project.source.source_id, sentence.sentence_id)}"
        f"{suffix}"
    )
    media_dir.mkdir(parents=True, exist_ok=True)
    dest = media_dir / filename
    if not dest.exists() or dest.stat().st_mtime < source_clip.stat().st_mtime:
        shutil.copy2(source_clip, dest)
    return filename, dest


def shadowing_note_fields(
    *,
    source: ShadowingSource,
    sentence: ShadowingSentence,
    expression: str,
    reading: str,
    wk_entry: Optional[dict],
    audio_filename: str,
    transcript_tag: str,
    surface: str = "",
    pitch_index: Optional[dict] = None,
) -> List[str]:
    cloze_html, plain_sentence = build_satori_cloze_sentence(
        sentence.japanese, expression, reading, surface=surface
    )
    enrichment = enrich_mining_note_fields(
        expression=expression,
        reading=reading,
        sentence=plain_sentence or sentence.japanese,
        sentence_furigana="",
        glossary=transcript_tag,
        translation=sentence.english,
        wk_entry=wk_entry,
    )
    wk_meaning = enrichment.wk_meaning or ""
    duplicate_key = (
        f"{source.source_id}|{sentence.sentence_id}|{enrichment.expression}|"
        f"{(wk_entry or {}).get('id', '')}"
    )
    meta = (
        f"Shadowing · {source.title} · {sentence.transcript_status} · "
        f"template {SHADOWING_TEMPLATE_VERSION}"
    )
    sound = f"[sound:{audio_filename}]" if audio_filename else ""
    pitch_fields = pitch_field_values(
        enrichment.expression,
        enrichment.reading or reading,
        pitch_index,
    )
    raw_html_fields = {
        "ClozeSentence",
        "DictLinksJa",
        "DictLinksEn",
        "SentenceFurigana",
        "Furigana",
        "PitchGraphs",
    }
    values = {
        "DuplicateKey": duplicate_key,
        "Expression": enrichment.expression,
        "Reading": enrichment.reading or reading,
        "Translation": sentence.english,
        "Furigana": "",
        "PitchAccents": pitch_fields["PitchAccents"],
        "PitchPositions": pitch_fields["PitchPositions"],
        "PitchGraphs": pitch_fields["PitchGraphs"],
        "Glossary": transcript_tag,
        "Synonyms": "",
        "Antonyms": "",
        "Image": "",
        "ClozeSentence": cloze_html or enrichment.cloze_sentence,
        "WkSubjectId": enrichment.wk_subject_id,
        "PrerequisiteIds": enrichment.prerequisite_ids,
        "WkMeaning": wk_meaning,
        "HintGlossary": enrichment.hint_glossary,
        "HintStage": "0",
        "ShowEnglish": "1",
        "ShowKana": "",
        "ShowJjBack": "",
        "SentenceKana": enrichment.sentence_kana,
        "DictLinksJa": enrichment.dict_links_ja,
        "DictLinksEn": enrichment.dict_links_en,
        "Sentence": enrichment.sentence,
        "SentenceFurigana": "",
        "SentenceAudio": sound,
        "SentenceAudioEasy": "",
        "Audio": "",
        "ReadingAudio": "",
        "VoicevoxAudio": "",
        "VoicevoxSpeakerId": "",
        "UserNotes": sentence.notes,
        "SourceUrl": source.url,
        "SourceTitle": source.title,
        "Meta": meta,
    }
    fields: List[str] = []
    for name in SHADOWING_FIELD_NAMES:
        value = values[name]
        if name in raw_html_fields or name == "SentenceAudio":
            fields.append(value)
        else:
            fields.append(html.escape(value))
    return fields


def shadowing_candidate_note_fields(
    *,
    source: ShadowingSource,
    sentence: ShadowingSentence,
    candidate: CandidateLemma,
    audio_filename: str,
) -> List[str]:
    surface = name_surface_for_shogo(
        sentence.japanese, candidate.surface or candidate.lemma
    )
    expression = surface if surface.startswith("し吾") else candidate.lemma
    reading = reading_for_surface_in_sentence(
        sentence.japanese, surface
    ) or reading_for_candidate_lemma(candidate.lemma, candidate.reading)
    cloze_html, plain_sentence = build_satori_cloze_sentence(
        sentence.japanese,
        expression,
        reading,
        surface=surface,
    )
    sound = f"[sound:{audio_filename}]" if audio_filename else ""
    duplicate_key = f"{source.source_id}|{sentence.sentence_id}|{expression}"
    meta = (
        f"Shadowing candidate · {source.title} · {candidate.pos or 'content'} · "
        f"template {SHADOWING_CANDIDATE_TEMPLATE_VERSION}"
    )
    values = {
        "DuplicateKey": duplicate_key,
        "Expression": expression,
        "Reading": reading,
        "Translation": sentence.english,
        "ClozeSentence": cloze_html or html.escape(plain_sentence or sentence.japanese),
        "Sentence": plain_sentence or sentence.japanese,
        "SentenceAudio": sound,
        "Audio": "",
        "ReadingAudio": "",
        "Glossary": f"POS: {candidate.pos}" if candidate.pos else "non-WK candidate",
        "UserNotes": sentence.notes,
        "SourceUrl": source.url,
        "SourceTitle": source.title,
        "Meta": meta,
    }
    fields: List[str] = []
    for name in SHADOWING_CANDIDATE_FIELD_NAMES:
        value = values[name]
        if name in {"ClozeSentence", "SentenceAudio", "Audio", "ReadingAudio"}:
            fields.append(value)
        else:
            fields.append(html.escape(value))
    return fields


def _trust_tags(sentence: ShadowingSentence) -> List[str]:
    tags = ["immersion", SHADOWING_TAG, f"shadowing-{sentence.transcript_status}"]
    if sentence.transcript_status == "auto-caption":
        tags.append("shadowing-auto-caption")
    for tag in sentence.tags:
        safe = re.sub(r"[^\w\-]+", "-", tag, flags=re.UNICODE).strip("-")
        if safe:
            tags.append(f"shadowing-src-{safe[:40]}")
    return tags


def build_shadowing_decks(
    project: ShadowingProject,
    output_dir: Path,
    *,
    wk_index: Optional[dict] = None,
    include_auto_caption: bool = True,
    pitch_index: Optional[dict] = None,
) -> Tuple[Path, Path, ShadowingBuildStats]:
    """Build WK cloze + candidate APKGs. Returns (wk_path, candidate_path, stats)."""
    index = wk_index or {}
    media_dir = output_dir / "media" / "shadowing"
    media_dir.mkdir(parents=True, exist_ok=True)

    wk_deck = genanki.Deck(SHADOWING_DECK_ID, SHADOWING_DECK_NAME)
    wk_model = make_shadowing_model()
    cand_deck = genanki.Deck(SHADOWING_CANDIDATE_DECK_ID, SHADOWING_CANDIDATE_DECK_NAME)
    cand_model = make_shadowing_candidate_model()

    media_paths: List[str] = []
    seen_media: Set[str] = set()
    wk_notes = 0
    wk_matches = 0
    candidate_notes = 0
    missing_clips = 0
    skipped_auto = 0
    curated_selections = 0
    seen_candidate_lemmas: Set[str] = set()
    use_curated = project.curated or any(
        sentence.selected_vocabulary for sentence in project.sentences
    )

    for sentence in project.sentences:
        if not include_auto_caption and sentence.transcript_status == "auto-caption":
            skipped_auto += 1
            continue

        audio_name, media_path = stage_clip_media(project, sentence, media_dir)
        if media_path is None:
            missing_clips += 1
        elif str(media_path) not in seen_media:
            seen_media.add(str(media_path))
            media_paths.append(str(media_path))

        if use_curated:
            if not sentence.selected_vocabulary:
                continue
            curated_selections += len(sentence.selected_vocabulary)
            for selection in sentence.selected_vocabulary:
                validate_selected_vocabulary(
                    sentence.japanese,
                    selection,
                    sentence_id=sentence.sentence_id,
                )
                wk_entry = lookup_wk_vocab(
                    selection.expression, selection.reading, index
                )
                if wk_entry:
                    if should_skip_copula_cloze(
                        selection.expression,
                        selection.reading or str(wk_entry.get("reading") or ""),
                        sentence.japanese,
                        surface=selection.surface,
                    ):
                        continue
                    wk_matches += 1
                    guid = stable_guid(
                        SHADOWING_KIND,
                        project.source.source_id,
                        sentence.sentence_id,
                        wk_entry["id"],
                    )
                    note = genanki.Note(
                        model=wk_model,
                        fields=shadowing_note_fields(
                            source=project.source,
                            sentence=sentence,
                            expression=selection.expression,
                            reading=selection.reading
                            or str(wk_entry.get("reading") or ""),
                            wk_entry=wk_entry,
                            audio_filename=audio_name,
                            transcript_tag=sentence.transcript_status,
                            surface=selection.surface,
                            pitch_index=pitch_index,
                        ),
                        tags=_trust_tags(sentence) + ["shadowing-curated"],
                        guid=guid,
                    )
                    wk_deck.add_note(note)
                    wk_notes += 1
                    continue

                lemma_key = selection.expression
                if lemma_key in seen_candidate_lemmas:
                    continue
                seen_candidate_lemmas.add(lemma_key)
                candidate = CandidateLemma(
                    lemma=selection.expression,
                    surface=selection.surface,
                    reading=selection.reading,
                    pos=selection.pos,
                    start=selection.start,
                    end=selection.end,
                )
                guid = stable_guid(
                    SHADOWING_CANDIDATE_KIND,
                    project.source.source_id,
                    sentence.sentence_id,
                    candidate.lemma,
                )
                note = genanki.Note(
                    model=cand_model,
                    fields=shadowing_candidate_note_fields(
                        source=project.source,
                        sentence=sentence,
                        candidate=candidate,
                        audio_filename=audio_name,
                    ),
                    tags=[
                        "immersion",
                        SHADOWING_CANDIDATE_TAG,
                        f"shadowing-{sentence.transcript_status}",
                        "shadowing-curated",
                    ],
                    guid=guid,
                )
                cand_deck.add_note(note)
                candidate_notes += 1
            continue

        # Legacy automatic matching for unreviewed project directories.
        matches = match_wk_vocab_in_sentence(
            sentence.japanese,
            index,
            sentence_reading=sentence.reading,
        )
        wk_matches += len(matches)
        matched_ids = {int(match.wk_entry["id"]) for match in matches}
        matched_expr = {match.expression for match in matches}

        for match in matches:
            if should_skip_copula_cloze(
                match.expression,
                match.reading,
                sentence.japanese,
                surface=match.surface,
            ):
                continue
            guid = stable_guid(
                SHADOWING_KIND,
                project.source.source_id,
                sentence.sentence_id,
                match.wk_entry["id"],
            )
            note = genanki.Note(
                model=wk_model,
                fields=shadowing_note_fields(
                    source=project.source,
                    sentence=sentence,
                    expression=match.expression,
                    reading=match.reading,
                    wk_entry=match.wk_entry,
                    audio_filename=audio_name,
                    transcript_tag=sentence.transcript_status,
                    surface=match.surface,
                    pitch_index=pitch_index,
                ),
                tags=_trust_tags(sentence),
                guid=guid,
            )
            wk_deck.add_note(note)
            wk_notes += 1

        candidates = candidate_lemmas_in_sentence(
            sentence.japanese,
            index,
            wk_matched_ids=matched_ids,
            wk_matched_expressions=matched_expr,
            wk_matched_spans={(match.start, match.end) for match in matches},
        )
        for candidate in candidates:
            if candidate.lemma in seen_candidate_lemmas:
                continue
            # Extra guard: type-in answers must not end in っ (mid-conjugation cut).
            reading = reading_for_surface_in_sentence(
                sentence.japanese, candidate.surface or candidate.lemma
            ) or candidate.reading
            if candidate_reading_looks_truncated(reading):
                continue
            seen_candidate_lemmas.add(candidate.lemma)
            guid = stable_guid(
                SHADOWING_CANDIDATE_KIND,
                project.source.source_id,
                sentence.sentence_id,
                candidate.lemma,
            )
            note = genanki.Note(
                model=cand_model,
                fields=shadowing_candidate_note_fields(
                    source=project.source,
                    sentence=sentence,
                    candidate=candidate,
                    audio_filename=audio_name,
                ),
                tags=[
                    "immersion",
                    SHADOWING_CANDIDATE_TAG,
                    f"shadowing-{sentence.transcript_status}",
                ],
                guid=guid,
            )
            cand_deck.add_note(note)
            candidate_notes += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    wk_path = output_dir / SHADOWING_EXPORT_FILENAME
    cand_path = output_dir / SHADOWING_CANDIDATE_EXPORT_FILENAME
    write_apkg(wk_deck, wk_path, media_files=media_paths or None)
    write_apkg(cand_deck, cand_path, media_files=media_paths or None)

    stats = ShadowingBuildStats(
        sentences=len(project.sentences),
        wk_matches=wk_matches,
        wk_notes=wk_notes,
        candidate_notes=candidate_notes,
        missing_clips=missing_clips,
        skipped_auto_caption=skipped_auto,
        curated_selections=curated_selections,
    )
    return wk_path, cand_path, stats


def load_default_wk_index(path: Optional[Path] = None) -> dict:
    index_path = path or (REPO_ROOT / "out" / "wk_mining_vocab_index.json")
    if not index_path.is_file():
        return {"by_expression": {}, "by_reading": {}}
    return load_mining_vocab_index(index_path)
