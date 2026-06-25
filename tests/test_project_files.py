import json
import sys
import uuid
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TEST_OUTPUT = ROOT / "test-output"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from my_ai_novel.project_files import (  # noqa: E402
    delete_style_sample,
    ensure_project_structure,
    load_style_profile,
    load_style_sample_text,
    load_style_samples,
    project_path,
    sanitize_filename,
    sync_chapters,
    sync_library,
    sync_project_core,
    sync_versions,
    write_style_profile,
    write_style_sample,
)


class ProjectFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_OUTPUT.mkdir(exist_ok=True)
        self.temp_dir = TEST_OUTPUT / f"project-files-{uuid.uuid4().hex}"
        self.temp_dir.mkdir()
        self.root = self.temp_dir / "projects"
        self.project = {
            "id": 42,
            "title": '雨夜:旧宅/第一卷*?"<>|',
            "genre": "悬疑",
            "style": "克制、冷峻",
            "target_readers": "成人",
            "length_target": "20万字",
            "pov": "第三人称有限",
            "world_summary": "旧宅只在雨夜显形。",
            "character_brief": "林砚追查失踪案。",
            "writing_style_guide": "短句，少解释，多动作。",
            "global_concept": "记忆会重写房间。",
        }

    def tearDown(self) -> None:
        pass

    def test_sanitize_filename_keeps_chinese_and_removes_windows_invalid_chars(self) -> None:
        self.assertEqual(sanitize_filename('雨夜:旧宅/第一卷*?"<>|'), "雨夜-旧宅-第一卷")
        self.assertEqual(sanitize_filename("CON"), "CON-file")
        self.assertEqual(sanitize_filename("..."), "untitled")

    def test_ensure_project_structure_uses_project_id_and_safe_title(self) -> None:
        base = ensure_project_structure(self.project, self.root)

        self.assertEqual(base.name, "project-42-雨夜-旧宅-第一卷")
        self.assertTrue(base.is_dir())
        for dirname in ("outline", "library", "chapters", "versions", "exports"):
            self.assertTrue((base / dirname).is_dir(), dirname)

        renamed = dict(self.project, title="改名后的标题")
        self.assertEqual(project_path(renamed, self.root), base)

    def test_sync_project_core_writes_readable_json_and_markdown(self) -> None:
        base = sync_project_core(self.project, self.root)

        project_json = json.loads((base / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(project_json["title"], self.project["title"])
        self.assertEqual(project_json["world_summary"], "旧宅只在雨夜显形。")

        worldbook = (base / "worldbook.md").read_text(encoding="utf-8")
        style = (base / "style.md").read_text(encoding="utf-8")
        self.assertIn("旧宅只在雨夜显形。", worldbook)
        self.assertIn("短句，少解释，多动作。", style)

    def test_sync_helpers_write_library_chapters_sections_and_versions(self) -> None:
        sync_project_core(self.project, self.root)
        library_paths = sync_library(
            self.project,
            [
                {
                    "id": 7,
                    "project_id": 42,
                    "kind": "character",
                    "name": "林砚:侦探",
                    "summary": "失眠的调查员",
                }
            ],
            self.root,
        )
        chapter = {
            "id": 3,
            "project_id": 42,
            "number": 1,
            "title": "旧宅入口",
            "story_time": "雨夜",
            "location": "旧宅",
            "goal": "发现入口",
            "outline": "门自己开了。",
            "status": "planned",
        }
        section = {
            "id": 9,
            "chapter_id": 3,
            "number": 2,
            "title": "走廊:回声",
            "scene": "一层走廊",
            "goal": "找到拖痕",
            "status": "generated",
        }
        chapter_paths = sync_chapters(self.project, [chapter], {3: [section]}, self.root)
        version_paths = sync_versions(
            self.project,
            [
                {
                    "id": 11,
                    "project_id": 42,
                    "chapter_id": 3,
                    "section_id": 9,
                    "kind": "draft",
                    "label": "粗稿",
                    "content": "雨线像针一样落下。",
                    "status": "usable",
                }
            ],
            self.root,
        )

        self.assertTrue(library_paths[0].name.endswith("林砚-侦探.json"))
        self.assertIn("门自己开了。", chapter_paths[0].read_text(encoding="utf-8"))
        self.assertTrue((self.root / "project-42-雨夜-旧宅-第一卷" / "chapters" / "chapter-001-旧宅入口" / "section-002-走廊-回声.json").exists())
        self.assertEqual(version_paths[0].read_text(encoding="utf-8"), "雨线像针一样落下。\n")
        self.assertTrue(version_paths[0].with_suffix(".json").exists())


class StyleSampleFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_OUTPUT.mkdir(exist_ok=True)
        self.temp_dir = TEST_OUTPUT / f"style-files-{uuid.uuid4().hex}"
        self.temp_dir.mkdir()
        self.root = self.temp_dir / "projects"
        self.project = {"id": 7, "title": "文风测试", "genre": "悬疑"}

    def test_write_and_load_style_sample_roundtrip(self) -> None:
        meta = {
            "id": "sample-001",
            "title": "样书A",
            "source_type": "authorized",
            "sha1": "abc123",
            "char_count": 12,
        }
        write_style_sample(self.project, meta, "他推开门，雨水灌进来。", self.root)

        samples = load_style_samples(self.project, self.root)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["id"], "sample-001")
        self.assertEqual(samples[0]["sha1"], "abc123")
        self.assertIn("他推开门", load_style_sample_text(self.project, "sample-001", self.root))

    def test_load_style_samples_excludes_profile_file(self) -> None:
        write_style_sample(self.project, {"id": "sample-001"}, "正文一。", self.root)
        write_style_profile(self.project, {"version": 1, "summary": "x"}, self.root)
        samples = load_style_samples(self.project, self.root)
        self.assertEqual([s["id"] for s in samples], ["sample-001"])

    def test_delete_style_sample_removes_meta_and_text(self) -> None:
        write_style_sample(self.project, {"id": "sample-001"}, "正文。", self.root)
        delete_style_sample(self.project, "sample-001", self.root)
        self.assertEqual(load_style_samples(self.project, self.root), [])
        self.assertEqual(load_style_sample_text(self.project, "sample-001", self.root), "")

    def test_write_and_load_style_profile_roundtrip(self) -> None:
        profile = {
            "version": 1,
            "summary": "近距离第三人称，短句为主",
            "metrics": {"avg_sentence_len": 14.7, "dialogue_ratio": 0.25},
            "anti_ai_rules": ["避免段尾总结主题"],
            "source_files": [{"name": "a.txt", "sha1": "abc123"}],
        }
        write_style_profile(self.project, profile, self.root)
        loaded = load_style_profile(self.project, self.root)
        self.assertEqual(loaded["summary"], profile["summary"])
        self.assertEqual(loaded["metrics"]["avg_sentence_len"], 14.7)
        self.assertEqual(loaded["source_files"][0]["sha1"], "abc123")

    def test_load_style_profile_missing_returns_empty(self) -> None:
        self.assertEqual(load_style_profile(self.project, self.root), {})


if __name__ == "__main__":
    unittest.main()
