from __future__ import annotations

import json
from typing import Any

from .style_tags import PROJECT_STYLE_TAG_FIELDS, build_prompt_modules, dump_tag_ids


AGENT_SYSTEM_PROMPTS = {
    "global_architect": "你是全书故事大纲 Agent。你的任务不是拆章节，而是把用户给出的总体概括、总世界书、写作风格、项目设定和资料库内容，扩写成一份用户能读懂故事大概讲什么的大纲。输入的 outline_planning 决定任务范围：outline_mode=full_book 时生成整本书大纲，planning_target_words 表示整本书目标字数；outline_mode=serial 时只生成本次连载规划，planning_target_words 表示本次规划情节的目标字数。planning_chapter_count 表示后续拆分时预计生成的章节数，不是小节数；default_chapter_target_words 表示默认单章目标字数，不是单小节目标字数；section_count_approx 只供后续把单章拆成约几个小节时参考。serial_action=revise_current 表示修改当前连载大纲；serial_action=next_part 表示根据已有资料和当前进度生成下一部分大纲，不要重讲或重置已发生内容。若输入包含 outline_world_context，必须参考其中所有资料类型建立故事，包括角色卡、地点、组织/势力、规则、时间线、伏笔和禁止事项；不得无视已存在资料、改名替换核心资料或写出与禁止事项冲突的内容。若输入包含 main_character_cards，必须以这些角色的身份、性格、动机、说话风格、角色定位和模块状态为主要人物基础，不要无视、改名或另造同职能主角；若没有资料库内容，则按项目已有概括继续生成。禁止输出章节、章节列表、小节、小节列表、章节拆分建议、分卷拆分、target_words 分配或资料库候选；不要强行设计反派势力；核心阻力应从人物选择、世界规则、环境限制、关系变化和目标冲突中自然显现。输出应以连贯自然段呈现故事如何展开，让用户能判断这段/这本小说从什么局面开始、如何推进、主要变化是什么、最终大致走向哪里。",
    "outline_splitter": "你是总框架拆分 Agent，只在用户确认总体框架后工作。你负责把已确认的 expanded_outline 拆分为章节、每章小节和资料库候选。输入的 outline_planning 决定拆分范围：full_book 按整本书拆分；serial+next_part 只拆分本次新增连载内容，章节将在程序中追加到已有章节之后，不要输出旧章节；serial+revise_current 只拆分当前连载大纲。planning_target_words 是本次拆分的目标总字数。planning_chapter_count 是本次要生成的章节数，不是小节数；应尽量输出接近该数量的 chapters。default_chapter_target_words 是默认单章目标字数，不是单小节目标字数；每章 target_words 应接近该值，所有章节 target_words 总和应接近 planning_target_words。section_count_approx 表示每一章约拆成几个小节；每章 sections 数量应尽量接近该值，不必机械固定。每个小节也必须给出 target_words，且同一章下所有小节 target_words 总和应接近该章 target_words。若输入包含 outline_world_context，必须优先使用已有资料的 name 填写章节/小节人物、地点、组织、规则、伏笔和禁止事项；不要为已有资料创建同义或改名的 world_items。只有确实不存在的新资料才允许写入 world_items。",
    "chapter_architect": "你是章节架构 Agent，只负责本章目标、冲突、转折、节奏、信息释放和结尾钩子。",
    "section_planner": "你是小节规划 Agent，只负责把章节拆成可执行小节任务单。",
    "scene_director": "你是场景导演 Agent，只负责场景推进、动作、观察、心理、对白比例和视角限制。",
    "dialogue_psychology": "你是对白/心理 Agent，只负责人物声音、潜台词、隐瞒、打断和心理层次。",
    "draft_writer": "你是正文写作 Agent，只输出正文相关 JSON，不寒暄不解释。",
    "reviewer": "你是审稿 Agent，只输出结构化问题列表。",
    "rewriter": "你是改写 Agent，只按问题改写指定范围。",
    "world_item_enricher": "你是资料库设定补全 Agent，只补充已有资料条目的结构化设定，不改变资料类型。如果输入包含 enrich_direction，必须优先按该方向补充或修正。允许在必要时输出 name 修改资料名称。对于角色卡，你可以在 details 中补充或修改 identity、personality、motivation、speech_style、role_flags 和 modules；这些字段会回填到角色卡基础信息与完整 JSON 中。",
    "world_item_creator": "你是资料库条目创建 Agent。你的任务是根据当前项目资料、已生成的全书故事大纲和用户选择的资料种类，创建一条可直接保存到资料库的新资料。只生成一条；kind 必须等于 current_kind；不要生成章节、小节、正文或多个候选。",
    "tagged_character_creator": "你是标签化角色卡创建 Agent。你的任务是根据项目资料、已有大纲、已有角色卡、用户选择的角色定位和角色标签，创建一条可直接保存到资料库的角色卡。只生成一条；kind 必须是 character；不要生成章节、小节、正文、剧情大纲或多个候选。必须避免与 existing_characters 中已有角色同名、同身份功能或同剧情职能。角色定位必须写入 details.role_flags，且 protagonist、pov、ensemble_main、supporting 中只能有本次 role_profile 对应项为 true。用户选择的状态型标签必须写入 details.modules，而不是只写在 summary 或 tags 中。identity、personality、motivation、speech_style 必须填写，便于资料库角色卡基础信息 UI 直接显示。等级、技能、TS、恋爱关系、身份秘密等表现不固定的信息必须保存在 details.modules 或 details.relationships 中，不要强行变成基础字段。",
    "main_character_generator": "你是主要角色卡生成 Agent。你的任务是根据项目名称、题材、目标读者、总世界书、风格说明、总体概括、叙事视角和项目标签，生成一个默认主要角色卡。只生成一个角色；角色必须能作为全书故事大纲的主要推动者。不要生成章节、剧情大纲或多个候选。输出必须能直接保存为资料库 character 角色卡。",
    "novel_candidate_generator": "你是小说项目候选方案生成 Agent。你的任务是根据用户像搜索小说一样输入的条件、已选标签、排除标签、读者、视角、篇幅和自由偏好，生成 3-6 个原创可写小说方案。不要搜索、复述或模仿真实已存在作品；不要直接写正文；不要生成全书大纲或章节拆分。每个候选必须像小说网站结果卡片一样可供选择，并且要能继续转换为可编辑项目字段。字段语义必须清楚：style_direction 只写自然语言写作风格，不要输出 <xxx>、尖括号占位或标签列表；world_form 写世界形式、社会/力量规则的总体形态；world_history 写影响当前故事的历史背景；world_direction 可补充世界观重点，但必须偏世界形式和历史，而不是剧情简介；novel_blurb 写类似小说网站简介的总体概括，突出主角处境、开局诱因和阅读看点，不要写成设定清单。",
    "chapter_memory_writer": "你是章末记忆回写 Agent，只总结本章已定稿正文中与 called_world_items 相关的经历、事件影响、关系变化、伏笔推进和禁止事项检查，并输出可反写资料库的结构化条目；不要改写基础设定。",
}

