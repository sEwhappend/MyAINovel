import json
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_ai_novel.pipeline import NovelPipeline, parse_length_target
from my_ai_novel.storage import NovelStore


TEST_OUTPUT = ROOT / "test-output"


class FakeLLM:
    config = {"chat_model": "fake"}

    def chat_json(self, agent_name, messages, schema_hint=None):
        if agent_name == "global_architect":
            return {
                "expanded_outline": "丰满后的全书框架",
                "core_conflict": "旧宅真相与现实秩序冲突",
                "main_arc": "林砚逐步接近父亲失踪真相",
                "themes": ["记忆", "谎言"],
                "ending_direction": "真相被延后揭示",
            }
        if agent_name == "outline_splitter":
            return {
                "expanded_outline": "丰满后的全书框架",
                "chapters": [
                    {
                        "number": 1,
                        "title": "旧宅",
                        "story_time": "雨夜",
                        "location": "旧宅",
                        "characters": ["林砚"],
                        "goal": "发现入口",
                        "outline": "进入旧宅",
                        "sections": [
                            {
                                "number": 1,
                                "title": "走廊",
                                "story_time": "十点",
                                "location": "走廊",
                                "characters": ["林砚"],
                                "goal": "发现拖痕",
                                "scene": "走廊",
                            }
                        ],
                    }
                ],
            }
        if agent_name == "draft_writer":
            return {"content": "粗稿正文", "notes": ""}
        if agent_name == "reviewer":
            return {
                "issues": [
                    {
                        "type": "pacing",
                        "severity": "medium",
                        "location": "第二段",
                        "description": "节奏慢",
                        "suggestion": "压缩",
                    }
                ],
                "summary": "需压缩",
            }
        if agent_name == "rewriter":
            return {"content": "改写正文", "rewrite_notes": "已压缩"}
        if agent_name == "world_item_enricher":
            return {
                "name": "林砚改名",
                "summary": "补全后的角色摘要",
                "details": {"motivation": "寻找真相", "speech_style": "克制"},
                "tags": "主角,AI补全",
                "status": "active",
            }
        if agent_name == "world_item_creator":
            return {
                "kind": "location",
                "name": "钟楼广场",
                "summary": "故事开局的重要公共空间。",
                "details": {"atmosphere": "明亮但暗藏监视"},
                "tags": "AI创建",
                "status": "candidate",
            }
        if agent_name == "main_character_generator":
            return {
                "name": "林砚",
                "summary": "被旧宅记忆牵引的调查员。",
                "details": {
                    "identity": "调查员",
                    "personality": "克制敏锐",
                    "motivation": "确认旧宅与父亲失踪的关系",
                    "speech_style": "短句，回避情绪表达",
                    "role_flags": {"protagonist": True},
                    "modules": {"growth": {"start": "不信任他人"}},
                },
                "tags": "主角",
                "status": "candidate",
            }
        if agent_name == "chapter_memory_writer":
            return {
                "world_items": [
                    {
                        "kind": "timeline_event",
                        "name": "旧宅雨夜发现拖痕",
                        "summary": "林砚在旧宅发现新的案件线索。",
                        "details": {"chapter": "旧宅入口", "payoff_plan": "下一章追查"},
                        "tags": "线索",
                        "status": "candidate",
                    },
                    {"kind": "unknown", "name": "忽略无效类型"},
                ],
                "notes": "已提取章末记忆",
            }
        return {"section": {"goal": "更新目标"}, "content": "ok"}

    def embed(self, texts):
        raise RuntimeError("no embedding")


class StreamingFakeLLM(FakeLLM):
    def stream_text(self, model, messages, on_delta):
        self.stream_model = model
        self.stream_messages = messages
        for chunk in ["流式", "正文"]:
            on_delta(chunk)
        return "流式正文"


class GlobalOutlineStreamingFakeLLM(FakeLLM):
    config = {"chat_model": "fast-model", "review_model": "strong-model"}

    def stream_text(self, model, messages, on_delta):
        self.stream_model = model
        self.stream_messages = messages
        chunks = ["流式", "全书故事大纲"]
        for chunk in chunks:
            on_delta(chunk)
        return "".join(chunks)


