from __future__ import annotations

import json
from typing import Any


PROJECT_STYLE_TAG_FIELDS = (
    "selected_genre_tags",
    "selected_setting_tags",
    "selected_character_tags",
    "selected_structure_tags",
    "selected_style_tags",
    "selected_forbidden_tags",
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


def _tag(
    tag_id: str,
    label: str,
    style_rule: str,
    usage_rule: str,
    *,
    requires_memory: bool = False,
    memory_kinds: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": tag_id,
        "label": label,
        "style_rule": style_rule,
        "usage_rule": usage_rule,
        "requires_memory": requires_memory,
        "memory_kinds": list(memory_kinds or []),
    }


STYLE_TAG_CATALOG = {
    "genre_tags": [
        _tag("fantasy", "奇幻", "允许魔法、异族、神秘力量或非现实规则推动剧情；设定必须通过事件和选择逐步呈现。", "核心世界规则写入规则设定，重要地点和势力写入资料库。", requires_memory=True, memory_kinds=["rule", "location", "organization"]),
        _tag("western_fantasy", "西式幻想", "使用王国、骑士、教会、魔法学院、地城等西式幻想语汇，避免只堆名词。", "王国、教会、学院、公会等长期实体写入组织或地点。", requires_memory=True, memory_kinds=["organization", "location", "rule"]),
        _tag("eastern_fantasy", "东方幻想", "以灵脉、宗门、妖异、法器或神怪秩序组织世界，规则要和社会结构绑定。", "宗门、修行阶段、法器限制写入组织、规则或角色模块。", requires_memory=True, memory_kinds=["organization", "rule", "character"]),
        _tag("xianxia", "仙侠", "修行、因果、宗门和境界构成主要冲突，战力提升要有代价和门槛。", "境界、功法、誓约和宗门身份需要持续记录。", requires_memory=True, memory_kinds=["character", "rule", "organization"]),
        _tag("xuanhuan", "玄幻", "可使用原创力量体系和大型世界阶层，冲突应由力量规则和社会秩序共同驱动。", "力量层级、血脉、秘境和势力关系需进入长期设定。", requires_memory=True, memory_kinds=["character", "rule", "organization"]),
        _tag("urban", "都市", "以现代城市生活、职业、家庭和社会压力为主要舞台，超常元素应克制。", "固定工作、住处、人际关系和城市地标写入资料库。", requires_memory=True, memory_kinds=["character", "location", "organization"]),
        _tag("urban_fantasy", "都市异能", "在现代社会中隐藏或公开超常能力，日常秩序与异常事件产生张力。", "异能规则、隐藏世界边界和组织反应需持续记录。", requires_memory=True, memory_kinds=["character", "rule", "organization"]),
        _tag("campus", "校园", "以学校、社团、考试、同学关系和成长压力组织剧情。", "班级、社团、校规和关键关系写入角色、组织或规则。", requires_memory=True, memory_kinds=["character", "organization", "rule"]),
        _tag("romance", "恋爱", "关系靠行动、误解、靠近和退缩推进，情绪变化必须有具体触发。", "关系变化写入角色模块，避免下一章关系状态回滚。", requires_memory=True, memory_kinds=["character"]),
        _tag("mystery", "悬疑", "信息分层释放，线索、误导、隐瞒和推理服务当前场景目标。", "关键线索、未解谜团和禁止提前揭示内容需要持续检查。", requires_memory=True, memory_kinds=["foreshadowing", "forbidden", "timeline_event"]),
        _tag("detective", "推理", "调查、证据链和推理过程必须公平呈现，结论来自已布置信息。", "证据、嫌疑人、时间线和已排除假设需要记录。", requires_memory=True, memory_kinds=["foreshadowing", "timeline_event", "character"]),
        _tag("horror", "恐怖", "恐惧来自未知、失控、环境压迫或认知偏差，不依赖直白血腥堆叠。", "怪异规则、幸存者状态和禁忌行为写入规则或时间线。", requires_memory=True, memory_kinds=["rule", "timeline_event", "character"]),
        _tag("sci_fi", "科幻", "科技、社会结构或未来假设影响人物选择，科学概念要服务剧情。", "核心技术限制、组织利益和世界变化写入规则或组织。", requires_memory=True, memory_kinds=["rule", "organization", "location"]),
        _tag("space_opera", "太空歌剧", "使用星际航行、舰队、殖民地和跨文明冲突制造宏大叙事。", "星域、舰队、政体和航行限制写入地点、组织或规则。", requires_memory=True, memory_kinds=["location", "organization", "rule"]),
        _tag("cyberpunk", "赛博朋克", "高科技与低生活并置，公司、身体改造和信息控制形成压迫。", "义体、公司势力、身份记录和网络权限需要持续记录。", requires_memory=True, memory_kinds=["character", "organization", "rule"]),
        _tag("post_apocalypse", "末世", "资源、秩序崩塌和生存选择构成主要压力，胜利应有代价。", "据点资源、队伍状态、感染或灾变规则写入资料库。", requires_memory=True, memory_kinds=["location", "character", "rule"]),
        _tag("historical", "历史", "尊重时代生活方式、阶层、礼法和物质条件，冲突贴合时代限制。", "官职、家族、地理和历史约束写入组织、地点或规则。", requires_memory=True, memory_kinds=["organization", "location", "rule"]),
        _tag("alternate_history", "架空历史", "用改写的历史分歧塑造政治、战争和社会秩序。", "历史分歧点、政权关系和时间线变化必须记录。", requires_memory=True, memory_kinds=["timeline_event", "organization", "rule"]),
        _tag("game_world", "游戏世界", "等级、任务、职业、道具或副本机制会影响剧情，但系统信息应简洁。", "角色数值、技能、任务和装备变化写入对应模块。", requires_memory=True, memory_kinds=["character", "rule", "timeline_event"]),
        _tag("fanfiction_like", "同人感", "使用熟悉类型感和角色互动密度，但必须生成原创人物、设定和剧情。", "避免复刻真实作品的专有设定、角色名和标志性桥段。"),
        _tag("slice_of_life", "日常", "以生活细节、人际互动和小事件推进情绪，不追求每章大冲突。", "稳定关系、生活地点和长期小目标可写入角色或地点。", requires_memory=True, memory_kinds=["character", "location"]),
        _tag("adventure", "冒险", "以旅程、探索、风险和收获组织章节，每段行动应有目标和代价。", "地图进度、队伍状态、已探索地点和承诺需要记录。", requires_memory=True, memory_kinds=["location", "character", "timeline_event"]),
    ],
    "setting_tags": [
        _tag("isekai_transfer", "异世界转移", "主角从原世界进入异世界，保留记忆或常识差异，突出两个世界价值观冲突。", "记录主角原世界认知、返回动机和异世界身份变化。", requires_memory=True, memory_kinds=["character", "rule", "timeline_event"]),
        _tag("isekai_reincarnation", "异世界转生", "主角以新身份重生，前世经验影响选择但不替代当前成长。", "前世记忆、新身份、家庭和社会关系变化写入角色模块。", requires_memory=True, memory_kinds=["character", "timeline_event"]),
        _tag("second_chance", "第二次机会", "角色获得重新选择的机会，核心看点是用经验改变遗憾。", "已知未来、改变节点和未改变的风险写入时间线。", requires_memory=True, memory_kinds=["character", "timeline_event"]),
        _tag("time_loop", "时间循环", "重复时间段中信息逐步积累，角色心理和外部变量要变化。", "循环次数、保留记忆者、已尝试路线写入 modules.loop_state。", requires_memory=True, memory_kinds=["character", "timeline_event", "rule"]),
        _tag("regression", "回归过去", "主角回到过去节点，利用先验信息但必须面对蝴蝶效应。", "回归节点、已改变事件和失效情报写入时间线。", requires_memory=True, memory_kinds=["timeline_event", "character"]),
        _tag("system", "系统", "系统提示、任务、奖励或限制推动选择，但不能替代角色行动。", "系统规则和绑定状态写入规则与角色 modules.system。", requires_memory=True, memory_kinds=["character", "rule"]),
        _tag("system_flow", "系统流", "系统信息简洁出现，任务和奖励必须服务剧情压力。", "系统任务、奖励、惩罚和限制写入角色 modules.system_flow。", requires_memory=True, memory_kinds=["character", "rule"]),
        _tag("no_system", "无系统", "不使用面板、任务、奖励或数值化旁白推动剧情。", "审稿时检查是否意外写入系统提示或面板。"),
        _tag("level_system", "等级体系", "等级、经验、阶位或实力层级影响冲突解决方式，数值变化服务剧情。", "等级变化写入角色卡 modules.level_system，升级后后续章节保持连续。", requires_memory=True, memory_kinds=["character", "rule"]),
        _tag("skill_system", "技能体系", "技能、专长或能力树影响行动方案，新增技能要来自事件、训练或代价。", "技能获得、限制和熟练度写入角色卡 modules.skill_system。", requires_memory=True, memory_kinds=["character", "rule"]),
        _tag("class_system", "职业体系", "职业决定能力边界、社会身份和成长路线，转职需要明确条件。", "职业、转职条件和职业限制写入角色卡 modules.class_system。", requires_memory=True, memory_kinds=["character", "rule"]),
        _tag("magic_academy", "魔法学院", "学院课程、派系、考核和师生关系组织阶段性剧情。", "学院制度、课程、导师和社团写入地点、组织或角色。", requires_memory=True, memory_kinds=["location", "organization", "character"]),
        _tag("guild", "冒险者公会", "公会提供任务、等级、情报和交易规则，不能只是背景牌匾。", "公会等级、任务记录和人脉写入组织或角色模块。", requires_memory=True, memory_kinds=["organization", "timeline_event", "character"]),
        _tag("dungeon", "地下城", "地下城、迷宫或副本提供探索、战斗和资源目标，每次进入有明确风险。", "地点结构、资源状态和探索进度写入 location.modules.dungeon。", requires_memory=True, memory_kinds=["location", "rule", "timeline_event"]),
        _tag("tower_climbing", "爬塔", "楼层、试炼和规则逐层升级，阶段目标清晰。", "楼层进度、通关条件和奖励写入时间线或规则。", requires_memory=True, memory_kinds=["timeline_event", "rule", "character"]),
        _tag("kingdom_politics", "王国政治", "王室、贵族、军队和民意形成权力博弈，冲突要有制度后果。", "派系、头衔、盟约和公开事件写入组织或时间线。", requires_memory=True, memory_kinds=["organization", "timeline_event", "character"]),
        _tag("noble_society", "贵族社会", "礼法、血统、婚约、财产和名誉影响角色选择。", "家族关系、爵位、婚约和社交评价写入角色或组织。", requires_memory=True, memory_kinds=["character", "organization"]),
        _tag("religious_order", "教会体系", "信仰、神职、禁忌和组织利益影响世界运行。", "教义、禁忌、神职阶层和异端判断写入规则或组织。", requires_memory=True, memory_kinds=["organization", "rule"]),
        _tag("ancient_ruins", "古代遗迹", "遗迹提供历史谜团、机关、禁忌技术和世界真相碎片。", "遗迹位置、已发现信息和未解机关写入地点或伏笔。", requires_memory=True, memory_kinds=["location", "foreshadowing", "rule"]),
        _tag("contract_magic", "契约魔法", "契约、誓言或代价约束行动，违约后果明确。", "契约对象、条款、代价和触发条件写入角色或规则模块。", requires_memory=True, memory_kinds=["character", "rule"]),
        _tag("summoning", "召唤", "召唤关系带来权力、责任和信息不对称，不只作为开场事件。", "召唤者、被召唤者、契约和归属写入角色模块。", requires_memory=True, memory_kinds=["character", "rule"]),
        _tag("monster_ecology", "魔物生态", "怪物有栖息、迁徙、食物链和社会影响，避免纯刷怪。", "魔物规则、分布和威胁等级写入规则或地点。", requires_memory=True, memory_kinds=["rule", "location"]),
        _tag("public_status_board", "公开状态板", "角色状态公开可见，带来社会评价、歧视、误判或机会。", "公开状态、隐瞒信息和公众认知写入 modules.public_status。", requires_memory=True, memory_kinds=["character", "rule", "timeline_event"]),
        _tag("hidden_world_rule", "隐藏世界规则", "普通社会背后存在隐秘规则或组织，揭示要分层推进。", "隐藏规则、知情者名单和破例事件写入规则或组织。", requires_memory=True, memory_kinds=["rule", "organization", "character"]),
    ],
    "character_tags": [
        _tag("single_protagonist", "单主角", "主要视角、成长线和关键选择集中在一个核心主角身上。", "主角身份标记在角色卡 role_flags.protagonist。", memory_kinds=["character"]),
        _tag("dual_protagonists", "双主角", "两名核心人物共同推进主线，目标可互补也可冲突。", "双主角都需要角色卡和视角/主线责任标记。", requires_memory=True, memory_kinds=["character"]),
        _tag("ensemble_cast", "群像", "多名角色共同推动主线，每人应有独立目标、视角差异和行动后果。", "群像主要角色标记在角色卡 role_flags.ensemble_main。", requires_memory=True, memory_kinds=["character"]),
        _tag("ensemble", "群像", "多名角色共同推动主线，不同角色承担不同信息和情绪功能。", "群像主要角色标记在角色卡 role_flags.ensemble_main。", requires_memory=True, memory_kinds=["character"]),
        _tag("pov_protagonist", "主视角主角", "叙事紧贴主角认知，读者主要通过主角获得信息。", "主视角角色标记在 role_flags.pov。", requires_memory=True, memory_kinds=["character"]),
        _tag("weak_to_strong", "弱到强", "主角从明显短板出发，通过代价、训练和选择逐步变强。", "能力变化和代价写入角色 modules.growth。", requires_memory=True, memory_kinds=["character", "timeline_event"]),
        _tag("overpowered_hidden", "隐藏强者", "主角拥有强实力但因身份、代价或目标选择隐藏。", "真实实力、隐藏原因和暴露风险写入角色模块。", requires_memory=True, memory_kinds=["character"]),
        _tag("ordinary_person", "普通人主角", "主角以普通能力面对异常局面，靠观察、选择和关系推进。", "普通身份、限制和已获得资源写入角色卡。", requires_memory=True, memory_kinds=["character"]),
        _tag("antihero", "反英雄", "主角可有灰色手段，但核心动机和代价要清楚。", "越界行为、后果和道德边界写入角色时间线。", requires_memory=True, memory_kinds=["character", "timeline_event"]),
        _tag("reluctant_hero", "不情愿行动者", "主角不主动救世，但被规则、关系或危机推着行动。", "被迫行动的责任、承诺和逃避失败点需要记录。", requires_memory=True, memory_kinds=["character", "timeline_event"]),
        _tag("ts", "TS", "角色性别、身体或自我认知变化必须影响心理、关系和社会互动，避免只作噱头。", "TS 状态写入角色卡 modules.identity_state。", requires_memory=True, memory_kinds=["character"]),
        _tag("crossdressing", "身份伪装", "女装、男装或身份伪装服务目标、风险和关系张力。", "伪装身份、知情者和暴露风险写入角色模块。", requires_memory=True, memory_kinds=["character"]),
        _tag("nonhuman_protagonist", "非人主角", "主角的非人感知、需求和社会位置应影响行动。", "物种规则、伪装状态和能力限制写入角色或规则。", requires_memory=True, memory_kinds=["character", "rule"]),
        _tag("villainess", "恶役千金", "角色被恶名、剧本或阶层期待束缚，重点是改写命运和关系。", "恶名来源、社交评价和改变节点写入角色或时间线。", requires_memory=True, memory_kinds=["character", "timeline_event"]),
        _tag("mentor_student", "师徒", "师徒关系同时承担知识传递、价值冲突和情感牵引。", "教导进度、承诺、分歧和关系状态写入角色模块。", requires_memory=True, memory_kinds=["character"]),
        _tag("childhood_friends", "青梅竹马", "长期共同记忆影响信任、误会和未说出口的情感。", "共同过去、承诺和关系变化写入角色模块。", requires_memory=True, memory_kinds=["character"]),
        _tag("rivals", "宿敌/竞争者", "竞争关系要推动双方成长和选择，不只是口头挑衅。", "胜负记录、目标差异和关系变化写入角色模块。", requires_memory=True, memory_kinds=["character", "timeline_event"]),
        _tag("found_family", "临时家族/羁绊小队", "角色从利益同盟逐渐形成类似家人的归属感。", "队伍成员、信任变化和共同承诺写入角色模块。", requires_memory=True, memory_kinds=["character"]),
        _tag("party_adventure", "小队冒险", "小队分工、资源和内部冲突共同影响冒险结果。", "队伍职责、装备、伤势和关系状态写入角色模块。", requires_memory=True, memory_kinds=["character"]),
        _tag("relationship_slow_burn", "慢热关系", "关系靠小行动和累积信任推进，不要突然跳到亲密或决裂。", "重要关系变化写入角色卡 modules.relationship_state。", requires_memory=True, memory_kinds=["character"]),
        _tag("identity_secret", "身份秘密", "角色隐瞒身份带来信息差、风险和关系张力。", "秘密内容、知情者、暴露风险写入 modules.identity_state。", requires_memory=True, memory_kinds=["character"]),
    ],
    "structure_tags": [
        _tag("main_plot_driven", "主线推进", "每章都应推进核心目标、冲突或信息，不让支线长期偏航。", "大纲和章节规划检查主线目标是否推进。"),
        _tag("unit_episodes", "单元剧", "每个单元有相对完整的事件闭环，同时留下主线线索。", "单元状态、已解决问题和遗留伏笔写入时间线。", requires_memory=True, memory_kinds=["timeline_event", "foreshadowing"]),
        _tag("arc_structure", "篇章式结构", "按篇章组织目标、反派、地点和阶段成果。", "篇章目标、结局影响和进入下一篇的变化写入时间线。", requires_memory=True, memory_kinds=["timeline_event"]),
        _tag("quest_flow", "任务流", "任务目标、限制、奖励和失败代价清晰，任务不等于流水账。", "任务领取、完成、失败和奖励写入时间线或角色模块。", requires_memory=True, memory_kinds=["timeline_event", "character"]),
        _tag("road_movie", "旅途结构", "地点变化带来新人、新规则和新冲突，旅途本身改变角色。", "路线、已访问地点和旅途承诺写入地点或时间线。", requires_memory=True, memory_kinds=["location", "timeline_event"]),
        _tag("mystery_box", "谜团盒", "用多个层级谜团牵引阅读，回答旧问题时提出更深问题。", "谜团、假线索和已揭示事实写入伏笔模块。", requires_memory=True, memory_kinds=["foreshadowing"]),
        _tag("foreshadowing_heavy", "伏笔密集", "早期细节需要在后文回收，回收时应改变读者对旧信息的理解。", "伏笔、回收章节和当前状态写入 modules.foreshadowing_state。", requires_memory=True, memory_kinds=["foreshadowing", "timeline_event"]),
        _tag("bbs", "告示板/论坛体", "可用论坛楼层、匿名发言、旁观讨论或碎片信息推进部分剧情，格式要清晰。", "论坛公开信息、误传和社会反馈写入 modules.public_opinion。", requires_memory=True, memory_kinds=["timeline_event", "rule"]),
        _tag("multi_pov", "多视角", "视角切换必须带来新信息、误解或立场差异。", "POV 角色和视角权限标记在角色卡。", requires_memory=True, memory_kinds=["character"]),
        _tag("limited_pov", "有限视角", "叙事只呈现视角角色可感知和可推断的信息。", "审稿时检查是否越过视角泄露真相。"),
        _tag("linear_timeline", "线性时间", "按时间顺序推进，闪回应短且服务当前行动。", "重大事件按时间线记录，避免顺序矛盾。", requires_memory=True, memory_kinds=["timeline_event"]),
        _tag("nonlinear_timeline", "非线性时间", "倒叙、插叙或多时间线服务谜团和情绪，不制造无意义混乱。", "时间线锚点和读者已知信息必须记录。", requires_memory=True, memory_kinds=["timeline_event", "foreshadowing"]),
        _tag("slow_burn", "慢热", "情节和关系逐步累积，每节仍需有明确推进。", "审稿时检查推进量，而不只保留氛围。"),
        _tag("fast_paced", "快节奏", "场景目标明确，减少停顿式解释，用行动和选择承接信息。", "检查说明段是否可拆入行动。"),
        _tag("daily_to_epic", "日常到史诗", "从小范围日常逐步扩展到更大世界危机，规模升级要有铺垫。", "规模变化、责任扩大和世界反应写入时间线。", requires_memory=True, memory_kinds=["timeline_event", "rule"]),
        _tag("survival_progression", "生存成长", "资源、伤势、天气、据点和队伍信任共同构成压力。", "资源、伤势、据点和队伍状态写入角色或地点。", requires_memory=True, memory_kinds=["character", "location", "timeline_event"]),
        _tag("investigation_progression", "调查推进", "调查通过证据、访谈、矛盾和排除法逐步收束。", "线索、证人、假设和排除项写入 modules.investigation_state。", requires_memory=True, memory_kinds=["foreshadowing", "timeline_event", "character"]),
    ],
    "style_tags": [
        _tag("jp_light_novel", "日式轻小说", "对白轻快，段落清爽，角色反应鲜明，但不要复制具体作品语气。", "作为文风规则进入提示词，不要求额外资料结构。"),
        _tag("webnovel_fast_read", "网文快读", "段落短、钩子清楚、冲突密度高，信息以可读性优先。", "审稿时检查章节末尾是否保留推进钩子。"),
        _tag("restrained_prose", "克制叙事", "少用夸张形容，用动作、细节和留白承载情绪。", "作为文风规则进入提示词。"),
        _tag("lyrical", "抒情", "可使用更强意象和节奏感，但不得牺牲事件清晰度。", "审稿时检查抒情段是否仍服务场景目标。"),
        _tag("comedic", "轻喜剧", "语气轻快，可有误会、吐槽和节奏反差，但不破坏人物一致性。", "作为文风规则进入提示词。"),
        _tag("light_comedy", "轻喜剧", "语气轻快，可有误会、吐槽和节奏反差，但不破坏关键情绪。", "作为文风规则进入提示词。"),
        _tag("deadpan_humor", "冷面吐槽", "吐槽来自角色认知差和反差，不用作者旁白强行解释笑点。", "作为文风规则进入提示词。"),
        _tag("warm_healing", "治愈", "用照顾、修复、理解和小胜利提供温暖体验。", "关系修复和重要承诺可写入角色模块。", requires_memory=True, memory_kinds=["character"]),
        _tag("dark_tension", "黑暗压迫", "保持危险、代价和道德压力，但避免无意义虐待堆叠。", "伤害、创伤和不可逆后果需要进入角色或时间线。", requires_memory=True, memory_kinds=["character", "timeline_event"]),
        _tag("suspenseful", "悬疑压迫", "通过未知、倒计时、信息差和威胁接近制造张力。", "威胁来源、已知线索和未揭示事实写入伏笔或时间线。", requires_memory=True, memory_kinds=["foreshadowing", "timeline_event"]),
        _tag("romantic_tension", "暧昧拉扯", "用未说出口的选择、误会和靠近退缩制造张力。", "关系阶段和关键误会写入角色模块。", requires_memory=True, memory_kinds=["character"]),
        _tag("battle_shounen", "少年热血", "战斗、友情、目标和突破感明确，胜利来自选择和代价。", "突破、伤势、技能变化写入角色模块。", requires_memory=True, memory_kinds=["character"]),
        _tag("dialogue_heavy", "对白密集", "用对白推进关系和信息，避免对白变成说明书。", "审稿时检查每段对白是否改变关系、信息或行动。"),
        _tag("psychology_heavy", "心理描写重", "心理活动要和外部行动互相验证，避免长段原地内耗。", "关键心理转折写入角色状态。", requires_memory=True, memory_kinds=["character"]),
        _tag("action_heavy", "动作场面重", "动作场景强调空间、目标、限制和局势变化。", "伤势、装备消耗和战后状态写入角色模块。", requires_memory=True, memory_kinds=["character"]),
        _tag("worldbuilding_heavy", "设定展开重", "设定通过冲突、职业、制度和选择展开，避免一次性说明文堆砌。", "核心规则和势力结构写入资料库。", requires_memory=True, memory_kinds=["rule", "organization", "location"]),
        _tag("growth", "成长流", "能力、认知或关系随事件逐步变化，成长必须有挫折、选择和反馈。", "重要成长节点写入角色卡 modules.growth。", requires_memory=True, memory_kinds=["character", "timeline_event"]),
        _tag("battle", "战斗", "战斗场景包含目标、位置、限制、代价和局势变化，避免只有技能名和结果。", "能力限制和战斗后状态写入角色卡或规则 modules。", requires_memory=True, memory_kinds=["character", "rule"]),
        _tag("corner_quotes", "日式引号「」", "角色对白统一使用日式直角引号「」。", "和 dialogue_quote_style 保持一致，避免同章混用。"),
        _tag("cn_quotes", "中文引号“”", "角色对白统一使用中文弯引号“”。", "和 dialogue_quote_style 保持一致，避免同章混用。"),
    ],
    "forbidden_tags": [
        _tag("no_harem", "不要后宫", "不要把多名角色对主角的单向迷恋作为默认奖励。", "审稿时检查关系线是否变成后宫收集。"),
        _tag("no_forced_villain", "不要强行反派势力", "不要为了冲突临时制造缺乏动机的反派组织。", "反派或敌对势力必须有目标、资源和行动逻辑。"),
        _tag("no_system", "不要系统", "不要出现系统面板、任务、奖励、惩罚或机械提示音。", "如项目选择无系统，审稿时检查是否误写系统元素。"),
        _tag("no_infodump", "不要说明文堆设定", "避免连续大段解释世界设定，优先通过行动和冲突呈现。", "审稿时检查设定说明是否可拆入场景。"),
        _tag("no_early_truth_reveal", "不要过早揭示真相", "核心谜底和世界真相应分层释放，不提前摊牌。", "禁止提前揭示内容写入 forbidden 或伏笔状态。", requires_memory=True, memory_kinds=["forbidden", "foreshadowing"]),
        _tag("no_ooc", "不要人物 OOC", "角色不得为了推进剧情突然违背已建立动机和能力边界。", "审稿时对照角色卡动机、性格和关系状态。", requires_memory=True, memory_kinds=["character"]),
        _tag("no_power_reset", "不要实力重置", "不要无解释取消角色已获得能力、装备或经验。", "能力变化必须写入角色模块并保持连续。", requires_memory=True, memory_kinds=["character"]),
        _tag("no_relationship_reset", "不要关系重置", "不要让已经改变的信任、误会或亲密度在下一章无故回滚。", "关系变化必须写入角色 modules.relationship_state。", requires_memory=True, memory_kinds=["character"]),
        _tag("no_tonal_break", "不要风格突变", "不要在严肃、治愈、恐怖或悬疑段落突然切换无关玩笑。", "审稿时检查章节内语气是否服务同一情绪目标。"),
        _tag("no_deus_ex_machina", "不要机械降神", "不要用未铺垫的新能力、新角色或巧合解决关键危机。", "关键解法必须回扣已有伏笔、能力或代价。", requires_memory=True, memory_kinds=["foreshadowing", "character"]),
        _tag("no_chatty_ai_voice", "不要聊天化 AI 腔", "避免解释式、总结式、客服式和现代网络聊天口吻污染正文。", "审稿时检查旁白是否像作者在解释创作意图。"),
    ],
}

FIELD_TO_CATEGORY = {
    "selected_genre_tags": "genre_tags",
    "selected_setting_tags": "setting_tags",
    "selected_character_tags": "character_tags",
    "selected_structure_tags": "structure_tags",
    "selected_style_tags": "style_tags",
    "selected_forbidden_tags": "forbidden_tags",
}


def list_style_tag_catalog() -> dict[str, list[dict[str, Any]]]:
    return {key: [dict(item) for item in items] for key, items in STYLE_TAG_CATALOG.items()}


def search_style_tags(query: str, category: str | None = None) -> list[dict[str, Any]]:
    needle = str(query or "").strip().lower()
    categories = [category] if category else list(STYLE_TAG_CATALOG)
    matches: list[dict[str, Any]] = []
    for category_name in categories:
        for item in STYLE_TAG_CATALOG.get(category_name, []):
            haystack = " ".join(
                str(item.get(key, ""))
                for key in ("id", "label", "style_rule", "usage_rule")
            ).lower()
            if not needle or needle in haystack:
                matches.append({"category": category_name, **item})
    return matches


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
