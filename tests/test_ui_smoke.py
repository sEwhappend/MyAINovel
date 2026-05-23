import json
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_ai_novel.ui import NovelDesktopUI
from my_ai_novel.ui_logic import (
    PROJECT_TEXT_FIELDS,
    build_llm_config_from_vars,
    build_world_context_query,
    calculate_default_section_target_words,
    format_export_success_message,
    format_character_card_choice,
    format_model_discovery_result,
    format_location_choice,
    format_world_context_pack,
    llm_config_field_keys,
    latest_outline_index,
    model_scan_autofill,
    parse_lines,
    parse_model_candidates,
    project_index_by_id,
    selected_character_card_names,
    selected_location_name,
    world_kind_label,
    world_kind_value,
)
from my_ai_novel.models import DEFAULT_LLM_CONFIG
from my_ai_novel.pyside_ui import build_pyside_stylesheet
from my_ai_novel.ui_theme import (
    BUTTON_HOVER,
    BUTTON_PRESSED,
    PRIMARY,
    apply_ttk_theme,
    create_navigation_button,
    load_customtkinter,
    set_navigation_button_selected,
)


def destroy_ctk_root(root) -> None:
    try:
        for callback_id in root.tk.call("after", "info"):
            try:
                root.after_cancel(callback_id)
            except Exception:
                pass
    finally:
        root.destroy()


class FakeVar:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class FakeText:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self, _start: str, _end: str) -> str:
        return self.value

    def delete(self, _start: object, _end: object) -> None:
        self.value = ""

    def insert(self, start: object, value: str) -> None:
        if str(start).lower() == "end":
            self.value += value
        else:
            self.value = value


class UiThemeTests(unittest.TestCase):
    def test_customtkinter_dependency_message_is_actionable(self) -> None:
        try:
            load_customtkinter()
        except RuntimeError as exc:
            self.assertIn("python -m pip install -r requirements.txt", str(exc))

    def test_theme_uses_button_like_selected_tabs(self) -> None:
        try:
            ctk = load_customtkinter()
        except RuntimeError:
            self.skipTest("customtkinter is not installed")
        root = ctk.CTk()
        try:
            apply_ttk_theme(root)
            from tkinter import ttk

            style = ttk.Style(root)
            tab_backgrounds = dict(style.map("TNotebook.Tab", query_opt="background"))
            button_backgrounds = dict(style.map("TButton", query_opt="background"))
            self.assertEqual(tab_backgrounds.get("selected"), PRIMARY)
            self.assertEqual(button_backgrounds.get("active"), BUTTON_HOVER)
            self.assertEqual(button_backgrounds.get("pressed"), BUTTON_PRESSED)
        finally:
            destroy_ctk_root(root)

    def test_navigation_button_selected_state_uses_winui_like_highlight(self) -> None:
        try:
            ctk = load_customtkinter()
        except RuntimeError:
            self.skipTest("customtkinter is not installed")
        root = ctk.CTk()
        try:
            button = create_navigation_button(root, "项目", lambda: None)
            set_navigation_button_selected(button, True)
            self.assertEqual(button.cget("fg_color"), PRIMARY)
            self.assertEqual(button.cget("text_color"), "#ffffff")
            set_navigation_button_selected(button, False)
            self.assertEqual(button.cget("fg_color"), "transparent")
        finally:
            destroy_ctk_root(root)


class FakeRoot:
    def after(self, _delay: int, callback) -> None:
        callback()


class FakeEntry:
    def __init__(self, value: str) -> None:
        self.var = FakeVar(value)


class FakeListbox:
    def __init__(self) -> None:
        self.selected: int | None = None
        self.active: int | None = None
        self.visible: int | None = None
        self.deleted = False
        self.items: list[str] = []

    def selection_clear(self, _start: int, _end: object) -> None:
        self.selected = None

    def selection_set(self, index: int) -> None:
        self.selected = index

    def curselection(self) -> tuple[int, ...]:
        return () if self.selected is None else (self.selected,)

    def activate(self, index: int) -> None:
        self.active = index

    def see(self, index: int) -> None:
        self.visible = index

    def delete(self, _start: object, _end: object) -> None:
        self.deleted = True
        self.items = []

    def insert(self, _index: object, value: str) -> None:
        self.items.append(value)


class FakeStreamingPipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def expand_global_concept_streaming(self, project_id: int, on_delta, planning_options=None) -> dict[str, object]:
        self.calls.append(("stream_outline", project_id, planning_options))
        on_delta("第一段")
        on_delta("第二段")
        return {"version_id": 101, "expanded_outline": "第一段第二段"}

    def write_section_draft_streaming(self, project_id: int, section_id: int, mode: str, on_delta) -> dict[str, object]:
        self.calls.append(("stream_draft", project_id, section_id, mode))
        on_delta("第一段")
        on_delta("第二段")
        return {"version_id": 201, "content": "第一段第二段"}

    def confirm_outline_split_streaming(self, project_id: int, version_id: int, on_delta) -> dict[str, object]:
        self.calls.append(("stream_split", project_id, version_id))
        on_delta('{"chapters":')
        on_delta("[]}")
        return {"chapters": 1, "sections": 2, "world_items": 3}


class FakeStore:
    def __init__(self) -> None:
        self.saved_project_id: int | None = None
        self.saved_data: dict[str, str] | None = None
        self.deleted_project_id: int | None = None
        self.deleted_item_id: int | None = None
        self.deleted_chapter: tuple[int, int] | None = None
        self.deleted_section_id: int | None = None
        self.moved_chapter: tuple[int, int, int] | None = None
        self.moved_section: tuple[int, int, int] | None = None
        self.finalized_section: tuple[int, int] | None = None
        self.listed_world_kind: str | None = None
        self.projects: dict[int, dict[str, object]] = {}
        self.chapters: list[dict[str, object]] = []
        self.sections: dict[int, list[dict[str, object]]] = {}
        self.versions: list[dict[str, object]] = []
        self.world_items: dict[str, list[dict[str, str]]] = {
            "character": [],
            "location": [],
        }
        self.rebuild_count = 0
        self.next_version_id = 1000

    def rebuild_cache_from_project_files(self) -> None:
        self.rebuild_count += 1

    def save_world_item(self, project_id: int, data: dict[str, str]) -> None:
        self.saved_project_id = project_id
        self.saved_data = data

    def create_project(self, data: dict[str, str]) -> int:
        self.saved_project_id = 77
        self.saved_data = data
        self.projects[77] = {"id": 77, **data}
        return 77

    def update_project(self, project_id: int, data: dict[str, str]) -> None:
        self.saved_project_id = project_id
        self.saved_data = data
        self.projects[project_id] = {"id": project_id, **data}

    def list_projects(self) -> list[dict[str, object]]:
        return list(self.projects.values())

    def delete_world_item(self, project_id: int, item_id: int) -> None:
        self.deleted_project_id = project_id
        self.deleted_item_id = item_id

    def list_world_items(self, _project_id: int, kind: str | None = None) -> list[dict[str, str]]:
        self.listed_world_kind = kind
        if kind is None:
            return [item for rows in self.world_items.values() for item in rows]
        return self.world_items.get(kind, [])

    def list_chapters(self, _project_id: int) -> list[dict[str, object]]:
        return self.chapters

    def get_project(self, project_id: int) -> dict[str, object] | None:
        return self.projects.get(project_id)

    def get_chapter(self, chapter_id: int) -> dict[str, object] | None:
        return next((chapter for chapter in self.chapters if chapter["id"] == chapter_id), None)

    def list_sections(self, chapter_id: int) -> list[dict[str, object]]:
        return self.sections.get(chapter_id, [])

    def get_section(self, section_id: int) -> dict[str, object] | None:
        for sections in self.sections.values():
            for section in sections:
                if section["id"] == section_id:
                    return section
        return None

    def list_versions(
        self,
        _project_id: int,
        section_id: int | None = None,
        chapter_id: int | None = None,
        kind: str | None = None,
    ) -> list[dict[str, object]]:
        rows = self.versions
        if section_id is not None:
            rows = [row for row in rows if row.get("section_id") == section_id]
        if chapter_id is not None:
            rows = [row for row in rows if row.get("chapter_id") == chapter_id]
        if kind is not None:
            rows = [row for row in rows if row.get("kind") == kind]
        return rows

    def get_version(self, version_id: int) -> dict[str, object] | None:
        return next((row for row in self.versions if row.get("id") == version_id), None)

    def save_version(self, data: dict[str, object]) -> int:
        version_id = self.next_version_id
        self.next_version_id += 1
        metadata = data.get("metadata_json", data.get("metadata", {}))
        row = {
            "id": version_id,
            "project_id": data.get("project_id"),
            "chapter_id": data.get("chapter_id"),
            "section_id": data.get("section_id"),
            "kind": data.get("kind", "draft"),
            "label": data.get("label", ""),
            "content": data.get("content", ""),
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
            "status": data.get("status", "usable"),
            "created_at": "now",
        }
        self.versions.insert(0, row)
        return version_id

    def move_chapter(self, project_id: int, chapter_id: int, direction: int) -> None:
        self.moved_chapter = (project_id, chapter_id, direction)
        index = next(index for index, chapter in enumerate(self.chapters) if chapter["id"] == chapter_id)
        target = index + direction
        if target < 0:
            raise ValueError("已经是第一章")
        if target >= len(self.chapters):
            raise ValueError("已经是最后一章")
        self.chapters[index], self.chapters[target] = self.chapters[target], self.chapters[index]
        for number, chapter in enumerate(self.chapters, 1):
            chapter["number"] = number

    def delete_chapter(self, project_id: int, chapter_id: int) -> None:
        self.deleted_chapter = (project_id, chapter_id)
        self.chapters = [chapter for chapter in self.chapters if chapter["id"] != chapter_id]
        self.sections.pop(chapter_id, None)
        self.versions = [version for version in self.versions if version.get("chapter_id") != chapter_id]
        for number, chapter in enumerate(self.chapters, 1):
            chapter["number"] = number

    def move_section(self, chapter_id: int, section_id: int, direction: int) -> None:
        self.moved_section = (chapter_id, section_id, direction)
        rows = self.sections[chapter_id]
        index = next(index for index, section in enumerate(rows) if section["id"] == section_id)
        target = index + direction
        if target < 0:
            raise ValueError("已经是第一节")
        if target >= len(rows):
            raise ValueError("已经是最后一节")
        rows[index], rows[target] = rows[target], rows[index]
        for number, section in enumerate(rows, 1):
            section["number"] = number

    def delete_section(self, section_id: int) -> None:
        self.deleted_section_id = section_id
        for chapter_id, rows in self.sections.items():
            self.sections[chapter_id] = [section for section in rows if section["id"] != section_id]
            for number, section in enumerate(self.sections[chapter_id], 1):
                section["number"] = number
        self.versions = [version for version in self.versions if version.get("section_id") != section_id]

    def finalize_section(self, section_id: int, version_id: int) -> None:
        self.finalized_section = (section_id, version_id)
        section = self.get_section(section_id)
        if section is not None:
            section["status"] = "finalized"
            section["finalized_version_id"] = version_id


class FakePipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.next_section: dict[str, object] | None = None
        self.next_sections: list[dict[str, object] | None] | None = None

    def confirm_outline_split(self, project_id: int, version_id: int) -> dict[str, object]:
        self.calls.append(("confirm_outline_split", project_id, version_id))
        return {"chapters": 1, "sections": 2, "world_items": 3}

    def write_section_draft(self, project_id: int, section_id: int, mode: str = "rough") -> dict[str, object]:
        self.calls.append(("draft", project_id, section_id, mode))
        return {"version_id": 101, "content": "粗稿"}

    def review_section(self, project_id: int, section_id: int, version_id: int) -> dict[str, object]:
        self.calls.append(("review", project_id, section_id, version_id))
        return {"version_id": 102, "issues": []}

    def rewrite_section(
        self,
        project_id: int,
        section_id: int,
        version_id: int,
        review_id: int,
        rewrite_mode: str,
        preserve: list[str],
    ) -> dict[str, object]:
        self.calls.append(("rewrite", project_id, section_id, version_id, review_id, rewrite_mode, preserve))
        return {"version_id": 103, "content": "改写"}

    def continue_next_section(self, section_id: int) -> dict[str, object]:
        self.calls.append(("continue", section_id))
        if self.next_sections is not None:
            next_section = self.next_sections.pop(0) if self.next_sections else None
            if next_section is None:
                raise ValueError("当前章节没有下一节")
            return next_section
        if self.next_section is None:
            raise ValueError("当前章节没有下一节")
        return self.next_section


class FakeLLM:
    def __init__(self) -> None:
        self.retry_configs = []

    def configure_retry_until_cancel(self, cancel_event=None, callback=None, delays=None) -> None:
        self.retry_configs.append((cancel_event, callback, delays))


class FakeServices:
    def __init__(self) -> None:
        self.llm = FakeLLM()


