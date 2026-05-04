import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_ai_novel.storage import NovelStore


TEST_OUTPUT = ROOT / "test-output"


class VersioningTests(unittest.TestCase):
    def test_finalize_and_unfinalize(self) -> None:
        TEST_OUTPUT.mkdir(exist_ok=True)
        store = NovelStore(TEST_OUTPUT / f"versioning_{uuid.uuid4().hex}.db")
        project_id = store.create_project({"title": "测试"})
        chapter_id = store.save_chapter(project_id, {"number": 1, "title": "一"})
        section_id = store.save_section(chapter_id, {"number": 1, "title": "一节"})
        version_id = store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "draft",
                "content": "正文",
            }
        )
        store.finalize_section(section_id, version_id)
        self.assertEqual(store.get_section(section_id)["status"], "finalized")
        self.assertEqual(store.get_version(version_id)["status"], "final")
        store.unfinalize_section(section_id)
        self.assertEqual(store.get_section(section_id)["status"], "review_pending")
        self.assertEqual(store.get_version(version_id)["status"], "usable")


if __name__ == "__main__":
    unittest.main()
