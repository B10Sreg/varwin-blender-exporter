import bpy
import os
from .installer import get_varwin_data_path

class VarwinAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__ or "varwin_vwo_exporter"

    custom_varwin_data_path: bpy.props.StringProperty(
        name="Путь к VarwinData18",
        subtype='DIR_PATH',
        default="",
        description="Пользовательский путь к каталогу данных Varwin (если автопоиск не обнаружил папку)"
    )

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Интеграция с локальным Varwin XRMS", icon='PREFERENCES')

        detected_path = get_varwin_data_path()
        if detected_path:
            db_path = os.path.join(detected_path, "SQLite3", "database.db")
            has_db = os.path.isfile(db_path)
            row = box.row()
            if has_db:
                row.label(text=f"Каталог найден: {detected_path}", icon='CHECKMARK')
            else:
                row.label(text=f"Каталог найден (без database.db): {detected_path}", icon='QUESTION')
        else:
            box.label(text="VarwinData18 не обнаружен автоматически. Укажите путь вручную:", icon='ERROR')

        box.prop(self, "custom_varwin_data_path")
        box.label(text="Стандартные пути: ~/.config/VarwinData18 (Linux), %APPDATA%/VarwinData18 (Windows)", icon='INFO')

        # Dependencies box
        try:
            from .deps import get_dependency_status
            deps = get_dependency_status()
            box_dep = layout.box()
            box_dep.label(text="Зависимости Python (встроенный Python Blender):", icon='CONSOLE')
            row_u = box_dep.row()
            if deps['unitypy']:
                row_u.label(text=f"UnityPy: Установлен ({deps['unitypy_version']})", icon='CHECKMARK')
            else:
                row_u.label(text="UnityPy: Не найден (требуется для экспорта)", icon='ERROR')
                row_u.operator("varwin.install_dependencies", text="Установить UnityPy", icon='IMPORT')

            row_p = box_dep.row()
            if deps['pillow']:
                row_p.label(text=f"Pillow (PIL): Установлен ({deps['pillow_version']})", icon='CHECKMARK')
            else:
                row_p.label(text="Pillow (PIL): Не найден (опционально для превью)", icon='INFO')
        except Exception:
            pass


