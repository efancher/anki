"""Shared Anki card templates for WK Migaku Immersion (mining cloze)."""

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
