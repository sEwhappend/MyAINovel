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
    "timeline_event": "事件",
    "foreshadowing": "伏笔",
    "forbidden": "禁止事项",
}
WORLD_LABEL_TO_KIND = {label: kind for kind, label in WORLD_KIND_LABELS.items()}
WORLD_LABEL_TO_KIND["人物设定"] = "character"
WORLD_LABEL_TO_KIND["时间线"] = "timeline_event"

LLM_CONFIG_FIELDS = [
    ("Base URL", "base_url"),
    ("API 提供商", "provider"),
    ("API 类型", "api_type"),
    ("API Key", "api_key"),
    ("代理地址", "proxy_url"),
    ("正文模型", "chat_model"),
    ("架构/审稿模型", "review_model"),
    ("文风模型(可选)", "style_model"),
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

PROVIDER_CHOICES = {
    "custom": "自定义",
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
}
PROVIDER_VALUES = tuple(PROVIDER_CHOICES.values())
PROVIDER_LABELS_TO_CONFIG = {label: key for key, label in PROVIDER_CHOICES.items()}

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


def default_provider() -> str:
    return str(DEFAULT_LLM_CONFIG.get("provider", "custom") or "custom")


def provider_display_value(value: Any) -> str:
    provider = str(value or default_provider()).strip()
    return PROVIDER_CHOICES.get(provider, PROVIDER_CHOICES.get(default_provider(), provider))


def normalize_provider(value: Any) -> str:
    provider = str(value or default_provider()).strip()
    if provider in PROVIDER_CHOICES:
        return provider
    return PROVIDER_LABELS_TO_CONFIG.get(provider, default_provider()) or default_provider()


# 各提供商固定/默认使用的 API 类型；custom 不强制（返回 None，保留用户选择）。
PROVIDER_API_TYPE = {
    "deepseek": "chat_completions",
    "openai": "responses",
}


def provider_default_api_type(value: Any) -> str | None:
    """选某提供商时应切换到的 api_type；返回 None 表示不强制切换。

    DeepSeek 这类只支持 /chat/completions 的提供商会返回 chat_completions。
    """
    return PROVIDER_API_TYPE.get(normalize_provider(value))


def _is_blank_like(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"", "none", "null", "nil", "undefined"}


def build_llm_config_from_vars(config_vars: dict[str, Any]) -> dict[str, Any]:
    config = dict(DEFAULT_LLM_CONFIG)
    config.setdefault("api_type", default_api_type())
    for key, var in config_vars.items():
        config[key] = config_var_value(var)
    config["api_type"] = normalize_api_type(config.get("api_type"))
    config["provider"] = normalize_provider(config.get("provider"))
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


def format_style_cost(cost: dict[str, Any] | None) -> str:
    data = cost or {}
    chunks = int(data.get("sampled_chunks", 0) or 0)
    tokens = int(data.get("approx_input_tokens", 0) or 0)
    if chunks <= 0:
        return "预估：暂无样本，导入 txt/epub 后显示成本"
    return f"预估：抽样 {chunks} 段，约 {tokens:,} input tokens"


def _style_section_text(section: Any, limit: int = 4) -> str:
    """把画像里某个分节(dict)的非空文本/列表值拼成一行，便于概览展示。"""
    if not isinstance(section, dict):
        return ""
    parts: list[str] = []
    for value in section.values():
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, list):
            parts.extend(str(item).strip() for item in value if str(item).strip())
        if len(parts) >= limit:
            break
    return "｜".join(parts[:limit])


def format_style_profile_overview(profile: dict[str, Any] | None) -> str:
    if not profile:
        return "尚未生成文风画像。导入样本后点“分析文风”。"
    lines: list[str] = []
    summary = str(profile.get("summary", "")).strip()
    if summary:
        lines.append("【摘要】" + summary)
    for key, label in (
        ("narrative", "叙述"),
        ("sentence", "句式"),
        ("dialogue", "对白"),
        ("description", "描写"),
        ("emotion", "情绪"),
        ("pacing", "节奏"),
    ):
        text = _style_section_text(profile.get(key))
        if text:
            lines.append(f"【{label}】{text}")
    metrics = profile.get("metrics") or {}
    if isinstance(metrics, dict) and metrics:
        lines.append(
            "【统计】平均句长 {len}｜对白占比 {dlg}｜引号 {quote}".format(
                len=metrics.get("avg_sentence_len", "-"),
                dlg=metrics.get("dialogue_ratio", "-"),
                quote=metrics.get("quote_style", "-"),
            )
        )
    sampling = profile.get("sampling") or {}
    if isinstance(sampling, dict) and sampling:
        lines.append(
            "【采样参数】temperature {t}｜top_p {p}｜presence {pp}｜frequency {fp}".format(
                t=sampling.get("temperature", "-"),
                p=sampling.get("top_p", "-"),
                pp=sampling.get("presence_penalty", "-"),
                fp=sampling.get("frequency_penalty", "-"),
            )
        )
    rules = profile.get("anti_ai_rules") or []
    if isinstance(rules, list) and rules:
        lines.append("【反 AI 味】" + "；".join(str(rule) for rule in rules[:6]))
    guides = profile.get("rewrite_guides") or []
    if isinstance(guides, list) and guides:
        lines.append("【改写顺序】" + "；".join(str(guide) for guide in guides[:6]))
    sources = profile.get("source_files") or []
    if isinstance(sources, list) and sources:
        names = "、".join(str(item.get("name", "")) for item in sources if isinstance(item, dict) and item.get("name"))
        if names:
            lines.append("【来源】" + names)
    return "\n".join(lines) if lines else "文风画像为空。"


def style_guide_text_from_profile(profile: dict[str, Any] | None) -> str:
    """把文风画像压成可写入项目“风格说明”的文本。"""
    data = profile or {}
    parts: list[str] = []
    summary = str(data.get("summary", "")).strip()
    if summary:
        parts.append(summary)
    for key, prefix in (("rewrite_guides", "改写倾向"), ("anti_ai_rules", "避免")):
        values = data.get(key) or []
        if isinstance(values, list):
            for value in values:
                text = str(value).strip()
                if text:
                    parts.append(f"- {prefix}：{text}")
    return "\n".join(parts)


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
    return f"全书 Word 已分节导出到：{path}"


def latest_outline_index(rows: list[dict[str, Any]]) -> int | None:
    return 0 if rows else None
