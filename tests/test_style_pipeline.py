import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TEST_OUTPUT = ROOT / "test-output"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_ai_novel import style_library
from my_ai_novel.llm import LLMError
from my_ai_novel.pipeline import NovelPipeline, compact_style_profile
from my_ai_novel.prompts import AGENT_SYSTEM_PROMPTS


def _long_text() -> str:
    return "\n".join(f"第{i}段。他推开门，雨水灌进来。" + "字" * 60 for i in range(40))


class StyleFakeLLM:
    """流式打桩：文风分析现在走 stream_text；按 payload 关键字区分 Map / Reduce。"""

    config = {"chat_model": "fake-chat", "review_model": "fake-review"}

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _result_for(self, messages):
        user = next((m["content"] for m in messages if m.get("role") == "user"), "")
        if "chunk_observations" in user:
            self.calls.append("style_profile_builder")
            return {
                "summary": "短句快节奏，近距离第三人称",
                "sentence": {"length": "短句"},
                "anti_ai_rules": ["避免段尾总结主题"],
            }
        self.calls.append("style_analyzer_chunk")
        return {
            "sentence": {"length": "短句", "rhythm": "快"},
            "anti_ai_rules": ["避免段尾总结主题"],
        }

    def stream_text(self, model, messages, on_delta, max_tokens=None):
        text = json.dumps(self._result_for(messages), ensure_ascii=False)
        on_delta(text)
        return text


class RecordingStore:
    def __init__(self) -> None:
        self.logs: list[dict] = []

    def save_llm_call_log(self, data) -> int:
        self.logs.append(data)
        return len(self.logs)


def _pipeline(llm=None, store=None) -> NovelPipeline:
    pipe = NovelPipeline(store=store, llm=llm or StyleFakeLLM())
    pipe.style_retry_delays = [0]  # no real sleeping in tests
    return pipe


class StylePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_OUTPUT.mkdir(exist_ok=True)
        self.root = TEST_OUTPUT / f"styles-{uuid.uuid4().hex}"
        self.style_name = "测试文风"

    def test_analyze_style_chunk_calls_agent(self) -> None:
        pipe = _pipeline()
        result = pipe.analyze_style_chunk("他推开门，雨水灌进来。")
        self.assertIn("sentence", result)
        self.assertIn("style_analyzer_chunk", pipe.llm.calls)

    def test_build_style_profile_attaches_metrics_and_source(self) -> None:
        pipe = _pipeline()
        profile = pipe.build_style_profile(
            [{"sentence": {"length": "短句"}}], {"avg_sentence_len": 14.7, "lexical_diversity": 0.6}
        )
        self.assertEqual(profile["metrics"]["avg_sentence_len"], 14.7)
        self.assertEqual(profile["source"], "file_ingest")
        self.assertEqual(profile["version"], 1)
        # 倒推的采样参数
        self.assertIn("sampling", profile)
        self.assertIn("temperature", profile["sampling"])
        self.assertIn("frequency_penalty", profile["sampling"])

    def test_compact_style_profile_keeps_sampling(self) -> None:
        compact = compact_style_profile({"summary": "x", "sampling": {"temperature": 0.9}})
        self.assertIn("sampling", compact)

    def test_analyze_style_samples_returns_profile_and_persists_to_library(self) -> None:
        pipe = _pipeline()
        progress: list[int] = []
        samples = [{"name": "a.txt", "text": _long_text()}]
        profile = pipe.analyze_style_samples(
            self.style_name, samples, sample_count=4, root=self.root, on_progress=progress.append
        )
        self.assertEqual(profile["source_files"][0]["name"], "a.txt")
        self.assertTrue(profile["source_files"][0]["sha1"])
        self.assertTrue(profile["metrics"])
        self.assertIn("style_profile_builder", pipe.llm.calls)
        self.assertGreaterEqual(pipe.llm.calls.count("style_analyzer_chunk"), 1)
        self.assertTrue(progress)
        self.assertEqual(progress[-1], pipe.llm.calls.count("style_analyzer_chunk"))
        # persisted to the global style library
        self.assertEqual(
            style_library.load_style_profile(self.style_name, self.root)["summary"], profile["summary"]
        )

    def test_analyze_style_samples_cache_hit_skips_llm(self) -> None:
        pipe = _pipeline()
        samples = [{"name": "a.txt", "text": _long_text()}]
        pipe.analyze_style_samples(self.style_name, samples, sample_count=4, root=self.root)
        calls_after_first = len(pipe.llm.calls)
        cached = pipe.analyze_style_samples(self.style_name, samples, sample_count=4, root=self.root)
        self.assertEqual(len(pipe.llm.calls), calls_after_first)
        self.assertEqual(cached["summary"], "短句快节奏，近距离第三人称")

    def test_analyze_style_samples_no_persist_without_name(self) -> None:
        pipe = _pipeline()
        samples = [{"name": "a.txt", "text": _long_text()}]
        profile = pipe.analyze_style_samples("", samples, sample_count=3, persist=False)
        self.assertTrue(profile["metrics"])
        self.assertEqual(profile["source_files"][0]["name"], "a.txt")

    def test_analyze_style_samples_retries_transient_connection_reset(self) -> None:
        class FlakyLLM(StyleFakeLLM):
            def __init__(self) -> None:
                super().__init__()
                self.failed_once = False

            def chat_json(self, agent_name, messages, schema_hint=None):
                if agent_name == "style_analyzer_chunk" and not self.failed_once:
                    self.failed_once = True
                    raise LLMError("连接失败：连接被远程主机重置或中断（[WinError 10054]）")
                return super().chat_json(agent_name, messages, schema_hint)

        pipe = _pipeline(FlakyLLM())
        profile = pipe.analyze_style_samples(
            self.style_name, [{"name": "a.txt", "text": _long_text()}], sample_count=2, root=self.root
        )
        self.assertTrue(profile["summary"])  # recovered after a transient reset

    def test_analyze_style_logs_calls_including_failures(self) -> None:
        class FlakyLLM(StyleFakeLLM):
            def __init__(self) -> None:
                super().__init__()
                self.failed = False

            def stream_text(self, model, messages, on_delta, max_tokens=None):
                user = next((m["content"] for m in messages if m.get("role") == "user"), "")
                if "chunk_observations" not in user and not self.failed:
                    self.failed = True
                    raise LLMError("连接失败：连接被远程主机重置或中断（[WinError 10054]）")
                return super().stream_text(model, messages, on_delta, max_tokens)

        store = RecordingStore()
        pipe = _pipeline(FlakyLLM(), store=store)
        pipe.analyze_style_samples(
            self.style_name, [{"name": "a.txt", "text": _long_text()}], sample_count=2, root=self.root
        )
        failures = [log for log in store.logs if not log.get("success")]
        successes = [log for log in store.logs if log.get("success")]
        self.assertTrue(failures, "transient reset should be logged")
        self.assertIn("重置", failures[0].get("error", ""))
        self.assertIn("style_analyzer_chunk", failures[0].get("agent_name", ""))
        self.assertTrue(successes)
        self.assertTrue(any(log.get("agent_name") == "style_profile_builder" for log in store.logs))

    def test_analyze_style_streams_deltas(self) -> None:
        pipe = _pipeline()
        deltas: list[str] = []
        pipe.analyze_style_samples(
            self.style_name,
            [{"name": "a.txt", "text": _long_text()}],
            sample_count=2,
            root=self.root,
            on_delta=deltas.append,
        )
        self.assertTrue(deltas)  # streamed content was forwarded
        self.assertTrue(any("summary" in d or "sentence" in d for d in deltas))

    def test_analyze_style_without_store_does_not_crash(self) -> None:
        pipe = _pipeline()  # store=None
        profile = pipe.analyze_style_samples(
            self.style_name, [{"name": "a.txt", "text": _long_text()}], sample_count=2, root=self.root
        )
        self.assertTrue(profile["summary"])

    def test_estimate_style_cost_counts_chunks_and_tokens(self) -> None:
        cost = _pipeline().estimate_style_cost([_long_text()], sample_count=4)
        self.assertGreater(cost["sampled_chunks"], 0)
        self.assertGreater(cost["approx_input_tokens"], 0)

    def test_estimate_style_cost_empty(self) -> None:
        self.assertEqual(
            _pipeline().estimate_style_cost([]),
            {"sampled_chunks": 0, "approx_input_tokens": 0},
        )


