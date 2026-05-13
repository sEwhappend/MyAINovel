from __future__ import annotations

import difflib
import json
import os
import threading
from typing import Any, Callable

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
    format_export_success_message,
    format_model_discovery_result,
    format_world_context_pack,
    latest_outline_index,
    model_scan_autofill,
    parse_lines,
    project_index_by_id,
    world_kind_label,
    world_kind_value,
)

try:
    from PySide6.QtCore import QRect, QObject, QSize, Qt, Signal
    from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QTextCursor
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSplitter,
        QStackedWidget,
        QStyle,
        QStyledItemDelegate,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False


def _install_message() -> str:
    return "未安装 PySide6。请运行：python -m pip install -r requirements.txt"


def build_pyside_stylesheet() -> str:
    return """
    QMainWindow, QWidget {
        background: #f7faff;
        color: #243042;
        font-family: "Microsoft YaHei UI";
        font-size: 13px;
    }
    QLabel#Header {
        font-size: 18px;
        font-weight: 700;
        padding: 12px 14px;
        background: #ffffff;
        color: #2e5eaa;
        border: 1px solid #dce6f2;
        border-left: 6px solid #f6b7c9;
        border-radius: 10px;
    }
    QLabel#Status {
        padding: 8px 10px;
        background: #ffffff;
        border: 1px solid #dce6f2;
        border-radius: 8px;
        color: #687589;
    }
    QFrame#ProjectShelfPane, QFrame#ProjectDetailPane, QFrame#ChapterOutlinePane, QFrame#ChapterEditorPane {
        background: #ffffff;
        border: 1px solid #dce6f2;
        border-radius: 12px;
    }
    QLabel#PanelTitle {
        color: #2e5eaa;
        font-weight: 700;
        padding: 6px 4px;
    }
    QFrame#ProjectDetailPane QLabel {
        background: transparent;
        border: 0;
        color: #243042;
    }
    QListWidget, QTextEdit, QLineEdit, QComboBox {
        background: #ffffff;
        border: 1px solid #dce6f2;
        border-radius: 8px;
        padding: 6px;
        selection-background-color: #6fa8ff;
        selection-color: #ffffff;
    }
    QTextEdit:focus, QLineEdit:focus, QComboBox:focus {
        border: 1px solid #6fa8ff;
        background: #ffffff;
    }
    QListWidget { outline: 0; }
    QListWidget::item {
        padding: 8px 10px;
        margin: 2px 2px;
        border-radius: 6px;
        border: 1px solid transparent;
    }
    QListWidget::item:hover {
        background: #eaf3ff;
        border-color: #b8d4ff;
    }
    QListWidget::item:pressed {
        background: #dbeaff;
        border-color: #6fa8ff;
        padding-top: 9px;
        padding-bottom: 7px;
    }
    QListWidget::item:selected {
        background: #6fa8ff;
        border-color: #2e5eaa;
        color: #ffffff;
    }
    QListWidget::item:selected:hover {
        background: #5b99f2;
    }
    QListWidget::item:focus {
        outline: none;
        border: 1px solid transparent;
    }
    QListWidget#Navigation {
        background: #ffffff;
        border: 1px solid #dce6f2;
        border-radius: 12px;
        padding: 8px;
    }
    QListWidget#Navigation::item {
        padding: 10px 12px;
        margin: 3px 0;
        border-radius: 8px;
    }
    QListWidget#Navigation::item:selected {
        background: #eaf3ff;
        color: #2e5eaa;
        border: 1px solid #b8d4ff;
        font-weight: 700;
    }
    QListWidget#ProjectShelf {
        background: #fff8fb;
        border: 1px solid #f5ccd8;
        padding: 6px;
    }
    QListWidget#ProjectShelf::item {
        background: #ffffff;
        border: 1px solid #dce6f2;
        border-left: 8px solid #f6b7c9;
        border-radius: 8px;
        margin: 0;
        padding: 0;
        min-width: 0;
        min-height: 0;
        color: #243042;
    }
    QListWidget#ProjectShelf::item:hover {
        background: #f8fbff;
        border-color: #b8d4ff;
        border-left-color: #6fa8ff;
    }
    QListWidget#ProjectShelf::item:pressed {
        background: #eaf3ff;
        padding-top: 13px;
        padding-bottom: 11px;
    }
    QListWidget#ProjectShelf::item:selected {
        background: #eaf3ff;
        color: #1f4f99;
        border: 1px solid #6fa8ff;
        border-left: 10px solid #6fa8ff;
    }
    QListWidget#ChapterTree::item, QListWidget#SectionList::item {
        border-left: 4px solid #dce6f2;
    }
    QListWidget#ChapterTree::item:selected, QListWidget#SectionList::item:selected {
        background: #eaf3ff;
        color: #2e5eaa;
        border-color: #6fa8ff;
        border-left-color: #6fa8ff;
    }
    QTextEdit#WritingEditor {
        background: #ffffff;
        border: 1px solid #ccd9ea;
        color: #243042;
        font-size: 14px;
        line-height: 1.55;
    }
    QTextEdit#StreamingOutput {
        background: #f8fbff;
        border: 1px solid #b8d4ff;
        border-left: 5px solid #f6b7c9;
        color: #243042;
    }
    QTextEdit#WorldContext {
        background: #fbfdff;
        border-left: 5px solid #6fa8ff;
    }
    QTextEdit#ProjectTextInput {
        background: #ffffff;
        border: 1px solid #dce6f2;
        border-radius: 8px;
        padding: 6px;
        color: #243042;
        selection-background-color: #6fa8ff;
        selection-color: #ffffff;
    }
    QTextEdit#ProjectTextInput:focus {
        border: 1px solid #6fa8ff;
        background: #ffffff;
    }
    QPushButton {
        background: #ffffff;
        border: 1px solid #b8d4ff;
        border-radius: 8px;
        padding: 7px 11px;
        color: #2e5eaa;
        font-weight: 600;
    }
    QPushButton:hover {
        background: #eaf3ff;
        border-color: #6fa8ff;
    }
    QPushButton:pressed {
        background: #6fa8ff;
        color: #ffffff;
        padding-top: 8px;
        padding-bottom: 6px;
    }
    QPushButton[primary="true"] {
        background: #6fa8ff;
        color: #ffffff;
        border-color: #6fa8ff;
    }
    QPushButton[primary="true"]:hover {
        background: #5b99f2;
        border-color: #2e5eaa;
    }
    QPushButton[danger="true"] {
        color: #e56b73;
        border-color: #f3b6bc;
        background: #fff5f6;
    }
    QPushButton[danger="true"]:hover {
        background: #ffe9ec;
        border-color: #e56b73;
    }
    QCheckBox {
        spacing: 8px;
        color: #243042;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #b8d4ff;
        border-radius: 4px;
        background: #ffffff;
    }
    QCheckBox::indicator:checked {
        background: #6fa8ff;
        border-color: #2e5eaa;
    }
    QComboBox::drop-down {
        border: 0;
        width: 24px;
    }
    QFrame { border: 0; }
    """


class _ValueAdapter:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


