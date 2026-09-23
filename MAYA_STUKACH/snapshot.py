# -*- coding: utf-8 -*-
"""
STUKACH Maya — mesh snapshot builder.

Builds an immutable per-mesh snapshot in TWO iterator passes (faces, edges)
plus one points read. Snapshot-driven checks (see core.SnapshotCheck) consume
the snapshot instead of re-iterating the mesh themselves — N checks cost one
traversal, not N.

Pure data, no check logic. Component-id space matches Maya's:
face index = polygonId, edge index = edgeId, vertex index = vertId.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import maya.api.OpenMaya as om
import maya.cmds as cmds


@dataclass
class MeshSnapshot:
    transform: str                    # full path of the transform
    shape: str                        # full path of the mesh shape
    short_name: str                   # transform short name (with namespace)
    shape_short: str                  # shape short name
    namespace: str                    # "" when none
    layers: List[str]                 # display layer names (defaultLayer skipped)

    points: List[Tuple[float, float, float]]      # by vertId
    face_verts: List[Tuple[int, ...]]             # faceId -> corner vertIds
    face_area: List[float]                        # faceId -> area
    face_lamina: List[bool]                       # faceId -> is lamina
    face_starlike: List[bool]                     # faceId -> is starlike
    face_uvs: List[Optional[Tuple[float, ...]]]   # faceId -> flat (u,v,...) or None (None = no UVs)

    edges: List[Tuple[int, int]]                  # edgeId -> (v0, v1)
    edge_smooth: List[bool]                       # edgeId -> is smooth
    edge_conn: List[int]                          # edgeId -> connected face count

    world_matrix: Tuple[float, ...]               # 16 floats
    rotate_pivot: Tuple[float, float, float]
    parent_types: List[str]                       # node types of the parents

    # scene-level context shared by all snapshots of one run
    scene: Dict = field(default_factory=dict)     # e.g. {"short_names": {name: count}}

    # ── lazy adjacency (built on first request, shared by all snapshot checks;
    #    single main-thread use, no locking) ──
    _vert_edges: Optional[Dict[int, List[int]]] = field(
        default=None, init=False, repr=False, compare=False)
    _vert_faces: Optional[Dict[int, List[int]]] = field(
        default=None, init=False, repr=False, compare=False)
    _edge_faces: Optional[Dict[int, List[int]]] = field(
        default=None, init=False, repr=False, compare=False)

    def vert_edges(self) -> Dict[int, List[int]]:
        """vertId -> [edgeId, ...]"""
        if self._vert_edges is None:
            m: Dict[int, List[int]] = {}
            for eid, (a, b) in enumerate(self.edges):
                m.setdefault(a, []).append(eid)
                m.setdefault(b, []).append(eid)
            self._vert_edges = m
        return self._vert_edges

    def vert_faces(self) -> Dict[int, List[int]]:
        """vertId -> [faceId, ...] (distinct faces containing the vertex)"""
        if self._vert_faces is None:
            m: Dict[int, List[int]] = {}
            for fid, verts in enumerate(self.face_verts):
                for v in set(verts):
                    m.setdefault(v, []).append(fid)
            self._vert_faces = m
        return self._vert_faces

    def edge_faces(self) -> Dict[int, List[int]]:
        """edgeId -> [faceId, ...] — from face corner walks (a wire edge not
        walked by any face is absent; wire edges have no faces anyway)."""
        if self._edge_faces is None:
            pairs: Dict[Tuple[int, int], int] = {}
            for eid, (a, b) in enumerate(self.edges):
                pairs[(a, b) if a < b else (b, a)] = eid
            m: Dict[int, List[int]] = {}
            for fid, verts in enumerate(self.face_verts):
                n = len(verts)
                for i in range(n):
                    a, b = verts[i], verts[(i + 1) % n]
                    eid = pairs.get((a, b) if a < b else (b, a))
                    if eid is not None:
                        m.setdefault(eid, []).append(fid)
            self._edge_faces = m
        return self._edge_faces


def build_snapshot(dag_path: om.MDagPath, transform: str,
                   want_area: bool = True, want_lamina: bool = True,
                   want_starlike: bool = True, want_uvs: bool = True) -> MeshSnapshot:
    """One-traversal-per-mesh snapshot. Read-only, no cmds.* in hot loops.

    The per-face flags (area / lamina / starlike / uvs) are the EXPENSIVE part
    — request only what the currently enabled checks need. The dataclass lists
    stay complete (filled with safe defaults) so snapshot checks can always
    read them."""
    mesh = om.MFnMesh(dag_path)
    shape = mesh.fullPathName()
    short = transform.split("|")[-1]
    namespace = short.rsplit(":", 1)[0] if ":" in short else ""
    shape_short = shape.split("|")[-1]

    # ── pass 1: faces (verts, area, lamina, starlike, uvs) ────────────────────
    face_it = om.MItMeshPolygon(dag_path)
    face_verts: List[Tuple[int, ...]] = []
    face_area: List[float] = []
    face_lamina: List[bool] = []
    face_starlike: List[bool] = []
    face_uvs: List[Optional[Tuple[float, ...]]] = []
    while not face_it.isDone():
        face_verts.append(tuple(face_it.getVertices()))
        face_area.append(face_it.getArea() if want_area else 0.0)
        face_lamina.append(face_it.isLamina() if want_lamina else False)
        face_starlike.append(face_it.isStarlike() if want_starlike else False)
        if face_it.hasUVs():
            face_uvs.append(tuple(face_it.getUVs()) if want_uvs else ())
        else:
            face_uvs.append(None)
        face_it.next()

    # ── points (for zero-length edges) ─────────────────────────────────────────
    pts = mesh.getPoints()
    points = [(pts[i].x, pts[i].y, pts[i].z) for i in range(len(pts))]

    # ── pass 2: edges (pairs, smooth, connected faces) ─────────────────────────
    edges: List[Tuple[int, int]] = []
    edge_smooth: List[bool] = []
    edge_conn: List[int] = []
    edge_it = om.MItMeshEdge(dag_path)
    while not edge_it.isDone():
        e = edge_it.index()   # int edgeId (currentItem() returns MObject)
        vs = mesh.getEdgeVertices(e)
        edges.append((vs[0], vs[1]))
        edge_smooth.append(edge_it.isSmooth)
        edge_conn.append(edge_it.numConnectedFaces())
        edge_it.next()

    # ── scene surroundings (cheap cmds queries, once per object) ──────────────
    layers = [
        l for l in (cmds.listConnections(transform, type="displayLayer") or [])
        if l != "defaultLayer"
    ]
    parents = cmds.listRelatives(transform, parent=True, fullPath=True) or []
    parent_types = [cmds.nodeType(pt) for pt in parents]

    mat = cmds.xform(transform, q=True, matrix=True, ws=True)
    rp = cmds.xform(transform, q=True, rotatePivot=True, ws=True)

    return MeshSnapshot(
        transform=transform,
        shape=shape,
        short_name=short,
        shape_short=shape_short,
        namespace=namespace,
        layers=layers,
        points=points,
        face_verts=face_verts,
        face_area=face_area,
        face_lamina=face_lamina,
        face_starlike=face_starlike,
        face_uvs=face_uvs,
        edges=edges,
        edge_smooth=edge_smooth,
        edge_conn=edge_conn,
        world_matrix=tuple(mat),
        rotate_pivot=tuple(rp),
        parent_types=parent_types,
        scene={},
    )


def build_scene_ctx(objects: Dict[str, "object"]) -> Dict:
    """Scene-level context shared by snapshot checks (name maps etc.)."""
    names: Dict[str, int] = {}
    for t in objects:
        short = t.split("|")[-1]
        names[short] = names.get(short, 0) + 1
    return {"short_names": names}


def edge_length(points, edge: Tuple[int, int]) -> float:
    a, b = points[edge[0]], points[edge[1]]
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5
