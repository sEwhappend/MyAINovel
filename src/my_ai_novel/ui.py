from __future__ import annotations

import difflib
import json
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from .app import ApplicationServices
from .exporter import export_full_book_docx
from .llm import LLMClient, load_llm_config, save_llm_config
from .models import WORLD_ITEM_KINDS
from .pipeline import NovelPipeline
from .project_files import ensure_project_structure
from .retrieval import retrieve_context
from .ui_logic import (
    API_TYPE_VALUES,
    LLM_CONFIG_FIELDS,
    PROJECT_TEXT_FIELDS,
    STATUS_LABELS,
    api_type_display_value,
    build_llm_config_from_vars,
    build_world_context_query,
    calculate_default_section_target_words,
    config_var_value,
    format_character_card_choice,
    format_export_success_message,
    format_location_choice,
    format_model_discovery_result,
    format_world_context_pack,
    latest_outline_index,
    model_scan_autofill,
    parse_lines,
    project_index_by_id,
    selected_character_card_names,
    selected_location_name,
    world_kind_label,
    world_kind_value,
)
from .ui_theme import (
    NAV_WIDTH,
    PANEL_BG,
    apply_interaction_cues,
    apply_ttk_theme,
    create_navigation_button,
    create_root,
    load_customtkinter,
    set_navigation_button_selected,
    style_listbox,
    style_text_widget,
)


