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
    "world_item_creator": "你是资料库条目创建 Agent。你的任务是根据当前项目资料、已生成的全书故事大纲和用户选择的资料种类，创建一条可直接保存到资料库的新资料。只生成一条；kind 必须等于 current_kind；不要生成章节、小节、正文或多个候选。若 current_kind=organization，应把家族、教会、学院、王室、公会、商会、军团、社交圈等组织/势力的信息写入该组织/势力条目的 details，而不是写入角色卡 relationships。",
    "tagged_character_creator": "你是标签化角色卡创建 Agent。你的任务是根据项目资料、已有大纲、已有角色卡、用户选择的角色定位和角色标签，创建一条可直接保存到资料库的角色卡。只生成一条；kind 必须是 character；不要生成章节、小节、正文、剧情大纲或多个候选。必须避免与 existing_characters 中已有角色同名、同身份功能或同剧情职能。角色定位必须写入 details.role_flags，且 protagonist、pov、ensemble_main、supporting 中只能有本次 role_profile 对应项为 true。用户选择的状态型标签必须写入 details.modules，而不是只写在 summary 或 tags 中。identity、personality、motivation、speech_style 必须填写，便于资料库角色卡基础信息 UI 直接显示。等级、技能、TS、恋爱关系、身份秘密等表现不固定的信息必须保存在 details.modules 或 details.relationships 中，不要强行变成基础字段。details.relationships 只记录与其他角色卡之间的人物关系；家族、教会、学院、王室、公会、商会、军团、社交圈等组织/势力不要写入 relationships，应写入 details.affiliations/details.organizations，或作为 organization 资料条目单独创建。",
    "main_character_generator": "你是主要角色卡生成 Agent。你的任务是根据项目名称、题材、目标读者、总世界书、风格说明、总体概括、叙事视角和项目标签，生成一个默认主要角色卡。只生成一个角色；角色必须能作为全书故事大纲的主要推动者。不要生成章节、剧情大纲或多个候选。输出必须能直接保存为资料库 character 角色卡。details.relationships 只记录与其他角色卡之间的人物关系；家族、教会、学院、王室、公会、商会、军团、社交圈等组织/势力不要写入 relationships，应写入 details.affiliations/details.organizations，或后续作为 organization 资料条目单独创建。",
    "novel_candidate_generator": "你是小说项目候选方案生成 Agent。你的任务是根据用户像搜索小说一样输入的条件、已选标签、排除标签、读者、视角、篇幅和自由偏好，生成 3-6 个原创可写小说方案。不要搜索、复述或模仿真实已存在作品；不要直接写正文；不要生成全书大纲或章节拆分。每个候选必须像小说网站结果卡片一样可供选择，并且要能继续转换为可编辑项目字段。字段语义必须清楚：style_direction 只写自然语言写作风格，不要输出 <xxx>、尖括号占位或标签列表；world_form 写世界形式、社会/力量规则的总体形态；world_history 写影响当前故事的历史背景；world_direction 可补充世界观重点，但必须偏世界形式和历史，而不是剧情简介；novel_blurb 写类似小说网站简介的总体概括，突出主角处境、开局诱因和阅读看点，不要写成设定清单。",
    "project_assistant": "你是项目资料辅助修改 Agent。你的任务是根据当前项目表单、用户选择的标签、对白引号和修改方向，生成可供用户确认后应用的项目字段修改建议。只输出 project_patch，不要保存项目，不要生成章节、正文、角色卡或多个候选。project_patch 只能包含 title、genre、style、target_readers、pov、world_summary、writing_style_guide、global_concept 这些字段；没有必要修改的字段输出空字符串或省略。必须尊重用户已有内容，不要无故清空、改名或完全重写；如果用户 direction 要求局部调整，就只调整相关字段。",
    "chapter_memory_writer": "你是章末记忆回写 Agent，只总结本章已定稿正文中与 called_world_items 相关的经历、事件影响、关系变化、伏笔推进和禁止事项检查，并输出可反写资料库的结构化条目；不要改写基础设定。若输出角色关系变化，写入 details.relationship_delta 或角色 details.relationships；若输出真实事件，必须把 participants、location、related_organizations、causes、caused_by 或 graph_links 写在 details 顶层，便于事件关系图读取。",
}

