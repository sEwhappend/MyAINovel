from __future__ import annotations

import contextlib
import json
import socket
import threading
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

from .models import DEFAULT_LLM_CONFIG, LLMConfig


CONFIG_DIR = Path(".json")
CONFIG_PATH = CONFIG_DIR / "llm_config.json"
USER_AGENT = "MyAINovel/0.1"
BUILTIN_MODEL_CANDIDATES = {
    "api.openai.com": ["gpt-4.1", "gpt-4.1-mini", "text-embedding-3-small"],
    "openai.com": ["gpt-4.1", "gpt-4.1-mini", "text-embedding-3-small"],
    "api.deepseek.com": ["deepseek-chat", "deepseek-reasoner"],
    "deepseek.com": ["deepseek-chat", "deepseek-reasoner"],
    "api.siliconflow.cn": ["Qwen/Qwen2.5-72B-Instruct", "BAAI/bge-m3"],
    "siliconflow.cn": ["Qwen/Qwen2.5-72B-Instruct", "BAAI/bge-m3"],
    "generativelanguage.googleapis.com": ["gemini-2.0-flash", "text-embedding-004"],
    "googleapis.com": ["gemini-2.0-flash", "text-embedding-004"],
    "dashscope.aliyuncs.com": ["qwen-plus", "qwen-turbo", "text-embedding-v3"],
    "aliyuncs.com": ["qwen-plus", "qwen-turbo", "text-embedding-v3"],
}


class LLMError(RuntimeError):
    pass


def load_llm_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    config = dict(DEFAULT_LLM_CONFIG)
    target = Path(path)
    if target.exists():
        with target.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        config.update({key: value for key, value in data.items() if key in config})
    return config


