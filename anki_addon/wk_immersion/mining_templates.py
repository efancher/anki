"""Shared Anki card templates for WK Yomitan Immersion (mining cloze + shadow)."""

MINING_SENTENCE_TTS = "{{tts ja_JP:Sentence}}"

MINING_FRONT = """
<div class="mining-card">
  {{#ClozeSentence}}<div class="cloze-sentence jp">{{ClozeSentence}}</div>{{/ClozeSentence}}
  {{^ClozeSentence}}{{#Sentence}}<div class="cloze-sentence jp">{{Sentence}}</div>{{/Sentence}}{{/ClozeSentence}}
  <div class="hint-block">
    {{#ShowKana}}{{#Reading}}<div class="hint-reading">{{Reading}}</div>{{/Reading}}{{/ShowKana}}
    {{#ShowEnglish}}{{#WkMeaning}}<div class="hint-meaning">{{WkMeaning}}</div>{{/WkMeaning}}{{^WkMeaning}}{{#Translation}}<div class="hint-meaning">{{Translation}}</div>{{/Translation}}{{/WkMeaning}}{{/ShowEnglish}}
    {{#ShowEnglish}}{{^WkMeaning}}{{^Translation}}{{{DictLinksEn}}}{{/Translation}}{{/WkMeaning}}{{/ShowEnglish}}
    {{#ShowEnglish}}{{^WkMeaning}}{{^Translation}}{{#HintGlossary}}<div class="hint-glossary"><span class="meta">意味</span> {{HintGlossary}}</div>{{/HintGlossary}}{{/Translation}}{{/WkMeaning}}{{/ShowEnglish}}
    {{#ShowEnglish}}
    {{#PitchAccents}}<div class="hint-pitch"><span class="meta">Pitch</span> {{PitchAccents}}{{#PitchPositions}} <span class="pitch-pos">({{PitchPositions}})</span>{{/PitchPositions}}</div>{{/PitchAccents}}
    {{/ShowEnglish}}
  </div>
  <div class="type-prompt">{{type:Reading}}</div>
</div>
"""

MINING_BACK_CONTEXT = (
    """
{{#Image}}
<div class="context-image">{{Image}}</div>
{{/Image}}
{{#Sentence}}
<div class="context">
  <div class="sentence-audio-block">
  <div class="audio-label meta">Sentence</div>
  {{#SentenceAudio}}<div class="sentence-audio sentence-tts-file">{{SentenceAudio}}</div>{{/SentenceAudio}}
  {{^SentenceAudio}}
  {{#VoicevoxAudio}}<div class="sentence-audio voicevox-audio">{{VoicevoxAudio}}</div>{{/VoicevoxAudio}}
  {{^VoicevoxAudio}}
  <div class="sentence-tts">"""
    + MINING_SENTENCE_TTS
    + """</div>
  {{/VoicevoxAudio}}
  {{/SentenceAudio}}
  </div>
  {{#SentenceFurigana}}<div class="jp context-furigana">{{SentenceFurigana}}</div>{{/SentenceFurigana}}
  {{^SentenceFurigana}}<div class="jp">{{Sentence}}</div>{{/SentenceFurigana}}
</div>
{{/Sentence}}
"""
)

MINING_BACK_STAGE2 = """
{{#ShowJjBack}}
{{#SentenceKana}}<div class="sentence-kana-block"><div class="meta">Speak (kana)</div><div class="sentence-kana jp">{{SentenceKana}}</div></div>{{/SentenceKana}}
{{#PitchAccents}}<div class="pitch"><b>Pitch:</b> {{PitchAccents}}{{#PitchPositions}} <span class="pitch-pos">({{PitchPositions}})</span>{{/PitchPositions}}</div>{{/PitchAccents}}
{{#PitchGraphs}}<div class="pitch-graphs">{{PitchGraphs}}</div>{{/PitchGraphs}}
{{#SentencePitchGraphs}}
<div class="pitch sentence-pitch"><b>Sentence pitch:</b></div>
<div class="pitch-graphs">{{SentencePitchGraphs}}</div>
{{/SentencePitchGraphs}}
{{{DictLinksJa}}}
{{#Glossary}}
<div class="word-def word-def-glossary">
  <div class="meta word-def-label">意味</div>
  <div class="word-def-body">{{Glossary}}</div>
</div>
{{/Glossary}}
{{#Synonyms}}
<div class="word-def word-def-synonyms">
  <div class="meta word-def-label">類</div>
  <div class="word-def-body">{{Synonyms}}</div>
</div>
{{/Synonyms}}
{{#Antonyms}}
<div class="word-def word-def-antonyms">
  <div class="meta word-def-label">対</div>
  <div class="word-def-body">{{Antonyms}}</div>
</div>
{{/Antonyms}}
{{#Audio}}
<div class="word-audio-block">
  <div class="audio-label meta">Word</div>
  <div class="word-audio">{{Audio}}</div>
</div>
{{/Audio}}
{{/ShowJjBack}}
"""

MINING_BACK = (
    """
{{FrontSide}}
<hr>
<div class="answer-word jp">{{Expression}}{{#Reading}} <span class="reading answer">{{Reading}}</span>{{/Reading}}</div>
"""
    + MINING_BACK_CONTEXT
    + MINING_BACK_STAGE2
    + """
{{#UserNotes}}
<div class="user-notes">
  <div class="meta user-notes-label">Your notes</div>
  <div class="user-notes-body">{{UserNotes}}</div>
</div>
{{/UserNotes}}
{{#SourceTitle}}<div class="source">{{SourceTitle}}</div>{{/SourceTitle}}
{{#SourceUrl}}<div class="source"><a href="{{SourceUrl}}">{{SourceUrl}}</a></div>{{/SourceUrl}}
<div class="meta">{{Meta}}</div>
"""
)

# Shadowing card: listen → speak; back reveals kana + word pitch.
MINING_SHADOW_FRONT = (
    """
<div class="mining-card shadow-card">
  <div class="meta shadow-label">Shadow</div>
  <div class="sentence-audio-block">
  <div class="audio-label meta">Listen</div>
  {{#SentenceAudio}}<div class="sentence-audio sentence-tts-file">{{SentenceAudio}}</div>{{/SentenceAudio}}
  {{^SentenceAudio}}
  {{#VoicevoxAudio}}<div class="sentence-audio voicevox-audio">{{VoicevoxAudio}}</div>{{/VoicevoxAudio}}
  {{^VoicevoxAudio}}
  <div class="sentence-tts">"""
    + MINING_SENTENCE_TTS
    + """</div>
  {{/VoicevoxAudio}}
  {{/SentenceAudio}}
  </div>
  {{#Expression}}<div class="shadow-target meta">Target: <span class="jp">{{Expression}}</span></div>{{/Expression}}
  <div class="shadow-prompt">Speak along, then show pitch.</div>
</div>
"""
)

MINING_SHADOW_BACK = (
    """
{{FrontSide}}
<hr>
{{#SentenceKana}}
<div class="sentence-kana-block">
  <div class="meta">Kana</div>
  <div class="sentence-kana jp">{{SentenceKana}}</div>
</div>
{{/SentenceKana}}
{{#SentenceFurigana}}
<div class="context"><div class="jp context-furigana">{{SentenceFurigana}}</div></div>
{{/SentenceFurigana}}
{{^SentenceFurigana}}{{#Sentence}}
<div class="context"><div class="jp">{{Sentence}}</div></div>
{{/Sentence}}{{/SentenceFurigana}}
<div class="answer-word jp">{{Expression}}{{#Reading}} <span class="reading answer">{{Reading}}</span>{{/Reading}}</div>
{{#PitchAccents}}<div class="pitch"><b>Pitch:</b> {{PitchAccents}}{{#PitchPositions}} <span class="pitch-pos">({{PitchPositions}})</span>{{/PitchPositions}}</div>{{/PitchAccents}}
{{#PitchGraphs}}<div class="pitch-graphs">{{PitchGraphs}}</div>{{/PitchGraphs}}
{{#SentencePitchGraphs}}
<div class="pitch sentence-pitch"><b>Sentence pitch:</b></div>
<div class="pitch-graphs">{{SentencePitchGraphs}}</div>
{{/SentencePitchGraphs}}
{{#Audio}}
<div class="word-audio-block">
  <div class="audio-label meta">Word</div>
  <div class="word-audio">{{Audio}}</div>
</div>
{{/Audio}}
"""
)

