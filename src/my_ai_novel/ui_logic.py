from __future__ import annotations

import re
from typing import Any

from .models import DEFAULT_LLM_CONFIG


STATUS_LABELS = {
    "unplanned": "未规划",
    "planned": "已规划",
    "generated": "已生成",
    "review_pending": "待审",
    "finalized": "已定稿",
}

WORLD_KIND_LABELS = {
    "character": "角色卡",
    "location": "地点设定",
    "organization": "组织/势力",
    "rule": "规则设定",
    "timeline_event": "时间线",
    "foreshadowing": "伏笔",
    "forbidden": "禁止事项",
}
WORLD_LABEL_TO_KIND = {label: kind for kind, label in WORLD_KIND_LABELS.items()}
WORLD_LABEL_TO_KIND["人物设定"] = "character"

LLM_CONFIG_FIELDS = [
    ("Base URL", "base_url"),
    ("API 类型", "api_type"),
    ("API Key", "api_key"),
    ("代理地址", "proxy_url"),
    ("正文模型", "chat_model"),
    ("架构/审稿模型", "review_model"),
    ("Embedding 模型", "embedding_model"),
    ("模型候选(每行一个)", "model_candidates"),
    ("超时秒数", "timeout_seconds"),
    ("最大 token", "max_tokens"),
    ("Temperature", "temperature"),
    ("Top-P", "top_p"),
    ("Top-K", "top_k"),
    ("Presence Penalty", "presence_penalty"),
    ("Frequency Penalty", "frequency_penalty"),
]

API_TYPE_CHOICES = {
    "responses": "/responses",
    "chat_completions": "/chat/completions",
}
API_TYPE_VALUES = tuple(API_TYPE_CHOICES.values())
API_TYPE_LABELS_TO_CONFIG = {label: key for key, label in API_TYPE_CHOICES.items()}

PROJECT_TEXT_FIELDS = [
    ("总世界书", "world_summary"),
    ("风格说明", "writing_style_guide"),
    ("总体概括", "global_concept"),
]


def parse_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_positive_count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 0 else None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "").replace("，", "").replace(" ", "").lower()
    unit_match = re.search(r"(\d+(?:\.\d+)?)(?:万|w)", text)
    if unit_match:
        number = int(float(unit_match.group(1)) * 10000)
        return number if number > 0 else None
    number_match = re.search(r"\d+(?:\.\d+)?", text)
    if not number_match:
        return None
    number = int(float(number_match.group(0)))
    return number if number > 0 else None


def calculate_default_section_target_words(length_target: Any, estimated_total_sections: Any) -> str:
    total_words = parse_positive_count(length_target)
    section_count = parse_positive_count(estimated_total_sections)
    if not total_words or not section_count:
        return ""
    return str(max(1, round(total_words / section_count)))


def world_kind_label(kind: str) -> str:
    return WORLD_KIND_LABELS.get(kind, kind)


def world_kind_value(label_or_kind: str) -> str:
    return WORLD_LABEL_TO_KIND.get(label_or_kind, label_or_kind)


def parse_model_candidates(text: str) -> list[str]:
    return parse_lines(text)


def llm_config_field_keys() -> list[str]:
    return [key for _label, key in LLM_CONFIG_FIELDS]


def config_var_value(var: Any) -> str:
    try:
        return var.get("1.0", "end").strip()
    except TypeError:
        return var.get().strip()


def default_api_type() -> str:
    return str(DEFAULT_LLM_CONFIG.get("api_type", "responses") or "responses")


def api_type_display_value(value: Any) -> str:
    api_type = str(value or default_api_type()).strip()
    return API_TYPE_CHOICES.get(api_type, api_type)


def normalize_api_type(value: Any) -> str:
    api_type = str(value or default_api_type()).strip()
    return API_TYPE_LABELS_TO_CONFIG.get(api_type, api_type) or default_api_type()


def _is_blank_like(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"", "none", "null", "nil", "undefined"}


def build_llm_config_from_vars(config_vars: dict[str, Any]) -> dict[str, Any]:
    config = dict(DEFAULT_LLM_CONFIG)
    config.setdefault("api_type", default_api_type())
    for key, var in config_vars.items():
        config[key] = config_var_value(var)
    config["api_type"] = normalize_api_type(config.get("api_type"))
    config["model_candidates"] = "\n".join(parse_model_candidates(str(config.get("model_candidates", ""))))
    for key in ["timeout_seconds", "max_tokens"]:
        raw_value = config.get(key)
        if _is_blank_like(raw_value):
            raw_value = DEFAULT_LLM_CONFIG[key]
        config[key] = int(raw_value)
    for key in ["temperature", "top_p", "presence_penalty", "frequency_penalty"]:
        raw_value = config.get(key)
        if _is_blank_like(raw_value):
            raw_value = DEFAULT_LLM_CONFIG[key]
        config[key] = float(raw_value)
    top_k_value = config.get("top_k")
    config["top_k"] = None if _is_blank_like(top_k_value) else int(top_k_value)
    return config


