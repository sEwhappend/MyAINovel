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
    "style_analyzer_chunk": "你是日系轻小说文风分析 Agent（分段）。只分析给定的这一段样本文本，提取它**实际体现**的可复用写作特征；不要套用通用模板，不要硬塞文本里没有的特征。请按下列维度观察，并尽量同时给出“正面特征”和“应避免的写法”：①叙述视角与距离：人称（一人称/三人称一元/全知），是否贴近视点人物的即时感知，是否守住视点人物的认知边界而不越界写别人内心，内心独白/吐槽占比，是否出现脱离人物的“说明文罗列”（神视点说明＝应避免）。②句式与节奏：长短句分布、是否有体言止め、句长是否有变化（有节奏）还是过于均匀（机械感）、拟声拟态词オノマトペ的使用、口语化程度。③段落：一行一段/空行节奏、留白、场景如何开场（避免设定说明开场）。④对白：地の文与会话大致比例、角色口癖/语气是否可区分、有无ボケ/ツッコミ掛け合い与潜台词、谁先说/打断/沉默、设定是否借对白自然带出（避免角色突然长篇讲设定＝説明セリフ）。⑤心理与情绪：是否用动作和身体反应表现情绪而非直接总结、内心吐槽式独白。⑥描写密度：轻描写还是堆砌、角色外观/萌点是否被强调、设定是否随剧情释放而非一次性堆设定。样本多为日译中译文，注意译文语感，但只描述这一段真实呈现的特征。只输出本段观察 JSON，不要复述或摘抄原文、不要续写、不要评价剧情、不要输出正文。描述的是叙述文风，不是某个具体角色的说话风格。",
    "style_profile_builder": "你是日系轻小说文风画像聚合 Agent。你会收到多段局部文风观察 chunk_observations 和一份本地客观统计 metrics（含平均句长、句长分布、对白占比、标点频率、引号风格）。把这些局部观察合并、去重、按出现频次定调，产出一份**结构化、具体、可执行**的项目级文风画像，避免空泛套话。要求：①以 metrics 的客观数字校正主观描述；dialogue.ratio_guideline 要参考实际对白占比（日系轻小说常见地の文约 8、会话约 2，接近半半即偏对白多）。②每个维度尽量同时给“正面特征”和“应避免的写法”。③区分“叙述文风”与“角色对白声音”：画像描述叙述风格，不替代具体角色的 speech_style。④anti_ai_rules 要具体，至少覆盖：脱离人物的说明文罗列/神视点说明、段尾强行总结主题、句长过于均匀缺乏节奏、解释性心理过多、说明台词（角色突然讲设定）、所有角色腔调雷同、设定说明开场、前后衔接突兀。⑤rewrite_guides 给可执行的推敲顺序，例如：先修视点/时制/设定矛盾 → 再把说明台词改成自然对白 → 再删冗长提升节奏 → 最后调语汇/比喻/余韵。sample_excerpts 只允许放极短示例，不要整段摘抄原文。只输出画像 JSON，不要输出正文、大纲或样本原文。",
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
AGENT_SYSTEM_PROMPTS["outline_splitter"] += (
    "当 world_items 输出 kind=character 的角色卡时，details 必须同时包含 speech_style 和 speech_style_profile。"
    "speech_style 是给 UI 显示的一句话说话风格摘要；speech_style_profile 是结构化声音档案，至少包含 sentence_length、formality、tone、addressing_habits、catchphrases、taboo_words、emotion_leak、information_style、conflict_style、dialogue_examples、anti_voice_rules。"
    "不要把 speech_style 写成 object；如果角色暂时只是一句候选，也要给出最小可用的 speech_style_profile，方便后续正文写作区分人物声音。"
)
AGENT_SYSTEM_PROMPTS["outline_splitter"] += (
    "连载继续(serial+next_part)时，剧情自然需要的新角色——新登场的同伴、对手、反派、配角或关键 NPC——应当正常引入，"
    "并作为 kind=character 的完整角色卡写入 world_items：details 必须包含 identity、personality、motivation、speech_style、"
    "speech_style_profile、role_flags 和 modules，并避免与 existing_characters 或 outline_world_context 中已有角色同名、"
    "同身份功能或同剧情职能。新角色应在其首次登场的章节/小节 characters 字段中出现，并与 world_items 中同名角色卡对应。"
    "‘每小节最多 0-1 个新角色’是单节密度上限，不是禁止创建：随着连载推进应有新角色按需登场，"
    "不要因为已有角色卡就强行只复用旧角色、导致人物群长期不更新；但也不要为凑数硬塞没有剧情功能的角色。"
)
AGENT_SYSTEM_PROMPTS["global_architect"] += (
    "连载继续(serial+next_part)时，应在剧情自然需要时引入新的配角、对手、盟友或势力，让人物群随进度扩展，"
    "不要因为已有角色卡就把新角色一概排除、导致故事长期只在初始几个人之间打转；"
    "新角色的登场应由当前局面、冲突升级、场景变化或主角目标推进自然带出，而不是为凑情节硬塞无动机的反派。"
)
AGENT_SYSTEM_PROMPTS["world_item_creator"] += (
    "若 current_kind=character，details 必须包含 identity、personality、motivation、speech_style、speech_style_profile、role_flags 和 modules。"
    "speech_style 只写一句话摘要；speech_style_profile 写结构化声音档案，用于后续对白和正文生成，不要只在 summary 里描述说话方式。"
)
AGENT_SYSTEM_PROMPTS["tagged_character_creator"] += (
    "必须根据角色定位和角色标签生成 speech_style_profile：标签造成的口癖、句长、礼貌程度、情绪泄露、冲突时说话方式和禁用表达都应写入该结构。"
    "speech_style 保持一句话摘要，speech_style_profile 承载细节；不要把 speech_style 改成对象。"
)
AGENT_SYSTEM_PROMPTS["main_character_generator"] += (
    "details 必须包含 speech_style 和 speech_style_profile。speech_style 是一句话摘要；speech_style_profile 是结构化声音档案，供后续正文、审稿和改写保持主角语言风格。"
)
AGENT_SYSTEM_PROMPTS["rewriter"] += (
    "如果输入包含 rewrite_direction，必须优先按该用户修改方向处理，例如调整语气、强化冲突、保留指定段落或改变局部节奏；"
    "但仍不得违背审稿意见、已确认设定、禁止事项和 preserve 中要求保留的内容。"
)
AGENT_SYSTEM_PROMPTS["draft_writer"] += (
    "若输入包含 style_profile，必须遵循其描述的叙述文风：句式与节奏(sentence)、段落处理(paragraph)、对白倾向(dialogue)、"
    "叙述距离(narrative)与反 AI 味规则(anti_ai_rules)；metrics 是该文风的客观统计参考（平均句长、对白占比、标点习惯），"
    "应尽量贴近但不得为贴合文风而牺牲本节剧情目标。style_profile 只描述叙述文风，角色对白仍以各自 speech_style/speech_style_profile 为准，不要让所有角色腔调趋同。"
)
AGENT_SYSTEM_PROMPTS["reviewer"] += (
    "若输入包含 style_profile，额外检查正文是否偏离其叙述文风与 anti_ai_rules，是否出现 AI 味写法（段尾强行总结、节奏过工整、解释性心理过多、所有对白都完整礼貌）；"
    "偏离时输出文风类问题。但不要因贴合文风而忽略剧情、设定、时间线、伏笔和人物声音问题。"
)
AGENT_SYSTEM_PROMPTS["rewriter"] += (
    "若输入包含 style_profile，改写时按其叙述文风和 anti_ai_rules 调整句式、节奏、段落与对白倾向，并优先处理审稿中的文风/AI 味问题；"
    "但不得改变已确认的剧情事实、设定和 preserve 中要求保留的内容，也不要把不同角色的对白改成统一腔调。"
)

