from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


CHAPTER_STATUSES = {"unplanned", "planned", "generated", "review_pending", "finalized"}
VERSION_STATUSES = {"usable", "discarded", "needs_edit", "final"}
WORLD_ITEM_KINDS = {
    "character",
    "location",
    "organization",
    "rule",
    "timeline_event",
    "foreshadowing",
    "forbidden",
}


DEFAULT_LLM_CONFIG = {
    "name": "default",
    "base_url": "",
    "api_key": "",
    "api_type": "responses",
    "provider": "custom",
    "disable_thinking": False,
    "chat_model": "",
    "review_model": "",
    "embedding_model": "",
    "style_model": "",
    "model_candidates": "",
    "proxy_url": "",
    "timeout_seconds": 180,
    "max_tokens": 2000,
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": None,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
}


@dataclass
class LLMConfig:
    name: str = "default"
    base_url: str = ""
    api_key: str = ""
    api_type: str = "responses"
    provider: str = "custom"
    disable_thinking: bool = False
    chat_model: str = ""
    review_model: str = ""
    embedding_model: str = ""
    style_model: str = ""
    model_candidates: str = ""
    proxy_url: str = ""
    timeout_seconds: int = 180
    max_tokens: int = 2000
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int | None = None
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_status(status: str) -> str:
    if status not in CHAPTER_STATUSES:
        raise ValueError(f"invalid status: {status}")
    return status


def validate_version_status(status: str) -> str:
    if status not in VERSION_STATUSES:
        raise ValueError(f"invalid version status: {status}")
    return status


def validate_world_kind(kind: str) -> str:
    if kind not in WORLD_ITEM_KINDS:
        raise ValueError(f"invalid world item kind: {kind}")
    return kind
