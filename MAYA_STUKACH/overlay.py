# -*- coding: utf-8 -*-
"""
STUKACH for Maya — viewport overlay.

Two complementary modes, mirroring Blender STUKACH:

  1. SINGLE-CHECK overlay (the informative one)
     The user picks ONE check in the panel (click the check row). Every bad
     component of that check is painted red on the mesh via per-face vertex
     colours (MFnMesh.setFaceColor), the rest of the mesh goes dark grey. This
     is the equivalent of Blender's per-check GPU face fill — you see exactly
     which polygons/edges/verts are wrong, not just "this object has problems".

  2. OVERVIEW overlay (quick "where are the problems")
     No check in focus. Each tracked object is moved into a coloured display
     layer: red if it has any BLOCKER, yellow if only WARNINGs. Use it to spot
     the worst objects at a glance; then click a check to drill down.

Why vertex colours and not a real GPU overlay: Maya has no pure-Python
draw_handler_add (that needs a C++ MPxDrawOverride plugin). Per-face vertex
colour is the standard Maya idiom for per-face viewport feedback — robust,
visible in shaded AND wireframe-on-shaded, and leaves the original asset intact
(we back up any existing colour set / displayColors and restore on stop).

Bad components come from the checkers as strings like "mesh.f[12]",
"mesh.e[3]", "mesh.vtx[7]". For overlay we always resolve them to the faces
that should be tinted: face -> itself, edge -> its connected faces,
vertex -> all faces touching it.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set

import maya.cmds as cmds
import maya.api.OpenMaya as om

# Display layers for the overview mode
LAYER_BLOCKERS = "STUKACH_BLOCKERS"
LAYER_WARNINGS = "STUKACH_WARNINGS"

_COLOR_BLOCKERS = (0.85, 0.30, 0.30)   # red
_COLOR_WARNINGS = (0.85, 0.65, 0.30)   # yellow

_DEFAULT_LAYER = "defaultLayer"

# Vertex colours for the single-check face overlay
_OVERLAY_COLOR_SET = "stukach_overlay"
_CLR_BASELINE = om.MColor([0.05, 0.05, 0.05, 1.0])   # near-black for clean faces
_CLR_BAD = om.MColor([1.0, 0.15, 0.15, 1.0])         # bright red for bad faces

# Component string patterns -> ("f"|"e"|"vtx", index)
_FACE_RE = re.compile(r"\.f\[(\d+)\]")
_EDGE_RE = re.compile(r"\.e\[(\d+)\]")
_VTX_RE = re.compile(r"\.vtx\[(\d+)\]")

# Module state
_enabled: bool = True
_active_check: Optional[str] = None   # key of the check currently in focus

# Backups so we leave the asset exactly as we found it on stop():
#   { shape_full_path: (list_of_existing_colorsets, displayColors_before_bool) }
_color_backup: Dict[str, tuple] = {}


# ── VP2 DrawOverride support (C++ companion plugin) ───────────────────────────

_LOCATOR_PREFIX = "stukach_loc_"
_plugin_cache: Optional[bool] = None  # cached plugin-loaded check

# Per-check overlay colors from Blender preferences (identity palette)
_CHECK_OVERLAY_COLORS = {
    "triangles": "#B2B205", "ngons": "#B20505", "non_manifold": "#05FF05",
    "zero_area": "#FF00FF", "poles": "#4066FF", "isolated_verts": "#FFFF00",
    "boundary_edges": "#FF8000", "duplicate_verts": "#FF9900",
    "face_aspect_ratio": "#FFD900", "z_fighting": "#FF0000",
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


def _hex_to_rgb(hex_str: str) -> tuple:
    """Convert '#RRGGBB' to (r, g, b) floats 0..1."""
    h = hex_str.lstrip('#')
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


# User color overrides (set via UI swatch clicks)
_color_overrides: Dict[str, str] = {}  # check_key -> "#RRGGBB"

def set_check_color(check_key: str, hex_color: str) -> None:
    """Set a user override color for a check's viewport overlay."""
    _color_overrides[check_key] = hex_color

