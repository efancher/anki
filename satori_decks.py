"""
satori_decks.py

Immersion · Satori — sentence cloze cards from a Satori Reader CSV export.

Front: cloze mark on the full surface span in Context1 + type Reading (dictionary kana).
Back: full sentence, reading, word English, sentence translation (always shown).
"""

from __future__ import annotations

import csv
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import genanki

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

from mining_logic import (  # noqa: E402
    CLOZE_BLANK_DISPLAY,
    blank_targets_for_expression,
    enrich_mining_note_fields,
    plain_mining_text,
)

# Kanji ranges (CJK unified + extension A + compatibility ideographs).
_KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ffー]")
_HIRAGANA_RE = re.compile(r"[\u3040-\u309fー]")
# Trim these after a dictionary-form surface (okurigana matched).
_TRAILING_PARTICLES: Tuple[str, ...] = (
    "から",
    "まで",
    "より",
    "ので",
    "のに",
    "では",
    "にも",
    "のは",
    "への",
    "とは",
    "は",
    "が",
    "を",
    "に",
    "で",
    "へ",
    "と",
    "も",
    "や",
    "か",
    "の",
    "ね",
    "よ",
    "な",
    "わ",
    "さ",
    "ぞ",
    "ぜ",
)
# After a conjugated surface, still drop clear particles — but never て/で,
# which are also te-form endings (喜んで, 見て).
_CONJUGATED_TRAILING_PARTICLES: Tuple[str, ...] = tuple(
    particle for particle in _TRAILING_PARTICLES if particle not in {"て", "で", "では"}
)

# Not conjugation — separate morphology/cards (達, さん, …).
_NON_INFLECTION_SUFFIXES: Tuple[str, ...] = (
    "たち",
    "達",
    "さん",
    "くん",
    "ちゃん",
    "さま",
    "様",
)

# Stop hiragana conjugation growth before these (aux / clause boundaries).
# Do NOT include ます/ました — those are part of the verb form (作りました).
_GROW_STOP_PREFIXES: Tuple[str, ...] = (
    "ください",
    "下さい",
    "かもしれない",
    "かもしれません",
    "けれど",
    "けれども",
    "けど",
    "です",
    "でした",
    "でしょう",
    "から",
    "ので",
    "のに",
    "すみません",
    "すいません",
    "んだよ",
    "んだ",
    "のだ",
    "んです",
)


def kanji_stem(text: str) -> str:
    """Contiguous substring from the first kanji to the last kanji (inclusive).

    Kanji do not change when a word conjugates, so this stem is a stable anchor
    for a target word even when it appears inflected in the sentence.
    Returns '' when the text has no kanji.
    """
    indices = [index for index, ch in enumerate(text) if _KANJI_RE.match(ch)]
    if not indices:
        return ""
    return text[indices[0] : indices[-1] + 1]


def _is_kana(ch: str) -> bool:
    return bool(_KANA_RE.match(ch))


def _is_hiragana(ch: str) -> bool:
    return bool(_HIRAGANA_RE.match(ch))


def _is_kanji(ch: str) -> bool:
    return bool(_KANJI_RE.match(ch))


def _expression_parts(expression: str) -> Tuple[str, str, str]:
    """Split expression into (kana_prefix, kanji_stem, okurigana).

    Kana-only lemmas return empty okurigana so expand_surface_span does not
    grow through following kana (ひなたち, 声でピーピー, 口にえさ, …).

    Address/plural suffixes (さん, たち, …) are stripped from okurigana so they
    do not trigger conjugation growth (お姉さん → prefix お, stem 姉).
    """
    expr = plain_mining_text(expression)
    stem = kanji_stem(expr)
    if not stem:
        return "", "", ""
    stem_at = expr.find(stem)
    prefix = expr[:stem_at]
    okurigana = expr[stem_at + len(stem) :]
    for suffix in _NON_INFLECTION_SUFFIXES:
        if okurigana.endswith(suffix):
            okurigana = okurigana[: -len(suffix)]
            break
    return prefix, stem, okurigana


def _trim_trailing_particles(
    span: str,
    *,
    min_len: int,
    particles: Sequence[str],
) -> str:
    """Drop trailing particles while keeping at least min_len characters."""
    text = span
    changed = True
    while changed:
        changed = False
        for particle in particles:
            if len(text) - len(particle) < min_len:
                continue
            if text.endswith(particle):
                text = text[: -len(particle)]
                changed = True
                break
    return text


def _trim_non_inflection_suffixes(
    span: str,
    *,
    min_len: int,
    expression: str,
) -> str:
    """Drop pluralizer/address suffixes that are not part of the lemma."""
    expr = plain_mining_text(expression)
    text = span
    changed = True
    while changed:
        changed = False
        for suffix in _NON_INFLECTION_SUFFIXES:
            if expr.endswith(suffix):
                continue
            if len(text) - len(suffix) < min_len:
                continue
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                changed = True
                break
    return text


def _okurigana_is_inflecting(okurigana: str) -> bool:
    """True when okurigana is hiragana that can conjugate (not 々, さん, …)."""
    if not okurigana:
        return False
    return all(_is_hiragana(ch) for ch in okurigana)


def _looks_like_inflection_after_stem(after: str, okurigana: str) -> bool:
    """Whether kana after a kanji stem looks like this lemma's inflection."""
    if not after or not _is_hiragana(after[0]):
        return False
    if not okurigana:
        return True
    if not _okurigana_is_inflecting(okurigana):
        return after.startswith(okurigana)
    if after.startswith(okurigana):
        return True
    # しい→しかった, がる→がって: first kana preserved
    if after[0] == okurigana[0]:
        return True
    # Single-kana okurigana (る/い/う…) — conjugated forms change the vowel row.
    if len(okurigana) == 1:
        allowed = _SINGLE_OKURI_CONJ_STARTS.get(okurigana)
        if allowed is not None:
            return after[0] in allowed
        return True
    return False


# First hiragana allowed after the kanji stem for common single-kana okurigana.
# Include ま for polite ます/ました (来ました, します).
_SINGLE_OKURI_CONJ_STARTS: Dict[str, frozenset] = {
    "る": frozenset("らりるれろっないたてとどだでずねま"),
    "う": frozenset("わいうえおったてとだま"),
    "く": frozenset("かきくけこいったてとだま"),
    "す": frozenset("さしすせそったてとだま"),
    "つ": frozenset("たちつてとっだま"),
    "ぬ": frozenset("なにぬねのっだま"),
    "ぶ": frozenset("ばびぶべぼんっだてとま"),
    "む": frozenset("まみむめもんっだてと"),
    "ぐ": frozenset("がぎぐげごいだてとま"),
    "い": frozenset("いくけかっう"),  # i-adjective
}


def _find_stem_index(plain: str, stem: str, okurigana: str) -> int:
    """First stem hit that is not mid-kanji-compound and matches inflection."""
    start = 0
    while True:
        idx = plain.find(stem, start)
        if idx < 0:
            return -1
        after_idx = idx + len(stem)
        # 日本|人 — stem must not continue into another kanji with no okurigana.
        if after_idx < len(plain) and _is_kanji(plain[after_idx]):
            start = idx + 1
            continue
        after = plain[after_idx:]
        if okurigana and not _looks_like_inflection_after_stem(after, okurigana):
            start = idx + 1
            continue
        return idx


