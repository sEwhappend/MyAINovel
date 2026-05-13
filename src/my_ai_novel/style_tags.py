from __future__ import annotations

import json
from typing import Any


PROJECT_STYLE_TAG_FIELDS = (
    "selected_genre_tags",
    "selected_setting_tags",
    "selected_structure_tags",
    "selected_style_tags",
)

DIALOGUE_QUOTE_STYLES = {
    "cn_quotes": {
        "id": "cn_quotes",
        "label": "中文弯引号",
        "rule": "角色对白统一使用中文弯引号“”。",
    },
    "corner_quotes": {
        "id": "corner_quotes",
        "label": "日式直角引号",
        "rule": "角色对白统一使用日式直角引号「」。",
    },
}

STYLE_TAG_CATALOG = {
    "genre_tags": [
        {
            "id": "isekai_transfer",
            "label": "异世界转移",
            "style_rule": "主角从原本世界进入异世界，保留原身份、记忆或常识差异；故事应体现两个世界之间的价值观、常识和生存方式差异。",
            "usage_rule": "需要记录主角对两个世界的认知差异和回不回去等长期动机。",
            "requires_memory": True,
            "memory_kinds": ["character", "rule", "timeline_event"],
        },
        {
            "id": "isekai_reincarnation",
            "label": "异世界转生",
            "style_rule": "主角以新身份在异世界重生，前世经验应影响选择，但不要让设定说明压过当前剧情。",
            "usage_rule": "需要记录前世记忆、新身份和当前社会关系的变化。",
            "requires_memory": True,
            "memory_kinds": ["character", "rule", "timeline_event"],
        },
        {
            "id": "fantasy",
            "label": "幻想/奇幻",
            "style_rule": "世界中存在非现实规则、魔法、神秘力量或幻想种族；设定必须通过事件和角色行动逐步呈现。",
            "usage_rule": "世界规则应放入规则设定，影响每章行动选择。",
            "requires_memory": True,
            "memory_kinds": ["rule", "organization", "location"],
        },
        {
            "id": "mystery",
            "label": "悬疑",
            "style_rule": "信息应分层释放，线索、误导、隐瞒和推理要服务当前场景目标；不要提前揭示核心真相。",
            "usage_rule": "关键线索、禁止提前揭示内容和伏笔回收计划需要持续检查。",
            "requires_memory": True,
            "memory_kinds": ["foreshadowing", "forbidden", "timeline_event"],
        },
        {
            "id": "romance",
            "label": "恋爱",
            "style_rule": "人物关系、吸引、误解、靠近与退缩是重要推动力；情感变化需要具体行动和选择支撑。",
            "usage_rule": "关系变化不直接放进一级 UI，应写入角色卡 modules.relationships。",
            "requires_memory": True,
            "memory_kinds": ["character"],
        },
    ],
    "setting_tags": [
        {
            "id": "ts",
            "label": "TS",
            "style_rule": "角色性别、身体或自我认知变化必须影响心理、关系、社会互动和行动选择，避免只作为噱头。",
            "usage_rule": "TS 状态写入角色卡 modules.ts，不在角色卡一级 UI 固化。",
            "requires_memory": True,
            "memory_kinds": ["character"],
        },
        {
            "id": "level_system",
            "label": "等级体系",
            "style_rule": "等级、经验、阶位或数值成长影响冲突解决方式；数值变化应服务剧情，不要堆砌面板。",
            "usage_rule": "等级变化写入角色卡 modules.level_system，升级后后续章节必须保持连续。",
            "requires_memory": True,
            "memory_kinds": ["character", "rule"],
        },
        {
            "id": "skill_system",
            "label": "技能体系",
            "style_rule": "技能、专长或能力树影响角色行动方案；新增技能需要与事件、训练或代价有关。",
            "usage_rule": "技能获得和限制写入角色卡 modules.skill_system。",
            "requires_memory": True,
            "memory_kinds": ["character", "rule"],
        },
        {
            "id": "system_flow",
            "label": "系统流",
            "style_rule": "系统提示、任务、奖励或限制会推动角色选择；系统信息应简洁，不要替代角色行动。",
            "usage_rule": "系统规则放入规则设定，角色绑定状态放入角色卡 modules.system_flow。",
            "requires_memory": True,
            "memory_kinds": ["character", "rule"],
        },
        {
            "id": "dungeon",
            "label": "地下城",
            "style_rule": "地下城、迷宫或副本提供探索、战斗和资源目标；每次进入应有明确风险和收获。",
            "usage_rule": "地点结构和资源状态放入地点设定 modules.dungeon。",
            "requires_memory": True,
            "memory_kinds": ["location", "rule", "timeline_event"],
        },
    ],
    "structure_tags": [
        {
            "id": "single_protagonist",
            "label": "单主角",
            "style_rule": "主要视角、成长线和关键选择集中在一个核心主角身上，避免无必要地切换主线中心。",
            "usage_rule": "主角身份应标记在角色卡 role_flags.protagonist。",
            "requires_memory": False,
            "memory_kinds": ["character"],
        },
        {
            "id": "ensemble",
            "label": "群像",
            "style_rule": "多名角色共同推动主线；不同角色应有独立目标、视角差异和行动后果。",
            "usage_rule": "群像主要角色标记在角色卡 role_flags.ensemble_main。",
            "requires_memory": True,
            "memory_kinds": ["character"],
        },
        {
            "id": "multi_pov",
            "label": "多视角",
            "style_rule": "可以切换不同视角人物，但每次切换必须带来新的信息、误解或立场差异。",
            "usage_rule": "POV 可用角色标记在角色卡 role_flags.pov。",
            "requires_memory": True,
            "memory_kinds": ["character"],
        },
        {
            "id": "bbs",
            "label": "告示板/论坛体",
            "style_rule": "可以用论坛楼层、匿名发言、旁观者讨论或碎片信息推进部分剧情；格式要清晰，不能喧宾夺主。",
            "usage_rule": "论坛体公开信息、误传和社会反馈写入时间线或规则 modules.bbs。",
            "requires_memory": True,
            "memory_kinds": ["timeline_event", "rule"],
        },
    ],
    "style_tags": [
        {
            "id": "slow_burn",
            "label": "慢热",
            "style_rule": "情节和关系逐步累积，不急于揭示全部设定；每节仍需有明确推进，避免原地停留。",
            "usage_rule": "审稿时检查是否有推进，而不是只保留气氛。",
            "requires_memory": False,
            "memory_kinds": [],
        },
        {
            "id": "light_comedy",
            "label": "轻喜剧",
            "style_rule": "语气轻快，可有误会、吐槽和节奏反差；不要让玩笑破坏关键情绪或人物一致性。",
            "usage_rule": "作为风格规则进入提示词，不要求额外资料结构。",
            "requires_memory": False,
            "memory_kinds": [],
        },
        {
            "id": "growth",
            "label": "成长流",
            "style_rule": "角色能力、认知或关系应随事件逐步变化；成长必须有挫折、选择和反馈。",
            "usage_rule": "重要成长节点写入角色卡 modules.growth。",
            "requires_memory": True,
            "memory_kinds": ["character", "timeline_event"],
        },
        {
            "id": "battle",
            "label": "战斗",
            "style_rule": "战斗场景应包含目标、位置、限制、代价和局势变化，避免只有技能名和结果。",
            "usage_rule": "能力限制和战斗后状态写入角色卡或规则 modules。",
            "requires_memory": True,
            "memory_kinds": ["character", "rule"],
        },
    ],
}

