import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_ai_novel.review import build_rewrite_request, validate_review_issues


class ReviewTests(unittest.TestCase):
    def test_validate_review_issues_normalizes_unknowns(self) -> None:
        issues = validate_review_issues(
            {"issues": [{"type": "unknown", "severity": "bad", "description": "慢"}]}
        )
        self.assertEqual(issues[0]["type"], "pacing")
        self.assertEqual(issues[0]["severity"], "medium")

    def test_build_rewrite_request_preserves_text(self) -> None:
        request = build_rewrite_request({"title": "走廊"}, "原文", [], "只改对白", ["保留句"])
        self.assertEqual(request["rewrite_mode"], "只改对白")
        self.assertEqual(request["preserve"], ["保留句"])

    def test_build_rewrite_request_includes_optional_direction(self) -> None:
        request = build_rewrite_request(
            {"title": "走廊"},
            "原文",
            [],
            "增强冲突",
            [],
            "让女主语气更冷，保留第三段",
        )

        self.assertEqual(request["rewrite_direction"], "让女主语气更冷，保留第三段")


if __name__ == "__main__":
    unittest.main()