class StyleProfileInjectionTests(unittest.TestCase):
    def test_compact_style_profile_keeps_core_drops_excerpts_and_sources(self) -> None:
        profile = {
            "summary": "短句快节奏",
            "sentence": {"length": "短"},
            "anti_ai_rules": ["避免段尾总结主题"],
            "metrics": {"avg_sentence_len": 14.75},
            "sample_excerpts": [{"text": "原文片段"}],
            "source_files": [{"name": "a.txt", "sha1": "x"}],
            "version": 1,
            "source": "file_ingest",
        }
        compact = compact_style_profile(profile)
        self.assertEqual(compact["summary"], "短句快节奏")
        self.assertIn("metrics", compact)
        self.assertIn("anti_ai_rules", compact)
        self.assertNotIn("sample_excerpts", compact)
        self.assertNotIn("source_files", compact)

    def test_compact_style_profile_empty(self) -> None:
        self.assertEqual(compact_style_profile({}), {})
        self.assertEqual(compact_style_profile(None), {})

    def test_with_style_profile_injects_when_project_has_style_ref(self) -> None:
        pipe = _pipeline()
        profile = {
            "summary": "短句",
            "anti_ai_rules": ["避免段尾总结"],
            "sample_excerpts": [{"text": "原文片段"}],
            "source_files": [{"name": "a.txt"}],
        }
        with patch("my_ai_novel.style_library.load_style_profile", return_value=profile) as loader:
            out = pipe._with_style_profile({"project": {"id": 1, "style_ref": "测试文风"}, "section": {}})
        loader.assert_called_once_with("测试文风")
        self.assertEqual(out["style_profile"]["summary"], "短句")
        self.assertNotIn("sample_excerpts", out["style_profile"])
        self.assertNotIn("source_files", out["style_profile"])

    def test_with_style_profile_noop_without_style_ref(self) -> None:
        pipe = _pipeline()
        out = pipe._with_style_profile({"project": {"id": 1, "style_ref": ""}, "section": {}})
        self.assertNotIn("style_profile", out)

    def test_with_style_profile_noop_without_project(self) -> None:
        pipe = _pipeline()
        out = pipe._with_style_profile({"section": {}})
        self.assertNotIn("style_profile", out)

    def test_style_sampling_overrides_from_project(self) -> None:
        pipe = _pipeline()
        profile = {"sampling": {"temperature": 0.95, "top_p": 0.93, "top_k": 0, "frequency_penalty": 0.4}}
        with patch("my_ai_novel.style_library.load_style_profile", return_value=profile):
            overrides = pipe._style_sampling_overrides({"id": 1, "style_ref": "轻小说体"})
        self.assertEqual(overrides["temperature"], 0.95)
        self.assertEqual(overrides["frequency_penalty"], 0.4)

    def test_style_sampling_overrides_empty_without_ref(self) -> None:
        pipe = _pipeline()
        self.assertEqual(pipe._style_sampling_overrides({"id": 1, "style_ref": ""}), {})
        self.assertEqual(pipe._style_sampling_overrides(None), {})

    def test_style_prompts_reference_style_profile(self) -> None:
        for agent in ("draft_writer", "reviewer", "rewriter"):
            self.assertIn("style_profile", AGENT_SYSTEM_PROMPTS[agent])

    def test_style_profile_schema_has_lightnovel_dimensions(self) -> None:
        from my_ai_novel.prompts import SCHEMA_HINTS

        builder = SCHEMA_HINTS["style_profile_builder"]
        self.assertIn("pacing", builder)
        self.assertIn("voice_distinction", builder["dialogue"])
        self.assertIn("ratio_guideline", builder["dialogue"])
        self.assertIn("onomatopoeia", builder["sentence"])
        self.assertIn("setting_release", builder["description"])
        chunk = SCHEMA_HINTS["style_analyzer_chunk"]
        self.assertIn("dialogue", chunk)
        self.assertIn("banter", chunk["dialogue"])

    def test_compact_style_profile_keeps_description_and_pacing(self) -> None:
        profile = {
            "summary": "x",
            "description": {"density": "轻描写"},
            "pacing": {"hook": "章末钩子"},
            "punctuation_conventions": {"ellipsis": "……成对"},
            "sample_excerpts": [{"text": "原文片段"}],
        }
        compact = compact_style_profile(profile)
        self.assertIn("description", compact)
        self.assertIn("pacing", compact)
        self.assertIn("punctuation_conventions", compact)
        self.assertNotIn("sample_excerpts", compact)

    def test_style_analyzer_prompt_mentions_craft_concepts(self) -> None:
        builder = AGENT_SYSTEM_PROMPTS["style_profile_builder"]
        for keyword in ("视点", "说明"):
            self.assertIn(keyword, builder)


if __name__ == "__main__":
    unittest.main()
