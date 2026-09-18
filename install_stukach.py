# -*- coding: utf-8 -*-
"""
STUKACH Maya Installer — drag & drop into Maya viewport or run from Script Editor.

What it does:
  1. Copies MAYA_STUKACH/ to Maya scripts directory
  2. Copies stukachDrawOverride.mll to Maya plug-ins directory
  3. Adds STUKACH shelf button
  4. Installs numpy/scipy if missing (optional)
"""
from __future__ import annotations

import os
import shutil
import sys
import subprocess

import maya.cmds as cmds

# ── Paths ─────────────────────────────────────────────────────────────────────

_SCRIPTS_DIR = cmds.internalVar(userScriptDir=True).rstrip("/").rstrip("\\")
_PLUGINS_DIR = os.path.join(os.path.dirname(_SCRIPTS_DIR), "plug-ins")
_ICONS_DIR  = os.path.join(os.path.dirname(_SCRIPTS_DIR), "prefs", "icons")
_MAYA_SCRIPTS_DST = os.path.join(_SCRIPTS_DIR, "MAYA_STUKACH")

# Source directory — auto-detect from this file or fallback to known path
try:
    _SRC_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _SRC_DIR = r"D:\AI\ZCode\Project\STUKACH\work\maya"

_PYTHON_PACKAGE = os.path.join(_SRC_DIR, "MAYA_STUKACH")
# C++ plugin: distributive layout first (plug-ins/ next to this script),
# dev build tree second (work/maya/stukach_draw/build/Release/).
_CPP_PLUGIN_CANDIDATES = (
    os.path.join(_SRC_DIR, "plug-ins", "stukachDrawOverride.mll"),
    os.path.join(_SRC_DIR, "stukach_draw", "build", "Release", "stukachDrawOverride.mll"),
)
_CPP_PLUGIN = next(
    (p for p in _CPP_PLUGIN_CANDIDATES if os.path.exists(p)),
    _CPP_PLUGIN_CANDIDATES[0],
)
_CPP_PLUGIN_DST = os.path.join(_PLUGINS_DIR, "stukachDrawOverride.mll")

# Иконка логотипа STUKACH для шельфа. Копируется в prefs/icons/, после чего
# доступна по голому имени через -image в shelfButton.
_SHELF_ICON_SRC = os.path.join(_SRC_DIR, "icons", "stukach_shelf_logo.png")
_SHELF_ICON_NAME = "stukach_shelf_logo.png"


def _copy_tree(src: str, dst: str) -> int:
    """Copy directory tree, overwriting existing. Returns file count."""
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return sum(len(files) for _, _, files in os.walk(dst))


def _install_plugin_safe(src: str, dst: str) -> str:
    """
    Копирование C++ плагина с защитой от блокировки Windows.

    На Windows загруженный .mll/.dll нельзя перезаписать (PermissionError).
    Стратегия:
      1) выгрузить плагин из Maya если загружен
      2) попытаться скопировать напрямую
      3) если файл заблокирован — переименовать старый в *.pending_delete,
         скопировать новый, старый удалится при следующем старте Maya
    Возвращает: путь назначения или raise Exception с понятным сообщением.
    """
    plugin_name = os.path.basename(dst)

    # 1) Выгрузить если загружен
    try:
        if cmds.pluginInfo(plugin_name, query=True, loaded=True):
            cmds.unloadPlugin(plugin_name, force=True)
    except Exception:
        pass

    os.makedirs(os.path.dirname(dst), exist_ok=True)

    # 2) Пробуем напрямую
    try:
        shutil.copy2(src, dst)
        return dst
    except PermissionError:
        pass

    # 3) Файл заблокирован — переносим старый в сторону, копируем новый
    try:
        pending = dst + ".pending_delete"
        if os.path.exists(pending):
            try:
                os.remove(pending)
            except Exception:
                pass
        os.rename(dst, pending)
        shutil.copy2(src, dst)
        return dst
    except Exception as e:
        raise RuntimeError(
            "Плагин '%s' заблокирован. Закройте Maya и запустите установщик заново. "
            "(подробности: %s)" % (plugin_name, e)
        )