FIELD_TO_CATEGORY = {
    "selected_genre_tags": "genre_tags",
    "selected_setting_tags": "setting_tags",
    "selected_structure_tags": "structure_tags",
    "selected_style_tags": "style_tags",
}


def list_style_tag_catalog() -> dict[str, list[dict[str, Any]]]:
    return {key: [dict(item) for item in items] for key, items in STYLE_TAG_CATALOG.items()}


def normalize_tag_ids(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        raw_values = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            raw_values = text.replace("，", ",").split(",")
        else:
            raw_values = parsed if isinstance(parsed, list) else [parsed]
    else:
        raw_values = [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        tag_id = str(raw or "").strip()
        if tag_id and tag_id not in seen:
            result.append(tag_id)
            seen.add(tag_id)
    return result


def dump_tag_ids(value: Any) -> str:
    return json.dumps(normalize_tag_ids(value), ensure_ascii=False)


def normalize_project_style_selection(project: dict[str, Any] | None) -> dict[str, list[str]]:
    project = project or {}
    return {
        field: normalize_tag_ids(project.get(field))
        for field in PROJECT_STYLE_TAG_FIELDS
    }


def selected_tag_definitions(project: dict[str, Any] | None) -> list[dict[str, Any]]:
    selection = normalize_project_style_selection(project)
    definitions: list[dict[str, Any]] = []
    for field, category in FIELD_TO_CATEGORY.items():
        by_id = {item["id"]: item for item in STYLE_TAG_CATALOG.get(category, [])}
        for tag_id in selection[field]:
            item = by_id.get(tag_id)
            if item is None:
                definitions.append(
                    {
                        "id": tag_id,
                        "label": tag_id,
                        "category": category,
                        "style_rule": "",
                        "usage_rule": "用户自定义标签，按项目写作风格理解。",
                        "requires_memory": False,
                        "memory_kinds": [],
                    }
                )
            else:
                definitions.append({"category": category, **item})
    return definitions


def dialogue_quote_definition(project: dict[str, Any] | None) -> dict[str, str]:
    quote_id = str((project or {}).get("dialogue_quote_style") or "cn_quotes").strip()
    return dict(DIALOGUE_QUOTE_STYLES.get(quote_id, DIALOGUE_QUOTE_STYLES["cn_quotes"]))


def build_prompt_modules(project: dict[str, Any] | None) -> dict[str, Any]:
    tags = selected_tag_definitions(project)
    quote_style = dialogue_quote_definition(project)
    return {
        "selected_tags": [
            {
                "category": tag.get("category", ""),
                "id": tag.get("id", ""),
                "label": tag.get("label", ""),
                "requires_memory": bool(tag.get("requires_memory")),
                "memory_kinds": tag.get("memory_kinds", []),
                "style_rule": tag.get("style_rule", ""),
                "usage_rule": tag.get("usage_rule", ""),
            }
            for tag in tags
        ],
        "dialogue_quote_style": quote_style,
        "style_rules": [tag["style_rule"] for tag in tags if tag.get("style_rule")] + [quote_style["rule"]],
        "continuity_rules": [
            tag["usage_rule"]
            for tag in tags
            if tag.get("requires_memory") and tag.get("usage_rule")
        ],
    }
