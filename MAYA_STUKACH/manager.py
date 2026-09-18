# -*- coding: utf-8 -*-
"""
STUKACH for Maya — scene manager.

MayaCheck:
  - tracks mesh transforms in the scene (SCENE scope) or just selected ones
    (SELECTED scope) — mirrors Blender's scope modes
  - runs checkers on demand or on scene change (scriptJob)
  - stores per-object results
  - drives a display-layer overlay (red BLOCKERS / yellow WARNINGS) so problems
    are visible in the viewport without a C++ draw plugin
"""
from __future__ import annotations

import getpass
import os
import time
from collections import deque
from typing import Dict, List, Optional

import maya.cmds as cmds
import maya.api.OpenMaya as om

from . import core as _core
from . import overlay as _overlay

# Single source of truth for the panel header, reports and debug info.
_VERSION = "1.1.0"


# ── session log (Blender parity: alog + ring buffer + %TEMP% file) ───────────
# ASCII-only messages — Maya print() dies on emoji (UnicodeEncodeError).

_LOG: deque = deque(maxlen=40)
_LOG_PATH = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMP", "/tmp")), "stukach_maya.log")


def alog(msg: str) -> None:
    """Print + remember the last 40 messages + append to %TEMP%/stukach_maya.log."""
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    print("[STUKACH] " + msg)
    _LOG.append(line)
    try:
        if os.path.exists(_LOG_PATH) and os.path.getsize(_LOG_PATH) > 262144:
            old = _LOG_PATH + ".old"
            if os.path.exists(old):
                os.remove(old)
            os.replace(_LOG_PATH, old)
        with open(_LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ponytail: _DEFAULT_ENABLED removed — RUN only validates what user explicitly enabled.
# Use batch buttons (All/None/Blk/Wrn) to quickly set check state.

# Scope modes — same idea as Blender STUKACH
_SCOPE_SCENE = "SCENE"        # validate every mesh transform in the scene
_SCOPE_SELECTED = "SELECTED"  # validate only currently selected mesh transforms


# Checks that depend on mesh topology (vertices, edges, faces)
_TOPOLOGY_CHECKS = frozenset({
    "triangles", "ngons", "non_manifold", "zero_area", "poles",
    "isolated_verts", "boundary_edges", "duplicate_verts", "face_aspect_ratio",
    "flipped_normals", "invalid_normals", "z_fighting",
    "uv_single_set", "uv_udim_ready", "uv_udim_bounds", "uv_material_udim",
    "uv_overlap", "uv_stretch", "uv_texel_density", "uv_micro_shell", "uv_padding",
})

# Checks that depend on transform (world position, rotation, scale)
_TRANSFORM_CHECKS = frozenset({
    "non_applied_transform", "scale", "origin_at_zero",
    "symmetry_x", "symmetry_y", "symmetry_z",
})


class MayaCheckObject:
    """Holds checker instances + cached results for one transform node.

    Supports dirty detection: only re-runs checkers whose data dependency
    (topology vs transform) has actually changed since the last run.
    """

    def __init__(self, transform: str):
        self.transform: str = transform
        self.dag_path: om.MDagPath = _core._get_dag_path(transform)
        self.checkers: Dict[str, _core.BaseCheck] = {
            key: cls() for key, cls in _core.CHECK_TYPES.items()
        }
        self.enabled: Dict[str, bool] = {key: False for key in _core.CHECK_TYPES}
        self._valid: bool = True
        self._topo_key: tuple = None      # (n_verts, n_edges, n_faces)
        self._transform_key: tuple = None  # world matrix hash

    def _is_topo_dirty(self) -> bool:
        """Check if mesh topology has changed since last run."""
        shape = _core._get_shape(self.transform)
        if not shape:
            return False
        try:
            mesh = _core._get_mesh_fn(self.dag_path)
            key = (mesh.numVertices, mesh.numEdges, mesh.numPolygons)
        except Exception:
            return True
        if key != self._topo_key:
            self._topo_key = key
            return True
        return False

    def _is_transform_dirty(self) -> bool:
        """Check if world transform has changed since last run."""
        try:
            mat = cmds.xform(self.transform, q=True, matrix=True, ws=True)
            key = tuple(round(x, 6) for x in mat)
        except Exception:
            return True
        if key != self._transform_key:
            self._transform_key = key
            return True
        return False

    def run_enabled(self, force: bool = False) -> None:
        """Run enabled checkers. Skip unchanged data with dirty detection.

        Args:
            force: If True, skip dirty detection and run everything.
        """
        if not self._is_alive():
            self._valid = False
            return
        try:
            self.dag_path = _core._get_dag_path(self.transform)
        except Exception:
            self._valid = False
            return

        shape = _core._get_shape(self.transform)
        if not shape:
            return

        # Sync enabled state from class-level source of truth before running
        for key in self.enabled:
            self.enabled[key] = MayaCheck._enabled_checks.get(key, False)

        topo_dirty = force or self._is_topo_dirty()
        xform_dirty = force or self._is_transform_dirty()

        for key, checker in self.checkers.items():
            if not self.enabled.get(key, False):
                checker.reset()
                continue
            # Skip checkers whose data dependency hasn't changed
            # BUT always re-run if checker hasn't been run yet (just re-enabled)
            if not force and checker._ran:
                if key in _TOPOLOGY_CHECKS and not topo_dirty:
                    continue
                if key in _TRANSFORM_CHECKS and not xform_dirty:
                    continue
            try:
                checker.run(self.dag_path)
                checker._ran = True
            except Exception as e:
                checker.reset()
                alog(f"Error in {key} on {self.transform}: {e}")

    def _is_alive(self) -> bool:
        try:
            return cmds.objExists(self.transform)
        except Exception:
            return False

    @property
    def total_blockers(self) -> int:
        ignored = get_ignore_list(self.transform)
        return sum(
            c.count for key, c in self.checkers.items()
            if key not in ignored
            and self.enabled.get(key)
            and _core.CHECK_SEVERITIES.get(key) == "BLOCKER"
        )

    @property
    def total_warnings(self) -> int:
        ignored = get_ignore_list(self.transform)
        return sum(
            c.count for key, c in self.checkers.items()
            if key not in ignored
            and self.enabled.get(key)
            and _core.CHECK_SEVERITIES.get(key) == "WARNING"
        )


# ── Per-object ignore list (Blender parity) ──────────────────────────────────
# Ignored checks stay visible in the object details (greyed out) but are
# excluded from totals, object status, asset status and the score block.

_IGNORE_ATTR = "stukachIgnored"


def get_ignore_list(transform: str) -> set:
    """Set of check keys ignored on this transform."""
    try:
        if not cmds.objExists(transform + "." + _IGNORE_ATTR):
            return set()
        val = cmds.getAttr(transform + "." + _IGNORE_ATTR) or ""
        return {k for k in val.split(",") if k}
    except Exception:
        return set()


def set_ignore_list(transform: str, keys) -> None:
    try:
        if not cmds.objExists(transform + "." + _IGNORE_ATTR):
            cmds.addAttr(transform, longName=_IGNORE_ATTR, dataType="string")
        cmds.setAttr(transform + "." + _IGNORE_ATTR,
                     ",".join(sorted(keys)), type="string")
    except Exception as e:
        alog(f"set_ignore_list failed on {transform}: {e}")


def _all_mesh_transforms() -> List[str]:
    """Return full-path transforms that own a mesh shape, anywhere in the scene."""
    transforms: List[str] = []
    for mesh in cmds.ls(type='mesh', long=True) or []:
        parents = cmds.listRelatives(mesh, parent=True, fullPath=True) or []
        if parents:
            transforms.append(parents[0])
    return transforms


class MayaCheck:
    """Singleton-style manager — one instance per session."""

    objects: Dict[str, MayaCheckObject] = {}   # transform name -> MayaCheckObject
    _enabled_checks: Dict[str, bool] = {key: False for key in _core.CHECK_TYPES}
    scope: str = _SCOPE_SCENE                   # SCENE | SELECTED
    active_check: Optional[str] = None          # key of check in overlay focus, or None
    coordinator_mode: bool = False              # True = hide INFO checks, show asset status badge
    live: bool = False                          # live mode: panel timer calls live_tick()
    _next_issue_ptr: int = 0                    # cycling index for next_issue()
    _job_ids: List[int] = []
    _running: bool = False
    _ui_callback = None   # callable() -> triggers UI refresh

    # ── public API ────────────────────────────────────────────────────────────

    @classmethod
    def start(cls, ui_callback=None) -> None:
        """Begin monitoring. Call after user clicks RUN STUKACH.

        Preserves current enabled_checks — no auto-enable. Use batch buttons
        (All/None/Blk/Wrn) to set check state.
        """
        cls._ui_callback = ui_callback
        cls._running = True
        cls.active_check = None
        cls._saved_check_state = None
        _overlay.create()
        cls._register_jobs()
        cls.refresh_objects()
        cls.run_all()

    @classmethod
    def stop(cls) -> None:
        cls._running = False
        cls._remove_jobs()
        cls.objects.clear()
        _overlay.clear()

    @classmethod
    def set_check_enabled(cls, key: str, enabled: bool) -> None:
        cls._enabled_checks[key] = enabled
        for mco in cls.objects.values():
            mco.enabled[key] = enabled

    # ── batch operations (single run_all for the whole set) ───────────────────

    @classmethod
    def set_checks(cls, key_to_enabled: Dict[str, bool], run: bool = True) -> None:
        """Apply a whole enable-set at once, then optionally revalidate once.

        Batch buttons (All/None/severity/category) use this so the panel does
        one validation pass instead of N (one per toggled checkbox).
        """
        for key, en in key_to_enabled.items():
            cls._enabled_checks[key] = en
            for mco in cls.objects.values():
                mco.enabled[key] = en
        if run and cls._running:
            cls.run_all()
        cls._notify_ui()

    @classmethod
    def enable_all(cls, enabled: bool) -> None:
        """Toggle every check on/off."""
        cls.set_checks({k: enabled for k in _core.CHECK_TYPES})

    @classmethod
    def enable_by_severity(cls, severities: set) -> None:
        """Enable exactly the checks whose severity is in `severities`."""
        cls.set_checks({
            k: (_core.CHECK_SEVERITIES.get(k) in severities)
            for k in _core.CHECK_TYPES
        })

    @classmethod
    def enable_by_category(cls, category: str, enabled: bool) -> None:
        """Enable or disable every check in one category."""
        keys = _core.CHECK_CATEGORIES.get(category, ())
        cls.set_checks({k: enabled for k in keys})

    @classmethod
    def toggle_category(cls, category: str) -> None:
        """If any check in the category is on -> turn all off; else turn all on.

        Same semantics as Blender's mesh_check.toggle_category operator.
        """
        keys = _core.CHECK_CATEGORIES.get(category, ())
        any_on = any(cls._enabled_checks.get(k, False) for k in keys)
        cls.enable_by_category(category, not any_on)

    # ── isolate (temporarily validate a single check, non-destructive) ────────

    _saved_check_state: Optional[Dict[str, bool]] = None  # None = not isolating

    @classmethod
    def isolate_check(cls, check_key: str) -> None:
        """Validate ONLY check_key, remembering the previous enable-set.

        Calling again (any key) restores the saved set. Active overlay focus is
        left untouched so Show still works for the isolated check.
        """
        if cls._saved_check_state is not None:
            # Already isolating -> restore previous state
            cls.set_checks(cls._saved_check_state)
            cls._saved_check_state = None
        else:
            cls._saved_check_state = dict(cls._enabled_checks)
            cls.set_checks({k: (k == check_key) for k in _core.CHECK_TYPES})

    @classmethod
    def is_isolating(cls) -> bool:
        return cls._saved_check_state is not None

    # ── presets (persist in scene via cmds.fileInfo) ──────────────────────────

    _PRESET_PREFIX = "stukach_preset_"

    @classmethod
    def list_presets(cls) -> List[str]:
        """Return preset names stored in the current scene's fileInfo."""
        info = cmds.fileInfo(query=True) or []
        names = []
        for i in range(0, len(info) - 1, 2):
            key, _val = info[i], info[i + 1]
            if key.startswith(cls._PRESET_PREFIX):
                names.append(key[len(cls._PRESET_PREFIX):])
        return sorted(names)

    @classmethod
    def save_preset(cls, name: str) -> None:
        """Save the current enabled-check set under `name` (overwrites existing)."""
        import json
        payload = json.dumps({k: bool(v) for k, v in cls._enabled_checks.items()})
        cmds.fileInfo(cls._PRESET_PREFIX + name, payload)

    @classmethod
    def load_preset(cls, name: str) -> bool:
        """Load a preset by name. Returns False if not found."""
        import json
        info = cmds.fileInfo(cls._PRESET_PREFIX + name, query=True)
        if not info:
            return False
        # fileInfo escapes quotes when stored (\"), so unescape before JSON parse
        raw = info[0].replace('\\"', '"')
        try:
            state = json.loads(raw)
        except Exception:
            return False
        # Apply to all checks: missing keys default to False
        cls.set_checks({k: bool(state.get(k, False)) for k in _core.CHECK_TYPES})
        return True

    @classmethod
    def delete_preset(cls, name: str) -> None:
        # cmds.fileInfo has no remove flag — use MEL which supports -remove
        import maya.mel as mel
        mel.eval(f'fileInfo -remove "{cls._PRESET_PREFIX}{name}"')

    @classmethod
    def set_active_check(cls, check_key: Optional[str]) -> None:
        """Focus the viewport overlay on a single check (None = overview mode)."""
        cls.active_check = check_key
        _overlay.set_active_check(check_key)
        if cls._running:
            _overlay.update(cls.objects)
            cls._notify_ui()   # so the Show buttons + row highlight update

    @classmethod
    def toggle_active_check(cls, check_key: str) -> None:
        """Click the same check again to leave focus and return to overview."""
        if cls.active_check == check_key:
            cls.set_active_check(None)
        else:
            cls.set_active_check(check_key)

    @classmethod
    def set_scope(cls, scope: str) -> None:
        """Switch between SCENE and SELECTED scope, then re-validate."""
        if scope not in (_SCOPE_SCENE, _SCOPE_SELECTED):
            return
        cls.scope = scope
        if cls._running:
            # Drop manual-only objects so refresh_objects() repopulates cleanly
            cls.objects.clear()
            cls.refresh_objects()
            cls.run_all()

    @classmethod
    def set_overlay_enabled(cls, enabled: bool) -> None:
        _overlay.set_enabled(enabled)

    @classmethod
    def add_object(cls, transform: str) -> None:
        if not cmds.objExists(transform):
            return
        if not _core._get_shape(transform):
            return
        if transform not in cls.objects:
            mco = MayaCheckObject(transform)
            for key, en in cls._enabled_checks.items():
                mco.enabled[key] = en
            cls.objects[transform] = mco

    @classmethod
    def remove_object(cls, transform: str) -> None:
        cls.objects.pop(transform, None)

    @classmethod
    def refresh_objects(cls) -> None:
        """Populate tracked objects based on the current scope."""
        if cls.scope == _SCOPE_SCENE:
            targets = _all_mesh_transforms()
        else:  # SELECTED
            targets = cmds.ls(selection=True, long=True, type='transform') or []
        for t in targets:
            cls.add_object(t)
        # Drop deleted / no-longer-existing objects
        dead = [k for k, v in cls.objects.items() if not v._is_alive()]
        for k in dead:
            del cls.objects[k]

    @classmethod
    def run_all(cls) -> None:
        """Re-run all enabled checkers on all tracked objects."""
        if not cls._running:
            cls._notify_ui()   # still sync category headers etc.
            return
        for mco in list(cls.objects.values()):
            mco.run_enabled()
        # Refresh viewport tinting from the fresh results
        _overlay.update(cls.objects)
        cls._notify_ui()

    @classmethod
    def run_object(cls, transform: str) -> None:
        mco = cls.objects.get(transform)
        if mco:
            mco.run_enabled()
            _overlay.update(cls.objects)
            cls._notify_ui()

    # ── stats ─────────────────────────────────────────────────────────────────

    @classmethod
    def total_blockers(cls) -> int:
        return sum(mco.total_blockers for mco in cls.objects.values())

    @classmethod
    def total_warnings(cls) -> int:
        return sum(mco.total_warnings for mco in cls.objects.values())

    @classmethod
    def asset_status(cls) -> str:
        """Return asset status: 'CRITICAL' | 'WARNING' | 'READY' | 'NONE'.

        Mirrors Blender's _get_asset_status: CRITICAL requires at least one
        BLOCKER with count > 0 across all objects. WARNING requires at least
        one WARNING with count > 0. READY means all enabled checks are clean.
        NONE means nothing has been validated yet.
        """
        if not cls.objects:
            return "NONE"
        b = cls.total_blockers()
        w = cls.total_warnings()
        if b > 0:
            return "CRITICAL"
        if w > 0:
            return "WARNING"
        return "READY"

    @classmethod
    def set_coordinator_mode(cls, enabled: bool) -> None:
        cls.coordinator_mode = enabled
        cls._notify_ui()

    # ── ignore list (Blender parity) ──────────────────────────────────────────

    @classmethod
    def toggle_ignore(cls, transform: str, check_key: str) -> None:
        ignored = get_ignore_list(transform)
        if check_key in ignored:
            ignored.discard(check_key)
        else:
            ignored.add(check_key)
        set_ignore_list(transform, ignored)
        cls.run_all()

    @classmethod
    def clear_ignore_object(cls, transform: str) -> None:
        set_ignore_list(transform, set())
        cls.run_all()

    @classmethod
    def clear_all_ignores(cls) -> None:
        for transform in list(cls.objects.keys()):
            if get_ignore_list(transform):
                set_ignore_list(transform, set())
        cls.run_all()

    @classmethod
    def has_any_ignores(cls) -> bool:
        return any(get_ignore_list(t) for t in cls.objects.keys())

    # ── report export (JSON / CSV / HTML) ─────────────────────────────────────

    @classmethod
    def build_report(cls) -> dict:
        """Build a serializable report dict of current validation results."""
        from datetime import datetime
        scene_name = cmds.file(query=True, sceneName=True) or "untitled"
        report = {
            "tool": "STUKACH Maya",
            "version": _VERSION,
            "scene": scene_name,
            "date": datetime.now().isoformat(timespec="seconds"),
            "scope": cls.scope,
            "summary": {
                "status": cls.asset_status(),
                "objects": len(cls.objects),
                "blockers": cls.total_blockers(),
                "warnings": cls.total_warnings(),
            },
            "objects": [],
        }
        for transform, mco in cls.objects.items():
            short = transform.split("|")[-1]
            obj_entry = {"name": short, "checks": []}
            for key, checker in mco.checkers.items():
                if not mco.enabled.get(key, False):
                    continue
                sev = _core.CHECK_SEVERITIES.get(key, "WARNING")
                if checker.count > 0:
                    obj_entry["checks"].append({
                        "check": key,
                        "severity": sev,
                        "count": checker.count,
                        "detail": checker.metric_text or "",
                    })
            report["objects"].append(obj_entry)
        return report

    @classmethod
    def export_report(cls, path: str, fmt: str = "json") -> bool:
        """Export report to file. fmt: 'json' | 'csv' | 'html'. Returns True on success."""
        import json, csv, os
        report = cls.build_report()
        try:
            if fmt == "json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=2, ensure_ascii=False)
            elif fmt == "csv":
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["object", "check", "severity", "count", "detail"])
                    for obj in report["objects"]:
                        for c in obj["checks"]:
                            w.writerow([obj["name"], c["check"], c["severity"], c["count"], c["detail"]])
            elif fmt == "html":
                cls._write_html_report(path, report)
            else:
                return False
            return True
        except Exception as e:
            alog(f"export error: {e}")
            return False

    @staticmethod
    def _write_html_report(path: str, report: dict) -> None:
        import html as _html
        s = report["summary"]
        status_color = {"CRITICAL": "#e84040", "WARNING": "#e8a040", "READY": "#40c070"}.get(s["status"], "#888")
        rows = ""
        for obj in report["objects"]:
            for c in obj["checks"]:
                sev_color = {"BLOCKER": "#e84040", "WARNING": "#e8a040", "INFO": "#4488cc"}.get(c["severity"], "#888")
                rows += f"<tr><td>{_html.escape(obj['name'])}</td><td>{_html.escape(c['check'])}</td><td style='color:{sev_color}'>{c['severity']}</td><td>{c['count']}</td><td>{_html.escape(c['detail'])}</td></tr>\n"
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>STUKACH Report</title>
<style>body{{font-family:system-ui;background:#1a1a1a;color:#ddd;padding:20px}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #444;padding:6px 10px;text-align:left}}
th{{background:#2a2a2a}}.meta{{margin-bottom:20px}}.status{{font-weight:bold;font-size:18px;color:{status_color}}}
</style></head><body>
<h1>STUKACH Report</h1>
<div class="meta">
<p>Scene: <b>{_html.escape(report['scene'])}</b></p>
<p>Date: {report['date']}</p>
<p>Scope: {report['scope']}</p>
<p>Status: <span class="status">{s['status']}</span> · {s['objects']} obj · {s['blockers']} blockers · {s['warnings']} warnings</p>
</div>
<table><tr><th>Object</th><th>Check</th><th>Severity</th><th>Count</th><th>Detail</th></tr>
{rows}</table></body></html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    # ── publish blocking ─────────────────────────────────────────────────────

    @classmethod
    def preflight_export(cls) -> str:
        """Check asset status before FBX export. Returns 'ok' | 'warning' | 'blocked'.

        Mirrors Blender's preflight_export operator:
          CRITICAL (any BLOCKER > 0) -> 'blocked'  (export must not proceed)
          WARNING  (any WARNING > 0) -> 'warning'  (user decides)
          READY    (all clean)        -> 'ok'       (export freely)
        """
        if not cls.objects or not cls._running:
            return "ok"   # nothing validated — allow export
        status = cls.asset_status()
        if status == "CRITICAL":
            return "blocked"
        if status == "WARNING":
            return "warning"
        return "ok"

    @classmethod
    def publish_fbx(cls, path: str, selection_only: bool = False) -> bool:
        """Run preflight, then export FBX. Returns True if exported."""
        check = cls.preflight_export()
        if check == "blocked":
            alog(f"FBX export BLOCKED — {cls.total_blockers()} blockers found. Fix issues first.")
            return False
        if check == "warning":
            alog(f"FBX export WARNING — {cls.total_warnings()} warnings. Proceeding anyway.")
        try:
            if selection_only:
                cmds.file(path, force=True, type="FBX export", pr=True, es=True)
            else:
                cmds.file(path, force=True, type="FBX export", pr=True, ea=True)
            alog(f"FBX exported: {path}")
            return True
        except Exception as e:
            alog(f"FBX export error: {e}")
            return False

    # ── fix operators ────────────────────────────────────────────────────────

    @classmethod
    def fix_issues(cls, check_key: str, transform: str = None) -> int:
        """Run the appropriate fix for a check on the active (or given) object.

        Returns the number of objects fixed. Supported checks:
          non_applied_transform -> freeze transforms (rotate)
          scale                 -> freeze transforms (scale)
          construction_history  -> delete construction history
          non_manifold          -> polyCleanupArgList (non-manifold)
          mat_suffix            -> rename material to end with _mat
        """
        targets = [transform] if transform else list(cls.objects.keys())
        fixed = 0
        for t in targets:
            if not cmds.objExists(t):
                continue
            try:
                if check_key == "non_applied_transform":
                    cmds.makeIdentity(t, apply=True, rotate=True, translate=False, scale=False, normal=False)
                elif check_key == "scale":
                    cmds.makeIdentity(t, apply=True, rotate=False, translate=False, scale=True, normal=False)
                elif check_key == "construction_history":
                    cmds.delete(t, constructionHistory=True)
                elif check_key == "non_manifold":
                    shapes = cmds.listRelatives(t, shapes=True, type='mesh', fullPath=True) or []
                    for s in shapes:
                        cmds.polyCleanupArgList(s, 4, ["0", "0.0001", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0.0001", "0", "0", "0", "0", "0"])
                elif check_key == "mat_suffix":
                    shapes = cmds.listRelatives(t, shapes=True, type='mesh', fullPath=True) or []
                    for s in shapes:
                        shading_engines = cmds.listConnections(s, type="shadingEngine") or []
                        for sg in shading_engines:
                            surf = cmds.listConnections(sg + ".surfaceShader") or []
                            for mat in surf:
                                if not mat.endswith("_mat"):
                                    cmds.rename(mat, mat + "_mat")
                else:
                    continue
                fixed += 1
            except Exception as e:
                alog(f"fix {check_key} on {t}: {e}")
        return fixed

    @classmethod
    def fix_all_enabled(cls) -> int:
        """Run fix for every enabled check that has a fix, on all tracked objects."""
        fixable = {"non_applied_transform", "scale", "construction_history",
                   "non_manifold", "mat_suffix"}
        total = 0
        for key in fixable:
            if cls._enabled_checks.get(key, False):
                total += cls.fix_issues(key)
        return total

    # ── score data / navigation / clipboard (Blender parity) ──────────────────

    @staticmethod
    def object_issue_counts(mco: MayaCheckObject) -> "tuple[int, int]":
        """(blockers, warnings) for one object, ignored checks excluded."""
        ignored = get_ignore_list(mco.transform)
        b = w = 0
        for key, checker in mco.checkers.items():
            if not mco.enabled.get(key) or key in ignored:
                continue
            if not checker or checker.count == 0:
                continue
            sev = _core.CHECK_SEVERITIES.get(key)
            if sev == "BLOCKER":
                b += checker.count
            elif sev == "WARNING":
                w += checker.count
        return (b, w)

    @classmethod
    def category_summary(cls) -> Dict[str, "tuple[int, int]"]:
        """Per-category (blockers, warnings) across all tracked objects."""
        out = {}
        for cat, keys in _core.CHECK_CATEGORIES.items():
            b = w = 0
            for mco in cls.objects.values():
                ignored = get_ignore_list(mco.transform)
                for k in keys:
                    if not mco.enabled.get(k) or k in ignored:
                        continue
                    checker = mco.checkers.get(k)
                    if not checker or checker.count == 0:
                        continue
                    sev = _core.CHECK_SEVERITIES.get(k)
                    if sev == "BLOCKER":
                        b += checker.count
                    elif sev == "WARNING":
                        w += checker.count
            out[cat] = (b, w)
        return out

    @classmethod
    def problem_objects(cls) -> List[str]:
        """Tracked transforms with issues, worst-first (blockers, warnings)."""
        scored = []
        for t, mco in cls.objects.items():
            b, w = cls.object_issue_counts(mco)
            if b or w:
                scored.append((t, b, w))
        scored.sort(key=lambda item: (-item[1], -item[2], item[0]))
        return [t for t, _b, _w in scored]

    @classmethod
    def next_issue(cls) -> Optional[str]:
        """Cycle to the next problem object: select + frame it. Returns name."""
        probs = cls.problem_objects()
        if not probs:
            return None
        cls._next_issue_ptr = (cls._next_issue_ptr + 1) % len(probs)
        target = probs[cls._next_issue_ptr]
        try:
            cmds.select(target, replace=True)
            cmds.viewFit(target)
        except Exception as e:
            alog("next_issue: %s" % e)
        return target

    # ── validator name (optionVars; empty -> OS login) ───────────────────────

    @classmethod
    def get_validator_name(cls) -> str:
        try:
            name = cmds.optionVar(query="stukachValidatorName") or ""
        except Exception:
            name = ""
        return name or getpass.getuser()

    @classmethod
    def set_validator_name(cls, name: str) -> None:
        try:
            if name:
                cmds.optionVar(sv=("stukachValidatorName", name))
            elif cmds.optionVar(exists="stukachValidatorName"):
                cmds.optionVar(remove="stukachValidatorName")
        except Exception as e:
            alog("set_validator_name: %s" % e)

    # ── clipboard report text (mode-aware, Blender parity) ───────────────────

    @classmethod
    def build_summary_text(cls) -> str:
        from datetime import datetime
        maya_ver = cmds.about(query=True, version=True) or "?"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        sig = ("Validated by: %s | %s | Maya %s | STUKACH Maya v%s"
               % (cls.get_validator_name(), stamp, maya_ver, _VERSION))
        if not cls.objects or not cls._running:
            return "STUKACH Maya v%s — nothing validated yet.\n%s" % (_VERSION, sig)

        b_total, w_total = cls.total_blockers(), cls.total_warnings()
        lines = []
        if cls.coordinator_mode:
            if b_total:
                verdict = "BLOCKED (%d blockers, %d warnings)" % (b_total, w_total)
            elif w_total:
                verdict = "REVIEW (%d warnings)" % w_total
            else:
                verdict = "READY (0 blockers, 0 warnings)"
            lines.append("VALIDATION: %s" % verdict)
            lines.append("Scene: %s | scope: %s | %d objects"
                         % (cmds.file(query=True, sceneName=True) or "untitled",
                            cls.scope, len(cls.objects)))
            if b_total:
                lines.append("")
                lines.append("BLOCKERS (fix first):")
                lines += cls._summary_check_lines("BLOCKER")
            if w_total:
                lines.append("")
                lines.append("WARNINGS:")
                lines += cls._summary_check_lines("WARNING")
        else:
            lines.append("STUKACH Maya v%s — validation summary" % _VERSION)
            lines.append("Scene: %s | scope: %s"
                         % (cmds.file(query=True, sceneName=True) or "untitled",
                            cls.scope))
            lines.append("%d objects | %d blockers | %d warnings"
                         % (len(cls.objects), b_total, w_total))
            if b_total or w_total:
                lines.append("")
                for t in cls.problem_objects()[:10]:
                    mco = cls.objects[t]
                    b, w = cls.object_issue_counts(mco)
                    top = cls._top_check_label(mco)
                    short = t.split("|")[-1]
                    lines.append("%s: %dB/%dW (top: %s)" % (short, b, w, top))
        lines.append("")
        lines.append(sig)
        return "\n".join(lines)

    @classmethod
    def _summary_check_lines(cls, severity: str) -> List[str]:
        """Aggregated 'check: count' lines for one severity, worst-first."""
        agg: Dict[str, int] = {}
        for mco in cls.objects.values():
            ignored = get_ignore_list(mco.transform)
            for key, checker in mco.checkers.items():
                if (not mco.enabled.get(key) or key in ignored
                        or not checker or checker.count == 0):
                    continue
                if _core.CHECK_SEVERITIES.get(key) == severity:
                    agg[key] = agg.get(key, 0) + checker.count
        ordered = sorted(agg.items(), key=lambda kv: -kv[1])
        return ["  %s: %d" % (k, n) for k, n in ordered[:8]]

    @staticmethod
    def _top_check_label(mco: MayaCheckObject) -> str:
        """Name of the worst active check on the object (for the compact list)."""
        best, best_sev = "-", ""
        for key, checker in mco.checkers.items():
            if not mco.enabled.get(key) or not checker or checker.count == 0:
                continue
            sev = _core.CHECK_SEVERITIES.get(key)
            if sev == "BLOCKER":
                best, best_sev = key, "BLOCKER"
                break
            if sev == "WARNING" and best_sev != "BLOCKER":
                best, best_sev = key, sev
        return best

    # ── debug info (bug reports without crash logs) ──────────────────────────

    @classmethod
    def get_debug_info(cls) -> str:
        import platform
        import sys
        active = [k for k, en in cls._enabled_checks.items() if en]
        lines = [
            "STUKACH Maya debug info",
            "  STUKACH: %s" % _VERSION,
            "  Maya: %s" % (cmds.about(query=True, version=True) or "?"),
            "  OS: %s %s" % (platform.system(), platform.release()),
            "  Python: %s" % sys.version.split()[0],
            "  Running: %s | Live: %s | Coordinator: %s"
            % (cls._running, cls.live, cls.coordinator_mode),
            "  Scope: %s | Objects: %d | Blockers: %d | Warnings: %d"
            % (cls.scope, len(cls.objects), cls.total_blockers(),
               cls.total_warnings()),
            "  Isolating: %s" % cls.is_isolating(),
            "  Active checks (%d): %s" % (len(active), ", ".join(active)),
            "  Scene: %s" % (cmds.file(query=True, sceneName=True) or "untitled"),
            "  Log: %s" % _LOG_PATH,
            "  Recent log:",
        ]
        lines += ["    " + l for l in list(_LOG)[-40:]]
        return "\n".join(lines)

    # ── live mode (panel QTimer drives live_tick) ─────────────────────────────

    @classmethod
    def set_live(cls, enabled: bool) -> None:
        cls.live = bool(enabled)
        alog("live mode %s" % ("ON" if cls.live else "OFF"))

    @classmethod
    def live_tick(cls) -> None:
        """One live pass: pick up new/removed objects, revalidate dirty ones.
        Cheap — run_enabled() skips checkers whose data hasn't changed."""
        if not cls._running or not cls.live:
            return
        cls.refresh_objects()
        cls.run_all()

    # ── scriptJob callbacks ───────────────────────────────────────────────────

    @classmethod
    def _register_jobs(cls) -> None:
        cls._remove_jobs()
        cls._job_ids = [
            cmds.scriptJob(event=["SelectionChanged", cls._on_selection_changed]),
            cmds.scriptJob(event=["SceneOpened",      cls._on_scene_changed]),
            cmds.scriptJob(event=["NewSceneOpened",   cls._on_scene_changed]),
        ]

    @classmethod
    def _remove_jobs(cls) -> None:
        for jid in cls._job_ids:
            try:
                if cmds.scriptJob(exists=jid):
                    cmds.scriptJob(kill=jid, force=True)
            except Exception:
                pass
        cls._job_ids = []

    @classmethod
    def _on_selection_changed(cls) -> None:
        if not cls._running:
            return
        # Only SELECTED scope reacts to the active selection changing — SCENE
        # scope already covers everything and would just churn on every pick.
        if cls.scope == _SCOPE_SELECTED:
            cls.refresh_objects()
            cls.run_all()

    @classmethod
    def _on_scene_changed(cls) -> None:
        cls.objects.clear()
        cls._notify_ui()

    @classmethod
    def _notify_ui(cls) -> None:
        if cls._ui_callback:
            try:
                cls._ui_callback()
            except Exception as e:
                alog(f"UI callback error: {e}")