def _install_deps():
    """Install numpy + scipy via mayapy pip."""
    mayapy = os.path.join(os.path.dirname(sys.executable), "mayapy.exe")
    if not os.path.exists(mayapy):
        mayapy = sys.executable
    try:
        subprocess.check_call([mayapy, "-m", "pip", "install", "numpy", "scipy"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _install_icon():
    """Скопировать иконку логотипа в prefs/icons/.

    Maya ищет иконки по голому имени в нескольких путях, prefs/icons — главный из них.
    После копирования иконка доступна как image="stukach_shelf_logo.png" в shelfButton.
    Возвращает True если иконка установлена, False если источник не найден.
    """
    if not os.path.exists(_SHELF_ICON_SRC):
        return False
    try:
        os.makedirs(_ICONS_DIR, exist_ok=True)
        dst = os.path.join(_ICONS_DIR, _SHELF_ICON_NAME)
        shutil.copy2(_SHELF_ICON_SRC, dst)
        return True
    except Exception:
        return False


def _add_shelf_button():
    """Add STUKACH button to the Custom shelf."""
    custom = "Custom"
    if not cmds.shelfLayout(custom, exists=True):
        custom = cmds.shelfLayout(custom, parent="ShelfLayout")

    # Remove old button if exists
    for btn in (cmds.shelfLayout(custom, query=True, childArray=True) or []):
        if cmds.shelfButton(btn, exists=True) and cmds.shelfButton(btn, query=True, label=True) == "STUKACH":
            cmds.deleteUI(btn)

    # Hot-reload + launch command
    scripts_path = _SCRIPTS_DIR.replace("\\", "/")
    plugin_path = _CPP_PLUGIN_DST.replace("\\", "/")
    cmd = (
        "import sys, maya.cmds as cmds; "
        "sys.path.insert(0, '{scripts}'); "
        "[sys.modules.pop(k, None) for k in list(sys.modules) if 'MAYA_STUKACH' in k]; "
        "[cmds.loadPlugin('{plugin}', quiet=True) for _ in [0] if __import__('os').path.exists('{plugin}')]; "
        "import MAYA_STUKACH; MAYA_STUKACH.launch()"
    ).format(scripts=scripts_path, plugin=plugin_path)

    # Иконка: своя если установлена в prefs/icons/ или есть в дистрибутиве
    # (installer копирует её до этого шага, но подстраховываемся), иначе Maya.
    icon = (_SHELF_ICON_NAME
            if (os.path.exists(os.path.join(_ICONS_DIR, _SHELF_ICON_NAME))
                or os.path.exists(_SHELF_ICON_SRC))
            else "commandButton.png")

    cmds.shelfButton(
        parent=custom,
        label="STUKACH",
        annotation="STUKACH v1.0 — mesh validation (hot-reload)",
        image=icon,
        image1=icon,
        command=cmd,
        sourceType="python",
    )


def install():
    """Run the full installation."""
    results = []

    # 1. Copy Python package
    n = _copy_tree(_PYTHON_PACKAGE, _MAYA_SCRIPTS_DST)
    results.append("Python package: %d files -> %s" % (n, _MAYA_SCRIPTS_DST))

    # 2. Copy C++ plugin (с защитой от блокировки загруженного .mll)
    if os.path.exists(_CPP_PLUGIN):
        try:
            _install_plugin_safe(_CPP_PLUGIN, _CPP_PLUGIN_DST)
            # Перезагрузить плагин в текущем сеансе, чтобы STUKACH мог работать сразу
            try:
                cmds.loadPlugin(_CPP_PLUGIN_DST, quiet=True)
            except Exception:
                pass
            results.append("C++ plugin: -> %s" % _CPP_PLUGIN_DST)
        except Exception as e:
            results.append("C++ plugin: FAILED — %s" % e)
    else:
        results.append("C++ plugin: NOT FOUND at %s (build with CMake first)" % _CPP_PLUGIN)

    # 3. Install shelf icon (до добавления кнопки — чтобы та её нашла)
    if _install_icon():
        results.append("Shelf icon: -> %s" % os.path.join(_ICONS_DIR, _SHELF_ICON_NAME))
    else:
        results.append("Shelf icon: NOT FOUND at %s (button uses stock icon)" % _SHELF_ICON_SRC)

    # 4. Add shelf button
    _add_shelf_button()
    results.append("Shelf button: added to Custom shelf")

    # 5. Install deps
    if _install_deps():
        results.append("Dependencies: numpy + scipy installed")
    else:
        results.append("Dependencies: pip failed (install manually: mayapy -m pip install numpy scipy)")

    # Report
    msg = "STUKACH v1.0 installed!\n\n" + "\n".join("  " + r for r in results)
    cmds.confirmDialog(title="STUKACH Installer", message=msg, button=["OK"])
    print("[STUKACH] " + msg.replace("\n", " | "))


# Auto-run when dragged into viewport
install()
