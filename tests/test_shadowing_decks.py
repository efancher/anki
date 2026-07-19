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
            )
            self.assertEqual(stats.skipped_auto_caption, 1)

    def test_tags(self) -> None:
        self.assertEqual(SHADOWING_TAG, "shadowing-mining")
        self.assertEqual(SHADOWING_CANDIDATE_TAG, "shadowing-candidate")


if __name__ == "__main__":
    unittest.main()
