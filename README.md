# Varwin VWO & Scene Exporter for Blender

[🇷🇺 Документация на русском](#-русский) | [🇬🇧 English Documentation](#-english)

---

# 🇷🇺 Русский

Профессиональный кроссплатформенный аддон для **Blender (4.0 – 5.x)**, позволяющий экспортировать 3D-модели и целые локации напрямую в автономные пакеты **Varwin Object (`.vwo`)** и **Varwin Scene Template (`.vwt`)** с полной поддержкой возможностей **Varwin Unity SDK** (PhysX Rigidbody, Colliders, VR Interaction, SubMeshes, Teleportation, Directional & Point Lighting) **без необходимости установки и запуска Unity Editor**.

Работает автономно в среде Windows, Linux и macOS.

---

## 🌟 Ключевые возможности

### 1. Интерактивные объекты (Varwin Objects `.vwo`)
- **Физика твердых тел (PhysX Rigidbody):**
  - Масса (кг), симуляция гравитации, кинематический режим (*Is Kinematic*).
  - Линейное (*Drag*) и угловое (*Angular Drag*) сопротивление.
  - Дискретизация столкновений: *Discrete, Continuous, Continuous Dynamic, Continuous Speculative*.
  - Интерполяция движения: *None, Interpolate, Extrapolate*.
  - Блокировка степеней свободы (*Freeze Position & Rotation X, Y, Z*).
- **Физические коллайдеры:**
  - **Convex Mesh:** прямое кодирование вершинного буфера без артефактов PhysX QuickHull.
  - **Box / Sphere / Capsule Collider:** автоматический расчет по Bounding Box или ручные размеры.
  - **Is Trigger:** режим сенсорной зоны для регистрации событий и логики Blockly.
- **VR Взаимодействие (XR Interaction):**
  - **Grabbable:** хват и перемещение контроллером в VR.
  - **Touchable:** регистрация физического касания рукой игрока.
  - **Usable:** действие по нажатию триггера контроллера при удержании.
  - **Obstacle:** блокировка луча телепортации.
  - **Teleport Area:** поверхность, разрешенная для перемещения телепортом.
- **Быстрые пресеты в 1 клик:**
  - 🎈 Легкий предмет (1 кг, Grabbable, Динамика)
  - 🏋️ Тяжелый объект (25 кг, Grabbable, Инерция)
  - 🏛 Статичный проп (Кинематика, Препятствие)
  - ⚡ Сенсор / Зона событий (Триггер, Без коллизий)
  - 🎯 Площадка телепортации (Walkable Floor)

### 2. Шаблоны сцен и локаций (Scene Templates `.vwt`)
- **Разделение геометрии и коллизий:**
  - Автоматическое формирование визуального меша локации (`Base`, Layer 10).
  - Выделенная физическая коллизия (`BaseCollision`, Mesh 32) с автоматическим исключением потолочных полигонов, предотвращающая застревание игрока под сводами.
  - Специализированная поверхность телепортации (`TeleportArea`, Mesh 39, Tag 20000) для плавного и точного VR-передвижения.
- **Освещение и атмосфера:**
  - Передача реального угла и кватерниона вращения солнца (`SUN` Light в Blender) в направленный свет Unity (`Directional Light_BAKED`).
  - Мягкие реалистичные тени (*Soft Shadows*, сила 0.55), устраняющие эффект «черных провалов».
  - Плоский рассеянный рассеянный свет (*Flat Ambient Mode 3*) с автобалансом цвета неба, гарантирующий корректный рендеринг на Oculus Quest 2 и PCVR.
  - Автоматический перенос точечных источников света (*Point Lights*) из Blender в сцену Unity.
- **Точка спавна игрока:**
  - По положению 3D Курсора;
  - По выделенному объекту;
  - В центре координат (0, 0, 0);
  - Точные координаты (X, Y, Z) и угол поворота взгляда (°).

### 3. PBR Материалы и Шейдеры
- Нарезка геометрии на независимые SubMeshes по слотам материалов Blender.
- Автоматическая трансляция Principled BSDF в Unity Standard Shader:
  - Base Color, Roughness, Metallic, Glossiness, Emission Color/Keywords.
- Умный ограничитель Metallic (не более 0.80) для предотвращения абсолютно черных поверхностей при отсутствии запеченных кубмапов отражений.
- Автоматический Triplanar UV Fallback для объектов без развертки.

### 4. 1-Click интеграция с Varwin XRMS
- Кроссплатформенный поиск папки `VarwinData18`:
  - **Linux:** `~/.config/VarwinData18`, `/var/opt/VarwinData18`
  - **Windows:** `%APPDATA%\VarwinData18`, `%LOCALAPPDATA%\VarwinData18`, `C:\ProgramData\VarwinData18`
  - **macOS:** `~/Library/Application Support/VarwinData18`
- Прямая распаковка и регистрация в SQLite3 базе данных `database.db`.
- Детерминированные UUID5: повторный экспорт сцены или объекта обновляет ассет на месте без дублирования в библиотеке.

---

## 📦 Установка аддона

1. Скачайте папку аддона `varwin_vwo_exporter` или упакуйте её в `.zip`.
2. В Blender откройте меню: **Edit → Preferences → Add-ons** (в Blender 4.2+ — **Get Extensions → Install from Disk...**).
3. Выберите скачанный `.zip` или папку аддона.
4. Активируйте галочку **Varwin VWO & Scene Exporter**.
5. В настройках аддона нажмите **«Установить зависимости (UnityPy)»** — библиотека будет установлена во встроенный Python Blender автоматически.

---

## 🖥️ Использование в интерфейсе Blender

- **N-панель 3D Viewport:** вкладка **Varwin** — единый центр управления объектами, сценой, пресетами и зависимостями.
- **Вкладка Object Properties:** панель **Varwin Object (.vwo)** для настройки физики, коллайдеров и VR-хвата выбранного меша.
- **Вкладка Scene Properties:** панель **Varwin Scene Template (.vwt)** для настройки точки спавна, солнца, теней и автоустановки локации.
- **Меню экспорта:**
  - `File → Export → Varwin Object (.vwo)`
  - `File → Export → Varwin Scene Template (.vwt)`

---

## 🐍 Использование в скриптах (Python CLI / Background Mode)

Аддон поддерживает полную автоматизацию пакетной обработки через Python:

```python
import bpy
from varwin_vwo_exporter.vwo_builder import build_vwo_package, build_vwt_package
from varwin_vwo_exporter.properties import register as register_props

register_props()

# 1. Экспорт отдельного объекта
obj = bpy.data.objects['MyHeroGauntlet']
props = obj.varwin
props.object_name_ru = "Перчатка Резонанса"
props.grabbable = True
build_vwo_package(obj, props, "/path/to/gauntlet.vwo")

# 2. Экспорт локации
scene = bpy.context.scene
sprops = scene.varwin_scene
sprops.scene_name_ru = "Эфирный Разлом"
sprops.spawn_position = (-35.0, 0.0, 2.5)
sprops.light_shadows = "SOFT"
build_vwt_package(scene, sprops, "/path/to/rift_location.vwt")
```

Запуск в фоновом режиме:
```bash
blender --background scene.blend --python export_script.py
```

---

# 🇬🇧 English

A professional Blender add-on (Blender 4.0 – 5.x) enabling direct export of 3D assets and environments into standalone **Varwin Object (`.vwo`)** and **Varwin Scene Template (`.vwt`)** packages with complete **Varwin Unity SDK** feature set without opening or installing the Unity Editor.

Runs natively on **Windows, Linux, and macOS**.

---

## 🌟 Highlights

- **Complete Unity SDK Parity:**
  - PhysX Rigidbody (Mass, Gravity, IsKinematic, Linear/Angular Drag, Constraints, Collision Detection Modes).
  - Colliders (Convex Mesh, Box, Sphere, Capsule, Trigger zones).
  - XR Interaction (Grabbable, Touchable, Usable, Obstacle, Teleport Area).
  - 1-Click VR & Physics Presets.
- **Scene Templates (`.vwt`):**
  - Smart geometry splitting: Visual mesh (`Base`), overhead-free physical collisions (`BaseCollision`), and dedicated locomotion surface (`TeleportArea`, Tag 20000).
  - Directional Sun extraction: synchronizes Blender `SUN` rotation to Unity's directional light with soft daylight shadows (strength 0.55).
  - Flat ambient mode 3: prevents pitch-black surfaces on mobile VR (Meta Quest 2) and PCVR.
  - Point Light injection from Blender into the Unity scene.
  - Configurable VR Player spawn points.
- **PBR Multi-Material Pipeline:**
  - Automatic SubMesh segmentation per material slot.
  - Translation of Principled BSDF into Unity Standard Shader (Color, Metallic, Roughness, Emission).
  - Metallic limiter (≤ 0.80) to eliminate black reflection artifacts without baked cubemaps.
  - Triplanar UV fallback for procedural meshes.
- **Direct 1-Click Varwin XRMS Integration:**
  - Automatic OS-wide detection of `VarwinData18`.
  - Direct installation into SQLite3 database (`database.db`) and asset storage.
  - Deterministic UUID5 generation ensuring clean in-place updates.

---

## 📦 Installation

1. Download or archive the `varwin_vwo_exporter` folder as `.zip`.
2. In Blender: **Edit → Preferences → Add-ons** (or **Install from Disk...** in Blender 4.2+).
3. Select the add-on package and enable **Varwin VWO & Scene Exporter**.
4. In add-on preferences, click **"Install Dependencies (UnityPy)"** for 1-click automatic installation.

---

## 📄 License
GPL-3.0-or-later. Created by B10Sreg & Antigravity.