MINING_CSS_EXTRA = """
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
.hint-block { margin: 12px auto; max-width: 640px; font-size: 20px; line-height: 1.5; }
.hint-reading { font-size: 28px; margin-bottom: 6px; color: #d8d8d8; }
.hint-meaning { color: #c8e6c9; margin-bottom: 6px; }
.hint-pitch, .hint-glossary { font-size: 16px; margin-top: 8px; text-align: left; }
.hint-glossary .meta, .hint-pitch .meta { margin-right: 6px; }
.type-prompt { margin: 18px auto; max-width: 520px; font-size: 28px; }
.answer-word { font-size: 36px; margin: 12px auto; }
.context-image { margin: 12px auto; max-width: 760px; text-align: center; }
.context-image img { max-width: 100%; height: auto; border-radius: 6px; }
.context { font-size: 28px; margin: 12px auto; max-width: 760px; line-height: 1.6; }
.context-furigana { line-height: 1.8; }
.context-furigana ruby { font-size: 28px; }
.context-furigana rt { font-size: 16px; color: #d8d8d8; }
.sentence-kana-block { margin: 14px auto; max-width: 760px; text-align: left; }
.sentence-kana { font-size: 24px; line-height: 1.6; color: #d8d8d8; }
.dict-links { font-size: 15px; margin: 8px 0; }
.dict-label { font-weight: bold; margin-right: 4px; }
.dict-links a { margin-right: 6px; }
.pitch { font-size: 18px; margin: 10px auto; max-width: 760px; }
.pitch-pos { color: #aaa; font-size: 15px; }
.pitch-graphs { margin: 8px auto; max-width: 760px; }
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
.word-def-label { margin-bottom: 6px; letter-spacing: 0.06em; }
.word-def-synonyms { border-left-color: #6a7a9a; background: rgba(106, 122, 154, 0.08); }
.word-def-antonyms { border-left-color: #9a6a7a; background: rgba(154, 106, 122, 0.08); }
.nightMode .word-def,
.card.nightMode .word-def,
.night_mode .word-def {
  background: rgba(255, 255, 255, 0.06);
}
.source { font-size: 13px; color: #aaa; margin-top: 8px; word-break: break-all; }
.audio-label { font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 4px; opacity: 0.85; }
.word-audio-block, .sentence-audio-block { margin: 10px auto; max-width: 760px; }
.word-audio, .word-tts, .sentence-tts { margin: 4px 0; }
.sentence-audio { margin: 4px 0; }
.shadow-label { letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 12px; }
.shadow-target { margin: 16px auto; font-size: 18px; }
.shadow-prompt { margin-top: 20px; font-size: 20px; color: #c8e6c9; }
.user-notes {
  text-align: left;
  margin: 16px auto;
  max-width: 760px;
  padding: 12px 14px;
  border-left: 3px solid #6a8fc7;
  background: rgba(106, 143, 199, 0.08);
}
.user-notes-label { margin-bottom: 6px; font-style: italic; }
.user-notes-body {
  font-size: 18px;
  line-height: 1.55;
  white-space: pre-wrap;
}
.nightMode .user-notes,
.card.nightMode .user-notes,
.night_mode .user-notes {
  background: rgba(106, 143, 199, 0.15);
}
.nightMode .context-furigana rt,
.card.nightMode .context-furigana rt,
.night_mode .context-furigana rt {
  color: #eeeeee;
}
"""