class NovelDesktopUI:
    def __init__(self, services: ApplicationServices, title: str) -> None:
        self.services = services
        self.store = services.store
        self.pipeline = services.pipeline
        self.root = create_root(title)
        apply_ttk_theme(self.root)
        self.current_project_id: int | None = None
        self.current_chapter_id: int | None = None
        self.current_section_id: int | None = None
        self.current_world_item_id: int | None = None
        self.current_world_details_json = ""
        self.current_version_ids: list[int] = []
        self._async_busy = False
        self.automation_cancel_event: threading.Event | None = None
        self._build()
        self.refresh_projects()

    def run(self) -> None:
        self.root.mainloop()

    def _build(self) -> None:
        self.status_var = tk.StringVar(value="就绪")
        header = ttk.Frame(self.root, padding=(14, 12), style="Header.TFrame")
        header.pack(fill="x", padx=10, pady=(10, 8))
        ttk.Label(header, text="My AI Novel", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="结构化小说生产流水线",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(12, 0), pady=(4, 0))
        shell = ttk.Frame(self.root)
        shell.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.navigation_frame = self._create_navigation_frame(shell)
        self.navigation_frame.pack(side="left", fill="y", padx=(0, 10))
        self.notebook = ttk.Notebook(shell, style="Hidden.TNotebook")
        self.notebook.pack(side="left", fill="both", expand=True)
        apply_interaction_cues(self.notebook)
        self.nav_buttons: list[tk.Widget] = []
        self.nav_pages: list[ttk.Frame] = []
        self._build_project_tab()
        self._build_outline_tab()
        self._build_world_tab()
        self._build_structure_tab()
        self._build_writing_tab()
        self._build_settings_tab()
        self._build_logs_tab()
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self._sync_navigation_selection())
        self._sync_navigation_selection()
        ttk.Label(self.root, textvariable=self.status_var, anchor="w", style="Status.TLabel").pack(
            fill="x", padx=10, pady=(0, 10)
        )

    def _create_navigation_frame(self, parent: tk.Widget) -> tk.Widget:
        ctk = load_customtkinter()
        frame = ctk.CTkFrame(parent, width=NAV_WIDTH, corner_radius=16, fg_color=PANEL_BG)
        frame.pack_propagate(False)
        ctk.CTkLabel(
            frame,
            text="工作台",
            text_color="#5f6f89",
            font=("Microsoft YaHei UI", 12, "bold"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(16, 8))
        return frame

    def _add_page(self, frame: ttk.Frame, text: str) -> None:
        self.notebook.add(frame, text=text)
        index = len(self.nav_pages)
        button = create_navigation_button(
            self.navigation_frame,
            text,
            lambda page_index=index: self._select_navigation_page(page_index),
        )
        button.pack(fill="x", padx=12, pady=3)
        self.nav_pages.append(frame)
        self.nav_buttons.append(button)

    def _select_navigation_page(self, index: int) -> None:
        if 0 <= index < len(self.nav_pages):
            self.notebook.select(self.nav_pages[index])
            self._sync_navigation_selection()

    def _sync_navigation_selection(self) -> None:
        if not getattr(self, "nav_pages", None):
            return
        selected = self.notebook.select()
        for index, page in enumerate(self.nav_pages):
            set_navigation_button_selected(self.nav_buttons[index], str(page) == selected)

    def _build_project_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self._add_page(tab, "项目")
        left = ttk.Frame(tab)
        left.pack(side="left", fill="y")
        right_outer = ttk.Frame(tab)
        right_outer.pack(side="left", fill="both", expand=True, padx=(12, 0))
        right = self._scrollable_frame(right_outer)
        self.project_list = tk.Listbox(left, width=28)
        self.project_list.pack(fill="y", expand=True)
        self.project_list.bind("<<ListboxSelect>>", lambda _e: self.select_project())
        ttk.Button(left, text="新建项目", command=self.start_new_project).pack(fill="x", pady=(8, 0))
        ttk.Button(left, text="刷新", command=self.refresh_projects).pack(fill="x", pady=(8, 0))

        self.project_fields = {}
        for label, key in [
            ("项目名称", "title"),
            ("题材", "genre"),
            ("写作风格", "style"),
            ("目标读者", "target_readers"),
            ("总目标字数/篇幅", "length_target"),
            ("预计全书小节数", "estimated_total_sections"),
            ("默认每小节目标字数", "default_section_target_words"),
            ("叙事视角", "pov"),
        ]:
            row = ttk.Frame(right)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=12).pack(side="left")
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
            self.project_fields[key] = var
        self.project_texts = {}
        for label, key in PROJECT_TEXT_FIELDS:
            ttk.Label(right, text=label).pack(anchor="w", pady=(8, 0))
            text = tk.Text(right, height=4, wrap="word")
            text.pack(fill="x")
            self.project_texts[key] = text
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="打开项目文件夹", command=self.open_project_folder).pack(side="right", padx=(4, 0))
        ttk.Button(actions, text="导出全书 Word", command=self.export_full_book_word).pack(side="right", padx=(4, 0))
        ttk.Button(actions, text="保存项目", command=self.save_project).pack(side="right")
        self._style_widgets(tab)

    def _build_outline_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self._add_page(tab, "总框架")
        ttk.Button(tab, text="丰满总体框架", command=self.expand_outline).pack(anchor="w")
        ttk.Button(tab, text="保存当前总框架修改", command=self.save_current_outline).pack(anchor="w", pady=(4, 0))
        ttk.Button(tab, text="确认并拆分章节", command=self.confirm_outline_split).pack(anchor="w", pady=(4, 8))
        ttk.Button(tab, text="删除总框架版本", command=self.delete_selected_outline_version).pack(anchor="w", pady=(0, 8))
        panes = ttk.PanedWindow(tab, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=2)
        ttk.Label(left, text="总框架版本").pack(anchor="w")
        self.outline_versions = tk.Listbox(left, height=18)
        self.outline_versions.pack(fill="both", expand=True, pady=(4, 0))
        ttk.Label(right, text="总框架内容").pack(anchor="w")
        self.outline_text = tk.Text(right, wrap="word")
        self.outline_text.pack(fill="both", expand=True, pady=(4, 8))
        ttk.Label(right, text="章节拆分预览").pack(anchor="w")
        self.outline_split_preview = tk.Text(right, wrap="word")
        self.outline_split_preview.pack(fill="both", expand=True, pady=(8, 0))
        self.outline_versions.bind("<<ListboxSelect>>", lambda _e: self.show_outline_version())
        self._style_widgets(tab)

    def _build_world_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self._add_page(tab, "资料库")
        top = ttk.Frame(tab)
        top.pack(fill="x")
        world_kind_values = [world_kind_label(kind) for kind in sorted(WORLD_ITEM_KINDS)]
        self.world_kind = tk.StringVar(value=world_kind_label("character"))
        ttk.Label(top, text="类型").pack(side="left")
        kind_box = ttk.Combobox(top, textvariable=self.world_kind, values=world_kind_values, width=18)
        kind_box.pack(side="left", padx=(0, 4))
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._on_world_kind_changed())
        self.world_name = tk.StringVar()
        ttk.Entry(top, textvariable=self.world_name).pack(side="left", fill="x", expand=True, padx=4)
        self.world_tags = tk.StringVar()
        ttk.Entry(top, textvariable=self.world_tags, width=24).pack(side="left", padx=4)
        ttk.Button(top, text="保存资料", command=self.save_world_item).pack(side="left")
        ttk.Button(top, text="删除资料", command=self.delete_world_item).pack(side="left", padx=(4, 0))
        ttk.Button(top, text="AI 自动补充设定", command=self.enrich_selected_world_item).pack(side="left", padx=(4, 0))
        body = ttk.PanedWindow(tab, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(8, 0))
        self.world_list = tk.Listbox(body, width=34)
        self.world_list.bind("<<ListboxSelect>>", lambda _e: self.select_world_item())
        body.add(self.world_list)
        self.world_summary = tk.Text(body, wrap="word")
        body.add(self.world_summary)
        ttk.Button(tab, text="刷新资料库", command=self.refresh_world_items).pack(anchor="e", pady=(8, 0))
        self._style_widgets(tab)

    def _build_structure_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self._add_page(tab, "章节")
        panes = ttk.PanedWindow(tab, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes)
        right_outer = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right_outer, weight=2)
        right = self._scrollable_frame(right_outer)
        self.chapter_list = tk.Listbox(left)
        self.chapter_list.pack(fill="both", expand=True)
        self.chapter_list.bind("<<ListboxSelect>>", lambda _e: self.select_chapter())
        chapter_order_bar = ttk.Frame(left)
        chapter_order_bar.pack(fill="x", pady=(8, 0))
        ttk.Button(chapter_order_bar, text="上移章节", command=self.move_chapter_up).pack(side="left", fill="x", expand=True)
        ttk.Button(chapter_order_bar, text="下移章节", command=self.move_chapter_down).pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Button(left, text="删除章节", command=self.delete_selected_chapter).pack(fill="x", pady=(4, 0))
        self.section_list = tk.Listbox(left)
        self.section_list.pack(fill="both", expand=True, pady=(8, 0))
        self.section_list.bind("<<ListboxSelect>>", lambda _e: self.select_section())
        section_order_bar = ttk.Frame(left)
        section_order_bar.pack(fill="x")
        ttk.Button(section_order_bar, text="上移小节", command=self.move_section_up).pack(side="left", fill="x", expand=True)
        ttk.Button(section_order_bar, text="下移小节", command=self.move_section_down).pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Button(left, text="删除小节", command=self.delete_selected_section).pack(fill="x", pady=(4, 0))
        ttk.Button(left, text="新建章节", command=self.start_new_chapter).pack(fill="x", pady=(8, 0))
        ttk.Button(left, text="刷新章节", command=self.refresh_structure).pack(fill="x", pady=(8, 0))
        self.structure_auto_next_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text="自动切换到下一节写作", variable=self.structure_auto_next_enabled).pack(fill="x", pady=(8, 0))
        self.structure_auto_next_chapter_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            left,
            text="自动切换到下一章写作",
            variable=self.structure_auto_next_chapter_enabled,
        ).pack(fill="x", pady=(4, 0))
        ttk.Button(left, text="从当前小节开始自动化写作", command=self.start_chapter_automation).pack(fill="x", pady=(8, 0))
        ttk.Button(left, text="中断自动化写作", command=self.interrupt_chapter_automation).pack(fill="x", pady=(4, 0))
        ttk.Button(left, text="总结本章并更新资料库", command=self.write_current_chapter_memory).pack(fill="x", pady=(4, 0))

        self.structure_fields = {}
        for label, key in [
            ("标题", "title"),
            ("时间", "story_time"),
            ("地点（优先从资料库选择，也可手动输入）", "location"),
            ("人物(每行一个)", "characters"),
            ("目标", "goal"),
            ("场景", "scene"),
            ("冲突", "conflict"),
            ("情绪变化", "emotion_shift"),
            ("必须发生(每行一个)", "must_happen"),
            ("禁止内容(每行一个)", "forbidden"),
            ("目标字数", "target_words"),
        ]:
            ttk.Label(right, text=label).pack(anchor="w")
            if key in {"characters", "must_happen", "forbidden", "goal", "scene", "conflict", "emotion_shift"}:
                widget = tk.Text(right, height=3, wrap="word")
                widget.pack(fill="x", pady=(0, 4))
            else:
                var = tk.StringVar()
                widget = ttk.Entry(right, textvariable=var)
                widget.var = var
                widget.pack(fill="x", pady=(0, 4))
            self.structure_fields[key] = widget
            if key == "location":
                self._build_location_selector(right)
            if key == "characters":
                self._build_character_card_selector(right)
        bar = ttk.Frame(right)
        bar.pack(fill="x")
        ttk.Button(bar, text="保存为章节", command=self.save_chapter_from_form).pack(side="left")
        ttk.Button(bar, text="保存为小节", command=self.save_section_from_form).pack(side="left", padx=4)
        ttk.Button(bar, text="生成章节架构", command=self.generate_chapter_plan).pack(side="left", padx=4)
        ttk.Button(bar, text="生成小节规划", command=self.generate_section_plan).pack(side="left", padx=4)
        ttk.Button(bar, text="调用资料库", command=self.load_world_context).pack(side="left", padx=4)
        ttk.Label(right, text="写作参考资料").pack(anchor="w", pady=(8, 0))
        self.world_context_text = tk.Text(right, height=8, wrap="word")
        self.world_context_text.pack(fill="both", expand=True)
        self._style_widgets(tab)

    def _build_character_card_selector(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 4))
        ttk.Label(row, text="资料库角色卡").pack(side="left")
        ttk.Button(row, text="刷新角色卡", command=self.refresh_character_cards).pack(side="right")
        ttk.Button(row, text="使用选中角色卡", command=self.apply_selected_character_cards).pack(side="right", padx=(0, 4))
        self.character_card_rows = []
        self.character_card_list = tk.Listbox(parent, height=4, selectmode="extended")
        self.character_card_list.pack(fill="x", pady=(0, 4))

    def _build_location_selector(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 4))
        ttk.Label(row, text="资料库地点设定（优先从资料库选择）").pack(side="left")
        ttk.Button(row, text="刷新地点设定", command=self.refresh_location_items).pack(side="right")
        ttk.Button(row, text="使用选中地点", command=self.apply_selected_location_item).pack(side="right", padx=(0, 4))
        self.location_rows = []
        self.location_list = tk.Listbox(parent, height=3)
        self.location_list.pack(fill="x", pady=(0, 4))

    def _build_writing_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.writing_tab = tab
        self._add_page(tab, "写作")
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        for text, command in [
            ("生成正文(粗稿)", self.write_draft),
            ("审稿", self.review_selected_version),
            ("按意见改写", self.rewrite_selected_version),
            ("锁定定稿", self.finalize_selected_version),
            ("取消定稿", self.unfinalize_current_section),
            ("继续下一节", self.continue_next_section),
            ("比较版本", self.diff_versions),
            ("删除版本", self.delete_selected_version),
        ]:
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=(0, 4))
        self.rewrite_mode = tk.StringVar(value="全文改写")
        ttk.Combobox(
            bar,
            textvariable=self.rewrite_mode,
            values=["全文改写", "只改对白", "只改心理", "只改结尾", "增强冲突", "压缩", "扩写", "润色"],
            width=12,
        ).pack(side="left")
        self.writing_auto_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="自动化", variable=self.writing_auto_enabled).pack(side="left", padx=(8, 0))
        body = self._scrollable_frame(tab)
        direction_frame = ttk.Frame(body)
        direction_frame.pack(fill="x", pady=(8, 0))
        ttk.Label(direction_frame, text="AI 修改方向").pack(side="left")
        self.rewrite_direction = tk.StringVar(value="")
        ttk.Entry(direction_frame, textvariable=self.rewrite_direction).pack(side="left", fill="x", expand=True, padx=(6, 0))
        columns = ttk.Frame(body)
        columns.pack(fill="both", expand=True, pady=(8, 0))
        left_column = ttk.Frame(columns)
        left_column.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right_column = ttk.Frame(columns)
        right_column.pack(side="left", fill="both", expand=True, padx=(6, 0))
        ttk.Label(left_column, text="版本列表").pack(anchor="w")
        self.version_list = tk.Listbox(left_column, height=8, selectmode="extended")
        self.version_list.pack(fill="both", expand=True, pady=(4, 0))
        self.version_list.bind("<<ListboxSelect>>", lambda _e: self.show_selected_version())
        self.version_text_title = tk.StringVar(value="")
        ttk.Label(right_column, textvariable=self.version_text_title).pack(anchor="w")
        self.version_text = tk.Text(right_column, wrap="word", height=24)
        self.version_text.pack(fill="both", expand=True, pady=(4, 0))
        ttk.Label(body, text="当前流式生成内容").pack(anchor="w", pady=(8, 0))
        self.current_generation_text = tk.Text(body, wrap="word", height=10)
        self.current_generation_text.pack(fill="both", expand=True, pady=(4, 0))
        self._style_widgets(tab)

    def _scrollable_frame(self, parent: tk.Widget) -> ttk.Frame:
        canvas = tk.Canvas(parent, highlightthickness=0, background=PANEL_BG)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, style="Panel.TFrame")
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def update_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_width(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        content.bind("<Configure>", update_region)
        canvas.bind("<Configure>", update_width)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return content

    def _build_settings_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self._add_page(tab, "设置")
        self.config_vars = {}
        config = load_llm_config()
        for label, key in LLM_CONFIG_FIELDS:
            if key == "model_candidates":
                ttk.Label(tab, text=label).pack(anchor="w", pady=(8, 2))
                text = tk.Text(tab, height=4, wrap="word")
                text.insert("1.0", "" if config.get(key) is None else str(config.get(key, "")))
                text.pack(fill="x")
                self.config_vars[key] = text
                continue
            row = ttk.Frame(tab)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=20).pack(side="left")
            if key == "api_type":
                var = tk.StringVar(value=api_type_display_value(config.get(key)))
                ttk.Combobox(row, textvariable=var, values=API_TYPE_VALUES, state="readonly").pack(
                    side="left", fill="x", expand=True
                )
                self.config_vars[key] = var
                continue
            var = tk.StringVar(value="" if config.get(key) is None else str(config.get(key, "")))
            show = "*" if key == "api_key" else ""
            ttk.Entry(row, textvariable=var, show=show).pack(side="left", fill="x", expand=True)
            self.config_vars[key] = var
            if key == "proxy_url":
                ttk.Label(tab, text="HTTP 代理格式示例：http://127.0.0.1:7890").pack(anchor="w", padx=144)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="保存配置", command=self.save_llm_settings).pack(side="right")
        ttk.Button(actions, text="测试连接", command=self.test_llm_connection).pack(side="right", padx=(0, 4))
        ttk.Button(actions, text="扫描模型", command=self.scan_llm_models).pack(side="right", padx=(0, 4))
        ttk.Label(tab, text="可用模型").pack(anchor="w", pady=(10, 2))
        self.model_scan_text = tk.Text(tab, height=8, wrap="word")
        self.model_scan_text.pack(fill="both", expand=True)
        self._style_widgets(tab)

    def _build_logs_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self._add_page(tab, "日志")
        ttk.Button(tab, text="刷新日志", command=self.refresh_logs).pack(anchor="w")
        self.logs_text = tk.Text(tab, wrap="word")
        self.logs_text.pack(fill="both", expand=True, pady=(8, 0))
        self._style_widgets(tab)

    def _style_widgets(self, parent: tk.Widget) -> None:
        for child in parent.winfo_children():
            if isinstance(child, tk.Text):
                style_text_widget(child)
            elif isinstance(child, tk.Listbox):
                style_listbox(child)
            elif isinstance(child, tk.Canvas):
                child.configure(background=PANEL_BG)
            apply_interaction_cues(child)
            self._style_widgets(child)

    def refresh_projects(self) -> None:
        previous_project_id = getattr(self, "current_project_id", None)
        rebuild_cache = getattr(self.store, "rebuild_cache_from_project_files", None)
        if callable(rebuild_cache):
            rebuild_cache()
        self.projects = self.store.list_projects()
        self.project_list.delete(0, tk.END)
        for project in self.projects:
            self.project_list.insert(tk.END, f"{project['id']} | {project['title']}")
        if previous_project_id and project_index_by_id(self.projects, previous_project_id) is None:
            self.current_project_id = None
            self.current_chapter_id = None
            self.current_section_id = None
            self.current_world_item_id = None
            self.current_version_ids = []
            self._clear_project_form()
            self._clear_project_views()
            self._ok("当前项目文件夹已不存在，已从列表移除")

    def select_project_by_id(self, project_id: int | None) -> bool:
        index = project_index_by_id(self.projects, project_id)
        if index is None:
            return False
        self.project_list.selection_clear(0, tk.END)
        self.project_list.selection_set(index)
        self.project_list.activate(index)
        self.project_list.see(index)
        self.select_project()
        return True

    def select_project(self) -> None:
        selection = self.project_list.curselection()
        if not selection:
            return
        project = self.projects[selection[0]]
        self.current_project_id = project["id"]
        self.current_chapter_id = None
        self.current_section_id = None
        self.current_world_item_id = None
        self.current_version_ids = []
        for key, var in self.project_fields.items():
            var.set(project.get(key, ""))
        for key, text in self.project_texts.items():
            text.delete("1.0", tk.END)
            text.insert("1.0", project.get(key, ""))
        self._clear_project_views()
        self.refresh_all_project_views()

    def start_new_project(self) -> None:
        self.current_project_id = None
        self.current_chapter_id = None
        self.current_section_id = None
        self.current_world_item_id = None
        self.current_version_ids = []
        self._clear_project_form()
        self._clear_project_views()
        if hasattr(self, "project_list"):
            self.project_list.selection_clear(0, tk.END)
        self._ok("已切换到新建项目")

    def _clear_project_form(self) -> None:
        for var in self.project_fields.values():
            var.set("")
        for text in self.project_texts.values():
            text.delete("1.0", tk.END)

    def _clear_project_views(self) -> None:
        self.outline_version_rows = []
        self.world_rows = []
        self.current_world_item_id = None
        self.current_world_details_json = ""
        self.chapter_rows = []
        self.section_rows = []
        self.version_rows = []
        self.character_card_rows = []
        self.location_rows = []
        for attr in [
            "outline_versions",
            "world_list",
            "chapter_list",
            "section_list",
            "version_list",
            "character_card_list",
            "location_list",
        ]:
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.delete(0, tk.END)
        for attr in [
            "outline_text",
            "outline_split_preview",
            "world_context_text",
            "version_text",
            "current_generation_text",
            "logs_text",
        ]:
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.delete("1.0", tk.END)
        self._clear_structure_form()
        self._clear_world_form()
        if hasattr(self, "world_kind"):
            self.world_kind.set(world_kind_label("character"))

    def _clear_structure_form(self) -> None:
        for widget in getattr(self, "structure_fields", {}).values():
            if hasattr(widget, "var"):
                widget.var.set("")
            else:
                widget.delete("1.0", tk.END)

    def _clear_world_form(self, reset_kind: bool = True) -> None:
        self.current_world_item_id = None
        self.current_world_details_json = ""
        if reset_kind and hasattr(self, "world_kind"):
            self.world_kind.set(world_kind_label("character"))
        if hasattr(self, "world_name"):
            self.world_name.set("")
        if hasattr(self, "world_tags"):
            self.world_tags.set("")
        if hasattr(self, "world_summary"):
            self.world_summary.delete("1.0", tk.END)

    def save_project(self) -> None:
        data = {key: var.get() for key, var in self.project_fields.items()}
        data.update({key: text.get("1.0", tk.END).strip() for key, text in self.project_texts.items()})
        if not data["title"]:
            self._error("项目名称不能为空")
            return
        if not str(data.get("default_section_target_words", "") or "").strip():
            data["default_section_target_words"] = calculate_default_section_target_words(
                data.get("length_target"),
                data.get("estimated_total_sections"),
            )
            default_var = self.project_fields.get("default_section_target_words")
            if default_var is not None and data["default_section_target_words"]:
                default_var.set(data["default_section_target_words"])
        if self.current_project_id:
            self.store.update_project(self.current_project_id, data)
        else:
            self.current_project_id = self.store.create_project(data)
        self.refresh_projects()
        self.select_project_by_id(self.current_project_id)
        self._ok("项目已保存")

    def open_project_folder(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        project = self.store.get_project(project_id)
        if project is None:
            self._error("项目不存在")
            return
        projects_root = getattr(self.store, "projects_root", None)
        path = (
            ensure_project_structure(project, projects_root)
            if projects_root
            else ensure_project_structure(project)
        ).resolve()
        try:
            startfile = getattr(os, "startfile")
        except AttributeError:
            self._ok(f"项目文件夹：{path}")
            return
        try:
            startfile(str(path))
        except OSError:
            self._ok(f"项目文件夹：{path}")
        else:
            self._ok(f"已打开项目文件夹：{path}")

    def export_full_book_word(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        try:
            output_path = export_full_book_docx(self.store, project_id)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self._error(str(exc))
            return
        self._ok(format_export_success_message(output_path))

    def expand_outline(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        self._run_async(
            lambda: self._run_streaming_outline(project_id),
            "正在丰满总体框架，请稍候...",
            "已生成全书故事大纲",
            lambda _result: self._after_expand_outline(),
        )

    def save_current_outline(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        content = self.outline_text.get("1.0", tk.END).strip()
        if not content:
            self._error("总框架内容不能为空")
            return
        metadata = self._selected_outline_metadata()
        metadata["expanded_outline"] = content
        metadata["source"] = "manual_edit"
        version_id = self.store.save_version(
            {
                "project_id": project_id,
                "kind": "global_outline",
                "label": "手动修改总框架",
                "content": content,
                "metadata": metadata,
            }
        )
        self.refresh_outline_versions()
        self.select_outline_version_by_id(version_id)
        self._ok("当前总框架修改已保存")

    def confirm_outline_split(self) -> None:
        project_id = self._project_required()
        version_id = self._selected_outline_version()
        if not project_id or not version_id:
            self._error("请选择一个总框架版本")
            return
        self._run_async(
            lambda: self._run_streaming_outline_split(project_id, version_id),
            "正在确认并拆分章节，请稍候...",
            "已确认并拆分章节",
            lambda _result: self._after_confirm_outline_split(),
        )

    def delete_selected_outline_version(self) -> None:
        version_id = self._selected_outline_version()
        if not version_id:
            self._error("请选择一个总框架版本")
            return
        self.store.delete_version(version_id)
        self.outline_text.delete("1.0", tk.END)
        self.outline_split_preview.delete("1.0", tk.END)
        self.refresh_outline_versions()
        self.select_latest_outline_version()
        self.refresh_logs()
        self._ok("总框架版本已删除")

    def _after_confirm_outline_split(self) -> None:
        self.current_chapter_id = None
        self.current_section_id = None
        self.current_version_ids = []
        self.section_rows = []
        self.version_rows = []
        self._clear_structure_form()
        if hasattr(self, "version_list"):
            self.version_list.delete(0, tk.END)
        if hasattr(self, "version_text"):
            self.version_text.delete("1.0", tk.END)
        self._clear_current_generation_text()
        self.refresh_world_items()
        self.refresh_character_cards()
        self.refresh_location_items()
        self.refresh_structure()
        self.refresh_logs()

    def refresh_outline_versions(self) -> None:
        self.outline_versions.delete(0, tk.END)
        self.outline_version_rows = []
        if not self.current_project_id:
            return
        rows = self.store.list_versions(self.current_project_id, kind="global_outline")
        self.outline_version_rows = rows
        for index, row in enumerate(rows, 1):
            self.outline_versions.insert(tk.END, f"{index} | {row['label']} | {row['created_at']}")

    def _after_expand_outline(self) -> None:
        self.refresh_outline_versions()
        self.select_latest_outline_version()
        self.refresh_logs()

    def select_latest_outline_version(self) -> None:
        index = latest_outline_index(self.outline_version_rows)
        if index is None:
            return
        self.outline_versions.selection_clear(0, tk.END)
        self.outline_versions.selection_set(index)
        self.outline_versions.activate(index)
        self.show_outline_version()

    def select_outline_version_by_id(self, version_id: int) -> bool:
        for index, row in enumerate(getattr(self, "outline_version_rows", [])):
            if int(row.get("id", 0) or 0) == int(version_id):
                self.outline_versions.selection_clear(0, tk.END)
                self.outline_versions.selection_set(index)
                self.outline_versions.activate(index)
                self.show_outline_version()
                return True
        return False

    def show_outline_version(self) -> None:
        version_id = self._selected_outline_version()
        if not version_id:
            return
        row = self.store.get_version(version_id)
        self.outline_text.delete("1.0", tk.END)
        self.outline_text.insert("1.0", row.get("content", "") if row else "")

    def _selected_outline_metadata(self) -> dict[str, Any]:
        version_id = self._selected_outline_version()
        if not version_id:
            return {}
        row = self.store.get_version(version_id)
        if not row:
            return {}
        metadata = self._loads(row.get("metadata_json"))
        return metadata if isinstance(metadata, dict) else {}

    def _selected_outline_version(self) -> int | None:
        selection = self.outline_versions.curselection()
        if not selection:
            return None
        return self.outline_version_rows[selection[0]]["id"]

    def save_world_item(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        self.store.save_world_item(
            project_id,
            {
                "id": self.current_world_item_id,
                "kind": world_kind_value(self.world_kind.get()),
                "name": self.world_name.get(),
                "summary": self.world_summary.get("1.0", tk.END).strip(),
                "details_json": getattr(self, "current_world_details_json", ""),
                "tags": self.world_tags.get(),
            },
        )
        self.refresh_world_items()
        self.refresh_character_cards()
        self.refresh_location_items()
        self._ok("资料已保存")

    def delete_world_item(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        if not self.current_world_item_id:
            self._error("请先选择资料")
            return
        self.store.delete_world_item(project_id, self.current_world_item_id)
        self._clear_world_form(reset_kind=False)
        self.refresh_world_items()
        self.refresh_character_cards()
        self.refresh_location_items()
        self._ok("资料已删除")

    def _on_world_kind_changed(self) -> None:
        self._clear_world_form(reset_kind=False)
        self.refresh_world_items()

    def refresh_world_items(self) -> None:
        self.world_list.delete(0, tk.END)
        self.world_rows = []
        if not self.current_project_id:
            return
        kind = None
        if hasattr(self, "world_kind"):
            selected_kind = self.world_kind.get().strip()
            if selected_kind:
                kind = world_kind_value(selected_kind)
        self.world_rows = self.store.list_world_items(self.current_project_id, kind)
        for item in self.world_rows:
            kind_label = world_kind_label(item["kind"])
            self.world_list.insert(tk.END, f"{kind_label} | {item['name']} | {item['tags']}")

    def select_world_item(self) -> None:
        selection = self.world_list.curselection()
        if not selection:
            return
        item = self.world_rows[selection[0]]
        self.current_world_item_id = item["id"]
        self.current_world_details_json = item.get("details_json", "")
        self.world_kind.set(world_kind_label(item.get("kind", "character")))
        self.world_name.set(item.get("name", ""))
        self.world_tags.set(item.get("tags", ""))
        self.world_summary.delete("1.0", tk.END)
        self.world_summary.insert("1.0", item.get("summary", ""))

    def enrich_selected_world_item(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        if not self.current_world_item_id:
            self._error("请先选择或保存一个资料条目")
            return
        item_id = int(self.current_world_item_id)
        self._run_async(
            lambda: self.pipeline.enrich_world_item(project_id, item_id),
            "正在自动补充资料设定，请稍候...",
            "资料设定补充完成",
            self._after_enrich_world_item,
        )

    def _after_enrich_world_item(self, result: dict[str, Any]) -> str:
        item = result.get("world_item", {}) if isinstance(result, dict) else {}
        if not isinstance(item, dict):
            return "资料设定补充完成"
        self.current_world_item_id = int(item.get("id", self.current_world_item_id) or 0) or self.current_world_item_id
        self.current_world_details_json = json.dumps(item.get("details", {}), ensure_ascii=False, indent=2)
        self.world_kind.set(world_kind_label(str(item.get("kind", "character"))))
        self.world_name.set(str(item.get("name", "")))
        self.world_tags.set(str(item.get("tags", "")))
        self.world_summary.delete("1.0", tk.END)
        self.world_summary.insert("1.0", str(item.get("summary", "")))
        self.refresh_logs()
        return "资料设定补充完成，请确认后点击“保存资料”"

    def refresh_structure(self) -> None:
        self.chapter_list.delete(0, tk.END)
        self.section_list.delete(0, tk.END)
        self.chapter_rows = []
        self.section_rows = []
        if not self.current_project_id:
            return
        self.chapter_rows = self.store.list_chapters(self.current_project_id)
        for chapter in self.chapter_rows:
            status = STATUS_LABELS.get(chapter["status"], chapter["status"])
            self.chapter_list.insert(tk.END, f"{chapter['number']}. {chapter['title']} | {status}")

    def refresh_character_cards(self) -> None:
        if not hasattr(self, "character_card_list"):
            return
        self.character_card_list.delete(0, tk.END)
        self.character_card_rows = []
        if not self.current_project_id:
            return
        self.character_card_rows = self.store.list_world_items(self.current_project_id, "character")
        for item in self.character_card_rows:
            self.character_card_list.insert(tk.END, format_character_card_choice(item))

    def refresh_location_items(self) -> None:
        if not hasattr(self, "location_list"):
            return
        self.location_list.delete(0, tk.END)
        self.location_rows = []
        if not self.current_project_id:
            return
        self.location_rows = self.store.list_world_items(self.current_project_id, "location")
        for item in self.location_rows:
            self.location_list.insert(tk.END, format_location_choice(item))

    def apply_selected_character_cards(self) -> None:
        selected = self.character_card_list.curselection()
        names = selected_character_card_names(self.character_card_rows, selected)
        if not names:
            self._error("请选择资料库角色卡")
            return
        widget = self.structure_fields["characters"]
        widget.delete("1.0", tk.END)
        widget.insert("1.0", "\n".join(names))
        self._ok("已选择角色卡")

    def apply_selected_location_item(self) -> None:
        selected = self.location_list.curselection()
        name = selected_location_name(self.location_rows, selected)
        if not name:
            self._error("请选择资料库地点设定")
            return
        widget = self.structure_fields["location"]
        widget.var.set(name)
        self._ok("已选择地点设定")

    def select_chapter(self) -> None:
        selection = self.chapter_list.curselection()
        if not selection:
            return
        chapter = self.chapter_rows[selection[0]]
        self.current_chapter_id = chapter["id"]
        self.current_section_id = None
        self._fill_structure_form(chapter, is_section=False)
        default_words = self._project_default_section_target_words()
        if default_words:
            self._set_structure_value("target_words", default_words)
        self.section_list.delete(0, tk.END)
        self.section_rows = self.store.list_sections(chapter["id"])
        for section in self.section_rows:
            status = STATUS_LABELS.get(section["status"], section["status"])
            self.section_list.insert(tk.END, f"{section['number']}. {section['title']} | {status}")

    def select_chapter_by_id(self, chapter_id: int) -> bool:
        for index, chapter in enumerate(self.chapter_rows):
            if int(chapter.get("id", 0) or 0) == int(chapter_id):
                self.chapter_list.selection_clear(0, tk.END)
                self.chapter_list.selection_set(index)
                self.chapter_list.activate(index)
                self.chapter_list.see(index)
                self.select_chapter()
                return True
        return False

    def move_chapter_up(self) -> None:
        self._move_selected_chapter(-1)

    def move_chapter_down(self) -> None:
        self._move_selected_chapter(1)

    def _move_selected_chapter(self, direction: int) -> None:
        project_id = self._project_required()
        selection = self.chapter_list.curselection() if hasattr(self, "chapter_list") else ()
        if not project_id:
            return
        if not selection:
            self._error("请选择章节")
            return
        chapter = self.chapter_rows[selection[0]]
        chapter_id = int(chapter["id"])
        try:
            self.store.move_chapter(project_id, chapter_id, direction)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self._error(str(exc))
            return
        self.current_section_id = None
        self.refresh_structure()
        self.select_chapter_by_id(chapter_id)
        self._ok("章节顺序已更新")

    def delete_selected_chapter(self) -> None:
        project_id = self._project_required()
        selection = self.chapter_list.curselection() if hasattr(self, "chapter_list") else ()
        if not project_id:
            return
        if not selection:
            self._error("请选择章节")
            return
        chapter_id = int(self.chapter_rows[selection[0]]["id"])
        try:
            self.store.delete_chapter(project_id, chapter_id)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self._error(str(exc))
            return
        self.current_chapter_id = None
        self.current_section_id = None
        self.current_version_ids = []
        self.section_rows = []
        self.version_rows = []
        self._clear_structure_form()
        if hasattr(self, "version_list"):
            self.version_list.delete(0, tk.END)
        if hasattr(self, "version_text"):
            self.version_text.delete("1.0", tk.END)
        self._clear_current_generation_text()
        self.refresh_structure()
        self._ok("章节已删除")

    def start_new_chapter(self) -> None:
        if not self.current_project_id:
            self._error("请先创建或选择项目")
            return
        self.current_chapter_id = None
        self.current_section_id = None
        self.current_version_ids = []
        self.section_rows = []
        self.version_rows = []
        self._clear_structure_form()
        if hasattr(self, "chapter_list"):
            self.chapter_list.selection_clear(0, tk.END)
        if hasattr(self, "section_list"):
            self.section_list.delete(0, tk.END)
        if hasattr(self, "version_list"):
            self.version_list.delete(0, tk.END)
        if hasattr(self, "version_text"):
            self.version_text.delete("1.0", tk.END)
        self._clear_current_generation_text()
        self._ok("已切换到新建章节")

    def select_section(self) -> None:
        selection = self.section_list.curselection()
        if not selection:
            return
        section = self.section_rows[selection[0]]
        self.current_section_id = section["id"]
        self._fill_structure_form(section, is_section=True)
        self.refresh_versions()

    def select_section_by_id(self, section_id: int) -> bool:
        for index, section in enumerate(self.section_rows):
            if int(section.get("id", 0) or 0) == int(section_id):
                self.section_list.selection_clear(0, tk.END)
                self.section_list.selection_set(index)
                self.section_list.activate(index)
                self.section_list.see(index)
                self.select_section()
                return True
        return False

    def move_section_up(self) -> None:
        self._move_selected_section(-1)

    def move_section_down(self) -> None:
        self._move_selected_section(1)

    def _move_selected_section(self, direction: int) -> None:
        if not self.current_chapter_id:
            self._error("请先选择章节")
            return
        selection = self.section_list.curselection() if hasattr(self, "section_list") else ()
        if not selection:
            self._error("请选择小节")
            return
        section_id = int(self.section_rows[selection[0]]["id"])
        try:
            self.store.move_section(self.current_chapter_id, section_id, direction)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self._error(str(exc))
            return
        self.select_chapter_by_id(self.current_chapter_id)
        self.select_section_by_id(section_id)
        self._ok("小节顺序已更新")

    def delete_selected_section(self) -> None:
        if not self.current_chapter_id:
            self._error("请先选择章节")
            return
        selection = self.section_list.curselection() if hasattr(self, "section_list") else ()
        if not selection:
            self._error("请选择小节")
            return
        section_id = int(self.section_rows[selection[0]]["id"])
        try:
            self.store.delete_section(section_id)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self._error(str(exc))
            return
        chapter_id = self.current_chapter_id
        self.current_section_id = None
        self.current_version_ids = []
        self.version_rows = []
        if hasattr(self, "version_list"):
            self.version_list.delete(0, tk.END)
        if hasattr(self, "version_text"):
            self.version_text.delete("1.0", tk.END)
        self._clear_current_generation_text()
        self.select_chapter_by_id(chapter_id)
        self._ok("小节已删除")

    def _fill_structure_form(self, row: dict[str, Any], is_section: bool) -> None:
        for key, widget in self.structure_fields.items():
            value = row.get(key, "")
            if key == "characters":
                value = "\n".join(self._loads(row.get("characters_json")) or [])
            if key == "must_happen":
                value = "\n".join(self._loads(row.get("must_happen_json")) or [])
            if key == "forbidden":
                value = "\n".join(self._loads(row.get("forbidden_json")) or [])
            self._set_structure_value(key, str(value or ""))

    def save_chapter_from_form(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        number = len(self.store.list_chapters(project_id)) + 1
        data = self._structure_data()
        data["number"] = number if not self.current_chapter_id else self.store.get_chapter(self.current_chapter_id)["number"]
        if self.current_chapter_id:
            data["id"] = self.current_chapter_id
        self.current_chapter_id = self.store.save_chapter(project_id, data)
        self.refresh_structure()
        self._ok("章节已保存")

    def save_section_from_form(self) -> None:
        if not self.current_chapter_id:
            self._error("请先选择章节")
            return
        number = len(self.store.list_sections(self.current_chapter_id)) + 1
        data = self._structure_data()
        data["number"] = number if not self.current_section_id else self.store.get_section(self.current_section_id)["number"]
        if self.current_section_id:
            data["id"] = self.current_section_id
        self.current_section_id = self.store.save_section(self.current_chapter_id, data)
        self.select_chapter()
        self._ok("小节已保存")

    def _structure_data(self) -> dict[str, Any]:
        target_words = self._structure_value("target_words") or self._project_default_section_target_words() or "1200"
        return {
            "title": self._structure_value("title"),
            "story_time": self._structure_value("story_time"),
            "location": self._structure_value("location"),
            "characters": parse_lines(self._structure_value("characters")),
            "goal": self._structure_value("goal"),
            "scene": self._structure_value("scene"),
            "conflict": self._structure_value("conflict"),
            "emotion_shift": self._structure_value("emotion_shift"),
            "must_happen": parse_lines(self._structure_value("must_happen")),
            "forbidden": parse_lines(self._structure_value("forbidden")),
            "target_words": int(target_words or 1200),
            "status": "planned",
        }

    def _structure_value(self, key: str) -> str:
        widget = self.structure_fields[key]
        return widget.var.get().strip() if hasattr(widget, "var") else widget.get("1.0", tk.END).strip()

    def _set_structure_value(self, key: str, value: str) -> None:
        widget = self.structure_fields[key]
        if hasattr(widget, "var"):
            widget.var.set(value)
        else:
            widget.delete("1.0", tk.END)
            widget.insert("1.0", value)

    def _project_default_section_target_words(self) -> str:
        if "default_section_target_words" in getattr(self, "project_fields", {}):
            value = self.project_fields["default_section_target_words"].get().strip()
            if value:
                return value
        if not self.current_project_id or not hasattr(self.store, "get_project"):
            return ""
        project = self.store.get_project(self.current_project_id) or {}
        return str(project.get("default_section_target_words", "") or "").strip()

    def load_world_context(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        values = {key: self._structure_value(key) for key in self.structure_fields}
        query = build_world_context_query(values)
        if not query:
            self._error("请先填写或选择章节/小节信息")
            return
        pack = retrieve_context(
            self.store,
            project_id,
            self.current_chapter_id,
            self.current_section_id,
            query,
            llm=None,
        )
        self.world_context_text.delete("1.0", tk.END)
        self.world_context_text.insert("1.0", format_world_context_pack(pack))
        self._ok("资料库参考已加载")

    def generate_chapter_plan(self) -> None:
        project_id = self._project_required()
        if project_id and self.current_chapter_id:
            self._run_async(
                lambda: self.pipeline.generate_chapter_plan(project_id, self.current_chapter_id),
                "正在生成章节架构，请稍候...",
                "章节架构已生成",
                lambda _result: self._after_structure_generation(),
            )

    def generate_section_plan(self) -> None:
        project_id = self._project_required()
        if project_id and self.current_section_id:
            self._run_async(
                lambda: self.pipeline.generate_section_plan(project_id, self.current_section_id),
                "正在生成小节规划，请稍候...",
                "小节规划已生成",
                lambda _result: self._after_structure_generation(),
            )

    def _after_structure_generation(self) -> None:
        self.refresh_structure()
        self.refresh_logs()

    def write_draft(self) -> None:
        project_id = self._project_required()
        if project_id and self.current_section_id:
            section_id = self.current_section_id
            rewrite_mode = self.rewrite_mode.get()
            rewrite_direction_var = getattr(self, "rewrite_direction", None)
            rewrite_direction = rewrite_direction_var.get().strip() if rewrite_direction_var else ""
            if getattr(self, "writing_auto_enabled", None) and self.writing_auto_enabled.get():
                cancel_event = threading.Event()
                self.automation_cancel_event = cancel_event
                self._run_async(
                    lambda: self._run_single_writing_automation(
                        project_id,
                        section_id,
                        rewrite_mode,
                        cancel_event,
                        direction=rewrite_direction,
                    ),
                    "正在自动生成、审稿、改写并定稿，请稍候...",
                    "自动化写作完成",
                    self._after_writing_automation,
                )
                return
            self._run_async(
                lambda: self._run_streaming_draft(project_id, section_id),
                "正在生成正文，请稍候...",
                "粗稿已生成",
                lambda _result: self._after_writing_task(),
            )

    def review_selected_version(self) -> None:
        project_id = self._project_required()
        version_id = self._single_selected_version()
        if project_id and self.current_section_id and version_id:
            self._run_async(
                lambda: self.pipeline.review_section(project_id, self.current_section_id, version_id),
                "正在审稿，请稍候...",
                "审稿完成",
                lambda _result: self._after_writing_task(),
            )

    def rewrite_selected_version(self) -> None:
        project_id = self._project_required()
        selected = self._selected_versions()
        if not project_id or not self.current_section_id or len(selected) < 2:
            self._error("请选择一个正文版本和一个审稿版本")
            return
        self._run_async(
            lambda: self.pipeline.rewrite_section(
                project_id,
                self.current_section_id,
                selected[0],
                selected[1],
                self.rewrite_mode.get(),
                [],
                self.rewrite_direction.get().strip() if getattr(self, "rewrite_direction", None) else "",
            ),
            "正在按意见改写，请稍候...",
            "改写完成",
            lambda _result: self._after_writing_task(),
        )

    def _after_writing_task(self) -> None:
        self._refresh_structure_preserving_selection()
        self.refresh_logs()

    def _run_streaming_outline(self, project_id: int) -> dict[str, Any]:
        self._schedule_outline_streaming_reset()

        def on_delta(delta: str) -> None:
            if delta:
                self._schedule_outline_streaming_append(delta)

        if hasattr(self.pipeline, "expand_global_concept_streaming"):
            return self.pipeline.expand_global_concept_streaming(project_id, on_delta)
        result = self.pipeline.expand_global_concept(project_id)
        content = str(result.get("expanded_outline", "") or "")
        if content:
            on_delta(content)
        return result

    def _schedule_outline_streaming_reset(self) -> None:
        if not hasattr(self, "root"):
            self._reset_outline_streaming_text()
            return
        self.root.after(0, self._reset_outline_streaming_text)

    def _schedule_outline_streaming_append(self, delta: str) -> None:
        if not hasattr(self, "root"):
            self._append_outline_streaming_text(delta)
            return
        self.root.after(0, lambda delta=delta: self._append_outline_streaming_text(delta))

    def _reset_outline_streaming_text(self) -> None:
        if hasattr(self, "outline_text"):
            self.outline_text.delete("1.0", tk.END)

    def _append_outline_streaming_text(self, delta: str) -> None:
        if hasattr(self, "outline_text"):
            self.outline_text.insert(tk.END, delta)
            if hasattr(self.outline_text, "see"):
                self.outline_text.see(tk.END)

    def _run_streaming_outline_split(self, project_id: int, version_id: int) -> dict[str, Any]:
        self._schedule_outline_split_preview_reset()

        def on_delta(delta: str) -> None:
            if delta:
                self._schedule_outline_split_preview_append(delta)

        if hasattr(self.pipeline, "confirm_outline_split_streaming"):
            return self.pipeline.confirm_outline_split_streaming(project_id, version_id, on_delta)
        on_delta("当前 pipeline 不支持流式章节拆分，使用非流式降级。\n")
        return self.pipeline.confirm_outline_split(project_id, version_id)

    def _schedule_outline_split_preview_reset(self) -> None:
        if not hasattr(self, "root"):
            self._reset_outline_split_preview()
            return
        self.root.after(0, self._reset_outline_split_preview)

    def _schedule_outline_split_preview_append(self, delta: str) -> None:
        if not hasattr(self, "root"):
            self._append_outline_split_preview(delta)
            return
        self.root.after(0, lambda delta=delta: self._append_outline_split_preview(delta))

    def _reset_outline_split_preview(self) -> None:
        if hasattr(self, "outline_split_preview"):
            self.outline_split_preview.delete("1.0", tk.END)

    def _append_outline_split_preview(self, delta: str) -> None:
        if hasattr(self, "outline_split_preview"):
            self.outline_split_preview.insert(tk.END, delta)
            if hasattr(self.outline_split_preview, "see"):
                self.outline_split_preview.see(tk.END)

    def _run_streaming_draft(self, project_id: int, section_id: int) -> dict[str, Any]:
        self._schedule_streaming_text_reset()

        def on_delta(delta: str) -> None:
            if delta:
                self._schedule_streaming_text_append(delta)

        if hasattr(self.pipeline, "write_section_draft_streaming"):
            return self.pipeline.write_section_draft_streaming(project_id, section_id, "rough", on_delta)
        result = self.pipeline.write_section_draft(project_id, section_id, "rough")
        content = str(result.get("content", "") or "")
        if content:
            on_delta(content)
        return result

    def _schedule_streaming_text_reset(self) -> None:
        if not hasattr(self, "root"):
            self._reset_streaming_text()
            return
        self.root.after(0, self._reset_streaming_text)

    def _schedule_streaming_text_append(self, delta: str) -> None:
        if not hasattr(self, "root"):
            self._append_streaming_text(delta)
            return
        self.root.after(0, lambda delta=delta: self._append_streaming_text(delta))

    def _reset_streaming_text(self) -> None:
        target = self._streaming_text_widget()
        if target is not None:
            target.delete("1.0", tk.END)

    def _append_streaming_text(self, delta: str) -> None:
        target = self._streaming_text_widget()
        if target is not None:
            target.insert(tk.END, delta)
            if hasattr(target, "see"):
                target.see(tk.END)

    def _streaming_text_widget(self):
        return getattr(self, "current_generation_text", None) or getattr(self, "version_text", None)

    def _clear_current_generation_text(self) -> None:
        widget = getattr(self, "current_generation_text", None)
        if widget is not None:
            widget.delete("1.0", tk.END)

    def _run_writing_automation(
        self,
        project_id: int,
        section_id: int,
        rewrite_mode: str,
        cancel_event: threading.Event | None = None,
        direction: str = "",
    ) -> dict[str, Any]:
        self._raise_if_automation_cancelled(cancel_event)
        draft = self._run_streaming_draft(project_id, section_id)
        draft_version_id = int(draft["version_id"])
        self._raise_if_automation_cancelled(cancel_event)
        review = self.pipeline.review_section(project_id, section_id, draft_version_id)
        review_version_id = int(review["version_id"])
        self._raise_if_automation_cancelled(cancel_event)
        rewrite = self.pipeline.rewrite_section(
            project_id,
            section_id,
            draft_version_id,
            review_version_id,
            rewrite_mode,
            [],
            direction,
        )
        rewrite_version_id = int(rewrite["version_id"])
        self._raise_if_automation_cancelled(cancel_event)
        self.store.finalize_section(section_id, rewrite_version_id)
        self._raise_if_automation_cancelled(cancel_event)
        next_section = None
        next_message = ""
        try:
            next_section = self.pipeline.continue_next_section(section_id)
        except ValueError as exc:
            if "当前章节没有下一节" in str(exc):
                next_message = str(exc)
            else:
                raise
        return {
            "draft_version_id": draft_version_id,
            "review_version_id": review_version_id,
            "rewrite_version_id": rewrite_version_id,
            "next_section": next_section,
            "next_message": next_message,
        }

    def _run_single_writing_automation(
        self,
        project_id: int,
        section_id: int,
        rewrite_mode: str,
        cancel_event: threading.Event,
        direction: str = "",
    ) -> dict[str, Any]:
        self._configure_llm_retry(cancel_event)
        try:
            return self._run_writing_automation(project_id, section_id, rewrite_mode, cancel_event, direction)
        finally:
            if hasattr(self.services.llm, "configure_retry_until_cancel"):
                self.services.llm.configure_retry_until_cancel(None, None)

    def start_chapter_automation(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        if not self.current_chapter_id:
            self._error("请先选择章节")
            return
        if not self.current_section_id:
            self._error("请先选择小节")
            return
        if getattr(self, "_async_busy", False):
            self._error("已有后台任务运行中，请稍候")
            return
        cancel_event = threading.Event()
        self.automation_cancel_event = cancel_event
        chapter_id = int(self.current_chapter_id)
        section_id = int(self.current_section_id)
        rewrite_mode = self.rewrite_mode.get()
        rewrite_direction_var = getattr(self, "rewrite_direction", None)
        rewrite_direction = rewrite_direction_var.get().strip() if rewrite_direction_var else ""
        auto_next_chapter = bool(
            getattr(self, "structure_auto_next_chapter_enabled", None)
            and self.structure_auto_next_chapter_enabled.get()
        )
        self._run_async(
            lambda: self._run_chapter_writing_automation(
                project_id,
                chapter_id,
                section_id,
                rewrite_mode,
                cancel_event,
                auto_next_chapter,
                direction=rewrite_direction,
            ),
            "正在从当前小节开始自动化写作...",
            "章节自动化写作完成",
            self._after_chapter_automation,
        )

    def interrupt_chapter_automation(self) -> None:
        if self.automation_cancel_event is None:
            self._ok("当前没有章节自动化任务")
            return
        self.automation_cancel_event.set()
        self._ok("已请求中断自动化写作，等待当前请求结束")

    def write_current_chapter_memory(self) -> None:
        project_id = self._project_required()
        if not project_id:
            return
        if not self.current_chapter_id:
            self._error("请先选择章节")
            return
        chapter_id = int(self.current_chapter_id)
        self._run_async(
            lambda: self.pipeline.write_chapter_memory(project_id, chapter_id),
            "正在总结本章并更新资料库...",
            "本章资料库记忆已更新",
            self._after_chapter_memory_written,
        )

    def _after_chapter_memory_written(self, result: dict[str, Any]) -> str:
        self.refresh_world_items()
        self.refresh_character_cards()
        self.refresh_location_items()
        self.refresh_logs()
        count = result.get("world_items", 0) if isinstance(result, dict) else 0
        return f"本章资料库记忆已更新，共更新 {count} 条资料"

    def _run_chapter_writing_automation(
        self,
        project_id: int,
        chapter_id: int,
        start_section_id: int,
        rewrite_mode: str,
        cancel_event: threading.Event,
        auto_next_chapter: bool = False,
        direction: str = "",
    ) -> dict[str, Any]:
        processed: list[int] = []
        chapter_memory_results: list[dict[str, Any]] = []
        section_id = start_section_id
        self._configure_llm_retry(cancel_event)
        try:
            while True:
                self._raise_if_automation_cancelled(cancel_event)
                section = self.store.get_section(section_id)
                if not section:
                    raise ValueError("小节不存在")
                if int(section["chapter_id"]) != int(chapter_id):
                    break
                result = self._run_writing_automation(project_id, section_id, rewrite_mode, cancel_event, direction)
                processed.append(section_id)
                next_section = result.get("next_section")
                if not isinstance(next_section, dict):
                    chapter_memory_results.append(self._try_write_chapter_memory(project_id, chapter_id, cancel_event))
                    if auto_next_chapter:
                        next_chapter_section = self._first_section_in_next_chapter(project_id, chapter_id)
                        if next_chapter_section is not None:
                            chapter_id = int(next_chapter_section["chapter_id"])
                            section_id = int(next_chapter_section["id"])
                            continue
                    return {
                        "processed": processed,
                        "last_section_id": section_id,
                        "next_section": None,
                        "stopped": result.get("next_message", ""),
                        "chapter_memory_results": chapter_memory_results,
                    }
                next_section_id = int(next_section["id"])
                if int(next_section.get("chapter_id", chapter_id)) != int(chapter_id):
                    chapter_memory_results.append(self._try_write_chapter_memory(project_id, chapter_id, cancel_event))
                    if auto_next_chapter:
                        chapter_id = int(next_section["chapter_id"])
                        section_id = next_section_id
                        continue
                    return {
                        "processed": processed,
                        "last_section_id": section_id,
                        "next_section": next_section,
                        "stopped": "已到当前章节末尾",
                        "chapter_memory_results": chapter_memory_results,
                    }
                section_id = next_section_id
        finally:
            if hasattr(self.services.llm, "configure_retry_until_cancel"):
                self.services.llm.configure_retry_until_cancel(None, None)
        return {
            "processed": processed,
            "last_section_id": section_id,
            "next_section": None,
            "stopped": "",
            "chapter_memory_results": chapter_memory_results,
        }

    def _try_write_chapter_memory(
        self,
        project_id: int,
        chapter_id: int,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        retry_supported = hasattr(self.services.llm, "configure_retry_until_cancel")
        if retry_supported:
            self.services.llm.configure_retry_until_cancel(None, None)
        try:
            return {"ok": True, **self.pipeline.write_chapter_memory(project_id, chapter_id)}
        except Exception as exc:  # noqa: BLE001 - automation should not discard finalized prose
            return {"ok": False, "chapter_id": chapter_id, "error": str(exc)}
        finally:
            if retry_supported and cancel_event is not None and not cancel_event.is_set():
                self._configure_llm_retry(cancel_event)

    def _first_section_in_next_chapter(self, project_id: int, chapter_id: int) -> dict[str, Any] | None:
        chapters = self.store.list_chapters(project_id)
        current_index = None
        for index, chapter in enumerate(chapters):
            if int(chapter.get("id", 0) or 0) == int(chapter_id):
                current_index = index
                break
        if current_index is None:
            return None
        for chapter in chapters[current_index + 1 :]:
            sections = self.store.list_sections(int(chapter["id"]))
            if sections:
                return sections[0]
        return None

    def _configure_llm_retry(self, cancel_event: threading.Event) -> None:
        if not hasattr(self.services.llm, "configure_retry_until_cancel"):
            return

        def on_retry(attempt: int, delay: int, error: str) -> None:
            message = f"API 调用失败，{delay} 秒后第 {attempt + 1} 次重试：{error}"
            if hasattr(self, "root"):
                self.root.after(0, lambda message=message: self._ok(message))

        self.services.llm.configure_retry_until_cancel(cancel_event, on_retry)

    def _after_chapter_automation(self, result: dict[str, Any]) -> str:
        self.automation_cancel_event = None
        self.refresh_world_items()
        self.refresh_character_cards()
        self.refresh_location_items()
        self.refresh_logs()
        last_section_id = result.get("last_section_id") if isinstance(result, dict) else None
        if last_section_id:
            self._select_next_section_for_writing(int(last_section_id))
        else:
            self._refresh_structure_preserving_selection()
        processed = result.get("processed", []) if isinstance(result, dict) else []
        stopped = str(result.get("stopped", "") if isinstance(result, dict) else "").strip()
        if stopped:
            return f"章节自动化写作完成，已处理 {len(processed)} 节，{stopped}"
        return f"章节自动化写作完成，已处理 {len(processed)} 节"

    def _raise_if_automation_cancelled(self, cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("用户已中断自动化写作")

    def _after_writing_automation(self, result: dict[str, Any]) -> str:
        self.automation_cancel_event = None
        next_section = result.get("next_section") if isinstance(result, dict) else None
        if isinstance(next_section, dict):
            next_id = int(next_section["id"])
            should_switch = bool(
                getattr(self, "structure_auto_next_enabled", None)
                and self.structure_auto_next_enabled.get()
            )
            if should_switch and self._select_next_section_for_writing(next_id):
                self.refresh_logs()
                return "自动化写作完成，已切换到下一节"
            self._refresh_structure_preserving_selection()
            self.refresh_logs()
            return "自动化写作完成，下一节已满足继续条件"
        self._refresh_structure_preserving_selection()
        self.refresh_logs()
        message = str(result.get("next_message", "") if isinstance(result, dict) else "").strip()
        return f"自动化写作完成，{message}" if message else "自动化写作完成"

    def finalize_selected_version(self) -> None:
        version_id = self._single_selected_version()
        if not self.current_section_id or not version_id:
            self._error("请选择小节和版本")
            return
        self.store.finalize_section(self.current_section_id, version_id)
        self.refresh_versions()
        self.refresh_structure()
        self._ok("已锁定定稿")

    def unfinalize_current_section(self) -> None:
        if not self.current_section_id:
            self._error("请选择小节")
            return
        self.store.unfinalize_section(self.current_section_id)
        self.refresh_versions()
        self.refresh_structure()
        self._ok("已取消定稿")

    def continue_next_section(self) -> None:
        if not self.current_section_id:
            self._error("请选择小节")
            return
        try:
            next_section = self.pipeline.continue_next_section(self.current_section_id)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self._error(str(exc))
            return
        if self._select_next_section_for_writing(int(next_section["id"])):
            self._ok("已切换到下一节")
        else:
            self._ok("下一节已满足继续条件")

    def _select_next_section_for_writing(self, section_id: int) -> bool:
        section = self.store.get_section(section_id)
        if not section:
            return False
        chapter_id = int(section["chapter_id"])
        self.refresh_structure()
        if not self.select_chapter_by_id(chapter_id):
            return False
        if not self.select_section_by_id(section_id):
            return False
        if hasattr(self, "notebook") and hasattr(self, "writing_tab"):
            self.notebook.select(self.writing_tab)
        return True

    def refresh_versions(self) -> None:
        self.version_list.delete(0, tk.END)
        self.current_version_ids = []
        self._set_version_text_title(None)
        if hasattr(self, "version_text"):
            self.version_text.delete("1.0", tk.END)
        if not self.current_project_id or not self.current_section_id:
            return
        rows = self.store.list_versions(self.current_project_id, section_id=self.current_section_id)
        self.version_rows = rows
        for index, row in enumerate(rows, 1):
            self.current_version_ids.append(row["id"])
            self.version_list.insert(tk.END, f"{index} | {row['kind']} | {row['status']} | {row['label']}")

    def _set_version_text_title(self, row: dict[str, Any] | None, prefix: str = "版本内容") -> None:
        title = getattr(self, "version_text_title", None)
        if title is None:
            return
        if not row:
            title.set("")
            return
        version_id = int(row.get("id", 0) or 0)
        index = self.current_version_ids.index(version_id) + 1 if version_id in self.current_version_ids else "?"
        title.set(f"{prefix}：{index} | {row.get('kind', '')} | {row.get('status', '')} | {row.get('label', '')}")

    def _refresh_structure_preserving_selection(
        self,
        chapter_id: int | None = None,
        section_id: int | None = None,
    ) -> None:
        chapter_id = chapter_id if chapter_id is not None else self.current_chapter_id
        section_id = section_id if section_id is not None else self.current_section_id
        self.refresh_structure()
        if chapter_id and self.select_chapter_by_id(int(chapter_id)):
            if section_id:
                self.select_section_by_id(int(section_id))
            return
        self.refresh_versions()

    def show_selected_version(self) -> None:
        version_id = self._single_selected_version()
        if not version_id:
            self._set_version_text_title(None)
            self.version_text.delete("1.0", tk.END)
            return
        row = self.store.get_version(version_id)
        self._set_version_text_title(row)
        self.version_text.delete("1.0", tk.END)
        self.version_text.insert("1.0", row.get("content", "") if row else "")

    def diff_versions(self) -> None:
        selected = self._selected_versions()
        if len(selected) != 2:
            self._error("请选择两个版本")
            return
        a = self.store.get_version(selected[0])
        b = self.store.get_version(selected[1])
        diff = difflib.unified_diff(
            (a.get("content", "") if a else "").splitlines(),
            (b.get("content", "") if b else "").splitlines(),
            fromfile=str(selected[0]),
            tofile=str(selected[1]),
            lineterm="",
        )
        if hasattr(self, "version_text_title"):
            self.version_text_title.set(f"版本比较：{selected[0]} ↔ {selected[1]}")
        self.version_text.delete("1.0", tk.END)
        self.version_text.insert("1.0", "\n".join(diff))

    def delete_selected_version(self) -> None:
        selected = self._selected_versions()
        if not selected:
            self._error("请选择要删除的版本")
            return
        try:
            for version_id in selected:
                self.store.delete_version(version_id)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self._error(str(exc))
            self.refresh_versions()
            self.refresh_structure()
            return
        self.version_text.delete("1.0", tk.END)
        self._set_version_text_title(None)
        self.refresh_versions()
        self.refresh_structure()
        self.refresh_logs()
        self._ok(f"已删除 {len(selected)} 个版本")

    def save_llm_settings(self) -> None:
        config = self._llm_config_from_vars()
        save_llm_config(config)
        self.store.save_llm_config({**config, "api_key_ref": "llm_config"})
        self.services.llm = LLMClient(config)
        self.services.pipeline = NovelPipeline(self.store, self.services.llm)
        self.pipeline = self.services.pipeline
        self._ok("LLM 配置已保存")

    def test_llm_connection(self) -> None:
        self.save_llm_settings()
        self._run_async(
            self.services.llm.test_connection,
            "正在测试连接，请稍候...",
            "连接测试完成",
            self._after_llm_connection_test,
        )

    def _after_llm_connection_test(self, result: tuple[bool, str]) -> bool:
        ok, message = result
        self.refresh_logs()
        if ok:
            self._ok(message)
        else:
            self._error(message)
        return False

    def scan_llm_models(self) -> None:
        config = self._llm_config_from_vars()
        current = {key: config_var_value(var) for key, var in self.config_vars.items()}
        self._run_async(
            lambda: LLMClient(config).discover_models(),
            "正在扫描模型，请稍候...",
            "模型扫描完成",
            lambda discovery: self._apply_model_scan_results(current, discovery),
        )

    def _apply_model_scan_results(self, current: dict[str, str], discovery: dict[str, Any]) -> bool:
        models = [str(model) for model in discovery.get("models", []) if str(model)]
        self._show_model_scan_results(discovery)
        for key, value in model_scan_autofill(current, models).items():
            self.config_vars[key].set(value)
        warning = str(discovery.get("warning", "") or "")
        self.refresh_logs()
        self._ok(f"已扫描到 {len(models)} 个模型" + ("，有警告" if warning else ""))
        return False

    def _show_model_scan_results(self, discovery: dict[str, Any]) -> None:
        self.model_scan_text.delete("1.0", tk.END)
        self.model_scan_text.insert("1.0", format_model_discovery_result(discovery))

    def _llm_config_from_vars(self) -> dict[str, Any]:
        return build_llm_config_from_vars(self.config_vars)

    def refresh_logs(self) -> None:
        rows = self.store.list_llm_call_logs()
        self.logs_text.delete("1.0", tk.END)
        for row in rows:
            self.logs_text.insert(
                tk.END,
                f"[{row['created_at']}] {row['agent_name']} success={row['success']} error={row['error'] or ''}\n"
                f"请求：{row['request_summary']}\n响应：{row['response_summary']}\n\n",
            )

    def refresh_all_project_views(self) -> None:
        self.refresh_outline_versions()
        self.refresh_world_items()
        self.refresh_character_cards()
        self.refresh_location_items()
        self.refresh_structure()
        self.refresh_versions()
        self.refresh_logs()

    def _project_required(self) -> int | None:
        if not self.current_project_id:
            self._error("请先创建或选择项目")
            return None
        return self.current_project_id

    def _single_selected_version(self) -> int | None:
        selected = self._selected_versions()
        return selected[0] if selected else None

    def _selected_versions(self) -> list[int]:
        return [self.current_version_ids[index] for index in self.version_list.curselection()]

    def _run(self, action, success: str) -> None:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self._error(str(exc))
        else:
            self._ok(success)

    def _run_async(self, action, running: str, success: str, after_success=None) -> None:
        if getattr(self, "_async_busy", False):
            self._error("已有后台任务运行中，请稍候")
            return
        self._async_busy = True
        self._ok(running)

        def worker() -> None:
            try:
                result = action()
            except Exception as exc:  # noqa: BLE001 - UI boundary
                message = str(exc)
                self.root.after(0, lambda message=message: self._complete_async_error(message))
            else:
                def complete() -> None:
                    self._complete_async_success(success, after_success, result)

                self.root.after(0, complete)

        threading.Thread(target=worker, daemon=True).start()

    def _complete_async_success(self, success: str, after_success=None, result=None) -> None:
        try:
            status_message = success
            if after_success:
                callback_result = after_success(result)
                if callback_result is False:
                    status_message = ""
                elif isinstance(callback_result, str):
                    status_message = callback_result
            if status_message:
                self._ok(status_message)
        finally:
            self._async_busy = False

    def _complete_async_error(self, message: str) -> None:
        try:
            self.automation_cancel_event = None
            self.refresh_logs()
            self._error(message)
        finally:
            self._async_busy = False

    def _ok(self, message: str) -> None:
        self.status_var.set(message)

    def _error(self, message: str) -> None:
        self.status_var.set(message)
        messagebox.showerror("错误", message)

    @staticmethod
    def _loads(raw: str | None) -> Any:
        if not raw:
            return []
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []
