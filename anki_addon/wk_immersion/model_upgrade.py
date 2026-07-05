"""
Upgrade WK Yomitan Immersion note type in-place when apkg import did not apply template v7.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .logic import FIELD_SENTENCE_AUDIO, MINING_NOTE_TYPE

if TYPE_CHECKING:
    from anki.collection import Collection

# Template v5 audio block (VoicevoxAudio → Audio → TTS on Sentence).
_LEGACY_CONTEXT_AUDIO = (
    "  {{#VoicevoxAudio}}<div class=\"sentence-audio voicevox-audio\">{{VoicevoxAudio}}</div>{{/VoicevoxAudio}}\n"
    "  {{^VoicevoxAudio}}\n"
    "  {{#Audio}}<div class=\"sentence-audio mined-audio\">{{Audio}}</div>{{/Audio}}\n"
    "  {{^Audio}}<div class=\"sentence-tts\">{{tts ja_JP:Sentence}}</div>{{/Audio}}\n"
    "  {{/VoicevoxAudio}}\n"
)

# Template v6 — SentenceAudio first; Audio still fell through to sentence player.
_V6_SENTENCE_AUDIO_BLOCK = (
    "  {{#SentenceAudio}}<div class=\"sentence-audio sentence-tts-file\">{{SentenceAudio}}</div>{{/SentenceAudio}}\n"
    "  {{^SentenceAudio}}\n"
    "  {{#VoicevoxAudio}}<div class=\"sentence-audio voicevox-audio\">{{VoicevoxAudio}}</div>{{/VoicevoxAudio}}\n"
    "  {{^VoicevoxAudio}}\n"
    "  {{#Audio}}<div class=\"sentence-audio mined-audio\">{{Audio}}</div>{{/Audio}}\n"
    "  {{^Audio}}<div class=\"sentence-tts\">{{tts ja_JP:Sentence}}</div>{{/Audio}}\n"
    "  {{/VoicevoxAudio}}\n"
    "  {{/SentenceAudio}}\n"
)

# Template v7 — separate Word and Sentence players (Sentence label always visible).
_V7_SENTENCE_AUDIO_BLOCK = (
    "  <div class=\"sentence-audio-block\">\n"
    "  <div class=\"audio-label meta\">Sentence</div>\n"
    "  {{#SentenceAudio}}<div class=\"sentence-audio sentence-tts-file\">{{SentenceAudio}}</div>{{/SentenceAudio}}\n"
    "  {{^SentenceAudio}}\n"
    "  {{#VoicevoxAudio}}<div class=\"sentence-audio voicevox-audio\">{{VoicevoxAudio}}</div>{{/VoicevoxAudio}}\n"
    "  {{^VoicevoxAudio}}\n"
    "  <div class=\"sentence-tts\">{{tts ja_JP:Sentence}}</div>\n"
    "  {{/VoicevoxAudio}}\n"
    "  {{/SentenceAudio}}\n"
    "  </div>\n"
)

_V7_SENTENCE_SECTION = (
    "{{#Sentence}}\n"
    "<div class=\"context\">"
    + _V7_SENTENCE_AUDIO_BLOCK
    + "  {{#SentenceFurigana}}<div class=\"jp context-furigana\">{{SentenceFurigana}}</div>{{/SentenceFurigana}}\n"
    "  {{^SentenceFurigana}}<div class=\"jp\">{{Sentence}}</div>{{/SentenceFurigana}}\n"
    "</div>\n"
    "{{/Sentence}}\n"
)

_WORD_AUDIO_BLOCK = (
    "\n{{#Audio}}\n"
    "<div class=\"word-audio-block\">\n"
    "  <div class=\"audio-label meta\">Word</div>\n"
    "  <div class=\"word-audio\">{{Audio}}</div>\n"
    "</div>\n"
    "{{/Audio}}\n"
    "{{^Audio}}\n"
    "<div class=\"word-audio-block\">\n"
    "  <div class=\"audio-label meta\">Word</div>\n"
    "  {{#Reading}}<div class=\"word-tts\">{{tts ja_JP:Reading}}</div>{{/Reading}}\n"
    "  {{^Reading}}<div class=\"word-tts\">{{tts ja_JP:Expression}}</div>{{/Reading}}\n"
    "</div>\n"
    "{{/Audio}}\n"
)

_GLOSSARY_BLOCK = '<div class="meaning answer">{{Glossary}}</div>'
_WORD_DEFS_BLOCK = (
    "{{#Glossary}}\n"
    "<div class=\"word-def word-def-glossary\">\n"
    "  <div class=\"meta word-def-label\">意味</div>\n"
    "  <div class=\"word-def-body\">{{Glossary}}</div>\n"
    "</div>\n"
    "{{/Glossary}}\n"
    "{{#Synonyms}}\n"
    "<div class=\"word-def word-def-synonyms\">\n"
    "  <div class=\"meta word-def-label\">類</div>\n"
    "  <div class=\"word-def-body\">{{Synonyms}}</div>\n"
    "</div>\n"
    "{{/Synonyms}}\n"
    "{{#Antonyms}}\n"
    "<div class=\"word-def word-def-antonyms\">\n"
    "  <div class=\"meta word-def-label\">対</div>\n"
    "  <div class=\"word-def-body\">{{Antonyms}}</div>\n"
    "</div>\n"
    "{{/Antonyms}}\n"
)
FIELD_SYNONYMS = "Synonyms"
FIELD_ANTONYMS = "Antonyms"
_USER_NOTES_ANCHOR = "{{#UserNotes}}"
_SENTENCE_SECTION_RE = re.compile(r"\{\{#Sentence\}\}.*?\{\{/Sentence\}\}", re.DOTALL)


def _context_section_needs_repair(back: str) -> bool:
    if "{{#Sentence}}" not in back:
        return False
    if back.count("{{#SentenceAudio}}") > 1:
        return True
    if '{{^SentenceAudio}}\n  <div class="sentence-audio-block">' in back:
        return True
    if "sentence-audio-block" not in back:
        return True
    return False


def _repair_sentence_section(back: str) -> str:
    if not _context_section_needs_repair(back):
        return back
    if not _SENTENCE_SECTION_RE.search(back):
        return back
    return _SENTENCE_SECTION_RE.sub(_V7_SENTENCE_SECTION.strip(), back, count=1)


def _upgrade_back_template(back: str) -> str:
    updated = back
    if _GLOSSARY_BLOCK in updated:
        updated = updated.replace(_GLOSSARY_BLOCK + "\n                ", "")
        updated = updated.replace(_GLOSSARY_BLOCK + "\n", "")
        updated = updated.replace(_GLOSSARY_BLOCK, "")
    if _LEGACY_CONTEXT_AUDIO in updated:
        updated = updated.replace(_LEGACY_CONTEXT_AUDIO, _V7_SENTENCE_AUDIO_BLOCK)
    elif _V6_SENTENCE_AUDIO_BLOCK in updated:
        updated = updated.replace(_V6_SENTENCE_AUDIO_BLOCK, _V7_SENTENCE_AUDIO_BLOCK)
    updated = _repair_sentence_section(updated)
    if "word-def-glossary" not in updated:
        if "word-audio-block" in updated:
            updated = updated.replace(
                _WORD_AUDIO_BLOCK,
                _WORD_DEFS_BLOCK + _WORD_AUDIO_BLOCK,
                1,
            )
        elif _USER_NOTES_ANCHOR in updated:
            updated = updated.replace(
                _USER_NOTES_ANCHOR,
                _WORD_DEFS_BLOCK + _USER_NOTES_ANCHOR,
                1,
            )
    if "word-audio-block" not in updated and _USER_NOTES_ANCHOR in updated:
        updated = updated.replace(
            _USER_NOTES_ANCHOR,
            _WORD_AUDIO_BLOCK + "\n                " + _USER_NOTES_ANCHOR,
            1,
        )
    elif "word-audio-block" not in updated and _GLOSSARY_BLOCK in updated:
        updated = updated.replace(
            _GLOSSARY_BLOCK,
            _WORD_AUDIO_BLOCK + "\n                " + _GLOSSARY_BLOCK,
            1,
        )
    return updated


def ensure_immersion_model(col: "Collection") -> bool:
    """
    Add SentenceAudio and upgrade the back template when missing or outdated.
    Returns True if the note type was modified.
    """
    model = col.models.by_name(MINING_NOTE_TYPE)
    if model is None:
        return False

    changed = False
    field_names = [field["name"] for field in model["flds"]]
    if FIELD_SENTENCE_AUDIO not in field_names:
        col.models.add_field(model, col.models.new_field(FIELD_SENTENCE_AUDIO))
        changed = True
    if FIELD_SYNONYMS not in field_names:
        col.models.add_field(model, col.models.new_field(FIELD_SYNONYMS))
        changed = True
    if FIELD_ANTONYMS not in field_names:
        col.models.add_field(model, col.models.new_field(FIELD_ANTONYMS))
        changed = True

    for template in model["tmpls"]:
        back = template["afmt"]
        updated = _upgrade_back_template(back)
        if updated != back:
            template["afmt"] = updated
            changed = True

    if changed:
        col.models.save(model)
    return changed
