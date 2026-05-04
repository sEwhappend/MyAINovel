import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TEST_OUTPUT = ROOT / "test-output"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class SmokeTests(unittest.TestCase):
    def test_package_imports(self) -> None:
        import my_ai_novel

        self.assertEqual(my_ai_novel.__version__, "0.1.0")

    def test_app_shell_has_title(self) -> None:
        from my_ai_novel.app import APP_TITLE, ApplicationServices, NovelApp
        from my_ai_novel.llm import LLMClient
        from my_ai_novel.models import DEFAULT_LLM_CONFIG
        from my_ai_novel.pipeline import NovelPipeline
        from my_ai_novel.storage import NovelStore

        case_id = f"{self._testMethodName}_{uuid.uuid4().hex}"
        store = NovelStore(
            TEST_OUTPUT / f"{case_id}.db",
            projects_root=TEST_OUTPUT / f"{case_id}_projects",
        )
        llm = LLMClient(DEFAULT_LLM_CONFIG)
        services = ApplicationServices(store=store, llm=llm, pipeline=NovelPipeline(store, llm))

        app = NovelApp(services)
        self.assertEqual(APP_TITLE, "My AI Novel")
        self.assertEqual(app.title, APP_TITLE)


if __name__ == "__main__":
    unittest.main()