def is_embedding_model(model_name: str) -> bool:
    lowered = model_name.lower()
    return "embed" in lowered or "embedding" in lowered


def model_scan_autofill(current: dict[str, str], models: list[str]) -> dict[str, str]:
    updates: dict[str, str] = {}
    first_chat_model = next((model for model in models if not is_embedding_model(model)), "")
    first_embedding_model = next((model for model in models if is_embedding_model(model)), "")
    if not current.get("chat_model", "").strip() and first_chat_model:
        updates["chat_model"] = first_chat_model
    if not current.get("review_model", "").strip() and first_chat_model:
        updates["review_model"] = first_chat_model
    if not current.get("embedding_model", "").strip() and first_embedding_model:
        updates["embedding_model"] = first_embedding_model
    return updates


def format_model_discovery_result(result: dict[str, Any]) -> str:
    models = [str(model) for model in result.get("models", []) if str(model)]
    source = str(result.get("source", "") or "unknown")
    warning = str(result.get("warning", "") or "").strip()
    lines = [f"来源: {source}"]
    if warning:
        lines.append(f"警告: {warning}")
    lines.append("模型列表:")
    lines.extend(models or ["未发现可用模型"])
    return "\n".join(lines)


def build_world_context_query(values: dict[str, str]) -> str:
    keys = ["title", "story_time", "location", "characters", "goal", "scene", "conflict", "emotion_shift"]
    return "\n".join(str(values.get(key, "")).strip() for key in keys if str(values.get(key, "")).strip())


def format_world_context_pack(pack: dict[str, Any]) -> str:
    items = pack.get("long_term", [])
    forbidden = pack.get("forbidden", [])
    notes = pack.get("retrieval_notes", [])
    lines = ["写作参考资料"]
    if not items:
        lines.append("未检索到相关资料。")
    for item in items:
        label = world_kind_label(str(item.get("kind", "")))
        name = str(item.get("name", "")).strip() or "未命名"
        tags = str(item.get("tags", "")).strip()
        summary = str(item.get("summary", "")).strip()
        lines.append(f"[{label}] {name}" + (f" | {tags}" if tags else ""))
        if summary:
            lines.append(summary)
    if forbidden:
        lines.append("")
        lines.append("禁止事项")
        for item in forbidden:
            name = str(item.get("name", "")).strip() or "未命名"
            summary = str(item.get("summary", "")).strip()
            lines.append(f"- {name}" + (f"：{summary}" if summary else ""))
    if notes:
        lines.append("")
        lines.append("检索备注")
        lines.extend(f"- {note}" for note in notes)
    return "\n".join(lines)


def format_character_card_choice(item: dict[str, Any]) -> str:
    name = str(item.get("name", "")).strip() or "未命名"
    tags = str(item.get("tags", "")).strip()
    return f"{name} | {tags}" if tags else name


def format_location_choice(item: dict[str, Any]) -> str:
    name = str(item.get("name", "")).strip() or "未命名"
    tags = str(item.get("tags", "")).strip()
    return f"{name} | {tags}" if tags else name


def selected_character_card_names(rows: list[dict[str, Any]], indices: list[int] | tuple[int, ...]) -> list[str]:
    names = []
    for index in indices:
        if 0 <= index < len(rows):
            name = str(rows[index].get("name", "")).strip()
            if name:
                names.append(name)
    return names


def selected_location_name(rows: list[dict[str, Any]], indices: list[int] | tuple[int, ...]) -> str:
    for index in indices:
        if 0 <= index < len(rows):
            name = str(rows[index].get("name", "")).strip()
            if name:
                return name
    return ""


def project_index_by_id(projects: list[dict[str, Any]], project_id: int | None) -> int | None:
    if project_id is None:
        return None
    for index, project in enumerate(projects):
        if int(project.get("id", 0) or 0) == int(project_id):
            return index
    return None


def format_export_success_message(path: Any) -> str:
    return f"全书 Word 已导出：{path}"


def latest_outline_index(rows: list[dict[str, Any]]) -> int | None:
    return 0 if rows else None
