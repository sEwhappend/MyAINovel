import json
import unittest
import uuid
from pathlib import Path

from my_ai_novel.project_files import find_project_path
from my_ai_novel.storage import NovelStore

ROOT = Path(__file__).resolve().parents[1]
TEST_OUTPUT = ROOT / "test-output"


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_OUTPUT.mkdir(exist_ok=True)
        self.case_id = f"{self._testMethodName}_{uuid.uuid4().hex}"
        self.db_path = TEST_OUTPUT / f"{self.case_id}.db"
        self.projects_root = TEST_OUTPUT / f"{self.case_id}_projects"
        self.store = NovelStore(self.db_path, projects_root=self.projects_root)

    def tearDown(self) -> None:
        pass

    def _finalize_new_section(self, project_id, chapter_id, number, title, text):
        section_id = self.store.save_section(chapter_id, {"number": number, "title": title, "emotion_shift": f"{title}:平静→紧张"})
        version_id = self.store.save_version(
            {"project_id": project_id, "chapter_id": chapter_id, "section_id": section_id,
             "kind": "rewrite", "label": "定稿", "content": text}
        )
        self.store.finalize_section(section_id, version_id)
        return section_id

    def test_previous_finalized_section_same_chapter(self) -> None:
        pid = self.store.create_project({"title": "续写"})
        cid = self.store.save_chapter(pid, {"number": 1, "title": "章一"})
        self._finalize_new_section(pid, cid, 1, "第一节", "他推开门，雨水灌进来。")
        s2 = self.store.save_section(cid, {"number": 2, "title": "第二节"})
        prev = self.store.previous_finalized_section(pid, cid, 2)
        self.assertIsNotNone(prev)
        self.assertEqual(prev["section_number"], 1)
        self.assertIn("他推开门", prev["content"])

    def test_previous_finalized_section_crosses_chapter(self) -> None:
        pid = self.store.create_project({"title": "续写"})
        c1 = self.store.save_chapter(pid, {"number": 1, "title": "章一"})
        self._finalize_new_section(pid, c1, 1, "尾节", "她转身离开，灯光摇晃。")
        c2 = self.store.save_chapter(pid, {"number": 2, "title": "章二"})
        self.store.save_section(c2, {"number": 1, "title": "新章首节"})
        prev = self.store.previous_finalized_section(pid, c2, 1)
        self.assertIsNotNone(prev)
        self.assertIn("她转身离开", prev["content"])  # 取到上一章末节

    def test_previous_finalized_section_none_for_first(self) -> None:
        pid = self.store.create_project({"title": "续写"})
        cid = self.store.save_chapter(pid, {"number": 1, "title": "章一"})
        self.store.save_section(cid, {"number": 1, "title": "首节"})
        self.assertIsNone(self.store.previous_finalized_section(pid, cid, 1))

    def test_project_style_ref_roundtrip(self) -> None:
        project_id = self.store.create_project({"title": "引用文风", "style_ref": "轻小说体"})
        self.assertEqual(self.store.get_project(project_id)["style_ref"], "轻小说体")
        self.store.update_project(project_id, {"style_ref": "克制叙事"})
        self.assertEqual(self.store.get_project(project_id)["style_ref"], "克制叙事")

    def test_project_style_ref_defaults_empty(self) -> None:
        project_id = self.store.create_project({"title": "无文风"})
        self.assertEqual(self.store.get_project(project_id).get("style_ref", ""), "")

    def test_project_chapter_section_version_round_trip(self) -> None:
        project_id = self.store.create_project(
            {
                "title": "雨夜旧宅",
                "genre": "悬疑",
                "style": "克制",
                "target_readers": "成人",
                "length_target": "20万字",
                "pov": "第三人称有限",
            }
        )
        chapter_id = self.store.save_chapter(
            project_id,
            {
                "number": 1,
                "title": "旧宅入口",
                "story_time": "雨夜",
                "location": "旧宅",
                "characters": ["林砚", "周棠"],
                "goal": "发现入口",
            },
        )
        section_id = self.store.save_section(
            chapter_id,
            {
                "number": 1,
                "title": "走廊",
                "story_time": "雨夜十点",
                "location": "一层走廊",
                "characters": ["林砚"],
                "goal": "发现拖痕",
            },
        )
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "draft",
                "label": "粗稿",
                "content": "正文",
            }
        )

        self.store.finalize_section(section_id, version_id)
        section = self.store.get_section(section_id)
        self.assertEqual(section["status"], "finalized")
        self.assertEqual(section["finalized_version_id"], version_id)

        self.store.unfinalize_section(section_id)
        section = self.store.get_section(section_id)
        self.assertEqual(section["status"], "review_pending")
        self.assertIsNone(section["finalized_version_id"])

    def test_move_chapter_reorders_and_renumbers_project_chapters(self) -> None:
        project_id = self.store.create_project({"title": "章节排序"})
        first_id = self.store.save_chapter(project_id, {"number": 10, "title": "第一章"})
        second_id = self.store.save_chapter(project_id, {"number": 10, "title": "第二章"})
        third_id = self.store.save_chapter(project_id, {"number": 30, "title": "第三章"})

        self.store.move_chapter(project_id, third_id, -1)

        chapters = self.store.list_chapters(project_id)
        self.assertEqual([chapter["id"] for chapter in chapters], [first_id, third_id, second_id])
        self.assertEqual([chapter["number"] for chapter in chapters], [1, 2, 3])

    def test_move_chapter_reports_boundary_errors(self) -> None:
        project_id = self.store.create_project({"title": "章节边界"})
        first_id = self.store.save_chapter(project_id, {"number": 1, "title": "第一章"})
        second_id = self.store.save_chapter(project_id, {"number": 2, "title": "第二章"})

        with self.assertRaisesRegex(ValueError, "已经是第一章"):
            self.store.move_chapter(project_id, first_id, -1)
        with self.assertRaisesRegex(ValueError, "已经是最后一章"):
            self.store.move_chapter(project_id, second_id, 1)

    def test_project_default_section_target_words_round_trip(self) -> None:
        project_id = self.store.create_project(
            {"title": "默认字数项目", "default_section_target_words": "1800"}
        )

        self.assertEqual(self.store.get_project(project_id)["default_section_target_words"], "1800")

        self.store.update_project(project_id, {"default_section_target_words": "2200"})

        project = self.store.get_project(project_id)
        self.assertEqual(project["default_section_target_words"], "2200")
        project_json = json.loads((self._project_dir(project_id) / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(project_json["default_section_target_words"], "2200")

    def test_project_estimated_sections_calculates_default_section_target_words(self) -> None:
        project_id = self.store.create_project(
            {
                "title": "自动默认字数项目",
                "length_target": "8万字",
                "estimated_total_sections": "40",
                "default_section_target_words": "",
            }
        )

        project = self.store.get_project(project_id)
        self.assertEqual(project["estimated_total_sections"], "40")
        self.assertEqual(project["default_section_target_words"], "2000")
        project_json = json.loads((self._project_dir(project_id) / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(project_json["estimated_total_sections"], "40")
        self.assertEqual(project_json["default_section_target_words"], "2000")

    def test_update_project_calculates_default_section_target_words_when_blank(self) -> None:
        project_id = self.store.create_project({"title": "更新默认字数项目"})

        self.store.update_project(
            project_id,
            {
                "length_target": "90000",
                "estimated_total_sections": "45节",
                "default_section_target_words": "",
            },
        )

        project = self.store.get_project(project_id)
        self.assertEqual(project["default_section_target_words"], "2000")

    def test_project_style_tags_round_trip_to_project_json(self) -> None:
        project_id = self.store.create_project(
            {
                "title": "标签项目",
                "selected_genre_tags": ["fantasy", "mystery"],
                "selected_setting_tags": ["level_system"],
                "selected_structure_tags": ["ensemble"],
                "selected_style_tags": ["growth"],
                "dialogue_quote_style": "corner_quotes",
            }
        )

        project = self.store.get_project(project_id)
        self.assertEqual(json.loads(project["selected_genre_tags"]), ["fantasy", "mystery"])
        self.assertEqual(json.loads(project["selected_setting_tags"]), ["level_system"])
        self.assertEqual(project["dialogue_quote_style"], "corner_quotes")

        self.store.update_project(
            project_id,
            {
                "selected_setting_tags": "skill_system,ts",
                "dialogue_quote_style": "cn_quotes",
            },
        )
        project = self.store.get_project(project_id)
        self.assertEqual(json.loads(project["selected_setting_tags"]), ["skill_system", "ts"])
        self.assertEqual(project["dialogue_quote_style"], "cn_quotes")
        project_json = json.loads((self._project_dir(project_id) / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(project_json["selected_setting_tags"]), ["skill_system", "ts"])
        self.assertEqual(project_json["dialogue_quote_style"], "cn_quotes")

    def test_generation_profile_round_trip_to_project_json(self) -> None:
        profile = {
            "creation_mode": "candidate",
            "search_query": "异世界转移 等级成长",
            "selected_candidate": {"temporary_title": "钟楼异乡人"},
        }
        project_id = self.store.create_project(
            {
                "title": "搜索式项目",
                "generation_profile_json": profile,
            }
        )

        project = self.store.get_project(project_id)
        self.assertEqual(json.loads(project["generation_profile_json"])["search_query"], "异世界转移 等级成长")

        self.store.update_project(project_id, {"generation_profile_json": {"creation_mode": "manual"}})
        project = self.store.get_project(project_id)
        self.assertEqual(json.loads(project["generation_profile_json"])["creation_mode"], "manual")
        project_json = json.loads((self._project_dir(project_id) / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(project_json["generation_profile_json"])["creation_mode"], "manual")

    def test_move_section_reorders_and_renumbers_chapter_sections(self) -> None:
        project_id = self.store.create_project({"title": "小节排序"})
        chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "章节"})
        first_id = self.store.save_section(chapter_id, {"number": 10, "title": "第一节"})
        second_id = self.store.save_section(chapter_id, {"number": 10, "title": "第二节"})
        third_id = self.store.save_section(chapter_id, {"number": 30, "title": "第三节"})

        self.store.move_section(chapter_id, third_id, -1)

        sections = self.store.list_sections(chapter_id)
        self.assertEqual([section["id"] for section in sections], [first_id, third_id, second_id])
        self.assertEqual([section["number"] for section in sections], [1, 2, 3])

    def test_move_section_reports_boundary_errors(self) -> None:
        project_id = self.store.create_project({"title": "小节边界"})
        chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "章节"})
        first_id = self.store.save_section(chapter_id, {"number": 1, "title": "第一节"})
        second_id = self.store.save_section(chapter_id, {"number": 2, "title": "第二节"})

        with self.assertRaisesRegex(ValueError, "已经是第一节"):
            self.store.move_section(chapter_id, first_id, -1)
        with self.assertRaisesRegex(ValueError, "已经是最后一节"):
            self.store.move_section(chapter_id, second_id, 1)

    def test_delete_section_removes_versions_and_renumbers_remaining_sections(self) -> None:
        project_id = self.store.create_project({"title": "删除小节项目"})
        chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "章节"})
        first_id = self.store.save_section(chapter_id, {"number": 1, "title": "第一节"})
        second_id = self.store.save_section(chapter_id, {"number": 2, "title": "第二节"})
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": first_id,
                "kind": "draft",
                "label": "待删正文",
                "content": "正文",
            }
        )

        self.store.delete_section(first_id)

        self.assertIsNone(self.store.get_section(first_id))
        self.assertIsNone(self.store.get_version(version_id))
        sections = self.store.list_sections(chapter_id)
        self.assertEqual([section["id"] for section in sections], [second_id])
        self.assertEqual([section["number"] for section in sections], [1])

    def test_delete_section_removes_synced_version_files(self) -> None:
        project_id = self.store.create_project({"title": "删除版本文件项目"})
        chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "章节"})
        section_id = self.store.save_section(chapter_id, {"number": 1, "title": "第一节"})
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "draft",
                "label": "待删正文",
                "content": "正文",
            }
        )
        project_dir = self._project_dir(project_id)
        version_file = project_dir / "versions" / "draft" / f"{version_id:04d}-待删正文.md"
        self.assertTrue(version_file.exists())

        self.store.delete_section(section_id)

        self.assertFalse(version_file.exists())

    def test_delete_version_removes_database_row_and_synced_files(self) -> None:
        project_id = self.store.create_project({"title": "删除单个版本项目"})
        chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "章节"})
        section_id = self.store.save_section(chapter_id, {"number": 1, "title": "第一节"})
        first_version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "draft",
                "label": "待删正文",
                "content": "正文一",
            }
        )
        second_version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "rewrite",
                "label": "保留正文",
                "content": "正文二",
            }
        )
        project_dir = self._project_dir(project_id)
        deleted_file = project_dir / "versions" / "draft" / f"{first_version_id:04d}-待删正文.md"
        kept_file = project_dir / "versions" / "rewrite" / f"{second_version_id:04d}-保留正文.md"
        self.assertTrue(deleted_file.exists())
        self.assertTrue(kept_file.exists())

        self.store.delete_version(first_version_id)

        self.assertIsNone(self.store.get_version(first_version_id))
        self.assertIsNotNone(self.store.get_version(second_version_id))
        self.assertFalse(deleted_file.exists())
        self.assertTrue(kept_file.exists())

    def test_delete_version_rejects_finalized_version(self) -> None:
        project_id = self.store.create_project({"title": "保护定稿版本项目"})
        chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "章节"})
        section_id = self.store.save_section(chapter_id, {"number": 1, "title": "第一节"})
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "rewrite",
                "label": "定稿",
                "content": "正文",
            }
        )
        self.store.finalize_section(section_id, version_id)

        with self.assertRaisesRegex(ValueError, "定稿版本不能直接删除"):
            self.store.delete_version(version_id)

        self.assertIsNotNone(self.store.get_version(version_id))

    def test_delete_chapter_removes_sections_versions_and_renumbers_project(self) -> None:
        project_id = self.store.create_project({"title": "删除章节项目"})
        first_chapter = self.store.save_chapter(project_id, {"number": 1, "title": "第一章"})
        second_chapter = self.store.save_chapter(project_id, {"number": 2, "title": "第二章"})
        section_id = self.store.save_section(first_chapter, {"number": 1, "title": "第一节"})
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": first_chapter,
                "section_id": section_id,
                "kind": "draft",
                "label": "待删正文",
                "content": "正文",
            }
        )

        self.store.delete_chapter(project_id, first_chapter)

        self.assertIsNone(self.store.get_chapter(first_chapter))
        self.assertIsNone(self.store.get_section(section_id))
        self.assertIsNone(self.store.get_version(version_id))
        chapters = self.store.list_chapters(project_id)
        self.assertEqual([chapter["id"] for chapter in chapters], [second_chapter])
        self.assertEqual([chapter["number"] for chapter in chapters], [1])

    def test_status_validation(self) -> None:
        project_id = self.store.create_project({"title": "测试"})
        with self.assertRaises(ValueError):
            self.store.save_chapter(project_id, {"status": "bad"})

    def test_llm_config_does_not_store_api_key(self) -> None:
        config_id = self.store.save_llm_config(
            {
                "base_url": "https://example.test/v1",
                "api_key_ref": "llm_config",
                "chat_model": "writer",
                "max_tokens": 3000,
                "temperature": 0.8,
                "top_p": 0.95,
                "top_k": 40,
                "presence_penalty": 0.2,
                "frequency_penalty": 0.1,
            }
        )
        config = self.store.get_default_llm_config()
        self.assertEqual(config["id"], config_id)
        self.assertEqual(config["api_key_ref"], "llm_config")
        self.assertNotIn("api_key", config)
        self.assertEqual(config["top_k"], 40)

    def test_create_and_update_project_syncs_core_files(self) -> None:
        project_id = self.store.create_project(
            {
                "title": "雨夜:旧宅",
                "genre": "悬疑",
                "style": "冷峻",
                "world_summary": "雨不会停。",
                "api_key": "secret-key-should-not-sync",
            }
        )

        project_dir = self._project_dir(project_id)
        project_json = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(project_json["title"], "雨夜:旧宅")
        self.assertNotIn("api_key", project_json)
        self.assertIn("雨不会停。", (project_dir / "worldbook.md").read_text(encoding="utf-8"))
        self.assertIn("冷峻", (project_dir / "style.md").read_text(encoding="utf-8"))

        self.store.update_project(project_id, {"global_concept": "旧宅会回应每个谎言。"})
        self.assertIn(
            "旧宅会回应每个谎言。",
            (project_dir / "worldbook.md").read_text(encoding="utf-8"),
        )

    def test_world_chapter_section_and_version_sync_files(self) -> None:
        project_id = self.store.create_project({"title": "同步项目"})
        item_id = self.store.save_world_item(
            project_id,
            {
                "kind": "character",
                "name": "林砚",
                "summary": "主角",
                "details": {"motivation": "查明旧案"},
                "tags": "主角,侦探",
            },
        )
        chapter_id = self.store.save_chapter(
            project_id,
            {"number": 1, "title": "旧宅入口", "outline": "进入旧宅。"},
        )
        section_id = self.store.save_section(
            chapter_id,
            {"number": 1, "title": "走廊", "goal": "发现拖痕"},
        )
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "draft",
                "label": "粗稿",
                "content": "走廊尽头传来滴水声。",
            }
        )

        project_dir = self._project_dir(project_id)
        library_file = project_dir / "library" / "character" / f"{item_id:04d}-林砚.json"
        self.assertTrue(library_file.exists())
        library_data = json.loads(library_file.read_text(encoding="utf-8"))
        self.assertEqual(library_data["summary"], "主角")
        self.assertEqual(library_data["details"]["motivation"], "查明旧案")
        self.assertNotIn("details_json", library_data)

        chapter_dir = project_dir / "chapters" / "chapter-001-旧宅入口"
        self.assertTrue((chapter_dir / "chapter.json").exists())
        section_file = chapter_dir / "section-001-走廊.json"
        self.store.update_section_status(section_id, "generated")
        section_data = json.loads(section_file.read_text(encoding="utf-8"))
        self.assertEqual(section_data["status"], "generated")

        section_data = json.loads(section_file.read_text(encoding="utf-8"))
        version_file = project_dir / "versions" / "draft" / f"{version_id:04d}-粗稿.md"
        self.assertEqual(version_file.read_text(encoding="utf-8").strip(), "走廊尽头传来滴水声。")
        self.store.mark_version(version_id, "needs_edit")
        version_json = json.loads(version_file.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(version_json["status"], "needs_edit")
        self.assertNotIn("metadata_json", version_json)

        self.store.finalize_section(section_id, version_id)
        section_data = json.loads(section_file.read_text(encoding="utf-8"))
        version_json = json.loads(version_file.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(section_data["status"], "finalized")
        self.assertEqual(section_data["finalized_version_id"], version_id)
        self.assertEqual(version_json["status"], "final")

        self.store.unfinalize_section(section_id)
        section_data = json.loads(section_file.read_text(encoding="utf-8"))
        version_json = json.loads(version_file.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(section_data["status"], "review_pending")
        self.assertIsNone(section_data["finalized_version_id"])
        self.assertEqual(version_json["status"], "usable")

    def test_get_world_item_returns_project_scoped_item(self) -> None:
        project_id = self.store.create_project({"title": "资料项目"})
        other_project_id = self.store.create_project({"title": "其他项目"})
        item_id = self.store.save_world_item(
            project_id,
            {"kind": "character", "name": "林砚", "summary": "主角"},
        )

        item = self.store.get_world_item(project_id, item_id)

        self.assertEqual(item["name"], "林砚")
        self.assertIsNone(self.store.get_world_item(other_project_id, item_id))

    def test_list_finalized_section_versions_returns_ordered_final_text(self) -> None:
        project_id = self.store.create_project({"title": "章末记忆项目"})
        chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "章节"})
        first_id = self.store.save_section(chapter_id, {"number": 1, "title": "第一节"})
        second_id = self.store.save_section(chapter_id, {"number": 2, "title": "第二节"})
        self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": second_id,
                "kind": "draft",
                "label": "未定稿",
                "content": "未定稿正文",
            }
        )
        first_version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": first_id,
                "kind": "draft",
                "label": "第一节定稿",
                "content": "第一节正文",
            }
        )
        self.store.finalize_section(first_id, first_version_id)

        rows = self.store.list_finalized_section_versions(chapter_id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["section_id"], first_id)
        self.assertEqual(rows[0]["version_id"], first_version_id)
        self.assertEqual(rows[0]["content"], "第一节正文")

    def test_delete_world_item_removes_row_and_refreshes_synced_library(self) -> None:
        project_id = self.store.create_project({"title": "删除资料项目"})
        item_id = self.store.save_world_item(
            project_id,
            {"kind": "character", "name": "林砚", "summary": "主角"},
        )
        project_dir = self._project_dir(project_id)
        library_file = project_dir / "library" / "character" / f"{item_id:04d}-林砚.json"
        self.assertTrue(library_file.exists())

        self.store.delete_world_item(project_id, item_id)

        self.assertEqual(self.store.list_world_items(project_id), [])
        self.assertTrue((project_dir / "library").exists())

    def test_reset_outline_split_content_removes_chapters_and_auto_candidates_only(self) -> None:
        project_id = self.store.create_project({"title": "重置拆分项目"})
        chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "旧章节"})
        section_id = self.store.save_section(chapter_id, {"number": 1, "title": "旧小节"})
        self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "draft",
                "label": "旧正文",
                "content": "旧正文",
            }
        )
        manual_id = self.store.save_world_item(
            project_id,
            {
                "kind": "character",
                "name": "手动角色",
                "summary": "保留",
                "details": {"source": "manual"},
                "status": "active",
            },
        )
        auto_id = self.store.save_world_item(
            project_id,
            {
                "kind": "character",
                "name": "自动角色",
                "summary": "删除",
                "details": {"source": "outline_split"},
                "status": "candidate",
            },
        )

        self.store.reset_outline_split_content(project_id)

        self.assertEqual(self.store.list_chapters(project_id), [])
        self.assertEqual(self.store.list_versions(project_id), [])
        remaining_ids = {item["id"] for item in self.store.list_world_items(project_id)}
        self.assertIn(manual_id, remaining_ids)
        self.assertNotIn(auto_id, remaining_ids)

    def test_chapter_file_sync_removes_old_chapter_directories(self) -> None:
        project_id = self.store.create_project({"title": "章节镜像项目"})
        old_chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "旧章节"})
        project_dir = self._project_dir(project_id)
        old_chapter_dir = project_dir / "chapters" / "chapter-001-旧章节"
        self.assertTrue(old_chapter_dir.exists())

        self.store.reset_outline_split_content(project_id)
        self.store.save_chapter(project_id, {"number": 1, "title": "新章节"})

        self.assertIsNone(self.store.get_chapter(old_chapter_id))
        self.assertFalse(old_chapter_dir.exists())
        self.assertTrue((project_dir / "chapters" / "chapter-001-新章节").exists())

    def test_upsert_world_item_inserts_new_item_and_syncs_library(self) -> None:
        project_id = self.store.create_project({"title": "Upsert 新增项目"})

        item_id = self.store.upsert_world_item(
            project_id,
            {
                "kind": "character",
                "name": "林砚",
                "summary": "旧宅调查者",
                "details": {"motivation": "查明旧案"},
                "tags": "主角,调查",
                "status": "active",
            },
        )

        items = self.store.list_world_items(project_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], item_id)
        self.assertEqual(items[0]["summary"], "旧宅调查者")
        project_dir = self._project_dir(project_id)
        library_file = project_dir / "library" / "character" / f"{item_id:04d}-林砚.json"
        self.assertTrue(library_file.exists())

    def test_upsert_world_item_updates_same_kind_and_normalized_name(self) -> None:
        project_id = self.store.create_project({"title": "Upsert 更新项目"})
        item_id = self.store.upsert_world_item(
            project_id,
            {
                "kind": "character",
                "name": " Alice ",
                "summary": "原摘要",
                "details": {"identity": "侦探", "arc": "寻找真相"},
                "tags": "主角,调查",
                "status": "draft",
            },
        )

        updated_id = self.store.upsert_world_item(
            project_id,
            {
                "kind": "character",
                "name": "alice",
                "summary": "新摘要",
                "details": {"motivation": "保护朋友", "arc": ""},
                "tags": "调查,盟友",
                "status": "active",
            },
        )

        self.assertEqual(updated_id, item_id)
        items = self.store.list_world_items(project_id)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["summary"], "原摘要\n新摘要")
        self.assertEqual(item["tags"], "主角,调查,盟友")
        self.assertEqual(item["status"], "active")
        details = json.loads(item["details_json"])
        self.assertEqual(details["identity"], "侦探")
        self.assertEqual(details["arc"], "寻找真相")
        self.assertEqual(details["motivation"], "保护朋友")

    def test_outline_candidate_upsert_does_not_turn_manual_item_into_candidate(self) -> None:
        project_id = self.store.create_project({"title": "手动资料保留项目"})
        item_id = self.store.save_world_item(
            project_id,
            {
                "kind": "character",
                "name": "林砚",
                "summary": "用户手动维护",
                "details": {"source": "manual"},
                "status": "",
            },
        )

        updated_id = self.store.upsert_world_item(
            project_id,
            {
                "kind": "character",
                "name": "林砚",
                "summary": "来自拆分",
                "details": {"source": "outline_split"},
                "status": "candidate",
            },
        )

        self.assertEqual(updated_id, item_id)
        item = self.store.list_world_items(project_id)[0]
        self.assertEqual(item["status"], "")
        self.store.reset_outline_split_content(project_id)
        self.assertEqual([item["id"] for item in self.store.list_world_items(project_id)], [item_id])

    def test_upsert_world_item_keeps_same_name_different_kinds_separate(self) -> None:
        project_id = self.store.create_project({"title": "Upsert 类型项目"})

        character_id = self.store.upsert_world_item(
            project_id,
            {"kind": "character", "name": "旧宅", "summary": "代号旧宅的人"},
        )
        location_id = self.store.upsert_world_item(
            project_id,
            {"kind": "location", "name": " 旧宅 ", "summary": "真实地点"},
        )

        self.assertNotEqual(character_id, location_id)
        items = self.store.list_world_items(project_id)
        self.assertEqual(len(items), 2)
        summaries_by_kind = {item["kind"]: item["summary"] for item in items}
        self.assertEqual(summaries_by_kind["character"], "代号旧宅的人")
        self.assertEqual(summaries_by_kind["location"], "真实地点")

    def test_initialization_migrates_existing_sqlite_projects(self) -> None:
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    title, genre, style, target_readers, length_target, pov,
                    world_summary, character_brief, writing_style_guide,
                    global_concept, created_at, updated_at
                ) VALUES (?, '', '', '', '', '', ?, '', '', '', datetime('now'), datetime('now'))
                """,
                ("旧 SQLite 项目", "旧数据世界观"),
            )
            project_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        migrated_root = TEST_OUTPUT / f"{self.case_id}_migrated_projects"
        NovelStore(self.db_path, projects_root=migrated_root)
        project = NovelStore(self.db_path, projects_root=migrated_root).get_project(project_id)
        project_dir = find_project_path(project, migrated_root)

        self.assertIsNotNone(project_dir)
        self.assertTrue((project_dir / "project.json").exists())
        self.assertIn("旧数据世界观", (project_dir / "worldbook.md").read_text(encoding="utf-8"))

    def test_project_files_rebuild_sqlite_cache_after_database_is_changed(self) -> None:
        project_id = self.store.create_project(
            {
                "title": "文件源项目",
                "world_summary": "文件夹是真实数据源。",
                "global_concept": "删除数据库后仍能恢复。",
            }
        )
        item_id = self.store.save_world_item(
            project_id,
            {
                "kind": "character",
                "name": "林砚",
                "summary": "主角",
                "details": {"identity": "调查者", "chapter_memory": [{"chapter": 1, "event": "进入旧宅"}]},
                "tags": "主角",
                "status": "active",
            },
        )
        chapter_id = self.store.save_chapter(
            project_id,
            {"number": 1, "title": "旧宅", "outline": "进入旧宅。"},
        )
        section_id = self.store.save_section(
            chapter_id,
            {"number": 1, "title": "门厅", "goal": "找到线索", "status": "generated"},
        )
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "draft",
                "label": "定稿",
                "content": "门厅里有潮湿的脚印。",
                "metadata": {"retrieved_world_item_ids": [item_id]},
                "status": "usable",
            }
        )
        self.store.finalize_section(section_id, version_id)

        rebuilt_db = TEST_OUTPUT / f"{self.case_id}_rebuilt.db"
        rebuilt = NovelStore(rebuilt_db, projects_root=self.projects_root)

        project = rebuilt.get_project(project_id)
        self.assertEqual(project["title"], "文件源项目")
        self.assertEqual(project["global_concept"], "删除数据库后仍能恢复。")
        items = rebuilt.list_world_items(project_id)
        self.assertEqual([item["id"] for item in items], [item_id])
        details = json.loads(items[0]["details_json"])
        self.assertEqual(details["chapter_memory"][0]["event"], "进入旧宅")
        chapters = rebuilt.list_chapters(project_id)
        self.assertEqual([chapter["id"] for chapter in chapters], [chapter_id])
        sections = rebuilt.list_sections(chapter_id)
        self.assertEqual([section["id"] for section in sections], [section_id])
        self.assertEqual(sections[0]["status"], "finalized")
        self.assertEqual(sections[0]["finalized_version_id"], version_id)
        versions = rebuilt.list_versions(project_id, section_id=section_id)
        self.assertEqual([version["id"] for version in versions], [version_id])
        self.assertIn("门厅里有潮湿的脚印。", versions[0]["content"])
        self.assertEqual(json.loads(versions[0]["metadata_json"])["retrieved_world_item_ids"], [item_id])

    def test_project_files_rebuild_accepts_legacy_details_json(self) -> None:
        project_id = self.store.create_project({"title": "旧详情字段项目"})
        item_id = self.store.save_world_item(
            project_id,
            {
                "kind": "character",
                "name": "旧角色",
                "summary": "旧格式",
                "details_json": {"identity": "旧格式字段"},
            },
        )
        project_dir = self._project_dir(project_id)
        library_file = project_dir / "library" / "character" / f"{item_id:04d}-旧角色.json"
        data = json.loads(library_file.read_text(encoding="utf-8"))
        data.pop("details", None)
        data["details_json"] = {"identity": "旧格式字段", "chapter_memory": ["保留"]}
        library_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        legacy_db = TEST_OUTPUT / f"{self.case_id}_legacy_rebuild.db"
        rebuilt = NovelStore(legacy_db, projects_root=self.projects_root)

        item = rebuilt.list_world_items(project_id)[0]
        details = json.loads(item["details_json"])
        self.assertEqual(details["identity"], "旧格式字段")
        self.assertEqual(details["chapter_memory"], ["保留"])

    def test_project_files_rebuild_survives_duplicate_world_item_id(self) -> None:
        # 复制项目文件夹时容易沿用同一个全局 world_items.id；重建缓存不应整库崩溃，
        # 两个不同项目的不同实体都要保留（冲突的副本重新分配 id）。
        project_a = self.store.create_project({"title": "项目甲"})
        project_b = self.store.create_project({"title": "项目乙"})
        item_a = self.store.save_world_item(
            project_a, {"kind": "character", "name": "甲角色", "summary": "甲"}
        )
        item_b = self.store.save_world_item(
            project_b, {"kind": "character", "name": "乙角色", "summary": "乙"}
        )
        self.assertNotEqual(item_a, item_b)

        dir_b = self._project_dir(project_b)
        old_file = dir_b / "library" / "character" / f"{item_b:04d}-乙角色.json"
        data = json.loads(old_file.read_text(encoding="utf-8"))
        data["id"] = item_a  # 制造与项目甲条目相同的全局 id
        old_file.unlink()
        (dir_b / "library" / "character" / f"{item_a:04d}-乙角色.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        rebuilt_db = TEST_OUTPUT / f"{self.case_id}_dup_rebuild.db"
        rebuilt = NovelStore(rebuilt_db, projects_root=self.projects_root)

        names_a = {it["name"] for it in rebuilt.list_world_items(project_a)}
        names_b = {it["name"] for it in rebuilt.list_world_items(project_b)}
        self.assertIn("甲角色", names_a)
        self.assertIn("乙角色", names_b)

    def _project_dir(self, project_id: int) -> Path:
        project = self.store.get_project(project_id)
        project_dir = find_project_path(project, self.projects_root)
        self.assertIsNotNone(project_dir)
        return project_dir


if __name__ == "__main__":
    unittest.main()
