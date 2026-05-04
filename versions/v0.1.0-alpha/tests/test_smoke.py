import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class SmokeTests(unittest.TestCase):
    def test_package_imports(self) -> None:
        import my_ai_novel

        self.assertEqual(my_ai_novel.__version__, "0.1.0")

    def test_app_shell_has_title(self) -> None:
        from my_ai_novel.app import APP_TITLE, NovelApp

        app = NovelApp()
        self.assertEqual(APP_TITLE, "My AI Novel")
        self.assertEqual(app.title, APP_TITLE)


if __name__ == "__main__":
    unittest.main()
