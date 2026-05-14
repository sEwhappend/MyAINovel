from __future__ import annotations

import json
import re
from typing import Any

from .llm import LLMClient, parse_json_response
from .models import WORLD_ITEM_KINDS, validate_world_kind
from .prompts import SCHEMA_HINTS, build_messages, build_project_writing_constraints
from .retrieval import retrieve_context
from .review import build_rewrite_request, validate_review_issues
from .storage import NovelStore
from .world_modules import character_basic_fields_from_details, merge_module_patches


DEFAULT_SECTION_TARGET_WORDS = 1200
MIN_SECTION_TARGET_WORDS = 100


def _append_to_first_system_before_user(messages: list[dict[str, str]], content: str) -> None:
    first_user_index = next(
        (index for index, message in enumerate(messages) if message.get("role") == "user"),
        len(messages),
    )
    system_index = next(
        (
            index
            for index, message in enumerate(messages[:first_user_index])
            if message.get("role") == "system"
        ),
        None,
    )
    if system_index is not None:
        current = str(messages[system_index].get("content", "") or "")
        messages[system_index] = {
            **messages[system_index],
            "content": f"{current}\n\n{content}" if current else content,
        }
        return
    messages.insert(first_user_index, {"role": "system", "content": content})


def parse_length_target(value: Any) -> int | None:
    """Parse project length targets such as 80000字, 8万字, 约10万, or 10w."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        words = int(value)
        return words if words > 0 else None

    text = str(value).strip().lower()
    if not text:
        return None
    text = text.replace(",", "").replace("，", "").replace(" ", "")
    unit_match = re.search(r"(\d+(?:\.\d+)?)(?:万|w)", text)
    if unit_match:
        words = int(float(unit_match.group(1)) * 10000)
        return words if words > 0 else None
    number_match = re.search(r"\d+(?:\.\d+)?", text)
    if number_match:
        words = int(float(number_match.group(0)))
        return words if words > 0 else None
    return None


class NovelPipeline:
    def __init__(self, store: NovelStore, llm: LLMClient) -> None:
        self.store = store
        self.llm = llm

    def expand_global_concept(self, project_id: int) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        result = self._outline_expansion_result(
            self._call(
                "global_architect",
                self._outline_expansion_payload(project_id, project),
            )
        )
        content = result.get("expanded_outline") or json.dumps(result, ensure_ascii=False, indent=2)
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "kind": "global_outline",
                "label": "丰满总体框架",
                "content": content,
                "metadata": result,
            }
        )
        return {"version_id": version_id, **result}

    def expand_global_concept_streaming(self, project_id: int, on_delta=None) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        payload = self._with_project_writing_constraints(
            self._outline_expansion_payload(project_id, project)
        )
        messages = build_messages("global_architect", payload, output_json=False)
        _append_to_first_system_before_user(
            messages,
            "本次为流式输出：直接输出全书故事大纲正文。不要输出 JSON、代码块、字段名、解释、寒暄、章节列表、小节列表或字数分配。不要把内容写成设定清单；用自然段讲清楚整本小说的故事走向。",
        )
        config = getattr(self.llm, "config", {})
        model = config.get("review_model") or config.get("chat_model") or ""
        chunks: list[str] = []

        def collect(delta: str) -> None:
            chunks.append(delta)
            if on_delta:
                on_delta(delta)

        try:
            text = self.llm.stream_text(model, messages, collect)
            raw = (text or "".join(chunks)).strip()
            if not raw:
                raise ValueError("全书故事大纲为空")
            result = self._outline_expansion_result({"expanded_outline": raw, "source": "streaming_text"})
            self.store.save_llm_call_log(
                {
                    "project_id": project_id,
                    "agent_name": "global_architect",
                    "model": model,
                    "request_summary": self._request_summary(payload),
                    "response_summary": raw[:500],
                    "success": True,
                }
            )
        except Exception as exc:
            self.store.save_llm_call_log(
                {
                    "project_id": project_id,
                    "agent_name": "global_architect",
                    "model": model,
                    "request_summary": self._request_summary(payload),
                    "response_summary": "".join(chunks)[:500],
                    "success": False,
                    "error": str(exc),
                }
            )
            raise
        content = result.get("expanded_outline") or json.dumps(result, ensure_ascii=False, indent=2)
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "kind": "global_outline",
                "label": "丰满总体框架",
                "content": content,
                "metadata": result,
            }
        )
        return {"version_id": version_id, **result}

    def confirm_outline_split(self, project_id: int, version_id: int) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        version = self._require(self.store.get_version(version_id), "version")
        metadata = self._loads(version.get("metadata_json")) or self._loads(version.get("content"))
        split_metadata = self._outline_split_metadata(project, version, metadata)
        return self._apply_outline_split(project_id, project, split_metadata)

    def confirm_outline_split_streaming(self, project_id: int, version_id: int, on_delta=None) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        version = self._require(self.store.get_version(version_id), "version")
        metadata = self._loads(version.get("metadata_json")) or self._loads(version.get("content"))
        if isinstance(metadata.get("chapters"), list):
            return self._apply_outline_split(project_id, project, metadata)

        payload = self._outline_split_payload(project, version, metadata)
        messages = build_messages("outline_splitter", self._with_project_writing_constraints(payload))
        _append_to_first_system_before_user(
            messages,
            "输出必须是 JSON object，字段要求："
            + json.dumps(SCHEMA_HINTS["outline_splitter"], ensure_ascii=False),
        )
        config = getattr(self.llm, "config", {})
        model = config.get("chat_model") or config.get("review_model") or ""
        chunks: list[str] = []

        def collect(delta: str) -> None:
            chunks.append(delta)
            if on_delta:
                on_delta(delta)

        try:
            text = self.llm.stream_text(model, messages, collect)
            raw = text or "".join(chunks)
            split_metadata = parse_json_response(raw)
            self.store.save_llm_call_log(
                {
                    "project_id": project_id,
                    "agent_name": "outline_splitter",
                    "model": model,
                    "request_summary": self._request_summary(self._with_project_writing_constraints(payload)),
                    "response_summary": raw[:500],
                    "success": True,
                }
            )
        except Exception as exc:
            self.store.save_llm_call_log(
                {
                    "project_id": project_id,
                    "agent_name": "outline_splitter",
                    "model": model,
                    "request_summary": self._request_summary(self._with_project_writing_constraints(payload)),
                    "response_summary": "".join(chunks)[:500],
                    "success": False,
                    "error": str(exc),
                }
            )
            raise
        self._save_outline_split_version(project_id, split_metadata)
        return self._apply_outline_split(project_id, project, split_metadata)

    def _apply_outline_split(
        self,
        project_id: int,
        project: dict[str, Any],
        split_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        chapters = split_metadata.get("chapters", [])
        self._apply_section_word_budget(chapters, parse_length_target(project.get("length_target")))
        self.store.reset_outline_split_content(project_id)
        created_chapters = 0
        created_sections = 0
        for chapter_data in chapters:
            chapter_id = self.store.save_chapter(project_id, {**chapter_data, "status": "planned"})
            created_chapters += 1
            for section_data in chapter_data.get("sections", []):
                self.store.save_section(chapter_id, {**section_data, "status": "planned"})
                created_sections += 1
        world_items = 0
        for item in self._outline_world_item_candidates(split_metadata):
            self.store.upsert_world_item(project_id, item)
            world_items += 1
        return {"chapters": created_chapters, "sections": created_sections, "world_items": world_items}

    def enrich_world_item(self, project_id: int, item_id: int, direction: str = "") -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        item = self._require(self.store.get_world_item(project_id, item_id), "world_item")
        payload = {"project": project, "world_item": item}
        if str(direction or "").strip():
            payload["enrich_direction"] = str(direction or "").strip()
        result = self._call("world_item_enricher", payload)
        enriched = {
            "id": item_id,
            "kind": item["kind"],
            "name": str(result.get("name", item.get("name", "")) or "").strip() or item["name"],
            "summary": result.get("summary", item.get("summary", "")),
            "details": self._merged_details(item.get("details_json"), result.get("details")),
            "tags": self._merge_csv(item.get("tags", ""), result.get("tags", "AI补全")),
            "status": result.get("status") or item.get("status") or "active",
        }
        return {"world_item_id": item_id, "world_item": enriched, **result}

    def generate_world_item(self, project_id: int, kind: str) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        kind = validate_world_kind(kind)
        payload = {"project": project, "current_kind": kind}
        outline = self._latest_outline_snapshot(project_id)
        if outline:
            payload["current_outline"] = outline
        result = self._call("world_item_creator", payload)
        created = {
            "kind": kind,
            "name": str(result.get("name", "") or "").strip() or f"新{kind}",
            "summary": str(result.get("summary", "") or "").strip(),
            "details": result.get("details") if isinstance(result.get("details"), dict) else {},
            "tags": str(result.get("tags", "") or "").strip(),
            "status": str(result.get("status", "") or "candidate").strip() or "candidate",
        }
        item_id = self.store.save_world_item(project_id, created)
        saved = self.store.get_world_item(project_id, item_id) or {**created, "id": item_id}
        return {"world_item_id": item_id, "world_item": saved, **result}

    def generate_default_main_character(self, project_id: int) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        result = self._call("main_character_generator", {"project": project})
        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        details = character_basic_fields_from_details(details) | {
            key: value
            for key, value in details.items()
            if key not in {"identity", "personality", "motivation", "speech_style", "role_flags"}
        }
        role_flags = details.get("role_flags")
        if not isinstance(role_flags, dict) or not any(role_flags.values()):
            details["role_flags"] = {
                "protagonist": True,
                "pov": False,
                "ensemble_main": False,
                "supporting": False,
            }
        details.setdefault("modules", {})
        item = {
            "kind": "character",
            "name": str(result.get("name", "") or "").strip() or "默认主角",
            "summary": str(result.get("summary", "") or "").strip(),
            "details": details,
            "tags": self._merge_csv(result.get("tags", ""), "主角,AI生成"),
            "status": result.get("status") or "candidate",
        }
        item_id = self.store.save_world_item(project_id, item)
        saved = self.store.get_world_item(project_id, item_id) or {**item, "id": item_id}
        return {"world_item_id": item_id, "world_item": saved, **result}

    def write_chapter_memory(self, project_id: int, chapter_id: int) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        chapter = self._require(self.store.get_chapter(chapter_id), "chapter")
        finalized_sections = self.store.list_finalized_section_versions(chapter_id)
        if not finalized_sections:
            raise ValueError("章节没有已定稿小节，不能反写章末记忆")
        result = self._call(
            "chapter_memory_writer",
            {
                "project": project,
                "chapter": chapter,
                "finalized_sections": finalized_sections,
                "called_world_items": self._chapter_retrieved_world_items(project_id, chapter_id),
            },
        )
        saved_ids = [
            self.store.upsert_world_item(project_id, item)
            for item in self._chapter_memory_world_items(result)
        ]
        return {
            "chapter_id": chapter_id,
            "world_items": len(saved_ids),
            "world_item_ids": saved_ids,
            "notes": result.get("notes", ""),
        }

    def generate_chapter_plan(self, project_id: int, chapter_id: int) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        chapter = self._require(self.store.get_chapter(chapter_id), "chapter")
        context = self._with_retrieval_trace(
            retrieve_context(self.store, project_id, chapter_id, None, chapter.get("goal", ""), self.llm)
        )
        result = self._call("chapter_architect", {"project": project, "chapter": chapter, "context": context})
        outline = result.get("chapter_plan") or json.dumps(result, ensure_ascii=False, indent=2)
        self.store.save_chapter(project_id, {**chapter, "outline": outline, "goal": result.get("goal", chapter.get("goal", "")), "status": "planned"})
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "kind": "chapter_plan",
                "label": "章节架构",
                "content": outline,
                "metadata": result,
            }
        )
        return {"version_id": version_id, **result}

    def generate_section_plan(self, project_id: int, section_id: int) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        section = self._require(self.store.get_section(section_id), "section")
        chapter = self._require(self.store.get_chapter(section["chapter_id"]), "chapter")
        context = self._with_retrieval_trace(
            retrieve_context(self.store, project_id, chapter["id"], section_id, section.get("goal", ""), self.llm)
        )
        result = self._call("section_planner", {"project": project, "chapter": chapter, "section": section, "context": context})
        planned = result.get("section") or result
        self.store.save_section(chapter["id"], {**section, **planned, "status": "planned"})
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter["id"],
                "section_id": section_id,
                "kind": "section_plan",
                "label": "小节规划",
                "content": json.dumps(planned, ensure_ascii=False, indent=2),
                "metadata": result,
            }
        )
        return {"version_id": version_id, **result}

    def direct_scene(self, project_id: int, section_id: int) -> dict[str, Any]:
        return self._section_step(project_id, section_id, "scene_director", "scene_plan", "场景导演")

    def generate_dialogue_psychology(self, project_id: int, section_id: int) -> dict[str, Any]:
        return self._section_step(project_id, section_id, "dialogue_psychology", "dialogue_rules", "对白心理")

    def write_section_draft(self, project_id: int, section_id: int, mode: str = "rough") -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        section = self._require(self.store.get_section(section_id), "section")
        if section.get("status") == "finalized":
            raise ValueError("小节已定稿，不能覆盖生成")
        chapter = self._require(self.store.get_chapter(section["chapter_id"]), "chapter")
        context = self._with_retrieval_trace(
            retrieve_context(self.store, project_id, chapter["id"], section_id, section.get("goal", ""), self.llm)
        )
        result = self._call(
            "draft_writer",
            {"project": project, "chapter": chapter, "section": section, "context": context, "mode": mode},
        )
        content = result.get("content", "")
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter["id"],
                "section_id": section_id,
                "kind": "draft",
                "label": "粗稿" if mode == "rough" else mode,
                "content": content,
                "metadata": self._metadata_with_trace(result, context),
            }
        )
        self.store.update_section_status(section_id, "generated")
        return {"version_id": version_id, **result}

    def write_section_draft_streaming(
        self,
        project_id: int,
        section_id: int,
        mode: str = "rough",
        on_delta=None,
    ) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        section = self._require(self.store.get_section(section_id), "section")
        if section.get("status") == "finalized":
            raise ValueError("小节已定稿，不能覆盖生成")
        chapter = self._require(self.store.get_chapter(section["chapter_id"]), "chapter")
        context = self._with_retrieval_trace(
            retrieve_context(self.store, project_id, chapter["id"], section_id, section.get("goal", ""), self.llm)
        )
        payload = self._with_project_writing_constraints(
            {"project": project, "chapter": chapter, "section": section, "context": context, "mode": mode}
        )
        messages = build_messages("draft_writer", payload, output_json=False)
        _append_to_first_system_before_user(messages, "这次只输出正文内容本身，不要输出 JSON、标题、说明或寒暄。")
        model = self.llm.config.get("chat_model") or self.llm.config.get("review_model") or ""
        chunks: list[str] = []

        def collect(delta: str) -> None:
            chunks.append(delta)
            if on_delta:
                on_delta(delta)

        try:
            content = self.llm.stream_text(model, messages, collect)
            result = {"content": content or "".join(chunks), "notes": "streaming"}
            self.store.save_llm_call_log(
                {
                    "project_id": project_id,
                    "agent_name": "draft_writer",
                    "model": model,
                    "request_summary": self._request_summary(payload),
                    "response_summary": result["content"][:500],
                    "success": True,
                }
            )
        except Exception as exc:
            self.store.save_llm_call_log(
                {
                    "project_id": project_id,
                    "agent_name": "draft_writer",
                    "model": model,
                    "request_summary": self._request_summary(payload),
                    "response_summary": "",
                    "success": False,
                    "error": str(exc),
                }
            )
            raise
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter["id"],
                "section_id": section_id,
                "kind": "draft",
                "label": "粗稿" if mode == "rough" else mode,
                "content": result["content"],
                "metadata": self._metadata_with_trace(result, context),
            }
        )
        self.store.update_section_status(section_id, "generated")
        return {"version_id": version_id, **result}

    def review_section(self, project_id: int, section_id: int, version_id: int) -> dict[str, Any]:
        project = self._require(self.store.get_project(project_id), "project")
        section = self._require(self.store.get_section(section_id), "section")
        chapter = self._require(self.store.get_chapter(section["chapter_id"]), "chapter")
        version = self._require(self.store.get_version(version_id), "version")
        context = self._with_retrieval_trace(
            retrieve_context(self.store, project_id, chapter["id"], section_id, section.get("goal", ""), self.llm)
        )
        result = self._call("reviewer", {"project": project, "section": section, "draft": version["content"], "context": context})
        issues = validate_review_issues(result)
        saved_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter["id"],
                "section_id": section_id,
                "kind": "review",
                "label": "审稿意见",
                "content": json.dumps({"issues": issues, "summary": result.get("summary", "")}, ensure_ascii=False, indent=2),
                "metadata": self._metadata_with_trace(
                    {"issues": issues, "summary": result.get("summary", "")},
                    context,
                ),
            }
        )
        self.store.update_section_status(section_id, "review_pending")
        return {"version_id": saved_id, "issues": issues, "summary": result.get("summary", "")}

    def rewrite_section(
        self,
        project_id: int,
        section_id: int,
        version_id: int,
        review_id: int,
        rewrite_mode: str,
        preserve: list[str] | None = None,
    ) -> dict[str, Any]:
        section = self._require(self.store.get_section(section_id), "section")
        if section.get("status") == "finalized":
            raise ValueError("小节已定稿，不能改写")
        project = self._require(self.store.get_project(project_id), "project")
        draft = self._require(self.store.get_version(version_id), "draft")
        review = self._require(self.store.get_version(review_id), "review")
        review_data = self._loads(review.get("content"))
        issues = validate_review_issues(review_data)
        request = build_rewrite_request(section, draft["content"], issues, rewrite_mode, preserve or [])
        request["project"] = project
        draft_metadata = self._loads(draft.get("metadata_json"))
        request["retrieved_world_items"] = draft_metadata.get("retrieved_world_items", [])
        result = self._call("rewriter", request)
        chapter_id = section["chapter_id"]
        saved_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "rewrite",
                "label": rewrite_mode,
                "content": result.get("content", ""),
                "metadata": self._metadata_with_trace(result, {"retrieval_trace": request["retrieved_world_items"]}),
            }
        )
        return {"version_id": saved_id, **result}

    def continue_next_section(self, section_id: int) -> dict[str, Any]:
        section = self._require(self.store.get_section(section_id), "section")
        if section.get("status") != "finalized":
            raise ValueError("上一节必须定稿后才能继续下一节")
        sections = self.store.list_sections(section["chapter_id"])
        for candidate in sections:
            if candidate["number"] > section["number"]:
                return candidate
        raise ValueError("当前章节没有下一节")

    def _section_step(
        self,
        project_id: int,
        section_id: int,
        agent_name: str,
        content_key: str,
        label: str,
    ) -> dict[str, Any]:
        section = self._require(self.store.get_section(section_id), "section")
        project = self._require(self.store.get_project(project_id), "project")
        chapter = self._require(self.store.get_chapter(section["chapter_id"]), "chapter")
        context = self._with_retrieval_trace(
            retrieve_context(self.store, project_id, chapter["id"], section_id, section.get("goal", ""), self.llm)
        )
        result = self._call(agent_name, {"project": project, "chapter": chapter, "section": section, "context": context})
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "chapter_id": chapter["id"],
                "section_id": section_id,
                "kind": "section_plan",
                "label": label,
                "content": result.get(content_key, json.dumps(result, ensure_ascii=False)),
                "metadata": result,
            }
        )
        return {"version_id": version_id, **result}

    def _call(self, agent_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._with_project_writing_constraints(payload)
        messages = build_messages(agent_name, payload)
        try:
            result = self.llm.chat_json(agent_name, messages, SCHEMA_HINTS.get(agent_name))
            self.store.save_llm_call_log(
                {
                    "project_id": payload.get("project", {}).get("id") or payload.get("project_id"),
                    "agent_name": agent_name,
                    "model": self.llm.config.get("chat_model", ""),
                    "request_summary": self._request_summary(payload),
                    "response_summary": json.dumps(result, ensure_ascii=False)[:500],
                    "success": True,
                }
            )
            return result
        except Exception as exc:
            self.store.save_llm_call_log(
                {
                    "project_id": payload.get("project", {}).get("id") or payload.get("project_id"),
                    "agent_name": agent_name,
                    "model": self.llm.config.get("chat_model", ""),
                    "request_summary": self._request_summary(payload),
                    "response_summary": "",
                    "success": False,
                    "error": str(exc),
                }
            )
            raise

    def _outline_expansion_result(self, result: dict[str, Any]) -> dict[str, Any]:
        expanded = dict(result)
        expanded.pop("chapters", None)
        expanded.pop("world_items", None)
        expanded["source"] = expanded.get("source") or "global_expander"
        return expanded

    def main_character_cards(self, project_id: int) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        role_labels = {
            "protagonist": "主角",
            "pov": "POV",
            "ensemble_main": "群像主要角色",
            "supporting": "重要配角",
        }
        for item in self.store.list_world_items(project_id, "character"):
            details = self._loads(item.get("details_json"))
            fields = character_basic_fields_from_details(details)
            role_flags = fields.get("role_flags", {})
            roles = [
                label
                for key, label in role_labels.items()
                if isinstance(role_flags, dict) and role_flags.get(key)
            ]
            tags = str(item.get("tags", "") or "")
            if not roles:
                roles = [label for label in role_labels.values() if label in tags]
            if not roles:
                continue
            modules = details.get("modules") if isinstance(details.get("modules"), dict) else {}
            card = {
                "name": item.get("name", ""),
                "role": roles[0],
                "roles": roles,
                "summary": item.get("summary", ""),
                "tags": tags,
                "identity": fields.get("identity", ""),
                "personality": fields.get("personality", ""),
                "motivation": fields.get("motivation", ""),
                "speech_style": fields.get("speech_style", ""),
            }
            if modules:
                card["modules"] = modules
            cards.append(card)
        return cards

    def _outline_expansion_payload(self, project_id: int, project: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "project": project,
            "project_length_target": project.get("length_target", ""),
        }
        world_context = self.outline_world_context(project_id)
        if world_context:
            payload["outline_world_context"] = world_context
        main_character_cards = self.main_character_cards(project_id)
        if main_character_cards:
            payload["main_character_cards"] = main_character_cards
        return payload

    def outline_world_context(self, project_id: int) -> dict[str, list[dict[str, Any]]]:
        context: dict[str, list[dict[str, Any]]] = {}
        for kind in sorted(WORLD_ITEM_KINDS):
            entries: list[dict[str, Any]] = []
            for item in self.store.list_world_items(project_id, kind):
                details = self._loads(item.get("details_json"))
                entry: dict[str, Any] = {
                    "id": item.get("id"),
                    "kind": item.get("kind", kind),
                    "name": item.get("name", ""),
                    "summary": item.get("summary", ""),
                    "tags": item.get("tags", ""),
                    "status": item.get("status", ""),
                }
                if details:
                    entry["details"] = details
                entries.append(entry)
            if entries:
                context[kind] = entries
        return context

    def _outline_split_metadata(
        self,
        project: dict[str, Any],
        version: dict[str, Any],
        outline_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(outline_metadata.get("chapters"), list):
            return outline_metadata
        result = self._call("outline_splitter", self._outline_split_payload(project, version, outline_metadata))
        self._save_outline_split_version(int(project["id"]), result)
        return result

    @staticmethod
    def _outline_split_payload(
        project: dict[str, Any],
        version: dict[str, Any],
        outline_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "project": project,
            "outline_version": {
                "id": version.get("id"),
                "label": version.get("label", ""),
                "content": version.get("content", ""),
                "metadata": outline_metadata,
            },
            "expanded_outline": version.get("content", ""),
            "project_length_target": project.get("length_target", ""),
        }

    def _save_outline_split_version(self, project_id: int, split_metadata: dict[str, Any]) -> int:
        return self.store.save_version(
            {
                "project_id": project_id,
                "kind": "outline_split",
                "label": "章节拆分方案",
                "content": json.dumps(split_metadata, ensure_ascii=False, indent=2),
                "metadata": split_metadata,
            }
        )

    def _outline_world_item_candidates(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        source = "来自总体框架/章节拆分"
        candidates.extend(self._explicit_world_item_candidates(metadata.get("world_items"), source))
        top_level_fields = {
            "character": ("characters", "character_cards", "roles"),
            "location": ("locations", "places"),
            "organization": ("organizations", "factions", "forces"),
            "rule": ("rules", "world_rules"),
            "timeline_event": ("timeline", "timeline_events"),
            "foreshadowing": ("foreshadowing", "foreshadowings"),
            "forbidden": ("forbidden", "forbidden_items", "taboos"),
        }
        for kind, keys in top_level_fields.items():
            for key in keys:
                candidates.extend(self._world_items_from_value(kind, metadata.get(key), source))

        for chapter in metadata.get("chapters", []):
            if not isinstance(chapter, dict):
                continue
            chapter_label = self._numbered_label("第{number}章", chapter)
            candidates.extend(self._world_items_from_value("character", chapter.get("characters"), source))
            candidates.extend(self._world_items_from_value("location", chapter.get("location"), source))
            candidates.extend(self._world_items_from_value("forbidden", chapter.get("forbidden"), source))
            if chapter.get("story_time"):
                candidates.append(
                    self._world_item(
                        "timeline_event",
                        f"{chapter_label}：{chapter.get('story_time')}",
                        source,
                        {"scope": "chapter", "chapter": chapter.get("title", "")},
                    )
                )
            for section in chapter.get("sections", []):
                if not isinstance(section, dict):
                    continue
                section_label = self._numbered_label("第{number}节", section)
                candidates.extend(self._world_items_from_value("character", section.get("characters"), source))
                candidates.extend(self._world_items_from_value("location", section.get("location"), source))
                candidates.extend(self._world_items_from_value("forbidden", section.get("forbidden"), source))
                if section.get("story_time"):
                    candidates.append(
                        self._world_item(
                            "timeline_event",
                            f"{chapter_label}{section_label}：{section.get('story_time')}",
                            source,
                            {
                                "scope": "section",
                                "chapter": chapter.get("title", ""),
                                "section": section.get("title", ""),
                            },
                        )
                    )

        deduped: dict[tuple[str, str], dict[str, Any]] = {}
        for item in candidates:
            name = item.get("name", "").strip()
            if not name:
                continue
            key = (item.get("kind", ""), name.casefold())
            deduped.setdefault(key, item)
        return list(deduped.values())

    def _latest_outline_snapshot(self, project_id: int) -> dict[str, Any]:
        versions = self.store.list_versions(project_id, kind="global_outline")
        if not versions:
            return {}
        latest = versions[0]
        metadata = self._loads(latest.get("metadata_json")) or {}
        return {
            "id": latest.get("id"),
            "label": latest.get("label", ""),
            "content": latest.get("content", ""),
            "metadata": metadata,
        }

    def _explicit_world_item_candidates(self, raw_items: Any, source: str) -> list[dict[str, Any]]:
        if not isinstance(raw_items, list):
            return []
        valid_kinds = {
            "character",
            "location",
            "organization",
            "rule",
            "timeline_event",
            "foreshadowing",
            "forbidden",
        }
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind", "")).strip()
            name = str(raw.get("name", "")).strip()
            if kind not in valid_kinds or not name:
                continue
            details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
            module_patches = raw.get("module_patches") if isinstance(raw.get("module_patches"), dict) else {}
            details = merge_module_patches(details, module_patches) if module_patches else details
            items.append(
                {
                    "kind": kind,
                    "name": name,
                    "summary": raw.get("summary", source),
                    "details": {"source": "outline_split", **details},
                    "tags": self._merge_csv(raw.get("tags", ""), "总体框架,自动候选"),
                    "status": raw.get("status") or "candidate",
                }
            )
        return items

    def _chapter_memory_world_items(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        valid_kinds = {
            "character",
            "location",
            "organization",
            "rule",
            "timeline_event",
            "foreshadowing",
            "forbidden",
        }
        items: list[dict[str, Any]] = []
        raw_items = result.get("world_items", [])
        if not isinstance(raw_items, list):
            return items
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind", "")).strip()
            name = str(raw.get("name", "")).strip()
            if kind not in valid_kinds or not name:
                continue
            details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
            items.append(
                {
                    "kind": kind,
                    "name": name,
                    "summary": raw.get("summary", "来自章末记忆反写"),
                    "details": {
                        "source": "chapter_memory",
                        "chapter_memory": [
                            {
                                "summary": raw.get("summary", ""),
                                "impact": details.get("impact", ""),
                                "memory_delta": details.get("memory_delta", ""),
                                "relationship_delta": details.get("relationship_delta", ""),
                                "forbidden_check": details.get("forbidden_check", ""),
                                **details,
                            }
                        ],
                    },
                    "tags": self._merge_csv(raw.get("tags", ""), "章末记忆,自动候选"),
                    "status": raw.get("status") or "candidate",
                }
            )
        return items

    def _with_project_writing_constraints(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("project_writing_constraints"):
            return payload
        constraints = build_project_writing_constraints(payload.get("project"))
        if not constraints:
            return payload
        return {**payload, "project_writing_constraints": constraints}

    def _with_retrieval_trace(self, context: dict[str, Any]) -> dict[str, Any]:
        return {**context, "retrieval_trace": self._retrieval_trace(context)}

    def _request_summary(self, payload: dict[str, Any]) -> str:
        summary = {
            "retrieval_trace": self._payload_retrieval_trace(payload),
            "project_constraints": payload.get("project_writing_constraints", {}),
            "payload": payload,
        }
        return json.dumps(summary, ensure_ascii=False, default=str)[:500]

    def _metadata_with_trace(self, metadata: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if isinstance(context.get("retrieval_trace"), list):
            raw_trace = context["retrieval_trace"]
        else:
            raw_trace = self._retrieval_trace(context)
        trace = [
            item
            for item in raw_trace
            if item.get("id") is not None and item.get("source") in {"long_term", "forbidden"}
        ]
        return {
            **metadata,
            "retrieved_world_item_ids": [item["id"] for item in trace],
            "retrieved_world_items": trace,
        }

    def _payload_retrieval_trace(self, value: Any) -> list[dict[str, Any]]:
        traces: list[dict[str, Any]] = []
        if isinstance(value, dict):
            trace = value.get("retrieval_trace")
            if isinstance(trace, list):
                traces.extend(trace)
            for child in value.values():
                traces.extend(self._payload_retrieval_trace(child))
        elif isinstance(value, list):
            for child in value:
                traces.extend(self._payload_retrieval_trace(child))
        return traces

    def _retrieval_trace(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        trace: list[dict[str, Any]] = []
        for source, rows in (
            ("long_term", context.get("long_term", [])),
            ("forbidden", context.get("forbidden", [])),
            ("recent_plot", context.get("recent_plot", [])),
        ):
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                trace.append(
                    {
                        "source": source,
                        "id": row.get("id"),
                        "kind": row.get("kind"),
                        "name": row.get("name") or row.get("label") or row.get("title"),
                        "version_kind": row.get("kind") if source == "recent_plot" else None,
                    }
                )
        for note in context.get("retrieval_notes", []):
            trace.append({"source": "retrieval_note", "note": note})
        return trace

    def _chapter_retrieved_world_items(self, project_id: int, chapter_id: int) -> list[dict[str, Any]]:
        rows = self.store.list_versions(project_id, chapter_id=chapter_id)
        items: dict[int, dict[str, Any]] = {}
        for row in rows:
            metadata = self._loads(row.get("metadata_json"))
            for item in metadata.get("retrieved_world_items", []):
                if not isinstance(item, dict) or item.get("id") is None:
                    continue
                try:
                    item_id = int(item["id"])
                except (TypeError, ValueError):
                    continue
                world_item = self.store.get_world_item(project_id, item_id)
                if world_item:
                    items[item_id] = world_item
        return list(items.values())

    def _apply_section_word_budget(self, chapters: Any, total_words: int | None) -> None:
        sections: list[dict[str, Any]] = []
        if isinstance(chapters, list):
            for chapter in chapters:
                if not isinstance(chapter, dict):
                    continue
                for section in chapter.get("sections", []):
                    if isinstance(section, dict):
                        sections.append(section)
        if not sections:
            return

        if total_words is None:
            for section in sections:
                target_words = parse_length_target(section.get("target_words")) or DEFAULT_SECTION_TARGET_WORDS
                section["target_words"] = max(1, int(target_words))
            return

        weights = [
            float(parse_length_target(section.get("target_words")) or 1)
            for section in sections
        ]
        budgets = self._normalized_word_budgets(total_words, weights)
        for section, budget in zip(sections, budgets):
            section["target_words"] = budget

    @staticmethod
    def _normalized_word_budgets(total_words: int, weights: list[float]) -> list[int]:
        if not weights:
            return []
        count = len(weights)
        floor = min(MIN_SECTION_TARGET_WORDS, max(1, total_words // count))
        reserved = floor * count
        if reserved >= total_words:
            budgets = [floor] * count
            for index in range(reserved - total_words):
                budgets[-1 - index % count] -= 1
            return [max(1, budget) for budget in budgets]

        remaining = total_words - reserved
        weight_sum = sum(weight for weight in weights if weight > 0) or float(count)
        raw_shares = [(max(weight, 0.0) / weight_sum) * remaining for weight in weights]
        extra = [int(share) for share in raw_shares]
        budgets = [floor + value for value in extra]
        remainder = total_words - sum(budgets)
        order = sorted(
            range(count),
            key=lambda index: raw_shares[index] - extra[index],
            reverse=True,
        )
        for index in order[:remainder]:
            budgets[index] += 1
        return budgets

    def _world_items_from_value(self, kind: str, value: Any, source: str) -> list[dict[str, Any]]:
        if value is None or value == "":
            return []
        if isinstance(value, (str, int, float)):
            return [self._world_item(kind, str(value), source)]
        if isinstance(value, dict):
            name = self._first_text(value, ("name", "title", "event", "rule", "content", "text", "item"))
            summary = self._first_text(value, ("summary", "description", "details", "goal", "outline"))
            return [self._world_item(kind, name, summary or source, value)]
        if isinstance(value, list):
            items: list[dict[str, Any]] = []
            for entry in value:
                items.extend(self._world_items_from_value(kind, entry, source))
            return items
        return []

    @staticmethod
    def _world_item(kind: str, name: str, summary: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "kind": kind,
            "name": name.strip(),
            "summary": summary,
            "details": {"source": "outline_split", **(details or {})},
            "tags": "总体框架,章节拆分,自动候选",
            "status": "candidate",
        }

    @staticmethod
    def _merged_details(existing_json: str | None, incoming: Any) -> dict[str, Any]:
        try:
            existing = json.loads(existing_json or "{}")
        except json.JSONDecodeError:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        if isinstance(incoming, dict):
            existing.update({key: value for key, value in incoming.items() if value not in ("", None)})
        existing["source"] = "ai_enriched"
        return existing

    @staticmethod
    def _merge_csv(*values: Any) -> str:
        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            for part in str(value or "").split(","):
                clean = part.strip()
                key = clean.casefold()
                if clean and key not in seen:
                    merged.append(clean)
                    seen.add(key)
        return ",".join(merged)

    @staticmethod
    def _first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _numbered_label(template: str, data: dict[str, Any]) -> str:
        number = data.get("number")
        title = data.get("title", "")
        if number:
            label = template.format(number=number)
            return f"{label}{title}" if title else label
        return str(title or "").strip()

    @staticmethod
    def _loads(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _require(value: Any, name: str) -> Any:
        if value is None:
            raise ValueError(f"missing {name}")
        return value
