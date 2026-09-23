# -*- coding: utf-8 -*-
"""
STUKACH for Maya — Qt panel, pixel-faithful replica of the Blender add-on UI.

Layout (top to bottom, mirrors Blender's ASSET_CHECKER_PT_Panel v1.6.x):
  STUKACH v1.3.0 / Pipeline Snitch System
  [ RUN STUKACH ]
  [ Coordinator Mode | Live ]
  score block: status line + health-strip + [Next Issue][Copy Summary]
  [Scene][Selected][x]
  batch: All None Blk Wrn ... Viewport
  Scene Units row
  Pipeline Checks: collapsible categories (2-col grid, swatches, naming fields)
  presets row
  Objects (collapsible): search/issues/expand-all, worst-first details
  Ignored Issues (n)
  ASSET STATUS box
  Export: JSON/CSV/HTML | Pre-flight: FBX | Debug Info
  Coordinator page: status badge, units, scope, Copy Report, C&W checks

Compatible with Maya 2022+ (PySide2) and Maya 2025+ (PySide6).
"""
from __future__ import annotations

import contextlib
from typing import Dict

import maya.cmds as cmds

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Qt
    from shiboken2 import wrapInstance
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui
    from PySide6.QtCore import Qt
    from shiboken6 import wrapInstance

import maya.OpenMayaUI as omui

from . import core as _core
from . import manager as _manager
from . import overlay as _overlay

_VERSION = _manager._VERSION


# ── Maya-native font + DPI scaling ────────────────────────────────────────────

def _get_base_font_size() -> int:
    """Get Maya's native app font pixel size — use as base unit for all sizing."""
    try:
        app = QtWidgets.QApplication.instance()
        return app.font().pixelSize() if app.font().pixelSize() > 0 else 13
    except Exception:
        return 13


_FONT_PX = _get_base_font_size()
_S = _FONT_PX / 13.0


def _px(base: int) -> int:
    """Scale pixel value by font ratio — matches Maya's native sizing."""
    return max(1, int(base * _S))


def dpi_scale(value: int) -> int:
    try:
        return int(value * cmds.mayaDpiSetting(query=True, realScaleValue=True))
    except Exception:
        return value


# Fixed heights for TEXT buttons must exceed the PHYSICALLY rendered font:
# on some monitors Qt logical metrics are ~25% smaller than the drawn glyphs,
# and tight heights clip the label bottom (Copy Summary, Rename, mini Fix...)
_BTN_H = _px(30)   # standard text button
_BTN_H_SM = _px(26)   # compact text button
_BTN_H_XS = _px(24)   # mini button (Sel/Ign/Fix, S/D, x)


@contextlib.contextmanager
def block_signals(*widgets):
    for w in widgets:
        w.blockSignals(True)
    try:
        yield
    finally:
        for w in widgets:
            w.blockSignals(False)


def undo_decorator(func):
    def wrapper(*args, **kwargs):
        cmds.undoInfo(openChunk=True)
        try:
            return func(*args, **kwargs)
        finally:
            cmds.undoInfo(closeChunk=True)
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


# ── Blender 4.x dark palette ──────────────────────────────────────────────────

_C_BG       = "#1d1d1d"   # panel background
_C_TITLE    = "#c8c8c8"   # section titles
_C_SELECT   = "#4772b3"   # action blue (RUN, checked)
_C_TEXT     = "#e6e6e6"
_C_SUBTEXT  = "#8c8c8c"
_C_GREY     = "#606060"
_C_GREEN    = "#477a3c"
_C_YELLOW   = "#b0a060"
_C_RED      = "#ad4133"

# Checks with an auto-fix operator (category Fix button + per-row Fix)
_FIXABLE = frozenset({"non_applied_transform", "scale", "construction_history",
                      "non_manifold", "mat_suffix", "unused_data"})


def _coordinator_lock() -> bool:
    """Coordinator Lock (optionVar stukachCoordinatorLock) + Coordinator Mode:
    the curator reviews and reports; fix actions are hidden."""
    try:
        return bool(_manager.MayaCheck.coordinator_mode
                    and cmds.optionVar(query="stukachCoordinatorLock"))
    except Exception:
        return False

_CHECK_SWATCH = {
    "triangles": "#B2B205", "ngons": "#B20505", "non_manifold": "#05FF05",
    "zero_area": "#FF00FF", "poles": "#4066FF", "isolated_verts": "#FFFF00",
    "boundary_edges": "#FF8000", "duplicate_verts": "#FF9900",
    "face_aspect_ratio": "#FFD900", "z_fighting": "#FF0000",
    "non_applied_transform": "#FF0000", "scale": "#FF6600",
    "construction_history": "#808080", "origin_at_zero": "#FFCC00",
    "symmetry_x": "#FF2626", "symmetry_y": "#26FF26",
    "symmetry_z": "#2666FF", "uv_single_set": "#0080FF", "uv_udim_ready": "#0080FF",
    "uv_udim_bounds": "#B233FF", "uv_material_udim": "#FF3399",
    "uv_overlap": "#FF3300", "uv_stretch": "#FF8000", "uv_texel_density": "#4DE680",
    "uv_micro_shell": "#FF00CC", "uv_padding": "#FF9900",
    "obj_naming": "#FF8000", "col_naming": "#808080", "mat_numbering": "#FF6619",
    "mat_suffix": "#808080", "mat_assignment": "#808080",
    "missing_textures": "#FF3333", "unused_data": "#99661A",
    "hard_edges": "#CC6600", "lamina": "#FF0066",
    "zero_length_edges": "#FF33CC", "starlike": "#66FFCC",
    "missing_uvs": "#CCFF33", "duplicated_names": "#FF1111",
    "shape_names": "#FF9900", "trailing_numbers": "#FFCC66",
    "uncentered_pivots": "#FFCC00", "parent_geometry": "#99FF33",
}

# Per-check color overrides (user-chosen via swatch click)
_CHECK_COLOR_OVERRIDES: Dict[str, str] = {}  # key -> "#RRGGBB"

_CAT_ICONS = {
    "TOPOLOGY": "▲", "TRANSFORMS": "⇄", "SYMMETRY": "⊟",
    "UV": "◊", "NAMING": "⚐", "MATERIALS": "◈", "CLEANUP": "✦",
}

_CHECK_DISPLAY_NAMES = {
    "triangles": "Triangles", "ngons": "Ngons", "non_manifold": "Non Manifold",
    "zero_area": "Zero Area", "poles": "Poles", "isolated_verts": "Isolated Verts",
    "boundary_edges": "Boundary Edges", "duplicate_verts": "Duplicate Verts",
    "face_aspect_ratio": "Face Aspect Ratio", "z_fighting": "Z-Fighting",
    "non_applied_transform": "Non Applied Transform", "scale": "Scale",
    "construction_history": "Construction History", "origin_at_zero": "Origin at Zero",
    "symmetry_x": "Symmetry X",
    "symmetry_y": "Symmetry Y", "symmetry_z": "Symmetry Z",
    "uv_single_set": "UV Single Set", "uv_udim_ready": "UV UDIM Ready",
    "uv_udim_bounds": "UV UDIM Bounds", "uv_material_udim": "UV Material UDIM",
    "uv_overlap": "UV Overlap", "uv_stretch": "UV Stretch",
    "uv_texel_density": "UV Texel Density", "uv_micro_shell": "UV Micro Shell",
    "uv_padding": "UV Padding", "obj_naming": "Object Name",
    "col_naming": "Group Name", "mat_numbering": "Mat Numbering",
    "mat_suffix": "Mat Suffix", "mat_assignment": "Mat Assignment",
    "missing_textures": "Missing Textures", "unused_data": "Unused Data",
    "hard_edges": "Sharp Edges Not Hard", "lamina": "Lamina",
    "zero_length_edges": "Zero Length Edges", "starlike": "Starlike",
    "missing_uvs": "Missing UVs", "duplicated_names": "Duplicated Names",
    "shape_names": "Shape Names", "trailing_numbers": "Trailing Numbers",
    "uncentered_pivots": "Uncentered Pivots", "parent_geometry": "Parent Geometry",
}

_YELLOW_THRESHOLDS = {"triangles": 50, "ngons": 10, "poles": 20}

# metric_text longer than this renders on its own full-width row
_METRIC_FULL_WIDTH = 34


def _build_qss() -> str:
    """Blender-dark QSS — as in PROKLADKA (approved reference styling)."""
    f = _FONT_PX
    c = _px(16)   # checkbox indicator
    return (
        "QWidget { background: #1d1d1d; color: #e6e6e6; font-family: 'Segoe UI','Arial',sans-serif; font-size: %dpx; }"
        "QPushButton { background: #303030; color: #e6e6e6; border: 1px solid #3a3a3a; border-radius: 3px; padding: %dpx %dpx; font-size: %dpx; }"
        "QPushButton:hover { background: #3d3d3d; }"
        "QPushButton:pressed { background: #252525; }"
        "QPushButton:disabled { color: #606060; background: #252525; }"
        "QPushButton:checked { background: #4772b3; color: white; border-color: #4772b3; }"
        "QCheckBox { spacing: 5px; }"
        "QCheckBox::indicator { width: %dpx; height: %dpx; border: 1px solid #555; border-radius: 2px; background: #252525; }"
        "QCheckBox::indicator:hover { border-color: #4772b3; }"
        "QCheckBox::indicator:checked { background: #4772b3; border-color: #4772b3; image: none; }"
        "QLineEdit { background: #252525; color: #e6e6e6; border: 1px solid #3a3a3a; border-radius: 3px; padding: %dpx %dpx; font-size: %dpx; selection-background-color: #4772b3; }"
        "QComboBox { background: #303030; color: #e6e6e6; border: 1px solid #3a3a3a; padding: 3px 8px; font-size: %dpx; border-radius: 3px; }"
        "QComboBox::drop-down { border: none; width: %dpx; }"
        "QComboBox QLineEdit { background: #252525; color: #e6e6e6; border: none; }"
        "QComboBox QAbstractItemView { background: #252525; color: #e6e6e6; selection-background-color: #3d5d8a; border: 1px solid #3a3a3a; outline: none; }"
        "QScrollArea { border: none; background: transparent; }"
        "QScrollBar:vertical { background: #1d1d1d; width: %dpx; border: none; }"
        "QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 4px; min-height: %dpx; }"
        "QScrollBar::handle:vertical:hover { background: #4a4a4a; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        "QLabel { background: transparent; }"
        "QToolButton { color: #8c8c8c; border: none; font-size: %dpx; padding: 0; }"
        "QToolButton:hover { color: #e6e6e6; }"
        "QFrame#catBox { background: #212121; border: 1px solid #303030; border-radius: 4px; }"
        "QWidget#StukachPanel { background-color: #1d1d1d; border: 1px solid #2f2f2f; border-radius: 8px; }"
    ) % (f, _px(4), _px(10), f, c, c, _px(2), _px(6), f,
         f, _px(20), _px(12), _px(30), max(1, f - 1))


_QSS = _build_qss()


# ── Small painted widgets ─────────────────────────────────────────────────────

class _StatusDot(QtWidgets.QWidget):
    """Circular status indicator — like Blender's icon column."""
    def __init__(self, parent=None, size=10):
        super().__init__(parent)
        self._size = _px(size)
        self.setFixedSize(self._size + _px(2), self._size + _px(2))
        self._color = _C_GREY

    def set_color(self, hex_color: str):
        self._color = hex_color
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(QtGui.QBrush(QtGui.QColor(self._color)))
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(_px(1), _px(1), self._size, self._size)


class _Swatch(QtWidgets.QWidget):
    """Colored dot — click to pick a new overlay color for this check."""
    colorChanged = QtCore.Signal(str, str)  # (check_key, "#RRGGBB")

    def __init__(self, key: str, color: str = "#808080", parent=None):
        super().__init__(parent)
        self._key = key
        self._color = color
        self.setFixedSize(_px(14), _px(14))
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setToolTip("Click to change viewport overlay color")

    def set_color(self, hex_color: str):
        self._color = hex_color
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(QtGui.QBrush(QtGui.QColor(self._color)))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 1))
        p.drawEllipse(1, 1, _px(11), _px(11))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            current = QtGui.QColor(self._color)
            color = QtWidgets.QColorDialog.getColor(current, self, "Pick overlay color")
            if color.isValid():
                hex_c = color.name()
                self._color = hex_c
                _CHECK_COLOR_OVERRIDES[self._key] = hex_c
                self.update()
                self.colorChanged.emit(self._key, hex_c)


