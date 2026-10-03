# -*- coding: utf-8 -*-
"""Tranche 3c: ObjNaming / ColNaming run on the vendored stukach_core.naming.

Run with Maya's standalone interpreter (Maya may be closed):
    mayapy tests/test_naming_core.py

Prints "NAMING_CORE_RESULT: PASS" and exits 0 on success.
"""
import os
import sys

import maya.standalone
maya.standalone.initialize()

import maya.cmds as cmds  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from MAYA_STUKACH.core import (  # noqa: E402
    ColNaming, NamingPolicy, ObjNaming, _get_dag_path,
)

FAILURES = []


def check(cond, msg):
    if cond:
        print("  ok   - %s" % msg)
    else:
        FAILURES.append(msg)
        print("  FAIL - %s" % msg)


def fresh_scene(prefix="", suffix="", col_prefix="", col_suffix=""):
    """New untitled scene (fileInfo prefs are scene-scoped) + prefs."""
    cmds.file(new=True, force=True)
    if prefix:
        NamingPolicy.set_prefix(prefix)
    if suffix:
        NamingPolicy.set_suffix(suffix)
    if col_prefix:
        NamingPolicy.set_col_prefix(col_prefix)
    if col_suffix:
        NamingPolicy.set_col_suffix(col_suffix)


def run_obj(name):
    obj = cmds.polyCube(name=name)[0]
    chk = ObjNaming()
    chk.run(_get_dag_path(obj))
    return chk


def run_col(name, layers=()):
    """Poly cube *name* (namespaces auto-create), optional display layers
    the object is assigned to."""
    obj = cmds.polyCube(name=name)[0]
    for layer in layers:
        cmds.createDisplayLayer(empty=True, name=layer)
        cmds.editDisplayLayerMembers(layer, obj)
    chk = ColNaming()
    chk.run(_get_dag_path(obj))
    return chk


# ── ObjNaming ────────────────────────────────────────────────────────────────
print("[ObjNaming]")

fresh_scene(suffix="_geo")
chk = run_obj("door_geo")
check(chk.count == 0, "clean name with suffix: 0 findings (got %d)" % chk.count)

chk = run_obj("door_l_geo")
check(chk.count == 0, "built-in position _l passes the contract (got %d)" % chk.count)

chk = run_obj("Door_geo")
check(chk.count == 1 and "lowercase" in chk.metric_text,
      "uppercase name -> single lowercase warning")

chk = run_obj("pCube1")
check(chk.count >= 1 and "Default DCC name" in chk.metric_text,
      "pCube1 -> forbidden default name")

cyr = "\u043a\u0443\u0431_geo"   # 'kub_geo' in cyrillic
chk = run_obj(cyr)
check(chk.count >= 1 and "Non-ASCII" in chk.metric_text,
      "cyrillic name -> non_ascii error")

chk = run_obj("door")
check(chk.count == 1 and "contract" in chk.metric_text,
      "missing suffix -> contract_mismatch")

fresh_scene()
chk = run_obj("anything_goes")
check(chk.count == 0, "no suffix pref -> contract off, plain name clean")

# ── ColNaming ────────────────────────────────────────────────────────────────
print("[ColNaming]")

fresh_scene()
chk = run_col("props:door_geo")
check(chk.count == 0, "no col prefs -> plain namespace clean")

fresh_scene(col_suffix="_grp")
chk = run_col("pipe:door_geo")
check(chk.count == 1 and "namespace 'pipe'" in chk.metric_text,
      "namespace without _grp suffix -> one finding")

fresh_scene(col_suffix="_grp")
chk = run_col("pipe_grp:door_geo")
check(chk.count == 0, "namespaced object clean when ns carries the suffix")

fresh_scene()
chk = run_col("props:door_geo",
              layers=("goodlayer_grp", "badlayer_grp"))
check(chk.count == 0, "suffixed lowercase layers clean (no col prefs)")

chk = run_col("props:door_geo", layers=("BadLayer",))
check(chk.count == 1 and "layer 'BadLayer'" in chk.metric_text,
      "uppercase layer -> lowercase finding")

print("=" * 50)
if FAILURES:
    print("NAMING_CORE_RESULT: FAIL (%d)" % len(FAILURES))
    for f in FAILURES:
        print("  - %s" % f)
    sys.exit(1)
print("NAMING_CORE_RESULT: PASS")
sys.exit(0)