def _get_check_color(check_key: str) -> tuple:
    """Get RGB for a check — override first, then Blender defaults."""
    hex_c = _color_overrides.get(check_key) or _CHECK_OVERLAY_COLORS.get(check_key, "#FF0000")
    return _hex_to_rgb(hex_c)


def _vp2_available() -> bool:
    """Check if the C++ stukachDrawOverride plugin is loaded (cached)."""
    global _plugin_cache
    if _plugin_cache is not None:
        return _plugin_cache
    try:
        _plugin_cache = cmds.pluginInfo("stukachDrawOverride.mll", query=True, loaded=True)
    except Exception:
        _plugin_cache = False
    return _plugin_cache


def _ensure_locator(transform: str) -> Optional[str]:
    """Find or create a stukachLocator node connected to this transform's mesh."""
    loc_name = _LOCATOR_PREFIX + transform.split("|")[-1].replace(":", "_")
    if cmds.objExists(loc_name):
        return loc_name

    shape = cmds.listRelatives(transform, shapes=True, type="mesh", fullPath=True)
    if not shape:
        return None
    shape = shape[0]

    try:
        loc = cmds.createNode("stukachLocator", name=loc_name)
        cmds.connectAttr("%s.worldMesh[0]" % shape, "%s.inputMesh" % loc)
        return loc
    except Exception as e:
        print("[STUKACH] VP2 locator create error: %s" % e)
        return None


def _serialize_ids(components: List[str], id_type: str) -> str:
    """Extract indices from component strings: 'mesh.f[5]' -> '5'."""
    pattern = {"f": _FACE_RE, "e": _EDGE_RE, "vtx": _VTX_RE}.get(id_type)
    if not pattern:
        return ""
    ids = []
    for comp in components:
        m = pattern.search(comp)
        if m:
            ids.append(m.group(1))
    return ",".join(ids)


def _vp2_update(objects: Dict[str, object], active_check: Optional[str] = None) -> None:
    """Update stukachLocator nodes with bad component data for VP2 drawing."""
    # Clean up locators for objects no longer tracked
    tracked = set(objects.keys())
    for loc in (cmds.ls("stukach_loc_*", type="stukachLocator") or []):
        # Find which transform this locator is for
        connected = cmds.listConnections(loc + ".inputMesh", source=True, destination=False) or []
        if connected:
            parent = cmds.listRelatives(connected[0], parent=True, fullPath=True) or []
            if parent and parent[0] not in tracked:
                cmds.delete(loc)
        else:
            cmds.delete(loc)

    for transform, mco in objects.items():
        if not cmds.objExists(transform):
            continue

        loc = _ensure_locator(transform)
        if not loc or not cmds.objExists(loc):
            continue   # locator died with a scene change between passes

        # Gather bad components
        all_faces = []
        all_edges = []
        all_verts = []

        if active_check:
            checker = mco.checkers.get(active_check)
            if checker and checker.count > 0:
                for comp in checker.bad_components:
                    if ".f[" in comp:
                        all_faces.append(comp)
                    elif ".e[" in comp:
                        all_edges.append(comp)
                    elif ".vtx[" in comp:
                        all_verts.append(comp)
        else:
            for key, checker in mco.checkers.items():
                if not mco.enabled.get(key, False) or checker.count == 0:
                    continue
                for comp in checker.bad_components:
                    if ".f[" in comp:
                        all_faces.append(comp)
                    elif ".e[" in comp:
                        all_edges.append(comp)
                    elif ".vtx[" in comp:
                        all_verts.append(comp)

        # Serialize and set (locator may be deleted by a scene change mid-pass)
        if not cmds.objExists(loc):
            continue
        cmds.setAttr(loc + ".badFaces", _serialize_ids(all_faces, "f"), type="string")
        cmds.setAttr(loc + ".badEdges", _serialize_ids(all_edges, "e"), type="string")
        cmds.setAttr(loc + ".badVerts", _serialize_ids(all_verts, "vtx"), type="string")
        cmds.setAttr(loc + ".drawEnabled", True)
        cmds.setAttr(loc + ".drawMode", 1 if active_check else 0)

        # Object-level issues (transform checks etc.) report count > 0 with no
        # bad components — draw a bounding-box wireframe around the object.
        has_object_issue = False
        if active_check:
            c = mco.checkers.get(active_check)
            has_object_issue = bool(c and c.count > 0 and not c.bad_components)
        else:
            has_object_issue = any(
                mco.enabled.get(k, False) and c.count > 0 and not c.bad_components
                for k, c in mco.checkers.items()
            )

        if has_object_issue:
            try:
                bb = cmds.exactWorldBoundingBox(transform)
                (mnx, mny, mnz, mxx, mxy, mxz) = bb
                cmds.setAttr(loc + ".bboxMinX", float(mnx))
                cmds.setAttr(loc + ".bboxMinY", float(mny))
                cmds.setAttr(loc + ".bboxMinZ", float(mnz))
                cmds.setAttr(loc + ".bboxMaxX", float(mxx))
                cmds.setAttr(loc + ".bboxMaxY", float(mxy))
                cmds.setAttr(loc + ".bboxMaxZ", float(mxz))
                cmds.setAttr(loc + ".drawBBox", True)
            except Exception:
                cmds.setAttr(loc + ".drawBBox", False)
        else:
            cmds.setAttr(loc + ".drawBBox", False)

        # Trigger VP2 redraw (isAlwaysDirty=false — explicit dirty).
        # Deferred calls fire AFTER the caller returns — possibly after a
        # scene change deleted the locator: guard against dead names.
        try:
            cmds.evalDeferred(
                lambda l=loc: cmds.setAttr(l + ".drawEnabled", True)
                if cmds.objExists(l) else None)
        except Exception:
            pass

        # Per-check color (user override → Blender default → severity)
        r, g, b = _locator_color(mco, active_check)
        cmds.setAttr(loc + ".faceColorR", r)
        cmds.setAttr(loc + ".faceColorG", g)
        cmds.setAttr(loc + ".faceColorB", b)