class _HealthStrip(QtWidgets.QWidget):
    """Blender health-strip: one color cell per category (green/yellow/red)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(_px(2), _px(1), _px(2), _px(1))
        lay.setSpacing(_px(2))
        self._cells: Dict[str, QtWidgets.QFrame] = {}
        for cat in _core.CHECK_CATEGORIES:
            cell = QtWidgets.QFrame()
            cell.setFixedHeight(_px(12))
            cell.setStyleSheet("background: %s; border-radius: 2px;" % "#3a3a3a")
            cell.setToolTip(cat.title())
            lay.addWidget(cell, stretch=1)
            self._cells[cat] = cell

    def refresh(self, summary: Dict[str, "tuple[int, int]"]) -> None:
        for cat, (b, w) in summary.items():
            cell = self._cells.get(cat)
            if cell is None:
                continue
            if b:
                color = _C_RED
            elif w:
                color = _C_YELLOW
            else:
                color = _C_GREEN
            cell.setStyleSheet("background: %s; border-radius: 2px;" % color)


def _status_color(count: int, key: str) -> str:
    if count == 0:
        return _C_GREEN
    thresh = _YELLOW_THRESHOLDS.get(key, 0)
    if thresh and count <= thresh:
        return _C_YELLOW
    return _C_RED


# ── Check grid row (categories): [checkbox] Label  [swatch] ───────────────────

class _CheckGridRow(QtWidgets.QWidget):
    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self.setFixedHeight(_BTN_H)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(_px(4), 0, _px(4), 0)
        layout.setSpacing(_px(4))

        self._toggle = QtWidgets.QCheckBox()
        self._toggle.setToolTip("Shift+click to isolate this check")
        self._toggle.stateChanged.connect(self._on_toggle)
        layout.addWidget(self._toggle)

        self._name_label = QtWidgets.QLabel(
            _CHECK_DISPLAY_NAMES.get(key, key.replace("_", " ").title()))
        layout.addWidget(self._name_label, stretch=1)

        self._swatch = _Swatch(key, _CHECK_SWATCH.get(key, "#808080"), self)
        self._swatch.colorChanged.connect(self._on_color_changed)
        layout.addWidget(self._swatch)

    def refresh(self) -> None:
        enabled = _manager.MayaCheck._enabled_checks.get(self._key, False)
        self._toggle.blockSignals(True)
        self._toggle.setChecked(enabled)
        self._toggle.blockSignals(False)
        override = _CHECK_COLOR_OVERRIDES.get(self._key)
        if override:
            self._swatch.set_color(override)
        elif self._key in _CHECK_SWATCH:
            self._swatch.set_color(_CHECK_SWATCH[self._key])

    def _on_toggle(self, state: int) -> None:
        if QtWidgets.QApplication.keyboardModifiers() & Qt.ShiftModifier:
            # Isolate — revert visual state, let manager drive the UI update
            self._toggle.blockSignals(True)
            self._toggle.setChecked(not (int(state) == 2))
            self._toggle.blockSignals(False)
            _manager.MayaCheck.isolate_check(self._key)
            return
        enabled = (int(state) == 2)
        _manager.MayaCheck.set_check_enabled(self._key, enabled)
        _manager.MayaCheck.run_all()

    def _on_color_changed(self, key: str, hex_color: str) -> None:
        _overlay.set_check_color(key, hex_color)
        if _manager.MayaCheck._running and _manager.MayaCheck.objects:
            _overlay.refresh_colors(
                _manager.MayaCheck.objects, _manager.MayaCheck.active_check)


# ── Category box: [v] ICON Title ... [Fix] [checkbox] + 2-column grid ─────────

class _CategoryBox(QtWidgets.QFrame):
    def __init__(self, category: str, keys: tuple, parent=None):
        super().__init__(parent)
        self.setObjectName("catBox")
        self._category = category
        self._keys = keys
        self._open = False   # collapsed by default (user preference)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(_px(6), _px(4), _px(6), _px(6))
        outer.setSpacing(0)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(_px(4))

        self._collapse_btn = QtWidgets.QPushButton("▾")
        self._collapse_btn.setObjectName("flatBtn")
        self._collapse_btn.setFixedSize(_px(16), _px(16))
        self._collapse_btn.clicked.connect(self._on_collapse)
        header.addWidget(self._collapse_btn)

        icon_lbl = QtWidgets.QLabel(_CAT_ICONS.get(category, "·"))
        icon_lbl.setStyleSheet("color: #a0a0a0; font-size: %dpx;" % _FONT_PX)
        icon_lbl.setFixedWidth(_px(16))
        header.addWidget(icon_lbl)

        title = QtWidgets.QLabel(category.title())
        title.setStyleSheet(
            "color: #c8c8c8; font-size: %dpx; font-weight: bold;" % _FONT_PX)
        header.addWidget(title)
        header.addStretch()

        self._fix_btn = QtWidgets.QPushButton("Fix")
        self._fix_btn.setFixedHeight(_BTN_H_SM)
        self._fix_btn.setToolTip("Auto-fix every fixable issue in this category")
        self._fix_btn.setVisible(False)
        self._fix_btn.clicked.connect(self._on_fix_category)
        header.addWidget(self._fix_btn)

        self._cat_toggle = QtWidgets.QCheckBox()
        self._cat_toggle.setToolTip("Toggle all checks in this category")
        self._cat_toggle.stateChanged.connect(self._on_cat_toggle)
        header.addWidget(self._cat_toggle)
        outer.addLayout(header)

        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #2a2a2a;")
        outer.addWidget(sep)

        self._content = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self._content)
        grid.setContentsMargins(_px(14), 0, _px(2), _px(2))
        grid.setHorizontalSpacing(_px(4))
        grid.setVerticalSpacing(0)
        self._rows: Dict[str, _CheckGridRow] = {}
        self._naming_base = 0
        if category == "NAMING":
            grid.addWidget(self._build_naming_fields(self._content), 0, 0, 1, 2)
            grid.addWidget(self._build_check_naming_btn(self._content), 1, 0, 1, 2)
            self._naming_base = 2
        elif category == "UV":
            grid.addWidget(self._build_uv_names_block(self._content), 0, 0, 1, 2)
            self._naming_base = 1
        base_row = self._naming_base
        for i, key in enumerate(keys):
            row = _CheckGridRow(key, self._content)
            grid.addWidget(row, base_row + i // 2, i % 2)
            self._rows[key] = row
        outer.addWidget(self._content)
        self._content.setVisible(False)   # collapsed by default (user pref)

    def _build_naming_fields(self, parent) -> QtWidgets.QWidget:
        """Blender-style naming policy block: Objects / Groups columns."""
        w = QtWidgets.QWidget(parent)
        grid = QtWidgets.QGridLayout(w)
        grid.setContentsMargins(_px(2), _px(2), _px(2), _px(2))
        grid.setHorizontalSpacing(_px(8))
        grid.setVerticalSpacing(_px(2))
        small = "font-size: %dpx; color: #909090;" % max(1, _FONT_PX - 1)
        self._naming_edits = {}
        for col, (title, get_p, get_s, set_p, set_s) in enumerate((
                ("Objects:", "get_prefix", "get_suffix", "set_prefix", "set_suffix"),
                ("Groups:", "get_col_prefix", "get_col_suffix", "set_col_prefix", "set_col_suffix"))):
            cap = QtWidgets.QLabel(title)
            cap.setStyleSheet("color: #c8c8c8; font-weight: bold;")
            grid.addWidget(cap, 0, col * 2, 1, 2)
            # prefix row
            lbl_p = QtWidgets.QLabel("Prefix:")
            lbl_p.setStyleSheet(small)
            grid.addWidget(lbl_p, 1, col * 2)
            e_p = QtWidgets.QLineEdit()
            e_p.setPlaceholderText("_")
            e_p.setFixedHeight(_BTN_H_SM)
            e_p.setToolTip("Required %s name prefix (scene-wide)" % title[:-1].lower())
            e_p.setProperty("naming_getter", get_p)
            e_p.setProperty("naming_setter", set_p)
            e_p.editingFinished.connect(self._on_naming_edited)
            grid.addWidget(e_p, 1, col * 2 + 1)
            self._naming_edits[get_p] = e_p
            # suffix row
            lbl_s = QtWidgets.QLabel("Suffix:")
            lbl_s.setStyleSheet(small)
            grid.addWidget(lbl_s, 2, col * 2)
            e_s = QtWidgets.QLineEdit()
            e_s.setPlaceholderText("_")
            e_s.setFixedHeight(_BTN_H_SM)
            e_s.setToolTip("Required %s name suffix (scene-wide)" % title[:-1].lower())
            e_s.setProperty("naming_getter", get_s)
            e_s.setProperty("naming_setter", set_s)
            e_s.editingFinished.connect(self._on_naming_edited)
            grid.addWidget(e_s, 2, col * 2 + 1)
            self._naming_edits[get_s] = e_s
        return w

    def _build_uv_names_block(self, parent) -> QtWidgets.QWidget:
        """UV set naming: summary + canonical rename (Blender UV Map Names)."""
        w = QtWidgets.QWidget(parent)
        outer = QtWidgets.QVBoxLayout(w)
        outer.setContentsMargins(_px(2), _px(2), _px(2), _px(2))
        outer.setSpacing(_px(3))
        self._uv_names_summary = QtWidgets.QLabel("UV Sets:")
        self._uv_names_summary.setStyleSheet(
            "color: #909090; font-size: %dpx;" % max(1, _FONT_PX - 1))
        outer.addWidget(self._uv_names_summary)
        lay = QtWidgets.QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(_px(3))
        outer.addLayout(lay)
        # QPushButton + menu: an editable QComboBox rendered dark-on-dark
        # artifacts at some DPI scales, so a plain button opens a menu
        self._uv_rename_target = QtWidgets.QPushButton("map1")
        self._uv_rename_target.setFixedHeight(_BTN_H)
        # fonts need more height than logical metrics — 22px clipped the text
        self._uv_rename_target.setMinimumWidth(_px(70))
        self._uv_rename_target.setMaximumWidth(_px(110))
        self._uv_rename_target.setToolTip(
            "Pick or type the canonical UV set name")
        # explicit style: a menu-bearing button can fall back to the native
        # (white) style on scaled monitors where the global QSS misses it
        self._uv_rename_target.setStyleSheet(
            "QPushButton { background: #303030; color: #e6e6e6;"
            " border: 1px solid #3a3a3a; border-radius: 3px;"
            " padding: %dpx %dpx; font-size: %dpx; }"
            "QPushButton:hover { background: #3d3d3d; }"
            "QPushButton::menu-indicator { subcontrol-position: right center;"
            " right: 4px; }" % (_px(3), _px(6), _FONT_PX))
        # no setMenu(): a menu-bearing QPushButton can fall back to the
        # native white style on some setups — we open the menu manually
        self._uv_rename_target.clicked.connect(self._on_uv_target_menu)
        self._uv_rename_target.setToolTip(
            "Canonical UV set name (map1 = Maya, uv = Houdini, UVMap = Blender)")
        lay.addWidget(self._uv_rename_target)
        self._uv_all_scene = QtWidgets.QCheckBox("All Scene")
        self._uv_all_scene.setToolTip(
            "Rename on ALL scene meshes, not only validated ones")
        lay.addWidget(self._uv_all_scene)
        btn = QtWidgets.QPushButton("Rename")
        btn.setFixedHeight(_BTN_H_SM)
        btn.setToolTip("Rename UV sets to the target name")
        btn.clicked.connect(self._on_uv_rename)
        self._uv_rename_btn = btn   # visibility driven by Coordinator Lock
        lay.addWidget(btn)
        return w

    def _on_uv_target_menu(self) -> None:
        menu = QtWidgets.QMenu(self._uv_rename_target)
        for name in ("map1", "uv", "UVMap"):
            menu.addAction(name, lambda n=name:
                           self._uv_rename_target.setText(n))
        menu.addSeparator()
        menu.addAction("Custom...", self._on_uv_custom_name)
        menu.exec_(self._uv_rename_target.mapToGlobal(
            self._uv_rename_target.rect().bottomLeft()))

    def _on_uv_custom_name(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Custom UV Set Name", "Name:")
        if ok and name.strip():
            self._uv_rename_target.setText(name.strip())

    @undo_decorator
    def _on_uv_rename(self) -> None:
        mc = _manager.MayaCheck
        target = self._uv_rename_target.text().strip()
        if not target:
            return
        if self._uv_all_scene.isChecked():
            shapes = cmds.ls(type="mesh", long=True) or []
            transforms = [sh.rsplit("|", 1)[0] for sh in shapes]
        else:
            transforms = list(mc.objects.keys())
        renamed = deleted = skipped = 0
        for t in transforms:
            if not cmds.objExists(t):
                continue
            try:
                shapes = cmds.listRelatives(t, shapes=True, type="mesh",
                                            fullPath=True) or []
                if not shapes:
                    continue
                shape = shapes[0]
                sets = cmds.polyUVSet(t, query=True, allUVSets=True) or []
                if not sets:
                    continue
                # keep exactly one canonical set: rename the active one to
                # the target, delete the extras (target may already exist)
                active = (cmds.polyUVSet(t, query=True, currentUVSet=True)
                          or [sets[0]])[0]
                for old in sets:
                    if old == target:
                        continue
                    try:
                        cmds.polyUVSet(shape, delete=True, uvSet=old)
                        deleted += 1
                    except Exception:
                        skipped += 1
                if target not in sets and active != target:
                    try:
                        cmds.polyUVSet(shape, rename=True, newUVSet=target,
                                       uvSet=active)
                        renamed += 1
                    except Exception:
                        skipped += 1
            except Exception:
                skipped += 1
        _manager.alog("uv rename -> '%s': %d renamed, %d deleted, %d skipped"
                      % (target, renamed, deleted, skipped))
        cmds.inViewMessage(
            amg="STUKACH: UV sets -> '%s' (%d renamed, %d extra deleted)"
                % (target, renamed, deleted), pos="topCenter", fade=True)
        mc.run_all()

    def _refresh_uv_names_summary(self) -> None:
        mc = _manager.MayaCheck
        from collections import Counter
        names = Counter()
        for t in mc.objects:
            try:
                for us in (cmds.polyUVSet(t, query=True, allUVSets=True) or []):
                    names[us] += 1
            except Exception:
                pass
        if not names:
            self._uv_names_summary.setText("UV Sets: -")
            return
        self._uv_names_summary.setText(
            "UV Sets: " + " · ".join("%s x%d" % (n, c)
                                     for n, c in names.most_common(4)))

    def _build_check_naming_btn(self, parent) -> QtWidgets.QWidget:
        b = QtWidgets.QPushButton("Check Naming")
        b.setObjectName("catBoxChild")
        b.setFixedHeight(_BTN_H)
        b.setToolTip("Re-run the naming checks on all objects")
        b.clicked.connect(lambda: _manager.MayaCheck.run_all())
        return b

    def _on_naming_edited(self) -> None:
        policy = _core.NamingPolicy
        edit = self.sender()
        getter = edit.property("naming_getter")
        setter = edit.property("naming_setter")
        getattr(policy, setter)(edit.text().strip())
        _manager.alog("naming policy %s -> '%s'"
                      % (getter, getattr(policy, getter)()))
        _manager.MayaCheck.run_all()

    def _on_collapse(self) -> None:
        self._open = not self._open
        self._content.setVisible(self._open)
        self._collapse_btn.setText("▾" if self._open else "▸")

    def set_open(self, open_: bool) -> None:
        if self._open != open_:
            self._on_collapse()

    def _on_cat_toggle(self, state: int) -> None:
        enabled = (int(state) == 2)
        _manager.MayaCheck.enable_by_category(self._category, enabled)

    def refresh(self) -> None:
        any_on = any(_manager.MayaCheck._enabled_checks.get(k, False)
                     for k in self._keys)
        self._cat_toggle.blockSignals(True)
        self._cat_toggle.setChecked(any_on)
        self._cat_toggle.blockSignals(False)

        # UV set names summary
        if self._category == "UV":
            try:
                self._refresh_uv_names_summary()
            except Exception:
                pass

        # Inline naming fields — sync from NamingPolicy
        if self._category == "NAMING":
            policy = _core.NamingPolicy
            for getter, edit in self._naming_edits.items():
                val = getattr(policy, getter)()
                edit.blockSignals(True)
                if edit.text() != val:
                    edit.setText(val)
                edit.blockSignals(False)

        # Category Fix button — some fixable check has issues on some object
        cat_has_fix = any(
            k in _FIXABLE and _manager.MayaCheck._enabled_checks.get(k, False)
            and any(mco.checkers.get(k) and mco.checkers[k].count > 0
                    for mco in _manager.MayaCheck.objects.values())
            for k in self._keys)
        self._fix_btn.setVisible(cat_has_fix and not _coordinator_lock())

        coord = _manager.MayaCheck.coordinator_mode
        # Hide INFO rows in coordinator mode (Blender hides INFO entirely)
        info_keys = set()
        if coord:
            for k in self._keys:
                if _core.CHECK_SEVERITIES.get(k) == "INFO":
                    info_keys.add(k)
        # Re-flow grid so hiding INFO rows doesn't leave empty cells
        visible = [k for k in self._keys if k not in info_keys]
        base_row = self._naming_base
        for i, key in enumerate(visible):
            row = self._rows[key]
            grid = self._content.layout()
            grid.removeWidget(row)
            r = base_row + i // 2
            c = i % 2
            grid.addWidget(row, r, c)
            row.setVisible(True)
            row.refresh()
        for key in info_keys:
            self._rows[key].setVisible(False)
        if not visible:
            self._content.setVisible(False)
        elif self._open:
            self._content.setVisible(True)

    @undo_decorator
    def _on_fix_category(self) -> None:
        total = 0
        for transform in list(_manager.MayaCheck.objects.keys()):
            for k in self._keys:
                if (k in _FIXABLE
                        and _manager.MayaCheck._enabled_checks.get(k, False)):
                    total += _manager.MayaCheck.fix_issues(k, transform)
        if total:
            _manager.MayaCheck.run_all()


# ── Per-object detail row: [!] Label: count  [Sel][Ign][Fix] ──────────────────

class _DetailCheckRow(QtWidgets.QWidget):
    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self.setFixedHeight(_BTN_H)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(_px(10), 0, _px(2), 0)
        layout.setSpacing(_px(3))

        self._icon = QtWidgets.QLabel("✓")
        self._icon.setFixedWidth(_px(16))
        layout.addWidget(self._icon)

        self._label = QtWidgets.QLabel("")
        self._label.setWordWrap(False)
        layout.addWidget(self._label, stretch=1)

        small = ("QPushButton { font-size: %dpx; padding: %dpx %dpx; }"
                 % (max(1, _FONT_PX - 2), 0, _px(5)))

        def _mini(text, tooltip):
            b = QtWidgets.QPushButton(text)
            b.setFixedHeight(_BTN_H_XS)
            b.setStyleSheet(small)
            b.setToolTip(tooltip)
            layout.addWidget(b)
            return b

        self._sel_btn = _mini("Sel", "Select bad components")
        self._sel_btn.clicked.connect(self._on_select)
        self._ign_btn = _mini("Ign", "Ignore this issue (excluded from status)")
        self._ign_btn.clicked.connect(self._on_ignore)
        self._fix_btn = _mini("Fix", "Auto-fix this issue")
        self._fix_btn.clicked.connect(self._on_fix)

    def refresh(self, mco: "_manager.MayaCheckObject") -> bool:
        """Show only hot rows (issues + ignored). Returns True if visible."""
        checker = mco.checkers.get(self._key)
        enabled = mco.enabled.get(self._key, False)
        if not enabled or checker is None:
            self.setVisible(False)
            return False

        transform = self._find_transform()
        ignored = bool(
            transform and self._key in _manager.get_ignore_list(transform))
        count = checker.count
        if count == 0 and not ignored:
            self.setVisible(False)
            return False
        self.setVisible(True)

        mt = getattr(checker, "metric_text", "") or ""
        note = getattr(checker, "note_text", "") or ""
        if getattr(checker, "oversize", False):
            text = "%s: %d — %d sampled, Sel off" % (
                _CHECK_DISPLAY_NAMES.get(self._key, self._key), count,
                len(checker.bad_components))
        elif note:
            text = "%s: %d — %s" % (
                _CHECK_DISPLAY_NAMES.get(self._key, self._key), count, note)
        else:
            text = mt if mt else "%s: %d" % (
                _CHECK_DISPLAY_NAMES.get(self._key, self._key), count)
        self.setToolTip(text)

        if ignored:
            self._icon.setText("◫")
            self._icon.setStyleSheet("color: #606060; font-weight: bold;")
            self._label.setText(text)
            self._label.setStyleSheet(
                "color: #606060; font-size: %dpx;" % max(1, _FONT_PX - 1))
            self._sel_btn.setVisible(False)
            self._fix_btn.setVisible(False)
            self._ign_btn.setText("Un-Ign")
            self._ign_btn.setToolTip("Stop ignoring this issue")
            return True

        self._ign_btn.setText("Ign")
        self._ign_btn.setToolTip("Ignore this issue (excluded from status)")
        color = _status_color(count, self._key)
        self._icon.setText("!!" if color == _C_RED else "!")
        self._icon.setStyleSheet("color: %s; font-weight: bold;" % color)
        self._label.setText(text)
        self._label.setStyleSheet("color: #d5d5d5; font-size: %dpx;"
                                  % max(1, _FONT_PX - 1))
        self._sel_btn.setVisible(
            bool(checker.bad_components)
            and not getattr(checker, "oversize", False))
        self._fix_btn.setVisible(self._key in _FIXABLE
                                 and not _coordinator_lock())
        return True

    def _on_select(self) -> None:
        mco = self._find_mco()
        if mco:
            checker = mco.checkers.get(self._key)
            if checker and checker.bad_components:
                checker.select()
                _manager.MayaCheck.note_stukach_selection(
                    checker.bad_components)
                try:
                    # focus: frame the bad components (Blender's view_selected)
                    cmds.viewFit(checker.bad_components)
                except Exception:
                    try:
                        cmds.viewFit(mco.transform)
                    except Exception:
                        pass

    def _on_ignore(self) -> None:
        transform = self._find_transform()
        if transform:
            _manager.MayaCheck.toggle_ignore(transform, self._key)

    @undo_decorator
    def _on_fix(self) -> None:
        transform = self._find_transform()
        if transform:
            n = _manager.MayaCheck.fix_issues(self._key, transform)
            if n:
                _manager.MayaCheck.run_all()

    def _find_transform(self):
        w = self
        while w:
            if isinstance(w, _ObjectRow):
                return w._transform
            w = w.parent()
        return None

    def _find_mco(self):
        t = self._find_transform()
        return _manager.MayaCheck.objects.get(t) if t else None


# ── Object row: [v] name  [dot] status → expandable details ───────────────────

def _obj_stats(transform: str):
    try:
        # single query on the TRANSFORM: triCount is invalid on the shape node
        res = cmds.polyEvaluate(transform, vertex=True, edge=True,
                                face=True, triangle=True) or {}
        return (int(res.get("vertex", 0)), int(res.get("edge", 0)),
                int(res.get("face", 0)), int(res.get("triangle", 0)))
    except Exception:
        return (0, 0, 0, 0)


class _ObjectRow(QtWidgets.QWidget):
    def __init__(self, transform: str, keys: tuple, parent=None):
        super().__init__(parent)
        self._transform = transform
        self._keys = keys
        self._open = False
        self._status = "clean"

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(_px(4))
        self._expand_btn = QtWidgets.QPushButton("▸")
        self._expand_btn.setObjectName("flatBtn")
        self._expand_btn.setFixedSize(_px(16), _px(16))
        self._expand_btn.clicked.connect(self._on_expand)
        header.addWidget(self._expand_btn)

        self._name_label = QtWidgets.QLabel(transform.split("|")[-1])
        self._name_label.setStyleSheet("font-size: %dpx;" % _FONT_PX)
        header.addWidget(self._name_label, stretch=1)

        self._ign_badge = QtWidgets.QLabel("")
        self._ign_badge.setStyleSheet(
            "color: #606060; font-size: %dpx;" % max(1, _FONT_PX - 2))
        header.addWidget(self._ign_badge)
        self._badge = _StatusDot(self, size=9)
        header.addWidget(self._badge)
        outer.addLayout(header)

        self._detail = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(0, _px(1), 0, _px(2))
        detail_layout.setSpacing(0)
        self._stats_label = QtWidgets.QLabel("")
        self._stats_label.setStyleSheet(
            "color: #a0a0a0; font-size: %dpx;" % max(1, _FONT_PX - 1))
        detail_layout.addWidget(self._stats_label)
        self._detail_rows: Dict[str, _DetailCheckRow] = {}
        for key in keys:
            row = _DetailCheckRow(key, self._detail)
            row.setVisible(False)
            detail_layout.addWidget(row)
            self._detail_rows[key] = row
        # Clean checks collapse into one grey line (Blender parity)
        self._clean_label = QtWidgets.QLabel("")
        self._clean_label.setStyleSheet(
            "color: #6a6a6a; font-size: %dpx;" % max(1, _FONT_PX - 1))
        detail_layout.addWidget(self._clean_label)
        self._detail.setVisible(False)
        outer.addWidget(self._detail)

    def _on_expand(self) -> None:
        self._open = not self._open
        self._detail.setVisible(self._open)
        self._expand_btn.setText("▾" if self._open else "▸")
        mco = _manager.MayaCheck.objects.get(self._transform)
        if self._open and mco:
            self.refresh(mco)   # detail rows only render while open

    def set_open(self, open_: bool) -> None:
        if self._open != open_:
            self._on_expand()

    def is_open(self) -> bool:
        return self._open

    def refresh(self, mco: "_manager.MayaCheckObject") -> None:
        # Status badge: critical / warning / clean (ignored checks excluded)
        ignored = _manager.get_ignore_list(self._transform)
        has_blocker = has_warning = False
        for key, checker in mco.checkers.items():
            if not mco.enabled.get(key) or checker is None or checker.count == 0:
                continue
            if key in ignored:
                continue
            sev = _core.CHECK_SEVERITIES.get(key)
            if sev == "BLOCKER":
                has_blocker = True
            elif sev == "WARNING":
                has_warning = True
        if has_blocker:
            self._status = "critical"
            self._badge.set_color(_C_RED)
        elif has_warning:
            self._status = "warning"
            self._badge.set_color(_C_YELLOW)
        else:
            self._status = "clean"
            self._badge.set_color(_C_GREEN)

        n_ign = len(ignored)
        self._ign_badge.setText("◫ %d" % n_ign if n_ign else "")

        if self._open:
            v, e, f, t = _obj_stats(self._transform)
            self._stats_label.setText(f"V: {v}  E: {e}  F: {f}  T: {t}")
            n_clean = 0
            for row in self._detail_rows.values():
                shown = row.refresh(mco)
                if not shown:
                    key = row._key
                    if mco.enabled.get(key) and key not in ignored:
                        n_clean += 1
            self._clean_label.setText(
                "%d checks clean" % n_clean if n_clean else "")
            self._clean_label.setVisible(bool(n_clean))


# ── Ignored Issues block (Blender parity) ─────────────────────────────────────

class _IgnoredBox(QtWidgets.QWidget):
    """Collapsible list of per-object ignores with clear buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._open = False

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(_px(4))
        self._collapse_btn = QtWidgets.QPushButton("▸")
        self._collapse_btn.setObjectName("flatBtn")
        self._collapse_btn.setFixedSize(_px(16), _px(16))
        self._collapse_btn.setStyleSheet(
            "QPushButton { color: #8c8c8c; border: none; font-size: %dpx; padding: 0; }"
            "QPushButton:hover { color: #e6e6e6; }" % _FONT_PX)
        self._collapse_btn.clicked.connect(self._on_collapse)
        header.addWidget(self._collapse_btn)
        self._title = QtWidgets.QLabel("Ignored Issues (0)")
        self._title.setStyleSheet(
            "color: #c8c8c8; font-size: %dpx; font-weight: bold;" % _FONT_PX)
        header.addWidget(self._title)
        header.addStretch()
        clear_btn = QtWidgets.QPushButton("Clear All")
        clear_btn.setFixedHeight(_BTN_H_SM)
        clear_btn.setStyleSheet(
            "QPushButton { font-size: %dpx; padding: %dpx %dpx; }"
            % (max(1, _FONT_PX - 2), 0, _px(5)))
        clear_btn.clicked.connect(
            lambda: _manager.MayaCheck.clear_all_ignores())
        header.addWidget(clear_btn)
        outer.addLayout(header)

        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #2a2a2a;")
        outer.addWidget(sep)

        self._content = QtWidgets.QWidget()
        self._rows_layout = QtWidgets.QVBoxLayout(self._content)
        self._rows_layout.setContentsMargins(_px(8), _px(2), 0, _px(2))
        self._rows_layout.setSpacing(_px(2))
        self._content.setVisible(False)
        outer.addWidget(self._content)

    def _on_collapse(self) -> None:
        self._open = not self._open
        self._content.setVisible(self._open)
        self._collapse_btn.setText("▾" if self._open else "▸")

    def refresh(self) -> None:
        # Clear old rows
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        mc = _manager.MayaCheck
        entries = []
        for transform in sorted(mc.objects.keys()):
            ignored = _manager.get_ignore_list(transform)
            if ignored:
                entries.append((transform, sorted(ignored)))
        total = sum(len(ig) for _, ig in entries)
        self._title.setText("Ignored Issues (%d)" % total)
        self.setVisible(total > 0)

        for transform, ignored in entries:
            row = QtWidgets.QWidget()
            lay = QtWidgets.QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(_px(4))
            name = QtWidgets.QLabel(transform.split("|")[-1] + ":")
            name.setStyleSheet(
                "color: #c8c8c8; font-size: %dpx;" % max(1, _FONT_PX - 1))
            lay.addWidget(name)
            chips = " · ".join(
                _CHECK_DISPLAY_NAMES.get(k, k) for k in ignored)
            chip_lbl = QtWidgets.QLabel(chips)
            chip_lbl.setStyleSheet(
                "color: #606060; font-size: %dpx;" % max(1, _FONT_PX - 1))
            lay.addWidget(chip_lbl, stretch=1)
            clr = QtWidgets.QPushButton("X")
            clr.setFixedSize(_px(22), _px(18))
            clr.setStyleSheet(
                "QPushButton { font-size: %dpx; padding: 0; }"
                % max(1, _FONT_PX - 3))
            clr.setToolTip("Clear ignores for this object")
            clr.clicked.connect(lambda _=False, t=transform:
                                _manager.MayaCheck.clear_ignore_object(t))
            lay.addWidget(clr)
            self._rows_layout.addWidget(row)