class OutlineSplitStreamingFakeLLM(FakeLLM):
    config = {"chat_model": "split-model", "review_model": "review-model"}

    def stream_text(self, model, messages, on_delta):
        self.stream_model = model
        self.stream_messages = messages
        chunks = [
            '{"expanded_outline":"丰满后的全书框架","chapters":[',
            '{"number":1,"title":"流式旧宅","location":"旧宅","characters":["林砚"],',
            '"sections":[{"number":1,"title":"流式走廊","location":"走廊","characters":["林砚"]}]}]}',
        ]
        for chunk in chunks:
            on_delta(chunk)
        return "".join(chunks)


class InvalidOutlineSplitStreamingFakeLLM(FakeLLM):
    config = {"chat_model": "split-model"}

    def stream_text(self, model, messages, on_delta):
        self.stream_model = model
        chunks = ['{"chapters":[', '{"number":1']
        for chunk in chunks:
            on_delta(chunk)
        return "".join(chunks)


class LegacyStreamingSplitFakeLLM(FakeLLM):
    def chat_json(self, agent_name, messages, schema_hint=None):
        if agent_name == "outline_splitter":
            raise AssertionError("legacy outline metadata should not call outline_splitter")
        return super().chat_json(agent_name, messages, schema_hint)

    def stream_text(self, model, messages, on_delta):
        raise AssertionError("legacy outline metadata should not call stream_text")


class InspectingFakeLLM(FakeLLM):
    def __init__(self) -> None:
        self.calls = []

    def chat_json(self, agent_name, messages, schema_hint=None):
        self.calls.append({"agent_name": agent_name, "messages": messages, "schema_hint": schema_hint})
        return super().chat_json(agent_name, messages, schema_hint)


class LegacySplitFakeLLM(FakeLLM):
    def chat_json(self, agent_name, messages, schema_hint=None):
        if agent_name == "outline_splitter":
            raise AssertionError("legacy outline metadata should not call outline_splitter")
        return super().chat_json(agent_name, messages, schema_hint)


