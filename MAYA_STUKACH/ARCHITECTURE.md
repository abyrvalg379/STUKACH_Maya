# STUKACH for Maya

Maya-версия аддона-валидатора STUKACH. Порт с Blender.
**Maya 2022+ · Python 3.11 · PySide2/PySide6 · автор: Maksim Kovalev · версия 1.0.0**

---

## Зависимости

Помимо Maya API и PySide, требуется **numpy** и **scipy** (для symmetry, invalid_normals,
UV-чеков и duplicate_verts). Установка в Maya Python:

```
"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" -m pip install numpy scipy
```

Ставится в user site-packages (`C:\Users\<user>\AppData\Roaming\Python\Python311\site-packages`).
Без них часть чекеров будет сообщать об отсутствии библиотеки, остальные продолжат работать.

---

## Файлы

| Файл | Роль |
|---|---|
| `core.py` | Классы чекеров (32 шт.) + `CHECK_TYPES` + `CHECK_CATEGORIES` + `check_scene_units()` |
| `manager.py` | `MayaCheckObject` (per-object), `MayaCheck` (singleton manager, scriptJob callbacks, scope modes, active_check) |
| `overlay.py` | Двухрежимный viewport overlay: single-check (per-face vertex colours) + overview (display layers) |
| `ui.py` | Qt панель: `StukachPanel`, кнопки Show/Sel, scope selector, overlay toggle |
| `__init__.py` | Точка входа: `import MAYA_STUKACH; MAYA_STUKACH.launch()` |

### Вне пакета (рядом с установщиком `maya/`)

