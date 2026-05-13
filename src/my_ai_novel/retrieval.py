from __future__ import annotations

import json
import math
from typing import Any

from .llm import LLMClient, LLMError
from .storage import NovelStore
from .style_tags import selected_tag_definitions
from .world_modules import extract_required_state_modules


WORLD_KIND_PRIORITY = {
    "organization": 0,
    "character": 0,
    "foreshadowing": 1,
    "location": 1,
    "timeline_event": 1,
}


def world_kind_priority(kind: str) -> int:
    return WORLD_KIND_PRIORITY.get(kind, 2)


def _tokens(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    parts = set(normalized.split())
    parts.update(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    return parts


def _score(query: str, item: dict[str, Any]) -> int:
    haystack = " ".join(
        str(item.get(key, "")) for key in ("name", "summary", "details_json", "tags", "status")
    )
    return len(_tokens(query) & _tokens(haystack))


def rank_world_items(items: list[dict[str, Any]], query: str = "") -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            _score(query, item),
            -world_kind_priority(str(item.get("kind", ""))),
            str(item.get("updated_at", "")),
        ),
        reverse=True,
    )


def keyword_search(
    store: NovelStore,
    project_id: int,
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    items = store.list_world_items(project_id)
    ranked = rank_world_items(items, query)
    return [item for item in ranked if _score(query, item) > 0][:limit]


def tag_search(
    store: NovelStore,
    project_id: int,
    tags: list[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    wanted = {tag.strip().lower() for tag in tags if tag.strip()}
    if not wanted:
        return []
    results = []
    for item in store.list_world_items(project_id):
        item_tags = {tag.strip().lower() for tag in str(item.get("tags", "")).split(",") if tag.strip()}
        if wanted & item_tags:
            results.append(item)
    return rank_world_items(results, " ".join(tags))[:limit]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def vector_search(
    store: NovelStore,
    llm: LLMClient,
    project_id: int,
    query: str,
    limit: int = 8,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        query_vector = llm.embed([query])[0]
    except Exception as exc:  # noqa: BLE001 - retrieval must degrade when embeddings are unavailable
        return [], str(exc)
    scored = []
    for item in store.list_world_items(project_id):
        raw = item.get("embedding_json")
        if not raw:
            continue
        try:
            vector = json.loads(raw)
        except json.JSONDecodeError:
            continue
        scored.append((_cosine(query_vector, vector), item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for score, item in scored if score > 0][:limit], None


def retrieve_context(
    store: NovelStore,
    project_id: int,
    chapter_id: int | None,
    section_id: int | None,
    query: str,
    llm: LLMClient | None = None,
    limit: int = 12,
) -> dict[str, Any]:
    section = store.get_section(section_id) if section_id else None
    chapter = store.get_chapter(chapter_id) if chapter_id else None
    tags = []
    if section:
        tags.extend(str(section.get("location", "")).split())
        try:
            tags.extend(json.loads(section.get("characters_json") or "[]"))
        except json.JSONDecodeError:
            pass
    found: list[dict[str, Any]] = []
    notes = []
    found.extend(keyword_search(store, project_id, query, limit=limit))
    found.extend(tag_search(store, project_id, tags, limit=limit))
    if llm:
        vector_results, vector_error = vector_search(store, llm, project_id, query, limit=limit)
        found.extend(vector_results)
        if vector_error:
            notes.append(f"向量检索未启用：{vector_error}")
    else:
        notes.append("向量检索未启用：未传入 LLM client")
    deduped = []
    seen = set()
    for item in found:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        deduped.append(item)
    deduped = rank_world_items(deduped, query)
    forbidden = store.list_world_items(project_id, "forbidden")
    recent_plot = store.list_versions(project_id, chapter_id=chapter_id)[0:5] if chapter_id else []
    project = store.get_project(project_id) or {}
    active_tags = selected_tag_definitions(project)
    state_modules = extract_required_state_modules(deduped + forbidden, active_tags)
    return {
        "long_term": deduped[:limit],
        "state_modules": state_modules,
        "active_style_tags": active_tags,
        "recent_plot": recent_plot,
        "current_scene": {"chapter": chapter, "section": section},
        "forbidden": forbidden[:limit],
        "retrieval_notes": notes,
    }


def build_context_pack(*args, **kwargs) -> dict[str, Any]:
    return retrieve_context(*args, **kwargs)