# ── Main panel ────────────────────────────────────────────────────────────────

WINDOW_NAME = "StukachPanel"
_WC = "StukachWorkspaceControl"
_WORKSPACE_CONTROL = "StukachPanelWorkspaceControl"
_DOCK_CONTROL = "StukachPanelDockControl"
_HOST_FORM = "stukachHostForm"


class StukachPanel(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(WINDOW_NAME)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("STUKACH")
        self.setMinimumWidth(dpi_scale(378))
        self.setMinimumHeight(dpi_scale(640))
        self.setStyleSheet(_QSS)

        self._obj_rows: Dict[str, _ObjectRow] = {}
        self._filter_text = ""
        self._issues_only = True   # issues-only by default (user request)

        self._build_ui()
        # Fill the window vertically — without this the panel reports a small
        # sizeHint and reopens at ~1/3 of the saved height
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Expanding)
        _manager.MayaCheck._ui_callback = self.refresh
        self._height_anim = None
        self.refresh()   # initial sync: mode/stack/lock from live manager state

        # Live-mode tick (panel-owned so hot-reload kills it with the panel)
        # one timer drives BOTH progressive validation (150ms) and Live (1s)
        self._live_timer = QtCore.QTimer(self)
        self._live_timer.setInterval(150)
        self._tick_count = 0
        self._live_timer.timeout.connect(self._on_tick)
        self._live_timer.start()

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        # Right margin reserve: on scaled monitors Qt's logical layout is
        # narrower than the rendered text, which clipped everything anchored
        # to the right edge (Viewport, category checkboxes, +/-, Debug Info)
        root.setContentsMargins(_px(6), _px(6), _px(22), _px(6))
        root.setSpacing(_px(4))

        # ── header: title + subtitle ──
        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(0)
        title = QtWidgets.QLabel("STUKACH v%s" % _VERSION)
        title.setStyleSheet("color: #e5e5e5; font-size: %dpx; font-weight: bold;"
                            % _px(15))
        title_box.addWidget(title)
        subtitle = QtWidgets.QLabel("Pipeline Snitch System")
        subtitle.setStyleSheet("color: #909090; font-size: %dpx;" % _px(10))
        title_box.addWidget(subtitle)
        root.addLayout(title_box)

        # ── RUN toggle (full width, blue) ──
        self._run_btn = QtWidgets.QPushButton("RUN STUKACH")
        self._run_btn.setCheckable(True)
        self._run_btn.setFixedHeight(_px(34))
        self._run_btn.clicked.connect(self._on_run)
        self._run_btn.setStyleSheet(
            "QPushButton { background: %s; color: #fff; font-weight: bold; }"
            "QPushButton:hover { background: #5683c8; }" % _C_SELECT)
        root.addWidget(self._run_btn)

        # mode toolbar above the stack — visible on BOTH pages
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(_px(2))
        self._mode_coord_btn = QtWidgets.QPushButton("Coordinator Mode")
        self._mode_coord_btn.setCheckable(True)
        self._mode_coord_btn.setFixedHeight(_BTN_H)
        self._mode_coord_btn.setToolTip(
            "Coordinator mode: hide INFO checks, gate view + Copy Report. "
            "Click again to return to Artist Mode.")
        self._mode_coord_btn.clicked.connect(self._on_coordinator_toggled)
        mode_row.addWidget(self._mode_coord_btn, stretch=1)
        self._mode_live_btn = QtWidgets.QPushButton("Live")
        self._mode_live_btn.setCheckable(True)
        self._mode_live_btn.setFixedHeight(_BTN_H)
        self._mode_live_btn.setToolTip(
            "Live mode: revalidate dirty objects every second")
        self._mode_live_btn.clicked.connect(self._on_live_toggled)
        mode_row.addWidget(self._mode_live_btn, stretch=1)
        self._opts_btn = QtWidgets.QPushButton("...")
        self._opts_btn.setFixedHeight(_BTN_H)
        self._opts_btn.setMaximumWidth(_px(36))
        self._opts_btn.setToolTip(
            "Workstation options: start mode, Coordinator Lock")
        self._opts_btn.clicked.connect(self._on_options_menu)
        mode_row.addWidget(self._opts_btn, stretch=0)
        root.addLayout(mode_row)

        self._stack = QtWidgets.QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        artist_page = QtWidgets.QWidget()
        artist_layout = QtWidgets.QVBoxLayout(artist_page)
        artist_layout.setContentsMargins(0, 0, 0, 0)
        artist_layout.setSpacing(_px(4))
        self._stack.addWidget(artist_page)

        coord_page = QtWidgets.QWidget()
        self._coord_layout = QtWidgets.QVBoxLayout(coord_page)
        self._coord_layout.setContentsMargins(0, 0, 0, 0)
        self._coord_layout.setSpacing(_px(4))
        self._stack.addWidget(coord_page)

        self._build_artist_page(artist_layout)
        self._build_coordinator_page(self._coord_layout)
        self._build_delivery_box(root)   # shared by both pages

    def _build_artist_page(self, root: QtWidgets.QVBoxLayout) -> None:
        # ── isolate badge ── (Shift+click on a check)
        self._isolate_badge = QtWidgets.QLabel("")
        self._isolate_badge.setStyleSheet(
            "background: #4772b3; color: white; font-size: %dpx;"
            " font-weight: bold; padding: 1px %dpx; border-radius: %dpx;"
            % (_px(10), _px(6), _px(3)))
        self._isolate_badge.setVisible(False)
        root.addWidget(self._isolate_badge)

        # checkpoint restored hint (hidden until a checkpoint is loaded)
        self._hint_label = QtWidgets.QLabel("")
        self._hint_label.setStyleSheet(
            "color: #b0a060; font-size: %dpx; font-style: italic;"
            % max(1, _FONT_PX - 1))
        self._hint_label.setVisible(False)
        root.addWidget(self._hint_label)

        # ── score block ──
        self._score_widget = QtWidgets.QWidget()
        score_layout = QtWidgets.QVBoxLayout(self._score_widget)
        score_layout.setContentsMargins(_px(2), _px(2), _px(2), _px(2))
        score_layout.setSpacing(_px(2))

        line1 = QtWidgets.QHBoxLayout()
        line1.setSpacing(_px(5))
        self._score_icon = _StatusDot(self._score_widget)
        line1.addWidget(self._score_icon)
        self._score_text = QtWidgets.QLabel("Awaiting suspects.")
        self._score_text.setStyleSheet(
            "color: #a0a0a0; font-size: %dpx; font-style: italic;" % _FONT_PX)
        line1.addWidget(self._score_text)
        line1.addStretch()
        self._score_scope = QtWidgets.QLabel("")
        self._score_scope.setStyleSheet(
            "color: #909090; font-size: %dpx;" % max(1, _FONT_PX - 2))
        line1.addWidget(self._score_scope)
        self._progress_label = QtWidgets.QLabel("")
        self._progress_label.setStyleSheet(
            "color: #4772b3; font-size: %dpx; font-style: italic;"
            % max(1, _FONT_PX - 1))
        self._progress_label.setFixedHeight(_px(13))
        # space is ALWAYS reserved: showing/hiding the label made the
        # panel jitter on every short live-validation pass
        self._progress_label.setText("")
        score_layout.addWidget(self._progress_label)

        score_layout.addLayout(line1)

        self._health_strip = _HealthStrip(self._score_widget)
        score_layout.addWidget(self._health_strip)

        actions_row = QtWidgets.QHBoxLayout()
        actions_row.setSpacing(_px(3))
        self._next_issue_btn = QtWidgets.QPushButton("Next Issue")
        self._next_issue_btn.setFixedHeight(_BTN_H)
        self._next_issue_btn.setToolTip(
            "Jump to the next problem object (worst-first cycle)")
        self._next_issue_btn.clicked.connect(self._on_next_issue)
        actions_row.addWidget(self._next_issue_btn, stretch=1)
        self._copy_btn = QtWidgets.QPushButton("Copy Summary")
        self._copy_btn.setFixedHeight(_BTN_H)
        self._copy_btn.setToolTip("Copy validation summary to clipboard")
        self._copy_btn.clicked.connect(self._on_copy_summary)
        actions_row.addWidget(self._copy_btn, stretch=1)
        score_layout.addLayout(actions_row)
        root.addWidget(self._score_widget)

        # ── scope row: Scene | Selected | x ──
        scope_row = QtWidgets.QHBoxLayout()
        scope_row.setSpacing(_px(2))
        self._scope_group = QtWidgets.QButtonGroup(self)
        self._scope_group.setExclusive(True)
        self._scope_scene_btn = QtWidgets.QPushButton("Scene")
        self._scope_selected_btn = QtWidgets.QPushButton("Selected")
        for btn in (self._scope_scene_btn, self._scope_selected_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(_BTN_H)
            self._scope_group.addButton(btn)
            scope_row.addWidget(btn, stretch=1)
        self._scope_scene_btn.setChecked(True)
        self._scope_scene_btn.clicked.connect(lambda: self._on_scope_changed("SCENE"))
        self._scope_selected_btn.clicked.connect(lambda: self._on_scope_changed("SELECTED"))
        self._clear_btn = QtWidgets.QPushButton("✕ Clear")
        self._clear_btn.setFixedHeight(_BTN_H)
        self._clear_btn.setToolTip("Stop validation and clear results")
        self._clear_btn.clicked.connect(self._on_stop)
        root.addLayout(scope_row)

        # ── compact batch row ──
        batch_row = QtWidgets.QHBoxLayout()
        batch_row.setSpacing(_px(2))
        small_qss = ("QPushButton { font-size: %dpx; padding: %dpx %dpx; }"
                     % (max(1, _FONT_PX - 2), _px(1), _px(5)))
        self._small_qss = small_qss

        def _small(text, tooltip, slot):
            b = QtWidgets.QPushButton(text)
            b.setFixedHeight(_BTN_H_SM)
            b.setStyleSheet(small_qss)
            b.setToolTip(tooltip)
            b.clicked.connect(slot)
            batch_row.addWidget(b)
            return b

        _small("All", "Enable every check", lambda: _manager.MayaCheck.enable_all(True))
        _small("None", "Disable every check", lambda: _manager.MayaCheck.enable_all(False))
        _small("Blk", "Only BLOCKER checks", lambda: _manager.MayaCheck.enable_by_severity({"BLOCKER"}))
        _small("Wrn", "BLOCKER + WARNING", lambda: _manager.MayaCheck.enable_by_severity({"BLOCKER", "WARNING"}))
        batch_row.addStretch()

        self._overlay_cb = QtWidgets.QCheckBox("Viewport")
        self._overlay_cb.setChecked(True)
        self._overlay_cb.setToolTip("Viewport overlay on/off")
        self._overlay_cb.stateChanged.connect(self._on_overlay_toggled)
        batch_row.addWidget(self._overlay_cb)
        root.addLayout(batch_row)

        # ── scene-level rows (Scene Units + Empty Groups) ──
        self._units_rows = []
        self._eg_rows = []
        self._eg_groups = []
        root.addWidget(self._build_units_row())

        # ── scroll: Pipeline Checks + Objects ──
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setMinimumHeight(dpi_scale(200))   # never collapse: object
        # details live here; a squeezed scroll made "nothing drop out"
        container = QtWidgets.QWidget()
        cont_layout = QtWidgets.QVBoxLayout(container)
        cont_layout.setContentsMargins(0, 0, 0, 0)
        cont_layout.setSpacing(_px(3))

        checks_lbl = QtWidgets.QLabel("Pipeline Checks:")
        checks_lbl.setStyleSheet(
            "color: #c8c8c8; font-size: %dpx; font-weight: bold;" % _FONT_PX)
        cont_layout.addWidget(checks_lbl)

        self._checks_layout = cont_layout
        self._category_boxes: Dict[str, _CategoryBox] = {}
        for cat, keys in _core.CHECK_CATEGORIES.items():
            box = _CategoryBox(cat, keys)
            cont_layout.addWidget(box)
            self._category_boxes[cat] = box

        # ── presets row (inside Pipeline Checks, Blender parity) ──
        presets_row = QtWidgets.QHBoxLayout()
        presets_row.setSpacing(_px(2))
        self._preset_combo = QtWidgets.QComboBox()
        self._preset_combo.setFixedHeight(_BTN_H_SM)
        self._preset_combo.setMinimumWidth(_px(44))
        # allow the combo to shrink below its text sizeHint: a wide minimum
        # made the row overflow the scroll viewport (right-edge clipping)
        self._preset_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._preset_combo.setMinimumContentsLength(3)
        self._preset_combo.setStyleSheet(
            "QComboBox { background: #303030; color: #e6e6e6;"
            " border: 1px solid #3a3a3a; border-radius: 3px;"
            " padding: %dpx %dpx; font-size: %dpx; }"
            "QComboBox::drop-down { border: none; width: %dpx; }"
            % (_px(2), _px(6), max(1, _FONT_PX - 1), _px(16)))
        self._preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        presets_row.addWidget(self._preset_combo, stretch=1)
        self._preset_save_btn = QtWidgets.QPushButton("+")
        self._preset_save_btn.setFixedSize(_px(22), _px(20))
        self._preset_save_btn.setStyleSheet(small_qss)
        self._preset_save_btn.setToolTip("Save preset")
        self._preset_save_btn.clicked.connect(self._on_preset_save)
        presets_row.addWidget(self._preset_save_btn)
        self._preset_del_btn = QtWidgets.QPushButton("\u2212")
        self._preset_del_btn.setFixedSize(_px(22), _px(20))
        self._preset_del_btn.setStyleSheet(small_qss)
        self._preset_del_btn.setToolTip("Delete selected preset")
        self._preset_del_btn.clicked.connect(self._on_preset_delete)
        presets_row.addWidget(self._preset_del_btn)
        self._presets_widget = QtWidgets.QWidget()
        self._presets_widget.setLayout(presets_row)
        cont_layout.addWidget(self._presets_widget)
        self._refresh_preset_combo()

        # ── Objects section (collapsible) ──
        self._build_objects_section(cont_layout)

        self._ignored_box = _IgnoredBox()
        self._ignored_box.setVisible(False)
        cont_layout.addWidget(self._ignored_box)
        cont_layout.addStretch()
        scroll.setWidget(container)
        self._scroll = scroll
        root.addWidget(scroll, stretch=1)

        # ── asset status box (artist page) ──
        self._verdict_widget = QtWidgets.QWidget()
        verdict_layout = QtWidgets.QVBoxLayout(self._verdict_widget)
        verdict_layout.setContentsMargins(_px(2), _px(4), _px(2), _px(4))
        verdict_layout.setSpacing(0)
        self._verdict_headline = QtWidgets.QLabel("No active checks.")
        self._verdict_headline.setAlignment(Qt.AlignCenter)
        self._verdict_headline.setStyleSheet(
            "color: #909090; font-size: %dpx; font-weight: bold;" % _FONT_PX)
        verdict_layout.addWidget(self._verdict_headline)
        self._verdict_subtext = QtWidgets.QLabel("")
        self._verdict_subtext.setAlignment(Qt.AlignCenter)
        self._verdict_subtext.setStyleSheet(
            "color: #909090; font-size: %dpx;" % max(1, _FONT_PX - 2))
        verdict_layout.addWidget(self._verdict_subtext)
        root.addWidget(self._verdict_widget)

    def _build_units_row(self) -> QtWidgets.QFrame:
        """Scene-level checks (Scene Units + Empty Groups), bordered box."""
        box = QtWidgets.QFrame()
        box.setObjectName("catBox")
        outer = QtWidgets.QVBoxLayout(box)
        outer.setContentsMargins(_px(6), _px(3), _px(6), _px(3))
        outer.setSpacing(_px(2))

        units_row = QtWidgets.QHBoxLayout()
        units_row.setSpacing(_px(4))
        toggle = QtWidgets.QCheckBox("Scene Units")
        toggle.setToolTip("Check scene units: METRIC · m · scale 1.0")
        toggle.stateChanged.connect(self._on_units_toggled)
        units_row.addWidget(toggle)
        units_row.addStretch()
        status = QtWidgets.QLabel("")
        status.setStyleSheet(
            "color: #909090; font-size: %dpx;" % max(1, _FONT_PX - 1))
        units_row.addWidget(status)
        self._units_rows.append((toggle, status))
        outer.addLayout(units_row)

        # Empty Groups — scene-level clutter scan (transforms with no children)
        eg_row = QtWidgets.QHBoxLayout()
        eg_row.setSpacing(_px(4))
        eg_toggle = QtWidgets.QCheckBox("Empty Groups")
        eg_toggle.setToolTip(
            "Scene-level check: transforms with no children (empty groups "
            "left after rebuilds/imports). Select and delete manually.")
        eg_toggle.stateChanged.connect(self._on_empty_groups_toggled)
        eg_row.addWidget(eg_toggle)
        eg_row.addStretch()
        eg_status = QtWidgets.QLabel("")
        eg_status.setStyleSheet(
            "color: #909090; font-size: %dpx;" % max(1, _FONT_PX - 1))
        eg_row.addWidget(eg_status)
        eg_sel = QtWidgets.QPushButton("Sel")
        eg_sel.setFixedHeight(_BTN_H_XS)
        eg_sel.setToolTip("Select the empty groups (deletion stays manual)")
        eg_sel.clicked.connect(self._on_empty_groups_sel)
        eg_row.addWidget(eg_sel)
        self._eg_rows.append((eg_toggle, eg_status))
        outer.addLayout(eg_row)

        return box

    def _build_objects_section(self, cont_layout: QtWidgets.QVBoxLayout) -> None:
        self._objects_box = QtWidgets.QFrame()
        self._objects_box.setObjectName("catBox")
        obj_outer = QtWidgets.QVBoxLayout(self._objects_box)
        obj_outer.setContentsMargins(_px(6), _px(4), _px(6), _px(6))
        obj_outer.setSpacing(_px(3))
        self._objects_open = False   # collapsed by default like the categories

        obj_header = QtWidgets.QHBoxLayout()
        obj_header.setSpacing(_px(4))
        self._objects_collapse = QtWidgets.QPushButton("▸")
        self._objects_collapse.setObjectName("flatBtn")
        self._objects_collapse.setFixedSize(_px(16), _px(16))
        self._objects_collapse.clicked.connect(self._on_objects_collapse)
        obj_header.addWidget(self._objects_collapse)
        obj_title = QtWidgets.QLabel("Objects")
        obj_title.setStyleSheet(
            "color: #c8c8c8; font-size: %dpx; font-weight: bold;" % _FONT_PX)
        obj_header.addWidget(obj_title)
        obj_header.addStretch()
        self._objects_count = QtWidgets.QLabel("0")
        self._objects_count.setStyleSheet("color: #909090; font-size: %dpx;"
                                          % _FONT_PX)
        obj_header.addWidget(self._objects_count)
        self._objects_issues = QtWidgets.QLabel("")
        self._objects_issues.setStyleSheet(
            "color: #ad4133; font-size: %dpx; font-weight: bold;" % _FONT_PX)
        obj_header.addWidget(self._objects_issues)
        obj_outer.addLayout(obj_header)

        obj_sep = QtWidgets.QFrame()
        obj_sep.setFixedHeight(1)
        obj_sep.setStyleSheet("background: #2a2a2a;")
        obj_outer.addWidget(obj_sep)

        self._objects_content = QtWidgets.QWidget()
        oc_layout = QtWidgets.QVBoxLayout(self._objects_content)
        oc_layout.setContentsMargins(_px(2), 0, _px(2), 0)
        oc_layout.setSpacing(_px(2))

        filt_row = QtWidgets.QHBoxLayout()
        filt_row.setSpacing(_px(3))
        self._filter_edit = QtWidgets.QLineEdit()
        self._filter_edit.setPlaceholderText("Search objects")
        self._filter_edit.setFixedHeight(_BTN_H)
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        filt_row.addWidget(self._filter_edit, stretch=1)
        self._issues_only_btn = QtWidgets.QPushButton("Issues")
        self._issues_only_btn.setCheckable(True)
        self._issues_only_btn.setChecked(True)   # issues-only by default
        self._issues_only_btn.setFixedHeight(_BTN_H)
        self._issues_only_btn.setToolTip(
            "ON: only objects with issues; OFF: all tracked objects")
        self._issues_only_btn.clicked.connect(self._on_issues_only)
        filt_row.addWidget(self._issues_only_btn)
        oc_layout.addLayout(filt_row)

        self._expand_all_btn = QtWidgets.QPushButton("Expand All")
        self._expand_all_btn.setFixedHeight(_BTN_H_SM)
        self._expand_all_btn.setStyleSheet(self._small_qss)
        self._expand_all_btn.clicked.connect(self._on_expand_all)
        oc_layout.addWidget(self._expand_all_btn)

        self._obj_list_container = QtWidgets.QWidget()
        self._obj_list_layout = QtWidgets.QVBoxLayout(self._obj_list_container)
        self._obj_list_layout.setContentsMargins(0, 0, 0, 0)
        self._obj_list_layout.setSpacing(_px(1))
        oc_layout.addWidget(self._obj_list_container)
        obj_outer.addWidget(self._objects_content)
        self._objects_content.setVisible(False)   # collapsed by default
        cont_layout.addWidget(self._objects_box)

    def _build_coordinator_page(self, root: QtWidgets.QVBoxLayout) -> None:
        title = QtWidgets.QLabel("Coordinator Mode")
        title.setStyleSheet(
            "color: #c8c8c8; font-size: %dpx; font-weight: bold;" % _px(14))
        root.addWidget(title)

        # ── status badge ──
        self._gate_widget = QtWidgets.QWidget()
        gate_layout = QtWidgets.QVBoxLayout(self._gate_widget)
        gate_layout.setContentsMargins(_px(4), _px(4), _px(4), _px(4))
        gate_layout.setSpacing(0)
        self._gate_headline = QtWidgets.QLabel("Run validation first")
        self._gate_headline.setAlignment(Qt.AlignCenter)
        self._gate_headline.setStyleSheet(
            "color: #909090; font-size: %dpx; font-weight: bold;" % _px(13))
        gate_layout.addWidget(self._gate_headline)
        self._gate_subtext = QtWidgets.QLabel("")
        self._gate_subtext.setAlignment(Qt.AlignCenter)
        self._gate_subtext.setStyleSheet(
            "color: #909090; font-size: %dpx;" % max(1, _FONT_PX - 2))
        gate_layout.addWidget(self._gate_subtext)
        root.addWidget(self._gate_widget)

        # ── units + scope rows (coordinator's own instances) ──
        root.addWidget(self._build_units_row())
        coord_scope_row = QtWidgets.QHBoxLayout()
        coord_scope_row.setSpacing(_px(2))
        self._coord_scope_scene_btn = QtWidgets.QPushButton("Scene")
        self._coord_scope_selected_btn = QtWidgets.QPushButton("Selected")
        for btn in (self._coord_scope_scene_btn, self._coord_scope_selected_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(_BTN_H)
            if btn is self._coord_scope_scene_btn:
                btn.clicked.connect(lambda: self._on_scope_changed("SCENE"))
            else:
                btn.clicked.connect(lambda: self._on_scope_changed("SELECTED"))
            coord_scope_row.addWidget(btn, stretch=1)
        self._coord_scope_clear_btn = QtWidgets.QPushButton("✕ Clear")
        self._coord_scope_clear_btn.setFixedHeight(_BTN_H)
        self._coord_scope_clear_btn.setToolTip("Stop validation and clear results")
        self._coord_scope_clear_btn.clicked.connect(self._on_stop)
        coord_scope_row.addWidget(self._coord_scope_clear_btn)
        self._coord_layout.addLayout(coord_scope_row)

        self._copy_report_btn = QtWidgets.QPushButton("Copy Report")
        self._copy_report_btn.setFixedHeight(_BTN_H)
        self._copy_report_btn.setToolTip(
            "Verdict report for the task: VALIDATION + BLOCKERS/WARNINGS")
        self._copy_report_btn.clicked.connect(self._on_copy_summary)
        root.addWidget(self._copy_report_btn)

        cw_lbl = QtWidgets.QLabel("Critical & Warning Checks:")
        cw_lbl.setStyleSheet(
            "color: #c8c8c8; font-size: %dpx; font-weight: bold;" % _FONT_PX)
        root.addWidget(cw_lbl)
        self._coord_checks_container = QtWidgets.QWidget()
        self._coord_checks_layout = QtWidgets.QVBoxLayout(self._coord_checks_container)
        self._coord_checks_layout.setContentsMargins(0, 0, 0, 0)
        self._coord_checks_layout.setSpacing(_px(3))
        root.addWidget(self._coord_checks_container)
        root.addStretch()

    def _build_delivery_box(self, root: QtWidgets.QVBoxLayout) -> None:
        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #2a2a2a;")
        root.addWidget(sep)

        export_box = QtWidgets.QWidget()
        exp_layout = QtWidgets.QVBoxLayout(export_box)
        exp_layout.setContentsMargins(_px(2), _px(4), _px(2), _px(2))
        exp_layout.setSpacing(_px(3))

        lbl_w = _px(70)   # 'Checkpoint:' is the longest label
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(_px(3))
        lbl1 = QtWidgets.QLabel("Export:")
        lbl1.setStyleSheet("color: #a0a0a0;")
        lbl1.setFixedWidth(lbl_w)
        row1.addWidget(lbl1)
        for fmt in ("JSON", "CSV", "HTML"):
            b = QtWidgets.QPushButton(fmt)
            b.setFixedHeight(_BTN_H)
            b.clicked.connect(lambda _=False, f=fmt.lower(): self._on_export(f))
            row1.addWidget(b, stretch=1)
        exp_layout.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(_px(3))
        lbl2 = QtWidgets.QLabel("Pre-flight:")
        lbl2.setStyleSheet("color: #a0a0a0;")
        lbl2.setFixedWidth(lbl_w)
        row2.addWidget(lbl2)
        for fmt in ("FBX", "USD"):
            b = QtWidgets.QPushButton(fmt)
            b.setFixedHeight(_px(22))
            b.setToolTip("Pre-flight gate, then %s export" % fmt)
            b.clicked.connect(lambda _=False, f=fmt.lower(): self._on_publish(f))
            row2.addWidget(b, stretch=1)
        exp_layout.addLayout(row2)

        row3 = QtWidgets.QHBoxLayout()
        row3.setSpacing(_px(3))
        lbl3 = QtWidgets.QLabel("Checkpoint:")
        lbl3.setStyleSheet("color: #a0a0a0;")
        lbl3.setFixedWidth(lbl_w)
        row3.addWidget(lbl3)
        b_save = QtWidgets.QPushButton("Save")
        b_save.setFixedHeight(_BTN_H)
        b_save.setToolTip(
            "Store the current validation snapshot in the scene file")
        b_save.clicked.connect(self._on_checkpoint_save)
        row3.addWidget(b_save, stretch=1)
        b_load = QtWidgets.QPushButton("Load")
        b_load.setFixedHeight(_BTN_H)
        b_load.setToolTip(
            "Restore the snapshot: checks + stale results (Run revalidates)")
        b_load.clicked.connect(self._on_checkpoint_load)
        row3.addWidget(b_load, stretch=1)
        b_clear = QtWidgets.QPushButton("\u2715")
        b_clear.setFixedHeight(_BTN_H)
        b_clear.setFixedWidth(_px(26))
        b_clear.setToolTip("Delete the checkpoint from the scene file")
        b_clear.clicked.connect(self._on_checkpoint_clear)
        row3.addWidget(b_clear)
        exp_layout.addLayout(row3)

        dbg_row = QtWidgets.QHBoxLayout()
        dbg_row.addStretch()
        self._debug_btn = QtWidgets.QPushButton("Debug Info")
        self._debug_btn.setFixedHeight(_BTN_H_XS)
        self._debug_btn.setStyleSheet(
            "QPushButton { color: #8c8c8c; font-size: %dpx; padding: 0 %dpx; "
            "border: none; background: transparent; }"
            "QPushButton:hover { color: #e6e6e6; }"
            % (max(1, _FONT_PX - 2), _px(5)))
        self._debug_btn.setToolTip(
            "Copy versions, state and session log to clipboard (bug reports)")
        self._debug_btn.clicked.connect(self._on_debug_info)
        dbg_row.addWidget(self._debug_btn)
        exp_layout.addLayout(dbg_row)
        root.addWidget(export_box)

    # ── smooth height animation (FLOMASTER parity) ────────────────────────────

    def _animate_to_height(self, target_h: int) -> None:
        """Animate the window height to target (anchored top-right, growing
        down), like FLOMASTER's AnimateToHeight: 250 ms, OutCubic."""
        try:
            screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
            target_h = int(max(self.minimumHeight(),
                               min(target_h, screen.bottom() - self.y() - 8)))
            geom = self.geometry()
            if abs(geom.height() - target_h) < 2:
                return
            anim = QtCore.QPropertyAnimation(self, b"geometry", self)
            anim.setDuration(250)
            anim.setStartValue(QtCore.QRect(
                geom.x(), geom.y(), geom.width(), geom.height()))
            anim.setEndValue(QtCore.QRect(
                geom.x(), geom.y(), geom.width(), target_h))
            anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
            self._height_anim = anim   # keep a ref: parent does not own it
            anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        except Exception:
            pass

    # ── slots ──

    def _on_run(self) -> None:
        if self._run_btn.isChecked():
            scope = "SCENE" if self._scope_scene_btn.isChecked() else "SELECTED"
            _manager.MayaCheck.scope = scope
            _manager.MayaCheck.set_overlay_enabled(self._overlay_cb.isChecked())
            _manager.MayaCheck.start(ui_callback=self.refresh)
            self._run_btn.setText("\u25cf STUKACH ACTIVE")
        else:
            self._on_stop()

    def _on_stop(self) -> None:
        _manager.MayaCheck.stop()
        self._run_btn.blockSignals(True)
        self._run_btn.setChecked(False)
        self._run_btn.blockSignals(False)
        self._run_btn.setText("RUN STUKACH")

    def _on_scope_changed(self, scope: str) -> None:
        _manager.MayaCheck.set_scope(scope)

    def _on_overlay_toggled(self, state: int) -> None:
        _manager.MayaCheck.set_overlay_enabled(int(state) == 2)

    def _on_coordinator_toggled(self) -> None:
        _manager.MayaCheck.set_coordinator_mode(self._mode_coord_btn.isChecked())

    def _on_options_menu(self) -> None:
        menu = QtWidgets.QMenu(self._opts_btn)
        a_start = menu.addAction("Start in Coordinator Mode")
        a_start.setCheckable(True)
        a_start.setChecked(bool(int(cmds.optionVar(
            query="stukachStartCoordinator") or 0)))
        a_lock = menu.addAction("Coordinator Lock (hide fixes)")
        a_lock.setCheckable(True)
        a_lock.setChecked(bool(cmds.optionVar(query="stukachCoordinatorLock")))
        act = menu.exec_(self._opts_btn.mapToGlobal(
            self._opts_btn.rect().bottomLeft()))
        if act is a_start:
            cmds.optionVar(iv=("stukachStartCoordinator",
                               1 if a_start.isChecked() else 0))
        elif act is a_lock:
            if a_lock.isChecked():
                cmds.optionVar(iv=("stukachCoordinatorLock", 1))
            elif cmds.optionVar(exists="stukachCoordinatorLock"):
                cmds.optionVar(remove="stukachCoordinatorLock")
            _manager.MayaCheck._notify_ui()

    def _on_live_toggled(self) -> None:
        _manager.MayaCheck.set_live(self._mode_live_btn.isChecked())

    def _on_tick(self) -> None:
        mc = _manager.MayaCheck
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return   # never validate under a modal dialog
        # progressive validation: drain the queue in small time-budgeted steps
        if mc.validation_pending():
            mc.validation_step()
            self._tick_count += 1
        # live mode: enqueue dirty revalidation once per second
        self._tick_count += 1
        if mc.live and mc._running and self._tick_count % 7 == 0:
            if mc.objects:
                mc.live_tick()

    def _on_units_toggled(self, state: int) -> None:
        self._update_scene_units(int(state) == 2)

    def _on_empty_groups_toggled(self, state: int) -> None:
        self._update_empty_groups(int(state) == 2)

    def _update_empty_groups(self, enabled: bool) -> None:
        if not enabled:
            self._eg_groups = []
            for _toggle, status in self._eg_rows:
                status.setText("")
            return
        try:
            res = _core.check_empty_groups()
        except Exception:
            for _toggle, status in self._eg_rows:
                status.setText("?")
            return
        self._eg_groups = res.get("groups", [])
        n = len(self._eg_groups)
        for _toggle, status in self._eg_rows:
            if n:
                status.setText("%d empty group%s" % (n, "s" if n != 1 else ""))
                status.setStyleSheet(
                    "color: #b0a060; font-size: %dpx;" % max(1, _FONT_PX - 1))
            else:
                status.setText("clean")
                status.setStyleSheet(
                    "color: #477a3c; font-size: %dpx;" % max(1, _FONT_PX - 1))

    def _on_empty_groups_sel(self) -> None:
        if self._eg_groups:
            cmds.select(self._eg_groups, replace=True)

    def _on_next_issue(self) -> None:
        target = _manager.MayaCheck.next_issue()
        if target:
            self._next_issue_btn.setToolTip(
                "Next: %s" % target.split("|")[-1])

    def _on_copy_summary(self) -> None:
        text = _manager.MayaCheck.build_summary_text()
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        cmds.inViewMessage(amg="STUKACH: summary copied to clipboard",
                           pos="topCenter", fade=True)
        _manager.alog("summary copied to clipboard (%d chars)" % len(text))

    def _on_debug_info(self) -> None:
        text = _manager.MayaCheck.get_debug_info()
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        cmds.inViewMessage(amg="STUKACH: debug info copied to clipboard",
                           pos="topCenter", fade=True)

    def _on_objects_collapse(self) -> None:
        was_open = self._objects_open
        self._objects_open = not was_open
        self._objects_content.setVisible(self._objects_open)
        self._objects_collapse.setText("▾" if self._objects_open else "▸")
        if self._objects_open:
            QtCore.QTimer.singleShot(30, self._grow_for_objects)
        else:
            QtCore.QTimer.singleShot(30, lambda: self._scroll.ensureWidgetVisible(
                self._objects_box, 0, _px(20)))

    def _grow_for_objects(self) -> None:
        """Grow the window down so the expanded Objects list is on screen."""
        self._scroll.ensureWidgetVisible(self._objects_box, 0, _px(20))
        needed = self._objects_content.sizeHint().height() + _px(40)
        viewport_h = max(1, self._scroll.viewport().height())
        hidden = max(0, needed - viewport_h)
        if hidden > 0:
            self._animate_to_height(self.height() + hidden)

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text.lower().strip()
        self._apply_filter()

    def _on_issues_only(self) -> None:
        self._issues_only = self._issues_only_btn.isChecked()
        self._apply_filter()

    def _on_expand_all(self) -> None:
        any_open = any(r.is_open() for r in self._obj_rows.values())
        target = not any_open
        for r in self._obj_rows.values():
            r.set_open(target)
        self._expand_all_btn.setText(
            "Collapse All" if target else "Expand All")

    _PRESET_NONE = "-- presets --"

    def _refresh_preset_combo(self) -> None:
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        self._preset_combo.addItem(self._PRESET_NONE)
        for name in _manager.MayaCheck.list_presets():
            self._preset_combo.addItem(name)
        self._preset_combo.blockSignals(False)

    def _on_preset_selected(self, index: int) -> None:
        if index <= 0:
            return
        name = self._preset_combo.itemText(index)
        if not _manager.MayaCheck.load_preset(name):
            return
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentIndex(0)
        self._preset_combo.blockSignals(False)

    def _on_preset_save(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        _manager.MayaCheck.save_preset(name.strip())
        self._refresh_preset_combo()

    def _on_preset_delete(self) -> None:
        name = self._preset_combo.currentText()
        if not name or name == self._PRESET_NONE:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "Delete Preset", f"Delete preset '{name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            _manager.MayaCheck.delete_preset(name)
            self._refresh_preset_combo()

    def _on_export(self, fmt: str) -> None:
        exts = {"json": "JSON (*.json)", "csv": "CSV (*.csv)",
                "html": "HTML (*.html)"}
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Report", "", exts.get(fmt, "Report (*.*)"))
        if not path:
            return
        ok = _manager.MayaCheck.export_report(path, fmt)
        if ok:
            QtWidgets.QMessageBox.information(self, "Export", f"Saved:\n{path}")
        else:
            QtWidgets.QMessageBox.warning(self, "Export", "Failed. Check console.")

    def _on_publish(self, fmt: str = "fbx") -> None:
        mc = _manager.MayaCheck
        check = mc.preflight_export()
        if check == "blocked":
            QtWidgets.QMessageBox.critical(
                self, "Blocked", f"{mc.total_blockers()} BLOCKER issues.\nFix first.")
            return
        if check == "warning":
            reply = QtWidgets.QMessageBox.warning(
                self, "Warning", f"{mc.total_warnings()} warnings.\nProceed?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply != QtWidgets.QMessageBox.Yes:
                return
        if fmt == "usd":
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Publish USD", "", "USD (*.usd *.usda *.usdc)")
        else:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Publish FBX", "", "FBX (*.fbx)")
        if path:
            mc.publish(path, fmt)

    def _on_checkpoint_save(self) -> None:
        if _manager.MayaCheck.save_checkpoint():
            cmds.inViewMessage(amg="STUKACH: checkpoint saved to scene",
                               pos="topCenter", fade=True)
        self.refresh()

    def _on_checkpoint_load(self) -> None:
        if not _manager.MayaCheck.load_checkpoint():
            QtWidgets.QMessageBox.information(
                self, "Checkpoint", "No checkpoint in this scene file.")
        self.refresh()

    def _on_checkpoint_clear(self) -> None:
        _manager.MayaCheck.clear_checkpoint()
        self.refresh()

    # ── refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        mc = _manager.MayaCheck

        if mc.is_isolating():
            isolated = [k for k, en in mc._enabled_checks.items() if en]
            name = (_CHECK_DISPLAY_NAMES.get(isolated[0], isolated[0])
                    if isolated else "")
            self._isolate_badge.setText(f"ISOLATED: {name}")
            self._isolate_badge.setVisible(True)
        else:
            self._isolate_badge.setVisible(False)

        # run button state (MayaCheck may have been started/stopped elsewhere)
        running = mc._running
        self._run_btn.blockSignals(True)
        self._run_btn.setChecked(running)
        self._run_btn.setText(
            ("\u25cf STUKACH ACTIVE" if running else "RUN STUKACH"))
        self._run_btn.blockSignals(False)

        # mode toolbar + page stack + category box parenting
        coord = mc.coordinator_mode
        self._mode_coord_btn.blockSignals(True)
        self._mode_coord_btn.setChecked(coord)
        self._mode_coord_btn.setText("Artist Mode" if coord else "Coordinator Mode")
        self._mode_coord_btn.blockSignals(False)
        self._stack.setCurrentIndex(1 if coord else 0)
        if hasattr(self, "_uv_rename_btn"):
            self._uv_rename_btn.setVisible(not _coordinator_lock())
        parent_layout = self._coord_checks_layout if coord else self._checks_layout
        if self._category_boxes:
            first = next(iter(self._category_boxes.values()))
            if first.parent() is not (parent_layout.parentWidget()
                                      if parent_layout is not None else None):
                for i, box in enumerate(self._category_boxes.values()):
                    box.setParent(None)
                    if coord:
                        parent_layout.addWidget(box)
                    else:
                        # artist page: categories must sit between the
                        # "Pipeline Checks:" label and the presets row
                        parent_layout.insertWidget(1 + i, box)
                    box.setVisible(True)   # setParent(None) hides the widget

        # scope buttons on both pages
        scene_checked = (mc.scope == "SCENE")
        for scene_btn, selected_btn in (
                (self._scope_scene_btn, self._scope_selected_btn),
                (self._coord_scope_scene_btn, self._coord_scope_selected_btn)):
            scene_btn.blockSignals(True)
            selected_btn.blockSignals(True)
            scene_btn.setChecked(scene_checked)
            selected_btn.setChecked(not scene_checked)
            scene_btn.blockSignals(False)
            selected_btn.blockSignals(False)

        # checkpoint hint
        restored = mc._checkpoint_restored
        self._hint_label.setText(
            "Checkpoint restored - press RUN to revalidate" if restored else "")
        self._hint_label.setVisible(restored)

        # live button state
        self._mode_live_btn.blockSignals(True)
        self._mode_live_btn.setChecked(mc.live)
        self._mode_live_btn.blockSignals(False)

        for box in self._category_boxes.values():
            box.refresh()
        if not coord:
            self._refresh_objects(mc)
        self._update_score_block(mc)
        self._update_scene_units(self._units_rows[0][0].isChecked())
        self._ignored_box.refresh()

    def _refresh_objects(self, mc) -> None:
        current = set(mc.objects.keys())
        listed = set(self._obj_rows.keys())
        for t in listed - current:
            row = self._obj_rows.pop(t)
            row.setParent(None)
            row.deleteLater()
        all_keys = [k for keys in _core.CHECK_CATEGORIES.values() for k in keys]
        for t in current - listed:
            row = _ObjectRow(t, tuple(all_keys))
            self._obj_list_layout.addWidget(row)
            self._obj_rows[t] = row
        n_issues = 0
        for t, row in self._obj_rows.items():
            mco = mc.objects.get(t)
            if mco:
                row.refresh(mco)
                if row._status != "clean":
                    n_issues += 1
        self._objects_issues.setText("%d" % n_issues if n_issues else "")
        self._apply_filter()
        self._sort_rows_worst_first()

    def _sort_rows_worst_first(self) -> None:
        """Reorder visible rows: critical, then warning, then clean, then name."""
        order = {"critical": 0, "warning": 1, "clean": 2}
        rows = sorted(
            self._obj_rows.values(),
            key=lambda r: (order.get(r._status, 3), r._transform.split("|")[-1]))
        for row in rows:
            self._obj_list_layout.removeWidget(row)
        for row in rows:
            self._obj_list_layout.addWidget(row)

    def _apply_filter(self) -> None:
        visible = 0
        total = len(self._obj_rows)
        for t, row in self._obj_rows.items():
            name = t.split("|")[-1].lower()
            ok = (not self._filter_text or self._filter_text in name)
            if ok and self._issues_only:
                ok = row._status != "clean"
            row.setVisible(ok)
            if ok:
                visible += 1
        if self._filter_text or self._issues_only:
            self._objects_count.setText(f"{visible} / {total}")
        else:
            self._objects_count.setText(str(total))

    def _update_scene_units(self, enabled: bool) -> None:
        if not enabled:
            for _toggle, status in self._units_rows:
                status.setText("")
            return
        try:
            res = _core.check_scene_units()
        except Exception:
            for _toggle, status in self._units_rows:
                status.setText("?")
            return
        for _toggle, status in self._units_rows:
            if res.get("ok"):
                status.setText("METRIC · m · 1.0")
                status.setStyleSheet(
                    "color: #477a3c; font-size: %dpx;" % max(1, _FONT_PX - 1))
            else:
                issues = " · ".join(res.get("issues", ["issues"]))
                status.setText(issues)
                status.setStyleSheet(
                    "color: #ad4133; font-size: %dpx;" % max(1, _FONT_PX - 1))

    def _update_score_block(self, mc) -> None:
        """Score block + health strip + asset status / coordinator gate."""
        fs1 = _FONT_PX
        fs2 = max(1, _FONT_PX - 2)
        summary = mc.category_summary()
        self._health_strip.refresh(summary)

        # progress indicator — text only for substantial queues, otherwise
        # short live passes would flash the label half a second at a time
        pending = len(mc._val_queue)
        self._progress_label.setText(
            "Validating... %d to go" % pending if pending > 3 else "")

        coord = mc.coordinator_mode
        if not mc.objects:
            self._score_text.setText("Awaiting suspects.")
            self._score_text.setStyleSheet(
                f"color: #a0a0a0; font-size: {fs1}px; font-style: italic;")
            self._score_icon.set_color(_C_GREY)
            self._score_scope.setText("")
            self._verdict_headline.setText("No active checks.")
            self._verdict_headline.setStyleSheet(
                f"color: #909090; font-size: {fs1}px; font-weight: bold;")
            self._verdict_subtext.setText("")
            self._gate_headline.setText("Run validation first")
            self._gate_headline.setStyleSheet(
                f"color: #909090; font-size: {fs1}px; font-weight: bold;")
            self._gate_subtext.setText("")
            return

        b = mc.total_blockers()
        w = mc.total_warnings()
        n = len(mc.objects)

        if b and w:
            count_text = f"{n} obj · {b} block {w} warn"
        elif b:
            count_text = f"{n} obj · {b} blockers"
        elif w:
            count_text = f"{n} obj · {w} warnings"
        else:
            count_text = f"{n} obj · clean"
        self._score_text.setText(count_text)
        self._score_text.setStyleSheet(
            f"color: #c8c8c8; font-size: {fs1}px; font-weight: bold;")
        self._score_icon.set_color(
            _C_RED if b else (_C_YELLOW if w else _C_GREEN))

        scope_text = "[ %s ]" % ("SELECTED" if mc.scope == "SELECTED" else "SCENE")
        self._score_scope.setText(scope_text)
        self._score_scope.setStyleSheet(f"color: #909090; font-size: {fs2}px;")

        # Asset status (artist) / gate badge (coordinator)
        status = mc.asset_status()
        if status == "CRITICAL":
            headline, hcolor = "ASSET STATUS: CRITICAL", "#d86868"
            subtext = "Publish blocked — fix blockers first"
        elif status == "WARNING":
            headline, hcolor = "ASSET STATUS: WARNING", _C_YELLOW
            subtext = "Needs more work before delivery"
        else:
            headline, hcolor = "ASSET STATUS: PIPELINE READY", _C_GREEN
            subtext = "Asset is production-ready"
        if not coord:
            self._verdict_headline.setText(headline)
            self._verdict_headline.setStyleSheet(
                f"color: {hcolor}; font-size: {fs1}px; font-weight: bold;")
            self._verdict_subtext.setText(subtext)
        else:
            gate = {
                "CRITICAL": ("BLOCKED", "#d86868",
                             "Blockers must be resolved before publish"),
                "WARNING": ("REVIEW", _C_YELLOW,
                            "Warnings require artist decision"),
                "READY": ("READY", _C_GREEN, "Asset is production-ready"),
            }.get(status)
            if gate:
                self._gate_headline.setText(gate[0])
                self._gate_headline.setStyleSheet(
                    f"color: {gate[1]}; font-size: {fs1}px; font-weight: bold;")
                self._gate_subtext.setText(gate[2])


# ── launch / close ────────────────────────────────────────────────────────────

_panel_instance: StukachPanel = None


def _dock_builder(wc_name: str) -> None:
    """uiScript callback of the workspaceControl: parents a StukachPanel
    into the docked control. Runs on restore (scene start / layout load)."""
    try:
        # Maya 2025 dropped the -marshal query flag; findControl returns the
        # Qt pointer of the workspaceControl's main widget
        ptr = omui.MQtUtil.findControl(wc_name)
        if not ptr:
            return
        host = wrapInstance(int(ptr), QtWidgets.QWidget)
        for w in host.findChildren(QtWidgets.QWidget, WINDOW_NAME):
            try:
                w.deleteLater()
            except Exception:
                pass
        global _panel_instance
        layout = host.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(host)
        layout.setContentsMargins(8, 8, 8, 8)   # dock bg shows around the panel
        panel = StukachPanel(parent=host)
        # docked: the workspace column may be narrower than the floating
        # minimum (378) — a wider minimum was centered and clipped both sides
        panel.setMinimumWidth(dpi_scale(280))
        # the floating window's extra right-margin reserve is not needed
        # inside a dock column: asymmetric margins made the content wider
        # than the column and clipped both edges
        # native Maya windows inset their content from the frame — match that.
        # ABSOLUTE pixels: _px() shrinks with the small Maya font and the
        # insets become invisible
        panel.layout().setContentsMargins(14, 8, 14, 8)
        layout.addWidget(panel)
        _panel_instance = panel
    except Exception as e:
        _manager.alog("dock builder failed: %s" % e)


def _maya_main_window():
    try:
        ptr = omui.MQtUtil.mainWindow()
        if ptr:
            return wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception:
        pass
    return None


def _cleanup_dock_leftovers() -> None:
    """Remove any docks/forms left by previous STUKACH versions."""
    for ctrl in (_DOCK_CONTROL, _WORKSPACE_CONTROL, _WC):
        try:
            if cmds.dockControl(ctrl, exists=True):
                cmds.deleteUI(ctrl, control=True)
        except Exception:
            pass
        try:
            if cmds.workspaceControl(ctrl, exists=True):
                cmds.deleteUI(ctrl, control=True)
        except Exception:
            pass
    try:
        if cmds.formLayout(_HOST_FORM, exists=True):
            cmds.deleteUI(_HOST_FORM)
    except Exception:
        pass


_CMD_PORT = "127.0.0.1:7321"


def _ensure_command_port() -> None:
    """Open a localhost command port so external tooling (tests, CI) can
    drive this Maya session without restarting it."""
    try:
        if not cmds.commandPort(_CMD_PORT, query=True):
            cmds.commandPort(name=_CMD_PORT, sourceType="python",
                             echoOutput=False)
    except Exception:
        pass


_NEW_CHECKS_V11 = ("hard_edges", "lamina", "zero_length_edges", "starlike",
                   "missing_uvs", "duplicated_names", "shape_names",
                   "trailing_numbers", "uncentered_pivots", "parent_geometry")


def _migrate_new_checks() -> None:
    """One-time: enable the v1.1 checks on upgrade (they ship OFF and would
    otherwise be invisible to existing users)."""
    try:
        if cmds.optionVar(query="stukachNewChecks10"):
            return
        for k in _NEW_CHECKS_V11:
            _manager.MayaCheck._enabled_checks[k] = True
        cmds.optionVar(sv=("stukachNewChecks10", "1"))
        cmds.inViewMessage(amg="STUKACH: 10 new checks enabled (v1.1)",
                           pos="topCenter", fade=True)
    except Exception:
        pass


def launch() -> StukachPanel:
    """Open the STUKACH panel DOCKED to the right column of the main window
    (left of the Attribute Editor), like the user's reference layout.
    Falls back to the floating top-right window if docking fails."""
    global _panel_instance
    _ensure_command_port()
    _migrate_new_checks()
    _manager.MayaCheck.apply_startup_options()
    if _panel_instance is not None:
        try:
            _panel_instance.close()
            _panel_instance.deleteLater()
        except Exception:
            pass
        _panel_instance = None
    try:
        if cmds.workspaceControl(_WC, exists=True):
            cmds.deleteUI(_WC)
    except Exception:
        pass
    _cleanup_dock_leftovers()
    # Hot-reload (shelf button) purges the modules, so _panel_instance may
    # point nowhere while old panels still exist — kill them by object name.
    try:
        root = _maya_main_window() or QtWidgets.QApplication.instance()
        for w in root.findChildren(QtWidgets.QWidget, WINDOW_NAME):
            try:
                w.close()
                w.deleteLater()
            except Exception:
                pass
    except Exception:
        pass

    # ── docked (default) ──
    try:
        ui_script = "import MAYA_STUKACH.ui as _u; _u._dock_builder('%s')" % _WC
        cmds.workspaceControl(_WC, label="STUKACH", uiScript=ui_script)
        cmds.workspaceControl(_WC, edit=True, restore=True)
        cmds.workspaceControl(_WC, edit=True, dockToControl=("AttributeEditor", "left"))
        cmds.workspaceControl(_WC, edit=True, width=dpi_scale(380))
        # no width override: forcing a width wider than the space between the
        # viewport and the Attribute Editor pushed the whole control out of
        # its column (tab + rounded corners clipped at the left edge)
        if _panel_instance is not None:
            _panel_instance.setWindowFlags(Qt.Widget)
            _panel_instance.show()
            _manager.alog("panel docked to AttributeEditor column")
            return _panel_instance
    except Exception as e:
        _manager.alog("docking failed, floating fallback: %s" % e)

    # ── floating fallback ──
    _panel_instance = StukachPanel(parent=_maya_main_window())
    # Qt.Tool: stays above the Maya window, no taskbar entry
    _panel_instance.setWindowFlags(Qt.Tool)

    # Default placement: top-right screen corner (availableGeometry
    # excludes the taskbar)
    try:
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = max(dpi_scale(360), _panel_instance.sizeHint().width())
        h = min(screen.height(), max(dpi_scale(820), _px(980)))
        x = screen.right() - w + 1
        y = screen.top()
        _panel_instance.resize(w, h)
        _panel_instance.move(x, y)
    except Exception:
        _panel_instance.resize(dpi_scale(360), dpi_scale(820))

    _panel_instance.show()
    _panel_instance.raise_()
    _manager.alog("panel launched (v%s)" % _VERSION)
    return _panel_instance


def close() -> None:
    global _panel_instance
    try:
        if cmds.workspaceControl(_WC, exists=True):
            cmds.deleteUI(_WC)
    except Exception:
        pass
    if _panel_instance is not None:
        _manager.MayaCheck.stop()
        try:
            _panel_instance.close()
            _panel_instance.deleteLater()
        except Exception:
            pass
        _panel_instance = None
    _cleanup_dock_leftovers()
