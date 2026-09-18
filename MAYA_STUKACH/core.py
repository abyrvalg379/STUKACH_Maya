# -*- coding: utf-8 -*-
"""
STUKACH for Maya — checker classes.

All checkers follow the same interface:
    checker.run(dag_path)   -> populates _count and _bad_components
    checker.count           -> int
    checker.bad_components  -> list of component strings ("mesh.f[0]", etc.)
    checker.select()        -> selects bad components in viewport
    checker.metric_text     -> optional extra info string
"""
from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from typing import List, Optional

import maya.cmds as cmds
import maya.api.OpenMaya as om


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_dag_path(node: str) -> om.MDagPath:
    sel = om.MSelectionList()
    sel.add(node)
    return sel.getDagPath(0)


def _get_shape(transform: str) -> Optional[str]:
    shapes = cmds.listRelatives(transform, shapes=True, type='mesh', fullPath=True) or []
    return shapes[0] if shapes else None


# ─── base ─────────────────────────────────────────────────────────────────────

class BaseCheck(ABC):
    severity: str = "WARNING"   # "BLOCKER" | "WARNING" | "INFO"

    def __init__(self):
        self._count: int = 0
        self._bad_components: List[str] = []
        self.metric_text: str = ""
        self._ran: bool = False   # True after first successful run()

    @property
    def count(self) -> int:
        return self._count

    @property
    def bad_components(self) -> List[str]:
        return self._bad_components

    @abstractmethod
    def run(self, dag_path: om.MDagPath) -> None:
        pass

    def select(self) -> None:
        if self._bad_components:
            cmds.select(self._bad_components, replace=True)
        else:
            cmds.select(clear=True)

    def reset(self) -> None:
        self._count = 0
        self._bad_components = []
        self.metric_text = ""
        self._ran = False


# ─── TOPOLOGY ─────────────────────────────────────────────────────────────────

def _shape_dag(dag_path: om.MDagPath) -> om.MDagPath:
    """Return a copy of dag_path extended to the mesh shape node."""
    dag = om.MDagPath(dag_path)
    dag.extendToShape()
    return dag


def _get_mesh_fn(dag_path: om.MDagPath) -> om.MFnMesh:
    """Return MFnMesh for dag_path (works with transform or shape)."""
    return om.MFnMesh(_shape_dag(dag_path))


class Triangles(BaseCheck):
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        it = om.MItMeshPolygon(sdp)
        bad = []
        while not it.isDone():
            if it.polygonVertexCount() == 3:
                bad.append(f"{shape}.f[{it.index()}]")
            it.next()
        self._count = len(bad)
        self._bad_components = bad


class Ngons(BaseCheck):
    severity = "BLOCKER"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        it = om.MItMeshPolygon(sdp)
        bad = []
        while not it.isDone():
            if it.polygonVertexCount() > 4:
                bad.append(f"{shape}.f[{it.index()}]")
            it.next()
        self._count = len(bad)
        self._bad_components = bad


def _find_isolated_verts(sdp: om.MDagPath, shape: str) -> List[str]:
    """Return list of vtx[n] component strings for vertices with 0 connected edges."""
    bad = []
    it = om.MItMeshVertex(sdp)
    while not it.isDone():
        if it.numConnectedEdges() == 0:
            bad.append(f"{shape}.vtx[{it.index()}]")
        it.next()
    return bad


class NonManifold(BaseCheck):
    severity = "BLOCKER"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()

        bad_edges = []
        bad_faces = []
        bad_verts = []

        # 1) Non-manifold edges: shared by more than 2 faces
        it_edge = om.MItMeshEdge(sdp)
        while not it_edge.isDone():
            if len(it_edge.getConnectedFaces()) > 2:
                bad_edges.append(f"{shape}.e[{it_edge.index()}]")
            it_edge.next()

        # 2) Non-contiguous vertex fans: a vertex where connected faces
        #    don't form a single continuous fan around it.  This catches
        #    the classic "two mesh islands sharing one vertex" topology
        #    that Blender's Select Non-Manifold reports but our edge-only
        #    check misses.
        #
        #    Algorithm: for each vertex with >0 faces, walk the face fan
        #    by following edges that connect to the vertex.  If the walk
        #    visits fewer faces than the vertex has, the fan is split.
        it_vtx = om.MItMeshVertex(sdp)
        while not it_vtx.isDone():
            n_faces = it_vtx.numConnectedFaces()
            n_edges = it_vtx.numConnectedEdges()
            if n_faces > 1 and n_edges > 1:
                # Get all faces connected to this vertex
                connected_faces = it_vtx.getConnectedFaces()
                # Get all edges connected to this vertex
                connected_edges = it_vtx.getConnectedEdges()

                # Build adjacency: for each face, which other faces share
                # an edge that touches this vertex?
                face_to_faces = {}  # face_id -> set of adjacent face_ids
                for fi in connected_faces:
                    face_to_faces[fi] = set()

                for ei in connected_edges:
                    edge_it = om.MItMeshEdge(sdp)
                    edge_it.setIndex(ei)
                    edge_faces = edge_it.getConnectedFaces()
                    # Only consider faces that are also connected to our vertex
                    edge_faces_vtx = [f for f in edge_faces if f in face_to_faces]
                    for i in range(len(edge_faces_vtx)):
                        for j in range(i + 1, len(edge_faces_vtx)):
                            face_to_faces[edge_faces_vtx[i]].add(edge_faces_vtx[j])
                            face_to_faces[edge_faces_vtx[j]].add(edge_faces_vtx[i])

                # BFS from the first face
                visited = set()
                queue = [connected_faces[0]]
                visited.add(connected_faces[0])
                while queue:
                    current = queue.pop(0)
                    for neighbor in face_to_faces.get(current, set()):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)

                if len(visited) < n_faces:
                    bad_verts.append(f"{shape}.vtx[{it_vtx.index()}]")
            it_vtx.next()

        # 3) Lamina faces: two faces occupying the exact same space
        #    (duplicate/overlapping faces).  Created when an internal polygon
        #    is built between existing edges in Blender and imported.
        #    Maya's polyInfo detects these natively.
        try:
            lamina = cmds.polyInfo(mesh.fullPathName(), laminaFaces=True) or []
            for entry in lamina:
                import re as _re
                for m in _re.finditer(r'(\d+)', entry):
                    bad_faces.append(f"{shape}.f[{m.group(1)}]")
        except Exception:
            pass

        # 4) Isolated vertices (0 connected edges)
        bad_verts.extend(_find_isolated_verts(sdp, shape))
        # deduplicate
        bad_verts = list(dict.fromkeys(bad_verts))

        self._bad_components = bad_edges + bad_faces + bad_verts
        self._count = len(bad_edges) + len(bad_faces) + len(bad_verts)
        parts = []
        if bad_edges:
            parts.append(f"{len(bad_edges)} edges")
        if bad_faces:
            parts.append(f"{len(bad_faces)} lamina")
        if bad_verts:
            parts.append(f"{len(bad_verts)} verts")
        if parts:
            self.metric_text = " + ".join(parts)


class ZeroArea(BaseCheck):
    severity = "BLOCKER"
    _THRESHOLD = 1e-10

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        it = om.MItMeshPolygon(sdp)
        bad = []
        while not it.isDone():
            if it.getArea() < self._THRESHOLD:
                bad.append(f"{shape}.f[{it.index()}]")
            it.next()
        self._count = len(bad)
        self._bad_components = bad


class Poles(BaseCheck):
    """N-poles (3 edges) and E-poles (5+ edges)."""
    severity = "INFO"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        it = om.MItMeshVertex(sdp)
        n_poles = e_poles = more_poles = 0
        bad = []
        while not it.isDone():
            ne = it.numConnectedEdges()
            if ne == 3:
                n_poles += 1
                bad.append(f"{shape}.vtx[{it.index()}]")
            elif ne == 5:
                e_poles += 1
                bad.append(f"{shape}.vtx[{it.index()}]")
            elif ne > 5:
                more_poles += 1
                bad.append(f"{shape}.vtx[{it.index()}]")
            it.next()
        self._count = len(bad)
        self._bad_components = bad
        parts = []
        if n_poles:   parts.append(f"{n_poles}N")
        if e_poles:   parts.append(f"{e_poles}E")
        if more_poles: parts.append(f"{more_poles}+")
        self.metric_text = " ".join(parts)


class IsolatedVerts(BaseCheck):
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        shape = om.MFnMesh(sdp).fullPathName()
        bad = _find_isolated_verts(sdp, shape)
        self._count = len(bad)
        self._bad_components = bad


class BoundaryEdges(BaseCheck):
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        it = om.MItMeshEdge(sdp)
        bad = []
        while not it.isDone():
            if len(it.getConnectedFaces()) == 1:
                bad.append(f"{shape}.e[{it.index()}]")
            it.next()
        self._count = len(bad)
        self._bad_components = bad


# ─── TRANSFORMS ───────────────────────────────────────────────────────────────
# Transform-level checks report object-level issues (count > 0 with empty
# bad_components). The VP2 overlay draws a bounding-box wireframe for such
# objects — see overlay._vp2_update().

class NonAppliedTransform(BaseCheck):
    """Rotation not zeroed (Maya equivalent: freeze transforms)."""
    severity = "BLOCKER"
    _THRESHOLD = 1e-4

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        node = dag_path.fullPathName()
        rx = cmds.getAttr(f"{node}.rotateX")
        ry = cmds.getAttr(f"{node}.rotateY")
        rz = cmds.getAttr(f"{node}.rotateZ")
        if abs(rx) > self._THRESHOLD or abs(ry) > self._THRESHOLD or abs(rz) > self._THRESHOLD:
            self._count = 1
            self.metric_text = f"R({rx:.2f}, {ry:.2f}, {rz:.2f})"


class NonAppliedScale(BaseCheck):
    """Scale not (1,1,1)."""
    severity = "BLOCKER"
    _THRESHOLD = 0.001

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        node = dag_path.fullPathName()
        sx = cmds.getAttr(f"{node}.scaleX")
        sy = cmds.getAttr(f"{node}.scaleY")
        sz = cmds.getAttr(f"{node}.scaleZ")
        if (abs(sx - 1.0) > self._THRESHOLD or
                abs(sy - 1.0) > self._THRESHOLD or
                abs(sz - 1.0) > self._THRESHOLD):
            self._count = 1
            self.metric_text = f"S({sx:.3f}, {sy:.3f}, {sz:.3f})"


class ConstructionHistory(BaseCheck):
    """Object has construction history (Maya equivalent of modifier stack)."""
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        node = dag_path.fullPathName()
        history = cmds.listHistory(node, pruneDagObjects=True) or []
        # Filter out obvious noise (groupId, tweak, etc.)
        ignored = {'groupId', 'tweak', 'groupParts', 'shadingEngine'}
        real = [h for h in history if cmds.nodeType(h) not in ignored]
        self._count = len(real)
        if real:
            self.metric_text = f"History: {len(real)} nodes"


class OriginAtZero(BaseCheck):
    """Object pivot is not at world origin."""
    severity = "INFO"
    _THRESHOLD = 0.001

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        node = dag_path.fullPathName()
        tx = cmds.getAttr(f"{node}.translateX")
        ty = cmds.getAttr(f"{node}.translateY")
        tz = cmds.getAttr(f"{node}.translateZ")
        if abs(tx) > self._THRESHOLD or abs(ty) > self._THRESHOLD or abs(tz) > self._THRESHOLD:
            self._count = 1
            self.metric_text = f"T({tx:.3f}, {ty:.3f}, {tz:.3f})"


# ─── UV ───────────────────────────────────────────────────────────────────────

class UVSingleSet(BaseCheck):
    """Mesh must have exactly one UV set."""
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        mesh = _get_mesh_fn(dag_path)
        sets = mesh.getUVSetNames()
        n = len(sets)
        if n != 1:
            self._count = n
            self.metric_text = f"{n} UV sets: {', '.join(sets)}"


class UVUDIMReady(BaseCheck):
    """All UV coordinates must be in [0..10] × [0..10] UDIM range."""
    severity = "INFO"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        mesh = _get_mesh_fn(dag_path)
        shape = mesh.fullPathName()
        uv_sets = mesh.getUVSetNames()
        if not uv_sets:
            return
        us, vs = mesh.getUVs(uv_sets[0])
        bad_count = sum(
            1 for u, v in zip(us, vs)
            if not (0.0 <= u <= 10.0 and 0.0 <= v <= 10.0)
        )
        if bad_count:
            self._count = bad_count
            self.metric_text = f"{bad_count} UV coords outside UDIM range"


class UVUDIMBounds(BaseCheck):
    """UV islands must not cross UDIM tile boundaries."""
    severity = "BLOCKER"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        mesh = _get_mesh_fn(dag_path)
        shape = mesh.fullPathName()
        uv_sets = mesh.getUVSetNames()
        if not uv_sets:
            return

        n_polys = mesh.numPolygons
        sdp = _shape_dag(dag_path)
        it = om.MItMeshPolygon(sdp)
        bad_faces = []

        while not it.isDone():
            uvs = it.getUVs(uvSet=uv_sets[0])
            us, vs = uvs[0], uvs[1]
            if not us:
                it.next()
                continue
            # Check if polygon spans multiple UDIM tiles
            tiles = set(
                (int(math.floor(u)), int(math.floor(v)))
                for u, v in zip(us, vs)
                if 0.0 <= u <= 10.0 and 0.0 <= v <= 10.0
            )
            if len(tiles) > 1:
                bad_faces.append(f"{shape}.f[{it.index()}]")
            it.next()

        self._count = len(bad_faces)
        self._bad_components = bad_faces


class UVMaterialUDIM(BaseCheck):
    """Each UDIM tile must not contain UV shells from different materials."""
    severity = "BLOCKER"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        mesh = _get_mesh_fn(dag_path)
        shape = mesh.fullPathName()
        uv_sets = mesh.getUVSetNames()
        if not uv_sets:
            return

        sdp = _shape_dag(dag_path)
        it = om.MItMeshPolygon(sdp)

        # tile → set of shader indices
        tile_shaders: dict = {}
        # tile → list of face indices
        tile_faces: dict = {}

        # Get per-face shader assignment
        shaders_arr, face_shader_idx = mesh.getConnectedShaders(0)

        while not it.isDone():
            fi = it.index()
            uvs = it.getUVs(uvSet=uv_sets[0])
            us, vs = uvs[0], uvs[1]
            if not us:
                it.next()
                continue
            u_avg = sum(us) / len(us)
            v_avg = sum(vs) / len(vs)
            tile = (int(math.floor(u_avg)), int(math.floor(v_avg)))
            shader_idx = face_shader_idx[fi] if fi < len(face_shader_idx) else -1

            if tile not in tile_shaders:
                tile_shaders[tile] = set()
                tile_faces[tile] = []
            tile_shaders[tile].add(shader_idx)
            tile_faces[tile].append(fi)
            it.next()

        bad_tiles = {t for t, s in tile_shaders.items() if len(s) > 1}
        bad_faces = []
        for tile in bad_tiles:
            for fi in tile_faces[tile]:
                bad_faces.append(f"{shape}.f[{fi}]")

        self._count = len(bad_tiles)
        self._bad_components = bad_faces
        if bad_tiles:
            names = ", ".join(
                f"UDIM {1001 + t[0] + t[1] * 10}" for t in sorted(bad_tiles)[:3]
            )
            self.metric_text = f"{self._count} tile(s) ({names})"


# ─── NAMING ───────────────────────────────────────────────────────────────────

# Default naming policy: lowercase, letters/digits/underscores, optional suffix
_DEFAULT_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]*$')
_DEFAULT_MAT_SUFFIX   = "_mat"

# Forbidden DCC default names (would be renamed on FBX import downstream)
_FORBIDDEN_NAMES = frozenset({
    "pCube", "pSphere", "pCylinder", "pCone", "pTorus", "pPlane",
    "polySurface", "nurbsCircle", "nurbsCube", "group", "locator",
    "transform", "mesh", "object",
})


class NamingPolicy:
    """Configurable naming rules for objects.

    Rules (all optional, checked in order):
      1. Must match basic pattern (lowercase, underscores, no spaces/special chars)
      2. Must not be a forbidden DCC default name (pCube, polySurface, group, ...)
      3. If required_prefix set: name must start with it (e.g. "hero_", "bg_")
      4. If required_suffix set: name must end with it (e.g. "_geo", "_grp")
    """
    _PREFIX_KEY = "stukach_naming_prefix"
    _SUFFIX_KEY = "stukach_naming_suffix"
    # groups = namespaces / display layers (Maya equivalent of Blender collections)
    _COL_PREFIX_KEY = "stukach_col_prefix"
    _COL_SUFFIX_KEY = "stukach_col_suffix"

    @classmethod
    def get_prefix(cls) -> str:
        import maya.cmds as cmds
        try:
            val = cmds.fileInfo(cls._PREFIX_KEY, query=True)
            return val[0] if val else ""
        except Exception:
            return ""

    @classmethod
    def get_suffix(cls) -> str:
        import maya.cmds as cmds
        try:
            val = cmds.fileInfo(cls._SUFFIX_KEY, query=True)
            return val[0] if val else ""
        except Exception:
            return ""

    @classmethod
    def set_prefix(cls, prefix: str) -> None:
        import maya.cmds as cmds
        if prefix:
            cmds.fileInfo(cls._PREFIX_KEY, prefix)
        else:
            try:
                import maya.mel as mel
                mel.eval(f'fileInfo -remove "{cls._PREFIX_KEY}"')
            except Exception:
                pass

    @classmethod
    def set_suffix(cls, suffix: str) -> None:
        import maya.cmds as cmds
        if suffix:
            cmds.fileInfo(cls._SUFFIX_KEY, suffix)
        else:
            try:
                import maya.mel as mel
                mel.eval(f'fileInfo -remove "{cls._SUFFIX_KEY}"')
            except Exception:
                pass

    @classmethod
    def get_col_prefix(cls) -> str:
        import maya.cmds as cmds
        try:
            val = cmds.fileInfo(cls._COL_PREFIX_KEY, query=True)
            return val[0] if val else ""
        except Exception:
            return ""

    @classmethod
    def get_col_suffix(cls) -> str:
        import maya.cmds as cmds
        try:
            val = cmds.fileInfo(cls._COL_SUFFIX_KEY, query=True)
            return val[0] if val else ""
        except Exception:
            return ""

    @classmethod
    def set_col_prefix(cls, prefix: str) -> None:
        import maya.cmds as cmds
        if prefix:
            cmds.fileInfo(cls._COL_PREFIX_KEY, prefix)
        else:
            try:
                import maya.mel as mel
                mel.eval(f'fileInfo -remove "{cls._COL_PREFIX_KEY}"')
            except Exception:
                pass

    @classmethod
    def set_col_suffix(cls, suffix: str) -> None:
        import maya.cmds as cmds
        if suffix:
            cmds.fileInfo(cls._COL_SUFFIX_KEY, suffix)
        else:
            try:
                import maya.mel as mel
                mel.eval(f'fileInfo -remove "{cls._COL_SUFFIX_KEY}"')
            except Exception:
                pass

    @classmethod
    def validate_group(cls, name: str) -> list:
        """Issues for a namespace/layer name (lowercase + prefix/suffix policy)."""
        issues = []
        if not _DEFAULT_NAMESPACE_PATTERN.match(name):
            issues.append("not lowercase_snake_case")
        prefix = cls.get_col_prefix()
        if prefix and not name.startswith(prefix):
            issues.append(f"missing prefix '{prefix}'")
        suffix = cls.get_col_suffix()
        if suffix and not name.endswith(suffix):
            issues.append(f"missing suffix '{suffix}'")
        return issues

    @classmethod
    def validate(cls, name: str) -> list:
        """Return list of issue strings for a name. Empty = clean."""
        issues = []
        # 1. Basic pattern
        if not _DEFAULT_NAME_PATTERN.match(name):
            issues.append(f"invalid chars (need lowercase, underscores)")
        # 2. Forbidden DCC names
        base = re.sub(r'\d+$', '', name)  # strip trailing digits (pCube1 -> pCube)
        if base in _FORBIDDEN_NAMES or name in _FORBIDDEN_NAMES:
            issues.append(f"forbidden default name '{name}'")
        # 3. Required prefix
        prefix = cls.get_prefix()
        if prefix and not name.startswith(prefix):
            issues.append(f"missing prefix '{prefix}'")
        # 4. Required suffix
        suffix = cls.get_suffix()
        if suffix and not name.endswith(suffix):
            issues.append(f"missing suffix '{suffix}'")
        return issues


class ObjNaming(BaseCheck):
    """Object name must match naming policy."""
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        node = dag_path.fullPathName()
        short = node.split("|")[-1].split(":")[-1]   # strip namespace/path
        issues = NamingPolicy.validate(short)
        if issues:
            self._count = len(issues)
            self.metric_text = "; ".join(issues)


class MatSuffix(BaseCheck):
    """All assigned materials must end with '_mat'."""
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        mesh = _get_mesh_fn(dag_path)
        shaders_arr, _ = mesh.getConnectedShaders(0)
        bad = []
        for sh_obj in shaders_arr:
            sg_name = om.MFnDependencyNode(sh_obj).name()
            # Get all materials connected to this shading group
            connected = cmds.listConnections(sg_name + ".surfaceShader") or []
            mats = cmds.ls(connected) or []
            for m in set(mats):
                if not m.endswith(_DEFAULT_MAT_SUFFIX):
                    bad.append(m)
        self._count = len(bad)
        if bad:
            self.metric_text = ", ".join(bad[:3])


class MatAssignment(BaseCheck):
    """No unassigned material slots (faces with default shader only)."""
    severity = "BLOCKER"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        mesh = _get_mesh_fn(dag_path)
        shaders_arr, face_shader_idx = mesh.getConnectedShaders(0)
        # -1 in face_shader_idx means no shader assigned
        unassigned = sum(1 for idx in face_shader_idx if idx < 0)
        # Default lambert1 / initialShadingGroup counts as unassigned
        default_faces = 0
        for i, sh_obj in enumerate(shaders_arr):
            sg_name = om.MFnDependencyNode(sh_obj).name().lower()
            if "initial" in sg_name or sg_name == "defaultshader":
                default_faces += sum(1 for idx in face_shader_idx if idx == i)
        total_bad = unassigned + default_faces
        self._count = total_bad
        if total_bad:
            self.metric_text = f"{total_bad} face(s) with default/no material"


# ─── NEW CHECKERS (Phase 2 port from Blender) ────────────────────────────────
#
# numpy + scipy are required for these checkers (symmetry,
# the UV checks, duplicate_verts). Install via:
#   mayapy -m pip install numpy scipy
# They were added in Phase 2 of the Blender→Maya port.

# ─── TOPOLOGY: duplicate_verts ───────────────────────────────────────────────

class DuplicateVerts(BaseCheck):
    """Overlapping vertices within 0.01 mm — would merge on Merge by Distance.

    Uses scipy.spatial.cKDTree (the Maya equivalent of bmesh.ops.find_doubles).
    A vertex is flagged when another vertex sits within _MERGE_DIST of it.
    """
    severity = "BLOCKER"
    _MERGE_DIST = 1e-5   # 0.01 mm — only truly coincident verts

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        n = mesh.numVertices
        if n < 2:
            return
        try:
            from scipy.spatial import cKDTree
        except ImportError:
            self.metric_text = "scipy not installed — install via: mayapy -m pip install scipy"
            return

        pts = mesh.getPoints(om.MSpace.kObject)
        # numpy vectorized: MPointArray → (n,3) float64, filter NaN/inf
        try:
            import numpy as np
            co_all = np.array([(p.x, p.y, p.z) for p in pts], dtype=np.float64)
        except ImportError:
            # Fallback to Python loop if numpy unavailable
            co_all = None
        if co_all is not None:
            finite = np.isfinite(co_all).all(axis=1)
            reasonable = (np.abs(co_all) < 1e8).all(axis=1)
            mask = finite & reasonable
            valid_idx = np.where(mask)[0]
            co = co_all[mask]
        else:
            co = []
            valid_idx = []
            for i in range(n):
                x, y, z = pts[i].x, pts[i].y, pts[i].z
                if x != x or y != y or z != z:
                    continue
                if abs(x) > 1e8 or abs(y) > 1e8 or abs(z) > 1e8:
                    continue
                co.append((x, y, z))
                valid_idx.append(i)
        if len(co) < 2:
            return
        tree = cKDTree(co)
        # query_pairs returns unordered pairs (i, j) with i < j within the radius.
        # Indices here are into `co` (NaN verts excluded); map back to mesh verts.
        pairs = tree.query_pairs(r=self._MERGE_DIST, output_type='ndarray')
        if len(pairs) == 0:
            return
        # Both verts of each pair are duplicates — collect unique mesh-vertex ids
        if co_all is not None:
            import numpy as np
            dup_local = np.unique(pairs.ravel())
            dup_mesh = np.sort(valid_idx[dup_local])
            self._bad_components = [f"{shape}.vtx[{int(i)}]" for i in dup_mesh]
        else:
            dup_idx = set()
            for i, j in pairs:
                dup_idx.add(valid_idx[int(i)])
                dup_idx.add(valid_idx[int(j)])
            self._bad_components = [f"{shape}.vtx[{i}]" for i in sorted(dup_idx)]
        self._count = len(self._bad_components)


# ─── TOPOLOGY: face_aspect_ratio ─────────────────────────────────────────────

class FaceAspectRatio(BaseCheck):
    """Quad faces whose aspect ratio exceeds the threshold.

    Aspect ratio = max(avg_longer_pair, avg_shorter_pair) / min(...) for the two
    pairs of opposite edges in a quad.  Only quads are checked; tris/ngons skip.
    """
    severity = "INFO"
    _DEFAULT_THRESHOLD = 6.0

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        shape = sdp.fullPathName()
        it = om.MItMeshPolygon(sdp)
        bad = []
        threshold = self._DEFAULT_THRESHOLD
        while not it.isDone():
            if it.polygonVertexCount() != 4:
                it.next(); continue
            pts = it.getPoints(om.MSpace.kObject)   # MPointArray of the 4 corners
            # 4 edges: (0,1)(1,2)(2,3)(3,0); opposite pairs: (e0,e2) and (e1,e3)
            def edge_len(a, b):
                return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)
            e0 = edge_len(pts[0], pts[1])
            e1 = edge_len(pts[1], pts[2])
            e2 = edge_len(pts[2], pts[3])
            e3 = edge_len(pts[3], pts[0])
            avg_a = (e0 + e2) * 0.5
            avg_b = (e1 + e3) * 0.5
            if avg_a < 1e-10 or avg_b < 1e-10:
                it.next(); continue
            ratio = avg_a / avg_b if avg_a > avg_b else avg_b / avg_a
            if ratio > threshold:
                bad.append(f"{shape}.f[{it.index()}]")
            it.next()
        self._bad_components = bad
        self._count = len(bad)


# (flipped_normals / invalid_normals removed — Blender dropped both as
# unreliable on interior geometry; see STUKACH history)

# ─── SYMMETRY ─────────────────────────────────────────────────────────────────

class SymmetryCheck(BaseCheck):
    """Mesh symmetry check along an axis.

    Mirrors the Blender numpy algorithm exactly: round coords to an int grid,
    pack (gx,gy,gz) into one int64, binary-search for each mirrored key in the
    sorted set. A vertex is asymmetric if its mirror key is absent.
    Threshold 0.001 (1 mm grid). Severity INFO.
    """
    severity = "INFO"
    _AXIS: int = 0
    _THRESHOLD: float = 0.001

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        n = mesh.numVertices
        if n == 0:
            return
        import numpy as np
        pts = mesh.getPoints(om.MSpace.kObject)
        co_np = np.empty(n * 3, dtype=np.float64)
        for i in range(n):
            co_np[i * 3] = pts[i].x
            co_np[i * 3 + 1] = pts[i].y
            co_np[i * 3 + 2] = pts[i].z
        co_np = co_np.reshape(n, 3)

        thr = self._THRESHOLD
        axis = self._AXIS
        inv = 1.0 / max(thr, 1e-9)
        SHIFT = 1_000_000
        SPAN = 2 * SHIFT + 1

        gi = np.round(co_np * inv).astype(np.int64)
        gi = np.clip(gi, -SHIFT, SHIFT)
        gc = gi + SHIFT

        packed = (gc[:, 0] * SPAN + gc[:, 1]) * SPAN + gc[:, 2]
        packed_sorted = np.sort(packed)

        mi = gc.copy()
        mi[:, axis] = (-gi[:, axis]).clip(-SHIFT, SHIFT) + SHIFT
        m_packed = (mi[:, 0] * SPAN + mi[:, 1]) * SPAN + mi[:, 2]

        idx = np.searchsorted(packed_sorted, m_packed)
        idx = np.clip(idx, 0, len(packed_sorted) - 1)
        asym_mask = packed_sorted[idx] != m_packed

        asym_idx = list(np.where(asym_mask)[0].tolist())
        self._bad_components = [f"{shape}.vtx[{i}]" for i in asym_idx]
        self._count = len(asym_idx)


class SymmetryX(SymmetryCheck):
    _AXIS = 0


class SymmetryY(SymmetryCheck):
    _AXIS = 1


class SymmetryZ(SymmetryCheck):
    _AXIS = 2


# ─── NAMING: mat_numbering ────────────────────────────────────────────────────

class MatNumbering(BaseCheck):
    """Material names must not contain auto-numbering (.001, .002 ...).

    Catches stale default material copies that were never renamed.
    """
    severity = "WARNING"
    # Maya replaces dots with underscores in node names, so match both .001 and _001
    _RE_NUMBERING = re.compile(r"[._]\d{3,}$")

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        shape = sdp.fullPathName()
        transform = dag_path.fullPathName()
        if cmds.nodeType(transform) == "mesh":
            parent = cmds.listRelatives(transform, parent=True, fullPath=True)
            transform = parent[0] if parent else transform
        # Find shading engines via the mesh shape (not the transform)
        shading_engines = cmds.listConnections(shape, type="shadingEngine") or []
        bad_names = []
        seen = set()
        for sg in shading_engines:
            mats = cmds.ls(cmds.listConnections(sg + ".surfaceShader") or []) or []
            for mat in mats:
                if mat in seen:
                    continue
                seen.add(mat)
                if self._RE_NUMBERING.search(mat):
                    bad_names.append(mat)
        self._count = len(bad_names)
        if bad_names:
            self._bad_components = [transform]
            self.metric_text = f"{', '.join(bad_names[:3])}" + (f" +{len(bad_names)-3}" if len(bad_names) > 3 else "")


# ─── MATERIALS: missing_textures ──────────────────────────────────────────────

class MissingTextures(BaseCheck):
    """Materials whose file-texture nodes point to non-existent files on disk."""
    severity = "BLOCKER"
    _RE_NUMBERED = re.compile(r"\.\d{3,}$")

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        import os
        sdp = _shape_dag(dag_path)
        shape = sdp.fullPathName()
        transform = dag_path.fullPathName()
        if cmds.nodeType(transform) == "mesh":
            parent = cmds.listRelatives(transform, parent=True, fullPath=True)
            transform = parent[0] if parent else transform

        shading_engines = cmds.listConnections(shape, type="shadingEngine") or []
        seen = set()
        missing = []
        for sg in shading_engines:
            file_nodes = cmds.listConnections(cmds.listConnections(sg, d=False, s=True) or [],
                                              type="file") or []
            for fn in file_nodes:
                try:
                    tex_path = cmds.getAttr(fn + ".fileTextureName")
                except Exception:
                    continue
                if not tex_path or tex_path in seen:
                    continue
                seen.add(tex_path)
                # Resolve relative to workspace + expand env vars
                resolved = os.path.expandvars(tex_path)
                if not os.path.isabs(resolved):
                    ws = cmds.workspace(q=True, rootDirectory=True)
                    resolved = os.path.join(ws, resolved)
                if not os.path.exists(resolved):
                    missing.append(os.path.basename(tex_path))
        self._count = len(missing)
        if missing:
            self._bad_components = [transform]
            self.metric_text = f"missing: {', '.join(missing[:3])}" + (f" +{len(missing)-3}" if len(missing) > 3 else "")


# ─── UV: helpers (Union-Find island detection, 2D geometry) ────────────────────

def _mesh_uv_np(mesh_fn: om.MFnMesh, uv_set: str = None) -> "tuple":
    """Return (u_array, v_array, poly_vertices, uv_counts, uv_ids) for UV analysis.

    u_array / v_array : flat UV coord arrays (indexed by uv_id)
    poly_vertices     : flat per-face-vertex mesh-vertex ids (built per-polygon,
                        because MFnMesh.getPolygonVertices requires a polygonId in API 2.0)
    uv_counts         : verts per face (from getAssignedUVs)
    uv_ids            : per-face-vertex UV id (from getAssignedUVs)
    """
    if uv_set is None:
        uv_set = mesh_fn.currentUVSetName()
    u_arr, v_arr = mesh_fn.getUVs(uvSet=uv_set)
    uv_counts, uv_ids = mesh_fn.getAssignedUVs(uvSet=uv_set)
    uv_counts = list(uv_counts)
    uv_ids = list(uv_ids)
    # Build flat poly_verts by iterating polygons (API 2.0 has no bulk accessor).
    # uv_counts[i] may differ from len(getPolygonVertices(i)) when UV seams
    # split face-vertices — clamp to uv_counts to stay in sync.
    poly_verts: list = []
    n_polys = len(uv_counts)
    for fi in range(n_polys):
        verts = mesh_fn.getPolygonVertices(fi)
        n = uv_counts[fi]
        for k in range(min(n, len(verts))):
            poly_verts.append(int(verts[k]))
    return u_arr, v_arr, poly_verts, uv_counts, uv_ids


def _uv_island_membership(poly_verts, u_arr, v_arr, uv_counts, uv_ids) -> "list":
    """Union-Find UV island detection. Returns poly_to_island list[int].

    Two polygons share an island iff they share a mesh edge whose UV coords
    match at both endpoints (within 6 decimals). Pure Python, Maya-API-free.
    """
    n_polys = len(uv_counts)
    if n_polys == 0:
        return []
    # Per-face-vertex offset table
    fv_start = [0] * n_polys
    acc = 0
    for i in range(n_polys):
        fv_start[i] = acc
        acc += uv_counts[i]

    # round each face-vertex UV to 6 decimals (key stability)
    uv_keys = []
    for i in range(len(uv_ids)):
        u = round(u_arr[uv_ids[i]], 6) if uv_ids[i] < len(u_arr) else 0.0
        v = round(v_arr[uv_ids[i]], 6) if uv_ids[i] < len(v_arr) else 0.0
        uv_keys.append((u, v))

    parent = list(range(n_polys))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    from collections import defaultdict
    edge_map = defaultdict(list)
    for pi in range(n_polys):
        lt = uv_counts[pi]
        ls = fv_start[pi]
        for k in range(lt):
            li0 = ls + k
            li1 = ls + (k + 1) % lt
            v0 = poly_verts[li0]
            v1 = poly_verts[li1]
            u0 = uv_keys[li0]
            u1 = uv_keys[li1]
            key = (v0, v1) if v0 < v1 else (v1, v0)
            val = (pi, u0, u1) if v0 < v1 else (pi, u1, u0)
            edge_map[key].append(val)

    for entries in edge_map.values():
        for a in range(len(entries)):
            for b in range(a + 1, len(entries)):
                pa, ua0, ua1 = entries[a]
                pb, ub0, ub1 = entries[b]
                if ua0 == ub0 and ua1 == ub1:
                    ra, rb = find(pa), find(pb)
                    if ra != rb:
                        parent[ra] = rb

    root_to_idx = {}
    poly_to_island = [0] * n_polys
    for pi in range(n_polys):
        r = find(pi)
        if r not in root_to_idx:
            root_to_idx[r] = len(root_to_idx)
        poly_to_island[pi] = root_to_idx[r]
    return poly_to_island


def _mesh_triangles(shape_dag: om.MDagPath) -> "tuple":
    """Return (tri_face_ids, tri_vert_ids) — fan triangulation per polygon.

    tri_face_ids : list[int] — source polygon index per triangle
    tri_vert_ids : list[(v0, v1, v2)] — vertex ids per triangle
    Takes a shape dag_path (API 2.0 iterators need a dag path, not MObject).
    """
    it = om.MItMeshPolygon(shape_dag)
    tri_face_ids = []
    tri_vert_ids = []
    while not it.isDone():
        fi = it.index()
        verts = it.getVertices()   # MIntArray
        n = len(verts)
        if n < 3:
            it.next(); continue
        v0 = int(verts[0])
        for k in range(1, n - 1):
            tri_face_ids.append(fi)
            tri_vert_ids.append((v0, int(verts[k]), int(verts[k + 1])))
        it.next()
    return tri_face_ids, tri_vert_ids


# ─── UV: uv_overlap ───────────────────────────────────────────────────────────

_UV_OVERLAP_MAX_TRIS = 30_000


def _uv_point_in_tri_strict(p, a, b, c) -> bool:
    def cross(o, u, v):
        return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
    eps = 1e-9
    d1, d2, d3 = cross(a, b, p), cross(b, c, p), cross(c, a, p)
    return (d1 > eps and d2 > eps and d3 > eps) or (d1 < -eps and d2 < -eps and d3 < -eps)


def _seg_intersect_2d(p1, p2, p3, p4) -> bool:
    def cross2d(a, b):
        return a[0] * b[1] - a[1] * b[0]
    rx, ry = p2[0] - p1[0], p2[1] - p1[1]
    sx, sy = p4[0] - p3[0], p4[1] - p3[1]
    rxs = cross2d((rx, ry), (sx, sy))
    if abs(rxs) < 1e-10:
        return False
    qpx, qpy = p3[0] - p1[0], p3[1] - p1[1]
    t = cross2d((qpx, qpy), (sx, sy)) / rxs
    u = cross2d((qpx, qpy), (rx, ry)) / rxs
    eps = 1e-9
    return eps < t < 1.0 - eps and eps < u < 1.0 - eps


def _uv_tris_truly_overlap(t1, t2) -> bool:
    a1, b1, c1 = t1
    a2, b2, c2 = t2
    for p in (a1, b1, c1):
        if _uv_point_in_tri_strict(p, a2, b2, c2):
            return True
    for p in (a2, b2, c2):
        if _uv_point_in_tri_strict(p, a1, b1, c1):
            return True
    mid1 = ((a1[0] + b1[0] + c1[0]) / 3, (a1[1] + b1[1] + c1[1]) / 3)
    if _uv_point_in_tri_strict(mid1, a2, b2, c2):
        return True
    mid2 = ((a2[0] + b2[0] + c2[0]) / 3, (a2[1] + b2[1] + c2[1]) / 3)
    if _uv_point_in_tri_strict(mid2, a1, b1, c1):
        return True
    edges1 = ((a1, b1), (b1, c1), (c1, a1))
    edges2 = ((a2, b2), (b2, c2), (c2, a2))
    for e1 in edges1:
        for e2 in edges2:
            if _seg_intersect_2d(e1[0], e1[1], e2[0], e2[1]):
                return True
    return False


class UVOverlap(BaseCheck):
    """Overlapping UV triangles within the same island.
    4-stage pipeline: island membership → 2D grid broad-phase → AABB → exact test.
    """
    severity = "BLOCKER"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        u_arr, v_arr, poly_verts, uv_counts, uv_ids = _mesh_uv_np(mesh)
        n_polys = mesh.numPolygons
        if n_polys == 0:
            return
        # Guard: poly_verts length must match uv_ids length
        if len(poly_verts) < len(uv_ids):
            uv_ids = uv_ids[:len(poly_verts)]
        tri_face_ids, tri_vert_ids = _mesh_triangles(sdp)
        n_tris = len(tri_face_ids)
        if n_tris == 0 or n_tris > _UV_OVERLAP_MAX_TRIS:
            return

        # Guard: skip if UV count mismatch (mesh with partial UVs)
        if len(u_arr) == 0 or len(uv_ids) == 0:
            return

        # Resolve UV per triangle vertex
        tri_uvs = []       # list[((u0,v0),(u1,v1),(u2,v2))]
        tri_src_idx = []   # maps tri_uvs index → tri_face_ids index
        for idx, (v0, v1, v2) in enumerate(tri_vert_ids):
            fi = tri_face_ids[idx]
            try:
                li0 = _poly_vert_local_index(mesh, fi, v0)
                li1 = _poly_vert_local_index(mesh, fi, v1)
                li2 = _poly_vert_local_index(mesh, fi, v2)
                uva = mesh.getPolygonUV(fi, li0)
                uvb = mesh.getPolygonUV(fi, li1)
                uvc = mesh.getPolygonUV(fi, li2)
            except Exception:
                continue
            tri_uvs.append((uva, uvb, uvc))
            tri_src_idx.append(idx)

        poly_to_island = _uv_island_membership(poly_verts, u_arr, v_arr, uv_counts, uv_ids)

        # AABB per triangle
        u_min = [min(t[0][0], t[1][0], t[2][0]) for t in tri_uvs]
        v_min = [min(t[0][1], t[1][1], t[2][1]) for t in tri_uvs]
        u_max = [max(t[0][0], t[1][0], t[2][0]) for t in tri_uvs]
        v_max = [max(t[0][1], t[1][1], t[2][1]) for t in tri_uvs]

        # 2D grid broad-phase (128x128)
        # Use len(tri_uvs) not n_tris — some UVs may have failed to resolve
        n_valid = len(tri_uvs)
        GRID = 128
        u_lo, u_hi = (min(u_min) if u_min else 0), (max(u_max) if u_max else 0)
        v_lo, v_hi = (min(v_min) if v_min else 0), (max(v_max) if v_max else 0)
        span_u = u_hi - u_lo
        span_v = v_hi - v_lo

        candidates = set()
        if span_u < 1e-12 or span_v < 1e-12:
            # Degenerate UV — skip exhaustive O(n^2) which would freeze Maya
            pass
        else:
            inv_u = (GRID - 1) / span_u
            inv_v = (GRID - 1) / span_v
            grid = {}
            for i in range(n_valid):
                gx0 = int((u_min[i] - u_lo) * inv_u)
                gx1 = int((u_max[i] - u_lo) * inv_u)
                gy0 = int((v_min[i] - v_lo) * inv_v)
                gy1 = int((v_max[i] - v_lo) * inv_v)
                for gx in range(gx0, gx1 + 1):
                    for gy in range(gy0, gy1 + 1):
                        key = gx * GRID + gy
                        grid.setdefault(key, []).append(i)
            for cell in grid.values():
                if len(cell) < 2:
                    continue
                for a in range(len(cell)):
                    for b in range(a + 1, len(cell)):
                        i, j = cell[a], cell[b]
                        # Map back to original face ids via tri_src_idx
                        fi_i = tri_face_ids[tri_src_idx[i]]
                        fi_j = tri_face_ids[tri_src_idx[j]]
                        if fi_i == fi_j:
                            continue
                        if fi_i < len(poly_to_island) and fi_j < len(poly_to_island) and \
                           poly_to_island[fi_i] == poly_to_island[fi_j]:
                            continue
                        candidates.add((i, j) if i < j else (j, i))

        flagged_polys = set()
        for i, j in candidates:
            if (u_max[i] < u_min[j] or u_max[j] < u_min[i] or
                    v_max[i] < v_min[j] or v_max[j] < v_min[i]):
                continue
            if _uv_tris_truly_overlap(tri_uvs[i], tri_uvs[j]):
                flagged_polys.add(tri_face_ids[tri_src_idx[i]])
                flagged_polys.add(tri_face_ids[tri_src_idx[j]])

        self._bad_components = [f"{shape}.f[{fi}]" for fi in sorted(flagged_polys)]
        self._count = len(flagged_polys)


_pvl_cache: dict = {}   # ponytail: module-level cache, cleared per run


def _poly_vert_local_index(mesh_fn: om.MFnMesh, fi: int, global_vi: int) -> int:
    """Return the local (0..n-1) index of global_vi within polygon fi.

    Caches the full poly→verts mapping per mesh so repeated calls within
    one checker run don't re-scan getPolygonVertices each time.
    """
    mesh_id = id(mesh_fn)
    cache = _pvl_cache.get(mesh_id)
    if cache is None:
        n = mesh_fn.numPolygons
        cache = [mesh_fn.getPolygonVertices(pi) for pi in range(n)]
        _pvl_cache[mesh_id] = cache
    verts = cache[fi]
    for li, gv in enumerate(verts):
        if int(gv) == global_vi:
            return li
    return 0


def _clear_pvl_cache() -> None:
    """Call between major operations to free the poly-vert cache."""
    _pvl_cache.clear()


# ─── UV: uv_stretch ───────────────────────────────────────────────────────────

_UV_STRETCH_DEFAULT_THRESHOLD = 0.5   # radians (~28°)
_UV_STRETCH_MAX_POLYS = 100_000


class UVStretch(BaseCheck):
    """Faces where the UV corner angle differs from the mesh corner angle beyond threshold.

    ZenUV-style stretch detection. Vectorized via numpy.
    """
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        n_polys = mesh.numPolygons
        if n_polys == 0 or n_polys > _UV_STRETCH_MAX_POLYS:
            return
        import numpy as np

        threshold = _UV_STRETCH_DEFAULT_THRESHOLD

        # Build per-face-vertex arrays: mesh verts, UV coords
        u_arr, v_arr, poly_verts, uv_counts, uv_ids = _mesh_uv_np(mesh)
        n_fv = len(poly_verts)
        if n_fv == 0:
            return

        # Resolve world coords per face-vertex
        world_pts = mesh.getPoints(om.MSpace.kWorld)
        n_verts = len(world_pts)
        fv_co = np.empty((n_fv, 3), dtype=np.float64)
        for i in range(n_fv):
            vi = poly_verts[i]
            if 0 <= vi < n_verts:
                p = world_pts[vi]
                fv_co[i] = (p.x, p.y, p.z)
            else:
                fv_co[i] = (0.0, 0.0, 0.0)  # fallback for invalid index

        # UV per face-vertex
        fv_uv = np.empty((n_fv, 2), dtype=np.float64)
        for i in range(n_fv):
            uid = uv_ids[i] if i < len(uv_ids) else 0
            fv_uv[i] = (u_arr[uid] if uid < len(u_arr) else 0.0,
                        v_arr[uid] if uid < len(v_arr) else 0.0)

        # Per-poly start offsets
        fv_start = [0] * n_polys
        acc = 0
        for i in range(n_polys):
            fv_start[i] = acc
            acc += uv_counts[i]

        # ring-wrap next/prev within each polygon
        # Guard: if uv_counts doesn't match poly_verts (e.g. multi-UV-set mesh),
        # clamp to n_fv to prevent index-out-of-bounds.
        total_fv_from_counts = sum(uv_counts)
        if total_fv_from_counts > n_fv:
            # Truncate uv_counts to match poly_verts length
            acc = 0
            for i in range(n_polys):
                remaining = n_fv - acc
                if uv_counts[i] > remaining:
                    uv_counts[i] = remaining
                acc += uv_counts[i]
                if acc >= n_fv:
                    uv_counts = uv_counts[:i + 1]
                    n_polys = i + 1
                    break

        loop_next = np.empty(n_fv, dtype=np.int64)
        loop_prev = np.empty(n_fv, dtype=np.int64)
        poly_id = np.empty(n_fv, dtype=np.int64)
        for pi in range(n_polys):
            ls = fv_start[pi]
            lt = uv_counts[pi]
            for k in range(lt):
                li = ls + k
                if li >= n_fv:
                    break
                poly_id[li] = pi
                loop_next[li] = ls + (k + 1) % lt
                loop_prev[li] = ls + (k + lt - 1) % lt

        # 3D corner angle
        cur = fv_co
        nxt = fv_co[loop_next]
        prv = fv_co[loop_prev]
        e0 = nxt - cur
        e1 = prv - cur
        mag0 = np.sqrt((e0 * e0).sum(axis=1))
        mag1 = np.sqrt((e1 * e1).sum(axis=1))
        valid_3d = (mag0 > 1e-10) & (mag1 > 1e-10)
        denom3 = np.where(valid_3d, mag0 * mag1, 1.0)
        cos3 = np.clip((e0 * e1).sum(axis=1) / denom3, -1.0, 1.0)
        mesh_angle = np.arccos(np.where(valid_3d, cos3, 0.0))

        # UV corner angle
        cu = fv_uv
        nu = fv_uv[loop_next]
        pu = fv_uv[loop_prev]
        ax = nu[:, 0] - cu[:, 0]; ay = nu[:, 1] - cu[:, 1]
        bx = pu[:, 0] - cu[:, 0]; by = pu[:, 1] - cu[:, 1]
        mag_a = np.sqrt(ax * ax + ay * ay)
        mag_b = np.sqrt(bx * bx + by * by)
        valid_uv = (mag_a > 1e-10) & (mag_b > 1e-10)
        denomU = np.where(valid_uv, mag_a * mag_b, 1.0)
        cosU = np.clip((ax * bx + ay * by) / denomU, -1.0, 1.0)
        uv_angle = np.arccos(np.where(valid_uv, cosU, 0.0))

        stretched = valid_3d & valid_uv & (np.abs(mesh_angle - uv_angle) > threshold)

        bad_face_mask = np.zeros(n_polys, dtype=bool)
        np.bitwise_or.at(bad_face_mask, poly_id, stretched)
        bad_faces = np.where(bad_face_mask)[0]

        self._bad_components = [f"{shape}.f[{int(fi)}]" for fi in bad_faces]
        self._count = len(bad_faces)


# ─── UV: uv_texel_density ─────────────────────────────────────────────────────