class UISmokeTests(unittest.TestCase):
    def test_parse_lines(self) -> None:
        self.assertEqual(parse_lines("林砚\n\n周棠 "), ["林砚", "周棠"])

    def test_project_text_fields_do_not_include_character_brief(self) -> None:
        keys = [key for _label, key in PROJECT_TEXT_FIELDS]
        labels = [label for label, _key in PROJECT_TEXT_FIELDS]
        self.assertNotIn("character_brief", keys)
        self.assertNotIn("角色卡", labels)

    def test_world_kind_label_uses_chinese_display_name(self) -> None:
        self.assertEqual(world_kind_label("character"), "角色卡")
        self.assertEqual(world_kind_label("timeline_event"), "时间线")
        self.assertEqual(world_kind_label("unknown_kind"), "unknown_kind")

    def test_world_kind_value_preserves_internal_enum(self) -> None:
        self.assertEqual(world_kind_value("角色卡"), "character")
        self.assertEqual(world_kind_value("人物设定"), "character")
        self.assertEqual(world_kind_value("伏笔"), "foreshadowing")
        self.assertEqual(world_kind_value("character"), "character")

    def test_save_world_item_converts_chinese_label_to_internal_enum(self) -> None:
        store = FakeStore()
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_world_item_id = None
        ui.store = store
        ui.world_kind = FakeVar("角色卡")
        ui.world_name = FakeVar("林砚")
        ui.world_summary = FakeText("失忆的调查员")
        ui.world_tags = FakeVar("主角,调查")
        ui.refresh_world_items = lambda: None
        ui.refresh_character_cards = lambda: None
        ui.refresh_location_items = lambda: None
        ui._ok = lambda _message: None

        ui.save_world_item()

        self.assertEqual(store.saved_project_id, 42)
        self.assertIsNotNone(store.saved_data)
        self.assertEqual(store.saved_data["kind"], "character")
        self.assertEqual(store.saved_data["name"], "林砚")
        self.assertIsNone(store.saved_data["id"])

    def test_save_world_item_includes_current_item_id_for_updates(self) -> None:
        store = FakeStore()
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_world_item_id = 9
        ui.store = store
        ui.world_kind = FakeVar("角色卡")
        ui.world_name = FakeVar("林砚修改版")
        ui.world_summary = FakeText("新的摘要")
        ui.world_tags = FakeVar("主角")
        ui.refresh_world_items = lambda: None
        ui.refresh_character_cards = lambda: None
        ui.refresh_location_items = lambda: None
        ui._ok = lambda _message: None

        ui.save_world_item()

        self.assertEqual(store.saved_data["id"], 9)
        self.assertEqual(store.saved_data["name"], "林砚修改版")

    def test_save_world_item_refreshes_character_and_location_candidates(self) -> None:
        store = FakeStore()
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_world_item_id = None
        ui.store = store
        ui.world_kind = FakeVar("地点设定")
        ui.world_name = FakeVar("旧宅")
        ui.world_summary = FakeText("雨夜主舞台")
        ui.world_tags = FakeVar("主舞台")
        events = []
        ui.refresh_world_items = lambda: events.append("refresh_world_items")
        ui.refresh_character_cards = lambda: events.append("refresh_character_cards")
        ui.refresh_location_items = lambda: events.append("refresh_location_items")
        ui._ok = lambda message: events.append(f"ok:{message}")

        ui.save_world_item()

        self.assertEqual(store.saved_data["kind"], "location")
        self.assertEqual(
            events,
            ["refresh_world_items", "refresh_character_cards", "refresh_location_items", "ok:资料已保存"],
        )

    def test_select_world_item_fills_form_for_editing(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.world_rows = [
            {
                "id": 9,
                "kind": "character",
                "name": "林砚",
                "tags": "主角,调查",
                "summary": "失眠的调查员",
            }
        ]
        ui.world_list = FakeListbox()
        ui.world_list.selection_set(0)
        ui.current_world_item_id = None
        ui.world_kind = FakeVar("")
        ui.world_name = FakeVar("")
        ui.world_tags = FakeVar("")
        ui.world_summary = FakeText("")

        ui.select_world_item()

        self.assertEqual(ui.current_world_item_id, 9)
        self.assertEqual(ui.world_kind.get(), "角色卡")
        self.assertEqual(ui.world_name.get(), "林砚")
        self.assertEqual(ui.world_tags.get(), "主角,调查")
        self.assertEqual(ui.world_summary.get("1.0", "end"), "失眠的调查员")

    def test_delete_world_item_requires_selection(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_world_item_id = None
        messages = []
        ui._error = lambda message: messages.append(message)

        ui.delete_world_item()

        self.assertEqual(messages, ["请先选择资料"])

    def test_delete_world_item_deletes_selected_item_and_clears_form(self) -> None:
        store = FakeStore()
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_world_item_id = 9
        ui.store = store
        ui.world_kind = FakeVar("伏笔")
        ui.world_name = FakeVar("旧资料")
        ui.world_tags = FakeVar("旧标签")
        ui.world_summary = FakeText("旧摘要")
        events = []
        ui.refresh_world_items = lambda: events.append("refresh_world_items")
        ui.refresh_character_cards = lambda: events.append("refresh_character_cards")
        ui.refresh_location_items = lambda: events.append("refresh_location_items")
        ui._ok = lambda message: events.append(f"ok:{message}")

        ui.delete_world_item()

        self.assertEqual(store.deleted_project_id, 42)
        self.assertEqual(store.deleted_item_id, 9)
        self.assertIsNone(ui.current_world_item_id)
        self.assertEqual(ui.world_kind.get(), "伏笔")
        self.assertEqual(ui.world_name.get(), "")
        self.assertEqual(ui.world_tags.get(), "")
        self.assertEqual(ui.world_summary.get("1.0", "end"), "")
        self.assertEqual(
            events,
            ["refresh_world_items", "refresh_character_cards", "refresh_location_items", "ok:资料已删除"],
        )

    def test_character_card_choice_helpers_use_world_character_cards(self) -> None:
        rows = [
            {"name": "林砚", "tags": "主角"},
            {"name": "周棠", "tags": ""},
            {"name": "", "tags": "空"},
        ]

        self.assertEqual(format_character_card_choice(rows[0]), "林砚 | 主角")
        self.assertEqual(format_character_card_choice(rows[1]), "周棠")
        self.assertEqual(selected_character_card_names(rows, [0, 1, 2, 99]), ["林砚", "周棠"])

    def test_location_choice_helpers_use_world_location_items(self) -> None:
        rows = [
            {"name": "旧宅", "tags": "主舞台"},
            {"name": "码头", "tags": ""},
            {"name": "", "tags": "空"},
        ]

        self.assertEqual(format_location_choice(rows[0]), "旧宅 | 主舞台")
        self.assertEqual(format_location_choice(rows[1]), "码头")
        self.assertEqual(selected_location_name(rows, [2, 1, 99]), "码头")
        self.assertEqual(selected_location_name(rows, [2, 99]), "")

    def test_refresh_location_items_loads_location_world_items(self) -> None:
        store = FakeStore()
        store.world_items["location"] = [
            {"name": "旧宅", "tags": "主舞台"},
            {"name": "码头", "tags": ""},
        ]
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.store = store
        ui.location_list = FakeListbox()

        ui.refresh_location_items()

        self.assertEqual(ui.location_rows, store.world_items["location"])
        self.assertEqual(ui.location_list.items, ["旧宅 | 主舞台", "码头"])

    def test_refresh_world_items_filters_by_selected_type(self) -> None:
        store = FakeStore()
        store.world_items["character"] = [{"kind": "character", "name": "林砚", "tags": "主角"}]
        store.world_items["location"] = [{"kind": "location", "name": "旧宅", "tags": "主舞台"}]
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.store = store
        ui.world_kind = FakeVar("地点设定")
        ui.world_list = FakeListbox()

        ui.refresh_world_items()

        self.assertEqual(store.listed_world_kind, "location")
        self.assertEqual(ui.world_rows, store.world_items["location"])
        self.assertEqual(ui.world_list.items, ["地点设定 | 旧宅 | 主舞台"])

    def test_world_kind_change_clears_form_and_loads_selected_type(self) -> None:
        store = FakeStore()
        store.world_items["location"] = [{"kind": "location", "name": "旧宅", "tags": "主舞台"}]
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_world_item_id = 9
        ui.current_world_details_json = '{"old": true}'
        ui.store = store
        ui.world_kind = FakeVar("地点设定")
        ui.world_name = FakeVar("林砚")
        ui.world_tags = FakeVar("主角")
        ui.world_summary = FakeText("旧摘要")
        ui.world_list = FakeListbox()

        ui._on_world_kind_changed()

        self.assertIsNone(ui.current_world_item_id)
        self.assertEqual(ui.current_world_details_json, "")
        self.assertEqual(ui.world_kind.get(), "地点设定")
        self.assertEqual(ui.world_name.get(), "")
        self.assertEqual(ui.world_tags.get(), "")
        self.assertEqual(ui.world_summary.get("1.0", "end"), "")
        self.assertEqual(store.listed_world_kind, "location")
        self.assertEqual(ui.world_list.items, ["地点设定 | 旧宅 | 主舞台"])

    def test_after_enrich_world_item_fills_form_without_saving(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_world_item_id = 9
        ui.world_kind = FakeVar("")
        ui.world_name = FakeVar("")
        ui.world_tags = FakeVar("")
        ui.world_summary = FakeText("")
        ui.refresh_logs = lambda: None

        message = ui._after_enrich_world_item(
            {
                "world_item": {
                    "id": 9,
                    "kind": "character",
                    "name": "林砚",
                    "summary": "补全后的角色摘要",
                    "details": {"motivation": "寻找真相"},
                    "tags": "主角,AI补全",
                }
            }
        )

        self.assertEqual(message, "资料设定补充完成，请确认后点击“保存资料”")
        self.assertEqual(ui.world_kind.get(), "角色卡")
        self.assertEqual(ui.world_name.get(), "林砚")
        self.assertEqual(ui.world_tags.get(), "主角,AI补全")
        self.assertEqual(ui.world_summary.get("1.0", "end"), "补全后的角色摘要")
        self.assertIn("寻找真相", ui.current_world_details_json)

    def test_write_current_chapter_memory_runs_async_pipeline(self) -> None:
        calls = []

        class Pipeline:
            def write_chapter_memory(self, project_id: int, chapter_id: int):
                calls.append((project_id, chapter_id))
                return {"world_items": 2}

        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_chapter_id = 7
        ui.pipeline = Pipeline()
        ui.refresh_world_items = lambda: None
        ui.refresh_character_cards = lambda: None
        ui.refresh_location_items = lambda: None
        ui.refresh_logs = lambda: None
        ui._run_async = lambda action, _running, _success, after: calls.append(after(action()))

        ui.write_current_chapter_memory()

        self.assertEqual(calls[0], (42, 7))
        self.assertEqual(calls[1], "本章资料库记忆已更新，共更新 2 条资料")

    def test_apply_selected_location_item_sets_structure_location_field(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.location_rows = [{"name": "旧宅", "tags": "主舞台"}]
        ui.location_list = FakeListbox()
        ui.location_list.selection_set(0)
        ui.structure_fields = {"location": FakeEntry("手动地点")}
        messages = []
        ui._ok = lambda message: messages.append(message)

        ui.apply_selected_location_item()

        self.assertEqual(ui.structure_fields["location"].var.get(), "旧宅")
        self.assertEqual(messages, ["已选择地点设定"])

    def test_apply_selected_location_item_requires_world_location_selection(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.location_rows = [{"name": "旧宅", "tags": "主舞台"}]
        ui.location_list = FakeListbox()
        messages = []
        ui._error = lambda message: messages.append(message)

        ui.apply_selected_location_item()

        self.assertEqual(messages, ["请选择资料库地点设定"])

    def test_latest_outline_index_selects_first_refreshed_row(self) -> None:
        self.assertIsNone(latest_outline_index([]))
        self.assertEqual(latest_outline_index([{"id": 3}, {"id": 2}]), 0)

    def test_refresh_outline_versions_displays_project_local_numbers(self) -> None:
        store = FakeStore()
        store.versions = [
            {"id": 17, "kind": "global_outline", "label": "最新框架", "created_at": "now"},
            {"id": 9, "kind": "global_outline", "label": "旧框架", "created_at": "before"},
        ]
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.store = store
        ui.outline_versions = FakeListbox()

        ui.refresh_outline_versions()

        self.assertEqual([row["id"] for row in ui.outline_version_rows], [17, 9])
        self.assertEqual(ui.outline_versions.items, ["1 | 最新框架 | now", "2 | 旧框架 | before"])
        self.assertNotIn("17 |", ui.outline_versions.items[0])

    def test_save_current_outline_creates_new_global_outline_with_selected_metadata(self) -> None:
        store = FakeStore()
        store.versions = [
            {
                "id": 17,
                "project_id": 42,
                "kind": "global_outline",
                "label": "旧框架",
                "content": "旧内容",
                "metadata_json": json.dumps({"expanded_outline": "旧内容", "tone": "冷峻"}, ensure_ascii=False),
                "created_at": "before",
            }
        ]
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.store = store
        ui.outline_versions = FakeListbox()
        ui.outline_version_rows = store.versions
        ui.outline_versions.selection_set(0)
        ui.outline_text = FakeText("用户改写后的总框架")
        messages = []
        ui._ok = lambda message: messages.append(message)
        ui._error = lambda message: messages.append(message)

        ui.save_current_outline()

        saved = store.versions[0]
        self.assertEqual(saved["kind"], "global_outline")
        self.assertEqual(saved["label"], "手动修改总框架")
        self.assertEqual(saved["content"], "用户改写后的总框架")
        metadata = json.loads(saved["metadata_json"])
        self.assertEqual(metadata["tone"], "冷峻")
        self.assertEqual(metadata["expanded_outline"], "用户改写后的总框架")
        self.assertEqual(metadata["source"], "manual_edit")
        self.assertEqual(ui.outline_versions.curselection(), (0,))
        self.assertEqual(ui.outline_text.get("1.0", "end"), "用户改写后的总框架")
        self.assertEqual(messages, ["当前总框架修改已保存"])

    def test_save_current_outline_rejects_blank_content(self) -> None:
        store = FakeStore()
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.store = store
        ui.outline_text = FakeText("  \n")
        messages = []
        ui._error = lambda message: messages.append(message)

        ui.save_current_outline()

        self.assertEqual(store.versions, [])
        self.assertEqual(messages, ["总框架内容不能为空"])

    def test_confirm_outline_split_runs_pipeline_async(self) -> None:
        pipeline = FakeStreamingPipeline()
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.pipeline = pipeline
        ui.outline_version_rows = [{"id": 17}]
        ui.outline_versions = FakeListbox()
        ui.outline_versions.selection_set(0)
        ui.outline_split_preview = FakeText("旧预览")
        events = []
        ui.current_chapter_id = 3
        ui.current_section_id = 2
        ui.current_version_ids = [11]
        ui.section_rows = [{"id": 2}]
        ui.version_rows = [{"id": 11}]
        ui.structure_fields = {"title": FakeEntry("旧章节")}
        ui.version_list = FakeListbox()
        ui.version_text = FakeText("旧正文")
        ui.refresh_world_items = lambda: events.append("refresh_world_items")
        ui.refresh_character_cards = lambda: events.append("refresh_character_cards")
        ui.refresh_location_items = lambda: events.append("refresh_location_items")
        ui.refresh_structure = lambda: events.append("refresh_structure")
        ui.refresh_logs = lambda: events.append("refresh_logs")

        def fake_run_async(action, running, success, after):
            events.append(f"running:{running}")
            events.append(after(action()))
            events.append(f"success:{success}")

        ui._run_async = fake_run_async
        ui._error = lambda message: events.append(f"error:{message}")

        ui.confirm_outline_split()

        self.assertEqual(pipeline.calls, [("stream_split", 42, 17)])
        self.assertEqual(ui.outline_split_preview.get("1.0", "end"), '{"chapters":[]}')
        self.assertEqual(events[0], "running:正在确认并拆分章节，请稍候...")
        self.assertIn("refresh_structure", events)
        self.assertEqual(events[-1], "success:已确认并拆分章节")
        self.assertIsNone(ui.current_chapter_id)
        self.assertIsNone(ui.current_section_id)

    def test_refresh_versions_displays_local_numbers_but_keeps_real_ids(self) -> None:
        store = FakeStore()
        store.versions = [
            {"id": 31, "section_id": 7, "kind": "draft", "status": "usable", "label": "粗稿"},
            {"id": 42, "section_id": 7, "kind": "review", "status": "usable", "label": "审稿"},
        ]
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 1
        ui.current_section_id = 7
        ui.store = store
        ui.version_list = FakeListbox()

        ui.refresh_versions()

        self.assertEqual(ui.current_version_ids, [31, 42])
        self.assertEqual(ui.version_list.items, ["1 | draft | usable | 粗稿", "2 | review | usable | 审稿"])
        ui.version_list.selection_set(1)
        self.assertEqual(ui._selected_versions(), [42])

    def test_move_chapter_up_updates_order_and_keeps_moved_chapter_selected(self) -> None:
        store = FakeStore()
        store.chapters = [
            {"id": 1, "number": 1, "title": "第一章", "status": "planned"},
            {"id": 2, "number": 2, "title": "第二章", "status": "planned"},
        ]
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_chapter_id = 2
        ui.current_section_id = 9
        ui.store = store
        ui.chapter_rows = store.chapters
        ui.section_rows = []
        ui.chapter_list = FakeListbox()
        ui.chapter_list.selection_set(1)
        ui.section_list = FakeListbox()
        ui.structure_fields = {
            "title": FakeEntry(""),
            "characters": FakeEntry(""),
            "goal": FakeEntry(""),
        }
        messages = []
        ui._ok = lambda message: messages.append(message)
        ui._error = lambda message: messages.append(f"error:{message}")

        ui.move_chapter_up()

        self.assertEqual(store.moved_chapter, (42, 2, -1))
        self.assertEqual([chapter["id"] for chapter in ui.chapter_rows], [2, 1])
        self.assertEqual(ui.current_chapter_id, 2)
        self.assertIsNone(ui.current_section_id)
        self.assertEqual(ui.chapter_list.selected, 0)
        self.assertEqual(ui.structure_fields["title"].var.get(), "第二章")
        self.assertEqual(messages, ["章节顺序已更新"])

    def test_move_chapter_requires_selection(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.chapter_list = FakeListbox()
        messages = []
        ui._error = lambda message: messages.append(message)

        ui.move_chapter_down()

        self.assertEqual(messages, ["请选择章节"])

    def test_structure_data_uses_project_default_section_target_words_when_blank(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.store = FakeStore()
        ui.project_fields = {"default_section_target_words": FakeVar("1800")}
        ui.structure_fields = {
            "title": FakeEntry("小节"),
            "story_time": FakeEntry("雨夜"),
            "location": FakeEntry("旧宅"),
            "characters": FakeText("林砚"),
            "goal": FakeText("发现入口"),
            "scene": FakeText("走廊"),
            "conflict": FakeText("隐瞒"),
            "emotion_shift": FakeText("紧张"),
            "must_happen": FakeText("发现拖痕"),
            "forbidden": FakeText("不要揭示真相"),
            "target_words": FakeEntry(""),
        }

        data = ui._structure_data()

        self.assertEqual(data["target_words"], 1800)

    def test_calculate_default_section_target_words_uses_total_and_section_count(self) -> None:
        self.assertEqual(calculate_default_section_target_words("8万字", "40"), "2000")
        self.assertEqual(calculate_default_section_target_words("90000", "45节"), "2000")
        self.assertEqual(calculate_default_section_target_words("", "40"), "")

    def test_save_project_calculates_default_section_target_words_when_blank(self) -> None:
        store = FakeStore()
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = None
        ui.store = store
        ui.project_fields = {
            "title": FakeVar("新项目"),
            "length_target": FakeVar("8万字"),
            "estimated_total_sections": FakeVar("40"),
            "default_section_target_words": FakeVar(""),
        }
        ui.project_texts = {}
        events = []
        ui.refresh_projects = lambda: events.append("refresh_projects")
        ui.select_project_by_id = lambda project_id: events.append(f"select:{project_id}") or True
        ui._ok = lambda message: events.append(f"ok:{message}")
        ui._error = lambda message: events.append(f"error:{message}")

        ui.save_project()

        self.assertEqual(store.saved_project_id, 77)
        self.assertEqual(store.saved_data["estimated_total_sections"], "40")
        self.assertEqual(store.saved_data["default_section_target_words"], "2000")
        self.assertEqual(ui.project_fields["default_section_target_words"].get(), "2000")
        self.assertEqual(events, ["refresh_projects", "select:77", "ok:项目已保存"])

    def test_delete_selected_chapter_clears_context_and_refreshes(self) -> None:
        store = FakeStore()
        store.chapters = [
            {"id": 1, "number": 1, "title": "第一章", "status": "planned"},
            {"id": 2, "number": 2, "title": "第二章", "status": "planned"},
        ]
        store.sections = {1: [{"id": 7, "number": 1, "title": "第一节", "status": "planned"}]}
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_chapter_id = 1
        ui.current_section_id = 7
        ui.current_version_ids = [31]
        ui.store = store
        ui.chapter_rows = store.chapters
        ui.section_rows = store.sections[1]
        ui.version_rows = [{"id": 31}]
        ui.chapter_list = FakeListbox()
        ui.chapter_list.selection_set(0)
        ui.section_list = FakeListbox()
        ui.version_list = FakeListbox()
        ui.version_text = FakeText("正文")
        ui.structure_fields = {"title": FakeEntry("旧章"), "characters": FakeText("林砚")}
        messages = []
        ui._ok = lambda message: messages.append(message)
        ui._error = lambda message: messages.append(f"error:{message}")

        ui.delete_selected_chapter()

        self.assertEqual(store.deleted_chapter, (42, 1))
        self.assertIsNone(ui.current_chapter_id)
        self.assertIsNone(ui.current_section_id)
        self.assertEqual(ui.current_version_ids, [])
        self.assertEqual(ui.structure_fields["title"].var.get(), "")
        self.assertEqual(ui.version_text.get("1.0", "end"), "")
        self.assertEqual(ui.chapter_list.items, ["1. 第二章 | 已规划"])
        self.assertEqual(messages, ["章节已删除"])

    def test_move_section_up_updates_order_and_keeps_section_selected(self) -> None:
        store = FakeStore()
        store.chapters = [{"id": 3, "number": 1, "title": "章节", "status": "planned"}]
        store.sections = {
            3: [
                {"id": 7, "number": 1, "title": "第一节", "status": "planned"},
                {"id": 8, "number": 2, "title": "第二节", "status": "planned"},
            ]
        }
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_chapter_id = 3
        ui.store = store
        ui.chapter_rows = store.chapters
        ui.section_rows = store.sections[3]
        ui.chapter_list = FakeListbox()
        ui.chapter_list.selection_set(0)
        ui.section_list = FakeListbox()
        ui.section_list.selection_set(1)
        ui.version_list = FakeListbox()
        ui.structure_fields = {
            "title": FakeEntry(""),
            "target_words": FakeEntry(""),
        }
        ui.project_fields = {"default_section_target_words": FakeVar("")}
        messages = []
        ui._ok = lambda message: messages.append(message)
        ui._error = lambda message: messages.append(f"error:{message}")

        ui.move_section_up()

        self.assertEqual(store.moved_section, (3, 8, -1))
        self.assertEqual([section["id"] for section in store.sections[3]], [8, 7])
        self.assertEqual(ui.current_section_id, 8)
        self.assertEqual(ui.section_list.selected, 0)
        self.assertEqual(messages, ["小节顺序已更新"])

    def test_delete_selected_section_clears_versions_and_refreshes_section_list(self) -> None:
        store = FakeStore()
        store.chapters = [{"id": 3, "number": 1, "title": "章节", "status": "planned"}]
        store.sections = {
            3: [
                {"id": 7, "number": 1, "title": "第一节", "status": "planned"},
                {"id": 8, "number": 2, "title": "第二节", "status": "planned"},
            ]
        }
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_chapter_id = 3
        ui.current_section_id = 7
        ui.current_version_ids = [31]
        ui.store = store
        ui.chapter_rows = store.chapters
        ui.section_rows = store.sections[3]
        ui.chapter_list = FakeListbox()
        ui.chapter_list.selection_set(0)
        ui.section_list = FakeListbox()
        ui.section_list.selection_set(0)
        ui.version_list = FakeListbox()
        ui.version_text = FakeText("正文")
        ui.structure_fields = {"title": FakeEntry(""), "target_words": FakeEntry("")}
        ui.project_fields = {"default_section_target_words": FakeVar("")}
        messages = []
        ui._ok = lambda message: messages.append(message)
        ui._error = lambda message: messages.append(f"error:{message}")

        ui.delete_selected_section()

        self.assertEqual(store.deleted_section_id, 7)
        self.assertIsNone(ui.current_section_id)
        self.assertEqual(ui.current_version_ids, [])
        self.assertEqual(ui.section_list.items, ["1. 第二节 | 已规划"])
        self.assertEqual(ui.version_text.get("1.0", "end"), "")
        self.assertEqual(messages, ["小节已删除"])

    def test_writing_automation_runs_draft_review_rewrite_finalize_and_continue(self) -> None:
        store = FakeStore()
        store.sections = {
            3: [
                {"id": 7, "chapter_id": 3, "number": 1, "title": "第一节", "status": "planned"},
                {"id": 8, "chapter_id": 3, "number": 2, "title": "第二节", "status": "planned"},
            ]
        }
        pipeline = FakePipeline()
        pipeline.next_section = store.sections[3][1]
        ui = object.__new__(NovelDesktopUI)
        ui.store = store
        ui.pipeline = pipeline

        result = ui._run_writing_automation(42, 7, "增强冲突")

        self.assertEqual(
            pipeline.calls,
            [
                ("draft", 42, 7, "rough"),
                ("review", 42, 7, 101),
                ("rewrite", 42, 7, 101, 102, "增强冲突", []),
                ("continue", 7),
            ],
        )
        self.assertEqual(store.finalized_section, (7, 103))
        self.assertEqual(result["next_section"]["id"], 8)

    def test_after_writing_automation_switches_to_next_section_when_enabled(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.structure_auto_next_enabled = FakeVar(True)
        events = []
        ui.refresh_versions = lambda: events.append("refresh_versions")
        ui.refresh_structure = lambda: events.append("refresh_structure")
        ui.refresh_logs = lambda: events.append("refresh_logs")
        ui._select_next_section_for_writing = lambda section_id: events.append(f"select:{section_id}") or True

        message = ui._after_writing_automation({"next_section": {"id": 8}})

        self.assertEqual(
            events,
            ["refresh_versions", "refresh_structure", "refresh_logs", "select:8"],
        )
        self.assertEqual(message, "自动化写作完成，已切换到下一节")

    def test_chapter_automation_starts_from_current_section_and_continues_same_chapter(self) -> None:
        store = FakeStore()
        store.sections = {
            3: [
                {"id": 7, "chapter_id": 3, "number": 1, "title": "第一节", "status": "planned"},
                {"id": 8, "chapter_id": 3, "number": 2, "title": "第二节", "status": "planned"},
                {"id": 9, "chapter_id": 3, "number": 3, "title": "第三节", "status": "planned"},
            ]
        }
        pipeline = FakePipeline()
        pipeline.next_sections = [store.sections[3][2], None]
        ui = object.__new__(NovelDesktopUI)
        ui.store = store
        ui.pipeline = pipeline
        ui.services = FakeServices()
        cancel_event = threading.Event()

        result = ui._run_chapter_writing_automation(42, 3, 8, "全文改写", cancel_event)

        draft_calls = [call for call in pipeline.calls if call[0] == "draft"]
        self.assertEqual(draft_calls, [("draft", 42, 8, "rough"), ("draft", 42, 9, "rough")])
        self.assertEqual(result["processed"], [8, 9])
        self.assertEqual(result["last_section_id"], 9)
        self.assertIn("当前章节没有下一节", result["stopped"])
        self.assertEqual(store.finalized_section, (9, 103))
        self.assertIs(ui.services.llm.retry_configs[0][0], cancel_event)
        self.assertEqual(ui.services.llm.retry_configs[-1], (None, None, None))

    def test_chapter_automation_does_not_cross_chapter_by_default(self) -> None:
        store = FakeStore()
        store.chapters = [
            {"id": 3, "number": 1, "title": "第一章"},
            {"id": 4, "number": 2, "title": "第二章"},
        ]
        store.sections = {
            3: [{"id": 8, "chapter_id": 3, "number": 1, "title": "第一节", "status": "planned"}],
            4: [{"id": 20, "chapter_id": 4, "number": 1, "title": "下一章第一节", "status": "planned"}],
        }
        pipeline = FakePipeline()
        pipeline.next_sections = [None]
        ui = object.__new__(NovelDesktopUI)
        ui.store = store
        ui.pipeline = pipeline
        ui.services = FakeServices()
        cancel_event = threading.Event()

        result = ui._run_chapter_writing_automation(42, 3, 8, "全文改写", cancel_event)

        draft_calls = [call for call in pipeline.calls if call[0] == "draft"]
        self.assertEqual(draft_calls, [("draft", 42, 8, "rough")])
        self.assertEqual(result["processed"], [8])
        self.assertIn("当前章节没有下一节", result["stopped"])

    def test_chapter_automation_crosses_to_next_chapter_when_enabled(self) -> None:
        store = FakeStore()
        store.chapters = [
            {"id": 3, "number": 1, "title": "第一章"},
            {"id": 4, "number": 2, "title": "第二章"},
        ]
        store.sections = {
            3: [{"id": 8, "chapter_id": 3, "number": 1, "title": "第一节", "status": "planned"}],
            4: [{"id": 20, "chapter_id": 4, "number": 1, "title": "下一章第一节", "status": "planned"}],
        }
        pipeline = FakePipeline()
        pipeline.next_sections = [None, None]
        ui = object.__new__(NovelDesktopUI)
        ui.store = store
        ui.pipeline = pipeline
        ui.services = FakeServices()
        cancel_event = threading.Event()

        result = ui._run_chapter_writing_automation(
            42,
            3,
            8,
            "全文改写",
            cancel_event,
            auto_next_chapter=True,
        )

        draft_calls = [call for call in pipeline.calls if call[0] == "draft"]
        self.assertEqual(draft_calls, [("draft", 42, 8, "rough"), ("draft", 42, 20, "rough")])
        self.assertEqual(result["processed"], [8, 20])
        self.assertEqual(result["last_section_id"], 20)
        self.assertIn("当前章节没有下一节", result["stopped"])

    def test_start_chapter_automation_passes_next_chapter_option(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_chapter_id = 3
        ui.current_section_id = 8
        ui.rewrite_mode = FakeVar("全文改写")
        ui.structure_auto_next_chapter_enabled = FakeVar(True)
        ui.automation_cancel_event = None
        ui._project_required = lambda: 42
        captured = {}

        def fake_run_chapter(project_id, chapter_id, section_id, rewrite_mode, cancel_event, auto_next_chapter=False):
            captured["args"] = (project_id, chapter_id, section_id, rewrite_mode, auto_next_chapter)
            return {"processed": []}

        def fake_run_async(callback, *_args):
            callback()

        ui._run_chapter_writing_automation = fake_run_chapter
        ui._run_async = fake_run_async

        ui.start_chapter_automation()

        self.assertEqual(captured["args"], (42, 3, 8, "全文改写", True))

    def test_chapter_automation_stops_when_cancelled_before_next_step(self) -> None:
        store = FakeStore()
        store.sections = {
            3: [
                {"id": 8, "chapter_id": 3, "number": 2, "title": "第二节", "status": "planned"},
            ]
        }
        pipeline = FakePipeline()
        ui = object.__new__(NovelDesktopUI)
        ui.store = store
        ui.pipeline = pipeline
        ui.services = FakeServices()
        cancel_event = threading.Event()
        cancel_event.set()

        with self.assertRaisesRegex(RuntimeError, "用户已中断自动化写作"):
            ui._run_chapter_writing_automation(42, 3, 8, "全文改写", cancel_event)

        self.assertEqual(pipeline.calls, [])
        self.assertEqual(ui.services.llm.retry_configs[-1], (None, None, None))

    def test_interrupt_chapter_automation_sets_cancel_event(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.automation_cancel_event = threading.Event()
        messages = []
        ui._ok = lambda message: messages.append(message)

        ui.interrupt_chapter_automation()

        self.assertTrue(ui.automation_cancel_event.is_set())
        self.assertEqual(messages, ["已请求中断自动化写作，等待当前请求结束"])

    def test_start_chapter_automation_requires_selected_section(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_chapter_id = 3
        ui.current_section_id = None
        messages = []
        ui._error = lambda message: messages.append(message)

        ui.start_chapter_automation()

        self.assertEqual(messages, ["请先选择小节"])

    def test_after_confirm_outline_split_refreshes_world_and_clears_selection_context(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_chapter_id = 3
        ui.current_section_id = 2
        ui.current_version_ids = [11]
        ui.section_rows = [{"id": 2}]
        ui.version_rows = [{"id": 11}]
        ui.structure_fields = {
            "title": FakeEntry("旧章节"),
            "characters": FakeText("旧角色"),
            "goal": FakeText("旧目标"),
        }
        ui.version_list = FakeListbox()
        ui.version_text = FakeText("旧正文")
        events = []
        ui.refresh_world_items = lambda: events.append("refresh_world_items")
        ui.refresh_character_cards = lambda: events.append("refresh_character_cards")
        ui.refresh_location_items = lambda: events.append("refresh_location_items")
        ui.refresh_structure = lambda: events.append("refresh_structure")
        ui.refresh_logs = lambda: events.append("refresh_logs")

        ui._after_confirm_outline_split()

        self.assertIsNone(ui.current_chapter_id)
        self.assertIsNone(ui.current_section_id)
        self.assertEqual(ui.current_version_ids, [])
        self.assertEqual(ui.section_rows, [])
        self.assertEqual(ui.version_rows, [])
        self.assertEqual(ui.structure_fields["title"].var.get(), "")
        self.assertEqual(ui.structure_fields["characters"].get("1.0", "end"), "")
        self.assertEqual(ui.structure_fields["goal"].get("1.0", "end"), "")
        self.assertTrue(ui.version_list.deleted)
        self.assertEqual(ui.version_text.get("1.0", "end"), "")
        self.assertEqual(
            events,
            [
                "refresh_world_items",
                "refresh_character_cards",
                "refresh_location_items",
                "refresh_structure",
                "refresh_logs",
            ],
        )

    def test_project_index_by_id_finds_new_project_after_refresh(self) -> None:
        projects = [{"id": 1, "title": "旧项目"}, {"id": 7, "title": "新项目"}]

        self.assertEqual(project_index_by_id(projects, 7), 1)
        self.assertIsNone(project_index_by_id(projects, 99))

    def test_select_project_by_id_selects_refreshed_project_without_gui_loop(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.projects = [{"id": 1, "title": "旧项目"}, {"id": 7, "title": "新项目"}]
        ui.project_list = FakeListbox()
        events = []
        ui.select_project = lambda: events.append("select_project")

        self.assertTrue(ui.select_project_by_id(7))

        self.assertEqual(ui.project_list.selected, 1)
        self.assertEqual(ui.project_list.active, 1)
        self.assertEqual(ui.project_list.visible, 1)
        self.assertEqual(events, ["select_project"])

    def test_refresh_projects_rebuilds_cache_and_clears_deleted_current_project(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        store = FakeStore()
        ui.store = store
        ui.projects = [{"id": 7, "title": "已删除项目"}]
        ui.project_list = FakeListbox()
        ui.current_project_id = 7
        ui.current_chapter_id = 3
        ui.current_section_id = 2
        ui.current_world_item_id = 9
        ui.current_version_ids = [11]
        ui.project_fields = {"title": FakeVar("已删除项目"), "genre": FakeVar("悬疑")}
        ui.project_texts = {"world_summary": FakeText("旧世界书")}
        ui.world_kind = FakeVar("伏笔")
        ui.world_name = FakeVar("旧资料")
        ui.world_tags = FakeVar("旧标签")
        ui.world_summary = FakeText("旧资料摘要")
        ui.structure_fields = {
            "title": FakeEntry("旧章节"),
            "characters": FakeText("旧人物"),
            "goal": FakeText("旧目标"),
        }
        ui.outline_versions = FakeListbox()
        ui.world_list = FakeListbox()
        ui.chapter_list = FakeListbox()
        ui.section_list = FakeListbox()
        ui.version_list = FakeListbox()
        ui.character_card_list = FakeListbox()
        ui.location_list = FakeListbox()
        ui.outline_text = FakeText("旧 AI 框架")
        ui.world_context_text = FakeText("旧资料参考")
        ui.version_text = FakeText("旧正文")
        ui.logs_text = FakeText("旧日志")
        ui.outline_version_rows = [{"id": 1}]
        ui.world_rows = [{"id": 2}]
        ui.chapter_rows = [{"id": 3}]
        ui.section_rows = [{"id": 4}]
        ui.version_rows = [{"id": 5}]
        ui.character_card_rows = [{"id": 6}]
        ui.location_rows = [{"id": 7}]
        messages = []
        ui._ok = lambda message: messages.append(message)

        ui.refresh_projects()

        self.assertEqual(store.rebuild_count, 1)
        self.assertEqual(ui.projects, [])
        self.assertEqual(ui.project_list.items, [])
        self.assertIsNone(ui.current_project_id)
        self.assertIsNone(ui.current_chapter_id)
        self.assertIsNone(ui.current_section_id)
        self.assertIsNone(ui.current_world_item_id)
        self.assertEqual(ui.current_version_ids, [])
        self.assertEqual(ui.project_fields["title"].get(), "")
        self.assertEqual(ui.project_texts["world_summary"].get("1.0", "end"), "")
        self.assertEqual(ui.outline_version_rows, [])
        self.assertEqual(ui.world_rows, [])
        self.assertEqual(ui.chapter_rows, [])
        self.assertEqual(ui.section_rows, [])
        self.assertEqual(ui.version_rows, [])
        self.assertEqual(messages, ["当前项目文件夹已不存在，已从列表移除"])

    def test_refresh_projects_keeps_current_project_when_cache_rebuild_still_lists_it(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        store = FakeStore()
        store.projects[7] = {"id": 7, "title": "保留项目"}
        ui.store = store
        ui.projects = []
        ui.project_list = FakeListbox()
        ui.current_project_id = 7
        messages = []
        ui._ok = lambda message: messages.append(message)

        ui.refresh_projects()

        self.assertEqual(store.rebuild_count, 1)
        self.assertEqual(ui.projects, [{"id": 7, "title": "保留项目"}])
        self.assertEqual(ui.project_list.items, ["7 | 保留项目"])
        self.assertEqual(ui.current_project_id, 7)
        self.assertEqual(messages, [])

    def test_start_new_project_clears_current_project_context_and_form(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 7
        ui.current_chapter_id = 3
        ui.current_section_id = 2
        ui.current_world_item_id = 9
        ui.current_version_ids = [11]
        ui.project_fields = {"title": FakeVar("旧项目"), "genre": FakeVar("悬疑")}
        ui.project_texts = {"world_summary": FakeText("旧世界书")}
        ui.project_list = FakeListbox()
        ui.outline_versions = FakeListbox()
        ui.world_list = FakeListbox()
        ui.chapter_list = FakeListbox()
        ui.section_list = FakeListbox()
        ui.version_list = FakeListbox()
        ui.character_card_list = FakeListbox()
        ui.location_list = FakeListbox()
        ui.outline_text = FakeText("旧大纲")
        ui.world_context_text = FakeText("旧资料")
        ui.version_text = FakeText("旧正文")
        ui.logs_text = FakeText("旧日志")
        ui.outline_version_rows = [{"id": 1}]
        ui.world_rows = [{"id": 2}]
        ui.chapter_rows = [{"id": 3}]
        ui.section_rows = [{"id": 4}]
        ui.version_rows = [{"id": 5}]
        ui.character_card_rows = [{"id": 6}]
        ui.location_rows = [{"id": 7}]
        messages = []
        ui._ok = lambda message: messages.append(message)

        ui.start_new_project()

        self.assertIsNone(ui.current_project_id)
        self.assertIsNone(ui.current_chapter_id)
        self.assertIsNone(ui.current_section_id)
        self.assertIsNone(ui.current_world_item_id)
        self.assertEqual(ui.current_version_ids, [])
        self.assertEqual(ui.project_fields["title"].get(), "")
        self.assertEqual(ui.project_fields["genre"].get(), "")
        self.assertEqual(ui.project_texts["world_summary"].get("1.0", "end"), "")
        self.assertEqual(ui.outline_version_rows, [])
        self.assertEqual(ui.world_rows, [])
        self.assertEqual(ui.chapter_rows, [])
        self.assertEqual(ui.section_rows, [])
        self.assertEqual(ui.version_rows, [])
        self.assertEqual(ui.character_card_rows, [])
        self.assertEqual(ui.location_rows, [])
        self.assertEqual(messages, ["已切换到新建项目"])

    def test_select_project_clears_previous_generated_content_and_structure_form(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.projects = [{"id": 8, "title": "新项目", "genre": "奇幻", "world_summary": "新世界"}]
        ui.project_list = FakeListbox()
        ui.project_list.selection_set(0)
        ui.current_project_id = 7
        ui.current_chapter_id = 3
        ui.current_section_id = 2
        ui.current_world_item_id = 9
        ui.current_version_ids = [11]
        ui.project_fields = {"title": FakeVar("旧项目"), "genre": FakeVar("悬疑")}
        ui.project_texts = {"world_summary": FakeText("旧世界书")}
        ui.world_kind = FakeVar("伏笔")
        ui.world_name = FakeVar("旧资料")
        ui.world_tags = FakeVar("旧标签")
        ui.world_summary = FakeText("旧资料摘要")
        ui.structure_fields = {
            "title": FakeEntry("旧章节"),
            "characters": FakeText("旧人物"),
            "goal": FakeText("旧目标"),
        }
        ui.outline_versions = FakeListbox()
        ui.world_list = FakeListbox()
        ui.chapter_list = FakeListbox()
        ui.section_list = FakeListbox()
        ui.version_list = FakeListbox()
        ui.character_card_list = FakeListbox()
        ui.location_list = FakeListbox()
        ui.outline_text = FakeText("旧 AI 框架")
        ui.world_context_text = FakeText("旧资料参考")
        ui.version_text = FakeText("旧正文")
        ui.logs_text = FakeText("旧日志")
        ui.outline_version_rows = [{"id": 1}]
        ui.world_rows = [{"id": 2}]
        ui.chapter_rows = [{"id": 3}]
        ui.section_rows = [{"id": 4}]
        ui.version_rows = [{"id": 5}]
        ui.character_card_rows = [{"id": 6}]
        ui.location_rows = [{"id": 7}]
        ui.refresh_all_project_views = lambda: None

        ui.select_project()

        self.assertEqual(ui.current_project_id, 8)
        self.assertIsNone(ui.current_chapter_id)
        self.assertIsNone(ui.current_section_id)
        self.assertIsNone(ui.current_world_item_id)
        self.assertEqual(ui.current_version_ids, [])
        self.assertEqual(ui.project_fields["title"].get(), "新项目")
        self.assertEqual(ui.project_fields["genre"].get(), "奇幻")
        self.assertEqual(ui.project_texts["world_summary"].get("1.0", "end"), "新世界")
        self.assertEqual(ui.world_kind.get(), "角色卡")
        self.assertEqual(ui.world_name.get(), "")
        self.assertEqual(ui.world_tags.get(), "")
        self.assertEqual(ui.world_summary.get("1.0", "end"), "")
        self.assertEqual(ui.structure_fields["title"].var.get(), "")
        self.assertEqual(ui.structure_fields["characters"].get("1.0", "end"), "")
        self.assertEqual(ui.structure_fields["goal"].get("1.0", "end"), "")
        self.assertEqual(ui.outline_text.get("1.0", "end"), "")
        self.assertEqual(ui.world_context_text.get("1.0", "end"), "")
        self.assertEqual(ui.version_text.get("1.0", "end"), "")

    def test_start_new_chapter_clears_selected_chapter_context_and_form(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 7
        ui.current_chapter_id = 3
        ui.current_section_id = 2
        ui.current_version_ids = [11]
        ui.section_rows = [{"id": 2}]
        ui.version_rows = [{"id": 11}]
        ui.structure_fields = {
            "title": FakeEntry("旧章节"),
            "location": FakeEntry("旧宅"),
            "characters": FakeText("林砚"),
            "goal": FakeText("旧目标"),
        }
        ui.chapter_list = FakeListbox()
        ui.chapter_list.selection_set(0)
        ui.section_list = FakeListbox()
        ui.version_list = FakeListbox()
        ui.version_text = FakeText("旧正文")
        messages = []
        ui._ok = lambda message: messages.append(message)

        ui.start_new_chapter()

        self.assertIsNone(ui.current_chapter_id)
        self.assertIsNone(ui.current_section_id)
        self.assertEqual(ui.current_version_ids, [])
        self.assertEqual(ui.section_rows, [])
        self.assertEqual(ui.version_rows, [])
        self.assertIsNone(ui.chapter_list.selected)
        self.assertTrue(ui.section_list.deleted)
        self.assertTrue(ui.version_list.deleted)
        self.assertEqual(ui.structure_fields["title"].var.get(), "")
        self.assertEqual(ui.structure_fields["location"].var.get(), "")
        self.assertEqual(ui.structure_fields["characters"].get("1.0", "end"), "")
        self.assertEqual(ui.structure_fields["goal"].get("1.0", "end"), "")
        self.assertEqual(ui.version_text.get("1.0", "end"), "")
        self.assertEqual(messages, ["已切换到新建章节"])

    def test_start_new_chapter_requires_project(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = None
        messages = []
        ui._error = lambda message: messages.append(message)

        ui.start_new_chapter()

        self.assertEqual(messages, ["请先创建或选择项目"])

    def test_export_success_message_includes_output_path(self) -> None:
        path = Path("projects/project-7/exports/新项目-全书.docx")

        self.assertEqual(format_export_success_message(path), f"全书 Word 已导出：{path}")

    def test_async_error_completion_refreshes_logs_and_reports_message(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        events = []
        ui._async_busy = True
        ui.refresh_logs = lambda: events.append("refresh_logs")
        ui._error = lambda message: events.append(f"error:{message}")

        ui._complete_async_error("boom")

        self.assertEqual(events, ["refresh_logs", "error:boom"])
        self.assertFalse(ui._async_busy)

    def test_run_async_sets_busy_and_rejects_duplicate_task(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.root = FakeRoot()
        ui._async_busy = False
        events = []
        started = threading.Event()
        release = threading.Event()
        ui._ok = lambda message: events.append(f"ok:{message}")
        ui._error = lambda message: events.append(f"error:{message}")
        ui.refresh_logs = lambda: events.append("refresh_logs")

        def action() -> None:
            started.set()
            release.wait(1)

        ui._run_async(action, "running", "done")
        self.assertTrue(started.wait(1))
        ui._run_async(lambda: events.append("duplicate action"), "running2", "done2")
        release.set()
        self._wait_until(lambda: not ui._async_busy)

        self.assertIn("ok:running", events)
        self.assertIn("error:已有后台任务运行中，请稍候", events)
        self.assertIn("ok:done", events)
        self.assertNotIn("duplicate action", events)

    def test_run_async_success_callback_receives_result_on_after(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.root = FakeRoot()
        ui._async_busy = False
        events = []
        ui._ok = lambda message: events.append(f"ok:{message}")
        ui._error = lambda message: events.append(f"error:{message}")
        ui.refresh_logs = lambda: events.append("refresh_logs")

        ui._run_async(lambda: 7, "running", "done", lambda result: events.append(f"callback:{result}"))
        self._wait_until(lambda: not ui._async_busy)

        self.assertEqual(events, ["ok:running", "callback:7", "ok:done"])

    def test_run_async_failure_callback_refreshes_logs_and_clears_busy(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.root = FakeRoot()
        ui._async_busy = False
        events = []
        ui._ok = lambda message: events.append(f"ok:{message}")
        ui._error = lambda message: events.append(f"error:{message}")
        ui.refresh_logs = lambda: events.append("refresh_logs")

        def action() -> None:
            raise RuntimeError("network down")

        ui._run_async(action, "running", "done")
        self._wait_until(lambda: not ui._async_busy)

        self.assertEqual(events, ["ok:running", "refresh_logs", "error:network down"])
        self.assertFalse(ui._async_busy)

    def test_run_streaming_draft_resets_and_appends_text(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.root = FakeRoot()
        ui.pipeline = FakeStreamingPipeline()
        ui.version_text = FakeText("旧正文")
        ui.current_generation_text = FakeText("旧生成")

        result = ui._run_streaming_draft(42, 7)

        self.assertEqual(result["content"], "第一段第二段")
        self.assertEqual(ui.pipeline.calls, [("stream_draft", 42, 7, "rough")])
        self.assertEqual(ui.current_generation_text.get("1.0", "end"), "第一段第二段")
        self.assertEqual(ui.version_text.get("1.0", "end"), "旧正文")

    def test_run_streaming_outline_resets_and_appends_text(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.root = FakeRoot()
        ui.pipeline = FakeStreamingPipeline()
        ui.outline_text = FakeText("旧框架")

        result = ui._run_streaming_outline(42)

        self.assertEqual(result["expanded_outline"], "第一段第二段")
        self.assertEqual(ui.pipeline.calls, [("stream_outline", 42, None)])
        self.assertEqual(ui.outline_text.get("1.0", "end"), "第一段第二段")

    def test_run_streaming_outline_split_resets_and_appends_preview_text(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.root = FakeRoot()
        ui.pipeline = FakeStreamingPipeline()
        ui.outline_split_preview = FakeText("旧预览")

        result = ui._run_streaming_outline_split(42, 17)

        self.assertEqual(result["sections"], 2)
        self.assertEqual(ui.pipeline.calls, [("stream_split", 42, 17)])
        self.assertEqual(ui.outline_split_preview.get("1.0", "end"), '{"chapters":[]}')

    def test_run_streaming_outline_split_falls_back_to_non_streaming_pipeline(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.root = FakeRoot()
        ui.pipeline = FakePipeline()
        ui.outline_split_preview = FakeText("旧预览")

        result = ui._run_streaming_outline_split(42, 17)

        self.assertEqual(result["world_items"], 3)
        self.assertEqual(ui.pipeline.calls, [("confirm_outline_split", 42, 17)])
        self.assertIn("非流式降级", ui.outline_split_preview.get("1.0", "end"))

    def test_run_streaming_outline_split_keeps_partial_preview_on_failure(self) -> None:
        class FailingSplitPipeline:
            def confirm_outline_split_streaming(self, project_id: int, version_id: int, on_delta) -> None:
                on_delta("partial")
                raise RuntimeError("bad json")

        ui = object.__new__(NovelDesktopUI)
        ui.root = FakeRoot()
        ui.pipeline = FailingSplitPipeline()
        ui.outline_split_preview = FakeText("旧预览")

        with self.assertRaises(RuntimeError):
            ui._run_streaming_outline_split(42, 17)

        self.assertEqual(ui.outline_split_preview.get("1.0", "end"), "partial")

    def test_append_streaming_text_scrolls_when_widget_supports_it(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_generation_text = FakeListbox()

        ui._append_streaming_text("正文")

        self.assertEqual(ui.current_generation_text.items, ["正文"])
        self.assertEqual(ui.current_generation_text.visible, "end")

    def test_apply_model_scan_results_updates_text_fields_and_logs(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.config_vars = {
            "chat_model": FakeVar(""),
            "review_model": FakeVar("existing-review"),
            "embedding_model": FakeVar(""),
        }
        ui.model_scan_text = FakeText("")
        events = []
        ui.refresh_logs = lambda: events.append("refresh_logs")
        ui._ok = lambda message: events.append(f"ok:{message}")

        result = ui._apply_model_scan_results(
            {"chat_model": "", "review_model": "existing-review", "embedding_model": ""},
            {"source": "remote", "warning": "", "models": ["writer-large", "embed-small"]},
        )

        self.assertFalse(result)
        self.assertEqual(ui.config_vars["chat_model"].get(), "writer-large")
        self.assertEqual(ui.config_vars["review_model"].get(), "existing-review")
        self.assertEqual(ui.config_vars["embedding_model"].get(), "embed-small")
        self.assertIn("来源: remote", ui.model_scan_text.get("1.0", "end"))
        self.assertEqual(events, ["refresh_logs", "ok:已扫描到 2 个模型"])

    def test_world_context_query_uses_chapter_and_section_fields(self) -> None:
        query = build_world_context_query(
            {
                "title": "第三章",
                "story_time": "雨夜",
                "location": "旧宅",
                "characters": "林砚\n周棠",
                "goal": "发现地下室入口",
                "scene": "一层走廊",
                "conflict": "周棠隐瞒来过这里",
            }
        )

        self.assertIn("旧宅", query)
        self.assertIn("林砚", query)
        self.assertIn("地下室入口", query)

    def test_format_world_context_pack_uses_chinese_kind_labels(self) -> None:
        text = format_world_context_pack(
            {
                "long_term": [
                    {"kind": "organization", "name": "旧宅基金会", "summary": "控制旧宅档案", "tags": "势力"},
                    {"kind": "character", "name": "林砚", "summary": "调查者", "tags": "主角"},
                ],
                "forbidden": [{"kind": "forbidden", "name": "真相", "summary": "不要提前揭示"}],
                "retrieval_notes": [],
            }
        )

        self.assertIn("[组织/势力] 旧宅基金会", text)
        self.assertIn("[角色卡] 林砚", text)
        self.assertIn("禁止事项", text)

    def test_model_scan_autofill_empty_fields(self) -> None:
        updates = model_scan_autofill(
            {"chat_model": "", "review_model": "", "embedding_model": ""},
            ["text-creative", "text-embedding-3-small", "reasoner"],
        )
        self.assertEqual(
            updates,
            {
                "chat_model": "text-creative",
                "review_model": "text-creative",
                "embedding_model": "text-embedding-3-small",
            },
        )

    def test_model_scan_autofill_preserves_existing_fields(self) -> None:
        updates = model_scan_autofill(
            {
                "chat_model": "existing-chat",
                "review_model": "existing-review",
                "embedding_model": "existing-embed",
            },
            ["new-chat", "new-embedding"],
        )
        self.assertEqual(updates, {})

    def test_model_scan_autofill_uses_first_non_embedding_for_text_models(self) -> None:
        updates = model_scan_autofill(
            {"chat_model": "", "review_model": "", "embedding_model": ""},
            ["fast-embed", "writer-large", "critic-large"],
        )
        self.assertEqual(updates["chat_model"], "writer-large")
        self.assertEqual(updates["review_model"], "writer-large")
        self.assertEqual(updates["embedding_model"], "fast-embed")

    def test_llm_config_fields_include_proxy_url(self) -> None:
        self.assertIn("proxy_url", llm_config_field_keys())

    def test_llm_config_fields_include_api_type(self) -> None:
        self.assertIn("api_type", llm_config_field_keys())

    def test_llm_config_fields_include_model_candidates(self) -> None:
        self.assertIn("model_candidates", llm_config_field_keys())

    def test_parse_model_candidates_strips_blank_lines(self) -> None:
        self.assertEqual(
            parse_model_candidates(" writer-large \n\nembed-small\n writer-large "),
            ["writer-large", "embed-small", "writer-large"],
        )

    def test_format_model_discovery_result_includes_source_warning_and_models(self) -> None:
        text = format_model_discovery_result(
            {
                "source": "manual",
                "warning": "Remote /models discovery failed",
                "models": ["writer-large", "embed-small"],
            }
        )
        self.assertIn("来源: manual", text)
        self.assertIn("警告: Remote /models discovery failed", text)
        self.assertIn("模型列表:", text)
        self.assertIn("writer-large", text)
        self.assertIn("embed-small", text)

    def test_format_model_discovery_result_handles_empty_models(self) -> None:
        self.assertIn(
            "未发现可用模型",
            format_model_discovery_result({"source": "none", "warning": "", "models": []}),
        )

    def test_build_llm_config_from_vars_includes_proxy_url(self) -> None:
        config = build_llm_config_from_vars(
            {
                "base_url": FakeVar("https://api.example.test/v1"),
                "api_type": FakeVar("/chat/completions"),
                "api_key": FakeVar("secret"),
                "proxy_url": FakeVar("http://127.0.0.1:7890"),
                "chat_model": FakeVar("writer"),
                "review_model": FakeVar("reviewer"),
                "embedding_model": FakeVar("embedder"),
                "model_candidates": FakeVar(" writer-large \n\nembed-small "),
                "timeout_seconds": FakeVar("30"),
                "max_tokens": FakeVar("2048"),
                "temperature": FakeVar("0.8"),
                "top_p": FakeVar("0.9"),
                "top_k": FakeVar("40"),
                "presence_penalty": FakeVar("0.1"),
                "frequency_penalty": FakeVar("0.2"),
            }
        )
        self.assertEqual(config["api_type"], "chat_completions")
        self.assertEqual(config["proxy_url"], "http://127.0.0.1:7890")
        self.assertEqual(config["model_candidates"], "writer-large\nembed-small")
        self.assertEqual(config["timeout_seconds"], 30)
        self.assertEqual(config["max_tokens"], 2048)
        self.assertEqual(config["top_k"], 40)
        self.assertEqual(config["temperature"], 0.8)

    def test_build_llm_config_from_vars_defaults_api_type(self) -> None:
        config = build_llm_config_from_vars(
            {
                "timeout_seconds": FakeVar("30"),
                "max_tokens": FakeVar("2048"),
                "temperature": FakeVar("0.8"),
                "top_p": FakeVar("0.9"),
                "top_k": FakeVar(""),
                "presence_penalty": FakeVar("0.1"),
                "frequency_penalty": FakeVar("0.2"),
            }
        )
        expected_api_type = str(DEFAULT_LLM_CONFIG.get("api_type", "responses") or "responses")
        self.assertEqual(config["api_type"], expected_api_type)

    def test_build_llm_config_from_vars_accepts_none_like_top_k(self) -> None:
        config = build_llm_config_from_vars(
            {
                "timeout_seconds": FakeVar("30"),
                "max_tokens": FakeVar("2048"),
                "temperature": FakeVar("0.8"),
                "top_p": FakeVar("0.9"),
                "top_k": FakeVar("None"),
                "presence_penalty": FakeVar("0.1"),
                "frequency_penalty": FakeVar("0.2"),
            }
        )
        self.assertIsNone(config["top_k"])

    def test_pyside_stylesheet_contains_hover_and_pressed_feedback(self) -> None:
        stylesheet = build_pyside_stylesheet()
        self.assertIn("QListWidget::item:hover", stylesheet)
        self.assertIn("QListWidget::item:pressed", stylesheet)
        self.assertIn("QListWidget#ProjectShelf::item", stylesheet)
        self.assertIn("QListWidget#ChapterTree::item", stylesheet)
        self.assertIn("QTextEdit#WritingEditor", stylesheet)
        self.assertIn("QTextEdit#StreamingOutput", stylesheet)
        self.assertIn("QTextEdit#ProjectTextInput", stylesheet)
        self.assertIn("QFrame#ProjectDetailPane QLabel", stylesheet)
        self.assertIn("background: transparent", stylesheet)
        self.assertIn("QPushButton:pressed", stylesheet)
        self.assertIn("QTextEdit:focus", stylesheet)
        self.assertIn("min-width: 0", stylesheet)
        self.assertIn("min-height: 0", stylesheet)
        self.assertIn("#6fa8ff", stylesheet)
        self.assertIn("#f6b7c9", stylesheet)

    def test_pyside_project_shelf_uses_custom_delegate(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("class ProjectShelfListWidget(QListWidget)", source)
        self.assertIn("EDGE_PADDING = 2", source)
        self.assertIn("def _fit_book_grid", source)
        self.assertIn("TWO_COLUMN_MIN_WIDTH =", source)
        self.assertIn("if base_available_width >= self.TWO_COLUMN_MIN_WIDTH:", source)
        self.assertIn("side_padding = self.EDGE_PADDING + max(0, (base_available_width - used_width) // 2)", source)
        self.assertIn("self.setViewportMargins(side_padding, 0, side_padding, 0)", source)
        self.assertIn("class ProjectShelfDelegate(QStyledItemDelegate)", source)
        self.assertIn("setItemDelegate(ProjectShelfDelegate", source)
        self.assertIn("GRID_WIDTH =", source)
        self.assertIn("self.setGridSize(QSize(self.GRID_WIDTH, self.GRID_HEIGHT))", source)
        self.assertIn("return QSize(176, 252)", source)
        self.assertIn("card_width = min(176", source)
        self.assertIn("cover_width =", source)
        self.assertIn("cover_height =", source)
        self.assertIn("shelf_rect", source)
        self.assertIn("cover_rect", source)
        self.assertIn("meta_rect = QRect(text_rect.left(), text_rect.top() + 26", source)

    def test_pyside_project_text_inputs_have_unified_input_style(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn('text.setObjectName("ProjectTextInput")', source)
        self.assertIn('text.setPlaceholderText(f"请输入{label}")', source)

    def test_pyside_tag_and_character_details_use_dialog_buttons(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("选择标签与引号", source)
        self.assertIn("def edit_project_tags_dialog", source)
        self.assertIn("编辑角色卡基础信息", source)
        self.assertIn("def edit_character_basic_dialog", source)
        self.assertIn("role_combo = QComboBox()", source)
        self.assertIn("_single_character_role_flags", source)

    def test_pyside_save_project_guides_main_character_setup(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("def _prompt_main_character_setup_after_save", source)
        self.assertIn("去资料库创建主要角色", source)
        self.assertIn("暂不创建，直接继续", source)
        self.assertIn("是否自动调用 API", source)
        self.assertIn("自动生成默认主要角色", source)
        self.assertIn("generate_default_main_character", source)
        self.assertIn("def _after_generate_default_main_character", source)
        self.assertIn("def _open_character_card_setup", source)
        self.assertIn("world_kind_label(\"character\")", source)

    def test_pyside_world_kind_programmatic_updates_do_not_refresh_list(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("def _set_world_kind_safely", source)
        self.assertIn("self._updating_world_kind = True", source)
        self.assertIn("self.world_kind.blockSignals(True)", source)
        self.assertIn("self.world_kind.blockSignals(previous)", source)
        self.assertIn("if getattr(self, \"_updating_world_kind\", False):", source)
        self.assertIn("self._set_world_kind_safely(str(item.get(\"kind\", \"character\")))", source)
        self.assertIn("self._set_world_kind_safely(item.get(\"kind\", \"character\"))", source)

    def test_pyside_project_refresh_does_not_steal_saved_selection(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("self.project_list.blockSignals(True)", source)
        self.assertIn("self.project_list.blockSignals(False)", source)
        self.assertIn("saved_project_id = self.store.create_project(data)", source)
        self.assertIn("self.current_project_id = saved_project_id", source)
        self.assertIn("self.select_project_by_id(saved_project_id)", source)

    def test_pyside_project_page_has_search_creation_entry(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        project_block = source[source.index("def _build_project_page"):source.index("def _build_project_tag_controls")]
        self.assertIn("新建空白项目", project_block)
        self.assertIn("open_new_project_choice_dialog", project_block)
        self.assertNotIn("open_search_project_creation_dialog", project_block)
        self.assertIn("def open_new_project_choice_dialog", source)
        self.assertIn("通过标签/候选方案生成", source)

    def test_pyside_search_creation_dialog_generates_and_applies_candidates(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("class SearchProjectCreationDialog(QDialog)", source)
        self.assertIn("搜索式需求", source)
        self.assertIn("相关标签：点一下选中", source)
        self.assertIn("QScrollArea", source)
        self.assertIn("QGridLayout", source)
        self.assertIn("self.candidate_list.setVerticalScrollBarPolicy", source)
        self.assertIn("self.detail_text.setVerticalScrollBarPolicy", source)
        self.assertIn("ScrollBarAlwaysOff", source)
        self.assertIn("ScrollBarAlwaysOn", source)
        self.assertIn("setViewportMargins(0, 0, 12, 0)", source)
        self.assertIn("\"故事标签\"", source)
        self.assertIn("\"写作标签\"", source)
        self.assertIn("def _group_visible_tags", source)
        self.assertIn("def _add_tag_button_group", source)
        self.assertIn("requires_memory", source)
        self.assertIn("max_columns = 3", source)
        self.assertIn("def _refresh_tag_buttons", source)
        self.assertIn("def _cycle_tag_state", source)
        self.assertIn("def _excluded_tag_ids", source)
        self.assertIn("正在自动创建候选方案", source)
        self.assertIn("def _after_generate_candidates", source)
        self.assertIn("def _set_generation_busy", source)
        self.assertIn("def _generate_search_creation_candidates_streaming", source)
        self.assertIn("generate_novel_candidates_streaming(profile, on_delta)", source)
        self.assertIn('self.owner._temporary_stream_targets["search_candidate"] = self.detail_text', source)
        self.assertIn('"search_candidate"', source)
        self.assertIn("self.progress_bar = QProgressBar()", source)
        self.assertIn('self.progress_bar.setObjectName("LlmProgress")', source)
        self.assertIn("self.progress_bar.setRange(0, 0)", source)
        self.assertIn("background: #ffe9ec", source)
        search_dialog_block = source[
            source.index("class SearchProjectCreationDialog(QDialog)"):
            source.index("def _generate_search_creation_candidates")
        ]
        self.assertNotIn("filter_column.addStretch", search_dialog_block)
        self.assertLess(source.index("相关标签：点一下选中"), source.index("filter_column.addWidget(QLabel(\"标签/排除项\"))"))
        self.assertLess(source.index("layout.addLayout(body, 1)"), source.index("self.reader_combo = QComboBox()"))
        self.assertNotIn("打开现有标签选择", source)
        self.assertIn("生成候选", source)
        self.assertIn("用这个创建项目", source)
        self.assertIn("def _generate_search_creation_candidates", source)
        self.assertIn("hasattr", source)
        self.assertIn("def _apply_search_candidate_to_project", source)
        self.assertIn("self.current_project_id = None", source)
        self.assertIn("尚未保存", source)
        self.assertIn("self._temporary_stream_targets", source)
        self.assertIn("widgets.update(getattr(self, \"_temporary_stream_targets\", {}))", source)

    def test_pyside_character_summary_does_not_expand_world_layout_width(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("self.character_basic_summary.setWordWrap(True)", source)
        self.assertIn("QSizePolicy.Policy.Ignored", source)

    def test_pyside_world_library_uses_resizable_splitter_and_direction_input(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("splitter = QSplitter(Qt.Orientation.Horizontal)", source)
        self.assertIn("splitter.setStretchFactor(0, 1)", source)
        self.assertIn("splitter.setStretchFactor(1, 2)", source)
        self.assertIn("AI 自动创建资料", source)
        self.assertIn("手动创建资料", source)
        self.assertLess(source.index("AI 自动创建资料"), source.index("手动创建资料"))
        self.assertLess(source.index("手动创建资料"), source.index("刷新资料库"))
        self.assertIn("def new_world_item", source)
        self.assertIn("self._clear_world_form(reset_kind=False)", source)
        self.assertIn("self.world_list.setCurrentRow(-1)", source)
        self.assertIn("def _ask_world_enrich_direction", source)
        self.assertIn("AI 修改方向", source)
        self.assertIn("direction = self._ask_world_enrich_direction()", source)
        self.assertIn("self.pipeline.enrich_world_item(project_id, item_id, direction)", source)
        self.assertIn("正在连接模型，准备流式生成资料 JSON", source)
        self.assertIn("def _run_streaming_world_item", source)
        self.assertIn("generate_world_item_streaming(project_id, kind, on_delta)", source)
        self.assertIn("self.pipeline.generate_world_item(project_id, kind)", source)
        self.assertIn('"world_item": self.world_summary', source)
        self.assertNotIn("self.world_ai_direction = QTextEdit()", source)

    def test_pyside_outline_page_owns_planning_mode_and_word_fields(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        project_block = source[source.index("def _build_project_page"):source.index("def _build_project_tag_controls")]
        outline_block = source[source.index("def _build_outline_page"):source.index("def _build_world_page")]
        self.assertNotIn('"length_target"', project_block)
        self.assertNotIn('"estimated_total_sections"', project_block)
        self.assertNotIn('"default_section_target_words"', project_block)
        self.assertIn("self.outline_mode = QComboBox()", outline_block)
        self.assertIn("整书模式", outline_block)
        self.assertIn("连载模式", outline_block)
        self.assertIn("self.serial_action = QComboBox()", outline_block)
        self.assertIn("生成下一部分大纲", outline_block)
        self.assertIn("self.outline_planning_fields", outline_block)
        self.assertIn('"planning_target_words"', outline_block)
        self.assertIn('"planning_chapter_count"', outline_block)
        self.assertIn('"default_chapter_target_words"', outline_block)
        self.assertIn('"section_count_approx"', outline_block)
        self.assertIn("预计全书/本次章节数", source)
        self.assertIn("默认每章目标字数", source)
        self.assertIn("单章节约几个小节", source)
        self.assertIn("planning_options = self._outline_planning_options()", source)
        self.assertIn("expand_global_concept_streaming(project_id, on_delta, planning_options)", source)

    def test_pyside_bottom_progress_bar_tracks_async_llm_tasks(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("QProgressBar", source)
        self.assertIn('self.llm_progress.setObjectName("LlmProgress")', source)
        self.assertIn("self.llm_progress.setRange(0, 0)", source)
        self.assertIn("self.llm_progress.setVisible(False)", source)
        self.assertIn("def _set_llm_progress", source)
        self.assertIn("self._set_llm_progress(True)", source)
        self.assertGreaterEqual(source.count("self._set_llm_progress(False)"), 2)

    def test_pyside_world_edit_dialogs_follow_main_window_size(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("def _resize_dialog_to_window", source)
        self.assertGreaterEqual(source.count("self._resize_dialog_to_window(dialog)"), 2)

    def _wait_until(self, predicate) -> None:
        deadline = time.time() + 1
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("condition was not met before timeout")


if __name__ == "__main__":
    unittest.main()