def _locator_color(mco, active_check: Optional[str]) -> tuple:
    """Resolve overlay color for one object: user override → Blender default → severity."""
    if active_check:
        return _get_check_color(active_check)
    from . import core as _core
    active_checks_with_issues = [
        k for k, c in mco.checkers.items()
        if mco.enabled.get(k) and c.count > 0
    ]
    if len(active_checks_with_issues) == 1:
        return _get_check_color(active_checks_with_issues[0])
    has_blocker = any(
        _core.CHECK_SEVERITIES.get(k) == "BLOCKER"
        for k in active_checks_with_issues
    )
    return _SEVERITY_COLORS["BLOCKER"] if has_blocker else _SEVERITY_COLORS["WARNING"]


def refresh_colors(objects: Dict[str, object], active_check: Optional[str] = None) -> None:
    """Live color refresh: re-apply locator colors and force VP2 to redraw.

    Called from the UI when the user changes a check color swatch.
    MRenderer.setGeometryDrawDirty() marks each locator dirty so VP2 re-runs
    prepareForDraw immediately — no need to wait for the next run_all().
    """
    if not _vp2_available():
        return
    from maya.api import OpenMayaRender as omr
    for transform, mco in objects.items():
        if not cmds.objExists(transform):
            continue
        loc = _ensure_locator(transform)
        if not loc:
            continue
        r, g, b = _locator_color(mco, active_check or _active_check)
        cmds.setAttr(loc + ".faceColorR", r)
        cmds.setAttr(loc + ".faceColorG", g)
        cmds.setAttr(loc + ".faceColorB", b)
        try:
            sel = om.MSelectionList()
            sel.add(loc)
            omr.MRenderer.setGeometryDrawDirty(sel.getDependNode(0), False)
        except Exception:
            pass


def _vp2_clear() -> None:
    """Remove all stukachLocator nodes."""
    for loc in (cmds.ls("stukach_loc_*", type="stukachLocator") or []):
        try:
            cmds.delete(loc)
        except Exception:
            pass


