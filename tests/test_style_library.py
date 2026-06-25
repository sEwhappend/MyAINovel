import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TEST_OUTPUT = ROOT / "test-output"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_ai_novel import style_library


class StyleLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_OUTPUT.mkdir(exist_ok=True)
        self.root = TEST_OUTPUT / f"styles-{uuid.uuid4().hex}"

    def test_create_and_list_styles(self) -> None:
        self.assertEqual(style_library.list_styles(self.root), [])
        style_library.create_style("轻小说体", self.root)
        styles = style_library.list_styles(self.root)
        self.assertEqual([s["name"] for s in styles], ["轻小说体"])
        self.assertEqual(styles[0]["sample_count"], 0)
        self.assertFalse(styles[0]["has_profile"])

    def test_sample_roundtrip_and_count(self) -> None:
        style_library.create_style("风A", self.root)
        style_library.write_style_sample(
            "风A", {"id": "sample-001", "title": "样书", "sha1": "abc", "char_count": 10}, "他推开门。", self.root
        )
        samples = style_library.load_style_samples("风A", self.root)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["sha1"], "abc")
        self.assertIn("他推开门", style_library.load_style_sample_text("风A", "sample-001", self.root))
        self.assertEqual(style_library.list_styles(self.root)[0]["sample_count"], 1)

    def test_delete_sample(self) -> None:
        style_library.create_style("风A", self.root)
        style_library.write_style_sample("风A", {"id": "sample-001"}, "正文。", self.root)
        style_library.delete_style_sample("风A", "sample-001", self.root)
        self.assertEqual(style_library.load_style_samples("风A", self.root), [])

    def test_profile_roundtrip(self) -> None:
        style_library.create_style("风A", self.root)
        profile = {"version": 1, "summary": "短句", "metrics": {"avg_sentence_len": 14.0}}
        style_library.write_style_profile("风A", profile, self.root)
        loaded = style_library.load_style_profile("风A", self.root)
        self.assertEqual(loaded["summary"], "短句")
        self.assertTrue(style_library.list_styles(self.root)[0]["has_profile"])

    def test_load_profile_missing_returns_empty(self) -> None:
        self.assertEqual(style_library.load_style_profile("不存在", self.root), {})

    def test_delete_style_removes_everything(self) -> None:
        style_library.create_style("风A", self.root)
        style_library.write_style_profile("风A", {"summary": "x"}, self.root)
        style_library.delete_style("风A", self.root)
        self.assertEqual(style_library.list_styles(self.root), [])
        self.assertEqual(style_library.load_style_profile("风A", self.root), {})


if __name__ == "__main__":
    unittest.main()
