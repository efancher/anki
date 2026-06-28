"""
Map Hanabira grammar points to Tae Kim guide chapters and lessons.

Chapters (sections): Basic Grammar, Essential Grammar, etc. (tk-sec-03 …)
Lessons: sidebar subsections on guidetojapanese.org — tagged by title slug, e.g.
tag:tk-lesson-basic-introduction-to-particles
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parent
_SECTIONS_PATH = _REPO_ROOT / "tae_kim_sections.json"
_LESSONS_PATH = _REPO_ROOT / "tae_kim_lessons.json"

# JLPT fallback when no pattern matches (num, slug).
_JLPT_FALLBACK_SECTION: Dict[str, Tuple[int, str]] = {
    "N5": (3, "basic-grammar"),
    "N4": (4, "essential-grammar"),
    "N3": (5, "special-expressions"),
    "N2": (5, "special-expressions"),
    "N1": (6, "advanced-topics"),
}

# Basic Grammar lesson rules: (lesson_num, lesson_slug, regex) — first match wins.
_BASIC_LESSON_RULES: Sequence[Tuple[int, str, re.Pattern[str]]] = (
    (17, "adverbs-sentence-ending-particles", re.compile(
        r"sentence-ending|Gobi|Adverb|adverb|"
        r"よく|たいてい|ときどき|"
        r"けれど|しかし|でも|じゃ|それじゃ|それでは|では|"
        r"そして|それから|だから|"
        r"かな|でしょう|だろう",
        re.I,
    )),
    (16, "noun-related-particles", re.compile(
        r"Noun-related|とか|"
        r"Noun\s+や|や\s+Noun|"
        r"Noun\s+と\s|と\s+Noun|"
        r"Noun\s+など|など|"
        r"Noun\s+か\s+Noun\s+か|"
        r"の\s+あと|の\s+前|"
        r"という\s+Noun",
        re.I,
    )),
    (15, "relative-clauses", re.compile(
        r"Relative|Subordinate|Sentence Order|"
        r"Verb\s+る\s+Noun|Verb\s+た\s|"
        r"Verb\s+る\s+の|Verb\s+る\s+こと|"
        r"～とき|とき|時|"
        r"ている.*Noun|"
        r"Clause",
        re.I,
    )),
    (14, "transitive-intransitive-verbs", re.compile(
        r"Transitive|Intransitive|"
        r"始ま|始め|終わ|終え|"
        r"上が|上げ|下が|下げ|"
        r"入[るれ]|出[るす]|"
        r"付[くけ]|"
        r"自他",
        re.I,
    )),
    (13, "particles-used-with-verbs", re.compile(
        r"Particles used with verbs|"
        r"Noun\s+を|を〜|を\s|"
        r"に\s+(行|来|帰|入|出)|"
        r"Noun\s+で\s|で\s|"
        r"Noun\s+へ|へ\s|"
        r"から\s|まで|"
        r"に\s+(します|なります|います|あります)|"
        r"（場所）に",
        re.I,
    )),
    (11, "past-tense", re.compile(
        r"Past Tense|past tense|"
        r"Verb\s+た[^い]|"
        r"でした|ました|"
        r"い-Adjective.*Past|Past.*Adjective|"
        r"だった|でした",
        re.I,
    )),
    (9, "negative-verbs", re.compile(
        r"Negative Verb|negative verb|"
        r"Verb\s+ない|ません|"
        r"ないで\s|"
        r"あまり.*ない|"
        r"ぜんぜん.*ない|"
        r"まだ.*ない|"
        r"Adjective.*Negative|Negative.*Adjective|"
        r"Negative Polite",
        re.I,
    )),
    (7, "verb-basics", re.compile(
        r"Verb Basics|verb basics|"
        r"Verb\s+ます|Verb\s+まし|"
        r"Verb\s+て\s|Verb\s+て～|"
        r"Verb\s+る[^前]|"
        r"ましょう|ませんか|"
        r"Verb-te|"
        r"～て\s?います|ている",
        re.I,
    )),
    (5, "adjectives", re.compile(
        r"Adjective|adjective|"
        r"い-Adjective|な-Adjective|"
        r"Adjective\s+く|"
        r"Adjective\s+に|"
        r"Adjective\s+で|"
        r"Adjective\s+て|"
        r"Noun\s+に\s+(します|なります)",
        re.I,
    )),
    (3, "introduction-to-particles", re.compile(
        r"Introduction to Particles|"
        r"Noun\s+は|は〜|は\s|"
        r"A\s+は\s+B\s+が|"
        r"Noun\s+が[^っ]|が\s|が、|"
        r"Noun\s+も|も〜|も\s|"
        r"より|ほうが|いちばん|"
        r"こちら|そちら|"
        r"どこ|だれ|なに|どう|"
        r"いつ|"
        r"～が\s|"
        r"Question",
        re.I,
    )),
    (1, "expressing-state-of-being", re.compile(
        r"state-of-being|state of being|"
        r"です|だ[^ろ]|"
        r"ではあり|じゃあり|"
        r"Noun\s+は[^B]|"
        r"あります|います|"
        r"好き|嫌い|"
        r"～に\s+あります",
        re.I,
    )),
)

# (section_num, slug, regex) — checked in list order (advanced → basic).
_SECTION_RULES: Sequence[Tuple[int, str, re.Pattern[str]]] = (
    # --- Advanced Topics (6) ---
    (6, "advanced-topics", re.compile(
        r"べき|べから|ざるを得|かねる|得[るな]|に限[らる]|に越した|"
        r"とはいえ|ものの|にしても|からして|からすると|から見|"
        r"に相違ない|にほかなら|をもって|を以て|"
        r"んばかり|一方で|反面|上[はを]|末[に]|際[に]|"
        r"を契機|を機に|を皮切り|を踏まえ|"
        r"恐れ|恐れがある|に足[りる]|に値する|"
        r"Formal|literary|書き言葉",
        re.I,
    )),
    # --- Special Expressions (5) ---
    (5, "special-expressions", re.compile(
        r"わけ|はず|おかげ|せいで|"
        r"について|に対して|にとって|によって|により|"
        r"に関して|において|に比べ|にかわって|"
        r"らしい|みたい|っぽい|ようだ|そうだ|"
        r"ばかり|だけ|しか|ほど|くらい|ぐらい|"
        r"切[れる]|切れない|出す|続ける|終わる|"
        r"てしま|ちゃった|てお[くき]|てある|"
        r"ふり|振り|"
        r"かもしれ|でしょう|だろう|"
        r"一方|他方|"
        r"Causative and Passive|Honorific|Humble|"
        r"させ[らる]|られ[るた]|"
        r"いただ|くださる|差し上|"
        r"にくい|やすい|"
        r"すぎる|"
        r"っていう|というより|というと|というのは|"
        r"とおり|通り|"
        r"にしては|にしたら|として|"
        r"かけ|っぱなし|"
        r"うちに|たびに|"
        r"ものだ|もんだ|"
        r"決して|必ずしも|"
        r"上げる|"
        r"最中",
        re.I,
    )),
    # --- Essential Grammar (4) ---
    (4, "essential-grammar", re.compile(
        r"ください|下さい|なさい|ちょうだい|"
        r"ないと|いけない|なくちゃ|なきゃ|なければ|"
        r"てもいい|てはいけ|なくてもいい|"
        r"たら|れば|なら|と[、]?|"
        r"たい|ほしい|てほしい|"
        r"あげ[るた]|くれ[るた]|もら[うい]|"
        r"と思|という|っていう|"
        r"ように|ために|ようにする|ようになる|"
        r"ことができる|ことがある|"
        r"てみ|ておく|"
        r"ので|のに|"
        r"かどうか|"
        r"のです|んです|"
        r"ましょう|ませんか|"
        r"つもり|"
        r"ほうがいい|"
        r"ながら|"
        r"Polite|polite|ます|"
        r"Potential|potential|できる|"
        r"Conditional|Must|Desire|Request|Quotation|"
        r"Numbers|Counting|"
        r"Casual|Slang|"
        r"Addressing|Question Marker|Compound|"
        r"Trying|attempt|"
        r"Defining|Describing|"
        r"Giving|Receiving|"
        r"numbers|counter|"
        r"かなあ|かしら|"
        r"てから|"
        r"たことが|"
        r"ことにする|ことになる|"
        r"ところ|"
        r"ばかり|"
        r"ために|"
        r"の間|"
        r"させ[るて]|"
        r"Verb 方|"
        r"っけ",
        re.I,
    )),
    # --- Basic Grammar (3) ---
    (3, "basic-grammar", re.compile(
        r"Particle|particle|"
        r"Adjective|adjective|"
        r"Verb Basics|Negative Verbs|Past Tense|"
        r"Transitive|Intransitive|"
        r"Relative Clause|Subordinate|"
        r"Adverb|Gobi|sentence-ending|"
        r"state-of-being|state of being|"
        r"Noun\s+(は|が|を|に|で|へ|と|も|から|まで|より|の)|"
        r"い-Adjective|な-Adjective|"
        r"Verb\s+(?:て|た|ない|ます|まし|ません)|"
        r"ている|て\s?い|"
        r"けれど|しかし|でも|じゃ|それじゃ|それでは|では|"
        r"そして|それから|だから|"
        r"より|ほうが|いちばん|"
        r"たり|"
        r"とき|時|"
        r"あまり|"
        r"もう|まだ|"
        r"いつ|どこ|だれ|なに|どう|"
        r"こちら|そちら|"
        r"あります|います|"
        r"から\s|まで|"
        r"や\s|など|"
        r"か\s|"
        r"と\s|"
        r"に\s|"
        r"で\s|"
        r"を\s|"
        r"は\s|"
        r"が\s|"
        r"の\s|"
        r"も\s",
        re.I,
    )),
)


class TaeKimSection(NamedTuple):
    num: int
    slug: str
    name: str
    guide_url: str


class TaeKimLesson(NamedTuple):
    chapter_slug: str
    chapter_name: str
    num: int
    slug: str
    name: str
    has_cards: bool
    section_num: int


@lru_cache(maxsize=1)
def load_tae_kim_lessons() -> List[TaeKimLesson]:
    payload = json.loads(_LESSONS_PATH.read_text(encoding="utf-8"))
    lessons: List[TaeKimLesson] = []
    for chapter in payload["chapters"]:
        chapter_slug = str(chapter["slug"])
        chapter_name = str(chapter["name"])
        section_num = int(chapter["section_num"])
        for item in chapter["lessons"]:
            lessons.append(
                TaeKimLesson(
                    chapter_slug=chapter_slug,
                    chapter_name=chapter_name,
                    num=int(item["num"]),
                    slug=str(item["slug"]),
                    name=str(item["name"]),
                    has_cards=bool(item.get("has_cards", True)),
                    section_num=section_num,
                )
            )
    return lessons


def tae_kim_lesson(chapter_slug: str, lesson_num: int) -> Optional[TaeKimLesson]:
    for lesson in load_tae_kim_lessons():
        if lesson.chapter_slug == chapter_slug and lesson.num == lesson_num:
            return lesson
    return None


def tae_kim_lesson_by_slug(chapter_slug: str, lesson_slug: str) -> Optional[TaeKimLesson]:
    needle = _normalize_lesson_key(lesson_slug)
    for lesson in load_tae_kim_lessons():
        if lesson.chapter_slug != chapter_slug:
            continue
        if _normalize_lesson_key(lesson.slug) == needle:
            return lesson
        if _normalize_lesson_key(lesson.name) == needle:
            return lesson
    return None


def _normalize_lesson_key(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(" ", "-")


def tae_kim_lessons_for_chapter(chapter_slug: str) -> List[TaeKimLesson]:
    return [lesson for lesson in load_tae_kim_lessons() if lesson.chapter_slug == chapter_slug]


def parse_tae_kim_lesson_cap(value: str, *, default_chapter: str = "basic") -> Tuple[str, int]:
    """
    Parse a lesson cap using guidetojapanese.org subsection titles.

    Examples:
      basic:introduction-to-particles
      introduction-to-particles          (basic chapter assumed)
      basic:Introduction to Particles    (spaces → slug)
      basic:03                           (legacy numeric order)
    """
    raw = value.strip()
    if not raw:
        raise ValueError("Lesson cap cannot be empty.")

    if ":" in raw:
        chapter, lesson_part = raw.split(":", 1)
        chapter = chapter.strip().lower()
        lesson_part = lesson_part.strip()
    else:
        chapter = default_chapter
        lesson_part = raw.strip()

    if not chapter:
        raise ValueError(f"Invalid lesson cap {value!r}; missing chapter slug.")

    if lesson_part.isdigit():
        lesson = tae_kim_lesson(chapter, int(lesson_part))
        if lesson is None:
            raise ValueError(f"Unknown lesson number {lesson_part!r} in chapter {chapter!r}.")
        return chapter, lesson.num

    lesson = tae_kim_lesson_by_slug(chapter, lesson_part)
    if lesson is None:
        known = [
            f"{chapter}:{item.slug}"
            for item in tae_kim_lessons_for_chapter(chapter)
            if item.has_cards
        ]
        hint = ", ".join(known[:5])
        if len(known) > 5:
            hint += ", ..."
        raise ValueError(
            f"Unknown lesson {lesson_part!r} in chapter {chapter!r}. "
            f"Use a subsection title slug, e.g. {hint}"
        )
    return chapter, lesson.num


@lru_cache(maxsize=1)
def load_tae_kim_sections() -> List[TaeKimSection]:
    payload = json.loads(_SECTIONS_PATH.read_text(encoding="utf-8"))
    return [
        TaeKimSection(
            num=int(item["num"]),
            slug=str(item["slug"]),
            name=str(item["name"]),
            guide_url=str(item["guide_url"]),
        )
        for item in payload["sections"]
    ]


def tae_kim_section_by_num(num: int) -> Optional[TaeKimSection]:
    for section in load_tae_kim_sections():
        if section.num == num:
            return section
    return None


def tae_kim_section_by_slug(slug: str) -> Optional[TaeKimSection]:
    for section in load_tae_kim_sections():
        if section.slug == slug:
            return section
    return None


def grammar_point_search_text(point: dict) -> str:
    parts = [
        point.get("title") or "",
        point.get("formation") or "",
        point.get("short_explanation") or "",
        point.get("long_explanation") or "",
    ]
    return "\n".join(parts)


def map_grammar_point_to_tae_kim_section(point: dict) -> TaeKimSection:
    text = grammar_point_search_text(point)
    for num, slug, pattern in _SECTION_RULES:
        if pattern.search(text):
            section = tae_kim_section_by_num(num)
            if section is not None:
                return section

    jlpt = point.get("_jlpt") or "N3"
    fallback_num, fallback_slug = _JLPT_FALLBACK_SECTION.get(jlpt, (5, "special-expressions"))
    return tae_kim_section_by_slug(fallback_slug) or tae_kim_section_by_num(fallback_num)  # type: ignore[return-value]


def map_grammar_point_to_tae_kim_lesson(
    point: dict,
    *,
    section: Optional[TaeKimSection] = None,
) -> Optional[TaeKimLesson]:
    """Map to a Basic Grammar lesson when possible; None for other chapters (for now)."""
    resolved_section = section or map_grammar_point_to_tae_kim_section(point)
    if resolved_section.slug != "basic-grammar":
        return None

    text = grammar_point_search_text(point)
    for lesson_num, lesson_slug, pattern in _BASIC_LESSON_RULES:
        if pattern.search(text):
            return tae_kim_lesson("basic", lesson_num)

    # Unclassified N5-style points stay on the first basic lesson bucket.
    jlpt = point.get("_jlpt") or "N5"
    if jlpt == "N5":
        return tae_kim_lesson("basic", 3)
    return tae_kim_lesson("basic", 17)


def tae_kim_section_tags(section: TaeKimSection) -> List[str]:
    return [
        "tae-kim",
        f"tk-sec-{section.num:02d}",
        f"tk-{section.slug}",
    ]


def tae_kim_lesson_tags(lesson: TaeKimLesson) -> List[str]:
    chapter = lesson.chapter_slug
    return [
        "tae-kim",
        f"tk-lesson-{chapter}-{lesson.slug}",
    ]


def tae_kim_card_tags(
    section: TaeKimSection,
    lesson: Optional[TaeKimLesson],
) -> List[str]:
    tags = tae_kim_section_tags(section)
    if lesson is not None and lesson.has_cards:
        for tag in tae_kim_lesson_tags(lesson):
            if tag not in tags:
                tags.append(tag)
    return tags


def tae_kim_section_within_cap(section_num: int, max_section: int) -> bool:
    """Include grammar from section 3 upward through max_section (reading-order cap)."""
    grammar_min = 3
    return grammar_min <= section_num <= max_section


def tae_kim_lesson_within_cap(
    lesson: Optional[TaeKimLesson],
    section: TaeKimSection,
    *,
    max_chapter: str,
    max_lesson_num: int,
) -> bool:
    """Include cards through max_chapter:max_lesson_num (Basic Grammar lessons today)."""
    if max_chapter != "basic":
        return True
    if section.slug != "basic-grammar":
        return False
    if lesson is None:
        return False
    return lesson.num <= max_lesson_num


# Tae Kim Basic Grammar lesson when each WK conjugation form is introduced.
_TAE_KIM_BASIC_VERB_FORM_MIN_LESSON: Dict[str, int] = {
    "polite_present": 7,   # Verb Basics
    "polite_negative": 9,  # Negative Verbs
    "plain_negative": 9,
    "polite_past": 11,     # Past Tense
    "plain_past": 11,
    "te_form": 99,         # Essential Grammar (see section cap below)
}
_TAE_KIM_BASIC_I_ADJECTIVE_MIN_LESSON = 5   # Adjectives
_TAE_KIM_BASIC_NA_ADJECTIVE_MIN_LESSON = 1  # State-of-being (な-adj copula)
_TAE_KIM_TE_FORM_MIN_SECTION = 4            # Essential Grammar


class TaeKimConjugationCap(NamedTuple):
    """Allowed WK conjugation drill forms for a Tae Kim lesson/section cap."""

    verb_forms: frozenset
    i_adjective_forms: frozenset
    na_adjective_forms: frozenset

    def allows_word_class(self, word_class: str) -> bool:
        if word_class in {"godan", "ichidan", "suru_verb", "irregular_verb"}:
            return bool(self.verb_forms)
        if word_class == "i_adjective":
            return bool(self.i_adjective_forms)
        if word_class == "na_adjective":
            return bool(self.na_adjective_forms)
        return False

    def allows_form(self, word_class: str, form_key: str) -> bool:
        if word_class in {"godan", "ichidan", "suru_verb", "irregular_verb"}:
            return form_key in self.verb_forms
        if word_class == "i_adjective":
            return form_key in self.i_adjective_forms
        if word_class == "na_adjective":
            return form_key in self.na_adjective_forms
        return False


def _all_verb_form_keys() -> frozenset:
    return frozenset(_TAE_KIM_BASIC_VERB_FORM_MIN_LESSON.keys())


def _all_i_adjective_form_keys() -> frozenset:
    return frozenset(
        {
            "plain_negative",
            "plain_past",
            "plain_past_negative",
            "polite",
            "polite_negative",
            "polite_past",
        }
    )


def _all_na_adjective_form_keys() -> frozenset:
    return frozenset(_all_i_adjective_form_keys())


def conjugation_cap_for_tae_kim(
    *,
    max_tae_kim_lesson: str,
    max_tae_kim_section: int,
) -> TaeKimConjugationCap:
    """Map grammar lesson cap to allowed WK conjugation forms."""
    chapter, max_lesson_num = parse_tae_kim_lesson_cap(max_tae_kim_lesson)
    include_te = max_tae_kim_section >= _TAE_KIM_TE_FORM_MIN_SECTION

    if chapter != "basic":
        verb_forms = set(_all_verb_form_keys())
        if not include_te:
            verb_forms.discard("te_form")
        return TaeKimConjugationCap(
            verb_forms=frozenset(verb_forms),
            i_adjective_forms=_all_i_adjective_form_keys(),
            na_adjective_forms=_all_na_adjective_form_keys(),
        )

    verb_forms = {
        form_key
        for form_key, min_lesson in _TAE_KIM_BASIC_VERB_FORM_MIN_LESSON.items()
        if form_key != "te_form"
        and max_lesson_num >= min_lesson
    }
    if include_te:
        verb_forms.add("te_form")

    i_adj_forms = (
        _all_i_adjective_form_keys()
        if max_lesson_num >= _TAE_KIM_BASIC_I_ADJECTIVE_MIN_LESSON
        else frozenset()
    )
    na_adj_forms = (
        _all_na_adjective_form_keys()
        if max_lesson_num >= _TAE_KIM_BASIC_NA_ADJECTIVE_MIN_LESSON
        else frozenset()
    )
    return TaeKimConjugationCap(
        verb_forms=frozenset(verb_forms),
        i_adjective_forms=i_adj_forms,
        na_adjective_forms=na_adj_forms,
    )