def save_llm_config(config: dict[str, Any], path: str | Path = CONFIG_PATH) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(DEFAULT_LLM_CONFIG)
    clean.update(config)
    if clean.get("top_k") in ("", 0, "0"):
        clean["top_k"] = None
    target.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_json_response(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM response is not valid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise LLMError("LLM response JSON must be an object")
    return result


class LLMClient:
    def __init__(self, config: dict[str, Any] | LLMConfig | None = None) -> None:
        if isinstance(config, LLMConfig):
            self.config = config.to_dict()
        else:
            self.config = dict(DEFAULT_LLM_CONFIG)
            self.config.update(config or load_llm_config())
        self.retry_cancel_event: Any = None
        self.retry_callback: Any = None
        self.retry_delays = [5, 15, 30, 60]
        self.retry_timeout_delays = [30, 60, 90, 120]
        self._request_lock = threading.RLock()
        # 临时采样参数覆盖（如项目文风推荐的 temperature/top_p/penalties）。
        self._param_overrides: dict[str, Any] = {}

    @contextlib.contextmanager
    def override_params(self, overrides: dict[str, Any] | None):
        """在 with 块内临时覆盖采样参数；退出后恢复。None 值忽略。"""
        clean = {key: value for key, value in (overrides or {}).items() if value is not None}
        if not clean:
            yield
            return
        previous = self._param_overrides
        self._param_overrides = {**previous, **clean}
        try:
            yield
        finally:
            self._param_overrides = previous

    def _effective(self, key: str, default: Any) -> Any:
        overrides = self._param_overrides
        if key in overrides and overrides[key] is not None:
            return overrides[key]
        return self.config.get(key, default)

    def configure_retry_until_cancel(
        self,
        cancel_event: Any = None,
        callback: Any = None,
        delays: list[int] | None = None,
    ) -> None:
        self.retry_cancel_event = cancel_event
        self.retry_callback = callback
        if delays is not None:
            self.retry_delays = delays or [0]

    @property
    def base_url(self) -> str:
        return str(self.config.get("base_url", "")).rstrip("/")

    @property
    def api_type(self) -> str:
        raw = str(self.config.get("api_type", DEFAULT_LLM_CONFIG["api_type"]) or "").strip()
        if raw in {"chat", "chat_completions", "/chat/completions"}:
            return "chat_completions"
        if raw in {"responses", "/responses"}:
            return "responses"
        return str(DEFAULT_LLM_CONFIG["api_type"])

    def _thinking_disabled(self) -> bool:
        """是否在 chat/completions 请求体注入 thinking:{"type":"disabled"}。

        仅 chat_completions 协议有效（DeepSeek 不走 /responses）。
        provider=deepseek 自动关闭思考；provider=openai 永不注入；
        其余（custom/未设）由 disable_thinking 开关控制。
        """
        if self.api_type != "chat_completions":
            return False
        provider = str(self.config.get("provider", "") or "").strip().lower()
        if provider == "deepseek":
            return True
        if provider == "openai":
            return False
        return bool(self.config.get("disable_thinking", False))

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._test_connection_once(self.config.get("chat_model") or self.config.get("review_model") or "")
        except Exception as exc:  # noqa: BLE001 - surfaced to UI as text
            return False, str(exc)
        return True, "连接成功"

    def chat_json(
        self,
        agent_name: str,
        messages: list[dict[str, str]],
        schema_hint: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        selected_model = model or self._model_for_agent(agent_name)
        final_messages = list(messages)
        if schema_hint:
            schema_content = "输出必须是 JSON object，字段要求：" + json.dumps(schema_hint, ensure_ascii=False)
            system_index = next(
                (index for index, message in enumerate(final_messages) if message.get("role") == "system"),
                None,
            )
            if system_index is not None:
                current = str(final_messages[system_index].get("content", "") or "")
                final_messages[system_index] = {
                    **final_messages[system_index],
                    "content": f"{current}\n\n{schema_content}" if current else schema_content,
                }
            else:
                insert_at = next(
                    (index for index, message in enumerate(final_messages) if message.get("role") == "user"),
                    len(final_messages),
                )
                final_messages.insert(insert_at, {"role": "system", "content": schema_content})
        text = self._chat(selected_model, final_messages)
        return parse_json_response(text)

    def stream_text(
        self,
        model: str,
        messages: list[dict[str, str]],
        on_delta: Any,
        max_tokens: int | None = None,
    ) -> str:
        attempt = 0
        while True:
            emitted = False

            def forward_delta(delta: str) -> None:
                nonlocal emitted
                if delta:
                    emitted = True
                on_delta(delta)

            try:
                if self.api_type != "responses":
                    return self._chat_completions_stream_text(model, messages, forward_delta, max_tokens)
                if not self.base_url:
                    raise LLMError("未配置 base_url")
                if not self.config.get("api_key"):
                    raise LLMError("未配置 api_key")
                if not model:
                    raise LLMError("未配置模型")
                payload = self._responses_payload(model, messages, max_tokens)
                payload["stream"] = True
                chunks: list[str] = []
                for event in self._post_sse("/responses", payload):
                    delta = self._extract_responses_delta(event)
                    if delta:
                        chunks.append(delta)
                        forward_delta(delta)
                return "".join(chunks)
            except LLMError as exc:
                if emitted or not self._should_retry_until_cancel(exc):
                    raise
                attempt += 1
                delay = self._retry_delay(attempt, exc)
                if self.retry_callback:
                    self.retry_callback(attempt, delay, str(exc))
                if self.retry_cancel_event is None or self.retry_cancel_event.wait(delay):
                    raise LLMError("用户已中断自动化写作") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self.config.get("embedding_model")
        if not model:
            raise LLMError("未配置 embedding 模型")
        payload = {"model": model, "input": texts}
        data = self._post_json("/embeddings", payload)
        vectors = []
        for item in data.get("data", []):
            vectors.append([float(value) for value in item.get("embedding", [])])
        return vectors

    def list_models(self) -> list[str]:
        if not self.base_url:
            raise LLMError("未配置 base_url")
        if not self.config.get("api_key"):
            raise LLMError("未配置 api_key")
        data = self._get_json("/models")
        return self._extract_model_ids(data)

    def discover_models(self) -> dict[str, Any]:
        models: list[str] = []
        for model_id in self._configured_model_ids():
            self._append_unique(models, model_id)

        try:
            remote_models = self.list_models()
        except Exception as exc:  # noqa: BLE001 - discovery reports errors as warning text
            warning = self._format_discovery_warning(exc)
            if models:
                source = "manual" if self._manual_model_candidates() else "configured"
                return {"models": models, "source": source, "warning": warning}
            for model_id in self._builtin_model_candidates():
                self._append_unique(models, model_id)
            if models:
                return {"models": models, "source": "builtin", "warning": warning}
            return {"models": [], "source": "none", "warning": warning}

        for model_id in remote_models:
            self._append_unique(models, model_id)
        return {"models": models, "source": "remote", "warning": ""}

    def _model_for_agent(self, agent_name: str) -> str:
        if agent_name == "style_profile_builder":
            return (
                self.config.get("style_model")
                or self.config.get("review_model")
                or self.config.get("chat_model")
                or ""
            )
        if agent_name == "style_analyzer_chunk":
            return (
                self.config.get("style_model")
                or self.config.get("chat_model")
                or self.config.get("review_model")
                or ""
            )
        if agent_name in {"reviewer", "rewriter", "chapter_architect", "global_architect"}:
            return self.config.get("review_model") or self.config.get("chat_model") or ""
        return self.config.get("chat_model") or self.config.get("review_model") or ""

    def _chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> str:
        attempt = 0
        while True:
            try:
                return self._chat_once(model, messages, max_tokens)
            except LLMError as exc:
                if not self._should_retry_until_cancel(exc):
                    raise
                attempt += 1
                delay = self._retry_delay(attempt, exc)
                if self.retry_callback:
                    self.retry_callback(attempt, delay, str(exc))
                if self.retry_cancel_event.wait(delay):
                    raise LLMError("用户已中断自动化写作") from exc

    def _chat_once(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> str:
        if not self.base_url:
            raise LLMError("未配置 base_url")
        if not self.config.get("api_key"):
            raise LLMError("未配置 api_key")
        if not model:
            raise LLMError("未配置模型")
        if self.api_type == "responses":
            return self._responses_once(model, messages, max_tokens)
        return self._chat_completions_once(model, messages, max_tokens)

    def _chat_completions_once(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> str:
        payload = self._chat_payload(model, messages, max_tokens, include_compat_fields=True)
        try:
            data = self._post_json("/chat/completions", payload)
        except LLMError as exc:
            if not self._should_retry_with_conservative_payload(exc):
                raise
            fallback_payload = self._chat_payload(model, messages, max_tokens, include_compat_fields=False)
            data = self._post_json("/chat/completions", fallback_payload)
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("LLM 响应缺少 choices")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not content:
            raise LLMError("LLM 响应内容为空")
        return content

    def _chat_completions_stream_text(
        self,
        model: str,
        messages: list[dict[str, str]],
        on_delta: Any,
        max_tokens: int | None = None,
    ) -> str:
        if not self.base_url:
            raise LLMError("未配置 base_url")
        if not self.config.get("api_key"):
            raise LLMError("未配置 api_key")
        if not model:
            raise LLMError("未配置模型")
        payload = self._chat_stream_payload(model, messages, max_tokens)
        chunks: list[str] = []
        for event in self._post_sse("/chat/completions", payload):
            delta = self._extract_chat_delta(event)
            if delta:
                chunks.append(delta)
                on_delta(delta)
        return "".join(chunks)

    def _test_connection_once(self, model: str) -> None:
        if not self.base_url:
            raise LLMError("未配置 base_url")
        if not self.config.get("api_key"):
            raise LLMError("未配置 api_key")
        if not model:
            raise LLMError("未配置模型")

        if self.api_type == "responses":
            payload = self._responses_payload(
                model,
                [{"role": "user", "content": "Hello"}],
                max_tokens=64,
                include_writing_parameters=False,
            )
            data = self._post_json("/responses", payload)
            if not self._extract_responses_text(data):
                raise LLMError("Responses API 响应缺少文本内容")
            return

        payload = self._chat_payload(
            model,
            [{"role": "user", "content": "Hello"}],
            max_tokens=64,
            include_compat_fields=False,
            stream=False,
        )
        data = self._post_json("/chat/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("LLM 响应缺少 choices")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not content:
            raise LLMError("LLM 响应内容为空")

    def _responses_once(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> str:
        payload = self._responses_payload(model, messages, max_tokens)
        data = self._post_json("/responses", payload)
        content = self._extract_responses_text(data)
        if not content:
            raise LLMError("Responses API 响应缺少文本内容")
        return content

    def _chat_payload(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        include_compat_fields: bool = True,
        stream: bool | None = None,
    ) -> dict[str, Any]:
        temperature = float(self._effective("temperature", 0.7))
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else int(self.config.get("max_tokens", 2000)),
            "temperature": temperature,
        }
        if stream is not None:
            payload["stream"] = stream
        if self._thinking_disabled():
            payload["thinking"] = {"type": "disabled"}
        if not include_compat_fields:
            # 精简/流式 payload 默认不带这些字段；但若被显式覆盖（如文风推荐），仍需带上。
            overrides = self._param_overrides
            for key in ("top_p", "presence_penalty", "frequency_penalty"):
                if overrides.get(key) is not None:
                    payload[key] = float(overrides[key])
            if overrides.get("top_k") not in (None, "", 0, "0"):
                payload["top_k"] = int(overrides["top_k"])
            return payload
        payload["top_p"] = float(self._effective("top_p", 0.9))
        payload["presence_penalty"] = float(self._effective("presence_penalty", 0.0))
        payload["frequency_penalty"] = float(self._effective("frequency_penalty", 0.0))
        payload["response_format"] = {"type": "json_object"}
        top_k = self._effective("top_k", None)
        if top_k not in (None, "", 0, "0"):
            payload["top_k"] = int(top_k)
        return payload

    def _chat_stream_payload(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        return self._chat_payload(model, messages, max_tokens, include_compat_fields=False, stream=True)

    def _responses_payload(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        include_writing_parameters: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "input": self._responses_input(messages),
            "max_output_tokens": max_tokens
            if max_tokens is not None
            else int(self.config.get("max_tokens", 2000)),
            "temperature": float(self._effective("temperature", 0.7)),
        }
        if not include_writing_parameters:
            return payload
        payload["top_p"] = float(self._effective("top_p", 0.9))
        presence_penalty = float(self._effective("presence_penalty", 0.0))
        frequency_penalty = float(self._effective("frequency_penalty", 0.0))
        if presence_penalty:
            payload["presence_penalty"] = presence_penalty
        if frequency_penalty:
            payload["frequency_penalty"] = frequency_penalty
        top_k = self._effective("top_k", None)
        if top_k not in (None, "", 0, "0"):
            payload["top_k"] = int(top_k)
        return payload

    def _responses_input(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            {
                "role": str(message.get("role", "user") or "user"),
                "content": str(message.get("content", "") or ""),
            }
            for message in messages
        ]

    def _extract_responses_text(self, data: dict[str, Any]) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        parts: list[str] = []
        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for content_item in content:
                        if not isinstance(content_item, dict):
                            continue
                        text = content_item.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()

    def _extract_responses_delta(self, data: dict[str, Any]) -> str:
        event_type = str(data.get("type", "") or "")
        if event_type in {"response.output_text.delta", "output_text.delta"}:
            delta = data.get("delta")
            return delta if isinstance(delta, str) else ""
        if event_type in {"response.completed", "response.output_text.done"}:
            return ""
        delta = data.get("delta")
        if isinstance(delta, str):
            return delta
        text = data.get("text")
        if isinstance(text, str):
            return text
        return self._extract_responses_text(data)

    @staticmethod
    def _extract_chat_delta(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        choice = choices[0]
        if not isinstance(choice, dict):
            return ""
        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        text = choice.get("text")
        if isinstance(text, str):
            return text
        return ""

    def _get_json(self, path: str) -> Any:
        url = self.base_url + path
        req = request.Request(
            url,
            headers=self._request_headers(),
            method="GET",
        )
        try:
            with self._request_lock:
                with self._open_request(req) as resp:
                    raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(self._format_http_error(exc.code, detail)) from exc
        except error.URLError as exc:
            if self._is_timeout_error(exc):
                raise LLMError(self._format_timeout_error()) from exc
            raise LLMError(f"连接失败: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError(self._format_timeout_error()) from exc
        except socket.timeout as exc:
            raise LLMError(self._format_timeout_error()) from exc
        except (ConnectionError, OSError) as exc:
            raise LLMError(f"连接失败：连接被远程主机重置或中断（{exc}）") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM API returned invalid JSON: {exc}") from exc

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url + path
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers=self._request_headers(),
            method="POST",
        )
        try:
            with self._request_lock:
                with self._open_request(req) as resp:
                    raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(self._format_http_error(exc.code, detail)) from exc
        except error.URLError as exc:
            if self._is_timeout_error(exc):
                raise LLMError(self._format_timeout_error()) from exc
            raise LLMError(f"连接失败: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError(self._format_timeout_error()) from exc
        except socket.timeout as exc:
            raise LLMError(self._format_timeout_error()) from exc
        except (ConnectionError, OSError) as exc:
            raise LLMError(f"连接失败：连接被远程主机重置或中断（{exc}）") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM API returned invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise LLMError("LLM API response must be a JSON object")
        return data

    def _post_sse(self, path: str, payload: dict[str, Any]):
        url = self.base_url + path
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={**self._request_headers(), "Accept": "text/event-stream"},
            method="POST",
        )
        try:
            with self._request_lock:
                with self._open_request(req) as resp:
                    event_lines: list[str] = []
                    for raw_line in resp:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line:
                            yield from self._parse_sse_event(event_lines)
                            event_lines = []
                            continue
                        event_lines.append(line)
                    if event_lines:
                        yield from self._parse_sse_event(event_lines)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(self._format_http_error(exc.code, detail)) from exc
        except error.URLError as exc:
            if self._is_timeout_error(exc):
                raise LLMError(self._format_timeout_error()) from exc
            raise LLMError(f"连接失败: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError(self._format_timeout_error()) from exc
        except socket.timeout as exc:
            raise LLMError(self._format_timeout_error()) from exc
        except (ConnectionError, OSError) as exc:
            raise LLMError(f"连接失败：连接被远程主机重置或中断（{exc}）") from exc

    def _parse_sse_event(self, lines: list[str]):
        data_lines = []
        for line in lines:
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            data_lines.append(data)
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM stream event is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise LLMError("LLM stream event must be a JSON object")
        yield data

    def _request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.get('api_key', '')}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

    def _open_request(self, req: request.Request) -> Any:
        default_timeout = DEFAULT_LLM_CONFIG["timeout_seconds"]
        timeout = int(self.config.get("timeout_seconds", default_timeout) or default_timeout)
        proxy_url = str(self.config.get("proxy_url", "") or "").strip()
        if proxy_url:
            proxy_handler = request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            opener = request.build_opener(proxy_handler)
            return opener.open(req, timeout=timeout)
        return request.urlopen(req, timeout=timeout)

    def _extract_model_ids(self, data: Any) -> list[str]:
        candidates: Any
        if isinstance(data, dict):
            if isinstance(data.get("data"), list):
                candidates = data["data"]
            elif isinstance(data.get("models"), list):
                candidates = data["models"]
            elif isinstance(data.get("model"), list):
                candidates = data["model"]
            else:
                candidates = []
        elif isinstance(data, list):
            candidates = data
        else:
            candidates = []

        models: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            model_id = ""
            if isinstance(item, str):
                model_id = item
            elif isinstance(item, dict):
                for key in ("id", "name", "model"):
                    value = item.get(key)
                    if isinstance(value, str):
                        model_id = value
                        break
            if model_id and model_id not in seen:
                seen.add(model_id)
                models.append(model_id)
        return models

    def _configured_model_ids(self) -> list[str]:
        models: list[str] = []
        for key in ("chat_model", "review_model", "embedding_model"):
            self._append_unique(models, str(self.config.get(key, "") or "").strip())
        for model_id in self._manual_model_candidates():
            self._append_unique(models, model_id)
        return models

    def _manual_model_candidates(self) -> list[str]:
        raw = str(self.config.get("model_candidates", "") or "")
        models: list[str] = []
        for line in raw.splitlines():
            self._append_unique(models, line.strip())
        return models

    def _builtin_model_candidates(self) -> list[str]:
        host = (urlparse(self.base_url).hostname or "").lower()
        if not host:
            return []
        for provider_host, models in BUILTIN_MODEL_CANDIDATES.items():
            if host == provider_host or host.endswith("." + provider_host):
                return list(models)
        return []

    def _format_discovery_warning(self, exc: Exception) -> str:
        if self._is_connection_closed_error(exc):
            return f"Remote /models connection was closed by the provider: {exc}"
        return f"Remote /models discovery failed: {exc}"

    def _is_connection_closed_error(self, exc: BaseException) -> bool:
        if isinstance(exc, (RemoteDisconnected, ConnectionResetError)):
            return True
        if isinstance(exc, error.URLError):
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (RemoteDisconnected, ConnectionResetError)):
                return True
            return "remote end closed connection" in str(reason).lower()
        cause = getattr(exc, "__cause__", None)
        if isinstance(cause, BaseException) and cause is not exc:
            return self._is_connection_closed_error(cause)
        return "remote end closed connection" in str(exc).lower() or "connection reset" in str(exc).lower()

    def _is_timeout_error(self, exc: BaseException) -> bool:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return True
        if isinstance(exc, error.URLError):
            reason = getattr(exc, "reason", None)
            return isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower()
        cause = getattr(exc, "__cause__", None)
        if isinstance(cause, BaseException) and cause is not exc:
            return self._is_timeout_error(cause)
        return "timed out" in str(exc).lower()

    def _should_retry_with_conservative_payload(self, exc: BaseException) -> bool:
        if self._is_connection_closed_error(exc):
            return True
        return "HTTP 503" in str(exc)

    def _should_retry_until_cancel(self, exc: BaseException) -> bool:
        if self.retry_cancel_event is None:
            return False
        if self.retry_cancel_event.is_set():
            raise LLMError("用户已中断自动化写作") from exc
        text = str(exc)
        if self._is_connection_closed_error(exc) or self._is_timeout_error(exc):
            return True
        if "读取响应超时" in text or "连接失败" in text:
            return True
        retryable_codes = ("401", "403", "429", "499", "500", "502", "503", "504", "524")
        return any(f"HTTP {code}" in text for code in retryable_codes)

    def _retry_delay(self, attempt: int, exc: BaseException | None = None) -> int:
        delays = self.retry_delays
        if exc is not None and (
            self._is_timeout_error(exc) or "读取响应超时" in str(exc)
        ):
            delays = self.retry_timeout_delays
        if not delays:
            return 0
        index = min(max(attempt - 1, 0), len(delays) - 1)
        return int(delays[index])

    def _append_unique(self, models: list[str], model_id: str) -> None:
        if model_id and model_id not in models:
            models.append(model_id)

    def _format_http_error(self, code: int, detail: str) -> str:
        message = f"HTTP {code}: {detail}"
        if code == 499:
            message += (
                "\n诊断：Provider 记录 499 通常表示客户端先关闭了请求。"
                "如果本地同时显示读取响应超时，说明程序等待响应超过超时秒数后断开连接。"
                "请在设置页调大“超时秒数”，或降低最大 token、换更快模型、稍后重试。"
            )
        if code == 503:
            message += (
                "\n诊断：HTTP 503 通常表示 Provider 或上游模型服务暂时不可用、过载、网关超时，"
                "也可能是当前请求太重或兼容字段不被该 Provider 接受。"
                "审稿会发送正文、上下文和结构化审稿要求，负载通常比测试连接更高。"
                "请稍后重试，或降低最大 token、换更快/更稳定的审稿模型、减少待审正文长度。"
            )
            if "format_type_mismatch" in detail or "no_available_providers" in detail:
                message += "如果错误包含 format_type_mismatch，请在设置页确认 API 类型是否应使用 /responses。"
        if code == 403 and "1010" in detail:
            message += (
                "\n诊断：响应包含 1010，可能是提供商网关或 Cloudflare 访问规则拦截、"
                "base_url 错误、API key 权限不足，或当前来源/IP 被限制。"
                "请检查 base_url 是否为 OpenAI-compatible API 地址、确认 API key 权限，"
                "并查看提供商后台的访问规则或来源限制。"
            )
        return message

    def _format_timeout_error(self) -> str:
        default_timeout = DEFAULT_LLM_CONFIG["timeout_seconds"]
        timeout = int(self.config.get("timeout_seconds", default_timeout) or default_timeout)
        return (
            f"读取响应超时：本地程序等待 Provider 响应超过 {timeout} 秒后断开连接。"
            "如果 Provider 后台显示状态码 499，通常表示客户端先关闭了请求，而不是空包。"
            "请在设置页把“超时秒数”调大，或降低最大 token、换更快模型、稍后重试。"
        )