PROJECT_WRITING_CONSTRAINT_FIELDS = (
    "title",
    "genre",
    "style",
    "target_readers",
    "length_target",
    "pov",
    "selected_genre_tags",
    "selected_setting_tags",
    "selected_structure_tags",
    "selected_style_tags",
    "dialogue_quote_style",
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
        "name": "string",
        "summary": "string",
        "details": "object",
        "tags": "string",
        "status": "string",
    },
    "world_item_creator": {
        "kind": "character|location|organization|rule|timeline_event|foreshadowing|forbidden",
        "name": "string",
        "summary": "string",
        "details": "object",
        "tags": "string",
        "status": "string",
    },
    "tagged_character_creator": {
        "kind": "character",
        "name": "string",
        "summary": "string",
        "details": {
            "identity": "string",
            "personality": "string",
            "motivation": "string",
            "speech_style": "string",
            "role_flags": {
                "protagonist": "bool",
                "pov": "bool",
                "ensemble_main": "bool",
                "supporting": "bool",
            },
            "modules": "object",
            "relationships": "array",
        },
        "tags": "string",
        "status": "string",
    },
    "main_character_generator": {
        "name": "string",
        "summary": "string",
        "details": {
            "identity": "string",
            "personality": "string",
            "motivation": "string",
            "speech_style": "string",
            "role_flags": {
                "protagonist": "bool",
                "pov": "bool",
                "ensemble_main": "bool",
                "supporting": "bool",
            },
            "modules": "object",
        },
        "tags": "string",
        "status": "string",
    },
    "novel_candidate_generator": {
        "candidates": [
            {
                "temporary_title": "string",
                "one_line_hook": "string",
                "tags": ["string"],
                "target_readers": "string",
                "pov": "string",
                "story_start": "string",
                "main_character_direction": "string",
                "world_form": "string",
                "world_history": "string",
                "world_direction": "string",
                "novel_blurb": "string",
                "relationship_direction": "string",
                "style_direction": "string",
                "stateful_requirements": ["string"],
                "risk_notes": ["string"],
            }
        ]
    },
    "chapter_memory_writer": {
        "world_items": [
            {
                "kind": "character|location|organization|rule|timeline_event|foreshadowing|forbidden",
                "name": "string",
                "summary": "string",
                "details": "object",
                "module_patches": "object",
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
            constraints[field] = dump_tag_ids(value) if field in PROJECT_STYLE_TAG_FIELDS else value
    prompt_modules = build_prompt_modules(project)
    if prompt_modules["selected_tags"] or prompt_modules["dialogue_quote_style"]:
        constraints["prompt_modules"] = prompt_modules
    return constraints