class UVTexelDensity(BaseCheck):
    """Texel density (px/cm). INFO; count=1 if a target is set and out of tolerance."""
    severity = "INFO"
    _TD_TEX_SIZE = 2048
    _TD_TARGET = 0.0
    _TD_TOLERANCE = 0.20

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        import numpy as np
        import math

        u_arr, v_arr, poly_verts, uv_counts, uv_ids = _mesh_uv_np(mesh)
        tri_face_ids, tri_vert_ids = _mesh_triangles(sdp)
        n_tris = len(tri_face_ids)
        if n_tris == 0:
            return

        # UV area per triangle (2D cross product)
        uv_area = 0.0
        world_area = 0.0
        world_pts = mesh.getPoints(om.MSpace.kWorld)
        for (v0, v1, v2), fi in zip(tri_vert_ids, tri_face_ids):
            try:
                li0 = _poly_vert_local_index(mesh, fi, v0)
                li1 = _poly_vert_local_index(mesh, fi, v1)
                li2 = _poly_vert_local_index(mesh, fi, v2)
                a = mesh.getPolygonUV(fi, li0)
                b = mesh.getPolygonUV(fi, li1)
                c = mesh.getPolygonUV(fi, li2)
            except Exception:
                continue
            # UV area
            au = b[0] - a[0]; av = b[1] - a[1]
            bu = c[0] - a[0]; bv = c[1] - a[1]
            uv_area += abs(au * bv - av * bu) * 0.5
            # World area
            p0 = world_pts[v0]; p1 = world_pts[v1]; p2 = world_pts[v2]
            e1 = (p1.x - p0.x, p1.y - p0.y, p1.z - p0.z)
            e2 = (p2.x - p0.x, p2.y - p0.y, p2.z - p0.z)
            cx = e1[1] * e2[2] - e1[2] * e2[1]
            cy = e1[2] * e2[0] - e1[0] * e2[2]
            cz = e1[0] * e2[1] - e1[1] * e2[0]
            world_area += math.sqrt(cx * cx + cy * cy + cz * cz) * 0.5

        if world_area < 1e-10:
            self.metric_text = "TD: N/A"
            return

        scale_length = 1.0
        try:
            linear = cmds.currentUnit(query=True, linear=True)
            # Maya units → meters
            scale_map = {"meter": 1.0, "centimeter": 0.01, "millimeter": 0.001,
                         "inch": 0.0254, "foot": 0.3048, "yard": 0.9144}
            scale_length = scale_map.get(linear, 1.0)
        except Exception:
            pass

        density = (self._TD_TEX_SIZE * math.sqrt(uv_area)) / (math.sqrt(world_area) * 100.0 * scale_length)

        if self._TD_TARGET > 0.0:
            deviation = abs(density - self._TD_TARGET) / self._TD_TARGET
            self._count = 1 if deviation > self._TD_TOLERANCE else 0
        self.metric_text = (f"TD: {density:.2f} / {self._TD_TARGET:.2f} px/cm"
                            if self._TD_TARGET > 0.0
                            else f"TD: {density:.2f} px/cm")


# ─── UV: uv_micro_shell ───────────────────────────────────────────────────────

_MICRO_SHELL_ISLAND_AREA = 1e-5
_MICRO_SHELL_UV_AREA = 1e-12
_UV_MICRO_SHELL_MAX_POLYS = 50_000


class UVMicroShell(BaseCheck):
    """UV islands whose total area is below the micro-shell threshold (≈6px×6px @2048)."""
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        n_polys = mesh.numPolygons
        if n_polys == 0:
            return
        import numpy as np

        u_arr, v_arr, poly_verts, uv_counts, uv_ids = _mesh_uv_np(mesh)
        tri_face_ids, tri_vert_ids = _mesh_triangles(sdp)

        # Per-triangle UV area
        tri_areas = np.zeros(len(tri_face_ids), dtype=np.float64)
        tri_poly = np.array(tri_face_ids, dtype=np.int64)
        for k, ((v0, v1, v2), fi) in enumerate(zip(tri_vert_ids, tri_face_ids)):
            try:
                a = mesh.getPolygonUV(fi, _poly_vert_local_index(mesh, fi, v0))
                b = mesh.getPolygonUV(fi, _poly_vert_local_index(mesh, fi, v1))
                c = mesh.getPolygonUV(fi, _poly_vert_local_index(mesh, fi, v2))
            except Exception:
                continue
            au = b[0] - a[0]; av = b[1] - a[1]
            bu = c[0] - a[0]; bv = c[1] - a[1]
            tri_areas[k] = abs(au * bv - av * bu) * 0.5

        if n_polys <= _UV_MICRO_SHELL_MAX_POLYS:
            poly_to_island = _uv_island_membership(poly_verts, u_arr, v_arr, uv_counts, uv_ids)
            if not poly_to_island:
                return
            n_islands = (max(poly_to_island) + 1) if poly_to_island else 0
            # Aggregate per-triangle area into per-island totals: the bincount
            # indices are the island of each triangle's source polygon.
            tri_clipped = np.clip(tri_poly, 0, len(poly_to_island) - 1)
            tri_island = np.array([poly_to_island[int(p)] for p in tri_clipped], dtype=np.int64)
            island_area = np.bincount(tri_island, weights=tri_areas, minlength=n_islands)
            micro_islands = set(int(i) for i in np.where(island_area < _MICRO_SHELL_ISLAND_AREA)[0])
            if not micro_islands:
                return
            micro_polys = set(int(p) for p, isl in enumerate(poly_to_island) if isl in micro_islands)
        else:
            # Per-tri fallback
            micro_mask = tri_areas < _MICRO_SHELL_UV_AREA
            micro_polys = set(int(p) for p in tri_poly[micro_mask])

        self._bad_components = [f"{shape}.f[{fi}]" for fi in sorted(micro_polys)]
        self._count = len(micro_polys)


# ─── UV: uv_padding (single-object shell-to-shell + tile-border) ───────────────
#
# NOTE: Blender's uv_padding is cross-object (run_global_uv_padding). For the
# first Maya port we implement per-object shell-to-shell + tile-border, which
# covers the common case. Cross-object can be layered on later via a registry.

_UV_PADDING_MAX_POLYS = 30_000
_UV_PADDING_SHELL_PX = 16
_UV_PADDING_TILE_PX = 8
_UV_PADDING_TEX_SIZE = 4096


class UVPadding(BaseCheck):
    """UV islands closer than shell_px to another island, or tile_px to a UDIM border.

    Per-object spatial-hash shell-to-shell + analytic tile-border check.
    Severity INFO.
    """
    severity = "INFO"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        n_polys = mesh.numPolygons
        if n_polys == 0 or n_polys > _UV_PADDING_MAX_POLYS:
            return
        import math

        u_arr, v_arr, poly_verts, uv_counts, uv_ids = _mesh_uv_np(mesh)
        poly_to_island = _uv_island_membership(poly_verts, u_arr, v_arr, uv_counts, uv_ids)
        if not poly_to_island:
            return
        n_islands = (max(poly_to_island) + 1) if poly_to_island else 0

        # Collect UV points per island + dominant UDIM tile per island (vote)
        island_uvs = [[] for _ in range(n_islands)]
        island_votes = [{} for _ in range(n_islands)]
        fv_start = [0] * n_polys
        acc = 0
        for i in range(n_polys):
            fv_start[i] = acc
            acc += uv_counts[i]
        for pi in range(n_polys):
            isl = poly_to_island[pi]
            ls = fv_start[pi]
            lt = uv_counts[pi]
            for k in range(lt):
                uid = uv_ids[ls + k] if (ls + k) < len(uv_ids) else 0
                u = u_arr[uid] if uid < len(u_arr) else 0.0
                vv = v_arr[uid] if uid < len(v_arr) else 0.0
                island_uvs[isl].append((u, vv))
                tile = (int(math.floor(u)), int(math.floor(vv)))
                island_votes[isl][tile] = island_votes[isl].get(tile, 0) + 1

        island_tile = [max(v, key=v.__getitem__) if v else (0, 0) for v in island_votes]

        shell_thr = _UV_PADDING_SHELL_PX / _UV_PADDING_TEX_SIZE
        tile_thr = _UV_PADDING_TILE_PX / _UV_PADDING_TEX_SIZE
        inv = 1.0 / max(shell_thr, 1e-9)
        fl = math.floor

        # Build spatial hash: cell -> list of (island, u, v)
        grid_v = {}
        for isl in range(n_islands):
            for (u, vv) in island_uvs[isl]:
                key = (int(fl(u * inv)), int(fl(vv * inv)))
                grid_v.setdefault(key, []).append((isl, u, vv))

        bad_shell = set()
        bad_tile = set()
        shell_thr_sq = shell_thr * shell_thr

        # Shell-to-shell (only meaningful if >1 island)
        if n_islands > 1:
            for isl_a in range(n_islands):
                if isl_a in bad_shell:
                    continue
                for (ua, va) in island_uvs[isl_a]:
                    gx = int(fl(ua * inv)); gy = int(fl(va * inv))
                    found = False
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            cell = grid_v.get((gx + dx, gy + dy))
                            if not cell:
                                continue
                            for (isl_b, ub, vb) in cell:
                                if isl_b == isl_a:
                                    continue
                                d2 = (ua - ub) ** 2 + (va - vb) ** 2
                                if d2 < shell_thr_sq:
                                    bad_shell.add(isl_a)
                                    bad_shell.add(isl_b)
                                    found = True; break
                            if found: break
                        if found: break
                    if found: break

        # Tile-border (analytic distance to tile edge)
        for isl in range(n_islands):
            tu, tv = island_tile[isl]
            if isl in bad_tile:
                continue
            for (u, vv) in island_uvs[isl]:
                uf = u - tu; vf = vv - tv
                du = uf if uf < 0.5 else 1.0 - uf
                dv = vf if vf < 0.5 else 1.0 - vf
                if du < tile_thr or dv < tile_thr:
                    bad_tile.add(isl)
                    break

        bad_islands = bad_shell | bad_tile
        if not bad_islands:
            return
        bad_polys = set(int(p) for p, isl in enumerate(poly_to_island) if isl in bad_islands)
        self._bad_components = [f"{shape}.f[{fi}]" for fi in sorted(bad_polys)]
        self._count = len(bad_islands)