if PYSIDE6_AVAILABLE:

    class _AsyncBridge(QObject):
        success = Signal(str, object, object)
        error = Signal(str)
        stream = Signal(str, str)


    class ProjectShelfListWidget(QListWidget):
        # 项目书架布局参数：
        # GRID_WIDTH/GRID_HEIGHT 控制每一本书占用的格子大小。
        # TWO_COLUMN_MIN_WIDTH 控制书架从单列切换到双列的最小可用宽度。
        # EDGE_PADDING 和 SCROLLBAR_RESERVE 用来避免内容贴边或被滚动条挤压。
        GRID_WIDTH = 176
        GRID_HEIGHT = 300
        TWO_COLUMN_MIN_WIDTH = 160
        EDGE_PADDING = 2
        SCROLLBAR_RESERVE = -130

        def resizeEvent(self, event) -> None:  # type: ignore[override]
            super().resizeEvent(event)
            self._fit_book_grid()

        def showEvent(self, event) -> None:  # type: ignore[override]
            super().showEvent(event)
            self._fit_book_grid()

        def _fit_book_grid(self) -> None:
            base_available_width = max(1, self.width() - self.SCROLLBAR_RESERVE - (self.EDGE_PADDING * 2))
            if base_available_width >= self.TWO_COLUMN_MIN_WIDTH:
                columns = max(2, base_available_width // self.GRID_WIDTH)
            else:
                columns = 1
            used_width = columns * self.GRID_WIDTH
            # 固定书本格子宽度，把多余空间分配到左右边距，避免卡片被拉宽。
            side_padding = self.EDGE_PADDING + max(0, (base_available_width - used_width) // 2)
            self.setViewportMargins(side_padding, 0, side_padding, 0)
            self.setGridSize(QSize(self.GRID_WIDTH, self.GRID_HEIGHT))


    class ProjectShelfDelegate(QStyledItemDelegate):
        def sizeHint(self, option, index) -> QSize:  # type: ignore[override]
            # 实际卡片绘制区域；如果修改这里，通常也要同步调整 GRID_WIDTH/GRID_HEIGHT。
            return QSize(176, 252)

        def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            # 限制卡片最大宽度，避免书架格子变宽时卡片也跟着被拉伸。
            card_width = min(176, max(1, option.rect.width() - 8))
            card_left = option.rect.left() + max(0, (option.rect.width() - card_width) // 2)
            cell_rect = QRect(card_left, option.rect.top() + 6, card_width, option.rect.height() - 12)
            if selected or hovered:
                painter.setPen(QPen(QColor("#6fa8ff" if selected else "#b8d4ff"), 1))
                painter.setBrush(QColor("#f8fbff" if hovered else "#eaf3ff"))
                painter.drawRoundedRect(cell_rect, 14, 14)

            text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
            title, _, meta = text.partition("\n")
            title = title.strip() or "未命名项目"
            meta = meta.strip() or "未设置题材"
            palette_index = sum(ord(char) for char in title) % 4
            palettes = [
                ("#8ea6d9", "#f6b7c9", "#ffffff"),
                ("#f06a68", "#f6b7c9", "#ffffff"),
                ("#f9fbf8", "#57a7c9", "#f2c75c"),
                ("#dfe9ff", "#6fa8ff", "#fff0f5"),
            ]
            cover_top, cover_mid, cover_accent = palettes[palette_index]

            cover_width = 132
            cover_height = 213
            cover_left = cell_rect.left() + (cell_rect.width() - cover_width) // 2
            cover_top_y = cell_rect.top() + 12
            cover_rect = QRect(cover_left, cover_top_y, cover_width, cover_height)
            shadow_rect = cover_rect.adjusted(5, 6, 8, 10)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(36, 48, 66, 34))
            painter.drawRoundedRect(shadow_rect, 12, 12)

            gradient = QLinearGradient(cover_rect.topLeft(), cover_rect.bottomRight())
            gradient.setColorAt(0, QColor(cover_top))
            gradient.setColorAt(0.58, QColor(cover_mid))
            gradient.setColorAt(1, QColor(cover_accent))
            painter.setBrush(gradient)
            painter.setPen(QPen(QColor("#dce6f2"), 1))
            painter.drawRoundedRect(cover_rect, 12, 12)

            spine_rect = QRect(cover_rect.left(), cover_rect.top(), 16, cover_rect.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 46))
            painter.drawRoundedRect(spine_rect, 9, 9)
            painter.setBrush(QColor(36, 48, 66, 30))
            painter.drawRect(spine_rect.adjusted(11, 0, 12, 0))

            if palette_index in (0, 3):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 120))
                painter.drawEllipse(cover_rect.center().x() - 34, cover_rect.center().y() - 18, 68, 52)
                painter.setBrush(QColor(246, 183, 201, 112))
                painter.drawEllipse(cover_rect.center().x() - 18, cover_rect.center().y() + 20, 36, 26)
            elif palette_index == 1:
                painter.setPen(QPen(QColor(255, 255, 255, 190), 6))
                painter.drawLine(cover_rect.left() + 30, cover_rect.top() + 56, cover_rect.left() + 66, cover_rect.top() + 96)
                painter.drawLine(cover_rect.left() + 66, cover_rect.top() + 56, cover_rect.left() + 30, cover_rect.top() + 96)
                painter.setPen(QPen(QColor(255, 255, 255, 70), 8))
                painter.drawLine(cover_rect.left() + 26, cover_rect.bottom() - 48, cover_rect.right() - 18, cover_rect.bottom() - 48)
                painter.drawLine(cover_rect.left() + 26, cover_rect.bottom() - 28, cover_rect.left() + 66, cover_rect.bottom() - 28)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#57a7c9"))
                painter.drawEllipse(cover_rect.left() + 18, cover_rect.top() + 60, 62, 62)
                painter.setBrush(QColor("#f2c75c"))
                painter.drawEllipse(cover_rect.left() + 30, cover_rect.top() + 74, 34, 34)

            shelf_rect = QRect(cell_rect.left() + 6, cover_rect.bottom() + 8, cell_rect.width() - 12, 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#eef2f7"))
            painter.drawRoundedRect(shelf_rect, 4, 4)
            painter.setBrush(QColor(36, 48, 66, 22))
            painter.drawRoundedRect(shelf_rect.adjusted(4, 6, -4, 8), 6, 6)

            text_rect = QRect(cell_rect.left() + 18, shelf_rect.bottom() + 10, cell_rect.width() - 36, 42)
            title_font = QFont(option.font)
            title_font.setBold(True)
            title_font.setPointSize(max(title_font.pointSize() + 1, 10))
            painter.setFont(title_font)
            painter.setPen(QColor("#1f4f99" if selected else "#243042"))
            title_text = painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, text_rect.width())
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                title_text,
            )

            meta_font = QFont(option.font)
            meta_font.setPointSize(max(meta_font.pointSize(), 9))
            painter.setFont(meta_font)
            painter.setPen(QColor("#687589"))
            meta_rect = QRect(text_rect.left(), text_rect.top() + 26, text_rect.width(), 20)
            meta_text = painter.fontMetrics().elidedText(meta, Qt.TextElideMode.ElideRight, meta_rect.width())
            painter.drawText(meta_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, meta_text)

            if selected:
                chip_rect = QRect(cover_rect.right() - 44, cover_rect.top() + 10, 34, 18)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#fff0f5"))
                painter.drawRoundedRect(chip_rect, 8, 8)
                chip_font = QFont(option.font)
                chip_font.setPointSize(8)
                painter.setFont(chip_font)
                painter.setPen(QColor("#2e5eaa"))
                painter.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, "当前")

            painter.restore()


    class NovelDesktopUI:
        def __init__(self, services: ApplicationServices, title: str) -> None:
            self.services = services
            self.store = services.store
            self.pipeline = services.pipeline
            self.title = title
            self.current_project_id: int | None = None
            self.current_chapter_id: int | None = None
            self.current_section_id: int | None = None
            self.current_world_item_id: int | None = None
            self.current_world_details_json = ""
            self.current_version_ids: list[int] = []
            self.projects: list[dict[str, Any]] = []
            self.outline_version_rows: list[dict[str, Any]] = []
            self.world_rows: list[dict[str, Any]] = []
            self.chapter_rows: list[dict[str, Any]] = []
            self.section_rows: list[dict[str, Any]] = []
            self.version_rows: list[dict[str, Any]] = []
            self.character_card_rows: list[dict[str, Any]] = []
            self.location_rows: list[dict[str, Any]] = []
            self._async_busy = False
            self.automation_cancel_event: threading.Event | None = None
            self.app = QApplication.instance() or QApplication([])
            self.app.setStyle("Fusion")
            self.bridge = _AsyncBridge()
            self.bridge.success.connect(self._complete_async_success)
            self.bridge.error.connect(self._complete_async_error)
            self.bridge.stream.connect(self._append_streaming_target)
            self.window = QMainWindow()
            self.window.setWindowTitle(title)
            self.window.resize(1187, 667)
            self._build()
            self.refresh_projects()

        def run(self) -> None:
            self.window.show()
            self.app.exec()

        def _build(self) -> None:
            root = QWidget()
            layout = QVBoxLayout(root)
            layout.setContentsMargins(12, 12, 12, 10)
            header = QLabel("My AI Novel    结构化小说生产流水线")
            header.setObjectName("Header")
            layout.addWidget(header)

            shell = QHBoxLayout()
            self.navigation = QListWidget()
            self.navigation.setObjectName("Navigation")
            self.navigation.setFixedWidth(170)
            self.stack = QStackedWidget()
            shell.addWidget(self.navigation)
            shell.addWidget(self.stack, 1)
            layout.addLayout(shell, 1)

            self.status_label = QLabel("就绪")
            self.status_label.setObjectName("Status")
            layout.addWidget(self.status_label)
            self.window.setCentralWidget(root)

            self._build_project_page()
            self._build_outline_page()
            self._build_world_page()
            self._build_structure_page()
            self._build_writing_page()
            self._build_settings_page()
            self._build_logs_page()
            self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
            self.navigation.setCurrentRow(0)
            self._apply_theme()

        def _add_page(self, title: str) -> QWidget:
            page = QWidget()
            self.stack.addWidget(page)
            self.navigation.addItem(title)
            return page

        def _button(self, text: str, callback: Callable[[], None]) -> QPushButton:
            button = QPushButton(text)
            button.clicked.connect(callback)
            return button

        def _build_project_page(self) -> None:
            page = self._add_page("项目")
            layout = QHBoxLayout(page)
            left_frame = QFrame()
            left_frame.setObjectName("ProjectShelfPane")
            # 保证启动时项目书架左栏足够放下两张正常尺寸的书本卡片。
            #left_frame.setMinimumWidth(450)
            left = QVBoxLayout(left_frame)
            shelf_title = QLabel("项目列表")
            shelf_title.setObjectName("PanelTitle")
            left.addWidget(shelf_title)
            self.project_list = ProjectShelfListWidget()
            self.project_list.setObjectName("ProjectShelf")
            self.project_list.setViewMode(QListWidget.ViewMode.IconMode)
            self.project_list.setFlow(QListWidget.Flow.LeftToRight)
            self.project_list.setWrapping(True)
            self.project_list.setMovement(QListWidget.Movement.Static)
            self.project_list.setResizeMode(QListWidget.ResizeMode.Adjust)
            self.project_list.setSpacing(2)
            self.project_list.setGridSize(QSize(184, 266))
            self.project_list.setUniformItemSizes(True)
            self.project_list.setWordWrap(True)
            self.project_list.setTextElideMode(Qt.TextElideMode.ElideRight)
            self.project_list.setItemDelegate(ProjectShelfDelegate(self.project_list))
            self.project_list.currentRowChanged.connect(lambda _row: self.select_project())
            left.addWidget(self.project_list, 1)
            left.addWidget(self._button("新建项目", self.start_new_project))
            left.addWidget(self._button("刷新项目", self.refresh_projects))
            layout.addWidget(left_frame, 1.618)

            right_frame = QFrame()
            right_frame.setObjectName("ProjectDetailPane")
            # 保证启动时项目书架左栏足够放下两张正常尺寸的书本卡片。
            right_frame.setMinimumWidth(500)
            right = QVBoxLayout(right_frame)
            form = QFormLayout()
            self.project_fields: dict[str, QLineEdit] = {}
            for label, key in [
                ("项目名称", "title"),
                ("题材", "genre"),
                ("写作风格", "style"),
                ("目标读者", "target_readers"),
                ("总目标字数", "length_target"),
                ("预计全书小节数", "estimated_total_sections"),
                ("默认每小节目标字数", "default_section_target_words"),
                ("叙事视角", "pov"),
            ]:
                widget = QLineEdit()
                self.project_fields[key] = widget
                form.addRow(label, widget)
            right.addLayout(form)
            self.project_texts: dict[str, QTextEdit] = {}
            for label, key in PROJECT_TEXT_FIELDS:
                right.addWidget(QLabel(label))
                text = QTextEdit()
                text.setObjectName("ProjectTextInput")
                text.setPlaceholderText(f"请输入{label}")
                text.setMinimumHeight(80)
                self.project_texts[key] = text
                right.addWidget(text)
            actions = QHBoxLayout()
            for text, callback in [
                ("保存项目", self.save_project),
                ("打开项目文件夹", self.open_project_folder),
                ("导出全书 Word", self.export_full_book_word),
            ]:
                actions.addWidget(self._button(text, callback))
            right.addLayout(actions)
            layout.addWidget(right_frame, 1)

        def _build_outline_page(self) -> None:
            page = self._add_page("总框架")
            layout = QHBoxLayout(page)
            left = QVBoxLayout()
            for text, callback in [
                ("丰满总体框架", self.expand_outline),
                ("保存当前总框架修改", self.save_current_outline),
                ("确认并拆分章节", self.confirm_outline_split),
            ]:
                left.addWidget(self._button(text, callback))
            left.addWidget(QLabel("总框架版本"))
            self.outline_versions = QListWidget()
            self.outline_versions.currentRowChanged.connect(lambda _row: self.show_outline_version())
            left.addWidget(self.outline_versions, 1)
            layout.addLayout(left, 1)
            right = QSplitter(Qt.Orientation.Vertical)
            self.outline_text = QTextEdit()
            self.outline_text.setObjectName("WritingEditor")
            self.outline_split_preview = QTextEdit()
            self.outline_split_preview.setObjectName("StreamingOutput")
            self.outline_split_preview.setPlaceholderText("确认并拆分章节的流式输出")
            right.addWidget(self.outline_text)
            right.addWidget(self.outline_split_preview)
            layout.addWidget(right, 2)

        def _build_world_page(self) -> None:
            page = self._add_page("资料库")
            layout = QHBoxLayout(page)
            left = QVBoxLayout()
            self.world_kind = QComboBox()
            self.world_kind.addItems([world_kind_label(kind) for kind in sorted(WORLD_ITEM_KINDS)])
            self.world_kind.setCurrentText(world_kind_label("character"))
            self.world_kind.currentTextChanged.connect(lambda _text: self._on_world_kind_changed())
            left.addWidget(self.world_kind)
            self.world_list = QListWidget()
            self.world_list.setObjectName("WorldList")
            self.world_list.currentRowChanged.connect(lambda _row: self.select_world_item())
            left.addWidget(self.world_list, 1)
            left.addWidget(self._button("刷新资料库", self.refresh_world_items))
            layout.addLayout(left, 1)

            right = QVBoxLayout()
            self.world_name = QLineEdit()
            self.world_tags = QLineEdit()
            right.addWidget(QLabel("名称"))
            right.addWidget(self.world_name)
            right.addWidget(QLabel("标签"))
            right.addWidget(self.world_tags)
            right.addWidget(QLabel("摘要"))
            self.world_summary = QTextEdit()
            right.addWidget(self.world_summary, 1)
            actions = QHBoxLayout()
            for text, callback in [
                ("保存资料", self.save_world_item),
                ("删除资料", self.delete_world_item),
                ("AI 自动补充设定", self.enrich_selected_world_item),
            ]:
                actions.addWidget(self._button(text, callback))
            right.addLayout(actions)
            layout.addLayout(right, 2)

        def _build_structure_page(self) -> None:
            page = self._add_page("章节")
            layout = QHBoxLayout(page)
            left_frame = QFrame()
            left_frame.setObjectName("ChapterOutlinePane")
            left = QVBoxLayout(left_frame)
            chapter_title = QLabel("章节")
            chapter_title.setObjectName("PanelTitle")
            left.addWidget(chapter_title)
            self.chapter_list = QListWidget()
            self.chapter_list.setObjectName("ChapterTree")
            self.chapter_list.currentRowChanged.connect(lambda _row: self.select_chapter())
            left.addWidget(self.chapter_list, 1)
            chapter_actions = QHBoxLayout()
            for text, callback in [
                ("新建", self.start_new_chapter),
                ("上移", self.move_chapter_up),
                ("下移", self.move_chapter_down),
                ("删除", self.delete_selected_chapter),
            ]:
                chapter_actions.addWidget(self._button(text, callback))
            left.addLayout(chapter_actions)
            section_title = QLabel("小节")
            section_title.setObjectName("PanelTitle")
            left.addWidget(section_title)
            self.section_list = QListWidget()
            self.section_list.setObjectName("SectionList")
            self.section_list.currentRowChanged.connect(lambda _row: self.select_section())
            left.addWidget(self.section_list, 1)
            section_actions = QHBoxLayout()
            for text, callback in [
                ("上移", self.move_section_up),
                ("下移", self.move_section_down),
                ("删除", self.delete_selected_section),
            ]:
                section_actions.addWidget(self._button(text, callback))
            left.addLayout(section_actions)
            self.structure_auto_next_enabled = QCheckBox("自动切换到下一节写作")
            self.structure_auto_next_chapter_enabled = QCheckBox("自动切换到下一章写作")
            left.addWidget(self.structure_auto_next_enabled)
            left.addWidget(self.structure_auto_next_chapter_enabled)
            left.addWidget(self._button("从当前小节自动化写作", self.start_chapter_automation))
            left.addWidget(self._button("中断自动化写作", self.interrupt_chapter_automation))
            layout.addWidget(left_frame, 1)

            right_frame = QFrame()
            right_frame.setObjectName("ChapterEditorPane")
            right = QVBoxLayout(right_frame)
            self.structure_fields: dict[str, Any] = {}
            form = QFormLayout()
            for label, key in [
                ("标题", "title"),
                ("时间", "story_time"),
                ("地点", "location"),
                ("目标", "goal"),
                ("场景", "scene"),
                ("冲突", "conflict"),
                ("情绪变化", "emotion_shift"),
                ("目标字数", "target_words"),
            ]:
                widget = QLineEdit()
                self.structure_fields[key] = widget
                form.addRow(label, widget)
            right.addLayout(form)
            for label, key in [("人物", "characters"), ("必须发生", "must_happen"), ("禁止内容", "forbidden")]:
                right.addWidget(QLabel(label))
                widget = QTextEdit()
                widget.setMinimumHeight(60)
                self.structure_fields[key] = widget
                right.addWidget(widget)
            action_row = QHBoxLayout()
            for text, callback in [
                ("保存为章节", self.save_chapter_from_form),
                ("保存为小节", self.save_section_from_form),
                ("调用资料库", self.load_world_context),
                ("生成章节架构", self.generate_chapter_plan),
                ("生成小节规划", self.generate_section_plan),
            ]:
                action_row.addWidget(self._button(text, callback))
            right.addLayout(action_row)
            right.addWidget(QLabel("写作参考资料"))
            self.world_context_text = QTextEdit()
            self.world_context_text.setObjectName("WorldContext")
            right.addWidget(self.world_context_text, 1)
            layout.addWidget(right_frame, 2)

        def _build_writing_page(self) -> None:
            page = self._add_page("写作")
            self.writing_page = page
            layout = QVBoxLayout(page)
            actions = QHBoxLayout()
            for text, callback in [
                ("生成正文", self.write_draft),
                ("审稿", self.review_selected_version),
                ("按意见改写", self.rewrite_selected_version),
                ("锁定为定稿", self.finalize_selected_version),
                ("取消定稿", self.unfinalize_current_section),
                ("继续下一节", self.continue_next_section),
                ("比较版本", self.diff_versions),
                ("总结本章并更新资料库", self.write_current_chapter_memory),
            ]:
                actions.addWidget(self._button(text, callback))
            layout.addLayout(actions)
            options = QHBoxLayout()
            self.writing_auto_enabled = QCheckBox("自动化：正文 -> 审稿 -> 改写 -> 定稿 -> 继续下一节")
            self.rewrite_mode = QComboBox()
            self.rewrite_mode.addItems(["整体改写", "只改对白", "只改心理", "只改结尾", "增强冲突"])
            options.addWidget(self.writing_auto_enabled)
            options.addWidget(QLabel("改写模式"))
            options.addWidget(self.rewrite_mode)
            options.addStretch(1)
            layout.addLayout(options)
            body = QSplitter(Qt.Orientation.Horizontal)
            self.version_list = QListWidget()
            self.version_list.setObjectName("SectionList")
            self.version_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
            self.version_list.currentRowChanged.connect(lambda _row: self.show_selected_version())
            self.version_text = QTextEdit()
            self.version_text.setObjectName("WritingEditor")
            body.addWidget(self.version_list)
            body.addWidget(self.version_text)
            layout.addWidget(body, 2)
            layout.addWidget(QLabel("当前流式生成内容"))
            self.current_generation_text = QTextEdit()
            self.current_generation_text.setObjectName("StreamingOutput")
            layout.addWidget(self.current_generation_text, 1)

        def _build_settings_page(self) -> None:
            page = self._add_page("设置")
            layout = QVBoxLayout(page)
            form = QFormLayout()
            self.config_vars: dict[str, Any] = {}
            config = load_llm_config()
            for label, key in LLM_CONFIG_FIELDS:
                if key == "model_candidates":
                    widget = QTextEdit()
                    widget.setMinimumHeight(70)
                    widget.setPlainText(str(config.get(key, "")))
                elif key == "api_type":
                    widget = QComboBox()
                    widget.addItems(list(API_TYPE_VALUES))
                    widget.setCurrentText(api_type_display_value(config.get(key)))
                else:
                    widget = QLineEdit(str(config.get(key, "")))
                    if key == "api_key":
                        widget.setEchoMode(QLineEdit.EchoMode.Password)
                self.config_vars[key] = widget
                form.addRow(label, widget)
            layout.addLayout(form)
            actions = QHBoxLayout()
            for text, callback in [
                ("保存设置", self.save_llm_settings),
                ("测试连接", self.test_llm_connection),
                ("扫描模型", self.scan_llm_models),
            ]:
                actions.addWidget(self._button(text, callback))
            layout.addLayout(actions)
            self.model_scan_text = QTextEdit()
            layout.addWidget(QLabel("可用模型"))
            layout.addWidget(self.model_scan_text, 1)

        def _build_logs_page(self) -> None:
            page = self._add_page("日志")
            layout = QVBoxLayout(page)
            layout.addWidget(self._button("刷新日志", self.refresh_logs))
            self.logs_text = QTextEdit()
            layout.addWidget(self.logs_text, 1)

        def _apply_theme(self) -> None:
            self.window.setStyleSheet(build_pyside_stylesheet())

        def _text(self, widget: Any) -> str:
            if isinstance(widget, QTextEdit):
                return widget.toPlainText().strip()
            if isinstance(widget, QComboBox):
                return widget.currentText().strip()
            return widget.text().strip()

        def _set_text(self, widget: Any, value: Any) -> None:
            text = str(value or "")
            if isinstance(widget, QTextEdit):
                widget.setPlainText(text)
            elif isinstance(widget, QComboBox):
                index = widget.findText(text)
                if index >= 0:
                    widget.setCurrentIndex(index)
                else:
                    widget.setCurrentText(text)
            else:
                widget.setText(text)

        def _selected_row(self, list_widget: QListWidget, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
            row = list_widget.currentRow()
            if row < 0 or row >= len(rows):
                return None
            return rows[row]

        def _project_shelf_label(self, project: dict[str, Any]) -> str:
            title = str(project.get("title", "") or "未命名项目").strip()
            genre = str(project.get("genre", "") or "").strip()
            style = str(project.get("style", "") or "").strip()
            length_target = str(project.get("length_target", "") or "").strip()
            metadata = " / ".join(part for part in [genre, style] if part) or "未设置题材"
            if length_target:
                metadata = f"{metadata} · {length_target}"
            return f"{title}\n{metadata}"

        def refresh_projects(self) -> None:
            rebuild_cache = getattr(self.store, "rebuild_cache_from_project_files", None)
            if callable(rebuild_cache):
                rebuild_cache()
            previous_project_id = self.current_project_id
            self.projects = self.store.list_projects()
            self.project_list.clear()
            for project in self.projects:
                item = QListWidgetItem(self._project_shelf_label(project))
                item.setSizeHint(QSize(176, 252))
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item.setToolTip(f"{project['id']} | {project['title']}")
                item.setData(Qt.ItemDataRole.UserRole, int(project["id"]))
                self.project_list.addItem(item)
            if previous_project_id and project_index_by_id(self.projects, previous_project_id) is None:
                self.start_new_project()
                self._ok("当前项目文件夹已不存在，已从列表移除")

        def select_project_by_id(self, project_id: int | None) -> bool:
            index = project_index_by_id(self.projects, project_id)
            if index is None:
                return False
            self.project_list.setCurrentRow(index)
            return True

        def select_project(self) -> None:
            project = self._selected_row(self.project_list, self.projects)
            if not project:
                return
            self.current_project_id = int(project["id"])
            self.current_chapter_id = None
            self.current_section_id = None
            self.current_world_item_id = None
            self.current_version_ids = []
            for key, widget in self.project_fields.items():
                self._set_text(widget, project.get(key, ""))
            for key, widget in self.project_texts.items():
                self._set_text(widget, project.get(key, ""))
            self._clear_project_views()
            self.refresh_all_project_views()

        def start_new_project(self) -> None:
            self.current_project_id = None
            self.current_chapter_id = None
            self.current_section_id = None
            self.current_world_item_id = None
            self.current_version_ids = []
            for widget in self.project_fields.values():
                self._set_text(widget, "")
            for widget in self.project_texts.values():
                self._set_text(widget, "")
            self.project_list.clearSelection()
            self._clear_project_views()
            self._ok("已切换到新建项目")

        def _clear_project_views(self) -> None:
            self.outline_version_rows = []
            self.world_rows = []
            self.chapter_rows = []
            self.section_rows = []
            self.version_rows = []
            self.current_world_item_id = None
            self.current_world_details_json = ""
            for widget in [
                self.outline_versions,
                self.world_list,
                self.chapter_list,
                self.section_list,
                self.version_list,
            ]:
                widget.clear()
            for widget in [
                self.outline_text,
                self.outline_split_preview,
                self.world_context_text,
                self.version_text,
                self.current_generation_text,
                self.logs_text,
            ]:
                widget.clear()
            self._clear_structure_form()
            self._clear_world_form()

        def _clear_structure_form(self) -> None:
            for widget in self.structure_fields.values():
                self._set_text(widget, "")

        def _clear_world_form(self, reset_kind: bool = True) -> None:
            self.current_world_item_id = None
            self.current_world_details_json = ""
            if reset_kind:
                self.world_kind.setCurrentText(world_kind_label("character"))
            self.world_name.clear()
            self.world_tags.clear()
            self.world_summary.clear()

        def save_project(self) -> None:
            data = {key: self._text(widget) for key, widget in self.project_fields.items()}
            data.update({key: self._text(widget) for key, widget in self.project_texts.items()})
            if not data["title"]:
                self._error("项目名称不能为空")
                return
            if not data.get("default_section_target_words"):
                data["default_section_target_words"] = calculate_default_section_target_words(
                    data.get("length_target"),
                    data.get("estimated_total_sections"),
                )
                self._set_text(self.project_fields["default_section_target_words"], data["default_section_target_words"])
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
            path = ensure_project_structure(project, getattr(self.store, "projects_root", None)).resolve()
            try:
                os.startfile(str(path))
            except Exception:
                self._ok(f"项目文件夹：{path}")
            else:
                self._ok(f"已打开项目文件夹：{path}")

        def export_full_book_word(self) -> None:
            project_id = self._project_required()
            if not project_id:
                return
            try:
                output_path = export_full_book_docx(self.store, project_id)
            except Exception as exc:
                self._error(str(exc))
                return
            self._ok(format_export_success_message(output_path))

        def expand_outline(self) -> None:
            project_id = self._project_required()
            if project_id:
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
            content = self.outline_text.toPlainText().strip()
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

        def refresh_outline_versions(self) -> None:
            self.outline_versions.clear()
            self.outline_version_rows = []
            if not self.current_project_id:
                return
            self.outline_version_rows = self.store.list_versions(self.current_project_id, kind="global_outline")
            for index, row in enumerate(self.outline_version_rows, 1):
                item = QListWidgetItem(f"{index} | {row['label']} | {row['created_at']}")
                item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                self.outline_versions.addItem(item)

        def _after_expand_outline(self) -> None:
            self.refresh_outline_versions()
            self.select_latest_outline_version()
            self.refresh_logs()

        def _after_confirm_outline_split(self) -> None:
            self.current_chapter_id = None
            self.current_section_id = None
            self.current_version_ids = []
            self._clear_structure_form()
            self.refresh_world_items()
            self.refresh_structure()
            self.refresh_versions()
            self.refresh_logs()

        def select_latest_outline_version(self) -> None:
            index = latest_outline_index(self.outline_version_rows)
            if index is not None:
                self.outline_versions.setCurrentRow(index)

        def select_outline_version_by_id(self, version_id: int) -> bool:
            for index, row in enumerate(self.outline_version_rows):
                if int(row.get("id", 0) or 0) == int(version_id):
                    self.outline_versions.setCurrentRow(index)
                    return True
            return False

        def show_outline_version(self) -> None:
            version_id = self._selected_outline_version()
            if not version_id:
                return
            row = self.store.get_version(version_id)
            self.outline_text.setPlainText(row.get("content", "") if row else "")

        def _selected_outline_metadata(self) -> dict[str, Any]:
            version_id = self._selected_outline_version()
            row = self.store.get_version(version_id) if version_id else None
            metadata = self._loads(row.get("metadata_json")) if row else {}
            return metadata if isinstance(metadata, dict) else {}

        def _selected_outline_version(self) -> int | None:
            row = self._selected_row(self.outline_versions, self.outline_version_rows)
            return int(row["id"]) if row else None

        def save_world_item(self) -> None:
            project_id = self._project_required()
            if not project_id:
                return
            self.store.save_world_item(
                project_id,
                {
                    "id": self.current_world_item_id,
                    "kind": world_kind_value(self.world_kind.currentText()),
                    "name": self.world_name.text(),
                    "summary": self.world_summary.toPlainText().strip(),
                    "details_json": self.current_world_details_json,
                    "tags": self.world_tags.text(),
                },
            )
            self.refresh_world_items()
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
            self._ok("资料已删除")

        def _on_world_kind_changed(self) -> None:
            self._clear_world_form(reset_kind=False)
            self.refresh_world_items()

        def refresh_world_items(self) -> None:
            self.world_list.clear()
            self.world_rows = []
            if not self.current_project_id:
                return
            kind = world_kind_value(self.world_kind.currentText())
            self.world_rows = self.store.list_world_items(self.current_project_id, kind)
            for item in self.world_rows:
                list_item = QListWidgetItem(f"{world_kind_label(item['kind'])} | {item['name']} | {item['tags']}")
                list_item.setData(Qt.ItemDataRole.UserRole, int(item["id"]))
                self.world_list.addItem(list_item)

        def select_world_item(self) -> None:
            item = self._selected_row(self.world_list, self.world_rows)
            if not item:
                return
            self.current_world_item_id = int(item["id"])
            self.current_world_details_json = item.get("details_json", "")
            self.world_kind.setCurrentText(world_kind_label(item.get("kind", "character")))
            self.world_name.setText(item.get("name", ""))
            self.world_tags.setText(item.get("tags", ""))
            self.world_summary.setPlainText(item.get("summary", ""))

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
            if isinstance(item, dict):
                self.current_world_item_id = int(item.get("id", self.current_world_item_id) or 0) or self.current_world_item_id
                self.current_world_details_json = json.dumps(item.get("details", {}), ensure_ascii=False, indent=2)
                self.world_kind.setCurrentText(world_kind_label(str(item.get("kind", "character"))))
                self.world_name.setText(str(item.get("name", "")))
                self.world_tags.setText(str(item.get("tags", "")))
                self.world_summary.setPlainText(str(item.get("summary", "")))
            self.refresh_logs()
            return "资料设定补充完成，请确认后点击“保存资料”"

        def refresh_structure(self) -> None:
            self.chapter_list.clear()
            self.section_list.clear()
            self.chapter_rows = []
            self.section_rows = []
            if not self.current_project_id:
                return
            self.chapter_rows = self.store.list_chapters(self.current_project_id)
            for chapter in self.chapter_rows:
                status = STATUS_LABELS.get(chapter["status"], chapter["status"])
                item = QListWidgetItem(f"{chapter['number']}. {chapter['title']} | {status}")
                item.setData(Qt.ItemDataRole.UserRole, int(chapter["id"]))
                self.chapter_list.addItem(item)

        def select_chapter(self) -> None:
            chapter = self._selected_row(self.chapter_list, self.chapter_rows)
            if not chapter:
                return
            self.current_chapter_id = int(chapter["id"])
            self.current_section_id = None
            self._fill_structure_form(chapter)
            self.section_list.clear()
            self.section_rows = self.store.list_sections(self.current_chapter_id)
            for section in self.section_rows:
                status = STATUS_LABELS.get(section["status"], section["status"])
                item = QListWidgetItem(f"{section['number']}. {section['title']} | {status}")
                item.setData(Qt.ItemDataRole.UserRole, int(section["id"]))
                self.section_list.addItem(item)

        def select_chapter_by_id(self, chapter_id: int) -> bool:
            for index, chapter in enumerate(self.chapter_rows):
                if int(chapter.get("id", 0) or 0) == int(chapter_id):
                    self.chapter_list.setCurrentRow(index)
                    return True
            return False

        def move_chapter_up(self) -> None:
            self._move_selected_chapter(-1)

        def move_chapter_down(self) -> None:
            self._move_selected_chapter(1)

        def _move_selected_chapter(self, direction: int) -> None:
            project_id = self._project_required()
            chapter = self._selected_row(self.chapter_list, self.chapter_rows)
            if not project_id or not chapter:
                self._error("请选择章节")
                return
            chapter_id = int(chapter["id"])
            try:
                self.store.move_chapter(project_id, chapter_id, direction)
            except Exception as exc:
                self._error(str(exc))
                return
            self.refresh_structure()
            self.select_chapter_by_id(chapter_id)
            self._ok("章节顺序已更新")

        def delete_selected_chapter(self) -> None:
            project_id = self._project_required()
            chapter = self._selected_row(self.chapter_list, self.chapter_rows)
            if not project_id or not chapter:
                self._error("请选择章节")
                return
            self.store.delete_chapter(project_id, int(chapter["id"]))
            self.current_chapter_id = None
            self.current_section_id = None
            self.refresh_structure()
            self.refresh_versions()
            self._ok("章节已删除")

        def start_new_chapter(self) -> None:
            if not self.current_project_id:
                self._error("请先创建或选择项目")
                return
            self.current_chapter_id = None
            self.current_section_id = None
            self.section_list.clear()
            self._clear_structure_form()
            self.refresh_versions()
            self._ok("已切换到新建章节")

        def select_section(self) -> None:
            section = self._selected_row(self.section_list, self.section_rows)
            if not section:
                return
            self.current_section_id = int(section["id"])
            self._fill_structure_form(section)
            self.refresh_versions()

        def select_section_by_id(self, section_id: int) -> bool:
            for index, section in enumerate(self.section_rows):
                if int(section.get("id", 0) or 0) == int(section_id):
                    self.section_list.setCurrentRow(index)
                    return True
            return False

        def move_section_up(self) -> None:
            self._move_selected_section(-1)

        def move_section_down(self) -> None:
            self._move_selected_section(1)

        def _move_selected_section(self, direction: int) -> None:
            section = self._selected_row(self.section_list, self.section_rows)
            if not self.current_chapter_id or not section:
                self._error("请选择小节")
                return
            section_id = int(section["id"])
            try:
                self.store.move_section(self.current_chapter_id, section_id, direction)
            except Exception as exc:
                self._error(str(exc))
                return
            self.select_chapter_by_id(self.current_chapter_id)
            self.select_section_by_id(section_id)
            self._ok("小节顺序已更新")

        def delete_selected_section(self) -> None:
            section = self._selected_row(self.section_list, self.section_rows)
            if not self.current_chapter_id or not section:
                self._error("请选择小节")
                return
            self.store.delete_section(int(section["id"]))
            chapter_id = self.current_chapter_id
            self.current_section_id = None
            self.select_chapter_by_id(chapter_id)
            self.refresh_versions()
            self._ok("小节已删除")

        def _fill_structure_form(self, row: dict[str, Any]) -> None:
            for key, widget in self.structure_fields.items():
                value = row.get(key, "")
                if key == "characters":
                    value = "\n".join(self._loads(row.get("characters_json")) or [])
                if key == "must_happen":
                    value = "\n".join(self._loads(row.get("must_happen_json")) or [])
                if key == "forbidden":
                    value = "\n".join(self._loads(row.get("forbidden_json")) or [])
                self._set_text(widget, value)

        def save_chapter_from_form(self) -> None:
            project_id = self._project_required()
            if not project_id:
                return
            data = self._structure_data()
            data["number"] = len(self.store.list_chapters(project_id)) + 1
            if self.current_chapter_id:
                data["id"] = self.current_chapter_id
                data["number"] = self.store.get_chapter(self.current_chapter_id)["number"]
            self.current_chapter_id = self.store.save_chapter(project_id, data)
            self.refresh_structure()
            self.select_chapter_by_id(self.current_chapter_id)
            self._ok("章节已保存")

        def save_section_from_form(self) -> None:
            if not self.current_chapter_id:
                self._error("请先选择章节")
                return
            data = self._structure_data()
            data["number"] = len(self.store.list_sections(self.current_chapter_id)) + 1
            if self.current_section_id:
                data["id"] = self.current_section_id
                data["number"] = self.store.get_section(self.current_section_id)["number"]
            self.current_section_id = self.store.save_section(self.current_chapter_id, data)
            self.select_chapter_by_id(self.current_chapter_id)
            self.select_section_by_id(self.current_section_id)
            self._ok("小节已保存")

        def _structure_data(self) -> dict[str, Any]:
            target_words = self._text(self.structure_fields["target_words"]) or self._project_default_section_target_words() or "1200"
            return {
                "title": self._text(self.structure_fields["title"]),
                "story_time": self._text(self.structure_fields["story_time"]),
                "location": self._text(self.structure_fields["location"]),
                "characters": parse_lines(self._text(self.structure_fields["characters"])),
                "goal": self._text(self.structure_fields["goal"]),
                "scene": self._text(self.structure_fields["scene"]),
                "conflict": self._text(self.structure_fields["conflict"]),
                "emotion_shift": self._text(self.structure_fields["emotion_shift"]),
                "must_happen": parse_lines(self._text(self.structure_fields["must_happen"])),
                "forbidden": parse_lines(self._text(self.structure_fields["forbidden"])),
                "target_words": int(target_words or 1200),
                "status": "planned",
            }

        def _project_default_section_target_words(self) -> str:
            value = self.project_fields["default_section_target_words"].text().strip()
            if value:
                return value
            if not self.current_project_id:
                return ""
            project = self.store.get_project(self.current_project_id) or {}
            return str(project.get("default_section_target_words", "") or "").strip()

        def load_world_context(self) -> None:
            project_id = self._project_required()
            if not project_id:
                return
            values = {key: self._text(widget) for key, widget in self.structure_fields.items()}
            query = build_world_context_query(values)
            if not query:
                self._error("请先填写或选择章节/小节信息")
                return
            pack = retrieve_context(self.store, project_id, self.current_chapter_id, self.current_section_id, query, llm=None)
            self.world_context_text.setPlainText(format_world_context_pack(pack))
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
            if not project_id or not self.current_section_id:
                return
            section_id = self.current_section_id
            if self.writing_auto_enabled.isChecked():
                self._run_async(
                    lambda: self._run_writing_automation(project_id, section_id, self.rewrite_mode.currentText()),
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
                    self.rewrite_mode.currentText(),
                    [],
                ),
                "正在按意见改写，请稍候...",
                "改写完成",
                lambda _result: self._after_writing_task(),
            )

        def _after_writing_task(self) -> None:
            self.refresh_versions()
            self.refresh_structure()
            self.refresh_logs()

        def _run_streaming_outline(self, project_id: int) -> dict[str, Any]:
            self.bridge.stream.emit("outline", "")

            def on_delta(delta: str) -> None:
                if delta:
                    self.bridge.stream.emit("outline", delta)

            if hasattr(self.pipeline, "expand_global_concept_streaming"):
                return self.pipeline.expand_global_concept_streaming(project_id, on_delta)
            result = self.pipeline.expand_global_concept(project_id)
            content = str(result.get("expanded_outline", "") or "")
            if content:
                on_delta(content)
            return result

        def _run_streaming_outline_split(self, project_id: int, version_id: int) -> dict[str, Any]:
            self.bridge.stream.emit("outline_split", "")

            def on_delta(delta: str) -> None:
                if delta:
                    self.bridge.stream.emit("outline_split", delta)

            if hasattr(self.pipeline, "confirm_outline_split_streaming"):
                return self.pipeline.confirm_outline_split_streaming(project_id, version_id, on_delta)
            return self.pipeline.confirm_outline_split(project_id, version_id)

        def _run_streaming_draft(self, project_id: int, section_id: int) -> dict[str, Any]:
            self.bridge.stream.emit("draft", "")

            def on_delta(delta: str) -> None:
                if delta:
                    self.bridge.stream.emit("draft", delta)

            if hasattr(self.pipeline, "write_section_draft_streaming"):
                return self.pipeline.write_section_draft_streaming(project_id, section_id, "rough", on_delta)
            result = self.pipeline.write_section_draft(project_id, section_id, "rough")
            content = str(result.get("content", "") or "")
            if content:
                on_delta(content)
            return result

        def _append_streaming_target(self, target: str, delta: str) -> None:
            widgets = {
                "outline": self.outline_text,
                "outline_split": self.outline_split_preview,
                "draft": self.current_generation_text,
            }
            widget = widgets.get(target)
            if widget is None:
                return
            if delta == "":
                widget.setPlainText("")
                return
            cursor = widget.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            widget.setTextCursor(cursor)
            widget.insertPlainText(delta)
            cursor = widget.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            widget.setTextCursor(cursor)

        def _run_writing_automation(
            self,
            project_id: int,
            section_id: int,
            rewrite_mode: str,
            cancel_event: threading.Event | None = None,
        ) -> dict[str, Any]:
            self._raise_if_automation_cancelled(cancel_event)
            draft = self.pipeline.write_section_draft(project_id, section_id, "rough")
            draft_version_id = int(draft["version_id"])
            self._raise_if_automation_cancelled(cancel_event)
            review = self.pipeline.review_section(project_id, section_id, draft_version_id)
            review_version_id = int(review["version_id"])
            self._raise_if_automation_cancelled(cancel_event)
            rewrite = self.pipeline.rewrite_section(project_id, section_id, draft_version_id, review_version_id, rewrite_mode, [])
            rewrite_version_id = int(rewrite["version_id"])
            self._raise_if_automation_cancelled(cancel_event)
            self.store.finalize_section(section_id, rewrite_version_id)
            next_section = None
            next_message = ""
            try:
                next_section = self.pipeline.continue_next_section(section_id)
            except ValueError as exc:
                next_message = str(exc)
            return {
                "draft_version_id": draft_version_id,
                "review_version_id": review_version_id,
                "rewrite_version_id": rewrite_version_id,
                "next_section": next_section,
                "next_message": next_message,
            }

        def start_chapter_automation(self) -> None:
            project_id = self._project_required()
            if not project_id or not self.current_chapter_id or not self.current_section_id:
                self._error("请先选择章节和小节")
                return
            if self._async_busy:
                self._error("已有后台任务运行中，请稍候")
                return
            cancel_event = threading.Event()
            self.automation_cancel_event = cancel_event
            self._run_async(
                lambda: self._run_chapter_writing_automation(
                    project_id,
                    int(self.current_chapter_id),
                    int(self.current_section_id),
                    self.rewrite_mode.currentText(),
                    cancel_event,
                    self.structure_auto_next_chapter_enabled.isChecked(),
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

        def _run_chapter_writing_automation(
            self,
            project_id: int,
            chapter_id: int,
            start_section_id: int,
            rewrite_mode: str,
            cancel_event: threading.Event,
            auto_next_chapter: bool = False,
        ) -> dict[str, Any]:
            processed: list[int] = []
            section_id = start_section_id
            while True:
                self._raise_if_automation_cancelled(cancel_event)
                section = self.store.get_section(section_id)
                if not section or int(section["chapter_id"]) != int(chapter_id):
                    break
                result = self._run_writing_automation(project_id, section_id, rewrite_mode, cancel_event)
                processed.append(section_id)
                next_section = result.get("next_section")
                if isinstance(next_section, dict) and int(next_section.get("chapter_id", chapter_id)) == int(chapter_id):
                    section_id = int(next_section["id"])
                    continue
                try:
                    self.pipeline.write_chapter_memory(project_id, chapter_id)
                except Exception:
                    pass
                if auto_next_chapter:
                    next_chapter_section = self._first_section_in_next_chapter(project_id, chapter_id)
                    if next_chapter_section is not None:
                        chapter_id = int(next_chapter_section["chapter_id"])
                        section_id = int(next_chapter_section["id"])
                        continue
                return {"processed": processed, "last_section_id": section_id, "next_section": None}
            return {"processed": processed, "last_section_id": section_id, "next_section": None}

        def _first_section_in_next_chapter(self, project_id: int, chapter_id: int) -> dict[str, Any] | None:
            chapters = self.store.list_chapters(project_id)
            current_index = next((i for i, chapter in enumerate(chapters) if int(chapter["id"]) == int(chapter_id)), None)
            if current_index is None:
                return None
            for chapter in chapters[current_index + 1 :]:
                sections = self.store.list_sections(int(chapter["id"]))
                if sections:
                    return sections[0]
            return None

        def _after_chapter_automation(self, result: dict[str, Any]) -> str:
            self.automation_cancel_event = None
            self.refresh_versions()
            self.refresh_structure()
            self.refresh_world_items()
            self.refresh_logs()
            last_section_id = result.get("last_section_id") if isinstance(result, dict) else None
            if last_section_id:
                self._select_next_section_for_writing(int(last_section_id))
            processed = result.get("processed", []) if isinstance(result, dict) else []
            return f"章节自动化写作完成，已处理 {len(processed)} 节"

        def write_current_chapter_memory(self) -> None:
            project_id = self._project_required()
            if not project_id or not self.current_chapter_id:
                self._error("请先选择章节")
                return
            self._run_async(
                lambda: self.pipeline.write_chapter_memory(project_id, self.current_chapter_id),
                "正在总结本章并更新资料库...",
                "本章资料库记忆已更新",
                lambda _result: self._after_writing_task(),
            )

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
            except Exception as exc:
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
            self.stack.setCurrentWidget(self.writing_page)
            return True

        def _after_writing_automation(self, result: dict[str, Any]) -> str:
            self.refresh_versions()
            self.refresh_structure()
            self.refresh_logs()
            next_section = result.get("next_section") if isinstance(result, dict) else None
            if isinstance(next_section, dict) and self.structure_auto_next_enabled.isChecked():
                self._select_next_section_for_writing(int(next_section["id"]))
                return "自动化写作完成，已切换到下一节"
            message = str(result.get("next_message", "") if isinstance(result, dict) else "").strip()
            return f"自动化写作完成，{message}" if message else "自动化写作完成"

        def _raise_if_automation_cancelled(self, cancel_event: threading.Event | None) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("用户已中断自动化写作")

        def refresh_versions(self) -> None:
            self.version_list.clear()
            self.current_version_ids = []
            self.version_rows = []
            if not self.current_project_id or not self.current_section_id:
                return
            self.version_rows = self.store.list_versions(self.current_project_id, section_id=self.current_section_id)
            for index, row in enumerate(self.version_rows, 1):
                self.current_version_ids.append(int(row["id"]))
                item = QListWidgetItem(f"{index} | {row['kind']} | {row['status']} | {row['label']}")
                item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                self.version_list.addItem(item)

        def show_selected_version(self) -> None:
            version_id = self._single_selected_version()
            if not version_id:
                return
            row = self.store.get_version(version_id)
            self.version_text.setPlainText(row.get("content", "") if row else "")

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
            self.version_text.setPlainText("\n".join(diff))

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
            current = {key: self._config_value(key) for key in self.config_vars}
            self._run_async(
                lambda: LLMClient(config).discover_models(),
                "正在扫描模型，请稍候...",
                "模型扫描完成",
                lambda discovery: self._apply_model_scan_results(current, discovery),
            )

        def _apply_model_scan_results(self, current: dict[str, str], discovery: dict[str, Any]) -> bool:
            models = [str(model) for model in discovery.get("models", []) if str(model)]
            self.model_scan_text.setPlainText(format_model_discovery_result(discovery))
            for key, value in model_scan_autofill(current, models).items():
                self._set_text(self.config_vars[key], value)
            warning = str(discovery.get("warning", "") or "")
            self.refresh_logs()
            self._ok(f"已扫描到 {len(models)} 个模型" + ("，有警告" if warning else ""))
            return False

        def _config_value(self, key: str) -> str:
            return self._text(self.config_vars[key])

        def _llm_config_from_vars(self) -> dict[str, Any]:
            return build_llm_config_from_vars(
                {key: _ValueAdapter(self._config_value(key)) for key in self.config_vars}
            )

        def refresh_logs(self) -> None:
            rows = self.store.list_llm_call_logs()
            self.logs_text.clear()
            for row in rows:
                self.logs_text.append(
                    f"[{row['created_at']}] {row['agent_name']} success={row['success']} error={row['error'] or ''}\n"
                    f"请求：{row['request_summary']}\n响应：{row['response_summary']}\n"
                )

        def refresh_all_project_views(self) -> None:
            self.refresh_outline_versions()
            self.refresh_world_items()
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
            return [int(item.data(Qt.ItemDataRole.UserRole)) for item in self.version_list.selectedItems()]

        def _run_async(self, action, running: str, success: str, after_success=None) -> None:
            if self._async_busy:
                self._error("已有后台任务运行中，请稍候")
                return
            self._async_busy = True
            self._ok(running)

            def worker() -> None:
                try:
                    result = action()
                except Exception as exc:
                    self.bridge.error.emit(str(exc))
                else:
                    self.bridge.success.emit(success, after_success, result)

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
            self.status_label.setText(message)

        def _error(self, message: str) -> None:
            self.status_label.setText(message)
            QMessageBox.critical(self.window, "错误", message)

        @staticmethod
        def _loads(raw: str | None) -> Any:
            if not raw:
                return []
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return []

else:

    class NovelDesktopUI:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(_install_message())

        def run(self) -> None:
            raise RuntimeError(_install_message())