AGENT_SYSTEM_PROMPTS["global_architect"] += (
    "补充约束：outline_mode=full_book 时仍按全书压缩版处理，允许概括整本书的主线、阶段变化和结局方向；"
    "outline_mode=serial 时只规划一个连载单元，不要把目标字数当成整本书压缩，不要在一万字左右塞入过多地点、组织、支线、反转或终局信息。"
    "连载模式应优先保留少量核心角色、一个主要推进目标、少量自然阻力和可继续连载的未解问题。"
    "连载模式下，本次大纲只服务一个阶段性阅读期待；如果项目资料很多，只选择本次实际会登场或影响当前场景的少量资料。"
    "输出应体现这几章连续读起来发生了什么，而不是整本书讲了什么。"
    "若 outline_planning 包含 estimated_total_sections 或 serial_content_budget，生成/修改大纲的内容量必须严格适配该小节容量："
    "不要写出超过 total_sections 可承载数量的剧情拍点；一个小节容量只对应一个可表演场景或一个连续拍点。"
    "当预计小节数很少时，应主动缩小本次大纲范围，把多余事件、支线、设定解释和危机留到后续连载单元。"
)
AGENT_SYSTEM_PROMPTS["outline_splitter"] += (
    "补充约束：full_book 模式仍是整书压缩拆分；serial 模式只拆本次连载单元，章节应像连续更新的几章，而不是完整作品摘要。"
    "serial 模式下每章只承担少量剧情推进，避免每章都塞入新地点、新势力、新规则、重大反转和结局级信息。"
    "serial 模式下必须服从 planning_chapter_count、section_count_approx、estimated_total_sections 和 serial_content_budget："
    "输出章节数不得超过 planning_chapter_count；每章小节数不得超过 section_count_approx；总小节数不得超过 estimated_total_sections。"
    "如果 expanded_outline 内容多于这些小节能承载的容量，只选择最靠前、最必要的一段剧情拆分，其余明确视为后续连载，不要硬塞进当前小节。"
    "serial 模式下，每章只承担一个主要变化，最多带一个次级变化；每章通常拆成 2-3 个小节。"
    "serial 模式下，每一小节必须是一个可表演场景或一个场景中的连续拍点，而不是剧情摘要；换言之，小节是一个可表演场景。"
    "每一小节只允许一个场景目标、一个即时目标、一个即时阻力、一条信息释放、一个情绪变化和一个结尾推动点。"
    "小节中最多引入 0-1 个新角色、0-1 个新地点、0-1 条新规则或设定解释、0-1 个伏笔；不要单小节连续串多个大事件。"
    "小节 scene 字段必须像场景任务单，写清当前动作如何推进，不要写成“然后 A、然后 B、然后 C”的流水账。"
    "serial 模式下，小节可额外输出 section_focus、immediate_goal、immediate_obstacle、information_release、emotion_shift、ending_push、density_guard，以便后续正文写作控制密度。"
    "chapter.story_time 和 section.story_time 只是章节/小节自身的时间标记，不是资料库事件，不要因为它们创建 world_items。"
    "只有真正改变人物、组织、规则、伏笔或世界状态的事件才输出为 kind=timeline_event 的 world_items；"
    "这类事件的 details 应尽量包含 time_text、sequence、phase、status，便于后续按时间顺序显示。"
    "如果 world_items 输出角色、组织或事件，必须使用资料库关系图可读取的 details 顶层字段："
    "角色关系写 details.relationships；角色所属组织写 details.affiliations 或 details.organizations；"
    "组织成员写 details.members 或 details.leaders；事件参与者写 details.participants，地点写 details.location，"
    "事件因果写 details.causes/details.caused_by，跨资料关联写 details.graph_links 或 related_organizations/related_foreshadowing/related_rules/forbidden。"
    "不要只把这些信息写进 details.note。"
    "serial 模式下，world_items 只创建本次实际登场、调用或必须记忆的资料，不要把全书设定库一次性灌入本次规划。"
)
AGENT_SYSTEM_PROMPTS["draft_writer"] += (
    "正文生成时不要把规划写成条目或流水账摘要；需要把动作、观察、反应、停顿和对白写成连续场景。"
    "连载单元内不要急于解释所有设定或提前完成后续章节才应承担的转折。"
    "如果 section 中包含 section_focus、immediate_goal、immediate_obstacle、information_release、ending_push 或 density_guard，必须优先按这些字段控制本节信息密度。"
    "每一小节正文应围绕一个场景动作或一次互动展开，允许停顿、误解、反应和余韵，不要把 must_happen 展开成事件清单。"
)
AGENT_SYSTEM_PROMPTS["reviewer"] += (
    "审稿时额外检查信息密度：如果连载模式正文像全书摘要、事件连续堆叠、缺少场景停顿，或一章内过度塞入新设定、新地点、新组织、新反转，应输出问题。"
    "同时检查每节是否缺少即时目标、即时阻力、信息释放、情绪变化或结尾推动点；如果小节像剧情摘要、流水账而不是可阅读正文，也应输出问题。"
)

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
                        "section_focus": "optional string; serial mode only, the single focus of this section",
                        "immediate_goal": "optional string; serial mode only, what the POV character wants now",
                        "immediate_obstacle": "optional string; serial mode only, the immediate resistance",
                        "information_release": "optional string; serial mode only, the one piece of information released",
                        "emotion_shift": "optional string; serial mode only, emotional movement from A to B",
                        "ending_push": "optional string; serial mode only, payoff or hook that makes the next section necessary",
                        "density_guard": ["optional strings; serial mode only, what this section must not introduce, explain, or resolve"],
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
                "details": {
                    "note": "object; when kind=timeline_event, use time_text, sequence, phase and status for real chronological events",
                    "time_text": "string",
                    "sequence": "int|string",
                    "phase": "string",
                    "status": "string",
                    "relationships": "array; character only, character-to-character relationship edges",
                    "affiliations": "array; character only, organization/faction memberships",
                    "organizations": "array; character or timeline_event organization references",
                    "members": "array; organization only, character members",
                    "leaders": "array; organization only, character leaders",
                    "participants": "array; timeline_event only, character names",
                    "location": "string|array; timeline_event only, location names",
                    "causes": "array; timeline_event names caused by this event",
                    "caused_by": "array; timeline_event names that caused this event",
                    "graph_links": "array; explicit graph links with target_kind, target, type",
                    "related_organizations": "array; timeline_event organization names",
                    "related_foreshadowing": "array; timeline_event foreshadowing names",
                    "related_rules": "array; timeline_event rule names",
                    "forbidden": "array; timeline_event forbidden item names",
                },
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
            "relationships": "array of character-to-character relationships only",
            "affiliations": "array of organization/faction names or objects, not character relationships",
            "organizations": "array of organization/faction names or objects, not character relationships",
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
    "project_assistant": {
        "project_patch": {
            "title": "string",
            "genre": "string",
            "style": "string",
            "target_readers": "string",
            "pov": "string",
            "world_summary": "string",
            "writing_style_guide": "string",
            "global_concept": "string",
        },
        "reasoning_summary": "string",
        "warnings": ["string"],
    },
    "chapter_memory_writer": {
        "world_items": [
            {
                "kind": "character|location|organization|rule|timeline_event|foreshadowing|forbidden",
                "name": "string",
                "summary": "string",
                "details": {
                    "note": "object",
                    "relationships": "array; character relationship edges",
                    "relationship_delta": "object|array|string; chapter memory relationship change",
                    "affiliations": "array; character organization memberships",
                    "organizations": "array; character or timeline_event organization references",
                    "members": "array; organization members",
                    "leaders": "array; organization leaders",
                    "participants": "array; timeline_event character names",
                    "location": "string|array; timeline_event location names",
                    "causes": "array; timeline_event names caused by this event",
                    "caused_by": "array; timeline_event names that caused this event",
                    "graph_links": "array; explicit graph links with target_kind, target, type",
                    "related_organizations": "array; timeline_event organization names",
                    "related_foreshadowing": "array; timeline_event foreshadowing names",
                    "related_rules": "array; timeline_event rule names",
                    "forbidden": "array; timeline_event forbidden item names",
                },
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