def expand_surface_span(
    plain: str,
    start: int,
    end: int,
    expression: str,
) -> Tuple[int, int]:
    """Grow a provisional span to the full surface form of expression in plain.

    Exact dictionary-form / token-surface hits do not grow through following
    kana. Only a stem-sized hit for an inflecting lemma may grow, and only
    through hiragana up to an aux/clause boundary (not through アルバイト).
    """
    prefix, stem, okurigana = _expression_parts(expression)
    if stem and prefix:
        if start >= len(prefix) and plain[start - len(prefix) : start] == prefix:
            start -= len(prefix)

    provisional = plain[start:end]
    core = prefix + stem
    stem_only = bool(stem) and provisional in {stem, core}
    if stem and _okurigana_is_inflecting(okurigana) and stem_only:
        after = plain[end:]
        if _looks_like_inflection_after_stem(after, okurigana):
            grown = 0
            min_before_stop = max(len(okurigana), 1)
            while end < len(plain) and _is_hiragana(plain[end]):
                if grown >= min_before_stop:
                    stopped = False
                    for boundary in _GROW_STOP_PREFIXES:
                        if plain.startswith(boundary, end):
                            stopped = True
                            break
                    if stopped:
                        break
                end += 1
                grown += 1

    span = plain[start:end]
    if stem and span.startswith(core) and okurigana and span[len(core) :].startswith(okurigana):
        # Dictionary form is present — safe to strip a following particle.
        min_len = len(core) + len(okurigana)
        particles: Sequence[str] = _TRAILING_PARTICLES
    elif stem and not okurigana:
        # All-kanji (or kanji+prefix) noun — strip particles only; no kana growth.
        min_len = len(core) if core else 1
        particles = _TRAILING_PARTICLES
    elif stem:
        # Conjugated: keep te-form て/で; still drop は/が/を/…
        min_len = len(core) if core else 1
        particles = _CONJUGATED_TRAILING_PARTICLES
    else:
        # Exact kana (or empty) match — still drop a trailing particle if one
        # was included by a too-long provisional span.
        min_len = len(plain_mining_text(expression)) or 1
        particles = _TRAILING_PARTICLES
    trimmed = _trim_trailing_particles(span, min_len=max(min_len, 1), particles=particles)
    # Pluralizer / address suffixes are separate cards (達, さん), not inflection.
    trimmed = _trim_non_inflection_suffixes(
        trimmed, min_len=max(min_len, 1), expression=expression
    )
    return start, start + len(trimmed)


def split_surface_for_cloze(surface: str, expression: str) -> Tuple[str, str]:
    """Split surface into (answer_core, inflection_suffix) for two-tone cloze.

    Answer core is the lemma-aligned portion (kana prefix + kanji stem, plus
    dictionary okurigana when present). Inflection is conjugated material such
    as くて in 青くて or ました in やって来ました.
    """
    surface = plain_mining_text(surface)
    if not surface:
        return "", ""
    prefix, stem, okurigana = _expression_parts(expression)
    if not stem:
        return surface, ""
    core = prefix + stem
    if surface.startswith(core):
        rest = surface[len(core) :]
        if okurigana and rest.startswith(okurigana):
            return core + okurigana, rest[len(okurigana) :]
        return core, rest
    stem_at = surface.find(stem)
    if stem_at < 0:
        return surface, ""
    return surface[: stem_at + len(stem)], surface[stem_at + len(stem) :]


def format_cloze_surface_html(surface: str, expression: str) -> str:
    """HTML for a kanji-bearing surface: core target + optional inflection tint."""
    core, inflection = split_surface_for_cloze(surface, expression)
    if not core:
        return f'<span class="cloze-target">{html.escape(surface)}</span>'
    marked = f'<span class="cloze-target">{html.escape(core)}</span>'
    if inflection:
        marked += f'<span class="cloze-inflection">{html.escape(inflection)}</span>'
    return marked


# Transparent sentence forms only — not ありません/ない-based negatives
# (those are morphologically ある/ない, even when they negate です).
_EXPRESSION_SURFACE_VARIANTS: Dict[str, Tuple[str, ...]] = {
    "です": (
        "でした",
        "でしょう",
        "です",
        "だった",
        "だろ",
        "だ",
    ),
    "だ": (
        "だった",
        "だろ",
        "だ",
        "でした",
        "でしょう",
        "です",
    ),
    "である": (
        "であった",
        "である",
        "です",
        "でした",
        "だ",
        "だった",
    ),
}


_OPAQUE_COPULA_LEMMAS = frozenset({"です", "だ", "である"})


def should_skip_copula_cloze(
    expression: str,
    reading: str,
    sentence: str,
    *,
    surface: str = "",
) -> bool:
    """Skip です/だ/である unless the sentence has an obvious form (です/でした/…).

    Opaque negatives like ではありません are ある-based and are not useful clozes.
    """
    expr = plain_mining_text(expression)
    if expr not in _OPAQUE_COPULA_LEMMAS:
        return False
    return (
        resolve_surface_span(sentence, expression, reading, surface=surface) is None
    )


def surface_variants_for_expression(expression: str, reading: str = "") -> List[str]:
    """Candidate surface strings for expression, longest conjugations first."""
    expr = plain_mining_text(expression)
    read = plain_mining_text(reading)
    preferred: List[str] = []
    seen = set()
    for key in (expr, read):
        for item in _EXPRESSION_SURFACE_VARIANTS.get(key, ()):
            if item and item not in seen:
                seen.add(item)
                preferred.append(item)
    for item in blank_targets_for_expression(expression, reading):
        clean = plain_mining_text(item)
        if clean and clean not in seen:
            seen.add(clean)
            preferred.append(clean)
    return preferred


def resolve_surface_span(
    sentence: str,
    expression: str,
    reading: str = "",
    *,
    surface: str = "",
) -> Optional[Tuple[int, int, str]]:
    """Locate the target word span in sentence.

    Returns (start, end, plain_sentence) or None when no span can be found.
    Prefers an exact expression hit, then an optional morphology surface, then a
    kanji-stem anchor expanded to the full surface form (including conjugation).
    """
    plain = plain_mining_text(sentence)
    if not plain:
        return None
    expr = plain_mining_text(expression)

    def _finish(start: int, end: int) -> Tuple[int, int, str]:
        start, end = expand_surface_span(plain, start, end, expr or expression)
        return start, end, plain

    if expr:
        idx = plain.find(expr)
        if idx >= 0:
            return _finish(idx, idx + len(expr))

    surf = plain_mining_text(surface)
    if surf:
        idx = plain.find(surf)
        if idx >= 0:
            return _finish(idx, idx + len(surf))

    _prefix, stem, okuri = _expression_parts(expr)
    if stem:
        idx = _find_stem_index(plain, stem, okuri)
        if idx >= 0:
            return _finish(idx, idx + len(stem))

    for target in surface_variants_for_expression(expression, reading):
        clean = plain_mining_text(target)
        if not clean:
            continue
        idx = plain.find(clean)
        if idx < 0:
            continue
        # Known conjugations are already the full surface — do not re-expand
        # via dictionary okurigana heuristics (です must not grow through kana).
        variant_keys = {expr, plain_mining_text(reading)}
        is_known_variant = any(
            clean in _EXPRESSION_SURFACE_VARIANTS.get(key, ()) for key in variant_keys if key
        )
        if is_known_variant:
            return idx, idx + len(clean), plain
        if clean == expr:
            return _finish(idx, idx + len(clean))
        return _finish(idx, idx + len(clean))
    return None


def surface_span_text(
    sentence: str,
    expression: str,
    reading: str = "",
    *,
    surface: str = "",
) -> str:
    """Plain surface form of the target word in the sentence (for TTS / Audio)."""
    resolved = resolve_surface_span(
        sentence, expression, reading, surface=surface
    )
    if resolved is None:
        return ""
    start, end, plain = resolved
    return plain[start:end]


def build_satori_cloze_sentence(
    sentence: str,
    expression: str,
    reading: str,
    *,
    surface: str = "",
) -> Tuple[str, str]:
    """Immersion front cloze. Returns (cloze_html, plain_sentence).

    Marks the **whole surface span** of the target word in the sentence (including
    conjugation / okurigana). Type-in remains the dictionary ``Reading``.

    When the **sentence surface** contains kanji, use two tones: ``cloze-target``
    for the lemma core and ``cloze-inflection`` for conjugated endings.
    When the surface is kana-only (even if the lemma is written in kanji, e.g.
    達 → たち), blank it — highlighting kana would spoil the type-in.
    """
    resolved = resolve_surface_span(
        sentence, expression, reading, surface=surface
    )
    if resolved is None:
        plain = plain_mining_text(sentence)
        return (html.escape(plain) if plain else ""), plain
    start, end, plain = resolved
    before = html.escape(plain[:start])
    surface_text = plain[start:end]
    after = html.escape(plain[end:])
    # Blank vs highlight follows what appears in the sentence, not the lemma script.
    if kanji_stem(surface_text):
        marked = format_cloze_surface_html(surface_text, expression)
    else:
        marked = f'<span class="cloze-blank">{CLOZE_BLANK_DISPLAY}</span>'
    return f"{before}{marked}{after}", plain