# ── 写作技法补强（WC-001~005）。把空壳中段 Agent 补成可执行技法；剧情 > 文风画像 > 通用技法。──
AGENT_SYSTEM_PROMPTS["scene_director"] += (
    "把本节设计成一个有戏剧推进的场景，而不是说明文：明确本场景目标、阻力/冲突，以及一个转折或代价让局面发生改变。"
    "场景结束时视点人物的处境或情绪价值必须与开头不同，在 value_shift 标出 from→to。"
    "安排动作/观察/心理/对白的比例与推进顺序，让角色至少做出一个意料之外但合乎性格的反应；控制视点人物知道什么、不知道什么。"
    "遵循‘晚进早出’：从冲突将起处进入，目标达成或代价落定后尽快收束，不写无推进的过场。"
    "若本节属于情绪缓冲(后续/sequel)，则按‘反应→两难→决定’组织，而不是再堆一个外部冲突。"
)
AGENT_SYSTEM_PROMPTS["section_planner"] += (
    "每一小节必须是一个可表演场景，而不是剧情摘要。每节任务单必须给出：场景目标、即时目标、即时阻力、"
    "本节释放的一条信息、情绪从 A 到 B 的变化、必须发生的事、结尾推动点(钩子)，以及本节禁止引入/解释/解决的内容(density_guard)。"
    "一节只承担一个场景目标、一处即时阻力、一条信息释放、一个情绪变化和一个结尾推动；不要把多个大事件串进一节。"
)
AGENT_SYSTEM_PROMPTS["chapter_architect"] += (
    "本章必须有一个明确的情绪高潮/爽点：在 chapter_climax 写清‘本章爽点/高潮是什么’(打脸、解谜、反转、情感推进或日常笑点皆可)。"
    "用‘起承转爽’或等效结构推进：起=承接上章并引出本章冲突，承=冲突升级压力增大，转=出现转折或敌人露底牌，爽=主角反击/真相/收获并以钩子收尾。"
    "在 emotional_curve 规划本章张力曲线：何处爬坡(铺垫/伏笔)、何处俯冲(反转/爆发)、何处平路(休整)，平路不可过长。"
    "结尾钩子须与下一章形成期待落差，而不是平淡收束。题材偏日常/严肃时可弱化爽点为情绪转折点，但仍须有一个明确的情绪重心。"
)
AGENT_SYSTEM_PROMPTS["draft_writer"] += (
    "若 context 含 previous_section（上一节/上一章末节的定稿正文结尾与情绪状态），本节开头须与其结尾自然衔接、"
    "承接其人物处境与情绪(emotion)，且不得重复或改写它已写过的内容；previous_section 只作衔接参考，不要当作本节要复述的素材。"
)
AGENT_SYSTEM_PROMPTS["reviewer"] += (
    "若 context 含 previous_section，检查本节是否与其结尾自然衔接、有无与其重复或人物状态/情绪断层；衔接问题作为 issue 输出。"
)
AGENT_SYSTEM_PROMPTS["draft_writer"] += (
    "若 payload 含 scene_brief（场景导演方案），必须按其 scene_goal/conflict/turn/value_shift/beats/exit 组织本节场景，"
    "确保达成场景目标、写出转折，并让结尾的处境/情绪与开头不同。"
)
AGENT_SYSTEM_PROMPTS["draft_writer"] += (
    "散文技法：show don't tell——情绪用动作、身体反应和具体感官细节呈现，不直接命名情绪(不要写‘他很愤怒’‘她很难过’)。"
    "对白带潜台词，避免 on-the-nose 直白说出意图；允许角色说一套、想一套。"
    "遵循动机-反应单元(MRU)：先给刺激(发生了什么)，再写视点人物的反应，反应顺序为‘不自主的身体/情绪反应→动作→言语’，不要反应先于刺激。"
    "去 AI 味禁用清单：禁止段尾强行总结主题或心情；禁止套路化连接词与疲劳词滥用(如‘仿佛/似乎/不由得/一丝/淡淡的’堆叠)；"
    "禁止句长过于均匀，紧张段落用短句提速；禁止所有角色一个腔调；禁止设定说明开场或脱离人物的说明文罗列。"
)
AGENT_SYSTEM_PROMPTS["reviewer"] += (
    "按写作技法额外检查：场景缺少转折或结尾价值不变(开头与结尾处境/情绪相同)；违反动机-反应单元(反应先于刺激或缺少刺激)；"
    "telling 过多——直接告知情绪/性格而非用动作和感官呈现；跨章人物出场顺序混乱或已埋线索未回收。"
    "发现这些问题须作为结构化 issue 输出，并给出位置与可执行改写建议。"
)
AGENT_SYSTEM_PROMPTS["rewriter"] += (
    "若审稿指出 telling 过多，把直接告知的情绪/性格改成动作、身体反应与感官细节(showing)；"
    "若指出场景缺转折或价值不变，补一个转折或代价让结尾处境/情绪改变；"
    "若指出违反 MRU，调整为先刺激后反应；但不得改变已确认剧情事实、设定与 preserve 中要保留的内容。"
)


