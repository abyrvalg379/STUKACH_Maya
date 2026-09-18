# -*- coding: utf-8 -*-
"""
STUKACH for Maya — Qt panel, pixel-faithful replica of the Blender add-on UI.

Layout (top to bottom, mirrors Blender's ASSET_CHECKER_PT_Panel.draw()):
  STUKACH / pipeline snitch system
  [ RUN STUKACH ]  [Coord]
  score box (obj · block/warn + per-category badges + [SCOPE])
  [Scene][Selected][✕]
  compact: All None Blk Wrn · Preset ▼ S D · Viewport
  Scene Units row
  Pipeline Checks: 7 collapsible categories, 2-column check grid
  Objects (collapsible): filter · per-object expandable details
  ASSET STATUS box
  Export: JSON/CSV/HTML · Pre-flight FBX · Publish

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
                      "non_manifold", "mat_suffix"})

_CHECK_SWATCH = {
    "triangles": "#B2B205", "ngons": "#B20505", "non_manifold": "#05FF05",
    "zero_area": "#FF00FF", "poles": "#4066FF", "isolated_verts": "#FFFF00",
    "boundary_edges": "#FF8000", "duplicate_verts": "#FF9900",
    "face_aspect_ratio": "#FFD900", "flipped_normals": "#FF4D00",
    "invalid_normals": "#00CCFF", "z_fighting": "#FF0000",
    "non_applied_transform": "#FF0000", "scale": "#FF6600",
    "construction_history": "#808080", "origin_at_zero": "#FFCC00",
    "modifier_stack": "#9900FF", "symmetry_x": "#FF2626", "symmetry_y": "#26FF26",
    "symmetry_z": "#2666FF", "uv_single_set": "#0080FF", "uv_udim_ready": "#0080FF",
    "uv_udim_bounds": "#B233FF", "uv_material_udim": "#FF3399",
    "uv_overlap": "#FF3300", "uv_stretch": "#FF8000", "uv_texel_density": "#4DE680",
    "uv_micro_shell": "#FF00CC", "uv_padding": "#FF9900",
    "obj_naming": "#FF8000", "col_naming": "#808080", "mat_numbering": "#FF6619",
    "mat_suffix": "#808080", "mat_assignment": "#808080",
    "missing_textures": "#FF3333", "unused_data": "#99661A",
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
    "face_aspect_ratio": "Face Aspect Ratio", "flipped_normals": "Flipped Normals",
    "invalid_normals": "Invalid Normals", "z_fighting": "Z-Fighting",
    "non_applied_transform": "Non Applied Transform", "scale": "Scale",
    "construction_history": "Construction History", "origin_at_zero": "Origin at Zero",
    "modifier_stack": "Modifier Stack", "symmetry_x": "Symmetry X",
    "symmetry_y": "Symmetry Y", "symmetry_z": "Symmetry Z",
    "uv_single_set": "Uv Single Set", "uv_udim_ready": "Uv UDIM Ready",
    "uv_udim_bounds": "Uv UDIM Bounds", "uv_material_udim": "Uv Material Udim",
    "uv_overlap": "Uv Overlap", "uv_stretch": "Uv Stretch",
    "uv_texel_density": "Uv Texel Density", "uv_micro_shell": "Uv Micro Shell",
    "uv_padding": "Uv Padding", "obj_naming": "Object Name",
    "col_naming": "Group Name", "mat_numbering": "Mat Numbering",
    "mat_suffix": "Mat Suffix", "mat_assignment": "Mat Assignment",
    "missing_textures": "Missing Textures", "unused_data": "Unused Data",
}

_YELLOW_THRESHOLDS = {"triangles": 50, "ngons": 10, "poles": 20}


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
        "QComboBox QAbstractItemView { background: #252525; color: #e6e6e6; selection-background-color: #3d5d8a; border: 1px solid #3a3a3a; outline: none; }"
        "QScrollArea { border: none; background: transparent; }"
        "QScrollBar:vertical { background: #1d1d1d; width: %dpx; border: none; }"
        "QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 4px; min-height: %dpx; }"
        "QScrollBar::handle:vertical:hover { background: #4a4a4a; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        "QLabel { background: transparent; }"
        "QToolButton { color: #8c8c8c; border: none; font-size: %dpx; padding: 0; }"
        "QToolButton:hover { color: #e6e6e6; }"
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


def _status_color(count: int, key: str) -> str:
    if count == 0:
        return _C_GREEN
    thresh = _YELLOW_THRESHOLDS.get(key, 0)
    if thresh and count <= thresh:
        return _C_YELLOW
    return _C_RED


# ── Check grid row (categories): [☑] Label  ●  — Blender's 2-column grid ──────

class _CheckGridRow(QtWidgets.QWidget):
    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self.setFixedHeight(_px(24))

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


# ── Category box: ▸ ICON Title ... [Fix] [☑] + 2-column grid ──────────────────

class _CategoryBox(QtWidgets.QWidget):
    def __init__(self, category: str, keys: tuple, parent=None):
        super().__init__(parent)
        self._category = category
        self._keys = keys
        self._open = True

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
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

        title = QtWidgets.QLabel(category.replace("_", " ").title())
        title.setStyleSheet(
            "color: #c8c8c8; font-size: %dpx; font-weight: bold;" % _FONT_PX)
        header.addWidget(title)
        header.addStretch()

        self._fix_btn = QtWidgets.QPushButton("Fix")
        self._fix_btn.setFixedHeight(_px(20))
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
        for i, key in enumerate(keys):
            row = _CheckGridRow(key, self._content)
            grid.addWidget(row, i // 2, i % 2)
            self._rows[key] = row
        outer.addWidget(self._content)

    def _on_collapse(self) -> None:
        self._open = not self._open
        self._content.setVisible(self._open)
        self._collapse_btn.setText("▾" if self._open else "▸")

    def _on_cat_toggle(self, state: int) -> None:
        enabled = (int(state) == 2)
        _manager.MayaCheck.enable_by_category(self._category, enabled)

    def refresh(self) -> None:
        any_on = any(_manager.MayaCheck._enabled_checks.get(k, False)
                     for k in self._keys)
        self._cat_toggle.blockSignals(True)
        self._cat_toggle.setChecked(any_on)
        self._cat_toggle.blockSignals(False)

        # Category Fix button — some fixable check has issues on some object
        cat_has_fix = any(
            k in _FIXABLE and _manager.MayaCheck._enabled_checks.get(k, False)
            and any(mco.checkers.get(k) and mco.checkers[k].count > 0
                    for mco in _manager.MayaCheck.objects.values())
            for k in self._keys)
        self._fix_btn.setVisible(cat_has_fix)

        coord = _manager.MayaCheck.coordinator_mode
        # Hide INFO rows in coordinator mode (Blender hides INFO entirely)
        info_keys = set()
        if coord:
            for k in self._keys:
                if _core.CHECK_SEVERITIES.get(k) == "INFO":
                    info_keys.add(k)
        # Re-flow grid so hiding INFO rows doesn't leave empty cells
        visible = [k for k in self._keys if k not in info_keys]
        for i, key in enumerate(visible):
            row = self._rows[key]
            grid = self._content.layout()
            grid.removeWidget(row)
            grid.addWidget(row, i // 2, i % 2)
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


# ── Per-object detail row: [✓] Label: count  [Sel][Ign][Fix] ─────────────────

class _DetailCheckRow(QtWidgets.QWidget):
    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self.setFixedHeight(_px(24))

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(_px(10), 0, _px(2), 0)
        layout.setSpacing(_px(3))

        self._icon = QtWidgets.QLabel("✓")
        self._icon.setFixedWidth(_px(16))
        layout.addWidget(self._icon)

        self._label = QtWidgets.QLabel("")
        layout.addWidget(self._label, stretch=1)

        small = ("QPushButton { font-size: %dpx; padding: %dpx %dpx; }"
                 % (max(1, _FONT_PX - 2), 0, _px(5)))

        def _mini(text, tooltip):
            b = QtWidgets.QPushButton(text)
            b.setFixedHeight(_px(18))
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

    def refresh(self, mco: "_manager.MayaCheckObject") -> None:
        checker = mco.checkers.get(self._key)
        enabled = mco.enabled.get(self._key, False)
        if not enabled or checker is None or checker.count == 0:
            self.setVisible(False)
            return
        self.setVisible(True)

        transform = self._find_transform()
        ignored = bool(
            transform and self._key in _manager.get_ignore_list(transform))
        count = checker.count

        mt = getattr(checker, "metric_text", "") or ""
        text = mt if mt else "%s: %d" % (
            _CHECK_DISPLAY_NAMES.get(self._key, self._key), count)

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
            return

        self._ign_btn.setText("Ign")
        self._ign_btn.setToolTip("Ignore this issue (excluded from status)")
        color = _status_color(count, self._key)
        self._icon.setText("!!" if color == _C_RED else "!")
        self._icon.setStyleSheet("color: %s; font-weight: bold;" % color)
        self._label.setText(text)
        self._label.setStyleSheet("color: #d5d5d5; font-size: %dpx;"
                                  % max(1, _FONT_PX - 1))
        self._sel_btn.setVisible(bool(checker.bad_components))
        self._fix_btn.setVisible(self._key in _FIXABLE)

    def _on_select(self) -> None:
        mco = self._find_mco()
        if mco:
            checker = mco.checkers.get(self._key)
            if checker and checker.bad_components:
                checker.select()

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


# ── Object row: ▸ name  ●status  → expandable details ─────────────────────────

def _obj_stats(transform: str):
    try:
        shape = cmds.listRelatives(transform, shapes=True, type="mesh",
                                   fullPath=True) or []
        if not shape:
            return (0, 0, 0, 0)
        v = cmds.polyEvaluate(shape[0], vertex=True) or 0
        e = cmds.polyEvaluate(shape[0], edge=True) or 0
        f = cmds.polyEvaluate(shape[0], face=True) or 0
        t = cmds.polyEvaluate(shape[0], triCount=True) or 0
        return (int(v), int(e), int(f), int(t))
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
        self._detail.setVisible(False)
        outer.addWidget(self._detail)

    def _on_expand(self) -> None:
        self._open = not self._open
        self._detail.setVisible(self._open)
        self._expand_btn.setText("▾" if self._open else "▸")

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
            for row in self._detail_rows.values():
                row.refresh(mco)




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
        clear_btn.setFixedHeight(_px(20))
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
_WORKSPACE_CONTROL = "StukachPanelWorkspaceControl"
_DOCK_CONTROL = "StukachPanelDockControl"
_HOST_FORM = "stukachHostForm"


class StukachPanel(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(WINDOW_NAME)
        self.setWindowTitle("STUKACH")
        self.setMinimumWidth(dpi_scale(360))
        self.setStyleSheet(_QSS)

        self._obj_rows: Dict[str, _ObjectRow] = {}
        self._filter_text = ""
        self._issues_only = False

        self._build_ui()
        # Fill the dock vertically — without this the panel reports a small
        # sizeHint and the dock opens at ~1/3 of the window height
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Expanding)
        _manager.MayaCheck._ui_callback = self.refresh

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(_px(6), _px(6), _px(6), _px(6))
        root.setSpacing(_px(4))

        # ── header: title + subtitle (Blender panel header) ──
        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(0)
        title = QtWidgets.QLabel("STUKACH")
        title.setStyleSheet("color: #e5e5e5; font-size: %dpx; font-weight: bold;"
                            % _px(15))
        title_box.addWidget(title)
        subtitle = QtWidgets.QLabel("pipeline snitch system")
        subtitle.setStyleSheet("color: #909090; font-size: %dpx;" % _px(10))
        title_box.addWidget(subtitle)
        root.addLayout(title_box)

        # ── RUN toggle + coordinator (Blender run_row) ──
        run_row = QtWidgets.QHBoxLayout()
        run_row.setSpacing(_px(3))
        self._run_btn = QtWidgets.QPushButton("RUN STUKACH")
        self._run_btn.setCheckable(True)
        self._run_btn.setFixedHeight(_px(34))
        self._run_btn.clicked.connect(self._on_run)
        self._run_btn.setStyleSheet(
            "QPushButton { background: %s; color: #fff; font-weight: bold; }"
            "QPushButton:hover { background: #5683c8; }" % _C_SELECT)
        run_row.addWidget(self._run_btn, stretch=1)
        self._coord_btn = QtWidgets.QPushButton("◎")
        self._coord_btn.setCheckable(True)
        self._coord_btn.setFixedSize(_px(34), _px(34))
        self._coord_btn.setToolTip("Coordinator mode: hide INFO, pipeline gate")
        self._coord_btn.clicked.connect(self._on_coordinator_toggled)
        run_row.addWidget(self._coord_btn)
        root.addLayout(run_row)

        # isolate badge (Shift+click on a check)
        self._isolate_badge = QtWidgets.QLabel("")
        self._isolate_badge.setStyleSheet(
            "background: #4772b3; color: white; font-size: %dpx;"
            " font-weight: bold; padding: 1px %dpx; border-radius: %dpx;"
            % (_px(10), _px(6), _px(3)))
        self._isolate_badge.setVisible(False)
        root.addWidget(self._isolate_badge)

        # ── score box ──
        self._score_widget = QtWidgets.QWidget()
        score_layout = QtWidgets.QVBoxLayout(self._score_widget)
        score_layout.setContentsMargins(_px(2), _px(2), _px(2), _px(2))
        score_layout.setSpacing(_px(2))

        self._score_line1 = QtWidgets.QHBoxLayout()
        self._score_line1.setSpacing(_px(5))
        self._score_icon = _StatusDot(self._score_widget)
        self._score_line1.addWidget(self._score_icon)
        self._score_text = QtWidgets.QLabel("Awaiting suspects.")
        self._score_text.setStyleSheet(
            "color: #a0a0a0; font-size: %dpx; font-style: italic;" % _FONT_PX)
        self._score_line1.addWidget(self._score_text)
        self._score_line1.addStretch()
        self._score_scope = QtWidgets.QLabel("")
        self._score_scope.setStyleSheet(
            "color: #909090; font-size: %dpx;" % max(1, _FONT_PX - 2))
        self._score_line1.addWidget(self._score_scope)
        score_layout.addLayout(self._score_line1)

        self._score_badges_row = QtWidgets.QHBoxLayout()
        self._score_badges_row.setSpacing(_px(7))
        self._cat_badges: Dict[str, QtWidgets.QLabel] = {}
        for cat in _core.CHECK_CATEGORIES:
            badge_box = QtWidgets.QHBoxLayout()
            badge_box.setSpacing(_px(2))
            dot = _StatusDot(self._score_widget, size=7)
            badge_box.addWidget(dot)
            lbl = QtWidgets.QLabel(f"{cat[:4]}: 0")
            lbl.setStyleSheet("color: #909090; font-size: %dpx;"
                              % max(1, _FONT_PX - 2))
            badge_box.addWidget(lbl)
            wrap = QtWidgets.QWidget()
            wrap.setLayout(badge_box)
            self._score_badges_row.addWidget(wrap)
            self._cat_badges[cat] = lbl
            setattr(lbl, "_dot", dot)  # companion dot
        self._score_badges_row.addStretch()
        score_layout.addLayout(self._score_badges_row)
        root.addWidget(self._score_widget)

        # ── scope row: Scene | Selected | ✕ ──
        scope_row = QtWidgets.QHBoxLayout()
        scope_row.setSpacing(_px(2))
        self._scope_group = QtWidgets.QButtonGroup(self)
        self._scope_group.setExclusive(True)
        self._scope_scene_btn = QtWidgets.QPushButton("Scene")
        self._scope_selected_btn = QtWidgets.QPushButton("Selected")
        for btn in (self._scope_scene_btn, self._scope_selected_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(_px(24))
            self._scope_group.addButton(btn)
            scope_row.addWidget(btn, stretch=1)
        self._scope_scene_btn.setChecked(True)
        self._scope_scene_btn.clicked.connect(lambda: self._on_scope_changed("SCENE"))
        self._scope_selected_btn.clicked.connect(lambda: self._on_scope_changed("SELECTED"))
        self._clear_btn = QtWidgets.QPushButton("✕")
        self._clear_btn.setFixedSize(_px(26), _px(24))
        self._clear_btn.setToolTip("Stop validation and clear results")
        self._clear_btn.clicked.connect(self._on_stop)
        scope_row.addWidget(self._clear_btn)
        root.addLayout(scope_row)

        # ── compact batch row (Maya-specific, dim) ──
        batch_row = QtWidgets.QHBoxLayout()
        batch_row.setSpacing(_px(2))
        small_qss = ("QPushButton { font-size: %dpx; padding: %dpx %dpx; }"
                     % (max(1, _FONT_PX - 2), _px(1), _px(5)))

        def _small(text, tooltip, slot):
            b = QtWidgets.QPushButton(text)
            b.setFixedHeight(_px(20))
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

        self._preset_combo = QtWidgets.QComboBox()
        self._preset_combo.setFixedHeight(_px(20))
        self._preset_combo.setMinimumWidth(_px(70))
        self._preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        batch_row.addWidget(self._preset_combo)

        def _mini(text, tooltip):
            b = QtWidgets.QPushButton(text)
            b.setFixedSize(_px(22), _px(20))
            b.setStyleSheet(small_qss)
            b.setToolTip(tooltip)
            batch_row.addWidget(b)
            return b

        self._preset_save_btn = _mini("S", "Save preset")
        self._preset_save_btn.clicked.connect(self._on_preset_save)
        self._preset_del_btn = _mini("D", "Delete preset")
        self._preset_del_btn.clicked.connect(self._on_preset_delete)

        self._overlay_cb = QtWidgets.QCheckBox("Viewport")
        self._overlay_cb.setChecked(True)
        self._overlay_cb.setToolTip("Viewport overlay on/off")
        self._overlay_cb.stateChanged.connect(self._on_overlay_toggled)
        batch_row.addWidget(self._overlay_cb)
        root.addLayout(batch_row)
        self._refresh_preset_combo()

        # ── scene units row ──
        units_row = QtWidgets.QHBoxLayout()
        units_row.setSpacing(_px(4))
        self._units_toggle = QtWidgets.QCheckBox("Scene Units")
        self._units_toggle.setToolTip("Check scene units: METRIC · m · scale 1.0")
        self._units_toggle.stateChanged.connect(self._on_units_toggled)
        units_row.addWidget(self._units_toggle)
        units_row.addStretch()
        self._units_status = QtWidgets.QLabel("")
        self._units_status.setStyleSheet(
            "color: #909090; font-size: %dpx;" % max(1, _FONT_PX - 1))
        units_row.addWidget(self._units_status)
        root.addLayout(units_row)

        # ── scroll: Pipeline Checks + Objects ──
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        container = QtWidgets.QWidget()
        cont_layout = QtWidgets.QVBoxLayout(container)
        cont_layout.setContentsMargins(0, 0, 0, 0)
        cont_layout.setSpacing(_px(3))

        checks_lbl = QtWidgets.QLabel("Pipeline Checks:")
        checks_lbl.setStyleSheet(
            "color: #c8c8c8; font-size: %dpx; font-weight: bold;" % _FONT_PX)
        cont_layout.addWidget(checks_lbl)

        self._category_boxes: Dict[str, _CategoryBox] = {}
        for cat, keys in _core.CHECK_CATEGORIES.items():
            box = _CategoryBox(cat, keys)
            box._on_collapse()   # all categories collapsed by default
            cont_layout.addWidget(box)
            self._category_boxes[cat] = box

        # ── Objects section (collapsible) ──
        self._objects_box = QtWidgets.QWidget()
        obj_outer = QtWidgets.QVBoxLayout(self._objects_box)
        obj_outer.setContentsMargins(0, 0, 0, 0)
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
        self._filter_edit.setPlaceholderText("Filter…")
        self._filter_edit.setFixedHeight(_px(22))
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        filt_row.addWidget(self._filter_edit, stretch=1)
        self._issues_only_btn = QtWidgets.QPushButton("Issues only")
        self._issues_only_btn.setCheckable(True)
        self._issues_only_btn.setFixedHeight(_px(22))
        self._issues_only_btn.clicked.connect(self._on_issues_only)
        filt_row.addWidget(self._issues_only_btn)
        self._filter_count = QtWidgets.QLabel("0 / 0")
        self._filter_count.setStyleSheet(
            "color: #909090; font-size: %dpx;" % max(1, _FONT_PX - 2))
        filt_row.addWidget(self._filter_count)
        oc_layout.addLayout(filt_row)

        self._expand_all_btn = QtWidgets.QPushButton("Expand All")
        self._expand_all_btn.setFixedHeight(_px(20))
        self._expand_all_btn.setStyleSheet(small_qss)
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

        self._ignored_box = _IgnoredBox()
        self._ignored_box.setVisible(False)
        cont_layout.addWidget(self._ignored_box)
        cont_layout.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll, stretch=1)

        # ── asset status box ──
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

        # ── export box ──
        export_box = QtWidgets.QWidget()
        exp_sep = QtWidgets.QFrame()
        exp_sep.setFixedHeight(1)
        exp_sep.setStyleSheet("background: #2a2a2a;")
        root.addWidget(exp_sep)
        exp_layout = QtWidgets.QVBoxLayout(export_box)
        exp_layout.setContentsMargins(_px(2), _px(4), _px(2), _px(2))
        exp_layout.setSpacing(_px(3))

        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(_px(3))
        lbl1 = QtWidgets.QLabel("Export:")
        lbl1.setStyleSheet("color: #a0a0a0;")
        lbl1.setFixedWidth(_px(58))
        row1.addWidget(lbl1)
        for fmt in ("JSON", "CSV", "HTML"):
            b = QtWidgets.QPushButton(fmt)
            b.setFixedHeight(_px(22))
            b.clicked.connect(lambda _=False, f=fmt.lower(): self._on_export(f))
            row1.addWidget(b, stretch=1)
        exp_layout.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(_px(3))
        lbl2 = QtWidgets.QLabel("Pre-flight:")
        lbl2.setStyleSheet("color: #a0a0a0;")
        lbl2.setFixedWidth(_px(58))
        row2.addWidget(lbl2)
        b_fbx = QtWidgets.QPushButton("FBX")
        b_fbx.setFixedHeight(_px(22))
        b_fbx.clicked.connect(self._on_publish)
        row2.addWidget(b_fbx, stretch=1)
        exp_layout.addLayout(row2)
        root.addWidget(export_box)

    # ── slots ──

    def _on_run(self) -> None:
        if self._run_btn.isChecked():
            scope = "SCENE" if self._scope_scene_btn.isChecked() else "SELECTED"
            _manager.MayaCheck.scope = scope
            _manager.MayaCheck.set_overlay_enabled(self._overlay_cb.isChecked())
            _manager.MayaCheck.start(ui_callback=self.refresh)
            self._run_btn.setText("STUKACH ACTIVE")
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
        _manager.MayaCheck.set_coordinator_mode(self._coord_btn.isChecked())
        self.refresh()

    def _on_units_toggled(self, state: int) -> None:
        self._update_scene_units(int(state) == 2)

    def _on_objects_collapse(self) -> None:
        self._objects_open = not self._objects_open
        self._objects_content.setVisible(self._objects_open)
        self._objects_collapse.setText("▾" if self._objects_open else "▸")

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

    def _on_publish(self) -> None:
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
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Publish FBX", "", "FBX (*.fbx)")
        if path:
            mc.publish_fbx(path)

    @undo_decorator
    def _on_add_selected(self) -> None:
        sel = cmds.ls(selection=True, long=True, type='transform') or []
        for t in sel:
            _manager.MayaCheck.add_object(t)
        _manager.MayaCheck.run_all()

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
        self._run_btn.setText("STUKACH ACTIVE" if running else "RUN STUKACH")
        self._run_btn.blockSignals(False)

        for box in self._category_boxes.values():
            box.refresh()
        self._refresh_objects(mc)
        self._update_score_block(mc)
        self._update_scene_units(self._units_toggle.isChecked())

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
        self._ignored_box.refresh()
        self._objects_count.setText(str(len(self._obj_rows)))
        self._objects_issues.setText(f"⚠ {n_issues}" if n_issues else "")
        self._apply_filter()

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
        self._filter_count.setText(f"{visible} / {total}")

    def _update_scene_units(self, enabled: bool) -> None:
        if not enabled:
            self._units_status.setText("")
            return
        try:
            res = _core.check_scene_units()
        except Exception:
            self._units_status.setText("?")
            return
        if res.get("ok"):
            self._units_status.setText("METRIC · m · 1.0")
            self._units_status.setStyleSheet(
                "color: #477a3c; font-size: %dpx;" % max(1, _FONT_PX - 1))
        else:
            issues = " · ".join(res.get("issues", ["issues"]))
            self._units_status.setText(issues)
            self._units_status.setStyleSheet(
                "color: #ad4133; font-size: %dpx;" % max(1, _FONT_PX - 1))

    def _update_score_block(self, mc) -> None:
        """Score block (top) + asset status (bottom) — Blender format."""
        fs1 = _FONT_PX
        fs2 = max(1, _FONT_PX - 2)
        if not mc.objects:
            self._score_text.setText("Awaiting suspects.")
            self._score_text.setStyleSheet(
                f"color: #a0a0a0; font-size: {fs1}px; font-style: italic;")
            self._score_icon.set_color(_C_GREY)
            self._score_scope.setText("")
            for lbl in self._cat_badges.values():
                lbl.setText(f"{lbl.text().split(':')[0]}: 0")
                lbl.setStyleSheet(f"color: #6a6a6a; font-size: {fs2}px;")
                getattr(lbl, "_dot").set_color("#4a4a4a")
            self._verdict_headline.setText("No active checks.")
            self._verdict_headline.setStyleSheet(
                f"color: #909090; font-size: {fs1}px; font-weight: bold;")
            self._verdict_subtext.setText("")
            self._verdict_widget.setStyleSheet("")
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

        for cat, keys in _core.CHECK_CATEGORIES.items():
            cat_b = cat_w = 0
            for obj_mco in mc.objects.values():
                obj_ignored = _manager.get_ignore_list(obj_mco.transform)
                for k in keys:
                    if not obj_mco.enabled.get(k) or k in obj_ignored:
                        continue
                    checker = obj_mco.checkers.get(k)
                    if not checker or checker.count == 0:
                        continue
                    sev = _core.CHECK_SEVERITIES.get(k)
                    if sev == "BLOCKER":
                        cat_b += checker.count
                    elif sev == "WARNING":
                        cat_w += checker.count
            badge = self._cat_badges.get(cat)
            if badge is None:
                continue
            total = cat_b + cat_w
            badge.setText(f"{cat[:4]}: {total}")
            dot = getattr(badge, "_dot")
            if cat_b:
                badge.setStyleSheet(f"color: #ad4133; font-size: {fs2}px;")
                dot.set_color(_C_RED)
            elif cat_w:
                badge.setStyleSheet(f"color: #b0a060; font-size: {fs2}px;")
                dot.set_color(_C_YELLOW)
            else:
                badge.setStyleSheet(f"color: #6a6a6a; font-size: {fs2}px;")
                dot.set_color("#4a4a4a")

        # Asset status
        status = mc.asset_status()
        if status == "CRITICAL":
            self._verdict_headline.setText("ASSET STATUS: CRITICAL")
            self._verdict_headline.setStyleSheet(
                f"color: #d86868; font-size: {fs1}px; font-weight: bold;")
            self._verdict_subtext.setText("Стукач блокирует publish")
            self._verdict_widget.setStyleSheet("")
        elif status == "WARNING":
            self._verdict_headline.setText("ASSET STATUS: WARNING")
            self._verdict_headline.setStyleSheet(
                f"color: #b0a060; font-size: {fs1}px; font-weight: bold;")
            self._verdict_subtext.setText("Стукач советует еще поработать")
            self._verdict_widget.setStyleSheet("")
        elif status == "READY":
            self._verdict_headline.setText("ASSET STATUS: PIPELINE READY")
            self._verdict_headline.setStyleSheet(
                f"color: #477a3c; font-size: {fs1}px; font-weight: bold;")
            self._verdict_subtext.setText("Стукач считает ассет production-ready")
            self._verdict_widget.setStyleSheet("")
        else:
            self._verdict_headline.setText("No active checks.")
            self._verdict_headline.setStyleSheet(
                f"color: #909090; font-size: {fs1}px; font-weight: bold;")
            self._verdict_subtext.setText("")
            self._verdict_widget.setStyleSheet("")


# ── launch / close ────────────────────────────────────────────────────────────

_panel_instance: StukachPanel = None


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
    for ctrl in (_DOCK_CONTROL, _WORKSPACE_CONTROL):
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


def launch() -> StukachPanel:
    """Open the STUKACH panel as a floating window anchored to the
    top-right screen corner (user preference — dock hosting proved
    unstable across reopen cycles)."""
    global _panel_instance
    _ensure_command_port()
    if _panel_instance is not None:
        try:
            _panel_instance.close()
            _panel_instance.deleteLater()
        except Exception:
            pass
        _panel_instance = None
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

    _panel_instance = StukachPanel(parent=_maya_main_window())
    # Qt.Tool: stays above the Maya window, no taskbar entry
    _panel_instance.setWindowFlags(Qt.Tool)

    # Default placement: top-right screen corner (availableGeometry
    # excludes the taskbar)
    try:
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = max(dpi_scale(360), _panel_instance.sizeHint().width())
        h = min(screen.height(), max(dpi_scale(760), _px(900)))
        x = screen.right() - w + 1
        y = screen.top()
        _panel_instance.resize(w, h)
        _panel_instance.move(x, y)
    except Exception:
        _panel_instance.resize(dpi_scale(360), dpi_scale(760))

    _panel_instance.show()
    _panel_instance.raise_()
    return _panel_instance


def close() -> None:
    global _panel_instance
    if _panel_instance is not None:
        _manager.MayaCheck.stop()
        try:
            _panel_instance.close()
            _panel_instance.deleteLater()
        except Exception:
            pass
        _panel_instance = None
    _cleanup_dock_leftovers()
