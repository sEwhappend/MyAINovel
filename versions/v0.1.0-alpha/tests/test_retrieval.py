import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_ai_novel.retrieval import retrieve_context
from my_ai_novel.storage import NovelStore


TEST_OUTPUT = ROOT / "test-output"


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_OUTPUT.mkdir(exist_ok=True)
        self.store = NovelStore(TEST_OUTPUT / f"retrieval_{uuid.uuid4().hex}.db")
        self.project_id = self.store.create_project({"title": "测试"})

    def test_context_includes_keyword_and_forbidden_items(self) -> None:
        self.store.save_world_item(
            self.project_id,
            {"kind": "character", "name": "林砚", "summary": "旧宅调查者", "tags": "旧宅"},
        )
        self.store.save_world_item(
            self.project_id,
            {"kind": "forbidden", "name": "真相", "summary": "不要提前揭示父亲失踪真相"},
        )
        pack = retrieve_context(self.store, self.project_id, None, None, "林砚进入旧宅")
        self.assertEqual(pack["long_term"][0]["name"], "林砚")
        self.assertEqual(pack["forbidden"][0]["kind"], "forbidden")
        self.assertIn("向量检索未启用", pack["retrieval_notes"][0])

    def test_context_prioritizes_character_and_organization_for_writing(self) -> None:
        for kind, name in [
            ("rule", "共同规则"),
            ("timeline_event", "共同时间线"),
            ("location", "共同地点"),
            ("foreshadowing", "共同伏笔"),
            ("character", "共同角色"),
            ("organization", "共同组织"),
        ]:
            self.store.save_world_item(
                self.project_id,
                {"kind": kind, "name": name, "summary": "共同线索", "tags": "共同"},
            )

        pack = retrieve_context(self.store, self.project_id, None, None, "共同")
        kinds = [item["kind"] for item in pack["long_term"]]

        self.assertEqual(set(kinds[:2]), {"organization", "character"})
        self.assertEqual(set(kinds[2:5]), {"foreshadowing", "location", "timeline_event"})
        self.assertEqual(kinds[5], "rule")


if __name__ == "__main__":
    unittest.main()
