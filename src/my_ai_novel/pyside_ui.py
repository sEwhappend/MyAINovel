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
from .style_tags import (
    DIALOGUE_QUOTE_STYLES,
    FIELD_TO_CATEGORY,
    list_style_tag_catalog,
    normalize_tag_ids,
)
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
from .world_modules import (
    character_basic_fields_from_details,
    dump_details,
    update_character_basic_fields,
)

try:
    from PySide6.QtCore import QRect, QObject, QSize, Qt, Signal
    from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QTextCursor
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSizePolicy,
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
    QProgressBar#LlmProgress {
        min-height: 8px;
        max-height: 8px;
        border: 1px solid #dce6f2;
        border-radius: 4px;
        background: #ffffff;
        text-align: center;
    }
    QProgressBar#LlmProgress::chunk {
        border-radius: 4px;
        background: #f6b7c9;
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
        # 项目书架布局参数
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


    class SearchProjectCreationDialog(QDialog):
        def __init__(self, owner: "NovelDesktopUI") -> None:
            super().__init__(owner.window)
            self.owner = owner
            self.candidates: list[dict[str, Any]] = []
            self.tag_checks: dict[str, dict[str, QCheckBox]] = {}
            self.setWindowTitle("像找小说一样创建项目")
            layout = QVBoxLayout(self)
            self.query_input = QLineEdit()
            self.query_input.setPlaceholderText("输入想看/想写的小说方向，例如：异世界转移 TS 等级成长 轻小说 不要后宫")
            layout.addWidget(QLabel("搜索式需求"))
            layout.addWidget(self.query_input)

            controls = QHBoxLayout()
            self.reader_combo = QComboBox()
            self.reader_combo.addItems(["青少年向", "少女向", "青年向", "轻小说向", "成人向"])
            self.pov_combo = QComboBox()
            self.pov_combo.addItems(["第三人称有限视角", "第一人称", "多视角", "主角视角"])
            controls.addWidget(QLabel("读者"))
            controls.addWidget(self.reader_combo)
            controls.addWidget(QLabel("视角"))
            controls.addWidget(self.pov_combo)
            controls.addStretch(1)
            layout.addLayout(controls)

            body = QHBoxLayout()
            filter_column = QVBoxLayout()
            filter_column.addWidget(QLabel("标签/排除项"))
            self._build_tag_checks(filter_column)
            self.exclude_input = QLineEdit()
            self.exclude_input.setPlaceholderText("排除项，用逗号分隔，例如：不要系统,不要后宫")
            filter_column.addWidget(QLabel("排除项"))
            filter_column.addWidget(self.exclude_input)
            open_tags = QPushButton("打开现有标签选择")
            open_tags.clicked.connect(self._open_existing_tag_selector)
            filter_column.addWidget(open_tags)
            filter_column.addStretch(1)
            body.addLayout(filter_column, 1)

            result_column = QVBoxLayout()
            self.candidate_list = QListWidget()
            self.candidate_list.currentRowChanged.connect(lambda _row: self._show_candidate_detail())
            generate_button = QPushButton("生成候选")
            generate_button.setProperty("primary", True)
            generate_button.clicked.connect(self._generate_candidates)
            result_column.addWidget(generate_button)
            result_column.addWidget(QLabel("候选方案"))
            result_column.addWidget(self.candidate_list, 1)
            body.addLayout(result_column, 1)

            detail_column = QVBoxLayout()
            self.detail_text = QTextEdit()
            self.detail_text.setReadOnly(True)
            use_button = QPushButton("用这个创建项目")
            use_button.setProperty("primary", True)
            use_button.clicked.connect(self._use_selected_candidate)
            similar_button = QPushButton("生成相似方案")
            similar_button.clicked.connect(self._generate_candidates)
            detail_column.addWidget(QLabel("详情与操作"))
            detail_column.addWidget(self.detail_text, 1)
            detail_column.addWidget(use_button)
            detail_column.addWidget(similar_button)
            body.addLayout(detail_column, 1)
            layout.addLayout(body, 1)

            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            owner._resize_dialog_to_window(self)

        def _build_tag_checks(self, layout: QVBoxLayout) -> None:
            catalog = list_style_tag_catalog()
            labels = {
                "selected_genre_tags": "题材标签",
                "selected_setting_tags": "设定标签",
                "selected_structure_tags": "结构标签",
                "selected_style_tags": "风格标签",
            }
            for field, category in FIELD_TO_CATEGORY.items():
                layout.addWidget(QLabel(labels.get(field, field)))
                row = QVBoxLayout()
                self.tag_checks[field] = {}
                selected = set(getattr(self.owner, "project_tag_selection", {}).get(field, []))
                for tag in catalog.get(category, []):
                    tag_id = str(tag.get("id", ""))
                    checkbox = QCheckBox(str(tag.get("label", tag_id)))
                    checkbox.setToolTip(str(tag.get("usage_rule", "") or tag.get("style_rule", "")))
                    checkbox.setChecked(tag_id in selected)
                    self.tag_checks[field][tag_id] = checkbox
                    row.addWidget(checkbox)
                layout.addLayout(row)

        def _open_existing_tag_selector(self) -> None:
            self.owner.edit_project_tags_dialog()
            current = getattr(self.owner, "project_tag_selection", {})
            for field, field_checks in self.tag_checks.items():
                selected = set(current.get(field, []))
                for tag_id, checkbox in field_checks.items():
                    checkbox.setChecked(tag_id in selected)

        def _generation_profile(self) -> dict[str, Any]:
            return {
                "search_query": self.query_input.text().strip(),
                "selected_tags": {
                    field: [tag_id for tag_id, checkbox in checks.items() if checkbox.isChecked()]
                    for field, checks in self.tag_checks.items()
                },
                "exclude_tags": [
                    item.strip()
                    for item in self.exclude_input.text().replace("，", ",").split(",")
                    if item.strip()
                ],
                "target_readers": self.reader_combo.currentText().strip(),
                "pov": self.pov_combo.currentText().strip(),
            }

        def _generate_candidates(self) -> None:
            profile = self._generation_profile()
            self.candidates = self.owner._generate_search_creation_candidates(profile)
            self.candidate_list.clear()
            for candidate in self.candidates:
                title = str(candidate.get("temporary_title") or candidate.get("title") or "未命名候选")
                hook = str(candidate.get("one_line_hook") or candidate.get("hook") or "")
                self.candidate_list.addItem(f"{title}\n{hook}")
            if self.candidates:
                self.candidate_list.setCurrentRow(0)

        def _show_candidate_detail(self) -> None:
            candidate = self.owner._selected_row(self.candidate_list, self.candidates)
            if not candidate:
                self.detail_text.setPlainText("")
                return
            tags = candidate.get("tags", [])
            if isinstance(tags, list):
                tags_text = "、".join(str(tag) for tag in tags)
            else:
                tags_text = str(tags or "")
            lines = [
                str(candidate.get("temporary_title") or candidate.get("title") or "未命名候选"),
                str(candidate.get("one_line_hook") or ""),
                f"标签：{tags_text}",
                f"读者：{candidate.get('target_readers', '')}",
                f"视角：{candidate.get('pov', '')}",
                "",
                f"故事开局：{candidate.get('story_start', '')}",
                f"世界方向：{candidate.get('world_direction', '')}",
                f"主角方向：{candidate.get('main_character_direction', '')}",
                f"关系方向：{candidate.get('relationship_direction', '')}",
                f"风格方向：{candidate.get('style_direction', '')}",
                "",
                "状态记忆要求：",
                *[f"- {item}" for item in candidate.get("stateful_requirements", [])],
                "风险提示：",
                *[f"- {item}" for item in candidate.get("risk_notes", [])],
            ]
            self.detail_text.setPlainText("\n".join(lines))

        def _use_selected_candidate(self) -> None:
            candidate = self.owner._selected_row(self.candidate_list, self.candidates)
            if not candidate:
                self.owner._error("请先生成并选择一个候选方案")
                return
            self.owner._apply_search_candidate_to_project(candidate, self._generation_profile())
            self.accept()


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
            self.project_tag_selection: dict[str, list[str]] = {}
            self.dialogue_quote_style_value = "cn_quotes"
            self.pending_generation_profile_json = ""
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
            self.llm_progress = QProgressBar()
            self.llm_progress.setObjectName("LlmProgress")
            self.llm_progress.setRange(0, 0)
            self.llm_progress.setTextVisible(False)
            self.llm_progress.setVisible(False)
            layout.addWidget(self.llm_progress)
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

        def _resize_dialog_to_window(self, dialog: QDialog) -> None:
            size = self.window.size()
            if size.isValid():
                dialog.resize(size)

        def _build_project_page(self) -> None:
            page = self._add_page("项目")
            self.project_page = page
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
            left.addWidget(self._button("新建空白项目", self.start_new_project))
            left.addWidget(self._button("像找小说一样创建", self.open_search_project_creation_dialog))
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
            self._build_project_tag_controls(right)
            actions = QHBoxLayout()
            for text, callback in [
                ("保存项目", self.save_project),
                ("打开项目文件夹", self.open_project_folder),
                ("导出全书 Word", self.export_full_book_word),
            ]:
                actions.addWidget(self._button(text, callback))
            right.addLayout(actions)
            layout.addWidget(right_frame, 1)

        def _build_project_tag_controls(self, parent: QVBoxLayout) -> None:
            self.project_tag_summary = QLabel("未选择标签；对白引号：中文弯引号")
            parent.addWidget(self.project_tag_summary)
            parent.addWidget(self._button("选择标签与引号", self.edit_project_tags_dialog))

        def _build_outline_page(self) -> None:
            page = self._add_page("总框架")
            self.outline_page = page
            layout = QHBoxLayout(page)
            left = QVBoxLayout()
            self.outline_mode = QComboBox()
            self.outline_mode.addItems(["整书模式", "连载模式"])
            self.outline_mode.currentTextChanged.connect(lambda _text: self._sync_outline_mode_fields())
            left.addWidget(QLabel("规划模式"))
            left.addWidget(self.outline_mode)
            self.serial_action = QComboBox()
            self.serial_action.addItems(["修改当前连载大纲", "生成下一部分大纲"])
            self.serial_action.currentTextChanged.connect(lambda _text: self._sync_outline_mode_fields())
            left.addWidget(QLabel("连载操作"))
            left.addWidget(self.serial_action)
            self.outline_planning_fields: dict[str, QLineEdit] = {}
            for label, key in [
                ("总目标字数/本次规划字数", "planning_target_words"),
                ("预计全书/本次章节数", "planning_chapter_count"),
                ("默认每章目标字数", "default_chapter_target_words"),
            ]:
                left.addWidget(QLabel(label))
                widget = QLineEdit()
                self.outline_planning_fields[key] = widget
                left.addWidget(widget)
            left.addWidget(QLabel("单章节约几个小节"))
            self.outline_planning_fields["section_count_approx"] = QLineEdit()
            left.addWidget(self.outline_planning_fields["section_count_approx"])
            left.addWidget(QLabel("本次规划说明"))
            self.outline_planning_note = QTextEdit()
            self.outline_planning_note.setMinimumHeight(72)
            left.addWidget(self.outline_planning_note)
            for text, callback in [
                ("生成/修改大纲", self.expand_outline),
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
            self._sync_outline_mode_fields()

        def _build_world_page(self) -> None:
            page = self._add_page("资料库")
            self.world_page = page
            layout = QHBoxLayout(page)
            splitter = QSplitter(Qt.Orientation.Horizontal)
            layout.addWidget(splitter)
            left_panel = QWidget()
            left = QVBoxLayout(left_panel)
            self.world_kind = QComboBox()
            self.world_kind.addItems([world_kind_label(kind) for kind in sorted(WORLD_ITEM_KINDS)])
            self.world_kind.setCurrentText(world_kind_label("character"))
            self.world_kind.currentTextChanged.connect(lambda _text: self._on_world_kind_changed())
            left.addWidget(self.world_kind)
            self.world_list = QListWidget()
            self.world_list.setObjectName("WorldList")
            self.world_list.currentRowChanged.connect(lambda _row: self.select_world_item())
            left.addWidget(self.world_list, 1)
            left.addWidget(self._button("AI 自动创建资料", self.create_world_item_with_ai))
            left.addWidget(self._button("手动创建资料", self.new_world_item))
            left.addWidget(self._button("刷新资料库", self.refresh_world_items))
            splitter.addWidget(left_panel)

            right_panel = QWidget()
            right = QVBoxLayout(right_panel)
            self.world_name = QLineEdit()
            self.world_tags = QLineEdit()
            right.addWidget(QLabel("名称"))
            right.addWidget(self.world_name)
            right.addWidget(QLabel("标签"))
            right.addWidget(self.world_tags)
            self.character_basic_frame = QFrame()
            character_basic = QVBoxLayout(self.character_basic_frame)
            self.character_basic_summary = QLabel("角色卡基础信息未设置")
            self.character_basic_summary.setWordWrap(True)
            self.character_basic_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            character_basic.addWidget(self.character_basic_summary)
            character_basic.addWidget(self._button("编辑角色卡基础信息", self.edit_character_basic_dialog))
            right.addWidget(self.character_basic_frame)
            right.addWidget(QLabel("摘要"))
            self.world_summary = QTextEdit()
            right.addWidget(self.world_summary, 1)
            actions = QHBoxLayout()
            for text, callback in [
                ("保存资料", self.save_world_item),
                ("删除资料", self.delete_world_item),
                ("查看/编辑完整 JSON", self.edit_world_details_json),
                ("AI 自动补充设定", self.enrich_selected_world_item),
            ]:
                actions.addWidget(self._button(text, callback))
            right.addLayout(actions)
            splitter.addWidget(right_panel)
            splitter.setStretchFactor(0, 1)
            splitter.setStretchFactor(1, 2)
            splitter.setSizes([320, 680])
            self._sync_world_character_form_visibility()

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

        def _set_world_kind_safely(self, kind_or_label: Any) -> None:
            raw_value = str(kind_or_label or "character")
            kind = world_kind_value(raw_value)
            label = world_kind_label(kind)
            self._updating_world_kind = True
            previous = self.world_kind.blockSignals(True)
            try:
                self.world_kind.setCurrentText(label)
            finally:
                self.world_kind.blockSignals(previous)
                self._updating_world_kind = False

        def _project_tag_data(self) -> dict[str, str]:
            data: dict[str, str] = {}
            for field in FIELD_TO_CATEGORY:
                data[field] = json.dumps(
                    list(getattr(self, "project_tag_selection", {}).get(field, [])),
                    ensure_ascii=False,
                )
            data["dialogue_quote_style"] = getattr(self, "dialogue_quote_style_value", "cn_quotes")
            return data

        def _set_project_tag_data(self, project: dict[str, Any]) -> None:
            self.project_tag_selection = {
                field: normalize_tag_ids(project.get(field))
                for field in FIELD_TO_CATEGORY
            }
            self.dialogue_quote_style_value = str(project.get("dialogue_quote_style") or "cn_quotes")
            self._update_project_tag_summary()

        def _clear_project_tag_data(self) -> None:
            self._set_project_tag_data({})

        def _update_project_tag_summary(self) -> None:
            if not hasattr(self, "project_tag_summary"):
                return
            catalog = list_style_tag_catalog()
            label_by_id = {
                str(tag.get("id", "")): str(tag.get("label", tag.get("id", "")))
                for tags in catalog.values()
                for tag in tags
            }
            selected_labels = [
                label_by_id.get(tag_id, tag_id)
                for values in getattr(self, "project_tag_selection", {}).values()
                for tag_id in values
            ]
            quote = DIALOGUE_QUOTE_STYLES.get(
                getattr(self, "dialogue_quote_style_value", "cn_quotes"),
                DIALOGUE_QUOTE_STYLES["cn_quotes"],
            )
            tags_text = "、".join(selected_labels) if selected_labels else "未选择标签"
            self.project_tag_summary.setText(f"{tags_text}；对白引号：{quote['label']}")

        def edit_project_tags_dialog(self) -> None:
            dialog = QDialog(self.window)
            dialog.setWindowTitle("选择标签与引号")
            layout = QVBoxLayout(dialog)
            catalog = list_style_tag_catalog()
            labels = {
                "selected_genre_tags": "题材标签",
                "selected_setting_tags": "设定标签",
                "selected_structure_tags": "结构标签",
                "selected_style_tags": "风格标签",
            }
            checks: dict[str, dict[str, QCheckBox]] = {}
            current_selection = getattr(self, "project_tag_selection", {})
            for field, category in FIELD_TO_CATEGORY.items():
                layout.addWidget(QLabel(labels.get(field, field)))
                row = QHBoxLayout()
                checks[field] = {}
                selected = set(current_selection.get(field, []))
                for tag in catalog.get(category, []):
                    tag_id = str(tag.get("id", ""))
                    checkbox = QCheckBox(str(tag.get("label", tag_id)))
                    checkbox.setToolTip(str(tag.get("usage_rule", "") or tag.get("style_rule", "")))
                    checkbox.setChecked(tag_id in selected)
                    checks[field][tag_id] = checkbox
                    row.addWidget(checkbox)
                row.addStretch(1)
                layout.addLayout(row)
            layout.addWidget(QLabel("对白引号"))
            quote_combo = QComboBox()
            for quote_id, item in DIALOGUE_QUOTE_STYLES.items():
                quote_combo.addItem(str(item["label"]), quote_id)
            quote_index = quote_combo.findData(getattr(self, "dialogue_quote_style_value", "cn_quotes"))
            quote_combo.setCurrentIndex(quote_index if quote_index >= 0 else 0)
            layout.addWidget(quote_combo)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.project_tag_selection = {
                field: [tag_id for tag_id, checkbox in field_checks.items() if checkbox.isChecked()]
                for field, field_checks in checks.items()
            }
            self.dialogue_quote_style_value = str(quote_combo.currentData() or "cn_quotes")
            self._update_project_tag_summary()

        def open_search_project_creation_dialog(self) -> None:
            dialog = SearchProjectCreationDialog(self)
            dialog.exec()

        def _generate_search_creation_candidates(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
            for method_name in (
                "generate_novel_candidates",
                "generate_search_project_candidates",
                "novel_candidate_generator",
            ):
                if not hasattr(self.pipeline, method_name):
                    continue
                method = getattr(self.pipeline, method_name, None)
                if not callable(method):
                    continue
                result = method(profile)
                candidates = result.get("candidates", result) if isinstance(result, dict) else result
                if isinstance(candidates, list) and candidates:
                    return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]
            return self._fallback_search_creation_candidates(profile)

        def _fallback_search_creation_candidates(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
            query = str(profile.get("search_query") or "").strip() or "未指定搜索式"
            selected_tags = profile.get("selected_tags", {})
            tag_ids = [
                tag_id
                for values in selected_tags.values()
                if isinstance(values, list)
                for tag_id in values
            ] if isinstance(selected_tags, dict) else []
            tags = tag_ids[:6] or ["original", "draft"]
            exclusions = profile.get("exclude_tags", [])
            exclude_text = "、".join(str(item) for item in exclusions) if isinstance(exclusions, list) else str(exclusions or "")
            reader = str(profile.get("target_readers") or "轻小说向")
            pov = str(profile.get("pov") or "第三人称有限视角")
            return [
                {
                    "temporary_title": f"{query[:18]}：候选方案 {index}",
                    "one_line_hook": f"围绕“{query}”生成的原创小说方向，保留人工可编辑空间。",
                    "tags": tags,
                    "target_readers": reader,
                    "pov": pov,
                    "story_start": f"主角在与“{query}”相关的异常事件中被迫做出第一个选择。",
                    "main_character_direction": "谨慎但有行动力，初期目标清晰，能力与关系随事件逐步变化。",
                    "world_direction": "世界规则围绕搜索式需求展开，关键设定通过事件逐步揭示。",
                    "relationship_direction": "核心关系从互相试探开始，随着共同风险逐步建立信任。",
                    "style_direction": f"节奏服务于{reader}阅读体验；排除项：{exclude_text or '无'}。",
                    "stateful_requirements": ["重要身份、能力、关系变化需要进入资料库或后续回写。"],
                    "risk_notes": ["当前为 UI 兼容占位候选；接入 pipeline 后应由模型生成更完整候选。"],
                }
                for index in range(1, 4)
            ]

        def _candidate_project_draft(self, candidate: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
            for method_name in ("candidate_to_project_draft", "candidate_to_project_fields", "novel_candidate_to_project_fields"):
                if not hasattr(self.pipeline, method_name):
                    continue
                method = getattr(self.pipeline, method_name, None)
                if callable(method):
                    result = method(candidate, profile)
                    if isinstance(result, dict):
                        return dict(result)
            tags = candidate.get("tags", [])
            tags_text = "、".join(str(tag) for tag in tags) if isinstance(tags, list) else str(tags or "")
            return {
                "title": str(candidate.get("temporary_title") or candidate.get("title") or ""),
                "genre": tags_text,
                "style": str(candidate.get("style_direction") or ""),
                "target_readers": str(candidate.get("target_readers") or profile.get("target_readers") or ""),
                "pov": str(candidate.get("pov") or profile.get("pov") or ""),
                "world_summary": str(candidate.get("world_direction") or ""),
                "writing_style_guide": "\n".join(
                    part
                    for part in [
                        str(candidate.get("style_direction") or ""),
                        *[f"状态记忆：{item}" for item in candidate.get("stateful_requirements", [])],
                        *[f"风险提示：{item}" for item in candidate.get("risk_notes", [])],
                    ]
                    if part
                ),
                "global_concept": "\n".join(
                    part
                    for part in [
                        str(candidate.get("one_line_hook") or ""),
                        f"故事开局：{candidate.get('story_start', '')}",
                        f"主角方向：{candidate.get('main_character_direction', '')}",
                        f"关系方向：{candidate.get('relationship_direction', '')}",
                    ]
                    if part
                ),
            }

        def _apply_search_candidate_to_project(self, candidate: dict[str, Any], profile: dict[str, Any]) -> None:
            draft = self._candidate_project_draft(candidate, profile)
            profile_payload = {
                "creation_mode": "candidate",
                **profile,
                "selected_candidate": candidate,
            }
            draft["generation_profile_json"] = profile_payload
            self.pending_generation_profile_json = json.dumps(profile_payload, ensure_ascii=False, indent=2)
            self.current_project_id = None
            for key, widget in self.project_fields.items():
                if key in draft:
                    self._set_text(widget, draft.get(key, ""))
            for key, widget in self.project_texts.items():
                if key in draft:
                    self._set_text(widget, draft.get(key, ""))
            selected_tags = profile.get("selected_tags", {})
            if isinstance(selected_tags, dict):
                self.project_tag_selection = {
                    field: normalize_tag_ids(selected_tags.get(field))
                    for field in FIELD_TO_CATEGORY
                }
                self._update_project_tag_summary()
            self.project_list.clearSelection()
            self._ok("已根据候选填充项目字段和标签；尚未保存，可继续修改后手动保存。")

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
            self.project_list.blockSignals(True)
            try:
                self.project_list.clear()
                for project in self.projects:
                    item = QListWidgetItem(self._project_shelf_label(project))
                    item.setSizeHint(QSize(176, 252))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    item.setToolTip(f"{project['id']} | {project['title']}")
                    item.setData(Qt.ItemDataRole.UserRole, int(project["id"]))
                    self.project_list.addItem(item)
            finally:
                self.project_list.blockSignals(False)
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
            self._set_project_tag_data(project)
            self.pending_generation_profile_json = str(project.get("generation_profile_json", "") or "")
            self._load_outline_planning_defaults(project)
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
            self._clear_project_tag_data()
            self.pending_generation_profile_json = ""
            self._clear_outline_planning_fields()
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
                self._set_world_kind_safely("character")
            self.world_name.clear()
            self.world_tags.clear()
            self.world_summary.clear()
            self._clear_character_basic_form()
            self._sync_world_character_form_visibility()

        def _clear_character_basic_form(self) -> None:
            if hasattr(self, "character_basic_summary"):
                self.character_basic_summary.setText("角色卡基础信息未设置")

        def _sync_world_character_form_visibility(self) -> None:
            if hasattr(self, "character_basic_frame"):
                self.character_basic_frame.setVisible(world_kind_value(self.world_kind.currentText()) == "character")

        def _fill_character_basic_form(self, details_json: Any) -> None:
            fields = character_basic_fields_from_details(details_json)
            parts = [
                str(fields.get("identity", "") or "").strip(),
                str(fields.get("personality", "") or "").strip(),
                str(fields.get("motivation", "") or "").strip(),
                str(fields.get("speech_style", "") or "").strip(),
                self._character_role_label(fields.get("role_flags", {})),
            ]
            text = " / ".join(part for part in parts if part)
            if hasattr(self, "character_basic_summary"):
                self.character_basic_summary.setText(text or "角色卡基础信息未设置")

        def _world_details_from_form(self) -> str:
            return self.current_world_details_json

        def _character_role_options(self) -> list[tuple[str, str]]:
            return [
                ("", "未指定"),
                ("protagonist", "主角"),
                ("pov", "POV"),
                ("ensemble_main", "群像主要角色"),
                ("supporting", "重要配角"),
            ]

        def _character_role_key(self, role_flags: Any) -> str:
            if not isinstance(role_flags, dict):
                return ""
            for key, _label in self._character_role_options():
                if key and role_flags.get(key):
                    return key
            return ""

        def _character_role_label(self, role_flags: Any) -> str:
            selected = self._character_role_key(role_flags)
            for key, label in self._character_role_options():
                if key == selected:
                    return label if key else ""
            return ""

        def _single_character_role_flags(self, selected_key: str) -> dict[str, bool]:
            return {
                key: bool(key and key == selected_key)
                for key, _label in self._character_role_options()
                if key
            }

        def edit_character_basic_dialog(self) -> None:
            if world_kind_value(self.world_kind.currentText()) != "character":
                self._error("只有角色卡可以编辑角色卡基础信息")
                return
            fields = character_basic_fields_from_details(self.current_world_details_json)
            dialog = QDialog(self.window)
            dialog.setWindowTitle("编辑角色卡基础信息")
            layout = QVBoxLayout(dialog)
            form = QFormLayout()
            editors: dict[str, QLineEdit] = {}
            for label, key in [
                ("身份", "identity"),
                ("性格", "personality"),
                ("动机", "motivation"),
                ("说话风格", "speech_style"),
            ]:
                editor = QLineEdit()
                editor.setText(str(fields.get(key, "") or ""))
                editors[key] = editor
                form.addRow(label, editor)
            role_combo = QComboBox()
            selected_role = self._character_role_key(fields.get("role_flags", {}))
            for key, label in self._character_role_options():
                role_combo.addItem(label, key)
            role_index = role_combo.findData(selected_role)
            role_combo.setCurrentIndex(role_index if role_index >= 0 else 0)
            form.addRow("角色定位", role_combo)
            layout.addLayout(form)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            self._resize_dialog_to_window(dialog)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            details = update_character_basic_fields(
                self.current_world_details_json,
                identity=editors["identity"].text(),
                personality=editors["personality"].text(),
                motivation=editors["motivation"].text(),
                speech_style=editors["speech_style"].text(),
                role_flags=self._single_character_role_flags(str(role_combo.currentData() or "")),
            )
            self.current_world_details_json = dump_details(details)
            self._fill_character_basic_form(self.current_world_details_json)
            self._ok("角色卡基础信息已更新，点击保存资料后落盘")

        def save_project(self) -> None:
            data = {key: self._text(widget) for key, widget in self.project_fields.items()}
            data.update({key: self._text(widget) for key, widget in self.project_texts.items()})
            data.update(self._project_tag_data())
            if getattr(self, "pending_generation_profile_json", ""):
                data["generation_profile_json"] = self.pending_generation_profile_json
            if not data["title"]:
                self._error("项目名称不能为空")
                return
            if self.current_project_id:
                self.store.update_project(self.current_project_id, data)
                saved_project_id = self.current_project_id
            else:
                saved_project_id = self.store.create_project(data)
                self.current_project_id = saved_project_id
            self.refresh_projects()
            self.current_project_id = saved_project_id
            self.select_project_by_id(saved_project_id)
            opened_character_setup = self._prompt_main_character_setup_after_save()
            if opened_character_setup:
                self._ok("项目已保存，请在资料库创建主要角色卡")
            else:
                self._ok("项目已保存")

        def _prompt_main_character_setup_after_save(self) -> bool:
            project_id = self.current_project_id
            if not project_id:
                return False
            if self.pipeline.main_character_cards(project_id):
                return False
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("先准备主要角色")
            dialog.setIcon(QMessageBox.Icon.Information)
            dialog.setText("当前项目还没有主要角色卡。是否先去资料库创建主要角色，再继续丰满总体框架？")
            go_button = dialog.addButton("去资料库创建主要角色", QMessageBox.ButtonRole.AcceptRole)
            dialog.addButton("暂不创建，直接继续", QMessageBox.ButtonRole.RejectRole)
            dialog.setDefaultButton(go_button)
            dialog.exec()
            if dialog.clickedButton() is go_button:
                self._handle_main_character_setup_choice()
                return True
            return False

        def _handle_main_character_setup_choice(self) -> None:
            self._open_character_card_setup()
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("创建主要角色")
            dialog.setIcon(QMessageBox.Icon.Question)
            dialog.setText("是否自动调用 API，根据当前项目信息生成一个默认主要角色卡？")
            auto_button = dialog.addButton("自动生成默认主要角色", QMessageBox.ButtonRole.AcceptRole)
            dialog.addButton("我自己创建", QMessageBox.ButtonRole.RejectRole)
            dialog.setDefaultButton(auto_button)
            dialog.exec()
            if dialog.clickedButton() is auto_button:
                project_id = self.current_project_id
                if not project_id:
                    return
                self._run_async(
                    lambda: self.pipeline.generate_default_main_character(project_id),
                    "正在生成默认主要角色卡，请稍候...",
                    "默认主要角色卡已生成",
                    self._after_generate_default_main_character,
                )

        def _open_character_card_setup(self) -> None:
            self.stack.setCurrentWidget(self.world_page)
            index = self.stack.indexOf(self.world_page)
            if index >= 0:
                self.navigation.setCurrentRow(index)
            self._set_world_kind_safely("character")
            self._clear_world_form(reset_kind=False)
            self._sync_world_character_form_visibility()
            self.world_name.setFocus()

        def _after_generate_default_main_character(self, result: dict[str, Any]) -> str:
            item = result.get("world_item", {}) if isinstance(result, dict) else {}
            if isinstance(item, dict):
                self._fill_world_item_form(item)
            self.refresh_world_items()
            self.refresh_logs()
            return "默认主要角色卡已生成，可继续编辑后再丰满总体框架"

        def _fill_world_item_form(self, item: dict[str, Any]) -> None:
            self.current_world_item_id = int(item.get("id", item.get("world_item_id", 0)) or 0) or self.current_world_item_id
            self.current_world_details_json = item.get("details_json") or json.dumps(
                item.get("details", {}),
                ensure_ascii=False,
                indent=2,
            )
            self._set_world_kind_safely(str(item.get("kind", "character")))
            self.world_name.setText(str(item.get("name", "")))
            self.world_tags.setText(str(item.get("tags", "")))
            self.world_summary.setPlainText(str(item.get("summary", "")))
            self._fill_character_basic_form(self.current_world_details_json)
            self._sync_world_character_form_visibility()

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
            metadata["outline_planning"] = self._outline_planning_options()
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
            metadata = self._loads(row.get("metadata_json")) if row else {}
            if isinstance(metadata, dict):
                self._apply_outline_planning_to_ui(metadata.get("outline_planning"))

        def _selected_outline_metadata(self) -> dict[str, Any]:
            version_id = self._selected_outline_version()
            row = self.store.get_version(version_id) if version_id else None
            metadata = self._loads(row.get("metadata_json")) if row else {}
            return metadata if isinstance(metadata, dict) else {}

        def _outline_mode_value(self) -> str:
            return "serial" if self.outline_mode.currentText() == "连载模式" else "full_book"

        def _serial_action_value(self) -> str:
            return "next_part" if self.serial_action.currentText() == "生成下一部分大纲" else "revise_current"

        def _sync_outline_mode_fields(self) -> None:
            if not hasattr(self, "serial_action"):
                return
            is_serial = self._outline_mode_value() == "serial"
            self.serial_action.setEnabled(is_serial)
            if not is_serial:
                self.serial_action.setCurrentText("修改当前连载大纲")

        def _clear_outline_planning_fields(self) -> None:
            if not hasattr(self, "outline_planning_fields"):
                return
            self.outline_mode.setCurrentText("整书模式")
            self.serial_action.setCurrentText("修改当前连载大纲")
            for widget in self.outline_planning_fields.values():
                self._set_text(widget, "")
            self.outline_planning_note.clear()
            self._sync_outline_mode_fields()

        def _load_outline_planning_defaults(self, project: dict[str, Any]) -> None:
            if not hasattr(self, "outline_planning_fields"):
                return
            self._apply_outline_planning_to_ui(
                {
                    "outline_mode": "full_book",
                    "serial_action": "revise_current",
                    "planning_target_words": project.get("length_target", ""),
                    "planning_chapter_count": project.get("estimated_total_sections", ""),
                    "default_chapter_target_words": project.get("default_section_target_words", ""),
                    "section_count_approx": "",
                    "planning_note": "",
                }
            )

        def _apply_outline_planning_to_ui(self, planning: Any) -> None:
            if not hasattr(self, "outline_planning_fields") or not isinstance(planning, dict):
                return
            self.outline_mode.setCurrentText("连载模式" if planning.get("outline_mode") == "serial" else "整书模式")
            self.serial_action.setCurrentText("生成下一部分大纲" if planning.get("serial_action") == "next_part" else "修改当前连载大纲")
            chapter_count = planning.get("planning_chapter_count", planning.get("planning_section_count", ""))
            chapter_words = planning.get("default_chapter_target_words", planning.get("default_section_target_words", ""))
            section_count_approx = planning.get(
                "section_count_approx",
                planning.get("section_count_min", planning.get("section_count_max", "")),
            )
            values = {
                "planning_target_words": planning.get("planning_target_words", ""),
                "planning_chapter_count": chapter_count,
                "default_chapter_target_words": chapter_words,
                "section_count_approx": section_count_approx,
            }
            for key, value in values.items():
                self._set_text(self.outline_planning_fields[key], value)
            self.outline_planning_note.setPlainText(str(planning.get("planning_note", "") or ""))
            self._sync_outline_mode_fields()
            if not self._text(self.outline_planning_fields["default_chapter_target_words"]).strip():
                default_words = calculate_default_section_target_words(
                    self._text(self.outline_planning_fields["planning_target_words"]),
                    self._text(self.outline_planning_fields["planning_chapter_count"]),
                )
                if default_words:
                    self._set_text(self.outline_planning_fields["default_chapter_target_words"], default_words)

        def _outline_planning_options(self) -> dict[str, Any]:
            if not hasattr(self, "outline_planning_fields"):
                return {"outline_mode": "full_book", "serial_action": "revise_current"}
            target_words = self._text(self.outline_planning_fields["planning_target_words"]).strip()
            chapter_count = self._text(self.outline_planning_fields["planning_chapter_count"]).strip()
            default_chapter_words = self._text(self.outline_planning_fields["default_chapter_target_words"]).strip()
            if not default_chapter_words:
                default_chapter_words = calculate_default_section_target_words(target_words, chapter_count)
                if default_chapter_words:
                    self._set_text(self.outline_planning_fields["default_chapter_target_words"], default_chapter_words)
            options: dict[str, Any] = {
                "outline_mode": self._outline_mode_value(),
                "serial_action": self._serial_action_value(),
                "planning_target_words": target_words,
                "planning_chapter_count": chapter_count,
                "default_chapter_target_words": default_chapter_words,
                "section_count_approx": self._text(self.outline_planning_fields["section_count_approx"]).strip(),
                "planning_note": self.outline_planning_note.toPlainText().strip(),
            }
            if options["outline_mode"] == "serial" and options["serial_action"] == "next_part":
                next_number = self._next_chapter_number()
                options["append_after_chapter_number"] = max(0, (next_number or 1) - 1)
            return options

        def _next_chapter_number(self) -> int:
            if not self.current_project_id:
                return 1
            chapter_numbers = [
                int(row.get("number", 0) or 0)
                for row in self.store.list_chapters(self.current_project_id)
            ]
            return (max(chapter_numbers) + 1) if chapter_numbers else 1

        def _selected_outline_version(self) -> int | None:
            row = self._selected_row(self.outline_versions, self.outline_version_rows)
            return int(row["id"]) if row else None

        def save_world_item(self) -> None:
            project_id = self._project_required()
            if not project_id:
                return
            self.current_world_details_json = self._world_details_from_form()
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

        def new_world_item(self) -> None:
            if hasattr(self.world_list, "blockSignals"):
                previous = self.world_list.blockSignals(True)
                try:
                    self.world_list.clearSelection()
                    self.world_list.setCurrentRow(-1)
                finally:
                    self.world_list.blockSignals(previous)
            self._clear_world_form(reset_kind=False)
            self.world_name.setFocus()
            self._ok("已切换到新建资料，填写后点击“保存资料”")

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
            if getattr(self, "_updating_world_kind", False):
                return
            self._clear_world_form(reset_kind=False)
            self._sync_world_character_form_visibility()
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
            self._set_world_kind_safely(item.get("kind", "character"))
            self.world_name.setText(item.get("name", ""))
            self.world_tags.setText(item.get("tags", ""))
            self.world_summary.setPlainText(item.get("summary", ""))
            self._fill_character_basic_form(self.current_world_details_json)
            self._sync_world_character_form_visibility()

        def edit_world_details_json(self) -> None:
            dialog = QDialog(self.window)
            dialog.setWindowTitle("查看/编辑完整 JSON")
            layout = QVBoxLayout(dialog)
            editor = QTextEdit()
            editor.setPlainText(self._world_details_from_form() or "{}")
            layout.addWidget(editor, 1)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            self._resize_dialog_to_window(dialog)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            text = editor.toPlainText().strip()
            try:
                json.loads(text or "{}")
            except json.JSONDecodeError as exc:
                self._error(f"JSON 格式错误：{exc}")
                return
            self.current_world_details_json = text or "{}"
            self._fill_character_basic_form(self.current_world_details_json)
            self._ok("完整 JSON 已更新，点击保存资料后落盘")

        def create_world_item_with_ai(self) -> None:
            project_id = self._project_required()
            if not project_id:
                return
            kind = world_kind_value(self.world_kind.currentText())
            self._run_async(
                lambda: self.pipeline.generate_world_item(project_id, kind),
                f"正在自动创建{world_kind_label(kind)}，请稍候...",
                "资料已自动创建",
                self._after_create_world_item_with_ai,
            )

        def _after_create_world_item_with_ai(self, result: dict[str, Any]) -> str:
            item = result.get("world_item", {}) if isinstance(result, dict) else {}
            if isinstance(item, dict):
                self._fill_world_item_form(item)
            self.refresh_world_items()
            self.refresh_logs()
            return "资料已自动创建，可继续编辑后保存"

        def _ask_world_enrich_direction(self) -> str | None:
            dialog = QDialog(self.window)
            dialog.setWindowTitle("AI 修改方向")
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("填写本次 AI 自动补充设定的修改方向，可留空。"))
            editor = QTextEdit()
            editor.setPlaceholderText("例如：修改名称、强化动机、补充说话风格、补全等级体系限制")
            editor.setMinimumHeight(120)
            layout.addWidget(editor)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            self._resize_dialog_to_window(dialog)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            return editor.toPlainText().strip()

        def enrich_selected_world_item(self) -> None:
            project_id = self._project_required()
            if not project_id:
                return
            if not self.current_world_item_id:
                self._error("请先选择或保存一个资料条目")
                return
            item_id = int(self.current_world_item_id)
            direction = self._ask_world_enrich_direction()
            if direction is None:
                return
            self._run_async(
                lambda: self.pipeline.enrich_world_item(project_id, item_id, direction),
                "正在自动补充资料设定，请稍候...",
                "资料设定补充完成",
                self._after_enrich_world_item,
            )

        def _after_enrich_world_item(self, result: dict[str, Any]) -> str:
            item = result.get("world_item", {}) if isinstance(result, dict) else {}
            if isinstance(item, dict):
                self._fill_world_item_form(item)
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
            if hasattr(self, "outline_planning_fields") and "default_section_target_words" in self.outline_planning_fields:
                value = self.outline_planning_fields["default_section_target_words"].text().strip()
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
            planning_options = self._outline_planning_options()

            def on_delta(delta: str) -> None:
                if delta:
                    self.bridge.stream.emit("outline", delta)

            if hasattr(self.pipeline, "expand_global_concept_streaming"):
                return self.pipeline.expand_global_concept_streaming(project_id, on_delta, planning_options)
            result = self.pipeline.expand_global_concept(project_id, planning_options)
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
            self._set_llm_progress(True)
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
                self._set_llm_progress(False)
                self._async_busy = False

        def _complete_async_error(self, message: str) -> None:
            try:
                self.automation_cancel_event = None
                self.refresh_logs()
                self._error(message)
            finally:
                self._set_llm_progress(False)
                self._async_busy = False

        def _set_llm_progress(self, active: bool) -> None:
            if hasattr(self, "llm_progress"):
                self.llm_progress.setVisible(active)

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