class VarwinObjectProperties(bpy.types.PropertyGroup):
    # Metadata
    object_name_ru: bpy.props.StringProperty(
        name="Название (RU)",
        default="Новый объект",
        description="Отображаемое имя объекта в библиотеке Varwin на русском языке"
    )
    object_name_en: bpy.props.StringProperty(
        name="Name (EN)",
        default="New Object",
        description="Display name of the object in Varwin library in English"
    )
    description_ru: bpy.props.StringProperty(
        name="Описание (RU)",
        default="",
        description="Краткое описание назначения объекта"
    )
    description_en: bpy.props.StringProperty(
        name="Description (EN)",
        default="",
        description="Brief description of the object"
    )
    author_name: bpy.props.StringProperty(
        name="Автор",
        default="Blender Artist",
        description="Имя автора или студии"
    )
    license_code: bpy.props.EnumProperty(
        name="Лицензия",
        items=[
            ("cc-by", "CC BY 4.0", "Creative Commons Attribution"),
            ("mit", "MIT", "MIT Open Source License"),
            ("proprietary", "Proprietary", "Коммерческая закрытая лицензия"),
        ],
        default="cc-by"
    )

    # Rigidbody Physics
    use_rigidbody: bpy.props.BoolProperty(
        name="Включить Rigidbody",
        default=True,
        description="Включить симуляцию физики твердого тела в PhysX"
    )
    mass: bpy.props.FloatProperty(
        name="Масса (кг)",
        default=1.0,
        min=0.001,
        max=100000.0,
        description="Физическая масса объекта в килограммах"
    )
    use_gravity: bpy.props.BoolProperty(
        name="Гравитация",
        default=True,
        description="Включить влияние силы тяжести"
    )
    is_kinematic: bpy.props.BoolProperty(
        name="Кинематический",
        default=False,
        description="Объект зафиксирован в пространстве и не сдвигается от внешних физических сил"
    )
    drag: bpy.props.FloatProperty(
        name="Сопротивление (Drag)",
        default=0.0,
        min=0.0,
        max=100.0,
        description="Линейное сопротивление среды при перемещении"
    )
    angular_drag: bpy.props.FloatProperty(
        name="Угловое сопр. (Angular Drag)",
        default=0.05,
        min=0.0,
        max=100.0,
        description="Вращательное сопротивление среды при кручении"
    )
    collision_detection: bpy.props.EnumProperty(
        name="Collision Detection",
        items=[
            ("0", "Discrete (Дискретная)", "Стандартный дискретный расчет столкновений"),
            ("1", "Continuous (Непрерывная)", "Для быстро движущихся тел против статичных"),
            ("2", "Continuous Dynamic", "Для быстрых тел против динамических"),
            ("3", "Continuous Speculative", "Предиктивный расчет столкновений"),
        ],
        default="0",
        description="Режим дискретизации PhysX столкновений"
    )
    interpolate: bpy.props.EnumProperty(
        name="Интерполяция",
        items=[
            ("0", "None", "Без интерполяции"),
            ("1", "Interpolate", "Сглаживание положения между физическими тактами"),
            ("2", "Extrapolate", "Экстраполяция положения на следующий кадр"),
        ],
        default="0"
    )

    # Freeze constraints
    freeze_pos_x: bpy.props.BoolProperty(name="X", default=False, description="Заморозить позицию X")
    freeze_pos_y: bpy.props.BoolProperty(name="Y", default=False, description="Заморозить позицию Y")
    freeze_pos_z: bpy.props.BoolProperty(name="Z", default=False, description="Заморозить позицию Z")
    freeze_rot_x: bpy.props.BoolProperty(name="X", default=False, description="Заморозить вращение X")
    freeze_rot_y: bpy.props.BoolProperty(name="Y", default=False, description="Заморозить вращение Y")
    freeze_rot_z: bpy.props.BoolProperty(name="Z", default=False, description="Заморозить вращение Z")

    # Physics Material
    bounciness: bpy.props.FloatProperty(
        name="Упругость (Bounciness)",
        default=0.0,
        min=0.0,
        max=1.0,
        description="Коэффициент упругости отскока при столкновениях"
    )
    dynamic_friction: bpy.props.FloatProperty(
        name="Трение скольжения",
        default=0.6,
        min=0.0,
        max=1.0,
        description="Коэффициент динамического трения"
    )
    static_friction: bpy.props.FloatProperty(
        name="Трение покоя",
        default=0.6,
        min=0.0,
        max=1.0,
        description="Коэффициент статического трения"
    )

    # Collider Settings
    collider_type: bpy.props.EnumProperty(
        name="Коллайдер",
        items=[
            ("CONVEX", "Convex Mesh (Выпуклый меш)", "Выпуклый меш-коллайдер по форме геометрии (рекомендуется)"),
            ("BOX", "Box Collider (Параллелепипед)", "Прямоугольный параллелепипед"),
            ("SPHERE", "Sphere Collider (Сфера)", "Сферический коллайдер"),
            ("CAPSULE", "Capsule Collider (Капсула)", "Капсульный коллайдер"),
            ("NONE", "Без коллайдера", "Коллизии отключены")
        ],
        default="CONVEX",
        description="Тип физического коллайдера для расчета столкновений"
    )
    is_trigger: bpy.props.BoolProperty(
        name="Триггер (Сенсор)",
        default=False,
        description="Срабатывать как триггерная зона без физического отталкивания"
    )
    auto_fit_bounds: bpy.props.BoolProperty(
        name="Авто-размер по мешу",
        default=True,
        description="Автоматически рассчитать размеры коллайдера по габаритам геометрии"
    )

    # Manual Collider Offsets & Dimensions
    box_size: bpy.props.FloatVectorProperty(
        name="Размер Box",
        size=3,
        default=(1.0, 1.0, 1.0),
        subtype="XYZ"
    )
    box_center: bpy.props.FloatVectorProperty(
        name="Центр Box",
        size=3,
        default=(0.0, 0.0, 0.0),
        subtype="TRANSLATION"
    )
    sphere_radius: bpy.props.FloatProperty(
        name="Радиус Сферы",
        default=0.5,
        min=0.001
    )
    sphere_center: bpy.props.FloatVectorProperty(
        name="Центр Сферы",
        size=3,
        default=(0.0, 0.0, 0.0),
        subtype="TRANSLATION"
    )
    capsule_radius: bpy.props.FloatProperty(
        name="Радиус Капсулы",
        default=0.25,
        min=0.001
    )
    capsule_height: bpy.props.FloatProperty(
        name="Высота Капсулы",
        default=1.0,
        min=0.001
    )
    capsule_direction: bpy.props.EnumProperty(
        name="Ось Капсулы",
        items=[
            ("0", "X", "Вдоль оси X"),
            ("1", "Y", "Вдоль оси Y"),
            ("2", "Z", "Вдоль оси Z"),
        ],
        default="1"
    )
    capsule_center: bpy.props.FloatVectorProperty(
        name="Центр Капсулы",
        size=3,
        default=(0.0, 0.0, 0.0),
        subtype="TRANSLATION"
    )

    # VR Interaction Flags (Varwin Unity SDK)
    grabbable: bpy.props.BoolProperty(
        name="Хват в VR (Grabbable)",
        default=True,
        description="Позволяет брать объект в руку контроллером в VR"
    )
    touchable: bpy.props.BoolProperty(
        name="Касание (Touchable)",
        default=True,
        description="Реагирует на физическое касание рукой или другим предметом"
    )
    usable: bpy.props.BoolProperty(
        name="Использование (Usable)",
        default=False,
        description="Реагирует на нажатие кнопки действия (триггера контроллера) при удержании"
    )
    is_obstacle: bpy.props.BoolProperty(
        name="Препятствие (Obstacle)",
        default=True,
        description="Является препятствием для луча телепортации (сквозь него нельзя телепортироваться)"
    )
    teleport_area: bpy.props.BoolProperty(
        name="Зона телепортации (Teleport Area)",
        default=False,
        description="Поверхность, на которую игрок может свободно телепортироваться"
    )

    # Export & Installation
    apply_modifiers: bpy.props.BoolProperty(
        name="Применить модификаторы",
        default=True,
        description="Запечь стеки модификаторов (Subsurf, Mirror, Bevel и др.) перед экспортом"
    )
    generate_preview: bpy.props.BoolProperty(
        name="Рендерить превью",
        default=True,
        description="Автоматически создать рендер превью 512x512 и иконку для библиотеки"
    )
    direct_install_varwin: bpy.props.BoolProperty(
        name="Установить в Varwin",
        default=True,
        description="Опционально: зарегистрировать созданный объект в локальной библиотеке Varwin XRMS"
    )