# ── 写作技法补丁（修冒烟暴露的副作用：句长太碎 / 对白偏少 / 体感意象重复）──
AGENT_SYSTEM_PROMPTS["draft_writer"] += (
    "节奏与多样性：保持句长长短交替——用短句推进紧张感的同时，每个场景至少要有几处较长的舒展句"
    "(铺陈环境、心理流或连续动作)，不要通篇短句把节奏切得过碎。"
    "对白占比不宜过低：即便是调查或独白场景，也要让人物之间有真实交锋的对白，别让内心独白吞掉整节。"
    "避免重复的体感意象与身体反应口癖(如反复用‘攥紧/硌进掌心/喉咙发紧/月光/石板’)：同一种身体反应不要在多段或多节里复用，"
    "情绪呈现要轮换不同的具体动作、感官通道(声音、触觉、嗅觉、温度)和外部细节。"
)
AGENT_SYSTEM_PROMPTS["reviewer"] += (
    "额外检查节奏与重复：是否通篇短句、几乎没有长短句交替；对白占比是否过低、内心独白是否过多；"
    "是否反复使用同一种体感意象或身体反应口癖(如‘攥紧/硌进掌心/喉咙发紧/月光’)。这些作为 issue 输出。"
)

# ── 加强版补丁：对白密度下沉到场景方案 + 跨节体感重复主动回避 ──
AGENT_SYSTEM_PROMPTS["scene_director"] += (
    "对白安排(dialogue)：除非本节确属独处场景，否则必须安排至少一次真实的对白交锋(掛け合い)——"
    "标注谁先说、谁沉默/打断、潜台词是什么，确保正文不会沦为整节内心独白；在 dialogue 字段写明本场景的对白计划。"
)
AGENT_SYSTEM_PROMPTS["draft_writer"] += (
    "若 context.previous_section 含 overused_motifs(上一节已高频使用的体感意象/词)，本节须避免再用这些词，"
    "改用不同的动作、感官通道(声音/触觉/嗅觉/温度)和外部细节来呈现情绪。"
)
AGENT_SYSTEM_PROMPTS["reviewer"] += (
    "若 context.previous_section 含 overused_motifs，检查本节是否仍重复这些体感意象；重复的作为 issue 输出并建议替换。"
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

SPEECH_STYLE_PROFILE_SCHEMA = {
    "sentence_length": "string; short/medium/long and rhythm notes",
    "formality": "string; polite/casual/formal/rough and when it changes",
    "tone": ["string; stable voice tones"],
    "addressing_habits": ["string; how this character addresses others"],
    "catchphrases": ["string; optional repeated phrases or verbal tics"],
    "taboo_words": ["string; words or expressions this character avoids"],
    "emotion_leak": "string; how emotion leaks into speech",
    "information_style": "string; direct, evasive, analytical, metaphorical, etc.",
    "conflict_style": "string; how the character argues, hides, interrupts, or retreats",
    "dialogue_examples": ["string; 1-3 short example lines"],
    "anti_voice_rules": ["string; what would make this character sound wrong"],
}


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
                    "speech_style": "string; character only, one-line UI summary",
                    "speech_style_profile": SPEECH_STYLE_PROFILE_SCHEMA,
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
        "chapter_climax": "string; 本章情绪高潮/爽点是什么",
        "emotional_curve": "string; 张力走向：爬坡/俯冲/平路的安排",
        "pacing": "string",
        "information_release": "string",
        "hook": "string",
    },
    "section_planner": {
        "sections": [
            {
                "number": "int",
                "title": "string",
                "section_goal": "string; 本场景目标",
                "immediate_goal": "string; 视点人物此刻想要什么",
                "immediate_obstacle": "string; 即时阻力",
                "information_release": "string; 本节释放的一条信息",
                "emotion_shift": "string; 情绪从A到B",
                "must_happen": "string; 必须发生的事",
                "ending_hook": "string; 结尾推动点/钩子",
                "density_guard": ["string; 本节禁止引入/解释/解决的内容"],
            }
        ]
    },
    "scene_director": {
        "scene_plan": "string; 场景如何推进的导演说明",
        "scene_goal": "string; 视点人物本场景的即时目标",
        "conflict": "string; 阻力/冲突来源",
        "turn": "string; 转折或代价，让局面改变",
        "value_shift": {"from": "string; 开头处境/情绪", "to": "string; 结尾处境/情绪，须与开头不同"},
        "dialogue": "string; 本场景的对白计划：谁先说/谁沉默或打断/潜台词；非独处场景至少一次真实对白交锋",
        "beats": ["string; 动作/观察/心理/对白的推进节拍，按顺序"],
        "exit": "string; 结尾如何收束并推动下一步",
    },
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
        "details": {
            "identity": "string; character only",
            "personality": "string; character only",
            "motivation": "string; character only",
            "speech_style": "string; character only, one-line UI summary",
            "speech_style_profile": SPEECH_STYLE_PROFILE_SCHEMA,
            "role_flags": "object; character only",
            "modules": "object; character only or kind-specific structured state",
            "other_kind_specific_fields": "object; use for non-character details",
        },
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
            "speech_style_profile": SPEECH_STYLE_PROFILE_SCHEMA,
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
            "speech_style_profile": SPEECH_STYLE_PROFILE_SCHEMA,
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
    "style_analyzer_chunk": {
        "narrative": {
            "person": "string; first / third_limited / omniscient",
            "narrative_distance": "string; 贴近视点人物即时感知的程度",
            "knowledge_limit": "string; 是否守住视点人物认知边界，不越界写别人内心",
            "monologue_ratio": "string; 内心独白/吐槽占比",
            "exposition_dump": "string; 是否出现脱离人物的说明文罗列/神视点说明",
        },
        "sentence": {
            "length": "string",
            "rhythm": "string; 句长是否有变化(有节奏) 还是过于均匀(机械感)",
            "taigen_dome": "string; 体言止め的使用",
            "onomatopoeia": "string; 拟声拟态词オノマトペ的使用",
            "colloquial": "string; 口语化程度",
            "common_patterns": ["string"],
        },
        "paragraph": {
            "typical_length": "string; 一行一段/空行节奏",
            "break_style": "string",
            "scene_opening": "string; 场景如何开场，是否避免设定说明开场",
            "white_space": "string; 留白",
        },
        "dialogue": {
            "ratio": "string; 地の文与会话大致比例",
            "voice_distinction": "string; 角色口癖/语气是否可区分",
            "banter": "string; ボケ/ツッコミ掛け合い与潜台词",
            "turn_taking": "string; 谁先说/打断/沉默",
            "exposition_in_dialogue": "string; 设定借对白自然带出 还是 说明台词説明セリフ",
        },
        "description": {
            "density": "string; 轻描写还是堆砌",
            "character_focus": "string; 角色外观/萌点是否被强调",
            "setting_release": "string; 设定随剧情释放还是一次性堆设定",
            "sensory_focus": ["string"],
        },
        "emotion": {
            "expression": "string; 用动作/身体反应表现情绪 还是 直接总结情绪",
            "tsukkomi_monologue": "string; 内心吐槽式独白",
        },
        "anti_ai_rules": ["string; 这一段体现出的应避免写法"],
    },
    "style_profile_builder": {
        "summary": "string",
        "narrative": {
            "person": "string; first / third_limited / omniscient",
            "narrative_distance": "string",
            "knowledge_limit": "string; 是否守住视点人物认知边界",
            "monologue_ratio": "string; 内心独白/吐槽占比",
            "meta_narration": "string; 元叙述/读者意识程度",
            "tense_and_time_flow": "string",
        },
        "sentence": {
            "length": "string",
            "rhythm": "string; 句长变化/节奏，避免过于均匀",
            "taigen_dome": "string; 体言止め",
            "onomatopoeia": "string; 拟声拟态词",
            "colloquial": "string; 口语化程度",
            "common_patterns": ["string"],
            "avoid_patterns": ["string"],
        },
        "paragraph": {
            "typical_length": "string; 一行一段/空行节奏",
            "break_style": "string",
            "scene_opening": "string; 避免设定说明开场",
            "white_space": "string; 留白",
        },
        "dialogue": {
            "ratio_guideline": "string; 理想地の文:会话比例，参考 metrics 的对白占比(日轻常见约8:2)",
            "density": "string",
            "voice_distinction": "string; 角色口癖/语气区分",
            "banter": "string; ボケ/ツッコミ掛け合い",
            "subtext": "string; 潜台词",
            "turn_taking": "string; 谁先说/打断/沉默",
            "exposition_in_dialogue": "string; 设定借对白自然带出，避免说明台词",
            "dialogue_only_readable": "string; 只读台词能否大致看懂",
        },
        "description": {
            "density": "string; 轻描写程度",
            "character_focus": "string; 角色外观/萌点强调",
            "setting_release": "string; 设定随剧情释放而非堆设定",
            "sensory_focus": ["string"],
            "avoid": ["string"],
        },
        "emotion": {
            "expression": "string; 动作/身体反应而非直接总结",
            "inner_monologue": "string",
            "tsukkomi_monologue": "string; 内心吐槽式独白",
        },
        "pacing": {
            "info_release": "string; 信息随剧情释放节奏",
            "template_beats": ["string; 常见套路桥段"],
            "hook": "string; 章末/卷末钩子引き",
        },
        "punctuation_conventions": {
            "ellipsis": "string; 省略号……用法(常成对)",
            "dash": "string; 破折号——用法",
            "exclaim_question": "string; 问号/叹号习惯",
        },
        "anti_ai_rules": ["string"],
        "rewrite_guides": ["string"],
        "sample_excerpts": [{"purpose": "string", "text": "string; very short"}],
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