# ─── Z-FIGHTING (ported from Blender) ────────────────────────────────────────

_Z_FIGHT_MAX_FACES_INTRA = 100_000
_Z_FIGHT_MAX_FACES_INTER = 300_000
_Z_FIGHT_NORMAL_DOT = 0.99     # coplanar threshold (signed dot product)
_Z_FIGHT_CENTROID_DIST = 0.001  # 1mm world-space centroid distance


class ZFighting(BaseCheck):
    """Detect coplanar overlapping faces — intra-object and inter-object.

    Ported from Blender's ZFighting checker. Uses spatial hash + normal +
    adjacency + centroid filters to eliminate false positives.
    """
    severity = "BLOCKER"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        mesh = om.MFnMesh(sdp)
        shape = mesh.fullPathName()
        n_faces = mesh.numPolygons
        if n_faces < 2 or n_faces > _Z_FIGHT_MAX_FACES_INTRA:
            return

        # Collect per-face data: centroid + normal (via MItMeshPolygon)
        centroids = []
        normals = []
        it = om.MItMeshPolygon(sdp)
        while not it.isDone():
            fi = it.index()
            c = it.center(om.MSpace.kWorld)
            centroids.append((c[0], c[1], c[2]))
            n = it.getNormal(om.MSpace.kObject)
            normals.append((n[0], n[1], n[2]))
            it.next()

        # Build adjacency: face → set of vertex indices
        face_verts = [set(int(v) for v in mesh.getPolygonVertices(fi)) for fi in range(n_faces)]

        # Build spatial hash (grid-based broad phase)
        from collections import defaultdict
        cell_size = 0.05  # 5cm grid
        grid = defaultdict(list)
        for fi, (cx, cy, cz) in enumerate(centroids):
            key = (int(cx / cell_size), int(cy / cell_size), int(cz / cell_size))
            grid[key].append(fi)

        # Check pairs within same + adjacent cells
        thr_sq = _Z_FIGHT_CENTROID_DIST ** 2
        bad = set()
        checked = set()
        for (gx, gy, gz), faces_in_cell in grid.items():
            # Check within cell + 26 neighbors
            neighbors = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        neighbors.extend(grid.get((gx+dx, gy+dy, gz+dz), []))
            for i_idx in range(len(faces_in_cell)):
                fi = faces_in_cell[i_idx]
                for fj in neighbors:
                    if fj <= fi:
                        continue
                    pair = (fi, fj)
                    if pair in checked:
                        continue
                    checked.add(pair)

                    # 1. Coplanar: normals must agree (signed dot > threshold)
                    ni, nj = normals[fi], normals[fj]
                    dot = ni[0]*nj[0] + ni[1]*nj[1] + ni[2]*nj[2]
                    if dot < _Z_FIGHT_NORMAL_DOT:
                        continue

                    # 2. Adjacency: skip faces sharing a vertex
                    if face_verts[fi] & face_verts[fj]:
                        continue

                    # 3. Centroid distance
                    ci, cj = centroids[fi], centroids[fj]
                    dx = ci[0]-cj[0]; dy = ci[1]-cj[1]; dz = ci[2]-cj[2]
                    if dx*dx + dy*dy + dz*dz > thr_sq:
                        continue

                    bad.add(fi)
                    bad.add(fj)

        self._bad_components = [f"{shape}.f[{fi}]" for fi in sorted(bad)]
        self._count = len(bad)


# ─── MODIFIER STACK (ported from Blender) ─────────────────────────────────────

_MODIFIER_NODE_TYPES = frozenset({
    "polySmoothFace", "polyRemesh", "polyReduce", "polySubdivideFace",
    "subdiv", "ffd", "blendShape", "skinCluster", "nonLinear",
    "lattice", "wrap", "deltaMush", "tension", "proximityWrap",
    "sculpt", "shrinkWrap", "meshSmooth", "polyExtrudeFace",
    "polyBevel", "polyChamfer", "polyBoolOp",
})
_MODIFIER_EXCLUDE = frozenset({
    "groupId", "tweak", "groupParts", "shadingEngine",
    "objectSet", "renderPartition", "materialInfo",
})


class ModifierStack(BaseCheck):
    """Detect unapplied modifiers on the construction history.

    Ported from Blender's ModifierStack checker. Reports non-Armature
    deformers and modelling operators still in the history stack.
    """
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        shape = om.MFnMesh(sdp).fullPathName()
        transform = cmds.listRelatives(shape, parent=True, fullPath=True) or [shape.split(".")[0]]
        transform = transform[0]

        history = cmds.listHistory(transform) or []
        modifiers = []
        for node in history:
            try:
                nt = cmds.nodeType(node)
            except Exception:
                continue
            if nt in _MODIFIER_EXCLUDE:
                continue
            if nt in _MODIFIER_NODE_TYPES:
                modifiers.append(node)
            elif nt not in ("mesh", "transform", "dagNode", "dependNode",
                            "shape", "skinClusterFilter", "objectSet",
                            "polyCube", "polySphere", "polyCylinder",
                            "polyPlane", "polyTorus", "polyCone",
                            "polyPipe", "polyPrism", "polyPyramid"):
                # Check if it's a deformer (use node name, not type)
                try:
                    if cmds.objectType(node, isAType="deformer"):
                        modifiers.append(node)
                except Exception:
                    pass

        self._count = len(modifiers)
        self._bad_components = []  # no component-level selection
        if modifiers:
            self.metric_text = ", ".join(modifiers[:5])
            if len(modifiers) > 5:
                self.metric_text += f" +{len(modifiers)-5}"


# ─── COL/NAMESPACE NAMING (ported from Blender's ColNaming) ───────────────────

_DEFAULT_NAMESPACE_PATTERN = re.compile(r'^[a-z][a-z0-9_]*$')


class ColNaming(BaseCheck):
    """Validate namespace and display layer naming conventions.

    Ported from Blender's ColNaming checker. In Maya, collections map
    to namespaces and display layers.
    """
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        shape = om.MFnMesh(sdp).fullPathName()
        transform = cmds.listRelatives(shape, parent=True, fullPath=True) or [shape.split(".")[0]]
        transform = transform[0]

        issues = []

        # Check namespace against the group naming policy
        short = transform.split("|")[-1]
        if ":" in short:
            ns = short.rsplit(":", 1)[0]
            ns_issues = NamingPolicy.validate_group(ns)
            for msg in ns_issues:
                issues.append(f"namespace '{ns}' — {msg}")

        # Check display layers the object belongs to
        layers = cmds.listConnections(transform, type="displayLayer") or []
        for layer in set(layers):
            if layer == "defaultLayer":
                continue
            for msg in NamingPolicy.validate_group(layer):
                issues.append(f"layer '{layer}' — {msg}")

        self._count = len(issues)
        self._bad_components = []
        if issues:
            self.metric_text = "; ".join(issues[:3])


# ─── UNUSED DATA (ported from Blender) ────────────────────────────────────────

class UnusedData(BaseCheck):
    """Detect empty vertex groups and unused custom attributes.

    Ported from Blender's UnusedData checker.
    """
    severity = "WARNING"

    def run(self, dag_path: om.MDagPath) -> None:
        self.reset()
        sdp = _shape_dag(dag_path)
        shape = om.MFnMesh(sdp).fullPathName()
        transform = cmds.listRelatives(shape, parent=True, fullPath=True) or [shape.split(".")[0]]
        transform = transform[0]

        issues = []
        fix_targets = []

        # 1. Empty vertex groups (skinCluster joints with zero weight)
        skins = cmds.listConnections(shape, type="skinCluster") or []
        for skin in set(skins):
            influences = cmds.skinCluster(skin, query=True, influence=True) or []
            n_verts = cmds.polyEvaluate(shape, vertex=True)
            for inf in influences:
                try:
                    wts = cmds.skinPercent(skin, f"{shape}.vtx[0:{n_verts-1}]",
                                           transform=inf, query=True)
                    if all(w < 1e-6 for w in wts):
                        issues.append(f"empty vgroup: {inf}")
                        fix_targets.append("vgroup:%s|%s" % (skin, inf))
                except Exception:
                    pass

        # 2. Custom attributes on the transform
        custom_attrs = cmds.listAttr(transform, userDefined=True) or []
        _BUILTIN = frozenset({
            "stukach_naming_prefix", "stukach_naming_suffix",
            "offsetParentMatrix", "rotatePivot", "scalePivot",
            "rotateAxis", "inheritsTransform",
        })
        for attr in custom_attrs:
            if attr in _BUILTIN:
                continue
            if attr.startswith("stukach_"):
                continue
            issues.append(f"custom attr: {attr}")
            fix_targets.append("attr:%s.%s" % (transform, attr))

        self._count = len(issues)
        self._bad_components = fix_targets
        if issues:
            self.metric_text = "; ".join(issues[:5])
            if len(issues) > 5:
                self.metric_text += f" +{len(issues)-5}"


# ─── SNAPSHOT-DRIVEN CHECKS (reference: modelChecker, Weta) ───────────────────
#
# These consume a MeshSnapshot built ONCE per mesh (see snapshot.py) instead of
# re-iterating the mesh per check. bad_components use Maya component strings
# ("shape.f[3]", "shape.e[5]") so Sel + viewport overlay work as usual.


class SnapshotCheck(BaseCheck):
    """Base for checks that run against a MeshSnapshot."""

    def run(self, dag_path, ctx=None):
        snap = ctx.get("snapshot") if ctx else None
        if snap is None:
            return
        self.reset()
        self.run_snapshot(snap)

    def run_snapshot(self, snap):
        raise NotImplementedError


class HardEdges(SnapshotCheck):
    """Sharp edges (dihedral angle >= threshold) that are NOT marked hard.

    Smooth shading across a sharp corner produces shading artifacts — such
    edges must be hard (or handled by custom normals). Listing every hard
    edge is meaningless on hardsurf, so only the MISSED ones are flagged.
    """
    severity = "WARNING"
    ANGLE_THRESHOLD_DEG = 30.0

    @staticmethod
    def _face_normal(snap, face_id):
        """Newell's method — robust for concave/n-gon faces."""
        vs = snap.face_verts[face_id]
        nx = ny = nz = 0.0
        pts = snap.points
        for i in range(len(vs)):
            a = pts[vs[i]]
            b = pts[vs[(i + 1) % len(vs)]]
            nx += (a[1] - b[1]) * (a[2] + b[2])
            ny += (a[2] - b[2]) * (a[0] + b[0])
            nz += (a[0] - b[0]) * (a[1] + b[1])
        length = (nx * nx + ny * ny + nz * nz) ** 0.5
        if length < 1e-12:
            return None
        return (nx / length, ny / length, nz / length)

    def run_snapshot(self, snap):
        import math
        # edge id -> adjacent face ids (from face corner walks)
        edge_faces = {}
        face_edge_pairs = {}
        for eid, (v0, v1) in enumerate(snap.edges):
            face_edge_pairs[(v0, v1) if v0 < v1 else (v1, v0)] = eid
        for fid, vs in enumerate(snap.face_verts):
            n = len(vs)
            for i in range(n):
                a, b = vs[i], vs[(i + 1) % n]
                key = (a, b) if a < b else (b, a)
                eid = face_edge_pairs.get(key)
                if eid is not None:
                    edge_faces.setdefault(eid, []).append(fid)

        threshold = math.radians(self.ANGLE_THRESHOLD_DEG)
        cos_threshold = math.cos(threshold)
        bad = []
        for eid, (v0, v1) in enumerate(snap.edges):
            if snap.edge_smooth[eid] is False or snap.edge_conn[eid] != 2:
                continue   # already hard, or boundary/non-manifold
            faces = edge_faces.get(eid, [])
            if len(faces) != 2:
                continue
            n0 = self._face_normal(snap, faces[0])
            n1 = self._face_normal(snap, faces[1])
            if n0 is None or n1 is None:
                continue
            dot = n0[0] * n1[0] + n0[1] * n1[1] + n0[2] * n1[2]
            if dot < cos_threshold:   # angle > threshold while edge is smooth
                bad.append(snap.shape + ".e[%d]" % eid)
        self._count = len(bad)
        self._bad_components = bad


class Lamina(SnapshotCheck):
    """Lamina faces — zero-thickness geometry folded onto itself."""
    severity = "BLOCKER"

    def run_snapshot(self, snap):
        bad = [
            snap.shape + ".f[%d]" % i
            for i, is_lamina in enumerate(snap.face_lamina) if is_lamina
        ]
        self._count = len(bad)
        self._bad_components = bad


class ZeroLengthEdges(SnapshotCheck):
    """Edges of (near-)zero length — degenerate geometry."""
    severity = "BLOCKER"
    _TOL = 1e-8

    def run_snapshot(self, snap):
        bad = []
        pts = snap.points
        for i, (v0, v1) in enumerate(snap.edges):
            a, b = pts[v0], pts[v1]
            d = ((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2) ** 0.5
            if d <= self._TOL:
                bad.append(snap.shape + ".e[%d]" % i)
        self._count = len(bad)
        self._bad_components = bad


class Starlike(SnapshotCheck):
    """Non-starlike faces — polygon outline self-intersects."""
    severity = "WARNING"

    def run_snapshot(self, snap):
        bad = [
            snap.shape + ".f[%d]" % i
            for i, st in enumerate(snap.face_starlike) if st is False
        ]
        self._count = len(bad)
        self._bad_components = bad


class MissingUVs(SnapshotCheck):
    """Faces with no UV mapping at all."""
    severity = "WARNING"

    def run_snapshot(self, snap):
        bad = [
            snap.shape + ".f[%d]" % i
            for i, uvs in enumerate(snap.face_uvs) if uvs is None
        ]
        self._count = len(bad)
        self._bad_components = bad


class DuplicatedNames(SnapshotCheck):
    """Short names used by more than one node in the scene (FBX/AYON killers)."""
    severity = "BLOCKER"

    def run_snapshot(self, snap):
        n = snap.scene.get("short_names", {}).get(snap.short_name, 0)
        if n > 1:
            self._count = 1
            self.metric_text = "'%s' used by %d nodes" % (snap.short_name, n)
        else:
            self._count = 0


class ShapeNames(SnapshotCheck):
    """Shape node must be named '<transform>Shape'."""
    severity = "WARNING"

    def run_snapshot(self, snap):
        if snap.shape_short != snap.short_name + "Shape":
            self._count = 1
            self.metric_text = "shape '%s' != '%sShape'" % (
                snap.shape_short, snap.short_name)


class TrailingNumbers(SnapshotCheck):
    """Transform name ends with digits (pCube1-style leftovers)."""
    severity = "WARNING"

    def run_snapshot(self, snap):
        name = snap.short_name.split(":")[-1]
        if name and name[-1].isdigit():
            self._count = 1
            self.metric_text = "trailing digits in '%s'" % snap.short_name


class UncenteredPivots(SnapshotCheck):
    """Rotate pivot not at world origin."""
    severity = "WARNING"

    def run_snapshot(self, snap):
        rp = snap.rotate_pivot
        if any(abs(v) > 1e-6 for v in rp):
            self._count = 1
            self.metric_text = "pivot (%.3f, %.3f, %.3f)" % rp


class ParentGeometry(SnapshotCheck):
    """Mesh parented under another mesh — breaks export hierarchies."""
    severity = "WARNING"

    def run_snapshot(self, snap):
        if "mesh" in snap.parent_types:
            self._count = 1
            self.metric_text = "parented under a mesh"


# ─── CHECK_TYPES — maps key → class ──────────────────────────────────────────

CHECK_TYPES: dict = {
    # TOPOLOGY
    "triangles":            Triangles,
    "ngons":                Ngons,
    "non_manifold":         NonManifold,
    "zero_area":            ZeroArea,
    "poles":                Poles,
    "isolated_verts":       IsolatedVerts,
    "boundary_edges":       BoundaryEdges,
    "duplicate_verts":      DuplicateVerts,
    "face_aspect_ratio":    FaceAspectRatio,
    "z_fighting":           ZFighting,
    # TRANSFORMS
    "non_applied_transform": NonAppliedTransform,
    "scale":                NonAppliedScale,
    "construction_history": ConstructionHistory,
    "origin_at_zero":       OriginAtZero,
    "modifier_stack":       ModifierStack,
    # SYMMETRY
    "symmetry_x":           SymmetryX,
    "symmetry_y":           SymmetryY,
    "symmetry_z":           SymmetryZ,
    # UV
    "uv_single_set":        UVSingleSet,
    "uv_udim_ready":        UVUDIMReady,
    "uv_udim_bounds":       UVUDIMBounds,
    "uv_material_udim":     UVMaterialUDIM,
    "uv_overlap":           UVOverlap,
    "uv_stretch":           UVStretch,
    "uv_texel_density":     UVTexelDensity,
    "uv_micro_shell":       UVMicroShell,
    "uv_padding":           UVPadding,
    # NAMING
    "obj_naming":           ObjNaming,
    "col_naming":           ColNaming,
    "mat_numbering":        MatNumbering,
    # MATERIALS
    "mat_suffix":           MatSuffix,
    "mat_assignment":       MatAssignment,
    "missing_textures":     MissingTextures,
    # CLEANUP
    "missing_textures":     MissingTextures,
    "unused_data":          UnusedData,
    # SNAPSHOT-DRIVEN (modelChecker reference)
    "hard_edges":           HardEdges,
    "lamina":               Lamina,
    "zero_length_edges":    ZeroLengthEdges,
    "starlike":             Starlike,
    "missing_uvs":          MissingUVs,
    "duplicated_names":     DuplicatedNames,
    "shape_names":          ShapeNames,
    "trailing_numbers":     TrailingNumbers,
    "uncentered_pivots":    UncenteredPivots,
    "parent_geometry":      ParentGeometry,
}

CHECK_CATEGORIES: dict = {
    "TOPOLOGY":   ("non_manifold", "boundary_edges", "isolated_verts",
                   "duplicate_verts", "face_aspect_ratio",
                   "triangles", "ngons", "poles", "zero_area",
                   "z_fighting",
                   "hard_edges", "lamina", "zero_length_edges", "starlike"),
    "TRANSFORMS": ("non_applied_transform", "scale", "construction_history",
                   "origin_at_zero", "modifier_stack",
                   "uncentered_pivots", "parent_geometry"),
    "SYMMETRY":   ("symmetry_x", "symmetry_y", "symmetry_z"),
    "UV":         ("uv_single_set", "uv_udim_ready", "uv_udim_bounds", "uv_material_udim",
                   "uv_overlap", "uv_micro_shell", "uv_stretch", "uv_texel_density", "uv_padding",
                   "missing_uvs"),
    "NAMING":     ("obj_naming", "col_naming", "mat_numbering",
                   "duplicated_names", "shape_names", "trailing_numbers"),
    "MATERIALS":  ("mat_suffix", "mat_assignment", "missing_textures"),
    "CLEANUP":    ("unused_data",),
}

CHECK_SEVERITIES: dict = {
    key: cls.severity for key, cls in CHECK_TYPES.items()
}


# ─── scene-level check (not a BaseCheck — called directly from UI) ────────────

def check_scene_units() -> dict:
    """Scene-level check: linear unit must be meters.

    Returns {'ok': bool, 'issues': list[str]}.
    """
    issues = []
    try:
        # fullName=True returns 'meter'/'centimeter' rather than the short 'm'/'cm'
        linear = cmds.currentUnit(query=True, linear=True, fullName=True)
        angular = cmds.currentUnit(query=True, angle=True)
        if linear != "meter":
            issues.append(f"Linear unit: {linear} (need 'meter')")
        if angular != "deg":
            issues.append(f"Angular unit: {angular} (need 'deg')")
    except Exception as e:
        issues.append(f"Cannot read scene units: {e}")
    return {"ok": len(issues) == 0, "issues": issues}
