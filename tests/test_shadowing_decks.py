"""Tests for Shadowing project → Anki deck import."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shadowing_decks import (  # noqa: E402
    SHADOWING_CANDIDATE_FIELD_NAMES,
    SHADOWING_CANDIDATE_NOTE_TYPE_NAME,
    SHADOWING_CANDIDATE_TAG,
    SHADOWING_EXPORT_FILENAME,
    SHADOWING_FIELD_NAMES,
    SHADOWING_NOTE_TYPE_NAME,
    SHADOWING_TAG,
    build_shadowing_decks,
    load_shadowing_project,
    make_shadowing_candidate_model,
    make_shadowing_model,
)
from wk_decks import DECK_IDS, MODEL_IDS, NOTE_TYPE_NAMES, stable_guid  # noqa: E402


def _write_project(root: Path) -> Path:
    project = root / "demo-video"
    project.mkdir(parents=True)
    (project / "clips").mkdir()
    clip = project / "clips" / "sentence-001-aaaaaa.m4a"
    clip.write_bytes(b"fake-m4a-bytes")
    (project / "source.json").write_text(
        json.dumps(
            {
                "id": "source-demo",
                "type": "youtube",
                "url": "https://www.youtube.com/watch?v=demo",
                "videoId": "demo",
                "title": "Demo Source",
                "channel": "Demo Channel",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project / "sentences.json").write_text(
        json.dumps(
            [
                {
                    "id": "sentence-001-aaaaaa",
                    "japanese": "今日は電車で行きます。",
                    "english": "I will go by train today.",
                    "reading": "きょうはでんしゃでいきます。",
                    "transcriptStatus": "manually-corrected",
                    "tags": ["travel"],
                    "notes": "",
                    "clipPath": "clips/sentence-001-aaaaaa.m4a",
                    "startMs": 1000,
                    "endMs": 3000,
                },
                {
                    "id": "sentence-002-bbbbbb",
                    "japanese": "新幹線は速いです。",
                    "english": "The shinkansen is fast.",
                    "reading": "",
                    "transcriptStatus": "auto-caption",
                    "tags": [],
                    "notes": "",
                    "clipPath": "clips/missing.m4a",
                    "startMs": 4000,
                    "endMs": 6000,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project


class ShadowingIdentityTests(unittest.TestCase):
    def test_ids_and_note_types_are_distinct_from_satori(self) -> None:
        self.assertEqual(NOTE_TYPE_NAMES["shadowing"], "WK Shadowing Immersion")
        self.assertNotEqual(DECK_IDS["shadowing"], DECK_IDS["satori"])
        self.assertNotEqual(MODEL_IDS["shadowing"], MODEL_IDS["satori"])
        self.assertNotEqual(
            SHADOWING_FIELD_NAMES,
            # Satori puts Audio before SentenceAudio; Shadowing leads with SentenceAudio.
            (
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
                "SentenceAudio",
                "SentenceAudioEasy",
                "VoicevoxAudio",
                "VoicevoxSpeakerId",
                "UserNotes",
                "SourceUrl",
                "SourceTitle",
                "Meta",
            ),
        )

    def test_guid_is_stable(self) -> None:
        a = stable_guid("shadowing-mining", "source-demo", "sentence-001", 10)
        b = stable_guid("shadowing-mining", "source-demo", "sentence-001", 10)
        c = stable_guid("shadowing-mining", "source-demo", "sentence-001", 11)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_model_field_order(self) -> None:
        model = make_shadowing_model()
        self.assertEqual([f["name"] for f in model.fields], list(SHADOWING_FIELD_NAMES))
        cand = make_shadowing_candidate_model()
        self.assertEqual(
            [f["name"] for f in cand.fields], list(SHADOWING_CANDIDATE_FIELD_NAMES)
        )
        self.assertEqual(model.name, SHADOWING_NOTE_TYPE_NAME)
        self.assertEqual(cand.name, SHADOWING_CANDIDATE_NOTE_TYPE_NAME)
        self.assertIn("{{type:Reading}}", cand.templates[0]["qfmt"])
        self.assertNotIn("{{type:Expression}}", cand.templates[0]["qfmt"])
        self.assertIn("{{HintGlossary}}", cand.templates[0]["qfmt"])
        self.assertIn("{{Translation}}", cand.templates[0]["qfmt"])
        self.assertIn("{{Audio}}", cand.templates[0]["afmt"])
        self.assertIn("{{ReadingAudio}}", cand.templates[0]["afmt"])
        self.assertIn("Target", cand.templates[0]["afmt"])
        self.assertIn("Reading", cand.templates[0]["afmt"])
        afmt = cand.templates[0]["afmt"]
        self.assertIn("autoplay-audio", afmt)
        self.assertIn("manual-tts-sound", afmt)
        self.assertNotIn("[sound:{{Audio}}]", afmt)
        self.assertNotIn("<audio", afmt)
        model_afmt = model.templates[0]["afmt"]
        self.assertIn("autoplay-audio", model_afmt)
        self.assertIn("manual-tts-sound", model_afmt)
        self.assertNotIn("<audio", model_afmt)

    def test_native_media_stem_from_duplicate_key(self) -> None:
        from shadowing_decks import native_shadowing_media_stem_from_duplicate_key

        self.assertEqual(
            native_shadowing_media_stem_from_duplicate_key(
                "source-FkX4A-ZLBrc|sentence-007-c2fca3|水希"
            ),
            "wk_shadowing_source-FkX4A-ZLBrc_sentence-007-c2fca3",
        )


class ShadowingProjectLoadTests(unittest.TestCase):
    def test_loads_source_and_sentences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = _write_project(Path(tmp))
            project = load_shadowing_project(project_dir)
            self.assertEqual(project.source.source_id, "source-demo")
            self.assertEqual(len(project.sentences), 2)
            self.assertEqual(project.sentences[0].japanese, "今日は電車で行きます。")

    def test_rejects_path_escape_clips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = _write_project(root)
            payload = json.loads((project_dir / "sentences.json").read_text(encoding="utf-8"))
            payload[0]["clipPath"] = "../outside.m4a"
            (project_dir / "sentences.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            project = load_shadowing_project(project_dir)
            from shadowing_decks import resolve_clip_path

            self.assertIsNone(resolve_clip_path(project, project.sentences[0]))


class ShadowingBuildTests(unittest.TestCase):
    def test_builds_one_note_per_wk_match_and_candidates(self) -> None:
        index = {
            "by_expression": {
                "今日": {
                    "id": 100,
                    "expression": "今日",
                    "reading": "きょう",
                    "meaning": "today",
                    "prerequisite_ids": "1",
                },
                "電車": {
                    "id": 101,
                    "expression": "電車",
                    "reading": "でんしゃ",
                    "meaning": "train",
                    "prerequisite_ids": "2,3",
                },
                "行く": {
                    "id": 102,
                    "expression": "行く",
                    "reading": "いく",
                    "meaning": "to go",
                    "prerequisite_ids": "4",
                },
            },
            "by_reading": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = _write_project(root)
            out = root / "out"
            wk_path, cand_path, stats = build_shadowing_decks(
                load_shadowing_project(project_dir),
                out,
                wk_index=index,
                include_auto_caption=True,
                jmdict_gloss_index={
                    "by_key": {},
                    "by_expression": {
                        "新幹線": [
                            {
                                "g": "Shinkansen",
                                "r": "しんかんせん",
                                "p": "n",
                                "c": 1,
                            }
                        ]
                    },
                },
            )
            self.assertTrue(wk_path.is_file())
            self.assertTrue(cand_path.is_file())
            self.assertEqual(wk_path.name, SHADOWING_EXPORT_FILENAME)
            # 今日 + 電車 + 行く (stem 行) from first sentence; second may add です if in index (not)
            self.assertGreaterEqual(stats.wk_notes, 3)
            self.assertEqual(stats.wk_notes, stats.wk_matches)
            self.assertGreaterEqual(stats.candidate_notes, 1)  # 新幹線
            self.assertEqual(stats.missing_clips, 1)

            # Media embedded for the first clip
            with zipfile.ZipFile(wk_path) as zf:
                names = zf.namelist()
                self.assertTrue(any(name.startswith("0") for name in names))

    def test_skip_auto_caption(self) -> None:
        index = {"by_expression": {}, "by_reading": {}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = _write_project(root)
            _, _, stats = build_shadowing_decks(
                load_shadowing_project(project_dir),
                root / "out",
                wk_index=index,
                include_auto_caption=False,
                jmdict_gloss_index={"by_key": {}, "by_expression": {}},
            )
            self.assertEqual(stats.skipped_auto_caption, 1)

    def test_tags(self) -> None:
        self.assertEqual(SHADOWING_TAG, "shadowing-mining")
        self.assertEqual(SHADOWING_CANDIDATE_TAG, "shadowing-candidate")

    def test_mining_package_uses_authoritative_selections(self) -> None:
        from shadowing_decks import load_mining_package

        index = {
            "by_expression": {
                "する": {
                    "id": 2467,
                    "expression": "する",
                    "reading": "する",
                    "meaning": "to do",
                }
            },
            "by_reading": {},
        }
        japanese = "世話をしました。"
        # surface し at index 3
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "demo.mining.zip"
            with zipfile.ZipFile(package, "w") as zf:
                zf.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "format": "japanese-shadowing-mining-package",
                            "version": 1,
                            "createdAt": "2026-07-25T00:00:00Z",
                            "generator": {"name": "satori-glossbook", "version": "0.6.0"},
                        }
                    ),
                )
                zf.writestr(
                    "source.json",
                    json.dumps(
                        {
                            "id": "source-demo",
                            "type": "other",
                            "title": "Demo Mining",
                        }
                    ),
                )
                zf.writestr(
                    "sentences.json",
                    json.dumps(
                        [
                            {
                                "id": "sentence-001",
                                "japanese": japanese,
                                "english": "They took care.",
                                "startMs": 0,
                                "endMs": 1000,
                                "transcriptStatus": "verified",
                                "tags": ["glossbook-confirmed"],
                                "audio": {
                                    "path": "audio/sentence-001.m4a",
                                    "mimeType": "audio/mp4",
                                    "durationMs": 1000,
                                },
                                "selectedVocabulary": [
                                    {
                                        "surface": "し",
                                        "start": 3,
                                        "end": 4,
                                        "expression": "する",
                                        "reading": "する",
                                    },
                                    {
                                        "surface": "世話",
                                        "start": 0,
                                        "end": 2,
                                        "expression": "世話",
                                        "reading": "せわ",
                                    },
                                ],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                )
                zf.writestr("audio/sentence-001.m4a", b"fake-audio")

            project = load_mining_package(package)
            self.assertTrue(project.curated)
            self.assertEqual(len(project.sentences), 1)
            self.assertEqual(len(project.sentences[0].selected_vocabulary), 2)

            out = root / "out"
            _, _, stats = build_shadowing_decks(
                project,
                out,
                wk_index=index,
                include_auto_caption=True,
                jmdict_gloss_index={"by_key": {}, "by_expression": {}},
            )
            # する is WK; 世話 is not in index → candidate
            self.assertEqual(stats.curated_selections, 2)
            self.assertEqual(stats.wk_notes, 1)
            self.assertEqual(stats.candidate_notes, 1)
            self.assertEqual(stats.missing_clips, 0)

    def test_mining_package_rejects_bad_span(self) -> None:
        from shadowing_decks import load_mining_package

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "bad.mining.zip"
            with zipfile.ZipFile(package, "w") as zf:
                zf.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "format": "japanese-shadowing-mining-package",
                            "version": 1,
                            "createdAt": "2026-07-25T00:00:00Z",
                            "generator": {"name": "satori-glossbook", "version": "0.6.0"},
                        }
                    ),
                )
                zf.writestr(
                    "source.json",
                    json.dumps({"id": "s", "type": "other", "title": "t"}),
                )
                zf.writestr(
                    "sentences.json",
                    json.dumps(
                        [
                            {
                                "id": "s1",
                                "japanese": "世話をしました。",
                                "startMs": 0,
                                "endMs": 1,
                                "transcriptStatus": "verified",
                                "tags": [],
                                "audio": {
                                    "path": "audio/a.m4a",
                                    "mimeType": "audio/mp4",
                                    "durationMs": 1,
                                },
                                "selectedVocabulary": [
                                    {
                                        "surface": "担ぐ",
                                        "start": 0,
                                        "end": 2,
                                        "expression": "担ぐ",
                                        "reading": "かつぐ",
                                    }
                                ],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                )
                zf.writestr("audio/a.m4a", b"x")
            with self.assertRaises(ValueError):
                load_mining_package(package)


if __name__ == "__main__":
    unittest.main()