# Per-check colors (severity-based, like Blender's CHECK_SEVERITY colors)
_SEVERITY_COLORS = {
    "BLOCKER": (1.0, 0.15, 0.15),    # red
    "WARNING": (0.85, 0.65, 0.30),    # yellow-orange
    "INFO":    (0.30, 0.50, 0.85),    # blue
}


def _check_color(check_key: str) -> tuple:
    """Return RGB color for a check based on its severity."""
    from . import core as _core
    sev = _core.CHECK_SEVERITIES.get(check_key, "WARNING")
    return _SEVERITY_COLORS.get(sev, (1.0, 0.15, 0.15))


# ── lifecycle ─────────────────────────────────────────────────────────────────

def create() -> None:
    """Create the overview display layers if missing. Skip when VP2 is available."""
    if _vp2_available():
        return  # VP2 handles all rendering — no display layers needed
    _ensure_layer(LAYER_BLOCKERS, _COLOR_BLOCKERS)
    _ensure_layer(LAYER_WARNINGS, _COLOR_WARNINGS)


def clear() -> None:
    """Tear everything down: restore vertex colours, delete layers, remove VP2 locators."""
    restore_colors()
    _vp2_clear()
    for name in (LAYER_BLOCKERS, LAYER_WARNINGS):
        if cmds.objExists(name):
            try:
                cmds.delete(name)
            except Exception:
                pass
    _restore_viewport_material()
    global _active_check
    _active_check = None


def set_enabled(enabled: bool) -> None:
    global _enabled
    _enabled = enabled
    if not enabled:
        restore_colors()
        _vp2_clear()
        _return_layers_to_default()
        _restore_viewport_material()


def set_active_check(check_key: Optional[str]) -> None:
    """Focus the overlay on a single check (None = overview mode)."""
    global _active_check
    _active_check = check_key
    # VP2 handles its own rendering — no viewport material changes needed
    if not _vp2_available():
        if check_key is not None:
            _disable_viewport_default_material()
        else:
            _restore_viewport_material()


# ── update (driven by MayaCheck.run_all) ──────────────────────────────────────

def update(objects: Dict[str, object]) -> None:
    """Repaint the viewport based on current results + active check.

    Uses VP2 DrawOverride (C++ plugin) when available for high-quality
    per-face triangle/line/point rendering. Falls back to display layers
    + per-face vertex colours when the plugin is not installed.
    """
    if not _enabled:
        return

    if _vp2_available():
        # VP2 path: update stukachLocator nodes, let C++ draw override render
        _vp2_update(objects, _active_check)
        # Clear legacy overlay if switching from fallback mode
        if _color_backup:
            restore_colors()
            _return_layers_to_default()
        return

    # Fallback: display layers + vertex colours
    if _active_check is not None:
        _paint_single_check(objects, _active_check)
        _return_layers_to_default()
    else:
        restore_colors()
        _paint_overview(objects)


# ── overview mode (display layers) ────────────────────────────────────────────

def _paint_overview(objects: Dict[str, object]) -> None:
    if not cmds.objExists(LAYER_BLOCKERS):
        create()
    blockers: List[str] = []
    warnings: List[str] = []
    for transform, mco in objects.items():
        if not cmds.objExists(transform):
            continue
        b = getattr(mco, "total_blockers", 0)
        w = getattr(mco, "total_warnings", 0)
        if b > 0:
            blockers.append(transform)
        elif w > 0:
            warnings.append(transform)
    _assign_layer(LAYER_BLOCKERS, blockers)
    _assign_layer(LAYER_WARNINGS, warnings)
    # Everything else (clean, or INFO-only) stays in the default layer already.


# ── single-check mode (per-face vertex colour) ────────────────────────────────