class PipelineTests(unittest.TestCase):
    def assertSystemRuleBeforeFirstUser(self, messages, expected_content):
        first_user_index = next(index for index, message in enumerate(messages) if message["role"] == "user")
        self.assertEqual(first_user_index, 1)
        matching_indexes = [
            index
            for index, message in enumerate(messages)
            if message["role"] == "system" and expected_content in message["content"]
        ]
        self.assertTrue(matching_indexes)
        self.assertLess(matching_indexes[0], first_user_index)

    def setUp(self) -> None:
        TEST_OUTPUT.mkdir(exist_ok=True)
        self.store = NovelStore(TEST_OUTPUT / f"pipeline_{uuid.uuid4().hex}.db")
        self.project_id = self.store.create_project({"title": "测试", "global_concept": "旧宅"})
        self.pipeline = NovelPipeline(self.store, FakeLLM())

    def test_outline_split_draft_review_rewrite_flow(self) -> None:
        outline = self.pipeline.expand_global_concept(self.project_id)
        split = self.pipeline.confirm_outline_split(self.project_id, outline["version_id"])
        self.assertEqual(split, {"chapters": 1, "sections": 1, "world_items": 5})
        chapter = self.store.list_chapters(self.project_id)[0]
        section = self.store.list_sections(chapter["id"])[0]
        draft = self.pipeline.write_section_draft(self.project_id, section["id"])
        self.assertEqual(self.store.get_section(section["id"])["status"], "generated")
        review = self.pipeline.review_section(self.project_id, section["id"], draft["version_id"])
        rewrite = self.pipeline.rewrite_section(
            self.project_id,
            section["id"],
            draft["version_id"],
            review["version_id"],
            "压缩",
            [],
        )
        self.assertEqual(rewrite["content"], "改写正文")

    def test_write_section_draft_streaming_saves_draft_and_reports_chunks(self) -> None:
        pipeline = NovelPipeline(self.store, StreamingFakeLLM())
        chapter_id = self.store.save_chapter(self.project_id, {"number": 1, "title": "第一章"})
        section_id = self.store.save_section(chapter_id, {"number": 1, "title": "第一节", "status": "planned"})
        chunks = []

        result = pipeline.write_section_draft_streaming(self.project_id, section_id, "rough", chunks.append)

        self.assertEqual(chunks, ["流式", "正文"])
        self.assertEqual(result["content"], "流式正文")
        self.assertEqual(self.store.get_section(section_id)["status"], "generated")
        version = self.store.get_version(result["version_id"])
        self.assertEqual(version["content"], "流式正文")
        self.assertEqual(version["kind"], "draft")
        self.assertSystemRuleBeforeFirstUser(
            pipeline.llm.stream_messages,
            "这次只输出正文内容本身，不要输出 JSON、标题、说明或寒暄。",
        )

    def test_expand_global_concept_streaming_saves_outline_metadata(self) -> None:
        llm = GlobalOutlineStreamingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)
        chunks = []

        result = pipeline.expand_global_concept_streaming(self.project_id, chunks.append)

        self.assertEqual(llm.stream_model, "strong-model")
        self.assertEqual("".join(chunks), "流式全书故事大纲")
        self.assertEqual(result["expanded_outline"], "流式全书故事大纲")
        version = self.store.get_version(result["version_id"])
        self.assertEqual(version["kind"], "global_outline")
        self.assertEqual(version["content"], "流式全书故事大纲")
        metadata = json.loads(version["metadata_json"])
        self.assertEqual(metadata["expanded_outline"], "流式全书故事大纲")
        self.assertEqual(metadata["source"], "streaming_text")
        self.assertNotIn("chapters", metadata)
        self.assertSystemRuleBeforeFirstUser(llm.stream_messages, "直接输出全书故事大纲正文")
        self.assertNotIn("严格输出 JSON object", llm.stream_messages[-1]["content"])
        self.assertIn("全书故事大纲 Agent", llm.stream_messages[0]["content"])

    def test_expand_global_concept_does_not_save_chapters(self) -> None:
        result = self.pipeline.expand_global_concept(self.project_id)

        self.assertEqual(result["expanded_outline"], "丰满后的全书框架")
        self.assertNotIn("chapters", result)
        version = self.store.get_version(result["version_id"])
        metadata = json.loads(version["metadata_json"])
        self.assertNotIn("chapters", metadata)

    def test_expand_global_concept_includes_database_main_character_cards(self) -> None:
        llm = InspectingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)
        self.store.save_world_item(
            self.project_id,
            {
                "kind": "character",
                "name": "林砚",
                "summary": "失忆的调查员",
                "details": {
                    "identity": "调查员",
                    "personality": "克制",
                    "motivation": "寻找父亲失踪真相",
                    "speech_style": "短句，少解释",
                    "role_flags": {"protagonist": True},
                    "modules": {"level_system": {"level": 3}},
                },
                "tags": "主角",
            },
        )
        self.store.save_world_item(
            self.project_id,
            {
                "kind": "character",
                "name": "路人",
                "summary": "背景人物",
                "details": {},
                "tags": "",
            },
        )

        pipeline.expand_global_concept(self.project_id)

        user_content = llm.calls[0]["messages"][-1]["content"]
        payload = json.loads(user_content.split("\n", 1)[1])
        self.assertEqual([card["name"] for card in payload["main_character_cards"]], ["林砚"])
        card = payload["main_character_cards"][0]
        self.assertEqual(card["role"], "主角")
        self.assertEqual(card["identity"], "调查员")
        self.assertEqual(card["motivation"], "寻找父亲失踪真相")
        self.assertEqual(card["modules"]["level_system"]["level"], 3)

    def test_expand_global_concept_includes_all_world_items_when_database_exists(self) -> None:
        llm = InspectingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)
        self.store.save_world_item(
            self.project_id,
            {
                "kind": "character",
                "name": "林砚",
                "summary": "失忆的调查员",
                "details": {"identity": "调查员", "role_flags": {"protagonist": True}},
                "tags": "主角",
            },
        )
        self.store.save_world_item(
            self.project_id,
            {
                "kind": "location",
                "name": "旧宅",
                "summary": "雨夜中的核心地点",
                "details": {"atmosphere": "潮湿压抑"},
                "tags": "主舞台",
            },
        )
        self.store.save_world_item(
            self.project_id,
            {
                "kind": "forbidden",
                "name": "不能提前揭示真相",
                "summary": "父亲失踪真相不能在大纲开头揭露",
                "details": {"reason": "保持悬疑"},
                "tags": "禁止事项",
            },
        )

        pipeline.expand_global_concept(self.project_id)

        user_content = llm.calls[0]["messages"][-1]["content"]
        payload = json.loads(user_content.split("\n", 1)[1])
        context = payload["outline_world_context"]
        self.assertEqual(context["character"][0]["name"], "林砚")
        self.assertEqual(context["location"][0]["name"], "旧宅")
        self.assertEqual(context["location"][0]["details"]["atmosphere"], "潮湿压抑")
        self.assertEqual(context["forbidden"][0]["name"], "不能提前揭示真相")
        self.assertEqual(payload["main_character_cards"][0]["name"], "林砚")

    def test_generate_default_main_character_saves_character_card(self) -> None:
        llm = InspectingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)

        result = pipeline.generate_default_main_character(self.project_id)

        self.assertEqual(result["world_item"]["kind"], "character")
        self.assertEqual(result["world_item"]["name"], "林砚")
        self.assertIn("AI生成", result["world_item"]["tags"])
        details = json.loads(result["world_item"]["details_json"])
        self.assertEqual(details["identity"], "调查员")
        self.assertTrue(details["role_flags"]["protagonist"])
        self.assertEqual(details["modules"]["growth"]["start"], "不信任他人")
        self.assertEqual(llm.calls[0]["agent_name"], "main_character_generator")

    def test_confirm_outline_split_calls_splitter_for_expanded_outline(self) -> None:
        llm = InspectingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)
        outline = pipeline.expand_global_concept(self.project_id)

        split = pipeline.confirm_outline_split(self.project_id, outline["version_id"])

        self.assertEqual(split, {"chapters": 1, "sections": 1, "world_items": 5})
        self.assertEqual([call["agent_name"] for call in llm.calls], ["global_architect", "outline_splitter"])
        split_versions = self.store.list_versions(self.project_id, kind="outline_split")
        self.assertEqual(len(split_versions), 1)
        split_metadata = json.loads(split_versions[0]["metadata_json"])
        self.assertEqual(split_metadata["chapters"][0]["title"], "旧宅")

    def test_confirm_outline_split_payload_includes_world_context(self) -> None:
        llm = InspectingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)
        self.store.save_world_item(
            self.project_id,
            {
                "kind": "location",
                "name": "旧宅",
                "summary": "雨夜中的核心地点",
                "details": {"atmosphere": "潮湿压抑"},
                "tags": "主舞台",
                "status": "active",
            },
        )
        version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "待拆分大纲",
                "content": "林砚进入旧宅。",
                "metadata": {"expanded_outline": "林砚进入旧宅。"},
            }
        )

        pipeline.confirm_outline_split(self.project_id, version_id)

        user_content = llm.calls[0]["messages"][-1]["content"]
        payload = json.loads(user_content.split("\n", 1)[1])
        self.assertEqual(payload["outline_world_context"]["location"][0]["name"], "旧宅")
        self.assertEqual(payload["outline_world_context"]["location"][0]["details"]["atmosphere"], "潮湿压抑")

    def test_confirm_outline_split_keeps_legacy_metadata_without_splitter_call(self) -> None:
        pipeline = NovelPipeline(self.store, LegacySplitFakeLLM())
        version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "旧版总体框架",
                "content": "{}",
                "metadata": {
                    "chapters": [
                        {
                            "number": 1,
                            "title": "旧版章节",
                            "sections": [{"number": 1, "title": "旧版小节"}],
                        }
                    ]
                },
            }
        )

        split = pipeline.confirm_outline_split(self.project_id, version_id)

        self.assertEqual(split["chapters"], 1)
        self.assertEqual(self.store.list_chapters(self.project_id)[0]["title"], "旧版章节")
        self.assertEqual(self.store.list_versions(self.project_id, kind="outline_split"), [])

    def test_confirm_outline_split_streaming_saves_after_complete_json(self) -> None:
        llm = OutlineSplitStreamingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)
        outline = pipeline.expand_global_concept(self.project_id)
        chunks = []

        split = pipeline.confirm_outline_split_streaming(self.project_id, outline["version_id"], chunks.append)

        self.assertEqual(split, {"chapters": 1, "sections": 1, "world_items": 3})
        self.assertEqual(llm.stream_model, "split-model")
        self.assertEqual("".join(chunks), '{"expanded_outline":"丰满后的全书框架","chapters":[{"number":1,"title":"流式旧宅","location":"旧宅","characters":["林砚"],"sections":[{"number":1,"title":"流式走廊","location":"走廊","characters":["林砚"]}]}]}')
        chapters = self.store.list_chapters(self.project_id)
        self.assertEqual(chapters[0]["title"], "流式旧宅")
        self.assertEqual(self.store.list_sections(chapters[0]["id"])[0]["title"], "流式走廊")
        split_versions = self.store.list_versions(self.project_id, kind="outline_split")
        self.assertEqual(len(split_versions), 1)
        self.assertEqual(json.loads(split_versions[0]["metadata_json"])["chapters"][0]["title"], "流式旧宅")
        self.assertSystemRuleBeforeFirstUser(llm.stream_messages, "输出必须是 JSON object")

    def test_confirm_outline_split_streaming_invalid_json_does_not_persist_split(self) -> None:
        llm = InvalidOutlineSplitStreamingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)
        outline = pipeline.expand_global_concept(self.project_id)
        chunks = []

        with self.assertRaises(Exception):
            pipeline.confirm_outline_split_streaming(self.project_id, outline["version_id"], chunks.append)

        self.assertEqual("".join(chunks), '{"chapters":[{"number":1')
        self.assertEqual(self.store.list_chapters(self.project_id), [])
        self.assertEqual(self.store.list_world_items(self.project_id), [])
        self.assertEqual(self.store.list_versions(self.project_id, kind="outline_split"), [])
        log = self.store.list_llm_call_logs(limit=1)[0]
        self.assertEqual(log["agent_name"], "outline_splitter")
        self.assertEqual(log["success"], 0)
        self.assertIn('{"chapters":[{"number":1', log["response_summary"])

    def test_confirm_outline_split_streaming_keeps_legacy_metadata_without_streaming_call(self) -> None:
        pipeline = NovelPipeline(self.store, LegacyStreamingSplitFakeLLM())
        version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "旧版总体框架",
                "content": "{}",
                "metadata": {
                    "chapters": [
                        {
                            "number": 1,
                            "title": "旧版流式章节",
                            "sections": [{"number": 1, "title": "旧版流式小节"}],
                        }
                    ]
                },
            }
        )

        split = pipeline.confirm_outline_split_streaming(self.project_id, version_id, lambda delta: None)

        self.assertEqual(split["chapters"], 1)
        self.assertEqual(self.store.list_chapters(self.project_id)[0]["title"], "旧版流式章节")
        self.assertEqual(self.store.list_versions(self.project_id, kind="outline_split"), [])

    def test_project_writing_constraints_are_injected_into_prompts(self) -> None:
        self.store.update_project(
            self.project_id,
            {
                "style": "克制悬疑",
                "target_readers": "成人读者",
                "pov": "第三人称限知",
                "writing_style_guide": "短句，少解释，多动作。",
            },
        )
        llm = InspectingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)

        pipeline.expand_global_concept(self.project_id)

        system_messages = [
            message["content"]
            for message in llm.calls[-1]["messages"]
            if message["role"] == "system"
        ]
        self.assertTrue(any("项目级写作约束" in message for message in system_messages))
        self.assertTrue(any("短句，少解释，多动作。" in message for message in system_messages))
        user_message = llm.calls[-1]["messages"][-1]["content"]
        self.assertIn("project_writing_constraints", user_message)

    def test_context_retrieval_trace_is_written_to_llm_call_log(self) -> None:
        self.store.update_project(self.project_id, {"writing_style_guide": "冷峻，少形容。"})
        chapter_id = self.store.save_chapter(self.project_id, {"number": 1, "title": "第一章"})
        section_id = self.store.save_section(
            chapter_id,
            {"number": 1, "title": "第一节", "goal": "调查旧宅", "status": "planned"},
        )
        self.store.save_world_item(
            self.project_id,
            {"kind": "location", "name": "旧宅资料", "summary": "调查旧宅时必须调用", "tags": "旧宅"},
        )
        self.store.save_world_item(
            self.project_id,
            {"kind": "forbidden", "name": "提前揭示真相", "summary": "不能提前揭示父亲失踪真相"},
        )

        self.pipeline.write_section_draft(self.project_id, section_id)

        log = self.store.list_llm_call_logs(limit=1)[0]
        self.assertIn("retrieval_trace", log["request_summary"])
        self.assertIn("旧宅资料", log["request_summary"])
        self.assertIn("提前揭示真相", log["request_summary"])

    def test_parse_length_target_words(self) -> None:
        cases = {
            "80000": 80000,
            "80000字": 80000,
            "8万字": 80000,
            "约10万": 100000,
            "10w": 100000,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_length_target(raw), expected)

    def test_confirm_outline_split_allocates_missing_section_targets(self) -> None:
        self.store.update_project(self.project_id, {"length_target": "8万字"})
        version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "缺失小节字数",
                "content": "{}",
                "metadata": {
                    "chapters": [
                        {
                            "number": 1,
                            "title": "第一章",
                            "sections": [
                                {"number": 1, "title": "一"},
                                {"number": 2, "title": "二"},
                            ],
                        },
                        {
                            "number": 2,
                            "title": "第二章",
                            "sections": [
                                {"number": 1, "title": "三"},
                                {"number": 2, "title": "四"},
                            ],
                        },
                    ]
                },
            }
        )

        self.pipeline.confirm_outline_split(self.project_id, version_id)

        sections = [
            section
            for chapter in self.store.list_chapters(self.project_id)
            for section in self.store.list_sections(chapter["id"])
        ]
        self.assertEqual([section["target_words"] for section in sections], [20000, 20000, 20000, 20000])
        self.assertEqual(sum(section["target_words"] for section in sections), 80000)

    def test_confirm_outline_split_normalizes_deviating_section_targets(self) -> None:
        self.store.update_project(self.project_id, {"length_target": "10w"})
        version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "偏离小节字数",
                "content": "{}",
                "metadata": {
                    "chapters": [
                        {
                            "number": 1,
                            "title": "第一章",
                            "sections": [
                                {"number": 1, "title": "轻", "target_words": 1000},
                                {"number": 2, "title": "重", "target_words": 3000},
                            ],
                        }
                    ]
                },
            }
        )

        self.pipeline.confirm_outline_split(self.project_id, version_id)

        chapter = self.store.list_chapters(self.project_id)[0]
        targets = [section["target_words"] for section in self.store.list_sections(chapter["id"])]
        self.assertEqual(sum(targets), 100000)
        self.assertLess(targets[0], targets[1])
        self.assertGreaterEqual(min(targets), 100)

    def test_continue_next_requires_finalized(self) -> None:
        outline = self.pipeline.expand_global_concept(self.project_id)
        self.pipeline.confirm_outline_split(self.project_id, outline["version_id"])
        chapter = self.store.list_chapters(self.project_id)[0]
        section = self.store.list_sections(chapter["id"])[0]
        with self.assertRaises(ValueError):
            self.pipeline.continue_next_section(section["id"])

    def test_confirm_outline_split_creates_world_item_candidates(self) -> None:
        metadata = {
            "expanded_outline": "结构化总体框架",
            "characters": [{"name": "林砚", "summary": "旧案调查者"}],
            "locations": ["旧宅"],
            "timeline": [{"event": "十年前旧案", "summary": "旧宅发生失踪案"}],
            "forbidden": [{"name": "提前揭示真相", "summary": "不要提前揭示父亲失踪真相"}],
            "chapters": [
                {
                    "number": 1,
                    "title": "旧宅",
                    "story_time": "雨夜",
                    "location": "旧宅",
                    "characters": ["林砚", "林砚"],
                    "goal": "发现入口",
                    "outline": "进入旧宅",
                    "sections": [
                        {
                            "number": 1,
                            "title": "走廊",
                            "story_time": "十点",
                            "location": "旧宅",
                            "characters": ["林砚"],
                            "goal": "发现拖痕",
                            "scene": "走廊",
                        }
                    ],
                }
            ],
        }
        version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "测试总体框架",
                "content": json.dumps(metadata, ensure_ascii=False),
                "metadata": metadata,
            }
        )

        split = self.pipeline.confirm_outline_split(self.project_id, version_id)

        self.assertEqual(split, {"chapters": 1, "sections": 1, "world_items": 6})
        items = self.store.list_world_items(self.project_id)
        names_by_kind = {}
        for item in items:
            names_by_kind.setdefault(item["kind"], []).append(item["name"])
        self.assertEqual(names_by_kind["character"], ["林砚"])
        self.assertEqual(names_by_kind["location"], ["旧宅"])
        self.assertIn("十年前旧案", names_by_kind["timeline_event"])
        self.assertEqual(names_by_kind["forbidden"], ["提前揭示真相"])

    def test_confirm_outline_split_replaces_previous_chapters_and_auto_candidates(self) -> None:
        self.store.save_world_item(
            self.project_id,
            {
                "kind": "character",
                "name": "手动角色",
                "summary": "用户手动维护的资料",
                "details": {"source": "manual"},
                "status": "active",
            },
        )
        first_version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "第一次总体框架",
                "content": "{}",
                "metadata": {
                    "chapters": [
                        {
                            "number": 1,
                            "title": "旧章节",
                            "location": "旧地点",
                            "characters": ["旧角色"],
                            "sections": [{"number": 1, "title": "旧小节"}],
                        }
                    ]
                },
            }
        )
        second_version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "第二次总体框架",
                "content": "{}",
                "metadata": {
                    "chapters": [
                        {
                            "number": 1,
                            "title": "新章节",
                            "location": "新地点",
                            "characters": ["新角色"],
                            "sections": [{"number": 1, "title": "新小节"}],
                        }
                    ]
                },
            }
        )

        self.pipeline.confirm_outline_split(self.project_id, first_version_id)
        self.pipeline.confirm_outline_split(self.project_id, second_version_id)

        chapters = self.store.list_chapters(self.project_id)
        self.assertEqual([chapter["title"] for chapter in chapters], ["新章节"])
        self.assertEqual(
            [section["title"] for section in self.store.list_sections(chapters[0]["id"])],
            ["新小节"],
        )
        items = self.store.list_world_items(self.project_id)
        names = {item["name"] for item in items}
        self.assertNotIn("旧角色", names)
        self.assertNotIn("旧地点", names)
        self.assertIn("新角色", names)
        self.assertIn("新地点", names)
        self.assertIn("手动角色", names)

    def test_confirm_outline_split_skips_existing_world_item_alias_candidates(self) -> None:
        self.store.save_world_item(
            self.project_id,
            {
                "kind": "character",
                "name": "林砚",
                "summary": "用户已有角色卡",
                "details": {"source": "manual"},
                "status": "active",
            },
        )
        version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "重复资料测试",
                "content": "{}",
                "metadata": {
                    "world_items": [
                        {"kind": "character", "name": "主角林砚（少年）", "summary": "重复候选"}
                    ],
                    "chapters": [],
                },
            }
        )

        split = self.pipeline.confirm_outline_split(self.project_id, version_id)

        self.assertEqual(split["world_items"], 0)
        items = self.store.list_world_items(self.project_id, "character")
        self.assertEqual([item["name"] for item in items], ["林砚"])
        self.assertEqual(items[0]["summary"], "用户已有角色卡")

    def test_serial_next_outline_split_appends_after_existing_chapters(self) -> None:
        existing_chapter_id = self.store.save_chapter(
            self.project_id,
            {"number": 1, "title": "已有章节", "status": "planned"},
        )
        self.store.save_section(existing_chapter_id, {"number": 1, "title": "已有小节", "target_words": 900})
        version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "下一部分连载大纲",
                "content": "{}",
                "metadata": {
                    "outline_planning": {
                        "outline_mode": "serial",
                        "serial_action": "next_part",
                        "planning_target_words": "6000",
                        "planning_section_count": "3",
                        "default_section_target_words": "2000",
                    },
                    "chapters": [
                        {
                            "number": 1,
                            "title": "新增章节一",
                            "sections": [{"number": 1, "title": "新增一节"}],
                        },
                        {
                            "number": 2,
                            "title": "新增章节二",
                            "sections": [
                                {"number": 1, "title": "新增二节"},
                                {"number": 2, "title": "新增三节"},
                            ],
                        },
                    ],
                },
            }
        )

        self.pipeline.confirm_outline_split(self.project_id, version_id)

        chapters = self.store.list_chapters(self.project_id)
        self.assertEqual([chapter["number"] for chapter in chapters], [1, 2, 3])
        self.assertEqual([chapter["title"] for chapter in chapters], ["已有章节", "新增章节一", "新增章节二"])
        all_sections = [
            section
            for chapter in chapters
            for section in self.store.list_sections(chapter["id"])
        ]
        self.assertEqual([section["title"] for section in all_sections], ["已有小节", "新增一节", "新增二节", "新增三节"])
        self.assertEqual(sum(section["target_words"] for section in all_sections if section["title"].startswith("新增")), 6000)

    def test_enrich_world_item_returns_editable_draft_without_saving(self) -> None:
        item_id = self.store.save_world_item(
            self.project_id,
            {
                "kind": "character",
                "name": "林砚",
                "summary": "原始摘要",
                "details": {"identity": "调查者"},
                "tags": "主角",
                "status": "candidate",
            },
        )

        result = self.pipeline.enrich_world_item(self.project_id, item_id)

        self.assertEqual(result["world_item_id"], item_id)
        draft = result["world_item"]
        self.assertEqual(draft["name"], "林砚改名")
        self.assertEqual(draft["summary"], "补全后的角色摘要")
        self.assertEqual(draft["status"], "active")
        self.assertEqual(draft["tags"], "主角,AI补全")
        self.assertEqual(draft["details"]["identity"], "调查者")
        self.assertEqual(draft["details"]["motivation"], "寻找真相")
        self.assertEqual(draft["details"]["source"], "ai_enriched")
        item = self.store.get_world_item(self.project_id, item_id)
        self.assertEqual(item["summary"], "原始摘要")
        self.assertEqual(item["status"], "candidate")
        self.assertEqual(item["tags"], "主角")
        details = json.loads(item["details_json"])
        self.assertEqual(details["identity"], "调查者")
        self.assertNotIn("motivation", details)

    def test_enrich_world_item_passes_user_direction(self) -> None:
        llm = InspectingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)
        item_id = self.store.save_world_item(
            self.project_id,
            {
                "kind": "character",
                "name": "林砚",
                "summary": "原始摘要",
                "details": {"identity": "调查者"},
                "tags": "主角",
            },
        )

        pipeline.enrich_world_item(self.project_id, item_id, "强化说话风格")

        user_content = llm.calls[0]["messages"][-1]["content"]
        payload = json.loads(user_content.split("\n", 1)[1])
        self.assertEqual(payload["enrich_direction"], "强化说话风格")

    def test_generate_world_item_uses_selected_kind_and_latest_outline(self) -> None:
        llm = InspectingFakeLLM()
        pipeline = NovelPipeline(self.store, llm)
        self.store.save_version(
            {
                "project_id": self.project_id,
                "kind": "global_outline",
                "label": "全书故事大纲",
                "content": "旧宅故事从雨夜开始。",
                "metadata": {"expanded_outline": "旧宅故事从雨夜开始。"},
            }
        )

        result = pipeline.generate_world_item(self.project_id, "location")

        self.assertEqual(result["world_item"]["kind"], "location")
        self.assertEqual(result["world_item"]["name"], "钟楼广场")
        details = json.loads(result["world_item"]["details_json"])
        self.assertEqual(details["atmosphere"], "明亮但暗藏监视")
        user_content = llm.calls[0]["messages"][-1]["content"]
        payload = json.loads(user_content.split("\n", 1)[1])
        self.assertEqual(payload["current_kind"], "location")
        self.assertEqual(payload["current_outline"]["content"], "旧宅故事从雨夜开始。")

    def test_write_chapter_memory_upserts_candidates_from_finalized_sections(self) -> None:
        chapter_id = self.store.save_chapter(self.project_id, {"number": 1, "title": "旧宅入口"})
        section_id = self.store.save_section(chapter_id, {"number": 1, "title": "走廊"})
        version_id = self.store.save_version(
            {
                "project_id": self.project_id,
                "chapter_id": chapter_id,
                "section_id": section_id,
                "kind": "draft",
                "label": "定稿",
                "content": "林砚在旧宅雨夜发现拖痕。",
            }
        )
        self.store.finalize_section(section_id, version_id)

        result = self.pipeline.write_chapter_memory(self.project_id, chapter_id)

        self.assertEqual(result["world_items"], 1)
        items = self.store.list_world_items(self.project_id, "timeline_event")
        self.assertEqual(items[0]["name"], "旧宅雨夜发现拖痕")
        self.assertIn("章末记忆", items[0]["tags"])
        details = json.loads(items[0]["details_json"])
        self.assertEqual(details["source"], "chapter_memory")
        self.assertEqual(details["chapter_memory"][0]["payoff_plan"], "下一章追查")

    def test_write_chapter_memory_requires_finalized_sections(self) -> None:
        chapter_id = self.store.save_chapter(self.project_id, {"number": 1, "title": "空章"})

        with self.assertRaisesRegex(ValueError, "已定稿小节"):
            self.pipeline.write_chapter_memory(self.project_id, chapter_id)


if __name__ == "__main__":
    unittest.main()
