import json
import sys
import threading
import time
import unittest
from http.client import RemoteDisconnected
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_ai_novel.llm import LLMClient, LLMError, parse_json_response
from my_ai_novel.models import DEFAULT_LLM_CONFIG
from my_ai_novel.prompts import build_messages


class FakeResponse:
    def __init__(self, payload) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class TimeoutResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        raise TimeoutError("The read operation timed out")


class FakeStreamResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self.lines)


class LLMTests(unittest.TestCase):
    def test_parse_json_response_strips_code_fence(self) -> None:
        self.assertEqual(parse_json_response("```json\n{\"ok\": true}\n```"), {"ok": True})

    def test_parse_json_response_rejects_non_json(self) -> None:
        with self.assertRaises(LLMError):
            parse_json_response("not json")

    def test_default_api_type_is_responses(self) -> None:
        self.assertEqual(DEFAULT_LLM_CONFIG["api_type"], "responses")
        self.assertEqual(LLMClient({"api_type": "responses"}).api_type, "responses")

    def test_responses_api_is_default_and_parses_output_text(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"output_text": "{\"result\": \"ok\"}"})

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "chat_model": "writer",
                "max_tokens": 1234,
            }
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            result = client.chat_json("draft_writer", [{"role": "user", "content": "x"}])

        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(captured["url"], "https://example.test/v1/responses")
        self.assertEqual(captured["payload"]["model"], "writer")
        self.assertEqual(captured["payload"]["max_output_tokens"], 1234)
        self.assertEqual(captured["payload"]["input"], [{"role": "user", "content": "x"}])

    def test_responses_api_parses_output_content_text(self) -> None:
        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "chat_model": "writer",
            }
        )
        response = {
            "output": [
                {"type": "reasoning", "content": []},
                {"type": "message", "content": [{"type": "output_text", "text": "{\"result\":\"ok\"}"}]},
            ]
        }
        with patch("urllib.request.urlopen", return_value=FakeResponse(response)):
            result = client.chat_json("draft_writer", [{"role": "user", "content": "x"}])

        self.assertEqual(result, {"result": "ok"})

    def test_stream_text_reads_responses_sse_deltas(self) -> None:
        captured = {}
        lines = [
            'data: {"type":"response.output_text.delta","delta":"你"}\n'.encode("utf-8"),
            b"\n",
            'data: {"type":"response.output_text.delta","delta":"好"}\n'.encode("utf-8"),
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeStreamResponse(lines)

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "responses",
                "chat_model": "writer",
            }
        )
        chunks = []
        with patch("urllib.request.urlopen", fake_urlopen):
            text = client.stream_text("writer", [{"role": "user", "content": "x"}], chunks.append)

        self.assertEqual(text, "你好")
        self.assertEqual(chunks, ["你", "好"])
        self.assertEqual(captured["url"], "https://example.test/v1/responses")
        self.assertTrue(captured["payload"]["stream"])
        self.assertEqual(captured["headers"].get("Accept"), "text/event-stream")

    def test_stream_text_reads_chat_completions_sse_deltas(self) -> None:
        captured = {}
        lines = [
            'data: {"choices":[{"delta":{"content":"完"}}]}\n'.encode("utf-8"),
            b"\n",
            'data: {"choices":[{"delta":{"content":"整正文"}}]}\n'.encode("utf-8"),
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeStreamResponse(lines)

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "chat_completions",
                "chat_model": "writer",
                "top_k": 40,
                "presence_penalty": 0.3,
                "frequency_penalty": 0.2,
            }
        )
        chunks = []
        with patch("urllib.request.urlopen", fake_urlopen):
            text = client.stream_text("writer", [{"role": "user", "content": "x"}], chunks.append)

        self.assertEqual(text, "完整正文")
        self.assertEqual(chunks, ["完", "整正文"])
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["headers"].get("Accept"), "text/event-stream")
        self.assertTrue(captured["payload"]["stream"])
        self.assertNotIn("response_format", captured["payload"])
        self.assertNotIn("top_k", captured["payload"])
        self.assertNotIn("presence_penalty", captured["payload"])

    def test_stream_text_retries_524_before_first_delta(self) -> None:
        attempts = []
        retry_events = []
        lines = [
            'data: {"type":"response.output_text.delta","delta":"正文"}\n'.encode("utf-8"),
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]

        def fake_urlopen(req, timeout):
            attempts.append(req.full_url)
            if len(attempts) == 1:
                raise HTTPError(req.full_url, 524, "Timeout", {}, BytesIO(b"error code: 524"))
            return FakeStreamResponse(lines)

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "responses",
                "chat_model": "writer",
            }
        )
        cancel_event = threading.Event()
        client.configure_retry_until_cancel(
            cancel_event,
            lambda attempt, delay, error: retry_events.append((attempt, delay, error)),
            delays=[0],
        )
        chunks = []

        with patch("urllib.request.urlopen", fake_urlopen):
            text = client.stream_text("writer", [{"role": "user", "content": "x"}], chunks.append)

        self.assertEqual(text, "正文")
        self.assertEqual(chunks, ["正文"])
        self.assertEqual(len(attempts), 2)
        self.assertEqual(retry_events[0][0], 1)
        self.assertIn("HTTP 524", retry_events[0][2])

    def test_stream_text_does_not_retry_after_partial_delta(self) -> None:
        attempts = []
        lines = [
            'data: {"type":"response.output_text.delta","delta":"半"}\n'.encode("utf-8"),
            b"\n",
        ]

        class BrokenStreamResponse(FakeStreamResponse):
            def __iter__(self):
                yield from self.lines
                raise TimeoutError("The read operation timed out")

        def fake_urlopen(req, timeout):
            attempts.append(req.full_url)
            return BrokenStreamResponse(lines)

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "responses",
                "chat_model": "writer",
            }
        )
        client.configure_retry_until_cancel(threading.Event(), delays=[0])
        chunks = []

        with patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(LLMError):
                client.stream_text("writer", [{"role": "user", "content": "x"}], chunks.append)

        self.assertEqual(chunks, ["半"])
        self.assertEqual(len(attempts), 1)

    def test_chat_sends_writing_parameters(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["timeout"] = timeout
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse(
                {"choices": [{"message": {"content": "{\"result\": \"ok\"}"}}]}
            )

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "chat_completions",
                "chat_model": "writer",
                "max_tokens": 1234,
                "temperature": 0.8,
                "top_p": 0.92,
                "top_k": 40,
                "presence_penalty": 0.3,
                "frequency_penalty": 0.2,
                "timeout_seconds": 7,
            }
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            result = client.chat_json("draft_writer", [{"role": "user", "content": "x"}])
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(captured["payload"]["max_tokens"], 1234)
        self.assertEqual(captured["payload"]["temperature"], 0.8)
        self.assertEqual(captured["payload"]["top_p"], 0.92)
        self.assertEqual(captured["payload"]["top_k"], 40)
        self.assertEqual(captured["payload"]["presence_penalty"], 0.3)
        self.assertEqual(captured["payload"]["frequency_penalty"], 0.2)

    def test_chat_json_merges_schema_hint_into_first_system_message(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"output_text": "{\"result\": \"ok\"}"})

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "chat_model": "writer",
            }
        )
        messages = [
            {"role": "system", "content": "fixed agent"},
            {"role": "system", "content": "project constraints"},
            {"role": "user", "content": "dynamic payload"},
        ]

        with patch("urllib.request.urlopen", fake_urlopen):
            result = client.chat_json("draft_writer", messages, {"content": "string"})

        self.assertEqual(result, {"result": "ok"})
        final_messages = captured["payload"]["input"]
        self.assertEqual([message["role"] for message in final_messages], ["system", "system", "user"])
        self.assertTrue(final_messages[0]["content"].startswith("fixed agent"))
        self.assertIn("字段要求", final_messages[0]["content"])
        self.assertEqual(final_messages[1]["content"], "project constraints")
        self.assertEqual(final_messages[2]["content"], "dynamic payload")

    def test_chat_json_appends_schema_hint_when_no_user_message_exists(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"output_text": "{\"result\": \"ok\"}"})

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "chat_model": "writer",
            }
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            client.chat_json("draft_writer", [{"role": "system", "content": "fixed"}], {"content": "string"})

        final_messages = captured["payload"]["input"]
        self.assertEqual([message["role"] for message in final_messages], ["system"])
        self.assertTrue(final_messages[0]["content"].startswith("fixed"))
        self.assertIn("字段要求", final_messages[0]["content"])

    def test_build_messages_places_stable_project_constraints_before_user_payload(self) -> None:
        messages = build_messages(
            "draft_writer",
            {
                "project_writing_constraints": {
                    "writing_style_guide": "短句",
                    "genre": "悬疑",
                    "title": "旧宅",
                },
                "scene": "雨夜",
            },
        )

        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        self.assertIn("项目级写作约束", messages[0]["content"])
        self.assertLess(messages[0]["content"].index('"genre"'), messages[0]["content"].index('"title"'))
        self.assertLess(messages[0]["content"].index('"title"'), messages[0]["content"].index('"writing_style_guide"'))
        self.assertIn("输入数据如下", messages[1]["content"])

    def test_chat_retries_with_conservative_payload_when_remote_closes(self) -> None:
        captured_payloads = []

        def fake_urlopen(req, timeout):
            captured_payloads.append(json.loads(req.data.decode("utf-8")))
            if len(captured_payloads) == 1:
                raise URLError(RemoteDisconnected("Remote end closed connection without response"))
            return FakeResponse(
                {"choices": [{"message": {"content": "{\"result\": \"ok\"}"}}]}
            )

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "chat_completions",
                "chat_model": "writer",
                "max_tokens": 1234,
                "temperature": 0.8,
                "top_p": 0.92,
                "top_k": 40,
                "presence_penalty": 0.3,
                "frequency_penalty": 0.2,
            }
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            result = client.chat_json("draft_writer", [{"role": "user", "content": "x"}])

        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(len(captured_payloads), 2)
        self.assertTrue(captured_payloads[0])
        self.assertIn("messages", captured_payloads[0])
        self.assertIn("response_format", captured_payloads[0])
        self.assertIn("top_k", captured_payloads[0])
        self.assertIn("presence_penalty", captured_payloads[0])
        self.assertEqual(
            set(captured_payloads[1]),
            {"model", "messages", "max_tokens", "temperature"},
        )
        self.assertEqual(captured_payloads[1]["messages"], [{"role": "user", "content": "x"}])

    def test_chat_retries_with_conservative_payload_on_http_503(self) -> None:
        captured_payloads = []

        def fake_urlopen(req, timeout):
            captured_payloads.append(json.loads(req.data.decode("utf-8")))
            if len(captured_payloads) == 1:
                raise HTTPError(req.full_url, 503, "Service Unavailable", {}, BytesIO(b"upstream timeout"))
            return FakeResponse(
                {"choices": [{"message": {"content": "{\"result\": \"ok\"}"}}]}
            )

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "chat_completions",
                "chat_model": "writer",
                "top_k": 40,
                "presence_penalty": 0.3,
                "frequency_penalty": 0.2,
            }
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            result = client.chat_json("reviewer", [{"role": "user", "content": "draft"}])

        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(len(captured_payloads), 2)
        self.assertIn("response_format", captured_payloads[0])
        self.assertIn("top_k", captured_payloads[0])
        self.assertEqual(
            set(captured_payloads[1]),
            {"model", "messages", "max_tokens", "temperature"},
        )

    def test_chat_retries_api_errors_until_cancel_config_succeeds(self) -> None:
        attempts = []
        retry_events = []

        def fake_urlopen(req, timeout):
            attempts.append(json.loads(req.data.decode("utf-8")))
            if len(attempts) < 3:
                raise HTTPError(req.full_url, 403, "Forbidden", {}, BytesIO(b"access denied"))
            return FakeResponse(
                {"choices": [{"message": {"content": "{\"result\": \"ok\"}"}}]}
            )

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "chat_completions",
                "chat_model": "writer",
            }
        )
        import threading

        cancel_event = threading.Event()
        client.configure_retry_until_cancel(
            cancel_event,
            lambda attempt, delay, error: retry_events.append((attempt, delay, error)),
            delays=[0],
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            result = client.chat_json("draft_writer", [{"role": "user", "content": "x"}])

        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(len(attempts), 3)
        self.assertEqual([event[0] for event in retry_events], [1, 2])
        self.assertTrue(all("HTTP 403" in event[2] for event in retry_events))

    def test_chat_retry_until_cancel_stops_before_next_request(self) -> None:
        attempts = []

        def fake_urlopen(req, timeout):
            attempts.append(json.loads(req.data.decode("utf-8")))
            raise HTTPError(req.full_url, 403, "Forbidden", {}, BytesIO(b"access denied"))

        class CancelOnWait:
            def is_set(self) -> bool:
                return False

            def wait(self, _delay: int) -> bool:
                return True

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "chat_completions",
                "chat_model": "writer",
            }
        )
        client.configure_retry_until_cancel(CancelOnWait(), delays=[0])

        with patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(LLMError) as ctx:
                client.chat_json("draft_writer", [{"role": "user", "content": "x"}])

        self.assertEqual(len(attempts), 1)
        self.assertIn("用户已中断自动化写作", str(ctx.exception))

    def test_timeout_retry_uses_longer_cooldown(self) -> None:
        client = LLMClient()
        self.assertEqual(client._retry_delay(1, LLMError("读取响应超时")), 30)
        self.assertEqual(client._retry_delay(2, LLMError("读取响应超时")), 60)
        self.assertEqual(client._retry_delay(1, LLMError("HTTP 503: busy")), 5)

    def test_llm_requests_are_serialized_per_client(self) -> None:
        client = LLMClient({"base_url": "https://example.test/v1", "api_key": "key"})
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_urlopen(req, timeout):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return FakeResponse({"data": [{"id": "writer"}]})

        results = []

        def run() -> None:
            results.append(client.list_models())

        with patch("urllib.request.urlopen", fake_urlopen):
            threads = [threading.Thread(target=run), threading.Thread(target=run)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(results, [["writer"], ["writer"]])
        self.assertEqual(max_active, 1)

    def test_list_models_reads_openai_compatible_data(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["auth"] = req.headers.get("Authorization")
            captured["user_agent"] = req.headers.get("User-agent")
            captured["timeout"] = timeout
            return FakeResponse(
                {
                    "data": [
                        {"id": "writer-model"},
                        {"id": "review-model"},
                        {"id": "writer-model"},
                    ]
                }
            )

        client = LLMClient(
            {
                "base_url": "https://example.test/v1/",
                "api_key": "key",
                "timeout_seconds": 5,
            }
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            models = client.list_models()
        self.assertEqual(models, ["writer-model", "review-model"])
        self.assertEqual(captured["url"], "https://example.test/v1/models")
        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["auth"], "Bearer key")
        self.assertEqual(captured["user_agent"], "MyAINovel/0.1")
        self.assertEqual(captured["timeout"], 5)

    def test_list_models_accepts_string_list(self) -> None:
        client = LLMClient({"base_url": "https://example.test/v1", "api_key": "key"})
        with patch("urllib.request.urlopen", return_value=FakeResponse(["model-a", "model-b"])):
            self.assertEqual(client.list_models(), ["model-a", "model-b"])

    def test_discover_models_merges_remote_with_configured_candidates(self) -> None:
        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "chat_model": "configured-chat",
                "review_model": "configured-review",
                "embedding_model": "configured-embed",
                "model_candidates": "manual-a\nconfigured-chat\nmanual-b",
            }
        )
        with patch(
            "urllib.request.urlopen",
            return_value=FakeResponse({"data": [{"id": "remote-a"}, {"id": "manual-a"}]}),
        ):
            result = client.discover_models()
        self.assertEqual(
            result,
            {
                "models": [
                    "configured-chat",
                    "configured-review",
                    "configured-embed",
                    "manual-a",
                    "manual-b",
                    "remote-a",
                ],
                "source": "remote",
                "warning": "",
            },
        )

    def test_discover_models_keeps_manual_candidates_when_remote_closes(self) -> None:
        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "chat_model": "configured-chat",
                "model_candidates": "manual-a\nmanual-b",
            }
        )
        with patch(
            "urllib.request.urlopen",
            side_effect=URLError(RemoteDisconnected("Remote end closed connection without response")),
        ):
            result = client.discover_models()
        self.assertEqual(result["models"], ["configured-chat", "manual-a", "manual-b"])
        self.assertEqual(result["source"], "manual")
        self.assertIn("connection was closed", result["warning"])
        self.assertIn("/models", result["warning"])

    def test_discover_models_uses_builtin_candidates_for_provider_host_when_remote_closes(self) -> None:
        client = LLMClient({"base_url": "https://api.openai.com/v1", "api_key": "key"})
        with patch(
            "urllib.request.urlopen",
            side_effect=URLError(RemoteDisconnected("Remote end closed connection without response")),
        ):
            result = client.discover_models()
        self.assertEqual(result["models"], ["gpt-4.1", "gpt-4.1-mini", "text-embedding-3-small"])
        self.assertEqual(result["source"], "builtin")
        self.assertIn("connection was closed", result["warning"])

    def test_connection_returns_403_1010_diagnostic(self) -> None:
        def fake_urlopen(req, timeout):
            raise HTTPError(
                req.full_url,
                403,
                "Forbidden",
                {},
                BytesIO(b'{"error":{"code":1010,"message":"Access denied"}}'),
            )

        client = LLMClient(
            {
                "base_url": "https://blocked.example/v1",
                "api_key": "key",
                "chat_model": "writer",
            }
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            ok, message = client.test_connection()
        self.assertFalse(ok)
        self.assertIn("HTTP 403", message)
        self.assertIn("1010", message)
        self.assertIn("Cloudflare", message)
        self.assertIn("base_url", message)
        self.assertIn("API key", message)
        self.assertIn("来源", message)

    def test_connection_uses_minimal_chat_completions_python_kwargs(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

        client = LLMClient(
            {
                "base_url": "https://api.deepseek.com",
                "api_key": "key",
                "api_type": "chat_completions",
                "chat_model": "deepseek-v4-pro",
                "max_tokens": 2000,
                "temperature": 1.1,
                "top_p": 0.95,
                "top_k": 40,
                "presence_penalty": 0.3,
                "frequency_penalty": 0.5,
            }
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            ok, message = client.test_connection()

        self.assertTrue(ok)
        self.assertEqual(message, "连接成功")
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(
            captured["payload"],
            {
                "model": "deepseek-v4-pro",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 64,
                "temperature": 1.1,
                "stream": False,
            },
        )

    def test_connection_uses_minimal_responses_python_kwargs(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"output_text": "ok"})

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "responses",
                "chat_model": "writer",
                "max_tokens": 2000,
                "temperature": 1.1,
                "top_p": 0.95,
                "top_k": 40,
                "presence_penalty": 0.3,
                "frequency_penalty": 0.5,
            }
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            ok, message = client.test_connection()

        self.assertTrue(ok)
        self.assertEqual(message, "连接成功")
        self.assertEqual(captured["url"], "https://example.test/v1/responses")
        self.assertEqual(
            captured["payload"],
            {
                "model": "writer",
                "input": [{"role": "user", "content": "Hello"}],
                "max_output_tokens": 64,
                "temperature": 1.1,
            },
        )

    def test_chat_timeout_explains_provider_499(self) -> None:
        client = LLMClient(
            {
                "base_url": "https://slow.example/v1",
                "api_key": "key",
                "chat_model": "writer",
                "timeout_seconds": 11,
            }
        )
        with patch("urllib.request.urlopen", return_value=TimeoutResponse()):
            with self.assertRaises(LLMError) as ctx:
                client.chat_json("draft_writer", [{"role": "user", "content": "x"}])

        message = str(ctx.exception)
        self.assertIn("读取响应超时", message)
        self.assertIn("11 秒", message)
        self.assertIn("499", message)

    def test_list_models_urlerror_timeout_uses_timeout_diagnostic(self) -> None:
        client = LLMClient(
            {
                "base_url": "https://slow.example/v1",
                "api_key": "key",
                "timeout_seconds": 12,
            }
        )
        with patch("urllib.request.urlopen", side_effect=URLError(TimeoutError("The read operation timed out"))):
            with self.assertRaises(LLMError) as ctx:
                client.list_models()

        message = str(ctx.exception)
        self.assertIn("读取响应超时", message)
        self.assertIn("12 秒", message)
        self.assertIn("499", message)

    def test_connection_returns_499_diagnostic(self) -> None:
        def fake_urlopen(req, timeout):
            raise HTTPError(req.full_url, 499, "Client Closed Request", {}, BytesIO(b"client closed"))

        client = LLMClient(
            {
                "base_url": "https://slow.example/v1",
                "api_key": "key",
                "chat_model": "writer",
            }
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            ok, message = client.test_connection()

        self.assertFalse(ok)
        self.assertIn("HTTP 499", message)
        self.assertIn("客户端先关闭", message)
        self.assertIn("超时秒数", message)

    def test_connection_returns_503_diagnostic(self) -> None:
        def fake_urlopen(req, timeout):
            raise HTTPError(req.full_url, 503, "Service Unavailable", {}, BytesIO(b"upstream timeout"))

        client = LLMClient(
            {
                "base_url": "https://busy.example/v1",
                "api_key": "key",
                "chat_model": "writer",
            }
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            ok, message = client.test_connection()

        self.assertFalse(ok)
        self.assertIn("HTTP 503", message)
        self.assertIn("上游模型服务", message)
        self.assertIn("审稿", message)
        self.assertIn("稍后重试", message)

    def test_connection_503_format_mismatch_mentions_responses_api_type(self) -> None:
        def fake_urlopen(req, timeout):
            raise HTTPError(
                req.full_url,
                503,
                "Service Unavailable",
                {},
                BytesIO(b'{"error":{"code":"no_available_providers","details":{"filteredProviders":[{"reason":"format_type_mismatch"}]}}}'),
            )

        client = LLMClient(
            {
                "base_url": "https://busy.example/v1",
                "api_key": "key",
                "api_type": "chat_completions",
                "chat_model": "writer",
            }
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            ok, message = client.test_connection()

        self.assertFalse(ok)
        self.assertIn("format_type_mismatch", message)
        self.assertIn("/responses", message)

    def test_default_timeout_comes_from_default_llm_config(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["timeout"] = timeout
            return FakeResponse({"choices": [{"message": {"content": "{\"result\": \"ok\"}"}}]})

        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "api_type": "chat_completions",
                "chat_model": "writer",
            }
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            client.chat_json("draft_writer", [{"role": "user", "content": "x"}])

        self.assertEqual(captured["timeout"], DEFAULT_LLM_CONFIG["timeout_seconds"])

    def test_missing_config_returns_connection_error(self) -> None:
        ok, message = LLMClient({"base_url": "", "api_key": ""}).test_connection()
        self.assertFalse(ok)
        self.assertIn("base_url", message)

    def test_proxy_url_uses_proxy_handler_and_opener_for_all_llm_requests(self) -> None:
        opened_paths = []

        class FakeOpener:
            def open(self, req, timeout):
                opened_paths.append((req.full_url, req.get_method(), timeout))
                if req.full_url.endswith("/models"):
                    return FakeResponse({"data": [{"id": "writer"}]})
                if req.full_url.endswith("/responses"):
                    return FakeResponse({"output_text": "{\"result\": \"ok\"}"})
                if req.full_url.endswith("/embeddings"):
                    return FakeResponse({"data": [{"embedding": [1, 2, 3]}]})
                raise AssertionError(f"unexpected URL: {req.full_url}")

        proxy_handler = Mock(name="proxy_handler")
        opener = FakeOpener()
        client = LLMClient(
            {
                "base_url": "https://example.test/v1",
                "api_key": "key",
                "chat_model": "writer",
                "embedding_model": "embedder",
                "proxy_url": "http://127.0.0.1:7890",
                "timeout_seconds": 9,
            }
        )
        with patch("urllib.request.ProxyHandler", return_value=proxy_handler) as proxy_handler_cls, patch(
            "urllib.request.build_opener", return_value=opener
        ) as build_opener, patch("urllib.request.urlopen") as urlopen:
            self.assertEqual(client.list_models(), ["writer"])
            self.assertEqual(
                client.chat_json("draft_writer", [{"role": "user", "content": "x"}]),
                {"result": "ok"},
            )
            self.assertEqual(client.embed(["hello"]), [[1.0, 2.0, 3.0]])

        expected_proxy = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
        self.assertEqual(proxy_handler_cls.call_count, 3)
        proxy_handler_cls.assert_called_with(expected_proxy)
        self.assertEqual(build_opener.call_count, 3)
        build_opener.assert_called_with(proxy_handler)
        urlopen.assert_not_called()
        self.assertEqual(
            opened_paths,
            [
                ("https://example.test/v1/models", "GET", 9),
                ("https://example.test/v1/responses", "POST", 9),
                ("https://example.test/v1/embeddings", "POST", 9),
            ],
        )


if __name__ == "__main__":
    unittest.main()
