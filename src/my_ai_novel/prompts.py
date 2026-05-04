from __future__ import annotations

import json
from typing import Any


AGENT_SYSTEM_PROMPTS = {
    "global_architect": "你是全书故事大纲 Agent。你的任务不是拆章节，而是把用户给出的总体概括、总世界书、写作风格和项目设定，扩写成一份用户能读懂整本小说大概讲什么的全书故事大纲。禁止输出章节、章节列表、小节、小节列表、章节拆分建议、分卷拆分、target_words 分配或资料库候选；不要强行设计反派势力；核心阻力应从人物选择、世界规则、环境限制、关系变化和目标冲突中自然显现。输出应以连贯自然段呈现故事如何展开，让用户能判断这本小说从什么局面开始、如何推进、主要变化是什么、最终大致走向哪里。",
    "outline_splitter": "你是总框架拆分 Agent，只在用户确认总体框架后工作。你负责把已确认的 expanded_outline 拆分为章节、每章小节和资料库候选。项目 length_target 是全书总目标字数/篇幅，章节和小节都必须给出 target_words，且所有小节 target_words 总和应接近全书总目标。",
    "chapter_architect": "你是章节架构 Agent，只负责本章目标、冲突、转折、节奏、信息释放和结尾钩子。",
    "section_planner": "你是小节规划 Agent，只负责把章节拆成可执行小节任务单。",
    "scene_director": "你是场景导演 Agent，只负责场景推进、动作、观察、心理、对白比例和视角限制。",
    "dialogue_psychology": "你是对白/心理 Agent，只负责人物声音、潜台词、隐瞒、打断和心理层次。",
    "draft_writer": "你是正文写作 Agent，只输出正文相关 JSON，不寒暄不解释。",
    "reviewer": "你是审稿 Agent，只输出结构化问题列表。",
    "rewriter": "你是改写 Agent，只按问题改写指定范围。",
    "world_item_enricher": "你是资料库设定补全 Agent，只补充已有资料条目的结构化设定，不改变资料类型和名称。",
    "chapter_memory_writer": "你是章末记忆回写 Agent，只总结本章已定稿正文中与 called_world_items 相关的经历、事件影响、关系变化、伏笔推进和禁止事项检查，并输出可反写资料库的结构化条目；不要改写基础设定。",
}

PROJECT_WRITING_CONSTRAINT_FIELDS = (
    "title",
    "genre",
    "style",
    "target_readers",
    "length_target",
    "pov",
    "world_summary",
    "character_brief",
    "writing_style_guide",
    "global_concept",
)


SCHEMA_HINTS = {
    "global_architect": {
        "expanded_outline": "string",
    },
    "outline_splitter": {
        "chapters": [
            {
                "number": "int",
                "title": "string",
                "story_time": "string",
                "location": "string",
                "characters": ["string"],
                "goal": "string",
                "outline": "string",
                "target_words": "int",
                "sections": [
                    {
                        "number": "int",
                        "title": "string",
                        "story_time": "string",
                        "location": "string",
                        "characters": ["string"],
                        "goal": "string",
                        "scene": "string",
                        "target_words": "int",
                    }
                ],
            }
        ],
        "world_items": [
            {
                "kind": "character|location|organization|rule|timeline_event|foreshadowing|forbidden",
                "name": "string",
                "summary": "string",
                "details": "object",
                "tags": "string",
                "status": "string",
            }
        ],
    },
    "chapter_architect": {
        "chapter_plan": "string",
        "goal": "string",
        "conflict": "string",
        "turning_point": "string",
        "pacing": "string",
        "information_release": "string",
        "hook": "string",
    },
    "section_planner": {"sections": ["section objects"]},
    "scene_director": {"scene_plan": "string", "beats": ["string"]},
    "dialogue_psychology": {"dialogue_rules": "string", "character_voices": ["string"]},
    "draft_writer": {"content": "string", "notes": "string"},
    "reviewer": {"issues": ["ReviewIssue objects"], "summary": "string"},
    "rewriter": {"content": "string", "rewrite_notes": "string"},
    "world_item_enricher": {
        "summary": "string",
        "details": "object",
        "tags": "string",
        "status": "string",
    },
    "chapter_memory_writer": {
        "world_items": [
            {
                "kind": "character|location|organization|rule|timeline_event|foreshadowing|forbidden",
                "name": "string",
                "summary": "string",
                "details": "object",
                "tags": "string",
                "status": "string",
            }
        ],
        "notes": "string",
    },
}


def build_messages(agent_name: str, payload: dict[str, Any], output_json: bool = True) -> list[dict[str, str]]:
    system_content = AGENT_SYSTEM_PROMPTS[agent_name]
    project_constraints = payload.get("project_writing_constraints")
    if project_constraints:
        system_content += (
            "\n\n项目级写作约束如下，所有输出必须遵守，尤其是风格、视角、读者、世界设定、人物简述、篇幅目标和禁止改动的总体概念：\n"
            + json.dumps(project_constraints, ensure_ascii=False, indent=2, sort_keys=True)
        )
    messages = [
        {"role": "system", "content": system_content},
    ]
    if output_json:
        user_prefix = "输入数据如下，严格输出 JSON object：\n"
    else:
        user_prefix = "输入数据如下，请直接按本次任务要求输出正文内容，不要输出 JSON、代码块、字段名、解释或寒暄：\n"
    messages.append(
        {
            "role": "user",
            "content": user_prefix + json.dumps(payload, ensure_ascii=False, indent=2),
        }
    )
    return messages


def build_project_writing_constraints(project: dict[str, Any] | None) -> dict[str, Any]:
    if not project:
        return {}
    constraints = {}
    for field in PROJECT_WRITING_CONSTRAINT_FIELDS:
        value = project.get(field)
        if value not in (None, ""):
            constraints[field] = value
    return constraints
