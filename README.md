# Varwin VWO & Scene Exporter for Blender

[🇷🇺 Русский](#-русский) | [🇬🇧 English](#-english)

---

# 🇷🇺 Русский

Профессиональный аддон прямого экспорта 3D-моделей и шаблонов сцен из **Blender (4.0 - 4.2+ LTS)** в автономные пакеты **Varwin Object (`.vwo`)** и **Varwin Scene Template (`.vwt`)** со всеми возможностями **Varwin Unity SDK** без необходимости установки или запуска Unity Editor.

Работает полностью автономно на **Windows, Linux и macOS**.

---

## 🚀 Основные возможности

### 1. Полная замена Varwin Unity SDK внутри Blender:
- **Физика твердых тел (PhysX Rigidbody):**
  - Масса (кг), гравитация, кинематический режим (Is Kinematic).
  - Линейное (Drag) и угловое (Angular Drag) сопротивление среды.
  - Режимы дискретизации столкновений: *Discrete, Continuous, Continuous Dynamic, Continuous Speculative*.
  - Интерполяция движения (*None, Interpolate, Extrapolate*).
  - Заморозка степеней свободы (*Freeze Position & Rotation X, Y, Z*).
- **Физические материалы:**
  - Коэффициенты упругости (*Bounciness*), динамического и статического трения (*Friction*).
- **Физические коллайдеры:**
  - **Convex Mesh (Выпуклый меш):** бинарная генерация вершинных буферов с прямым шагом без искажений PhysX QuickHull.
  - **Box Collider, Sphere Collider, Capsule Collider:** автоматический расчет габаритов по геометрии или ручная настройка.
  - **Триггер (Is Trigger):** сенсорные зоны для регистрации событий в Blockly.
- **VR Взаимодействие (XR Interaction Flags):**
  - **Grabbable (Хват):** возможность брать предмет в руку контроллером VR.
  - **Touchable (Касание):** реакция на физическое касание рукой или другим предметом.
  - **Usable (Использование):** реакция на нажатие триггера контроллера при удержании.
  - **Obstacle (Препятствие):** блокировка луча телепортации.
  - **Teleport Area (Площадка телепортации):** поверхность, на которую разрешена телепортация игрока.
- **Поддержка многоматериальности (Multi-Material SubMeshes):**
  - Нарезка полигонов на независимые сабмеши по слотам материалов Blender.
  - Клонирование и настройка PBR Standard шейдеров (Base Color, Metallic, Roughness/Smoothness, Emission).
  - Адаптивное ограничение Metallic для исключения черных отражений при отсутствии запеченных кубмапов.

### 2. Экспорт шаблонов сцен (Scene Templates `.vwt`):
- Экспорт всей геометрии окружения и архитектуры локации в единый шаблон мира.
- Настройка точки спавна игрока в VR:
  - По текущему 3D Курсору;
  - По положению активного объекта;
  - В начале координат (0, 0, 0);
  - Ручные точные координаты (X, Y, Z) и угол взгляда игрока.
- Настройка солнечного освещения (*Directional Light Realtime*) и атмосферы (*Ambient*).
- Автоматическая генерация превью 512x512 и миниатюр для библиотеки Varwin.

### 3. Кроссплатформенность и интеграция с Varwin XRMS:
- **Кроссплатформенный автопоиск `VarwinData18`:**
  - Windows: `%APPDATA%\VarwinData18`, `%LOCALAPPDATA%\VarwinData18`, `C:\ProgramData\VarwinData18`
  - Linux: `~/.config/VarwinData18`, `/var/opt/VarwinData18`
  - macOS: `~/Library/Application Support/VarwinData18`
- **Прямая регистрация в базе данных SQLite3:**
  - При включенном чекбоксе *«Установить в Varwin»* объект или шаблон сцены мгновенно регистрируются в локальной библиотеке.
  - Использование детерминированных UUID гарантирует, что повторный экспорт обновляет ассет на месте без создания дубликатов.
- **Автономный экспорт на диск:**
  - При отключенном чекбоксе собирается чистый файл `.vwo` или `.vwt`, готовый для передачи клиентам или загрузки через веб-интерфейс Varwin RMS.

---

## 📦 Установка

1. Скачайте репозиторий в виде `.zip` архива.
2. В Blender откройте: `Edit -> Preferences -> Add-ons`.
3. Нажмите кнопку **Install...** (или стрелочку в правом верхнем углу в Blender 4.2 -> *Install from Disk...*) и выберите скачанный `.zip`.
4. Включите галочку напротив **Varwin VWO & Scene Exporter**.
5. Нажмите кнопку **«Установить зависимости (UnityPy)»** в настройках аддона (библиотека установится во встроенный Python Blender автоматически в 1 клик).

---

## 🖥️ Где находятся настройки в Blender

1. **Боковая N-панель 3D Viewport:**
   - Нажмите клавишу **`N`** в 3D окне и перейдите на вкладку **Varwin**. Здесь доступен единый пульт управления объектом, сценой, пресетами и статусом SDK.
2. **Окно свойств (Properties):**
   - **Для объекта:** вкладка *Object Properties* (иконка оранжевого куба) -> панель *Varwin Object (.vwo)*.
   - **Для сцены:** вкладка *Scene Properties* (иконка конуса и сферы) -> панель *Varwin Scene Template (.vwt)*.
   - **Единые настройки:** вкладка *Texture* (нижний значок в столбце) или кнопка *[ ⚙ Varwin ]* в шапке окна Properties.
3. **Меню экспорта:**
   - `File -> Export -> Varwin Object (.vwo)`
   - `File -> Export -> Varwin Scene Template (.vwt)`

---

# 🇬🇧 English

A professional Blender add-on (Blender 4.0 - 4.2+ LTS) for direct export of 3D models and scene environments into **Varwin Object (`.vwo`)** and **Varwin Scene Template (`.vwt`)** packages, fully supporting the **Varwin Unity SDK** feature set without requiring Unity Editor.

Runs seamlessly on **Windows, Linux, and macOS**.

## 🌟 Key Features
- **Full Unity SDK parity:** PhysX Rigidbody (Mass, Gravity, IsKinematic, Drag, Constraints), Box/Sphere/Capsule/Convex colliders, VR interactions (Grabbable, Touchable, Usable, Obstacle, Teleport Area).
- **Multi-material support:** Preserves multiple PBR material slots with automatic Unity Standard Shader configuration.
- **Scene Templates (`.vwt`):** Export entire levels with VR player spawn points, realtime lighting, and auto-generated preview thumbnails.
- **Direct Varwin XRMS integration:** Auto-detects local `VarwinData18` directory on all operating systems and registers assets directly into SQLite3.
- **Deterministic GUIDs:** Re-exporting updates existing assets in place without cluttering the library with duplicate entries.
- **1-Click Dependency Installer:** Automatically installs `UnityPy` into Blender's bundled Python environment.

---

## 📄 License
This project is licensed under the GNU General Public License v3.0 (GPL-3.0).