def _paint_single_check(objects: Dict[str, object], check_key: str) -> None:
    bad_components: List[str] = []
    # Gather the check's bad components across all tracked objects that have
    # the check enabled. (If the user disabled a check we don't paint it.)
    for transform, mco in objects.items():
        if not cmds.objExists(transform):
            continue
        if not mco.enabled.get(check_key, False):
            continue
        checker = mco.checkers.get(check_key)
        if checker is None:
            continue
        bad_components.extend(checker.bad_components)

    if not bad_components:
        restore_colors()
        return

    # Group bad components by shape
    shape_to_faces: Dict[str, Set[int]] = {}
    for comp in bad_components:
        shape, faces = _component_to_faces(comp)
        if shape is None:
            continue
        shape_to_faces.setdefault(shape, set()).update(faces)

    # Backup existing colour state once per shape, then paint
    for shape, bad_face_set in shape_to_faces.items():
        _backup_color_state(shape)
        _paint_shape_faces(shape, bad_face_set)

    # Restore/clear any shape we previously painted but no longer touch
    _cleanup_unpainted_shapes(set(shape_to_faces.keys()))


def _component_to_faces(comp: str) -> tuple:
    """Resolve a component string to (shape_full_path, set_of_face_indices).

    f[n] -> {n}; e[n] -> faces connected to edge n; vtx[n] -> all incident faces.
    Component strings look like "|frame|frameShape.e[2084]" — the part before
    '.' is already a shape node, so we resolve it directly rather than extending.
    """
    fm = _FACE_RE.search(comp)
    em = _EDGE_RE.search(comp)
    vm = _VTX_RE.search(comp)

    shape = comp.split(".")[0]
    try:
        sel = om.MSelectionList()
        sel.add(shape)
        dag = sel.getDagPath(0)
        # The node may be a transform (needs extendToShape) or already a shape.
        if cmds.nodeType(dag.fullPathName()) != "mesh":
            dag.extendToShape()
    except Exception:
        return (None, set())
    shape = dag.fullPathName()

    try:
        if fm:
            return (shape, {int(fm.group(1))})
        if em:
            edge_idx = int(em.group(1))
            it = om.MItMeshEdge(dag)
            it.setIndex(edge_idx)
            # API 2.0: getConnectedFaces() returns the array directly
            face_ids = it.getConnectedFaces()
            return (shape, {int(fid) for fid in face_ids})
        if vm:
            vtx_idx = int(vm.group(1))
            it = om.MItMeshVertex(dag)
            it.setIndex(vtx_idx)
            face_ids = it.getConnectedFaces()
            return (shape, {int(fid) for fid in face_ids})
    except Exception:
        pass
    return (None, set())


def _backup_color_state(shape: str) -> None:
    """Remember existing colour sets + displayColors so we can restore later."""
    if shape in _color_backup:
        return
    try:
        existing = cmds.polyColorSet(shape, query=True, allColorSets=True) or []
        disp = cmds.getAttr(f"{shape}.displayColors")
    except Exception:
        existing, disp = [], False
    _color_backup[shape] = (list(existing), bool(disp))


def _paint_shape_faces(shape: str, bad_faces: Set[int]) -> None:
    """Paint bad_faces red and the rest dark grey on a single shape.

    Single batched API call per mesh (not a per-face loop) — the per-face loop
    froze Maya for tens of seconds on large assets. We build parallel arrays of
    faceId/vertexId/colour for every face-vertex pair and hand them to
    MFnMesh.setFaceVertexColors in one shot.
    """
    try:
        sel = om.MSelectionList()
        sel.add(shape)
        dag = sel.getDagPath(0)
        dag.extendToShape()
    except Exception:
        return

    fn = om.MFnMesh(dag)

    # Create / switch to our overlay colour set. polyColorSet is idempotent.
    try:
        existing = cmds.polyColorSet(shape, query=True, allColorSets=True) or []
    except Exception:
        existing = []
    if _OVERLAY_COLOR_SET not in existing:
        cmds.polyColorSet(shape, create=True, clamped=True,
                          representation='RGBA', colorSet=_OVERLAY_COLOR_SET)
    cmds.polyColorSet(shape, currentColorSet=True, colorSet=_OVERLAY_COLOR_SET)

    # Build flat faceId / vertexId / colour arrays for every face-vertex pair.
    # Baseline (dark grey) by default; bad faces overridden to red.
    face_ids = om.MIntArray()
    vert_ids = om.MIntArray()
    colors = om.MColorArray()
    it = om.MItMeshPolygon(dag)
    while not it.isDone():
        fi = int(it.index())
        verts = it.getVertices()              # MIntArray of this face's vert ids
        is_bad = fi in bad_faces
        clr = _CLR_BAD if is_bad else _CLR_BASELINE
        for vi in verts:
            face_ids.append(fi)
            vert_ids.append(int(vi))
            colors.append(clr)
        it.next()

    if face_ids:
        fn.setFaceVertexColors(colors, face_ids, vert_ids)
    cmds.setAttr(f"{shape}.displayColors", 1)