class VarwinSceneProperties(bpy.types.PropertyGroup):
    # UI Tab selector
    ui_tab: bpy.props.EnumProperty(
        name="Раздел",
        items=[
            ("OBJECT", "Объект (.vwo)", "Настройки 3D-объекта, Rigidbody, коллайдеров и VR", "OBJECT_DATA", 0),
            ("SCENE", "Сцена (.vwt)", "Настройки шаблона сцены и точки спавна", "WORLD", 1),
            ("PRESETS", "Пресеты", "Быстрые пресеты физики", "PRESET", 2),
            ("SYSTEM", "SDK & Пути", "Интеграция с Varwin XRMS и пути", "PREFERENCES", 3),
        ],
        default="OBJECT",
        description="Разделы настроек аддона Varwin"
    )

    # Scene Metadata
    scene_name_ru: bpy.props.StringProperty(
        name="Название сцены (RU)",
        default="Новая сцена",
        description="Отображаемое имя локации в библиотеке шаблонов Varwin на русском языке"
    )
    scene_name_en: bpy.props.StringProperty(
        name="Scene Name (EN)",
        default="New Scene",
        description="Display name of the scene template in English"
    )
    description_ru: bpy.props.StringProperty(
        name="Описание (RU)",
        default="",
        description="Краткое описание назначения и окружения сцены"
    )
    description_en: bpy.props.StringProperty(
        name="Description (EN)",
        default="",
        description="Brief description of the scene environment"
    )
    author_name: bpy.props.StringProperty(
        name="Автор",
        default="Blender Artist",
        description="Имя автора или студии"
    )

    # Spawn Point
    spawn_mode: bpy.props.EnumProperty(
        name="Точка спавна",
        items=[
            ("CURSOR", "3D Курсор", "Использовать текущее положение 3D курсора в Blender"),
            ("ACTIVE_OBJECT", "Активный объект", "Использовать координаты выделенного объекта"),
            ("ORIGIN", "Начало координат (0, 0, 0)", "Спавнить игрока в точке (0, 0, 0)"),
            ("CUSTOM", "Вручную (X, Y, Z)", "Задать точные координаты точки появления"),
        ],
        default="CURSOR",
        description="Определяет место появления игрока в VR"
    )
    spawn_position: bpy.props.FloatVectorProperty(
        name="Координаты спавна",
        size=3,
        default=(0.0, 0.0, 0.0),
        subtype="TRANSLATION",
        description="Точные координаты точки спавна игрока"
    )
    spawn_rotation_z: bpy.props.FloatProperty(
        name="Угол спавна (°)",
        default=0.0,
        description="Направление взгляда игрока вокруг вертикальной оси при появлении"
    )

    # Lighting & Sky
    light_intensity: bpy.props.FloatProperty(
        name="Яркость солнца",
        default=1.0,
        min=0.0,
        max=10.0,
        description="Интенсивность основного направленного источника света (Directional Light)"
    )
    light_color: bpy.props.FloatVectorProperty(
        name="Цвет солнца",
        subtype='COLOR',
        size=3,
        default=(1.0, 0.95, 0.85),
        description="Цвет основного источника света"
    )

    # Export & Installation
    generate_preview: bpy.props.BoolProperty(
        name="Рендерить превью",
        default=True,
        description="Создать рендеры обложки и миниатюры сцены для каталога шаблонов"
    )
    selected_only: bpy.props.BoolProperty(
        name="Только выделенные",
        default=False,
        description="Экспортировать только выделенные меши в шаблон сцены (иначе все видимые меши сцены)"
    )
    direct_install_varwin: bpy.props.BoolProperty(
        name="Установить в Varwin",
        default=True,
        description="Опционально: автоматически зарегистрировать шаблон сцены в локальной библиотеке Varwin XRMS"
    )


def register():
    bpy.utils.register_class(VarwinAddonPreferences)
    bpy.utils.register_class(VarwinObjectProperties)
    bpy.utils.register_class(VarwinSceneProperties)
    bpy.types.Object.varwin = bpy.props.PointerProperty(type=VarwinObjectProperties)
    bpy.types.Scene.varwin_scene = bpy.props.PointerProperty(type=VarwinSceneProperties)


def unregister():
    del bpy.types.Scene.varwin_scene
    del bpy.types.Object.varwin
    bpy.utils.unregister_class(VarwinSceneProperties)
    bpy.utils.unregister_class(VarwinObjectProperties)
    bpy.utils.unregister_class(VarwinAddonPreferences)
