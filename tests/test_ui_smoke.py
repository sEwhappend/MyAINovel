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

    def delete_version(self, version_id: int) -> None:
        self.deleted_version_id = version_id
        self.versions = [version for version in self.versions if version.get("id") != version_id]

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

    def write_section_draft_streaming(self, project_id: int, section_id: int, mode: str, on_delta) -> dict[str, object]:
        self.calls.append(("stream_draft", project_id, section_id, mode))
        on_delta("粗稿")
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
        direction: str = "",
    ) -> dict[str, object]:
        self.calls.append(("rewrite", project_id, section_id, version_id, review_id, rewrite_mode, preserve, direction))
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

    def write_chapter_memory(self, project_id: int, chapter_id: int) -> dict[str, object]:
        self.calls.append(("chapter_memory", project_id, chapter_id))
        return {"world_items": 0}


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
        self.assertEqual(world_kind_label("timeline_event"), "事件")
        self.assertEqual(world_kind_label("unknown_kind"), "unknown_kind")

    def test_world_kind_value_preserves_internal_enum(self) -> None:
        self.assertEqual(world_kind_value("角色卡"), "character")
        self.assertEqual(world_kind_value("人物设定"), "character")
        self.assertEqual(world_kind_value("事件"), "timeline_event")
        self.assertEqual(world_kind_value("时间线"), "timeline_event")
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

    def test_delete_selected_outline_version_removes_version_and_refreshes(self) -> None:
        store = FakeStore()
        store.versions = [
            {
                "id": 17,
                "project_id": 42,
                "kind": "global_outline",
                "label": "最新框架",
                "content": "最新内容",
                "metadata_json": "{}",
                "created_at": "now",
            },
            {
                "id": 9,
                "project_id": 42,
                "kind": "global_outline",
                "label": "旧框架",
                "content": "旧内容",
                "metadata_json": "{}",
                "created_at": "before",
            },
        ]
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.store = store
        ui.outline_version_rows = store.versions
        ui.outline_versions = FakeListbox()
        ui.outline_versions.items = ["1 | 最新框架 | now", "2 | 旧框架 | before"]
        ui.outline_versions.selection_set(0)
        ui.outline_text = FakeText("最新内容")
        ui.outline_split_preview = FakeText("旧预览")
        events = []
        ui.refresh_logs = lambda: events.append("refresh_logs")
        ui._ok = lambda message: events.append(f"ok:{message}")
        ui._error = lambda message: events.append(f"error:{message}")

        ui.delete_selected_outline_version()

        self.assertIsNone(store.get_version(17))
        self.assertIsNotNone(store.get_version(9))
        self.assertEqual(ui.outline_versions.items, ["1 | 旧框架 | before"])
        self.assertEqual(ui.outline_versions.curselection(), (0,))
        self.assertEqual(ui.outline_text.get("1.0", "end"), "旧内容")
        self.assertEqual(events, ["refresh_logs", "ok:总框架版本已删除"])

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

    def test_delete_selected_version_removes_version_and_refreshes_list(self) -> None:
        store = FakeStore()
        store.sections = {3: [{"id": 7, "chapter_id": 3, "number": 1, "title": "第一节", "status": "planned"}]}
        store.versions = [
            {"id": 31, "project_id": 42, "chapter_id": 3, "section_id": 7, "kind": "draft", "status": "usable", "label": "粗稿", "content": "旧正文"},
            {"id": 32, "project_id": 42, "chapter_id": 3, "section_id": 7, "kind": "rewrite", "status": "usable", "label": "改写", "content": "新正文"},
        ]
        ui = object.__new__(NovelDesktopUI)
        ui.current_project_id = 42
        ui.current_chapter_id = 3
        ui.current_section_id = 7
        ui.current_version_ids = [31, 32]
        ui.version_rows = store.versions
        ui.store = store
        ui.version_list = FakeListbox()
        ui.version_list.items = ["1 | draft | usable | 粗稿", "2 | rewrite | usable | 改写"]
        ui.version_list.selection_set(0)
        ui.version_text = FakeText("旧正文")
        ui.refresh_structure = lambda: None
        ui.refresh_logs = lambda: None
        messages = []
        ui._ok = lambda message: messages.append(message)
        ui._error = lambda message: messages.append(f"error:{message}")

        ui.delete_selected_version()

        self.assertEqual(store.deleted_version_id, 31)
        self.assertIsNone(store.get_version(31))
        self.assertIsNotNone(store.get_version(32))
        self.assertEqual(ui.current_version_ids, [32])
        self.assertEqual(ui.version_list.items, ["1 | rewrite | usable | 改写"])
        self.assertEqual(ui.version_text.get("1.0", "end"), "")
        self.assertEqual(messages, ["已删除 1 个版本"])

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
                ("stream_draft", 42, 7, "rough"),
                ("review", 42, 7, 101),
                ("rewrite", 42, 7, 101, 102, "增强冲突", [], ""),
                ("continue", 7),
            ],
        )
        self.assertEqual(store.finalized_section, (7, 103))
        self.assertEqual(result["next_section"]["id"], 8)

    def test_single_writing_automation_configures_retry_until_finished(self) -> None:
        store = FakeStore()
        store.sections = {
            3: [
                {"id": 7, "chapter_id": 3, "number": 1, "title": "第一节", "status": "planned"},
            ]
        }
        pipeline = FakePipeline()
        ui = object.__new__(NovelDesktopUI)
        ui.store = store
        ui.pipeline = pipeline
        ui.services = FakeServices()
        cancel_event = threading.Event()

        result = ui._run_single_writing_automation(42, 7, "增强冲突", cancel_event)

        self.assertEqual(result["draft_version_id"], 101)
        self.assertEqual(pipeline.calls[0], ("stream_draft", 42, 7, "rough"))
        self.assertIs(ui.services.llm.retry_configs[0][0], cancel_event)
        self.assertEqual(ui.services.llm.retry_configs[-1], (None, None, None))

    def test_after_writing_automation_switches_to_next_section_when_enabled(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.structure_auto_next_enabled = FakeVar(True)
        events = []
        ui._refresh_structure_preserving_selection = lambda: events.append("preserve_selection")
        ui.refresh_logs = lambda: events.append("refresh_logs")
        ui._select_next_section_for_writing = lambda section_id: events.append(f"select:{section_id}") or True

        message = ui._after_writing_automation({"next_section": {"id": 8}})

        self.assertEqual(
            events,
            ["select:8", "refresh_logs"],
        )
        self.assertEqual(message, "自动化写作完成，已切换到下一节")

    def test_after_writing_automation_preserves_current_selection_when_not_switching(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.structure_auto_next_enabled = FakeVar(False)
        events = []
        ui._refresh_structure_preserving_selection = lambda: events.append("preserve_selection")
        ui.refresh_logs = lambda: events.append("refresh_logs")
        ui._select_next_section_for_writing = lambda section_id: events.append(f"select:{section_id}") or True

        message = ui._after_writing_automation({"next_section": {"id": 8}})

        self.assertEqual(events, ["preserve_selection", "refresh_logs"])
        self.assertEqual(message, "自动化写作完成，下一节已满足继续条件")

    def test_after_writing_task_preserves_current_selection_after_refresh(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        events = []
        ui._refresh_structure_preserving_selection = lambda: events.append("preserve_selection")
        ui.refresh_logs = lambda: events.append("refresh_logs")

        ui._after_writing_task()

        self.assertEqual(events, ["preserve_selection", "refresh_logs"])

    def test_version_text_title_describes_selected_version(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.current_version_ids = [31, 32]
        ui.version_text_title = FakeVar("版本内容：未选择版本")

        ui._set_version_text_title({"id": 32, "kind": "rewrite", "status": "usable", "label": "改写"})

        self.assertEqual(ui.version_text_title.get(), "版本内容：2 | rewrite | usable | 改写")

        ui._set_version_text_title(None)

        self.assertEqual(ui.version_text_title.get(), "")

    def test_show_selected_version_clears_right_side_when_no_version_selected(self) -> None:
        ui = object.__new__(NovelDesktopUI)
        ui.version_list = FakeListbox()
        ui.current_version_ids = []
        ui.version_text_title = FakeVar("旧标题")
        ui.version_text = FakeText("旧正文")

        ui.show_selected_version()

        self.assertEqual(ui.version_text_title.get(), "")
        self.assertEqual(ui.version_text.get("1.0", "end"), "")

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

        draft_calls = [call for call in pipeline.calls if call[0] in {"draft", "stream_draft"}]
        self.assertEqual(draft_calls, [("stream_draft", 42, 8, "rough"), ("stream_draft", 42, 9, "rough")])
        self.assertEqual(result["processed"], [8, 9])
        self.assertEqual(result["last_section_id"], 9)
        self.assertIn("当前章节没有下一节", result["stopped"])
        self.assertEqual(store.finalized_section, (9, 103))
        self.assertIs(ui.services.llm.retry_configs[0][0], cancel_event)
        self.assertEqual(ui.services.llm.retry_configs[-4][0], cancel_event)
        self.assertEqual(ui.services.llm.retry_configs[-3], (None, None, None))
        self.assertEqual(ui.services.llm.retry_configs[-2][0], cancel_event)
        self.assertEqual(ui.services.llm.retry_configs[-1], (None, None, None))
        self.assertIn(("chapter_memory", 42, 3), pipeline.calls)

    def test_chapter_memory_does_not_inherit_indefinite_retry(self) -> None:
        store = FakeStore()
        store.sections = {
            3: [{"id": 8, "chapter_id": 3, "number": 1, "title": "第一节", "status": "planned"}]
        }
        pipeline = FakePipeline()
        pipeline.next_sections = [None]
        ui = object.__new__(NovelDesktopUI)
        ui.store = store
        ui.pipeline = pipeline
        ui.services = FakeServices()
        cancel_event = threading.Event()

        result = ui._run_chapter_writing_automation(42, 3, 8, "全文改写", cancel_event)

        self.assertEqual(result["chapter_memory_results"], [{"ok": True, "world_items": 0}])
        self.assertIn(("chapter_memory", 42, 3), pipeline.calls)
        self.assertEqual(ui.services.llm.retry_configs[-3], (None, None, None))
        self.assertIs(ui.services.llm.retry_configs[-2][0], cancel_event)
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

        draft_calls = [call for call in pipeline.calls if call[0] in {"draft", "stream_draft"}]
        self.assertEqual(draft_calls, [("stream_draft", 42, 8, "rough")])
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

        draft_calls = [call for call in pipeline.calls if call[0] in {"draft", "stream_draft"}]
        self.assertEqual(draft_calls, [("stream_draft", 42, 8, "rough"), ("stream_draft", 42, 20, "rough")])
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

        def fake_run_chapter(project_id, chapter_id, section_id, rewrite_mode, cancel_event, auto_next_chapter=False, direction=""):
            captured["args"] = (project_id, chapter_id, section_id, rewrite_mode, auto_next_chapter, direction)
            return {"processed": []}

        def fake_run_async(callback, *_args):
            callback()

        ui._run_chapter_writing_automation = fake_run_chapter
        ui._run_async = fake_run_async

        ui.start_chapter_automation()

        self.assertEqual(captured["args"], (42, 3, 8, "全文改写", True, ""))

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
        path = Path("projects/project-7/exports/新项目-分节Word")

        self.assertEqual(format_export_success_message(path), f"全书 Word 已分节导出到：{path}")

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
        self.assertIn("QFrame#HeaderBar", stylesheet)
        self.assertIn("QLabel#HeaderTitle", stylesheet)
        self.assertIn("QToolButton#WindowControl", stylesheet)
        self.assertIn("QMainWindow {\n        background: transparent;", stylesheet)
        self.assertIn("QWidget#AppRoot", stylesheet)
        self.assertIn("border-radius: 10px", stylesheet)
        self.assertNotIn("border-radius: 14px", stylesheet)
        self.assertIn("min-height: 42px", stylesheet)
        self.assertIn("max-height: 42px", stylesheet)
        self.assertIn("max-width: 34px", stylesheet)
        self.assertIn("max-height: 24px", stylesheet)
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
        self.assertIn("EDGE_PADDING = 0", source)
        self.assertIn("def _fit_book_grid", source)
        self.assertIn("TWO_COLUMN_MIN_WIDTH =", source)
        self.assertIn("if base_available_width >= self.TWO_COLUMN_MIN_WIDTH:", source)
        self.assertIn("side_padding = self.EDGE_PADDING + max(0, (base_available_width - used_width) // 2)", source)
        self.assertIn("self.setViewportMargins(side_padding, 0, side_padding, 0)", source)
        self.assertIn("class ProjectShelfDelegate(QStyledItemDelegate)", source)
        self.assertIn("setItemDelegate(ProjectShelfDelegate", source)
        self.assertIn("GRID_WIDTH =", source)
        self.assertIn("self.setGridSize(QSize(self.GRID_WIDTH, self.GRID_HEIGHT))", source)
        self.assertIn("return QSize(176, 290)", source)
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

    def test_pyside_outline_page_uses_scrollable_left_settings_and_delete_button(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("splitter = QSplitter(Qt.Orientation.Horizontal)", source)
        self.assertIn("splitter.addWidget(self._vertical_scroll_area(left_frame))", source)
        self.assertIn("self.outline_versions.setMinimumHeight(280)", source)
        self.assertIn("left.addWidget(self.outline_versions, 4)", source)
        self.assertIn('"删除总框架版本", self.delete_selected_outline_version', source)
        self.assertIn("def delete_selected_outline_version", source)
        self.assertIn("self.store.delete_version(version_id)", source)

    def test_pyside_writing_automation_uses_streaming_draft_and_retry(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        automation_start = source.index("def _run_writing_automation(")
        automation_end = source.index("def _run_single_writing_automation(", automation_start)
        automation_source = source[automation_start:automation_end]
        self.assertIn("draft = self._run_streaming_draft(project_id, section_id)", automation_source)
        self.assertNotIn("self.pipeline.write_section_draft(project_id, section_id, \"rough\")", automation_source)
        self.assertIn("def _configure_llm_retry", source)
        self.assertIn("configure_retry_until_cancel(cancel_event, on_retry)", source)
        self.assertIn("self.bridge.status.emit", source)

    def test_pyside_chapter_memory_does_not_inherit_retry_until_cancel(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("def _try_write_chapter_memory(", source)
        self.assertIn("self.services.llm.configure_retry_until_cancel(None, None)", source)
        self.assertIn("return {\"ok\": True, **self.pipeline.write_chapter_memory(project_id, chapter_id)}", source)
        self.assertIn("self._try_write_chapter_memory(project_id, chapter_id, cancel_event)", source)

    def test_pyside_writing_refresh_preserves_current_section(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("def _refresh_structure_preserving_selection", source)
        self.assertIn("self._refresh_structure_preserving_selection()", source)
        self.assertIn("chapter_id = chapter_id if chapter_id is not None else self.current_chapter_id", source)
        self.assertIn("section_id = section_id if section_id is not None else self.current_section_id", source)
        self.assertIn("self.select_chapter_by_id(int(chapter_id))", source)
        self.assertIn("self.select_section_by_id(int(section_id))", source)

    def test_pyside_writing_page_has_version_column_titles(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn('self.version_list_title = QLabel("版本列表")', source)
        self.assertIn('self.version_text_title = QLabel("")', source)
        self.assertIn("def _set_version_text_title", source)
        self.assertIn("self.version_text_title.setText(", source)
        self.assertIn("self.version_list.currentRowChanged.connect(self.show_selected_version)", source)
        self.assertIn("def _display_version_id", source)
        self.assertIn("return int(self.current_version_ids[row_index])", source)
        self.assertIn("版本比较：", source)

    def test_pyside_tag_and_character_details_use_dialog_buttons(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("选择标签/辅助修改", source)
        self.assertIn("class ProjectTagAssistDialog(QDialog)", source)
        self.assertIn('WindowTitleBar("选择标签/辅助修改", self)', source)
        self.assertIn("TagFlowLayout", source)
        self.assertIn("self.query_input.textChanged.connect", source)
        self.assertIn("ProjectTagAssistDialog(self)", source)
        self.assertIn('self.owner._temporary_stream_targets["project_assist"] = self.detail_text', source)
        self.assertIn("def _run_streaming_project_assist", source)
        self.assertIn("assist_project_edit_streaming(profile, on_delta)", source)
        self.assertIn('"project_assist"', source)
        self.assertIn("def _apply_project_patch_to_form", source)
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
        self.assertIn('self.setWindowTitle("标签化生成")', source)
        self.assertIn("class WindowControlButton(QToolButton)", source)
        self.assertIn("def set_control_kind", source)
        self.assertIn('self._control_button("minimize"', source)
        self.assertIn('"maximize",', source)
        self.assertIn('self._control_button("close"', source)
        self.assertIn('self.maximize_button.set_control_kind("restore" if self._manually_maximized else "maximize")', source)
        self.assertIn('if self.control_kind == "minimize":', source)
        self.assertIn('elif self.control_kind == "maximize":', source)
        self.assertIn('elif self.control_kind == "close":', source)
        self.assertIn("class WindowTitleBar(QFrame)", source)
        self.assertNotIn("QStyle.StandardPixmap.SP_TitleBarMinButton", source)
        self.assertNotIn("QStyle.StandardPixmap.SP_TitleBarMaxButton", source)
        self.assertNotIn("QStyle.StandardPixmap.SP_TitleBarCloseButton", source)
        self.assertIn("self._normal_geometry: QRect | None = None", source)
        self.assertIn("self._manually_maximized = False", source)
        self.assertIn('self._resize_edges = ""', source)
        self.assertIn("self._resize_start_geometry: QRect | None = None", source)
        self.assertIn("self._edge_resize_margin = 8", source)
        self.assertIn("self.target.setMinimumSize(QSize(1260, 775))", source)
        self.assertIn("self.target.installEventFilter(self)", source)
        self.assertIn("self.target.setGeometry(screen.availableGeometry())", source)
        self.assertNotIn("self.target.showMaximized()", source)
        self.assertNotIn("self.target.showNormal()", source)
        self.assertNotIn("QBitmap", source)
        self.assertNotIn("setMask", source)
        self.assertIn("def _apply_windows_round_corners", source)
        self.assertIn("DwmSetWindowAttribute", source)
        self.assertIn("corner_preference = ctypes.c_int(2)", source)
        self.assertIn("_apply_windows_round_corners(self.window)", source)
        self.assertIn("_apply_windows_round_corners(self)", source)
        self.assertIn("handle.startSystemMove()", source)
        self.assertIn("handle.startSystemResize(system_edges)", source)
        self.assertIn("def _system_resize_edges", source)
        self.assertIn("def _edge_hit_test", source)
        self.assertIn("def _start_edge_resize", source)
        self.assertIn("def _resize_window", source)
        self.assertIn("def _finish_edge_resize", source)
        self.assertIn("def _update_edge_cursor", source)
        self.assertIn("Qt.CursorShape.SizeFDiagCursor", source)
        self.assertIn("Qt.CursorShape.SizeHorCursor", source)
        self.assertIn("Qt.CursorShape.SizeVerCursor", source)
        self.assertIn("QApplication.screenAt(cursor_pos)", source)
        self.assertIn("min_visible = 96", source)
        self.assertIn("layout.setContentsMargins(12, 4, 8, 4)", source)
        self.assertIn("layout.setSpacing(3)", source)
        self.assertNotIn("button.setIconSize(QSize(12, 12))", source)
        self.assertIn("self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)", source)
        self.assertIn('layout.addWidget(WindowTitleBar("标签化生成", self))', source)
        self.assertIn("self.window.setWindowFlags(self.window.windowFlags() | Qt.WindowType.FramelessWindowHint)", source)
        self.assertNotIn("WA_TranslucentBackground", source)
        self.assertIn("QCursor", source)
        self.assertIn("self._place_window_on_startup_screen()", source)
        self.assertIn("def _place_window_on_startup_screen", source)
        self.assertIn("QApplication.screenAt(QCursor.pos())", source)
        self.assertIn("self.window.move(geometry.topLeft())", source)
        self.assertIn("margin = 24", source)
        self.assertIn("def _vertical_scroll_area", source)
        self.assertIn("widget.setMinimumHeight(34)", source)
        self.assertIn("widget.setMinimumHeight(90)", source)
        self.assertIn("self.world_context_text.setMinimumHeight(180)", source)
        self.assertIn("widget.setMinimumHeight(110)", source)
        self.assertIn("self.model_scan_text.setMinimumHeight(220)", source)
        self.assertIn("Qt.ScrollBarPolicy.ScrollBarAsNeeded", source)
        self.assertIn("layout.addWidget(self._vertical_scroll_area(right_frame), 2)", source)
        self.assertIn("page_layout.addWidget(self._vertical_scroll_area(content))", source)
        self.assertNotIn("def _resize_main_window_to_file_explorer_default", source)
        self.assertNotIn("available.width() * 0.62", source)
        self.assertIn('root.setObjectName("AppRoot")', source)
        self.assertIn('layout.addWidget(WindowTitleBar("My AI Novel    结构化小说生产流水线", self.window))', source)
        self.assertIn("搜索式需求", source)
        self.assertIn("相关标签：点一下选中", source)
        self.assertIn("QScrollArea", source)
        self.assertIn("class TagFlowLayout(QLayout)", source)
        self.assertIn("def heightForWidth", source)
        self.assertIn("self.candidate_list.setVerticalScrollBarPolicy", source)
        self.assertIn("self.detail_text.setVerticalScrollBarPolicy", source)
        self.assertIn("ScrollBarAlwaysOff", source)
        self.assertIn("ScrollBarAlwaysOn", source)
        self.assertIn("setViewportMargins(0, 0, 12, 0)", source)
        self.assertIn('query_title.setObjectName("PanelTitle")', source)
        self.assertIn('tag_title.setObjectName("PanelTitle")', source)
        self.assertIn('candidate_title.setObjectName("PanelTitle")', source)
        self.assertIn('detail_title.setObjectName("PanelTitle")', source)
        self.assertIn('"selected_genre_tags": "题材标签"', source)
        self.assertIn('"selected_setting_tags": "设定标签"', source)
        self.assertIn('"selected_character_tags": "角色标签"', source)
        self.assertIn('"selected_structure_tags": "结构标签"', source)
        self.assertIn('"selected_style_tags": "风格标签"', source)
        self.assertIn('"selected_forbidden_tags": "排除/禁止标签"', source)
        self.assertIn("def _group_visible_tags", source)
        self.assertIn("def _add_tag_button_group", source)
        search_dialog_block = source[
            source.index("class SearchProjectCreationDialog(QDialog)"):
            source.index("class TaggedCharacterCreationDialog(QDialog)")
        ]
        self.assertNotIn('"故事标签"', search_dialog_block)
        self.assertNotIn('"写作标签"', search_dialog_block)
        self.assertNotIn("requires_memory", search_dialog_block)
        self.assertIn("self.tag_flow = TagFlowLayout(self.tag_host)", source)
        self.assertIn("self.tag_flow.addWidget(button)", source)
        self.assertIn('header.setProperty("flow_full_row", True)', source)
        self.assertNotIn("max_columns = 3", source)
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
        self.assertIn('self.detail_text.setObjectName("StreamingOutput")', source)
        self.assertIn('self.status_label.setObjectName("Status")', source)
        self.assertIn("self.progress_bar = QProgressBar()", source)
        self.assertIn('self.progress_bar.setObjectName("LlmProgress")', source)
        self.assertIn("self.progress_bar.setRange(0, 0)", source)
        self.assertIn("footer = QHBoxLayout()", source)
        self.assertIn("footer.addWidget(self.status_label, 1)", source)
        self.assertIn("footer.addWidget(buttons)", source)
        self.assertIn("layout.addLayout(footer)", source)
        self.assertIn("background: #ffe9ec", source)
        search_dialog_block = source[
            source.index("class SearchProjectCreationDialog(QDialog)"):
            source.index("def _generate_search_creation_candidates")
        ]
        self.assertNotIn("filter_column.addStretch", search_dialog_block)
        self.assertLess(source.index("相关标签：点一下选中"), source.index('tag_title = QLabel("标签/排除项")'))
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

    def test_pyside_character_world_item_can_use_tagged_generation(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("def _ask_character_creation_mode", source)
        self.assertIn("class TaggedCharacterCreationDialog(QDialog)", source)
        self.assertIn('WindowTitleBar("标签化生成角色卡", self)', source)
        self.assertIn("def _ask_tagged_character_profile", source)
        self.assertIn("标签化生成角色卡", source)
        self.assertIn("def _run_streaming_tagged_character", source)
        self.assertIn("generate_tagged_character_streaming(project_id, profile, on_delta)", source)
        self.assertIn("正在根据角色标签生成角色卡 JSON", source)
        self.assertIn("dialog = TaggedCharacterCreationDialog(self)", source)

        search_dialog_block = source[
            source.index("class SearchProjectCreationDialog(QDialog)"):
            source.index("def _generate_search_creation_candidates")
        ]
        character_dialog_start = source.index("class TaggedCharacterCreationDialog(QDialog)")
        character_dialog_end = source.index("def _ask_tagged_character_profile", character_dialog_start)
        character_dialog_block = source[character_dialog_start:character_dialog_end]

        for required in [
            "TagFlowLayout",
            "self.tag_flow = TagFlowLayout(self.tag_host)",
            "self.query_input.textChanged.connect",
            "self._refresh_tag_buttons()",
            "def _refresh_tag_buttons",
            "def _cycle_tag_state",
            "def _style_tag_button",
            "self._style_tag_button(button,",
            "self.tag_states",
            "self.tag_buttons",
            "selected_character_tags",
            "self.role_structure_tag_ids",
            "self.protagonist_structure_combo",
            'self.protagonist_structure_combo.addItem("单主角", "single_protagonist")',
            'self.protagonist_structure_combo.addItem("双主角", "dual_protagonists")',
            "role_structure_tag = str(self.protagonist_structure_combo.currentData()",
        ]:
            self.assertIn(required, character_dialog_block)

        self.assertTrue(
            "selected_forbidden_tags" in character_dialog_block or "exclude_tags" in character_dialog_block
        )
        self.assertIn("tag_id in self.role_structure_tag_ids", character_dialog_block)
        self.assertIn("def _visible_tags", character_dialog_block)
        self.assertNotIn('("故事标签", grouped_tags["story"])', character_dialog_block)
        self.assertNotIn('("写作标签", grouped_tags["writing"])', character_dialog_block)
        self.assertIn("def _cycle_tag_state", search_dialog_block)
        self.assertIn("def _style_tag_button", search_dialog_block)
        self.assertIn("self.query_input.textChanged.connect(lambda _text: self._refresh_tag_buttons())", search_dialog_block)

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

    def test_pyside_writing_page_sends_rewrite_direction(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("self.rewrite_direction_input = QLineEdit()", source)
        self.assertIn("AI 修改方向", source)
        self.assertIn("self.rewrite_direction_input.text().strip()", source)
        self.assertIn("direction=direction", source)

    def test_pyside_writing_page_can_delete_selected_version(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn('"删除版本"', source)
        self.assertIn("def delete_selected_version", source)
        self.assertIn("self.store.delete_version(version_id)", source)
        self.assertIn("请选择要删除的版本", source)

    def test_pyside_world_edit_dialogs_follow_main_window_size(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("def _resize_dialog_to_window", source)
        self.assertGreaterEqual(source.count("self._resize_dialog_to_window(dialog)"), 2)

    def test_pyside_relation_graph_page_exists(self) -> None:
        source = (SRC / "my_ai_novel" / "pyside_ui.py").read_text(encoding="utf-8")
        self.assertIn("from .relation_graph import build_character_graph, build_event_graph", source)
        self.assertIn("QGraphicsView", source)
        self.assertIn("QGraphicsScene", source)
        self.assertIn("class RelationGraphView(QGraphicsView)", source)
        self.assertIn("def _build_relation_graph_page", source)
        self.assertIn('page = self._add_page("关系图")', source)
        self.assertIn('"人物关系"', source)
        self.assertIn('"事件关系"', source)
        self.assertIn('"显示弱推断关系"', source)
        self.assertIn("def refresh_relation_graph", source)
        self.assertIn("def _filter_relation_graph_for_mode", source)
        self.assertIn('allowed = {"character", "organization"}', source)
        self.assertIn("build_character_graph(world_items, chapters, sections_by_chapter, include_inferred)", source)
        self.assertIn("build_event_graph(world_items, chapters, sections_by_chapter, include_inferred)", source)
        self.assertIn("def _open_world_item_from_graph", source)
        self.assertIn("def save_selected_relation_graph_item", source)
        self.assertIn("def _relation_graph_allowed_save_kinds", source)
        self.assertIn('return {"character", "organization"}', source)
        self.assertIn("def _relation_graph_kind_label", source)
        self.assertIn('"保存为资料库条目"', source)
        self.assertIn("这是推断节点，尚未写入资料库", source)
        self.assertIn("这是缺失引用节点，资料库中尚无对应条目", source)
        self.assertIn('"created_from": str(node.get("source", ""))', source)
        self.assertIn("normalize_character_card_details(details)", source)
        self.assertIn('"关系图生成"', source)
        self.assertIn("def _node_pen", source)
        self.assertIn('"character": "#2f80d9"', source)
        self.assertIn('"location": "#2d9a55"', source)
        self.assertIn('"organization": "#7b61d9"', source)
        self.assertIn("self.stack.setCurrentWidget(self.world_page)", source)
        self.assertIn("self._build_relation_graph_page()", source)

    def _wait_until(self, predicate) -> None:
        deadline = time.time() + 1
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("condition was not met before timeout")


if __name__ == "__main__":
    unittest.main()