SATORI_KIND = "satori-mining"
SATORI_TAG = "satori-mining"
SATORI_DECK_ID = DECK_IDS["satori"]
SATORI_MODEL_ID = MODEL_IDS["satori"]
SATORI_DECK_NAME = DECK_NAMES["satori"]
SATORI_NOTE_TYPE_NAME = NOTE_TYPE_NAMES["satori"]
SATORI_TEMPLATE_VERSION = MODEL_TEMPLATE_VERSIONS["satori"]
SATORI_MODEL_TEMPLATE_KEY = "satori"
SATORI_EXPORT_FILENAME = "wk_satori.apkg"

# Same field layout as Migaku immersion so enrich/unlock helpers stay compatible.
SATORI_FIELD_NAMES: Tuple[str, ...] = (
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
    "Audio",
    "ReadingAudio",
    "SentenceAudio",
    "SentenceAudioEasy",
    "VoicevoxAudio",
    "VoicevoxSpeakerId",
    "UserNotes",
    "SourceUrl",
    "SourceTitle",
    "Meta",
)

SATORI_FRONT = """
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

SATORI_SENTENCE_TTS = "{{tts ja_JP:Sentence}}"

SATORI_BACK = """
{{FrontSide}}
<hr>
<div class="answer-word jp">
  {{#Furigana}}{{furigana:Furigana}}{{/Furigana}}
  {{^Furigana}}{{Expression}}{{#Reading}} <span class="reading answer">{{Reading}}</span>{{/Reading}}{{/Furigana}}
</div>
{{#WkMeaning}}<div class="meaning answer">{{WkMeaning}}</div>{{/WkMeaning}}
{{#Audio}}
<div class="audio-row surface-audio-row">
  <div class="audio-label meta">Target</div>
  <audio class="surface-audio-manual" controls preload="none" src="{{Audio}}"></audio>
</div>
{{/Audio}}
{{#ReadingAudio}}
<div class="audio-row surface-audio-row">
  <div class="audio-label meta">Reading</div>
  <audio class="surface-audio-manual" controls preload="none" src="{{ReadingAudio}}"></audio>
</div>
{{/ReadingAudio}}
{{#Sentence}}
<div class="context">
  <div class="sentence-audio-block">
  {{#SentenceAudioEasy}}
  <div class="audio-row">
    <div class="audio-label meta">Easy</div>
    <div class="sentence-audio sentence-tts-file">{{SentenceAudioEasy}}</div>
  </div>
  {{/SentenceAudioEasy}}
  {{#SentenceAudio}}
  <div class="audio-row">
    <div class="audio-label meta">Normal</div>
    <audio class="sentence-audio-manual" controls preload="none" src="{{SentenceAudio}}"></audio>
  </div>
  {{/SentenceAudio}}
  {{^SentenceAudioEasy}}
  {{^SentenceAudio}}
  {{#VoicevoxAudio}}<div class="sentence-audio voicevox-audio">{{VoicevoxAudio}}</div>{{/VoicevoxAudio}}
  {{^VoicevoxAudio}}
  <div class="sentence-tts">""" + SATORI_SENTENCE_TTS + """</div>
  {{/VoicevoxAudio}}
  {{/SentenceAudio}}
  {{/SentenceAudioEasy}}
  </div>
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
<div class="meta">{{Meta}}</div>
<script>
(function () {
  document.querySelectorAll("audio.sentence-audio-manual, audio.surface-audio-manual").forEach(function (audio) {
    var src = (audio.getAttribute("src") || "").trim();
    var match = src.match(/\\[sound:([^\\]]+)\\]/);
    if (match) {
      audio.setAttribute("src", match[1]);
    }
  });
})();
</script>
"""

SATORI_CSS = """
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
.type-prompt { margin: 18px auto; max-width: 520px; font-size: 28px; }
.answer-word { font-size: 36px; margin: 12px auto; line-height: 1.8; }
.answer-word ruby rt { font-size: 14px; color: #d8d8d8; }
.context { font-size: 28px; margin: 12px auto; max-width: 760px; line-height: 1.6; }
.context-furigana { line-height: 2.1; }
.context-furigana ruby rt { font-size: 14px; color: #d8d8d8; }
.sentence-audio-block { margin: 8px 0 12px; }
.audio-row { margin: 6px 0; }
.audio-label { font-size: 13px; margin-bottom: 2px; }
.surface-audio-row { margin: 10px auto; max-width: 520px; }
.sentence-audio, .sentence-tts { margin: 2px 0 6px; }
.sentence-audio-manual,
.surface-audio-manual {
  display: block;
  width: 100%;
  max-width: 420px;
  margin: 2px 0 6px;
  height: 32px;
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
class SatoriCard:
    card_id: str
    card_type: str
    expression: str
    reading: str
    expression_furigana: str
    english: str
    parts_of_speech: str
    sentence: str
    sentence_furigana: str
    sentence_translation: str
    user_notes: str


# Satori often leaves the English column blank for conjunctions / story vocab
# that aren't in the WK mining index. Without a word gloss, kana-blank fronts
# become pure memorization — keep short production hints here.
SATORI_FALLBACK_MEANINGS: Dict[str, str] = {
    "そして": "and; and then",
    "しかし": "but; however",
    "それで": "and so; therefore",
    "それから": "and then; after that",
    "だから": "so; therefore",
    "でも": "but; however",
    "木々": "trees",
    "小鳥": "little bird",
    "とっても": "very; extremely",
    "親鳥": "parent bird",
    "ある日": "one day",
    "飛び出す": "to jump out; to fly out",
    "怖がり": "coward; timid person",
    "週間": "week(s); ... weeks",
}


def resolve_satori_word_meaning(
    expression: str,
    *,
    csv_english: str = "",
    wk_entry: Optional[dict] = None,
) -> str:
    """Prefer WK meaning, then CSV English, then curated fallbacks."""
    wk_meaning = str((wk_entry or {}).get("meaning") or "").strip()
    if wk_meaning:
        return wk_meaning
    csv_meaning = (csv_english or "").strip()
    if csv_meaning:
        return csv_meaning
    return SATORI_FALLBACK_MEANINGS.get((expression or "").strip(), "").strip()


def make_satori_model() -> WkModel:
    return WkModel(
        SATORI_MODEL_ID,
        SATORI_NOTE_TYPE_NAME,
        template_key=SATORI_MODEL_TEMPLATE_KEY,
        fields=[{"name": name} for name in SATORI_FIELD_NAMES],
        templates=[
            {
                "name": "Sentence cloze → word",
                "qfmt": SATORI_FRONT,
                "afmt": SATORI_BACK,
            },
        ],
        css=versioned_css(COMMON_CSS + SATORI_CSS, SATORI_MODEL_TEMPLATE_KEY),
    )


def _cell(row: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""


def parse_satori_csv(
    path: Path,
    *,
    card_types: Optional[Sequence[str]] = None,
) -> List[SatoriCard]:
    """Parse a Satori Reader export. Default: JE production cards only."""
    allowed = {ctype.upper() for ctype in (card_types or ("JE",))}
    cards: List[SatoriCard] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            card_type = _cell(row, "CardType").upper()
            if allowed and card_type not in allowed:
                continue
            expression = _cell(row, "Expression")
            sentence = _cell(row, "Context1")
            if not expression or not sentence:
                continue
            cards.append(
                SatoriCard(
                    card_id=_cell(row, "CardID") or f"{expression}|{sentence}",
                    card_type=card_type,
                    expression=expression,
                    reading=_cell(row, "Expression-ReadingsOnly"),
                    expression_furigana=_cell(row, "Expression-ReadingsInline"),
                    english=_cell(row, "English"),
                    parts_of_speech=_cell(row, "PartsOfSpeech"),
                    sentence=sentence,
                    sentence_furigana=_cell(row, "Context1-ReadingsInline"),
                    sentence_translation=_cell(row, "Context1-Translation"),
                    user_notes=_cell(row, "UserNotes"),
                )
            )
    return cards


def satori_note_fields(card: SatoriCard, *, wk_entry: Optional[dict] = None) -> List[str]:
    cloze_html, plain_sentence = build_satori_cloze_sentence(
        card.sentence, card.expression, card.reading
    )
    enrichment = enrich_mining_note_fields(
        expression=card.expression,
        reading=card.reading,
        sentence=plain_sentence or card.sentence,
        sentence_furigana=card.sentence_furigana,
        glossary=card.parts_of_speech,
        translation=card.english,
        wk_entry=wk_entry,
    )
    # Always keep Satori English visible (word + sentence), independent of hint stage.
    # Kana stays on the back only (via {{furigana:…}} / Reading) — never as a front hint.
    wk_meaning = resolve_satori_word_meaning(
        card.expression,
        csv_english=card.english,
        wk_entry=wk_entry,
    )
    translation = card.sentence_translation
    glossary = card.parts_of_speech
    duplicate_key = f"{card.card_id}|{enrichment.expression}|{enrichment.sentence}"
    meta = f"Satori · {card.card_type} · template {SATORI_TEMPLATE_VERSION}"
    expression_furigana = (card.expression_furigana or "").strip()
    sentence_furigana = (card.sentence_furigana or "").strip()
    # Hide the Jisho chip when a word gloss is already on the front.
    dict_links_en = "" if wk_meaning else enrichment.dict_links_en
    raw_html_fields = {
        "ClozeSentence",
        "DictLinksJa",
        "DictLinksEn",
        "SentenceFurigana",
        "Furigana",
    }
    values = {
        "DuplicateKey": duplicate_key,
        "Expression": enrichment.expression,
        "Reading": enrichment.reading or card.reading,
        "Translation": translation,
        "Furigana": expression_furigana,
        "PitchAccents": "",
        "PitchPositions": "",
        "PitchGraphs": "",
        "Glossary": glossary,
        "Synonyms": "",
        "Antonyms": "",
        "Image": "",
        "ClozeSentence": cloze_html or enrichment.cloze_sentence,
        "WkSubjectId": enrichment.wk_subject_id,
        "PrerequisiteIds": enrichment.prerequisite_ids,
        "WkMeaning": wk_meaning,
        "HintGlossary": enrichment.hint_glossary if not wk_meaning else "",
        "HintStage": "0",
        # Satori always shows English on the front; unlock must not clear these.
        "ShowEnglish": "1",
        "ShowKana": "",
        "ShowJjBack": "",
        "SentenceKana": enrichment.sentence_kana,
        "DictLinksJa": enrichment.dict_links_ja,
        "DictLinksEn": dict_links_en,
        "Sentence": enrichment.sentence,
        "SentenceFurigana": sentence_furigana,
        "Audio": "",
        "ReadingAudio": "",
        "SentenceAudio": "",
        "SentenceAudioEasy": "",
        "VoicevoxAudio": "",
        "VoicevoxSpeakerId": "",
        "UserNotes": card.user_notes,
        "SourceUrl": "",
        "SourceTitle": "Satori Reader",
        "Meta": meta,
    }
    fields: List[str] = []
    for name in SATORI_FIELD_NAMES:
        value = values[name]
        if name in raw_html_fields:
            fields.append(value)
        else:
            fields.append(html.escape(value))
    return fields


def build_satori_deck(
    cards: Sequence[SatoriCard],
    output_dir: Path,
    *,
    wk_index: Optional[dict] = None,
) -> Tuple[Path, genanki.Deck]:
    deck = genanki.Deck(SATORI_DECK_ID, SATORI_DECK_NAME)
    model = make_satori_model()
    by_expression = (wk_index or {}).get("by_expression") or {}
    skipped_copula = 0

    for card in cards:
        if should_skip_copula_cloze(card.expression, card.reading, card.sentence):
            skipped_copula += 1
            continue
        wk_entry = by_expression.get(card.expression)
        guid = stable_guid(SATORI_KIND, card.card_id)
        note = genanki.Note(
            model=model,
            fields=satori_note_fields(card, wk_entry=wk_entry),
            tags=["immersion", SATORI_TAG, f"satori-{card.card_type.lower()}"],
            guid=guid,
        )
        deck.add_note(note)

    if skipped_copula:
        print(
            f"Skipped {skipped_copula} opaque です/だ/である card(s) "
            "(no obvious form in sentence).",
            file=sys.stderr,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / SATORI_EXPORT_FILENAME
    write_apkg(deck, out)
    return out, deck
