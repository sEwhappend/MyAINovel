import unittest
import uuid
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_ai_novel import exporter
from my_ai_novel.storage import NovelStore


TEST_OUTPUT = ROOT / "test-output"


class ExporterTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_OUTPUT.mkdir(exist_ok=True)
        self.db_path = TEST_OUTPUT / f"{self._testMethodName}_{uuid.uuid4().hex}.db"
        self.projects_root = TEST_OUTPUT / f"{self._testMethodName}_{uuid.uuid4().hex}_projects"
        self.store = NovelStore(self.db_path, projects_root=self.projects_root)

    def tearDown(self) -> None:
        pass

    def test_export_full_book_docx_writes_only_finalized_sections(self) -> None:
        project_id = self.store.create_project({"title": "雨夜旧宅"})
        chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "旧宅入口"})

        finalized_section_id = self.store.save_section(
            chapter_id,
            {"number": 1, "title": "走廊", "status": "generated"},
        )
        finalized_version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": finalized_section_id,
                "kind": "draft",
                "label": "定稿",
                "content": "定稿正文第一段\n定稿正文第二段",
            }
        )
        self.store.finalize_section(finalized_section_id, finalized_version_id)

        draft_section_id = self.store.save_section(
            chapter_id,
            {"number": 2, "title": "未定稿小节", "status": "generated"},
        )
        self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": draft_section_id,
                "kind": "draft",
                "label": "草稿",
                "content": "未定稿正文不应出现",
            }
        )

        finalized_without_version_id = self.store.save_section(
            chapter_id,
            {"number": 3, "title": "缺少定稿版本", "status": "finalized"},
        )
        self.assertIsNone(self.store.get_section(finalized_without_version_id)["finalized_version_id"])

        docx_path = exporter.export_full_book_docx(self.store, project_id)

        self.assertEqual(docx_path.parent.name, "exports")
        self.assertTrue(docx_path.exists())
        self.assertTrue(str(docx_path).startswith(str(self.projects_root)))

        with ZipFile(docx_path) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")

        self.assertIn("雨夜旧宅", document_xml)
        self.assertIn("第1章 旧宅入口", document_xml)
        self.assertIn("第1节 走廊", document_xml)
        self.assertIn("定稿正文第一段", document_xml)
        self.assertIn("定稿正文第二段", document_xml)
        self.assertNotIn("未定稿正文不应出现", document_xml)
        self.assertNotIn("缺少定稿版本", document_xml)

    def test_export_escapes_docx_xml_text(self) -> None:
        project_id = self.store.create_project({"title": "A&B <书>"})
        chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "符号"})
        section_id = self.store.save_section(chapter_id, {"number": 1, "title": "正文"})
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "draft",
                "label": "定稿",
                "content": "她说：A&B <ok>",
            }
        )
        self.store.finalize_section(section_id, version_id)

        docx_path = exporter.export_full_book_docx(self.store, project_id)

        with ZipFile(docx_path) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")

        self.assertIn("A&amp;B &lt;书&gt;", document_xml)
        self.assertIn("她说：A&amp;B &lt;ok&gt;", document_xml)

    def test_export_uses_manual_chapter_order(self) -> None:
        project_id = self.store.create_project({"title": "排序导出"})
        first_chapter_id = self.store.save_chapter(project_id, {"number": 1, "title": "原第一章"})
        second_chapter_id = self.store.save_chapter(project_id, {"number": 2, "title": "原第二章"})
        first_section_id = self.store.save_section(first_chapter_id, {"number": 1, "title": "第一节"})
        second_section_id = self.store.save_section(second_chapter_id, {"number": 1, "title": "第二节"})
        first_version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": first_chapter_id,
                "section_id": first_section_id,
                "kind": "draft",
                "label": "定稿",
                "content": "第一章正文",
            }
        )
        second_version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": second_chapter_id,
                "section_id": second_section_id,
                "kind": "draft",
                "label": "定稿",
                "content": "第二章正文",
            }
        )
        self.store.finalize_section(first_section_id, first_version_id)
        self.store.finalize_section(second_section_id, second_version_id)

        self.store.move_chapter(project_id, second_chapter_id, -1)
        docx_path = exporter.export_full_book_docx(self.store, project_id)

        with ZipFile(docx_path) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")

        self.assertLess(document_xml.index("原第二章"), document_xml.index("原第一章"))

if __name__ == "__main__":
    unittest.main()