| Файл | Роль |
|---|---|
| `install_stukach.py` | **Активный установщик** (drag & drop в viewport). Копирует пакет + плагин + иконку, ставит shelf-кнопку, тянет numpy/scipy через mayapy pip |
| `icons/stukach_shelf_logo.png` | Иконка логотипа для кнопки шельфа (см. [Иконка шельфа](#иконка-шельфа)) |
| `stukach_draw/` | Исходники C++ плагина VP2 DrawOverride (CMake + VS 2022) |
| `stukach_maya_install.md` | Документация по установке (в т.ч. старая `.mod`-схема) |

---

## Установка

### Основной способ — drag & drop инсталлятор

Перетащить `maya/install_stukach.py` в Maya viewport. Скрипт выполнит `install()`:
1. Скопирует пакет `MAYA_STUKACH/` в `Documents/maya/2025/scripts/`
2. Скопирует C++ плагин `stukachDrawOverride.mll` в `plug-ins/` (с защитой от блокировки загруженного `.mll` — выгружает, переименовывает в `.pending_delete` если нужно)
3. Скопирует иконку `stukach_shelf_logo.png` в `prefs/icons/`
4. Создаст shelf-кнопку `STUKACH` на шельфе `Custom` (hot-reload команда)
5. Установит `numpy`+`scipy` через `mayapy -m pip`

Результат — диалог с отчётом по каждому шагу.

### Ручной способ

1. Скопировать папку `MAYA_STUKACH` в `Documents/maya/scripts/`
2. Установить зависимости: `mayapy -m pip install numpy scipy`
3. В Script Editor (Python):
```python
import MAYA_STUKACH
MAYA_STUKACH.launch()
```
4. Или добавить кнопку на shelf с этим кодом (см. `install_stukach.py` → `_add_shelf_button`).

---

## Иконка шельфа

Кастомная иконка `stukach_shelf_logo.png` (1040×1024, RGBA, pixel-art) ставится
автоматически инсталлятором. Источник — `maya/icons/stukach_shelf_logo.png`,
копируется в `Documents/maya/2025/prefs/icons/` (главный путь поиска иконок Maya).

**Поведение `install_stukach.py`:**
- `_install_icon()` копирует PNG в `prefs/icons/` (шаг 3 `install()`, до создания shelf-кнопки)
- `_add_shelf_button()` ставит `image`/`image1` = `stukach_shelf_logo.png` если файл
  найден в `prefs/icons/`, иначе fallback на `commandButton.png` (стандартная Maya)
- Отчёт в диалоге: `Shelf icon: -> .../prefs/icons/stukach_shelf_logo.png` или
  `Shelf icon: NOT FOUND ... (button uses stock icon)`

**Сопровождение иконки:**
- Исходник лежит в `D:\AI\ZCode\Project\STUKACH\logo\` (`stukach_shelf_logo.png` для кнопки,
  `stukach_logo.png` для документации/окон)
- Рабочая копия — `maya/icons/stukach_shelf_logo.png` (рядом с инсталлятором,
  коммитится в репозиторий)
- При замене PNG: обновить оба места и перетащить `install_stukach.py` повторно

**Ручное обновление без реинсталла** (например, при правке PNG):
```bash
# Копировать в активный путь иконок Maya
cp "D:/AI/ZCode/Project/STUKACH/maya/icons/stukach_shelf_logo.png" \
   "C:/Users/mkova/Documents/maya/2025/prefs/icons/stukach_shelf_logo.png"
```
Перезапустить Maya — новая иконка подхватится автоматически.

**Замечание о размере:** Maya масштабирует PNG под кнопку (35×34 px) сама через
`-useAlpha 1`. Иконка 1040×1024 даёт чёткий пиксель-арт кроп; если планируется
текст или мелкие детали — рекомендуется править исходник в `logo/`, а не в
`maya/icons/` (там только рабочая копия).

---

## Архитектура

### Отличия от Blender-версии

| Blender | Maya |
|---|---|
| `bmesh` | `MFnMesh`, `MItMeshPolygon`, `MItMeshEdge`, `MItMeshVertex` |
| `depsgraph_update_post` | `scriptJob(event=["SelectionChanged", ...])` |
| `draw_handler_add` (GPU overlay) | **display layers** (`overlay.py`) — tint объектов по severity |
| Blender N-panel | Qt `QWidget` floating панель (parented to Maya main window) |
| `foreach_get` | `MFnMesh.getPoints()`, `getUVs()` |

### Viewport overlay — два режима (вместо GPU overlays)

В Maya нет простого API для кастомной отрисовки в viewport из Python (нужен C++
`MPxDrawOverride`). Решение — **два режима** в `overlay.py`, переключаемых кнопкой
**Show** в чек-строке:

**1. Single-check overlay (информативный, аналог Blender face-fill):**
Клик по **Show** на чек-строке → фокус на одном чеке. Все bad-компоненты этого
чека красятся **красным через per-face vertex colours** (`MFnMesh.setFaceVertexColors`,
batch-вызов — один на меш, ~1с на всю сцену вместо зависания). Остальные faces —
тёмно-серые. Component resolution: `face` → сам face; `edge` → connected faces;
`vertex` → incident faces (`getConnectedFaces`). Повторный клик по Show → выход
в overview. Кнопка Sel остаётся для Maya-выделения bad-компонентов активного объекта.

**2. Overview overlay (быстрый обзор «где проблемы»):**
Без активного чека. Каждый объект → display layer по severity:
- `STUKACH_BLOCKERS` — красный `(0.85, 0.30, 0.30)` — объекты с BLOCKER count > 0
- `STUKACH_WARNINGS` — жёлтый `(0.85, 0.65, 0.30)` — WARNING count > 0 (без blockers)
- чистые → `defaultLayer` (без подсветки). INFO не влияет на tint.

**Lifecycle** (`manager.py`): `start()` → `overlay.create()`,
`run_all()`/`set_active_check()` → `overlay.update(objects)`, `stop()` →
`overlay.clear()`. Backup/restore: перед покраской запоминаются существующие
color sets + `displayColors`; при выходе/stop всё восстанавливается — ассет не
повреждается. Чекбокс **Viewport** в панели отключает tint без остановки валидации.

### Checker interface

```python
class BaseCheck(ABC):
    severity: str          # "BLOCKER" | "WARNING" | "INFO"
    
    def run(self, dag_path: om.MDagPath) -> None: ...
    def select(self) -> None: ...        # cmds.select(bad_components)
    def reset(self) -> None: ...
    
    count:           int
    bad_components:  list[str]           # ["mesh.f[0]", "mesh.e[5]", ...]
    metric_text:     str
```

### MayaCheck lifecycle

1. `MayaCheck.start(ui_callback)` → сброс `_enabled_checks` к дефолту, `overlay.create()`,
   регистрирует `scriptJob` (SelectionChanged, SceneOpened, NewSceneOpened), `refresh_objects()`, `run_all()`
2. `SelectionChanged` → (только в SELECTED scope) `refresh_objects()` + `run_all()`
3. `run_all()` → `mco.run_enabled()` для каждого tracked объекта + `overlay.update(objects)`
4. UI callback → `StukachPanel.refresh()`
5. `MayaCheck.stop()` → убивает scriptJobs, очищает objects, `overlay.clear()`

### Дефолтные чеки

При RUN включаются все BLOCKER + WARNING (15 шт.), INFO выключены (3 шт.):
- **OFF:** `poles`, `origin_at_zero`, `uv_udim_ready` (шумные на реальном ассете)
- Задаётся в `_DEFAULT_ENABLED` (`manager.py`)

### Scope modes

`MayaCheck.scope` — `"SCENE"` (по умолчанию) или `"SELECTED"`:
- **SCENE** — тречить все mesh-transforms сцены (через `cmds.ls(type='mesh')` → parent)
- **SELECTED** — только выбранные; реагирует на `SelectionChanged`
Переключается кнопками **Scene / Selected** в панели. При смене — `objects.clear()` + `refresh_objects()` + `run_all()`.

### Структура данных

```python
MayaCheck.objects: dict[str, MayaCheckObject]   # transform_name → mco
MayaCheck._enabled_checks: dict[str, bool]      # key → enabled (reset to _DEFAULT_ENABLED on start)
MayaCheck.scope: str                            # "SCENE" | "SELECTED"

MayaCheckObject.checkers: dict[str, BaseCheck]  # key → checker instance
MayaCheckObject.enabled:  dict[str, bool]       # key → enabled (per-object copy)
```

---

## CHECK_CATEGORIES

```python
CHECK_CATEGORIES = {
    "TOPOLOGY":   ("non_manifold", "boundary_edges", "isolated_verts", "duplicate_verts",
                   "face_aspect_ratio", "triangles", "ngons", "poles", "zero_area",
                   "flipped_normals", "invalid_normals"),
    "TRANSFORMS": ("non_applied_transform", "scale", "construction_history", "origin_at_zero"),
    "SYMMETRY":   ("symmetry_x", "symmetry_y", "symmetry_z"),
    "UV":         ("uv_single_set", "uv_udim_ready", "uv_udim_bounds", "uv_material_udim",
                   "uv_overlap", "uv_micro_shell", "uv_stretch", "uv_texel_density", "uv_padding"),
    "NAMING":     ("obj_naming", "mat_numbering"),
    "MATERIALS":  ("mat_suffix", "mat_assignment", "missing_textures"),
}
# + check_scene_units() — scene-level, не BaseCheck, вызывается напрямую из UI
```

---

## Статус чекеров (32 BaseCheck + 1 scene-level)

### TOPOLOGY (11)

| Чек | Механизм | Severity | numpy/scipy |
|---|---|---|---|
| `triangles` | `polygonVertexCount() == 3` | WARNING | — |
| `ngons` | `polygonVertexCount() > 4` | BLOCKER | — |
| `non_manifold` | `len(getConnectedFaces()) > 2` | BLOCKER | — |
| `zero_area` | `getArea() < 1e-10` | BLOCKER | — |
| `poles` | `numConnectedEdges()` (3=N, 5=E, >5) | INFO | — |
| `isolated_verts` | `numConnectedEdges() == 0` | WARNING | — |
| `boundary_edges` | `len(getConnectedFaces()) == 1` | WARNING | — |
| `duplicate_verts` | `scipy.spatial.cKDTree.query_pairs(r=1e-5)`; NaN-вершины пропускаются | BLOCKER | scipy |
| `face_aspect_ratio` | ratio пар противоположных рёбер квадра > 6.0 | INFO | — |
| `flipped_normals` | duplicate mesh + `polyNormal` conform, сравнение dot<0 | WARNING | — |
| `invalid_normals` | locked normals: len²<1e-12 или dot(custom,face)<0 | WARNING | — |

### TRANSFORMS (4)

| Чек | Механизм | Severity |
|---|---|---|
| `non_applied_transform` | rotate attrs != 0 | BLOCKER |
| `scale` | scale attrs != 1 | BLOCKER |
| `construction_history` | `listHistory(pruneDagObjects=True)` | WARNING |
| `origin_at_zero` | translate attrs != 0 | INFO |

### SYMMETRY (3)

| Чек | Механизм | Severity | numpy |
|---|---|---|---|
| `symmetry_x` | numpy: round→int64 grid→pack→searchsorted mirror-key | INFO | numpy |
| `symmetry_y` | то же, axis=1 | INFO | numpy |
| `symmetry_z` | то же, axis=2 | INFO | numpy |

### UV (9)

| Чек | Механизм | Severity | numpy |
|---|---|---|---|
| `uv_single_set` | `getUVSetNames()` count != 1 | WARNING | — |
| `uv_udim_ready` | UV coords в [0..10]×[0..10] | INFO | — |
| `uv_udim_bounds` | face spanит > 1 UDIM-тайл | BLOCKER | — |
| `uv_material_udim` | тайл → set шейдеров, len > 1 | BLOCKER | — |
| `uv_overlap` | Union-Find islands → 2D grid 128² → AABB → точный tri-overlap | BLOCKER | — (pure Python) |
| `uv_micro_shell` | island area < 1e-5 (Union-Find) | WARNING | numpy |
| `uv_stretch` | `\|mesh_angle - uv_angle\| > 0.5 rad` (векторизованный) | WARNING | numpy |
| `uv_texel_density` | `TD = tex×√uv_area/(√world_area×100×scale)` | INFO | — |
| `uv_padding` | spatial-hash shell-to-shell (16px) + tile-border (8px) | INFO | — (pure Python) |

### NAMING (2) / MATERIALS (3)

| Чек | Механизм | Severity |
|---|---|---|
| `obj_naming` | regex `^[a-z][a-z0-9_]*$` | WARNING |
| `mat_numbering` | regex `\.\d{3,}$` на именах материалов | WARNING |
| `mat_suffix` | endswith("_mat") | WARNING |
| `mat_assignment` | faces с default/no shader | BLOCKER |
| `missing_textures` | `file` ноды + `os.path.exists` | BLOCKER |

### Scene-level (не BaseCheck)

| Чек | Механизм |
|---|---|
| `check_scene_units()` | `currentUnit(linear=fullName) == 'meter'`, `angle == 'deg'` |

---

## Добавить новый чек — 4 шага

1. `core.py` — класс `: BaseCheck`, реализовать `run(dag_path)`
2. `core.py` — добавить в `CHECK_TYPES` + `CHECK_CATEGORIES`
3. `ui.py` — добавить display name в `_CHECK_DISPLAY_NAMES`
4. При необходимости — добавить в `_YELLOW_THRESHOLDS`

---

## TODO (не реализовано в v2.0)

- **Coordinator Mode** + severity filter (Фаза 3)
- **Publish blocking / pre-flight** — FBX экспорт с блокировкой при BLOCKER (Фаза 3)
- **Экспорт отчётов** (JSON/CSV/HTML) — прямая адаптация из Blender (Фаза 3)
- **Naming policy** — configurable prefix/suffix (Фаза 3)
- **Fix operators** — freezeTransforms, deleteHistory, polyMergeVertex (Фаза 3)
- **uv_padding cross-object** — сейчас per-object; Blender имеет `run_global_uv_padding` registry
- **z_fighting** — единственный чек из Blender не перенесён (требует inter-object BVH)