def _cleanup_unpainted_shapes(current_shapes: Set[str]) -> None:
    """If the active check no longer touches a shape we painted before, restore it."""
    stale = [s for s in _color_backup if s not in current_shapes]
    for s in stale:
        _restore_one_shape(s)


# ── restore / teardown ────────────────────────────────────────────────────────

def restore_colors() -> None:
    """Remove the overlay colour set from every shape we touched."""
    for shape in list(_color_backup.keys()):
        _restore_one_shape(shape)


def _restore_one_shape(shape: str) -> None:
    backup = _color_backup.pop(shape, None)
    if backup is None or not cmds.objExists(shape):
        _color_backup.pop(shape, None)
        return
    existing_before, disp_before = backup
    try:
        current = cmds.polyColorSet(shape, query=True, allColorSets=True) or []
        if _OVERLAY_COLOR_SET in current:
            cmds.polyColorSet(shape, delete=True, colorSet=_OVERLAY_COLOR_SET)
        cmds.setAttr(f"{shape}.displayColors", disp_before)
    except Exception:
        pass


# ── display-layer helpers ─────────────────────────────────────────────────────

def _ensure_layer(name: str, rgb: tuple) -> None:
    if cmds.objExists(name):
        return
    cmds.createDisplayLayer(name=name, empty=True)
    cmds.setAttr(f"{name}.overrideRGBColors", 1)
    cmds.setAttr(f"{name}.overrideColorRGB", rgb[0], rgb[1], rgb[2], type="double3")


def _assign_layer(layer: str, transforms: Iterable[str]) -> None:
    members = [t for t in transforms if cmds.objExists(t)]
    if not members:
        return
    try:
        cmds.editDisplayLayerMembers(layer, *members, noRecurse=True)
    except Exception as e:
        print(f"[STUKACH] overlay assign error ({layer}): {e}")


def _return_layers_to_default() -> None:
    for name in (LAYER_BLOCKERS, LAYER_WARNINGS):
        if not cmds.objExists(name):
            continue
        try:
            members = cmds.editDisplayLayerMembers(name, q=True, fn=True) or []
        except Exception:
            members = []
        if members:
            try:
                cmds.editDisplayLayerMembers(_DEFAULT_LAYER, *members, noRecurse=True)
            except Exception:
                pass


# ── viewport material helpers ─────────────────────────────────────────────────
#
# Vertex colours are invisible when "Use Default Material" is active in the
# viewport (Maya replaces all shading with lambert1, suppressing per-vertex
# colour display). We auto-disable it when painting, restore on exit.

_viewport_backup: Dict[str, bool] = {}   # panel_name -> useDefaultMaterial before

import atexit
atexit.register(lambda: _restore_viewport_material())


def _get_model_panels() -> list:
    """Return all visible model panels."""
    return cmds.getPanel(type="modelPanel") or []


def _disable_viewport_default_material() -> None:
    for panel in _get_model_panels():
        try:
            current = cmds.modelEditor(panel, query=True, useDefaultMaterial=True)
            if panel not in _viewport_backup:
                _viewport_backup[panel] = current
            if current:
                cmds.modelEditor(panel, edit=True, useDefaultMaterial=False)
        except Exception:
            pass


def _restore_viewport_material() -> None:
    for panel, was_enabled in _viewport_backup.items():
        try:
            if was_enabled:
                cmds.modelEditor(panel, edit=True, useDefaultMaterial=True)
        except Exception:
            pass
    _viewport_backup.clear()
