from __future__ import annotations

import difflib
import json
import math
import os
import threading
from typing import Any, Callable

from .app import ApplicationServices
from .exporter import export_full_book_docx
from .llm import LLMClient, load_llm_config, save_llm_config
from .models import WORLD_ITEM_KINDS
from .pipeline import NovelPipeline
from .project_files import ensure_project_structure
from .relation_graph import build_character_graph, build_event_graph
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
    normalize_character_card_details,
    update_character_basic_fields,
)

try:
    from PySide6.QtCore import QEvent, QRect, QObject, QSize, Qt, Signal
    from PySide6.QtGui import QColor, QBrush, QCursor, QFont, QLinearGradient, QPainter, QPen, QTextCursor
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QFrame,
        QGraphicsEllipseItem,
        QGraphicsItem,
        QGraphicsLineItem,
        QGraphicsRectItem,
        QGraphicsScene,
        QGraphicsTextItem,
        QGraphicsView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QLayout,
        QLayoutItem,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSplitter,
        QStackedWidget,
        QStyle,
        QStyledItemDelegate,
        QTextEdit,
        QToolButton,
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
    QMainWindow {
        background: transparent;
    }
    QWidget {
        background: #f7faff;
        color: #243042;
        font-family: "Microsoft YaHei UI";
        font-size: 13px;
    }
    QWidget#AppRoot {
        background: #f7faff;
        border: 1px solid #dce6f2;
        border-radius: 10px;
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
    QFrame#HeaderBar {
        background: #ffffff;
        border: 1px solid #dce6f2;
        border-left: 6px solid #f6b7c9;
        border-radius: 10px;
        min-height: 42px;
        max-height: 42px;
    }
    QLabel#HeaderTitle {
        background: transparent;
        border: 0;
        color: #2e5eaa;
        font-size: 18px;
        font-weight: 700;
        padding: 0;
    }
    QToolButton#WindowControl {
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 2px;
        min-width: 34px;
        min-height: 20px;
        max-width: 34px;
        max-height: 24px;
    }
    QToolButton#WindowControl:hover {
        background: #eaf3ff;
        border-color: #b8d4ff;
    }
    QToolButton#WindowControl:pressed {
        background: #dbeaff;
        border-color: #6fa8ff;
    }
    QToolButton#WindowControl[closeControl="true"]:hover {
        background: #ffe9ec;
        border-color: #e56b73;
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
        border-radius: 10px;
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
        border-radius: 10px;
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

    def _apply_windows_round_corners(widget: QWidget) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = int(widget.winId())
            # Windows 11 原生 DWM 圆角：2 表示系统默认圆角，不使用透明窗口或顶层 mask。
            corner_preference = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                33,
                ctypes.byref(corner_preference),
                ctypes.sizeof(corner_preference),
            )
        except Exception:
            pass


    class _AsyncBridge(QObject):
        success = Signal(str, object, object)
        error = Signal(str)
        stream = Signal(str, str)
        status = Signal(str)


    class RelationGraphView(QGraphicsView):
        def __init__(self, on_select: Callable[[dict[str, Any], str], None], on_open: Callable[[dict[str, Any]], None]) -> None:
            super().__init__()
            self._scene = QGraphicsScene(self)
            self.setScene(self._scene)
            self.on_select = on_select
            self.on_open = on_open
            self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self.setObjectName("RelationGraphView")
            self.graph: dict[str, Any] = {"nodes": [], "edges": [], "warnings": []}

        def render_graph(self, graph: dict[str, Any], mode: str, query: str = "") -> None:
            self.graph = graph
            self._scene.clear()
            nodes = list(graph.get("nodes", []))
            edges = list(graph.get("edges", []))
            query = query.strip().lower()
            if query:
                nodes = [
                    node
                    for node in nodes
                    if query in str(node.get("label") or node.get("name") or "").lower()
                    or query in str(node.get("summary", "")).lower()
                ]
                node_ids = {str(node.get("id")) for node in nodes}
                edges = [
                    edge
                    for edge in edges
                    if str(edge.get("source")) in node_ids and str(edge.get("target")) in node_ids
                ]
            if not nodes:
                self._scene.addText("暂无可显示的关系数据")
                return

            positions = self._layout_positions(nodes, mode)
            for edge in edges:
                source_pos = positions.get(str(edge.get("source")))
                target_pos = positions.get(str(edge.get("target")))
                if not source_pos or not target_pos:
                    continue
                line = QGraphicsLineItem(source_pos[0], source_pos[1], target_pos[0], target_pos[1])
                pen = QPen(self._edge_color(str(edge.get("kind", ""))), max(1, int(edge.get("weight", 1))))
                if str(edge.get("confidence")) != "explicit":
                    pen.setStyle(Qt.PenStyle.DashLine)
                line.setPen(pen)
                line.setZValue(0)
                line.setData(0, edge)
                line.setData(1, "edge")
                self._scene.addItem(line)

            for node in nodes:
                x, y = positions[str(node.get("id"))]
                width = 132
                height = 48
                if str(node.get("kind")) == "character":
                    item = QGraphicsEllipseItem(x - 42, y - 42, 84, 84)
                else:
                    item = QGraphicsRectItem(x - width / 2, y - height / 2, width, height)
                item.setBrush(QBrush(self._node_color(str(node.get("kind", "")), str(node.get("source", "")))))
                item.setPen(self._node_pen(str(node.get("kind", "")), str(node.get("source", ""))))
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                item.setZValue(2)
                item.setData(0, node)
                item.setData(1, "node")
                self._scene.addItem(item)

                label = QGraphicsTextItem(str(node.get("label") or node.get("name") or "未命名"))
                label.setDefaultTextColor(QColor("#243042"))
                label.setTextWidth(width)
                label_rect = label.boundingRect()
                label.setPos(x - width / 2, y - label_rect.height() / 2)
                label.setZValue(3)
                label.setData(0, node)
                label.setData(1, "node")
                self._scene.addItem(label)
            self.fit_graph()

        def fit_graph(self) -> None:
            rect = self._scene.itemsBoundingRect()
            if rect.isValid() and not rect.isEmpty():
                self.fitInView(rect.adjusted(-80, -80, 80, 80), Qt.AspectRatioMode.KeepAspectRatio)

        def wheelEvent(self, event) -> None:  # type: ignore[override]
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)

        def mousePressEvent(self, event) -> None:  # type: ignore[override]
            item = self._graph_item_at(event)
            if item is not None:
                payload = item.data(0)
                payload_type = item.data(1)
                if isinstance(payload, dict):
                    self.on_select(payload, str(payload_type))
            super().mousePressEvent(event)

        def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
            item = self._graph_item_at(event)
            if item is not None and item.data(1) == "node":
                payload = item.data(0)
                if isinstance(payload, dict):
                    self.on_open(payload)
            super().mouseDoubleClickEvent(event)

        def _graph_item_at(self, event) -> QGraphicsItem | None:
            try:
                position = event.position().toPoint()
            except AttributeError:
                position = event.pos()
            item = self.itemAt(position)
            while item is not None and item.data(1) not in {"node", "edge"}:
                item = item.parentItem()
            return item

        def _layout_positions(self, nodes: list[dict[str, Any]], mode: str) -> dict[str, tuple[float, float]]:
            if mode == "event":
                return {
                    str(node.get("id")): ((index % 4) * 250.0, (index // 4) * 150.0)
                    for index, node in enumerate(nodes)
                }
            radius = max(160.0, len(nodes) * 32.0)
            positions: dict[str, tuple[float, float]] = {}
            for index, node in enumerate(nodes):
                angle = (math.tau * index / max(1, len(nodes))) - math.pi / 2
                positions[str(node.get("id"))] = (math.cos(angle) * radius, math.sin(angle) * radius)
            return positions

        def _node_color(self, kind: str, source: str = "") -> QColor:
            if source == "missing_reference":
                return QColor("#fff0f2")
            if source == "inferred":
                return QColor("#f5f8fc")
            colors = {
                "character": "#cfe7ff",
                "timeline_event": "#fff2bd",
                "foreshadowing": "#f3d4ff",
                "location": "#d7f3df",
                "organization": "#e4d8ff",
                "rule": "#e9eef7",
                "forbidden": "#ffd9e0",
                "chapter": "#eef6ff",
                "section": "#f8fbff",
            }
            return QColor(colors.get(kind, "#ffffff"))

        def _node_pen(self, kind: str, source: str = "") -> QPen:
            border_colors = {
                "character": "#2f80d9",
                "timeline_event": "#d59b13",
                "foreshadowing": "#9b59c7",
                "location": "#2d9a55",
                "organization": "#7b61d9",
                "rule": "#6b7a90",
                "forbidden": "#d84c5f",
                "chapter": "#6fa8ff",
                "section": "#9aa8ba",
            }
            if source == "missing_reference":
                pen = QPen(QColor("#d84c5f"), 2)
                pen.setStyle(Qt.PenStyle.DashLine)
                return pen
            if source == "inferred":
                pen = QPen(QColor("#9aa8ba"), 2)
                pen.setStyle(Qt.PenStyle.DashLine)
                return pen
            return QPen(QColor(border_colors.get(kind, "#6fa8ff")), 2)

        def _edge_color(self, kind: str) -> QColor:
            if kind in {"conflict", "forbidden_constraint"}:
                return QColor("#e56b73")
            if kind in {"ally", "same_scene", "involves", "mentions_character"}:
                return QColor("#6fa8ff")
            if kind in {"causes", "caused_by", "before", "after"}:
                return QColor("#9b7ede")
            return QColor("#9aa8ba")


    class ProjectShelfListWidget(QListWidget):
        # 项目书架布局参数
        # GRID_WIDTH/GRID_HEIGHT 控制每一本书占用的格子大小。
        # TWO_COLUMN_MIN_WIDTH 控制书架从单列切换到双列的最小可用宽度。
        # EDGE_PADDING 和 SCROLLBAR_RESERVE 用来避免内容贴边或被滚动条挤压。
        GRID_WIDTH = 190
        GRID_HEIGHT = 300
        TWO_COLUMN_MIN_WIDTH = 160
        EDGE_PADDING = 0
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
            return QSize(176, 290)

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


    class TagFlowLayout(QLayout):
        """让标签按内容宽度从左到右排列，行宽不够时自动换行。"""

        def __init__(self, parent: QWidget | None = None, margin: int = 4, spacing: int = 6) -> None:
            super().__init__(parent)
            self._items: list[QLayoutItem] = []
            self.setContentsMargins(margin, margin, margin + 24, margin)
            self.setSpacing(spacing)

        def addItem(self, item: QLayoutItem) -> None:  # type: ignore[override]
            self._items.append(item)

        def count(self) -> int:  # type: ignore[override]
            return len(self._items)

        def itemAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
            if 0 <= index < len(self._items):
                return self._items[index]
            return None

        def takeAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
            if 0 <= index < len(self._items):
                return self._items.pop(index)
            return None

        def expandingDirections(self) -> Qt.Orientation:  # type: ignore[override]
            return Qt.Orientation(0)

        def hasHeightForWidth(self) -> bool:  # type: ignore[override]
            return True

        def heightForWidth(self, width: int) -> int:  # type: ignore[override]
            return self._do_layout(QRect(0, 0, width, 0), True)

        def setGeometry(self, rect: QRect) -> None:  # type: ignore[override]
            super().setGeometry(rect)
            self._do_layout(rect, False)

        def sizeHint(self) -> QSize:  # type: ignore[override]
            return self.minimumSize()

        def minimumSize(self) -> QSize:  # type: ignore[override]
            size = QSize()
            for item in self._items:
                size = size.expandedTo(item.minimumSize())
            margins = self.contentsMargins()
            size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
            return size

        def _do_layout(self, rect: QRect, test_only: bool) -> int:
            margins = self.contentsMargins()
            x = rect.x() + margins.left()
            y = rect.y() + margins.top()
            line_height = 0
            right_limit = rect.right() - margins.right()

            for item in self._items:
                hint = item.sizeHint()
                widget = item.widget()
                if widget is not None and bool(widget.property("flow_full_row")):
                    if x > rect.x() + margins.left():
                        y += line_height + self.spacing()
                    if not test_only:
                        item.setGeometry(QRect(rect.x() + margins.left(), y, right_limit - rect.x(), hint.height()))
                    x = rect.x() + margins.left()
                    y += hint.height() + self.spacing()
                    line_height = 0
                    continue
                next_x = x + hint.width() + self.spacing()
                if x > rect.x() + margins.left() and next_x - self.spacing() > right_limit:
                    x = rect.x() + margins.left()
                    y += line_height + self.spacing()
                    next_x = x + hint.width() + self.spacing()
                    line_height = 0
                if not test_only:
                    item.setGeometry(QRect(x, y, hint.width(), hint.height()))
                x = next_x
                line_height = max(line_height, hint.height())
            return y + line_height + margins.bottom() - rect.y()


    class WindowControlButton(QToolButton):
        def __init__(self, control_kind: str, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.control_kind = control_kind
            self.setObjectName("WindowControl")
            self.setText("")
            self.setAutoRaise(True)
            self.setFixedSize(34, 24)

        def set_control_kind(self, control_kind: str) -> None:
            self.control_kind = control_kind
            self.update()

        def paintEvent(self, event) -> None:  # type: ignore[override]
            super().paintEvent(event)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            pen = QPen(QColor("#5f6368"), 1)
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
            painter.setPen(pen)
            rect = self.rect()
            center_x = rect.center().x()
            center_y = rect.center().y()
            if self.control_kind == "minimize":
                painter.drawLine(center_x - 5, center_y + 4, center_x + 5, center_y + 4)
            elif self.control_kind == "maximize":
                painter.drawRect(center_x - 5, center_y - 5, 10, 10)
            elif self.control_kind == "restore":
                painter.drawRect(center_x - 3, center_y - 6, 9, 9)
                painter.drawRect(center_x - 6, center_y - 3, 9, 9)
            elif self.control_kind == "close":
                painter.drawLine(center_x - 5, center_y - 5, center_x + 5, center_y + 5)
                painter.drawLine(center_x + 5, center_y - 5, center_x - 5, center_y + 5)
            painter.end()


    class WindowTitleBar(QFrame):
        """无系统标题栏窗口使用的自定义标题栏。"""

        def __init__(self, title: str, target: QWidget) -> None:
            super().__init__(target)
            self.target = target
            self._drag_offset = None
            self._normal_geometry: QRect | None = None
            self._manually_maximized = False
            self._resize_edges = ""
            self._resize_start_pos = None
            self._resize_start_geometry: QRect | None = None
            self._edge_resize_margin = 8
            # 手动调整窗口最小尺寸的位置：这里控制用户拖动边缘时能缩到多小。
            # 如果放大初始窗口后仍希望允许缩小，可以只改下面的初始 resize，不改这里。
            self.target.setMinimumSize(QSize(1260, 775))
            self.target.setMouseTracking(True)
            self.target.installEventFilter(self)
            self.setObjectName("HeaderBar")
            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 4, 8, 4)
            layout.setSpacing(3)
            self.title_label = QLabel(title)
            self.title_label.setObjectName("HeaderTitle")
            self.title_label.installEventFilter(self)
            layout.addWidget(self.title_label, 1)
            layout.addWidget(self._control_button("minimize", self.target.showMinimized))
            self.maximize_button = self._control_button(
                "maximize",
                self._toggle_maximized,
            )
            layout.addWidget(self.maximize_button)
            close_button = self._control_button("close", self.target.close)
            close_button.setProperty("closeControl", True)
            layout.addWidget(close_button)

        def _control_button(self, control_kind: str, slot: Callable[[], None]) -> WindowControlButton:
            button = WindowControlButton(control_kind, self)
            button.clicked.connect(slot)
            return button

        def _toggle_maximized(self) -> None:
            if self._manually_maximized:
                if self._normal_geometry is not None:
                    self.target.setGeometry(self._normal_geometry)
                self._manually_maximized = False
            else:
                self._normal_geometry = self.target.geometry()
                screen = self.target.screen() or QApplication.primaryScreen()
                if screen is not None:
                    self.target.setGeometry(screen.availableGeometry())
                self._manually_maximized = True
            self._refresh_maximize_icon()

        def _refresh_maximize_icon(self) -> None:
            self.maximize_button.set_control_kind("restore" if self._manually_maximized else "maximize")

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
            if watched is self.target:
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    if self._start_edge_resize(event):
                        return True
                if event.type() == QEvent.Type.MouseMove:
                    if self._resize_edges:
                        self._resize_window(event)
                        return True
                    self._update_edge_cursor(event)
                if event.type() == QEvent.Type.MouseButtonRelease:
                    self._finish_edge_resize()
                    return False
            if watched is self.title_label:
                if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                    self._toggle_maximized()
                    return True
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    self._start_drag(event)
                    return True
                if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                    self._drag_window(event)
                    return True
                if event.type() == QEvent.Type.MouseButtonRelease:
                    self._drag_offset = None
                    return True
            return super().eventFilter(watched, event)

        def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
            if event.button() == Qt.MouseButton.LeftButton:
                self._toggle_maximized()
                return
            super().mouseDoubleClickEvent(event)

        def mousePressEvent(self, event) -> None:  # type: ignore[override]
            if event.button() == Qt.MouseButton.LeftButton:
                self._start_drag(event)
                return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
            if self._drag_offset is not None:
                self._drag_window(event)
                return
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
            self._drag_offset = None
            super().mouseReleaseEvent(event)

        def _start_drag(self, event) -> None:
            if self._manually_maximized:
                return
            handle = self.target.windowHandle()
            if handle is not None and handle.startSystemMove():
                self._drag_offset = None
                return
            self._drag_offset = event.globalPosition().toPoint() - self.target.frameGeometry().topLeft()

        def _drag_window(self, event) -> None:
            if self._manually_maximized:
                return
            cursor_pos = event.globalPosition().toPoint()
            screen = QApplication.screenAt(cursor_pos) or self.target.screen() or QApplication.primaryScreen()
            target_pos = cursor_pos - self._drag_offset
            if screen is not None:
                available = screen.availableGeometry()
                width = self.target.width()
                height = self.target.height()
                min_visible = 96
                min_x = available.left() - width + min_visible
                max_x = available.right() - min_visible
                min_y = available.top()
                max_y = available.bottom() - min_visible
                target_pos.setX(max(min_x, min(target_pos.x(), max_x)))
                target_pos.setY(max(min_y, min(target_pos.y(), max_y)))
            self.target.move(target_pos)

        def _edge_hit_test(self, global_pos) -> str:
            if self._manually_maximized:
                return ""
            rect = self.target.frameGeometry()
            margin = self._edge_resize_margin
            edges = ""
            if abs(global_pos.x() - rect.left()) <= margin:
                edges += "l"
            elif abs(global_pos.x() - rect.right()) <= margin:
                edges += "r"
            if abs(global_pos.y() - rect.top()) <= margin:
                edges += "t"
            elif abs(global_pos.y() - rect.bottom()) <= margin:
                edges += "b"
            return edges

        def _start_edge_resize(self, event) -> bool:
            edges = self._edge_hit_test(event.globalPosition().toPoint())
            if not edges:
                return False
            handle = self.target.windowHandle()
            system_edges = self._system_resize_edges(edges)
            if handle is not None and system_edges and handle.startSystemResize(system_edges):
                self._resize_edges = ""
                self._resize_start_pos = None
                self._resize_start_geometry = None
                return True
            self._resize_edges = edges
            self._resize_start_pos = event.globalPosition().toPoint()
            self._resize_start_geometry = self.target.geometry()
            return True

        def _system_resize_edges(self, edges: str):
            system_edges = Qt.Edges()
            if "l" in edges:
                system_edges |= Qt.Edge.LeftEdge
            if "r" in edges:
                system_edges |= Qt.Edge.RightEdge
            if "t" in edges:
                system_edges |= Qt.Edge.TopEdge
            if "b" in edges:
                system_edges |= Qt.Edge.BottomEdge
            return system_edges

        def _resize_window(self, event) -> None:
            if self._resize_start_pos is None or self._resize_start_geometry is None:
                return
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            rect = QRect(self._resize_start_geometry)
            minimum = self.target.minimumSize()
            if "l" in self._resize_edges:
                new_left = min(rect.left() + delta.x(), rect.right() - minimum.width())
                rect.setLeft(new_left)
            if "r" in self._resize_edges:
                rect.setRight(max(rect.right() + delta.x(), rect.left() + minimum.width()))
            if "t" in self._resize_edges:
                new_top = min(rect.top() + delta.y(), rect.bottom() - minimum.height())
                rect.setTop(new_top)
            if "b" in self._resize_edges:
                rect.setBottom(max(rect.bottom() + delta.y(), rect.top() + minimum.height()))
            self.target.setGeometry(rect)

        def _finish_edge_resize(self) -> None:
            self._resize_edges = ""
            self._resize_start_pos = None
            self._resize_start_geometry = None
            self.target.unsetCursor()

        def _update_edge_cursor(self, event) -> None:
            edges = self._edge_hit_test(event.globalPosition().toPoint())
            if edges in ("lt", "rb", "tl", "br"):
                self.target.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif edges in ("rt", "lb", "tr", "bl"):
                self.target.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif edges in ("l", "r"):
                self.target.setCursor(Qt.CursorShape.SizeHorCursor)
            elif edges in ("t", "b"):
                self.target.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.target.unsetCursor()


    class SearchProjectCreationDialog(QDialog):
        def __init__(self, owner: "NovelDesktopUI") -> None:
            super().__init__(owner.window)
            self.owner = owner
            self.candidates: list[dict[str, Any]] = []
            self.tag_states: dict[str, dict[str, int]] = {}
            self.tag_buttons: dict[tuple[str, str], QPushButton] = {}
            self.tag_catalog: dict[str, list[dict[str, Any]]] = {}
            self.setWindowTitle("标签化生成")
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
            _apply_windows_round_corners(self)
            layout = QVBoxLayout(self)
            layout.addWidget(WindowTitleBar("标签化生成", self))
            self.query_input = QLineEdit()
            self.query_input.setPlaceholderText("输入想看/想写的小说方向，例如：异世界转移 TS 等级成长 轻小说 不要后宫")
            self.query_input.textChanged.connect(lambda _text: self._refresh_tag_buttons())
            query_title = QLabel("搜索式需求")
            query_title.setObjectName("PanelTitle")
            layout.addWidget(query_title)
            layout.addWidget(self.query_input)
            layout.addWidget(QLabel("相关标签：点一下选中，再点一下变为红色排除，再点一下恢复默认"))

            body = QHBoxLayout()
            filter_column = QVBoxLayout()
            tag_title = QLabel("标签/排除项")
            tag_title.setObjectName("PanelTitle")
            filter_column.addWidget(tag_title)
            self.tag_scroll = QScrollArea()
            self.tag_scroll.setWidgetResizable(True)
            self.tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.tag_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self.tag_scroll.setViewportMargins(0, 0, 12, 0)
            self.tag_scroll.setMinimumHeight(260)
            self.tag_host = QWidget()
            self.tag_flow = TagFlowLayout(self.tag_host)
            self.tag_scroll.setWidget(self.tag_host)
            filter_column.addWidget(self.tag_scroll, 1)
            self._build_tag_buttons()
            body.addLayout(filter_column, 1)

            result_column = QVBoxLayout()
            self.candidate_list = QListWidget()
            self.candidate_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.candidate_list.currentRowChanged.connect(lambda _row: self._show_candidate_detail())
            self.generate_button = QPushButton("生成候选")
            self.generate_button.setProperty("primary", True)
            self.generate_button.clicked.connect(self._generate_candidates)
            result_column.addWidget(self.generate_button)
            candidate_title = QLabel("候选方案")
            candidate_title.setObjectName("PanelTitle")
            result_column.addWidget(candidate_title)
            result_column.addWidget(self.candidate_list, 1)
            body.addLayout(result_column, 1)

            detail_column = QVBoxLayout()
            self.detail_text = QTextEdit()
            self.detail_text.setObjectName("StreamingOutput")
            self.detail_text.setReadOnly(True)
            self.detail_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            use_button = QPushButton("用这个创建项目")
            use_button.setProperty("primary", True)
            use_button.clicked.connect(self._use_selected_candidate)
            self.use_button = use_button
            self.similar_button = QPushButton("生成相似方案")
            self.similar_button.clicked.connect(self._generate_candidates)
            detail_title = QLabel("详情与操作")
            detail_title.setObjectName("PanelTitle")
            detail_column.addWidget(detail_title)
            detail_column.addWidget(self.detail_text, 1)
            detail_column.addWidget(use_button)
            detail_column.addWidget(self.similar_button)
            body.addLayout(detail_column, 1)
            layout.addLayout(body, 1)

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

            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
            self.status_label = QLabel("")
            self.status_label.setObjectName("Status")
            self.progress_bar = QProgressBar()
            self.progress_bar.setObjectName("LlmProgress")
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setVisible(False)
            layout.addWidget(self.progress_bar)
            footer = QHBoxLayout()
            footer.addWidget(self.status_label, 1)
            footer.addWidget(buttons)
            layout.addLayout(footer)
            owner._resize_dialog_to_window(self)

        def _build_tag_buttons(self) -> None:
            catalog = list_style_tag_catalog()
            for field, category in FIELD_TO_CATEGORY.items():
                self.tag_states[field] = {}
                self.tag_catalog[field] = []
                selected = set(getattr(self.owner, "project_tag_selection", {}).get(field, []))
                for tag in catalog.get(category, []):
                    tag_id = str(tag.get("id", ""))
                    self.tag_states[field][tag_id] = 1 if tag_id in selected else 0
                    self.tag_catalog[field].append(dict(tag))
            self._refresh_tag_buttons()

        def _refresh_tag_buttons(self) -> None:
            while self.tag_flow.count():
                item = self.tag_flow.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.tag_buttons = {}
            query = self.query_input.text().strip().lower() if hasattr(self, "query_input") else ""
            terms = [term for term in query.replace("，", " ").replace(",", " ").split() if term]
            grouped_tags = self._group_visible_tags(terms)
            for title, entries in grouped_tags:
                if not entries:
                    continue
                header = QLabel(title)
                header.setObjectName("PanelTitle")
                header.setProperty("flow_full_row", True)
                self.tag_flow.addWidget(header)
                self._add_tag_button_group(entries)
            if not self.tag_buttons:
                self.tag_flow.addWidget(QLabel("没有匹配标签，可以换一个关键词"))

        def _group_visible_tags(self, terms: list[str]) -> list[tuple[str, list[tuple[str, dict[str, Any]]]]]:
            labels = {
                "selected_genre_tags": "题材标签",
                "selected_setting_tags": "设定标签",
                "selected_character_tags": "角色标签",
                "selected_structure_tags": "结构标签",
                "selected_style_tags": "风格标签",
                "selected_forbidden_tags": "排除/禁止标签",
            }
            grouped: list[tuple[str, list[tuple[str, dict[str, Any]]]]] = []
            for field, tags in self.tag_catalog.items():
                entries = [(field, tag) for tag in tags if self._tag_matches_query(tag, terms)]
                if entries:
                    grouped.append((labels.get(field, field), entries))
            return grouped

        def _add_tag_button_group(
            self,
            entries: list[tuple[str, dict[str, Any]]],
        ) -> None:
            for field, tag in entries:
                tag_id = str(tag.get("id", ""))
                button = QPushButton(str(tag.get("label", tag_id)))
                button.setToolTip(str(tag.get("usage_rule", "") or tag.get("style_rule", "")))
                button.clicked.connect(lambda _checked=False, f=field, t=tag_id: self._cycle_tag_state(f, t))
                # 标签按钮只按文字内容取宽度，不再横向填满网格单元格。
                button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                #button.setMinimumHeight(32)  # 固定标签按钮高度，避免不同文字导致按钮视觉拥挤
                #button.setContentsMargins(0, 0, 6, 0)  # 给按钮自身右侧留一点空隙
                self.tag_buttons[(field, tag_id)] = button
                self._style_tag_button(button, self.tag_states.get(field, {}).get(tag_id, 0))
                self.tag_flow.addWidget(button)

        def _tag_matches_query(self, tag: dict[str, Any], terms: list[str]) -> bool:
            if not terms:
                return True
            haystack = " ".join(
                str(tag.get(key, ""))
                for key in ("id", "label", "style_rule", "usage_rule")
            ).lower()
            return any(term in haystack for term in terms)

        def _cycle_tag_state(self, field: str, tag_id: str) -> None:
            state = (self.tag_states.get(field, {}).get(tag_id, 0) + 1) % 3
            self.tag_states.setdefault(field, {})[tag_id] = state
            button = self.tag_buttons.get((field, tag_id))
            if button is not None:
                self._style_tag_button(button, state)

        def _style_tag_button(self, button: QPushButton, state: int) -> None:
            if state == 1:
                button.setStyleSheet("background: #eaf3ff; border: 1px solid #6fa8ff; color: #1f4f99;")
            elif state == 2:
                button.setStyleSheet("background: #ffe9ec; border: 1px solid #e56b73; color: #b63a45;")
            else:
                button.setStyleSheet("")

        def _generation_profile(self) -> dict[str, Any]:
            return {
                "search_query": self.query_input.text().strip(),
                "selected_tags": {
                    field: [tag_id for tag_id, state in states.items() if state == 1]
                    for field, states in self.tag_states.items()
                },
                "exclude_tags": self._excluded_tag_ids(),
                "target_readers": self.reader_combo.currentText().strip(),
                "pov": self.pov_combo.currentText().strip(),
            }

        def _excluded_tag_ids(self) -> list[str]:
            excluded: list[str] = []
            for states in self.tag_states.values():
                excluded.extend(tag_id for tag_id, state in states.items() if state == 2)
            return excluded

        def _generate_candidates(self) -> None:
            if getattr(self.owner, "_async_busy", False):
                self.owner._error("已有后台任务运行中，请稍候")
                return
            profile = self._generation_profile()
            self._set_generation_busy(True, "正在自动创建候选方案...")
            self.detail_text.setPlainText("")
            self.owner._temporary_stream_targets["search_candidate"] = self.detail_text

            def action() -> dict[str, Any]:
                try:
                    return {"ok": True, "candidates": self.owner._generate_search_creation_candidates_streaming(profile)}
                except Exception as exc:
                    return {"ok": False, "error": str(exc)}

            self.owner._run_async(action, "正在自动创建候选方案...", "", self._after_generate_candidates)

        def _after_generate_candidates(self, result: dict[str, Any]) -> bool:
            self._set_generation_busy(False, "")
            self.owner._temporary_stream_targets.pop("search_candidate", None)
            if not result.get("ok"):
                self.owner.refresh_logs()
                self.owner._error(str(result.get("error") or "生成候选失败"))
                return False
            candidates = result.get("candidates", [])
            self.candidates = [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]
            self.candidate_list.clear()
            for candidate in self.candidates:
                title = str(candidate.get("temporary_title") or candidate.get("title") or "未命名候选")
                hook = str(candidate.get("one_line_hook") or candidate.get("hook") or "")
                self.candidate_list.addItem(f"{title}\n{hook}")
            if self.candidates:
                self.candidate_list.setCurrentRow(0)
                self.status_label.setText(f"已生成 {len(self.candidates)} 个候选方案")
            else:
                self.status_label.setText("未生成候选方案，请调整标签或搜索词后重试")
            self.owner.refresh_logs()
            return False

        def _set_generation_busy(self, busy: bool, message: str) -> None:
            self.generate_button.setEnabled(not busy)
            self.similar_button.setEnabled(not busy)
            self.use_button.setEnabled(not busy)
            self.progress_bar.setVisible(busy)
            self.status_label.setText(message)

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


    class TaggedCharacterCreationDialog(QDialog):
        def __init__(self, owner: "NovelDesktopUI") -> None:
            super().__init__(owner.window)
            self.owner = owner
            self.tag_states: dict[str, int] = {}
            self.tag_buttons: dict[str, QPushButton] = {}
            self.tag_catalog: list[dict[str, Any]] = []
            self.role_structure_tag_ids = {"single_protagonist", "dual_protagonists"}
            self.setWindowTitle("标签化生成角色卡")
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
            _apply_windows_round_corners(self)

            layout = QVBoxLayout(self)
            layout.addWidget(WindowTitleBar("标签化生成角色卡", self))

            query_title = QLabel("搜索式需求")
            query_title.setObjectName("PanelTitle")
            layout.addWidget(query_title)
            self.query_input = QLineEdit()
            self.query_input.setPlaceholderText("输入角色方向或标签，例如：TS 弱到强 主视角 不要龙傲天")
            self.query_input.textChanged.connect(lambda _text: self._refresh_tag_buttons())
            layout.addWidget(self.query_input)
            layout.addWidget(QLabel("相关标签：点一下选中，再点一下变为红色排除，再点一下恢复默认"))

            body = QHBoxLayout()
            filter_column = QVBoxLayout()
            tag_title = QLabel("标签/排除项")
            tag_title.setObjectName("PanelTitle")
            filter_column.addWidget(tag_title)
            self.tag_scroll = QScrollArea()
            self.tag_scroll.setWidgetResizable(True)
            self.tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.tag_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self.tag_scroll.setViewportMargins(0, 0, 12, 0)
            self.tag_scroll.setMinimumHeight(260)
            self.tag_host = QWidget()
            self.tag_flow = TagFlowLayout(self.tag_host)
            self.tag_scroll.setWidget(self.tag_host)
            filter_column.addWidget(self.tag_scroll, 1)
            body.addLayout(filter_column, 1)

            detail_column = QVBoxLayout()
            role_title = QLabel("角色定位与方向")
            role_title.setObjectName("PanelTitle")
            detail_column.addWidget(role_title)
            self.role_combo = QComboBox()
            for key, label in [
                ("protagonist", "主角"),
                ("pov", "POV"),
                ("ensemble_main", "群像主要角色"),
                ("supporting", "重要配角"),
            ]:
                self.role_combo.addItem(label, key)
            detail_column.addWidget(QLabel("角色定位"))
            detail_column.addWidget(self.role_combo)
            self.protagonist_structure_combo = QComboBox()
            self.protagonist_structure_combo.addItem("单主角", "single_protagonist")
            self.protagonist_structure_combo.addItem("双主角", "dual_protagonists")
            detail_column.addWidget(QLabel("主角结构"))
            detail_column.addWidget(self.protagonist_structure_combo)
            detail_column.addWidget(QLabel("生成方向"))
            self.direction_edit = QTextEdit()
            self.direction_edit.setObjectName("StreamingOutput")
            self.direction_edit.setPlaceholderText("可选：写明本次角色创建方向，例如“生成一名沉默但责任感强的魔法学院转学生”。")
            self.direction_edit.setMinimumHeight(160)
            self.direction_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            detail_column.addWidget(self.direction_edit, 1)
            body.addLayout(detail_column, 1)
            layout.addLayout(body, 1)

            self._build_tag_buttons()

            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            self.status_label = QLabel("选择角色定位、生成方向和角色标签后开始生成")
            self.status_label.setObjectName("Status")
            self.progress_bar = QProgressBar()
            self.progress_bar.setObjectName("LlmProgress")
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setVisible(False)
            layout.addWidget(self.progress_bar)
            footer = QHBoxLayout()
            footer.addWidget(self.status_label, 1)
            footer.addWidget(buttons)
            layout.addLayout(footer)
            owner._resize_dialog_to_window(self)

        def _build_tag_buttons(self) -> None:
            for tag in list_style_tag_catalog().get("character_tags", []):
                tag_id = str(tag.get("id", "") or "").strip()
                if not tag_id or tag_id in self.role_structure_tag_ids or tag_id in self.tag_states:
                    continue
                self.tag_states[tag_id] = 0
                self.tag_catalog.append(dict(tag))
            self._refresh_tag_buttons()

        def _refresh_tag_buttons(self) -> None:
            while self.tag_flow.count():
                item = self.tag_flow.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.tag_buttons = {}
            query = self.query_input.text().strip().lower() if hasattr(self, "query_input") else ""
            terms = [term for term in query.replace("，", " ").replace(",", " ").split() if term]
            visible_tags = self._visible_tags(terms)
            self._add_tag_button_group(visible_tags)
            if not self.tag_buttons:
                self.tag_flow.addWidget(QLabel("没有匹配标签，可以换一个关键词"))

        def _visible_tags(self, terms: list[str]) -> list[dict[str, Any]]:
            return [tag for tag in self.tag_catalog if self._tag_matches_query(tag, terms)]

        def _add_tag_button_group(self, entries: list[dict[str, Any]]) -> None:
            for tag in entries:
                tag_id = str(tag.get("id", ""))
                button = QPushButton(str(tag.get("label", tag_id)))
                button.setToolTip(str(tag.get("usage_rule", "") or tag.get("style_rule", "")))
                button.clicked.connect(lambda _checked=False, t=tag_id: self._cycle_tag_state(t))
                button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                self.tag_buttons[tag_id] = button
                self._style_tag_button(button, self.tag_states.get(tag_id, 0))
                self.tag_flow.addWidget(button)

        def _tag_matches_query(self, tag: dict[str, Any], terms: list[str]) -> bool:
            if not terms:
                return True
            haystack = " ".join(
                str(tag.get(key, ""))
                for key in ("id", "label", "style_rule", "usage_rule")
            ).lower()
            return any(term in haystack for term in terms)

        def _cycle_tag_state(self, tag_id: str) -> None:
            state = (self.tag_states.get(tag_id, 0) + 1) % 3
            self.tag_states[tag_id] = state
            button = self.tag_buttons.get(tag_id)
            if button is not None:
                self._style_tag_button(button, state)

        def _style_tag_button(self, button: QPushButton, state: int) -> None:
            if state == 1:
                button.setStyleSheet("background: #eaf3ff; border: 1px solid #6fa8ff; color: #1f4f99;")
            elif state == 2:
                button.setStyleSheet("background: #ffe9ec; border: 1px solid #e56b73; color: #b63a45;")
            else:
                button.setStyleSheet("")

        def generation_profile(self) -> dict[str, Any]:
            role_structure_tag = str(self.protagonist_structure_combo.currentData() or "single_protagonist")
            selected = [role_structure_tag] + [tag_id for tag_id, state in self.tag_states.items() if state == 1]
            excluded = [tag_id for tag_id, state in self.tag_states.items() if state == 2]
            return {
                "search_query": self.query_input.text().strip(),
                "role_profile": str(self.role_combo.currentData() or "protagonist"),
                "selected_character_tags": selected,
                "selected_setting_tags": [],
                "selected_style_tags": [],
                "selected_forbidden_tags": excluded,
                "exclude_tags": excluded,
                "generation_direction": self.direction_edit.toPlainText().strip(),
            }


    class ProjectTagAssistDialog(QDialog):
        def __init__(self, owner: "NovelDesktopUI") -> None:
            super().__init__(owner.window)
            self.owner = owner
            self.tag_states: dict[str, dict[str, int]] = {}
            self.tag_buttons: dict[tuple[str, str], QPushButton] = {}
            self.tag_catalog: dict[str, list[dict[str, Any]]] = {}
            self.last_project_patch: dict[str, str] = {}
            self.setWindowTitle("选择标签/辅助修改")
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
            _apply_windows_round_corners(self)

            layout = QVBoxLayout(self)
            layout.addWidget(WindowTitleBar("选择标签/辅助修改", self))
            query_title = QLabel("搜索式需求")
            query_title.setObjectName("PanelTitle")
            layout.addWidget(query_title)
            self.query_input = QLineEdit()
            self.query_input.setPlaceholderText("输入标签或修改方向关键词，例如：异世界 轻小说 不要后宫")
            self.query_input.textChanged.connect(lambda _text: self._refresh_tag_buttons())
            layout.addWidget(self.query_input)
            layout.addWidget(QLabel("相关标签：点一下选中，再点一下变为红色排除，再点一下恢复默认"))

            body = QHBoxLayout()
            filter_column = QVBoxLayout()
            tag_title = QLabel("标签/排除项")
            tag_title.setObjectName("PanelTitle")
            filter_column.addWidget(tag_title)
            self.tag_scroll = QScrollArea()
            self.tag_scroll.setWidgetResizable(True)
            self.tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.tag_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self.tag_scroll.setViewportMargins(0, 0, 12, 0)
            self.tag_scroll.setMinimumHeight(260)
            self.tag_host = QWidget()
            self.tag_flow = TagFlowLayout(self.tag_host)
            self.tag_scroll.setWidget(self.tag_host)
            filter_column.addWidget(self.tag_scroll, 1)
            body.addLayout(filter_column, 1)

            detail_column = QVBoxLayout()
            detail_title = QLabel("辅助修改")
            detail_title.setObjectName("PanelTitle")
            detail_column.addWidget(detail_title)
            detail_column.addWidget(QLabel("对白引号"))
            self.quote_combo = QComboBox()
            for quote_id, item in DIALOGUE_QUOTE_STYLES.items():
                self.quote_combo.addItem(str(item["label"]), quote_id)
            quote_index = self.quote_combo.findData(getattr(owner, "dialogue_quote_style_value", "cn_quotes"))
            self.quote_combo.setCurrentIndex(quote_index if quote_index >= 0 else 0)
            detail_column.addWidget(self.quote_combo)
            detail_column.addWidget(QLabel("修改方向"))
            self.direction_edit = QTextEdit()
            self.direction_edit.setPlaceholderText("可选：例如强化日式轻小说感、统一叙事视角、把世界观改得更偏学院、减少后宫感。")
            self.direction_edit.setMinimumHeight(90)
            detail_column.addWidget(self.direction_edit)
            self.generate_button = QPushButton("生成修改建议")
            self.generate_button.setProperty("primary", True)
            self.generate_button.clicked.connect(self._generate_project_patch)
            self.apply_button = QPushButton("应用修改到项目表单")
            self.apply_button.clicked.connect(self._apply_project_patch)
            detail_column.addWidget(self.generate_button)
            detail_column.addWidget(self.apply_button)
            detail_column.addWidget(QLabel("流式输出/修改建议"))
            self.detail_text = QTextEdit()
            self.detail_text.setObjectName("StreamingOutput")
            self.detail_text.setReadOnly(True)
            self.detail_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            detail_column.addWidget(self.detail_text, 1)
            body.addLayout(detail_column, 1)
            layout.addLayout(body, 1)

            self._build_tag_buttons()

            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(self._accept_tag_settings)
            buttons.rejected.connect(self.reject)
            self.status_label = QLabel("可只修改标签与引号，也可生成 AI 辅助修改建议")
            self.status_label.setObjectName("Status")
            self.progress_bar = QProgressBar()
            self.progress_bar.setObjectName("LlmProgress")
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setVisible(False)
            layout.addWidget(self.progress_bar)
            footer = QHBoxLayout()
            footer.addWidget(self.status_label, 1)
            footer.addWidget(buttons)
            layout.addLayout(footer)
            owner._resize_dialog_to_window(self)

        def _build_tag_buttons(self) -> None:
            catalog = list_style_tag_catalog()
            current_selection = getattr(self.owner, "project_tag_selection", {})
            for field, category in FIELD_TO_CATEGORY.items():
                self.tag_states[field] = {}
                self.tag_catalog[field] = []
                selected = set(current_selection.get(field, []))
                for tag in catalog.get(category, []):
                    tag_id = str(tag.get("id", "") or "").strip()
                    if not tag_id:
                        continue
                    self.tag_states[field][tag_id] = 1 if tag_id in selected else 0
                    self.tag_catalog[field].append(dict(tag))
            self._refresh_tag_buttons()

        def _refresh_tag_buttons(self) -> None:
            while self.tag_flow.count():
                item = self.tag_flow.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.tag_buttons = {}
            query = self.query_input.text().strip().lower() if hasattr(self, "query_input") else ""
            terms = [term for term in query.replace("，", " ").replace(",", " ").split() if term]
            for title, entries in self._group_visible_tags(terms):
                if not entries:
                    continue
                header = QLabel(title)
                header.setObjectName("PanelTitle")
                header.setProperty("flow_full_row", True)
                self.tag_flow.addWidget(header)
                self._add_tag_button_group(entries)
            if not self.tag_buttons:
                self.tag_flow.addWidget(QLabel("没有匹配标签，可以换一个关键词"))

        def _group_visible_tags(self, terms: list[str]) -> list[tuple[str, list[tuple[str, dict[str, Any]]]]]:
            labels = {
                "selected_genre_tags": "题材标签",
                "selected_setting_tags": "设定标签",
                "selected_character_tags": "角色标签",
                "selected_structure_tags": "结构标签",
                "selected_style_tags": "风格标签",
                "selected_forbidden_tags": "排除/禁止标签",
            }
            groups: list[tuple[str, list[tuple[str, dict[str, Any]]]]] = []
            for field, tags in self.tag_catalog.items():
                entries = [(field, tag) for tag in tags if self._tag_matches_query(tag, terms)]
                if entries:
                    groups.append((labels.get(field, field), entries))
            return groups

        def _add_tag_button_group(self, entries: list[tuple[str, dict[str, Any]]]) -> None:
            for field, tag in entries:
                tag_id = str(tag.get("id", ""))
                button = QPushButton(str(tag.get("label", tag_id)))
                button.setToolTip(str(tag.get("usage_rule", "") or tag.get("style_rule", "")))
                button.clicked.connect(lambda _checked=False, f=field, t=tag_id: self._cycle_tag_state(f, t))
                button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                self.tag_buttons[(field, tag_id)] = button
                self._style_tag_button(button, self.tag_states.get(field, {}).get(tag_id, 0))
                self.tag_flow.addWidget(button)

        def _tag_matches_query(self, tag: dict[str, Any], terms: list[str]) -> bool:
            if not terms:
                return True
            haystack = " ".join(
                str(tag.get(key, ""))
                for key in ("id", "label", "style_rule", "usage_rule")
            ).lower()
            return any(term in haystack for term in terms)

        def _cycle_tag_state(self, field: str, tag_id: str) -> None:
            state = (self.tag_states.get(field, {}).get(tag_id, 0) + 1) % 3
            self.tag_states.setdefault(field, {})[tag_id] = state
            button = self.tag_buttons.get((field, tag_id))
            if button is not None:
                self._style_tag_button(button, state)

        def _style_tag_button(self, button: QPushButton, state: int) -> None:
            if state == 1:
                button.setStyleSheet("background: #eaf3ff; border: 1px solid #6fa8ff; color: #1f4f99;")
            elif state == 2:
                button.setStyleSheet("background: #ffe9ec; border: 1px solid #e56b73; color: #b63a45;")
            else:
                button.setStyleSheet("")

        def _generation_profile(self) -> dict[str, Any]:
            selected_tags = {
                field: [tag_id for tag_id, state in states.items() if state == 1]
                for field, states in self.tag_states.items()
            }
            excluded = self._excluded_tag_ids()
            if excluded:
                selected_tags.setdefault("selected_forbidden_tags", [])
                selected_tags["selected_forbidden_tags"] = list(
                    dict.fromkeys([*selected_tags["selected_forbidden_tags"], *excluded])
                )
            return {
                "project_id": self.owner.current_project_id,
                "project": self.owner._current_project_form_data(),
                "selected_tags": selected_tags,
                "exclude_tags": excluded,
                "dialogue_quote_style": str(self.quote_combo.currentData() or "cn_quotes"),
                "direction": self.direction_edit.toPlainText().strip(),
            }

        def _excluded_tag_ids(self) -> list[str]:
            excluded: list[str] = []
            for states in self.tag_states.values():
                excluded.extend(tag_id for tag_id, state in states.items() if state == 2)
            return excluded

        def _accept_tag_settings(self) -> None:
            self.owner.project_tag_selection = self._generation_profile()["selected_tags"]
            self.owner.dialogue_quote_style_value = str(self.quote_combo.currentData() or "cn_quotes")
            self.owner._update_project_tag_summary()
            self.accept()

        def _generate_project_patch(self) -> None:
            if getattr(self.owner, "_async_busy", False):
                self.owner._error("已有后台任务运行中，请稍候")
                return
            self._accept_tag_settings_without_close()
            self.last_project_patch = {}
            self.detail_text.setPlainText("")
            self._set_generation_busy(True, "正在生成项目修改建议...")
            self.owner._temporary_stream_targets["project_assist"] = self.detail_text
            profile = self._generation_profile()

            def action() -> dict[str, Any]:
                try:
                    return {"ok": True, "result": self.owner._run_streaming_project_assist(profile)}
                except Exception as exc:
                    return {"ok": False, "error": str(exc)}

            self.owner._run_async(action, "正在生成项目修改建议...", "", self._after_generate_project_patch)

        def _accept_tag_settings_without_close(self) -> None:
            self.owner.project_tag_selection = self._generation_profile()["selected_tags"]
            self.owner.dialogue_quote_style_value = str(self.quote_combo.currentData() or "cn_quotes")
            self.owner._update_project_tag_summary()

        def _after_generate_project_patch(self, result: dict[str, Any]) -> bool:
            self._set_generation_busy(False, "")
            self.owner._temporary_stream_targets.pop("project_assist", None)
            self.owner.refresh_logs()
            if not result.get("ok"):
                self.status_label.setText(str(result.get("error") or "生成修改建议失败"))
                self.owner._error(str(result.get("error") or "生成修改建议失败"))
                return False
            payload = result.get("result", {}) if isinstance(result, dict) else {}
            self.last_project_patch = payload.get("project_patch", {}) if isinstance(payload, dict) else {}
            if self.last_project_patch:
                self.status_label.setText("已生成修改建议，可点击“应用修改到项目表单”")
            else:
                self.status_label.setText("未生成可应用的字段修改，请调整修改方向后重试")
            return False

        def _apply_project_patch(self) -> None:
            if not self.last_project_patch:
                self.owner._error("请先生成修改建议")
                return
            self.owner._apply_project_patch_to_form(self.last_project_patch)
            self.status_label.setText("修改建议已应用到项目表单，请回到项目页保存")

        def _set_generation_busy(self, busy: bool, message: str) -> None:
            self.generate_button.setEnabled(not busy)
            self.apply_button.setEnabled(not busy)
            self.progress_bar.setVisible(busy)
            if message:
                self.status_label.setText(message)


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
            self._temporary_stream_targets: dict[str, QTextEdit] = {}
            self.automation_cancel_event: threading.Event | None = None
            self.app = QApplication.instance() or QApplication([])
            self.app.setStyle("Fusion")
            self.bridge = _AsyncBridge()
            self.bridge.success.connect(self._complete_async_success)
            self.bridge.error.connect(self._complete_async_error)
            self.bridge.stream.connect(self._append_streaming_target)
            self.bridge.status.connect(self._ok)
            self.window = QMainWindow()
            self.window.setWindowTitle(title)
            self.window.setWindowFlags(self.window.windowFlags() | Qt.WindowType.FramelessWindowHint)
            _apply_windows_round_corners(self.window)
            # 手动调整主窗口初始大小的位置：第一个数字是宽度，第二个数字是高度。
            # 例如可改为 QSize 接近的 1040x680 或 1120x720；不要改回按屏幕比例自动计算。
            self.window.resize(1260, 775)
            self._build()
            self._place_window_on_startup_screen()
            self.refresh_projects()

        def _place_window_on_startup_screen(self) -> None:
            # 启动位置修正：优先显示在鼠标当前所在屏幕，而不是总是交给系统放到主屏。
            # 这能减少主屏/副屏缩放比例不一致时，新窗口先落到错误屏幕后被 DPI 换算放大的问题。
            screen = QApplication.screenAt(QCursor.pos()) or self.window.screen() or QApplication.primaryScreen()
            if screen is None:
                return
            available = screen.availableGeometry()
            margin = 24
            current_size = self.window.size()
            max_width = max(self.window.minimumWidth(), available.width() - margin * 2)
            max_height = max(self.window.minimumHeight(), available.height() - margin * 2)
            target_width = min(current_size.width(), max_width)
            target_height = min(current_size.height(), max_height)
            if target_width != current_size.width() or target_height != current_size.height():
                self.window.resize(target_width, target_height)
            geometry = QRect(0, 0, self.window.width(), self.window.height())
            geometry.moveCenter(available.center())
            min_x = available.left() + margin
            max_x = available.right() - geometry.width() + 1 - margin
            min_y = available.top() + margin
            max_y = available.bottom() - geometry.height() + 1 - margin
            if max_x < min_x:
                min_x = available.left()
                max_x = available.right() - geometry.width() + 1
            if max_y < min_y:
                min_y = available.top()
                max_y = available.bottom() - geometry.height() + 1
            geometry.moveLeft(max(min_x, min(geometry.left(), max_x)))
            geometry.moveTop(max(min_y, min(geometry.top(), max_y)))
            self.window.move(geometry.topLeft())

        def run(self) -> None:
            self.window.show()
            _apply_windows_round_corners(self.window)
            self.app.exec()

        def _build(self) -> None:
            root = QWidget()
            root.setObjectName("AppRoot")
            layout = QVBoxLayout(root)
            layout.setContentsMargins(12, 12, 12, 10)
            layout.addWidget(WindowTitleBar("My AI Novel    结构化小说生产流水线", self.window))

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
            self._build_relation_graph_page()
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

        def _vertical_scroll_area(self, widget: QWidget) -> QScrollArea:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(widget)
            return scroll

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
            left.addWidget(self._button("新建空白项目", self.open_new_project_choice_dialog))
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
            parent.addWidget(self._button("选择标签/辅助修改", self.edit_project_tags_dialog))

        def _build_outline_page(self) -> None:
            page = self._add_page("总框架")
            self.outline_page = page
            layout = QHBoxLayout(page)
            splitter = QSplitter(Qt.Orientation.Horizontal)
            layout.addWidget(splitter)
            left_frame = QWidget()
            left = QVBoxLayout(left_frame)
            left.setContentsMargins(0, 0, 8, 0)
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
            self.outline_versions.setMinimumHeight(280)
            left.addWidget(self.outline_versions, 4)
            left.addWidget(self._button("删除总框架版本", self.delete_selected_outline_version))
            splitter.addWidget(self._vertical_scroll_area(left_frame))
            right = QSplitter(Qt.Orientation.Vertical)
            self.outline_text = QTextEdit()
            self.outline_text.setObjectName("WritingEditor")
            self.outline_split_preview = QTextEdit()
            self.outline_split_preview.setObjectName("StreamingOutput")
            self.outline_split_preview.setPlaceholderText("确认并拆分章节的流式输出")
            right.addWidget(self.outline_text)
            right.addWidget(self.outline_split_preview)
            splitter.addWidget(right)
            splitter.setStretchFactor(0, 1)
            splitter.setStretchFactor(1, 2)
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

        def _build_relation_graph_page(self) -> None:
            page = self._add_page("关系图")
            self.relation_graph_page = page
            layout = QVBoxLayout(page)

            toolbar = QHBoxLayout()
            self.relation_graph_mode = QComboBox()
            self.relation_graph_mode.addItems(["人物关系", "事件关系"])
            self.relation_graph_mode.currentTextChanged.connect(lambda _text: self.refresh_relation_graph())
            toolbar.addWidget(QLabel("图谱类型"))
            toolbar.addWidget(self.relation_graph_mode)
            self.relation_graph_search = QLineEdit()
            self.relation_graph_search.setPlaceholderText("搜索人物、事件或摘要")
            self.relation_graph_search.textChanged.connect(lambda _text: self.refresh_relation_graph())
            toolbar.addWidget(self.relation_graph_search, 1)
            self.relation_graph_inferred = QCheckBox("显示弱推断关系")
            self.relation_graph_inferred.setChecked(True)
            self.relation_graph_inferred.stateChanged.connect(lambda _state: self.refresh_relation_graph())
            toolbar.addWidget(self.relation_graph_inferred)
            toolbar.addWidget(self._button("刷新图谱", self.refresh_relation_graph))
            toolbar.addWidget(self._button("适配窗口", self.fit_relation_graph))
            layout.addLayout(toolbar)

            splitter = QSplitter(Qt.Orientation.Horizontal)
            left_panel = QFrame()
            left_panel.setObjectName("ProjectShelfPane")
            left = QVBoxLayout(left_panel)
            title = QLabel("筛选说明")
            title.setObjectName("PanelTitle")
            left.addWidget(title)
            self.relation_graph_hint = QTextEdit()
            self.relation_graph_hint.setReadOnly(True)
            self.relation_graph_hint.setPlainText(
                "人物关系读取角色卡 JSON 的 relationships，并可从章节/小节共同出现推断弱关系。\n\n"
                "事件关系读取事件、伏笔、地点、组织、规则、章节和小节信息。第一版只读，不会写回资料库。"
            )
            left.addWidget(self.relation_graph_hint, 1)
            splitter.addWidget(left_panel)

            self.relation_graph_view = RelationGraphView(self._on_relation_graph_selected, self._open_world_item_from_graph)
            splitter.addWidget(self.relation_graph_view)

            right_panel = QFrame()
            right_panel.setObjectName("ProjectDetailPane")
            right = QVBoxLayout(right_panel)
            detail_title = QLabel("详情")
            detail_title.setObjectName("PanelTitle")
            right.addWidget(detail_title)
            self.relation_graph_detail = QTextEdit()
            self.relation_graph_detail.setReadOnly(True)
            right.addWidget(self.relation_graph_detail, 1)
            right.addWidget(self._button("在资料库中打开", self.open_selected_relation_graph_item))
            self.save_relation_graph_item_button = self._button("保存为资料库条目", self.save_selected_relation_graph_item)
            self.save_relation_graph_item_button.setEnabled(False)
            right.addWidget(self.save_relation_graph_item_button)
            splitter.addWidget(right_panel)
            splitter.setStretchFactor(0, 1)
            splitter.setStretchFactor(1, 4)
            splitter.setStretchFactor(2, 2)
            splitter.setSizes([220, 640, 300])
            layout.addWidget(splitter, 1)
            self.current_relation_graph_item: dict[str, Any] | None = None

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
                widget.setMinimumHeight(34)
                self.structure_fields[key] = widget
                form.addRow(label, widget)
            right.addLayout(form)
            for label, key in [("人物", "characters"), ("必须发生", "must_happen"), ("禁止内容", "forbidden")]:
                right.addWidget(QLabel(label))
                widget = QTextEdit()
                widget.setMinimumHeight(90)
                widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
            self.world_context_text.setMinimumHeight(180)
            self.world_context_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            right.addWidget(self.world_context_text)
            layout.addWidget(self._vertical_scroll_area(right_frame), 2)

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
                ("删除版本", self.delete_selected_version),
                ("总结本章并更新资料库", self.write_current_chapter_memory),
            ]:
                actions.addWidget(self._button(text, callback))
            layout.addLayout(actions)
            options = QHBoxLayout()
            self.writing_auto_enabled = QCheckBox("自动化：正文 -> 审稿 -> 改写 -> 定稿 -> 继续下一节")
            self.rewrite_mode = QComboBox()
            self.rewrite_mode.addItems(["整体改写", "只改对白", "只改心理", "只改结尾", "增强冲突"])
            self.rewrite_direction_input = QLineEdit()
            self.rewrite_direction_input.setPlaceholderText("可选：本次 AI 修改方向，例如语气更冷、加强冲突、保留第三段")
            options.addWidget(self.writing_auto_enabled)
            options.addWidget(QLabel("改写模式"))
            options.addWidget(self.rewrite_mode)
            options.addWidget(QLabel("AI 修改方向"))
            options.addWidget(self.rewrite_direction_input, 1)
            options.addStretch(1)
            layout.addLayout(options)
            body = QSplitter(Qt.Orientation.Horizontal)
            left_panel = QWidget()
            left_layout = QVBoxLayout(left_panel)
            left_layout.setContentsMargins(0, 0, 0, 0)
            self.version_list_title = QLabel("版本列表")
            self.version_list_title.setObjectName("PanelTitle")
            left_layout.addWidget(self.version_list_title)
            self.version_list = QListWidget()
            self.version_list.setObjectName("SectionList")
            self.version_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
            self.version_list.currentRowChanged.connect(self.show_selected_version)
            left_layout.addWidget(self.version_list)
            right_panel = QWidget()
            right_layout = QVBoxLayout(right_panel)
            right_layout.setContentsMargins(0, 0, 0, 0)
            self.version_text_title = QLabel("")
            self.version_text_title.setObjectName("PanelTitle")
            right_layout.addWidget(self.version_text_title)
            self.version_text = QTextEdit()
            self.version_text.setObjectName("WritingEditor")
            right_layout.addWidget(self.version_text)
            body.addWidget(left_panel)
            body.addWidget(right_panel)
            layout.addWidget(body, 2)
            layout.addWidget(QLabel("当前流式生成内容"))
            self.current_generation_text = QTextEdit()
            self.current_generation_text.setObjectName("StreamingOutput")
            layout.addWidget(self.current_generation_text, 1)

        def _build_settings_page(self) -> None:
            page = self._add_page("设置")
            page_layout = QVBoxLayout(page)
            content = QWidget()
            layout = QVBoxLayout(content)
            form = QFormLayout()
            self.config_vars: dict[str, Any] = {}
            config = load_llm_config()
            for label, key in LLM_CONFIG_FIELDS:
                if key == "model_candidates":
                    widget = QTextEdit()
                    widget.setMinimumHeight(110)
                    widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    widget.setPlainText(str(config.get(key, "")))
                elif key == "api_type":
                    widget = QComboBox()
                    widget.addItems(list(API_TYPE_VALUES))
                    widget.setCurrentText(api_type_display_value(config.get(key)))
                else:
                    widget = QLineEdit(str(config.get(key, "")))
                    widget.setMinimumHeight(34)
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
            self.model_scan_text.setMinimumHeight(220)
            self.model_scan_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            layout.addWidget(QLabel("可用模型"))
            layout.addWidget(self.model_scan_text)
            page_layout.addWidget(self._vertical_scroll_area(content))

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

        def _current_project_form_data(self) -> dict[str, Any]:
            data = {key: self._text(widget) for key, widget in self.project_fields.items()}
            data.update({key: self._text(widget) for key, widget in self.project_texts.items()})
            data.update(self._project_tag_data())
            if self.current_project_id:
                data["id"] = self.current_project_id
            return data

        def _apply_project_patch_to_form(self, patch: dict[str, Any]) -> None:
            for key, value in (patch or {}).items():
                text = str(value or "").strip()
                if not text:
                    continue
                if key in self.project_fields:
                    self._set_text(self.project_fields[key], text)
                elif key in self.project_texts:
                    self._set_text(self.project_texts[key], text)

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
            dialog = ProjectTagAssistDialog(self)
            dialog.exec()

        def open_search_project_creation_dialog(self) -> None:
            dialog = SearchProjectCreationDialog(self)
            dialog.exec()

        def open_new_project_choice_dialog(self) -> None:
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("新建项目")
            dialog.setIcon(QMessageBox.Icon.Question)
            dialog.setText("请选择创建方式")
            manual_button = dialog.addButton("手动填写", QMessageBox.ButtonRole.AcceptRole)
            candidate_button = dialog.addButton("通过标签/候选方案生成", QMessageBox.ButtonRole.ActionRole)
            dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            dialog.setDefaultButton(manual_button)
            dialog.exec()
            if dialog.clickedButton() is manual_button:
                self.start_new_project()
            elif dialog.clickedButton() is candidate_button:
                self.open_search_project_creation_dialog()

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

        def _generate_search_creation_candidates_streaming(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
            def on_delta(delta: str) -> None:
                if delta:
                    self.bridge.stream.emit("search_candidate", delta)

            if hasattr(self.pipeline, "generate_novel_candidates_streaming"):
                result = self.pipeline.generate_novel_candidates_streaming(profile, on_delta)
                candidates = result.get("candidates", result) if isinstance(result, dict) else result
                if isinstance(candidates, list) and candidates:
                    return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]
            candidates = self._generate_search_creation_candidates(profile)
            on_delta(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2))
            return candidates

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

        def _relation_graph_mode_key(self) -> str:
            return "event" if self.relation_graph_mode.currentText() == "事件关系" else "character"

        def _relation_graph_source_data(
            self,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
            if not self.current_project_id:
                return [], [], {}
            world_items = self.store.list_world_items(self.current_project_id)
            chapters = self.store.list_chapters(self.current_project_id)
            sections_by_chapter = {
                int(chapter.get("id", 0)): self.store.list_sections(int(chapter.get("id", 0)))
                for chapter in chapters
            }
            return world_items, chapters, sections_by_chapter

        def refresh_relation_graph(self) -> None:
            if not hasattr(self, "relation_graph_view"):
                return
            self.current_relation_graph_item = None
            if not self.current_project_id:
                graph = {"nodes": [], "edges": [], "warnings": ["请先选择项目"]}
                self.relation_graph_view.render_graph(graph, "character")
                self.relation_graph_detail.setPlainText("请先选择项目")
                self.save_relation_graph_item_button.setEnabled(False)
                return
            world_items, chapters, sections_by_chapter = self._relation_graph_source_data()
            include_inferred = self.relation_graph_inferred.isChecked()
            mode = self._relation_graph_mode_key()
            if mode == "event":
                graph = build_event_graph(world_items, chapters, sections_by_chapter, include_inferred)
            else:
                graph = build_character_graph(world_items, chapters, sections_by_chapter, include_inferred)
            graph = self._filter_relation_graph_for_mode(graph, mode)
            self.relation_graph_view.render_graph(graph, mode, self.relation_graph_search.text())
            node_count = len(graph.get("nodes", []))
            edge_count = len(graph.get("edges", []))
            warnings = graph.get("warnings", [])
            lines = [f"节点：{node_count}", f"关系：{edge_count}"]
            if warnings:
                lines.append("")
                lines.append("提示")
                lines.extend(f"- {warning}" for warning in warnings[:12])
            self.relation_graph_detail.setPlainText("\n".join(lines))
            self.save_relation_graph_item_button.setEnabled(False)

        def fit_relation_graph(self) -> None:
            if hasattr(self, "relation_graph_view"):
                self.relation_graph_view.fit_graph()

        def _on_relation_graph_selected(self, payload: dict[str, Any], payload_type: str) -> None:
            self.current_relation_graph_item = payload if payload_type == "node" else None
            title = "节点详情" if payload_type == "node" else "关系详情"
            lines = [title, ""]
            if payload_type == "node":
                message = self._relation_graph_node_message(payload)
                if message:
                    lines.extend([message, ""])
            for key in ["label", "name", "kind", "summary", "status", "source", "confidence", "evidence"]:
                if key in payload and payload.get(key) not in (None, "", []):
                    value = payload.get(key)
                    if key == "kind":
                        value = self._relation_graph_kind_label(str(value))
                    if isinstance(value, list):
                        value = "、".join(str(item) for item in value)
                    lines.append(f"{key}: {value}")
            if payload_type == "node":
                lines.append("")
                lines.append("双击节点或点击下方按钮，可在资料库中打开对应条目。")
            self.relation_graph_detail.setPlainText("\n".join(lines))
            self.save_relation_graph_item_button.setEnabled(self._relation_graph_node_can_be_saved(payload))

        def open_selected_relation_graph_item(self) -> None:
            if not self.current_relation_graph_item:
                self._error("请先选择一个资料库节点")
                return
            self._open_world_item_from_graph(self.current_relation_graph_item)

        def _open_world_item_from_graph(self, node: dict[str, Any]) -> None:
            try:
                source_id = int(node.get("source_id") or 0)
            except (TypeError, ValueError):
                source_id = 0
            kind = str(node.get("kind") or "")
            if not source_id or kind not in WORLD_ITEM_KINDS:
                self._error(self._relation_graph_node_message(node) or "当前节点不是可打开的资料库条目")
                return
            self.stack.setCurrentWidget(self.world_page)
            index = self.stack.indexOf(self.world_page)
            if index >= 0:
                self.navigation.setCurrentRow(index)
            self._set_world_kind_safely(kind)
            self.refresh_world_items()
            for row, item in enumerate(self.world_rows):
                if int(item.get("id", 0)) == source_id:
                    self.world_list.setCurrentRow(row)
                    self.world_list.scrollToItem(self.world_list.item(row))
                    return
            self._error("资料库中未找到该条目")

        def _relation_graph_node_can_be_saved(self, node: dict[str, Any]) -> bool:
            return (
                str(node.get("source", "")) in {"inferred", "missing_reference"}
                and str(node.get("kind", "")) in self._relation_graph_allowed_save_kinds()
            )

        def _relation_graph_allowed_save_kinds(self) -> set[str]:
            if self._relation_graph_mode_key() == "character":
                return {"character", "organization"}
            return set(WORLD_ITEM_KINDS)

        def _filter_relation_graph_for_mode(self, graph: dict[str, Any], mode: str) -> dict[str, Any]:
            if mode != "character":
                return graph
            allowed = {"character", "organization"}
            nodes = [node for node in graph.get("nodes", []) if str(node.get("kind", "")) in allowed]
            node_ids = {str(node.get("id", "")) for node in nodes}
            edges = [
                edge
                for edge in graph.get("edges", [])
                if str(edge.get("source", "")) in node_ids and str(edge.get("target", "")) in node_ids
            ]
            return {"nodes": nodes, "edges": edges, "warnings": graph.get("warnings", [])}

        def _relation_graph_kind_label(self, kind: str) -> str:
            if kind == "chapter":
                return "章节"
            if kind == "section":
                return "小节"
            return world_kind_label(kind)

        def _relation_graph_node_message(self, node: dict[str, Any]) -> str:
            source = str(node.get("source", ""))
            kind = str(node.get("kind", ""))
            if source == "inferred":
                return "这是推断节点，尚未写入资料库"
            if source == "missing_reference":
                return "这是缺失引用节点，资料库中尚无对应条目"
            if kind in {"chapter", "section"}:
                return "这是章节/小节结构节点，不是资料库条目"
            if kind not in WORLD_ITEM_KINDS:
                return "当前节点不是可打开的资料库条目"
            if not node.get("source_id"):
                return "当前节点缺少资料库条目 ID"
            return ""

        def save_selected_relation_graph_item(self) -> None:
            project_id = self._project_required()
            node = self.current_relation_graph_item
            if not project_id or not node:
                return
            if not self._relation_graph_node_can_be_saved(node):
                self._error(self._relation_graph_node_message(node) or "当前节点不能保存为资料库条目")
                return
            name = str(node.get("name") or node.get("label") or "").strip()
            if not name:
                self._error("当前节点缺少名称，无法保存")
                return
            kind = str(node.get("kind", ""))
            details = {
                "source": "relation_graph",
                "created_from": str(node.get("source", "")),
                "graph_node_id": str(node.get("id", "")),
                "evidence": node.get("evidence", []),
            }
            if kind == "character":
                details = normalize_character_card_details(details)
            item_id = self.store.save_world_item(
                project_id,
                {
                    "kind": kind,
                    "name": name,
                    "summary": str(node.get("summary", "") or ""),
                    "details_json": details,
                    "tags": "关系图生成",
                    "status": "candidate",
                },
            )
            self.refresh_world_items()
            self.refresh_relation_graph()
            self._ok("已保存为资料库条目")
            if item_id:
                self._open_world_item_from_graph({"kind": kind, "source_id": item_id})

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
            if hasattr(self, "relation_graph_detail"):
                self.relation_graph_detail.clear()
                self.current_relation_graph_item = None
                self.refresh_relation_graph()
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
            data = self._current_project_form_data()
            data.pop("id", None)
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

        def delete_selected_outline_version(self) -> None:
            version_id = self._selected_outline_version()
            if not version_id:
                self._error("请选择一个总框架版本")
                return
            self.store.delete_version(version_id)
            self.outline_text.clear()
            self.outline_split_preview.clear()
            self.refresh_outline_versions()
            self.select_latest_outline_version()
            self.refresh_logs()
            self._ok("总框架版本已删除")

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
            self.refresh_relation_graph()
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
            if kind == "character":
                mode = self._ask_character_creation_mode()
                if mode is None:
                    return
                if mode == "tagged":
                    profile = self._ask_tagged_character_profile()
                    if profile is None:
                        return
                    self._clear_world_form(reset_kind=False)
                    self.world_summary.setPlainText("正在根据角色标签生成角色卡 JSON...\n")
                    self._run_async(
                        lambda: self._run_streaming_tagged_character(project_id, profile),
                        "正在标签化生成角色卡，请稍候...",
                        "角色卡已标签化生成",
                        self._after_create_world_item_with_ai,
                    )
                    return
            self._clear_world_form(reset_kind=False)
            self.world_summary.setPlainText("正在连接模型，准备流式生成资料 JSON...\n")
            self._run_async(
                lambda: self._run_streaming_world_item(project_id, kind),
                f"正在自动创建{world_kind_label(kind)}，请稍候...",
                "资料已自动创建",
                self._after_create_world_item_with_ai,
            )

        def _ask_character_creation_mode(self) -> str | None:
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("创建角色卡")
            dialog.setText("请选择角色卡 AI 自动创建方式。")
            normal_button = dialog.addButton("普通生成", QMessageBox.ButtonRole.AcceptRole)
            tagged_button = dialog.addButton("标签化生成", QMessageBox.ButtonRole.ActionRole)
            dialog.addButton(QMessageBox.StandardButton.Cancel)
            dialog.exec()
            clicked = dialog.clickedButton()
            if clicked == normal_button:
                return "normal"
            if clicked == tagged_button:
                return "tagged"
            return None

        def _ask_tagged_character_profile(self) -> dict[str, Any] | None:
            dialog = TaggedCharacterCreationDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            return dialog.generation_profile()

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
                direction = self.rewrite_direction_input.text().strip()
                cancel_event = threading.Event()
                self.automation_cancel_event = cancel_event
                self._run_async(
                    lambda: self._run_single_writing_automation(
                        project_id,
                        section_id,
                        self.rewrite_mode.currentText(),
                        cancel_event,
                        direction=direction,
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
                    self.rewrite_mode.currentText(),
                    [],
                    self.rewrite_direction_input.text().strip(),
                ),
                "正在按意见改写，请稍候...",
                "改写完成",
                lambda _result: self._after_writing_task(),
            )

        def _after_writing_task(self) -> None:
            self._refresh_structure_preserving_selection()
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

        def _run_streaming_world_item(self, project_id: int, kind: str) -> dict[str, Any]:
            self.bridge.stream.emit("world_item", "")

            def on_delta(delta: str) -> None:
                if delta:
                    self.bridge.stream.emit("world_item", delta)

            if hasattr(self.pipeline, "generate_world_item_streaming"):
                return self.pipeline.generate_world_item_streaming(project_id, kind, on_delta)
            result = self.pipeline.generate_world_item(project_id, kind)
            preview = json.dumps(result.get("world_item", result), ensure_ascii=False, indent=2)
            on_delta(preview)
            return result

        def _run_streaming_tagged_character(self, project_id: int, profile: dict[str, Any]) -> dict[str, Any]:
            self.bridge.stream.emit("world_item", "")

            def on_delta(delta: str) -> None:
                if delta:
                    self.bridge.stream.emit("world_item", delta)

            if hasattr(self.pipeline, "generate_tagged_character_streaming"):
                return self.pipeline.generate_tagged_character_streaming(project_id, profile, on_delta)
            result = self.pipeline.generate_tagged_character(project_id, profile)
            preview = json.dumps(result.get("world_item", result), ensure_ascii=False, indent=2)
            on_delta(preview)
            return result

        def _run_streaming_project_assist(self, profile: dict[str, Any]) -> dict[str, Any]:
            self.bridge.stream.emit("project_assist", "")

            def on_delta(delta: str) -> None:
                if delta:
                    self.bridge.stream.emit("project_assist", delta)

            if hasattr(self.pipeline, "assist_project_edit_streaming"):
                return self.pipeline.assist_project_edit_streaming(profile, on_delta)
            result = self.pipeline.assist_project_edit(profile)
            preview = json.dumps(result, ensure_ascii=False, indent=2)
            on_delta(preview)
            return result

        def _append_streaming_target(self, target: str, delta: str) -> None:
            widgets = {
                "outline": self.outline_text,
                "outline_split": self.outline_split_preview,
                "draft": self.current_generation_text,
                "world_item": self.world_summary,
            }
            widgets.update(getattr(self, "_temporary_stream_targets", {}))
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
            direction: str = "",
        ) -> dict[str, Any]:
            self._raise_if_automation_cancelled(cancel_event)
            draft = self._run_streaming_draft(project_id, section_id)
            draft_version_id = int(draft["version_id"])
            self._raise_if_automation_cancelled(cancel_event)
            review = self.pipeline.review_section(project_id, section_id, draft_version_id)
            review_version_id = int(review["version_id"])
            self._raise_if_automation_cancelled(cancel_event)
            rewrite = self.pipeline.rewrite_section(project_id, section_id, draft_version_id, review_version_id, rewrite_mode, [], direction)
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
                    direction=self.rewrite_direction_input.text().strip(),
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
            direction: str = "",
        ) -> dict[str, Any]:
            processed: list[int] = []
            section_id = start_section_id
            self._configure_llm_retry(cancel_event)
            try:
                while True:
                    self._raise_if_automation_cancelled(cancel_event)
                    section = self.store.get_section(section_id)
                    if not section or int(section["chapter_id"]) != int(chapter_id):
                        break
                    result = self._run_writing_automation(project_id, section_id, rewrite_mode, cancel_event, direction)
                    processed.append(section_id)
                    next_section = result.get("next_section")
                    if isinstance(next_section, dict) and int(next_section.get("chapter_id", chapter_id)) == int(chapter_id):
                        section_id = int(next_section["id"])
                        continue
                    self._try_write_chapter_memory(project_id, chapter_id, cancel_event)
                    if auto_next_chapter:
                        next_chapter_section = self._first_section_in_next_chapter(project_id, chapter_id)
                        if next_chapter_section is not None:
                            chapter_id = int(next_chapter_section["chapter_id"])
                            section_id = int(next_chapter_section["id"])
                            continue
                    return {"processed": processed, "last_section_id": section_id, "next_section": None}
            finally:
                if hasattr(self.services.llm, "configure_retry_until_cancel"):
                    self.services.llm.configure_retry_until_cancel(None, None)
            return {"processed": processed, "last_section_id": section_id, "next_section": None}

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
            except Exception as exc:  # noqa: BLE001 - chapter memory must not block finalized prose
                return {"ok": False, "chapter_id": chapter_id, "error": str(exc)}
            finally:
                if retry_supported and cancel_event is not None and not cancel_event.is_set():
                    self._configure_llm_retry(cancel_event)

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
            self.refresh_world_items()
            self.refresh_logs()
            last_section_id = result.get("last_section_id") if isinstance(result, dict) else None
            if last_section_id:
                self._select_next_section_for_writing(int(last_section_id))
            else:
                self._refresh_structure_preserving_selection()
            processed = result.get("processed", []) if isinstance(result, dict) else []
            return f"章节自动化写作完成，已处理 {len(processed)} 节"

        def _configure_llm_retry(self, cancel_event: threading.Event) -> None:
            if not hasattr(self.services.llm, "configure_retry_until_cancel"):
                return

            def on_retry(attempt: int, delay: int, error: str) -> None:
                self.bridge.status.emit(f"API 调用失败，{delay} 秒后第 {attempt + 1} 次重试：{error}")

            self.services.llm.configure_retry_until_cancel(cancel_event, on_retry)

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
            self.automation_cancel_event = None
            next_section = result.get("next_section") if isinstance(result, dict) else None
            if isinstance(next_section, dict) and self.structure_auto_next_enabled.isChecked():
                self._select_next_section_for_writing(int(next_section["id"]))
                self.refresh_logs()
                return "自动化写作完成，已切换到下一节"
            self._refresh_structure_preserving_selection()
            self.refresh_logs()
            message = str(result.get("next_message", "") if isinstance(result, dict) else "").strip()
            return f"自动化写作完成，{message}" if message else "自动化写作完成"

        def _raise_if_automation_cancelled(self, cancel_event: threading.Event | None) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("用户已中断自动化写作")

        def refresh_versions(self) -> None:
            self.version_list.clear()
            self.current_version_ids = []
            self.version_rows = []
            self._set_version_text_title(None)
            if hasattr(self, "version_text"):
                self.version_text.clear()
            if not self.current_project_id or not self.current_section_id:
                return
            self.version_rows = self.store.list_versions(self.current_project_id, section_id=self.current_section_id)
            for index, row in enumerate(self.version_rows, 1):
                self.current_version_ids.append(int(row["id"]))
                item = QListWidgetItem(f"{index} | {row['kind']} | {row['status']} | {row['label']}")
                item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                self.version_list.addItem(item)

        def _set_version_text_title(self, row: dict[str, Any] | None, prefix: str = "版本内容") -> None:
            if not hasattr(self, "version_text_title"):
                return
            if not row:
                self.version_text_title.setText("")
                return
            version_id = int(row.get("id", 0) or 0)
            index = self.current_version_ids.index(version_id) + 1 if version_id in self.current_version_ids else "?"
            self.version_text_title.setText(
                f"{prefix}：{index} | {row.get('kind', '')} | {row.get('status', '')} | {row.get('label', '')}"
            )

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

        def _display_version_id(self, row_index: int | None = None) -> int | None:
            if row_index is not None and 0 <= row_index < len(self.current_version_ids):
                return int(self.current_version_ids[row_index])
            item = self.version_list.currentItem()
            if item is not None:
                return int(item.data(Qt.ItemDataRole.UserRole))
            return self._single_selected_version()

        def show_selected_version(self, row_index: int | None = None) -> None:
            version_id = self._display_version_id(row_index)
            if not version_id:
                self._set_version_text_title(None)
                self.version_text.clear()
                return
            row = self.store.get_version(version_id)
            self._set_version_text_title(row)
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
            if hasattr(self, "version_text_title"):
                self.version_text_title.setText(f"版本比较：{selected[0]} ↔ {selected[1]}")
            self.version_text.setPlainText("\n".join(diff))

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
            self.version_text.clear()
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
            self.refresh_relation_graph()
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
