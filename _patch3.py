# -*- coding: utf-8 -*-
import io
p = "MAYA_STUKACH/manager.py"
s = io.open(p, encoding="utf-8").read()
def rep(old, new, n=1):
    global s
    assert old in s, old[:70]
    s = s.replace(old, new, n)

# 1) fix unused_data (вставить перед mat_suffix)
rep('''                elif check_key == "mat_suffix":''',
'''                elif check_key == "unused_data":
                    mco = cls.objects.get(t)
                    checker = mco.checkers.get("unused_data") if mco else None
                    for item in list(getattr(checker, "bad_components", []) or []):
                        try:
                            if item.startswith("attr:"):
                                cmds.deleteAttr(item[5:])
                            elif item.startswith("vgroup:"):
                                skin, inf = item[7:].split("|", 1)
                                cmds.skinCluster(skin, edit=True,
                                                 removeInfluence=inf)
                        except Exception as e:
                            alog("fix unused_data item %s: %s" % (item, e))
                elif check_key == "mat_suffix":''')

# 2) fix_all_enabled: расширить набор
rep('''        fixable = {"non_applied_transform", "scale", "construction_history",
                   "non_manifold", "mat_suffix"}''',
'''        fixable = {"non_applied_transform", "scale", "construction_history",
                   "non_manifold", "mat_suffix", "unused_data"}''')

# 3) publish: универсальный (FBX/USD)
rep('''    @classmethod
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
            return False''',
'''    @classmethod
    def publish(cls, path: str, fmt: str = "fbx", selection_only: bool = False) -> bool:
        """Run preflight, then export FBX or USD. Returns True if exported."""
        check = cls.preflight_export()
        if check == "blocked":
            alog("%s export BLOCKED - %d blockers found. Fix issues first."
                 % (fmt.upper(), cls.total_blockers()))
            return False
        if check == "warning":
            alog("%s export WARNING - %d warnings. Proceeding anyway."
                 % (fmt.upper(), cls.total_warnings()))
        try:
            ftype = "USD Export" if fmt == "usd" else "FBX export"
            export_kw = {"es": True} if selection_only else {"ea": True}
            cmds.file(path, force=True, type=ftype, pr=True, **export_kw)
            alog("%s exported: %s" % (fmt.upper(), path))
            return True
        except Exception as e:
            alog("%s export error: %s" % (fmt.upper(), e))
            return False

    @classmethod
    def publish_fbx(cls, path: str, selection_only: bool = False) -> bool:
        """Backward-compatible wrapper around publish(path, 'fbx')."""
        return cls.publish(path, "fbx", selection_only)

    # -- checkpoint (validation snapshot in scene fileInfo) -------------------

    _CHECKPOINT_KEY = "stukach_checkpoint"
    _checkpoint_restored: bool = False

    @classmethod
    def save_checkpoint(cls) -> bool:
        """Save the validation snapshot (enabled checks + per-object results)
        into the scene's fileInfo so it can be restored after reopening."""
        import json
        from datetime import datetime
        objects = {}
        for t, mco in cls.objects.items():
            checks = {}
            for key, checker in mco.checkers.items():
                if mco.enabled.get(key) and checker and checker._ran:
                    checks[key] = [checker.count, checker.metric_text or ""]
            objects[t.split("|")[-1]] = checks
        data = {
            "version": _VERSION,
            "date": datetime.now().isoformat(timespec="seconds"),
            "scope": cls.scope,
            "enabled": {k: bool(v) for k, v in cls._enabled_checks.items()},
            "objects": objects,
        }
        try:
            payload = json.dumps(data)
            # fileInfo -remove first: overwriting with a shorter value fails
            import maya.mel as mel
            mel.eval('fileInfo -remove "%s"' % cls._CHECKPOINT_KEY)
            cmds.fileInfo(cls._CHECKPOINT_KEY, payload)
            alog("checkpoint saved (%d objects)" % len(objects))
            return True
        except Exception as e:
            alog("save_checkpoint: %s" % e)
            return False

    @classmethod
    def has_checkpoint(cls) -> bool:
        try:
            return bool(cmds.fileInfo(cls._CHECKPOINT_KEY, query=True))
        except Exception:
            return False

    @classmethod
    def load_checkpoint(cls) -> bool:
        """Restore the snapshot: enabled checks + stale per-object results.
        Results show as-is until the next RUN revalidates them."""
        import json
        info = cmds.fileInfo(cls._CHECKPOINT_KEY, query=True)
        if not info:
            return False
        try:
            data = json.loads(info[0].replace('\\\\"', '"'))
        except Exception as e:
            alog("load_checkpoint parse: %s" % e)
            return False
        cls.set_checks({k: bool(v) for k, v in data.get("enabled", {}).items()},
                       run=False)
        cls.objects.clear()
        cls.refresh_objects()
        restored = data.get("objects", {})
        for t, mco in cls.objects.items():
            short = t.split("|")[-1]
            checks = restored.get(short)
            if not checks:
                continue
            for key, (cnt, metric) in checks.items():
                checker = mco.checkers.get(key)
                if checker is None:
                    continue
                checker._count = int(cnt)
                checker.metric_text = metric
                checker._ran = True   # stale display; Run re-runs (topo dirty)
        cls._checkpoint_restored = True
        alog("checkpoint restored (%d/%d objects matched)"
             % (sum(1 for t in cls.objects if t.split("|")[-1] in restored),
                len(restored))))
        cls._notify_ui()
        return True

    @classmethod
    def clear_checkpoint(cls) -> None:
        import maya.mel as mel
        try:
            mel.eval('fileInfo -remove "%s"' % cls._CHECKPOINT_KEY)
        except Exception:
            pass
        cls._checkpoint_restored = False
        cls._notify_ui()''')

# 4) run_all сбрасывает флаг restored
rep('''    @classmethod
    def run_all(cls) -> None:
        """Re-run all enabled checkers on all tracked objects."""
        if not cls._running:''',
'''    @classmethod
    def run_all(cls) -> None:
        """Re-run all enabled checkers on all tracked objects."""
        cls._checkpoint_restored = False
        if not cls._running:''')

io.open(p, "w", encoding="utf-8", newline="").write(s)
import py_compile; py_compile.compile(p, doraise=True)
print("manager ok")
