import bpy
import os
import sys
from bpy_extras.io_utils import ExportHelper
from .vwo_builder import build_vwo_package, build_vwt_package
from .installer import get_varwin_data_path
from .deps import VARWIN_OT_install_dependencies, get_dependency_status
from .updater import draw_updater_ui

def get_target_mesh_object(context, target_name: str = None):
    """Safely retrieves a mesh object from context, name or scene fallback."""
    if target_name and target_name in bpy.data.objects:
        o = bpy.data.objects[target_name]
        if o.type == 'MESH':
            return o
    if context.active_object and context.active_object.type == 'MESH':
        return context.active_object
    if hasattr(context, 'view_layer') and context.view_layer.objects.active and context.view_layer.objects.active.type == 'MESH':
        return context.view_layer.objects.active
    if hasattr(context, 'selected_objects'):
        selected_meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if selected_meshes:
            return selected_meshes[0]
    if hasattr(context, 'scene'):
        scene_meshes = [o for o in context.scene.objects if o.type == 'MESH']
        if scene_meshes:
            return scene_meshes[0]
    return None


# ==============================================================================
# COMMON DRAW HELPERS
# ==============================================================================

def draw_varwin_object_ui(layout, context, obj, props):
    """Draws full Varwin Object inspector UI with physics, colliders, VR flags, and export."""
    if not obj or obj.type != 'MESH':
        box = layout.box()
        box.label(text="Выберите полигональный меш (Mesh)", icon='INFO')
        return

    # Mesh Stats Header
    tri_count = len(obj.data.polygons)
    box_stats = layout.box()
    row_st = box_stats.row()
    row_st.label(text=f"Меш: {obj.name}", icon='MESH_DATA')
    if tri_count > 4000:
        box_stats.label(text=f"⚠️ {tri_count} полигонов (> 4000 limit Quest 2)", icon='ERROR')
    else:
        box_stats.label(text=f"Полигонов: ~{tri_count} (Quest 2 Ready)", icon='CHECKMARK')

    # Installation Checkbox (prominent)
    box_install = layout.box()
    row_inst = box_install.row()
    row_inst.prop(props, "direct_install_varwin", icon='IMPORT')
    detected = get_varwin_data_path()
    if props.direct_install_varwin:
        if detected:
            box_install.label(text=f"Цель: {detected}", icon='CHECKMARK')
        else:
            box_install.label(text="⚠️ VarwinData18 не найден! Проверьте путь в Preferences", icon='ERROR')

    # 1. Metadata
    box_meta = layout.box()
    box_meta.label(text="1. Метаданные объекта", icon='FILE_TEXT')
    box_meta.prop(props, "object_name_ru")
    box_meta.prop(props, "object_name_en")
    box_meta.prop(props, "description_ru")
    box_meta.prop(props, "author_name")
    box_meta.prop(props, "license_code")

    # 2. Geometry & Materials scope
    box_geo = layout.box()
    box_geo.label(text="2. Геометрия и материалы в .vwo", icon='OUTLINER_OB_MESH')

    # Selected only toggle (matching Scene template UI)
    row_sel = box_geo.row()
    row_sel.prop(props, "selected_only")

    selected_count = len([o for o in context.selected_objects if o.type == 'MESH']) if getattr(context, 'selected_objects', None) else 0
    visible_count = len([o for o in context.scene.objects if o.type == 'MESH' and not o.hide_get()]) if getattr(context, 'scene', None) else 0

    if props.selected_only:
        if selected_count > 1:
            box_geo.label(text=f"Выделено мешей для сборки: {selected_count}", icon='CHECKMARK')
        elif selected_count == 1:
            box_geo.label(text=f"Выделен 1 меш: {obj.name}", icon='OBJECT_DATA')
        else:
            box_geo.label(text=f"Нет выделенных мешей! Экспорт: {obj.name}", icon='ERROR')
    else:
        box_geo.label(text=f"Все видимые меши сцены: {visible_count} шт.", icon='HIDE_OFF')

    box_geo.label(text=f"Опорная точка (Pivot): {obj.name}", icon='PIVOT_CURSOR')

    # Slicing and separation tools (BIOS request)
    box_tools = box_geo.box()
    box_tools.label(text="Инструменты нарезки по материалам:", icon='MOD_BEVEL')
    row_split = box_tools.row(align=True)
    row_split.scale_y = 1.2
    row_split.operator("object.varwin_separate_by_material", text="Слайс по материалам", icon='UNLINKED')
    row_split.operator("object.varwin_join_selected", text="Объединить выделенные", icon='AUTOMERGE_ON')

    box_mat_opt = box_geo.box()
    box_mat_opt.label(text="Материалы и PBR-текстуры:", icon='MATERIAL')
    box_mat_opt.prop(props, "embed_textures")
    box_mat_opt.prop(props, "preserve_materials")

    # Procedural to file texture baking (Vad / BIOS request)
    box_bake = box_mat_opt.box()
    box_bake.label(text="Сделать текстуру файлом (Bake PBR):", icon='RENDER_STILL')
    row_b_params = box_bake.row(align=True)
    row_b_params.prop(props, "bake_channel", text="")
    row_b_params.prop(props, "bake_resolution", text="")
    box_bake.prop(props, "bake_auto_apply")

    row_bake_btn = box_bake.row(align=True)
    row_bake_btn.scale_y = 1.3
    row_bake_btn.operator("object.varwin_bake_texture", text="Запечь текстуру в PNG", icon='FILE_IMAGE')
    row_bake_btn.operator("object.varwin_open_textures_folder", text="", icon='FILE_FOLDER')

    # 3. Physics & Rigidbody
    box_phys = layout.box()
    box_phys.label(text="3. Физика Rigidbody (PhysX)", icon='PHYSICS')
    box_phys.prop(props, "use_rigidbody")

    if props.use_rigidbody:
        col = box_phys.column()
        col.prop(props, "mass")
        col.prop(props, "use_gravity")
        col.prop(props, "is_kinematic")

        row_drag = col.row(align=True)
        row_drag.prop(props, "drag")
        row_drag.prop(props, "angular_drag")

        col.prop(props, "collision_detection")
        col.prop(props, "interpolate")

        # Material Friction & Bounce
        box_mat = col.box()
        box_mat.label(text="Физический материал:")
        box_mat.prop(props, "bounciness")
        row_fric = box_mat.row(align=True)
        row_fric.prop(props, "dynamic_friction")
        row_fric.prop(props, "static_friction")

        # Constraints
        box_const = col.box()
        box_const.label(text="Заморозка осей (Freeze):")
        r_pos = box_const.row(align=True)
        r_pos.label(text="Позиция:")
        r_pos.prop(props, "freeze_pos_x", toggle=True)
        r_pos.prop(props, "freeze_pos_y", toggle=True)
        r_pos.prop(props, "freeze_pos_z", toggle=True)

        r_rot = box_const.row(align=True)
        r_rot.label(text="Вращение:")
        r_rot.prop(props, "freeze_rot_x", toggle=True)
        r_rot.prop(props, "freeze_rot_y", toggle=True)
        r_rot.prop(props, "freeze_rot_z", toggle=True)

    # 4. Collider Settings
    box_col = layout.box()
    box_col.label(text="4. Форма Коллайдера", icon='MOD_BEVEL')
    box_col.prop(props, "collider_type")
    box_col.prop(props, "is_trigger")

    if props.collider_type == 'BOX':
        box_col.label(text="✓ 8-вершинный Box Mesh: 100% стабильность PhysX и 0 лагов!", icon='CHECKMARK')
    elif props.collider_type == 'CONVEX':
        box_col.label(text="✓ Оптимизированный Convex Hull (<=64 верт.): лимит PhysX!", icon='CHECKMARK')
    elif props.collider_type == 'MESH':
        box_col.label(text="✓ Полый точный коллайдер (Concave): огибает стены и пол!", icon='CHECKMARK')
        box_col.label(text="ℹ️ Внутри свободно для ходьбы игрока в VR / Desktop.", icon='INFO')
    elif props.collider_type != 'NONE':
        box_col.prop(props, "auto_fit_bounds")
        if not props.auto_fit_bounds:
            if props.collider_type == 'BOX':
                box_col.prop(props, "box_size")
                box_col.prop(props, "box_center")
            elif props.collider_type == 'SPHERE':
                box_col.prop(props, "sphere_radius")
                box_col.prop(props, "sphere_center")
            elif props.collider_type == 'CAPSULE':
                box_col.prop(props, "capsule_radius")
                box_col.prop(props, "capsule_height")
                box_col.prop(props, "capsule_direction")
                box_col.prop(props, "capsule_center")

    # 5. VR Interaction Flags (Varwin Unity SDK)
    box_vr = layout.box()
    box_vr.label(text="5. Взаимодействие в VR (Varwin SDK)", icon='HAND')
    box_vr.prop(props, "grabbable")
    box_vr.prop(props, "touchable")
    box_vr.prop(props, "usable")
    box_vr.prop(props, "is_obstacle")
    box_vr.prop(props, "teleport_area")
    box_vr.separator()
    box_vr.prop(props, "disable_scene_logic")

    # 6. Quick Presets
    box_presets = layout.box()
    box_presets.label(text="Пресеты физики:", icon='PRESET')
    row_p1 = box_presets.row(align=True)
    op1 = row_p1.operator("object.varwin_apply_preset", text="Динамический (1 кг)")
    op1.preset = 'DYNAMIC_LIGHT'
    op2 = row_p1.operator("object.varwin_apply_preset", text="Тяжелый (25 кг)")
    op2.preset = 'DYNAMIC_HEAVY'

    row_p2 = box_presets.row(align=True)
    op3 = row_p2.operator("object.varwin_apply_preset", text="Статичный проп")
    op3.preset = 'STATIC_PROP'
    op4 = row_p2.operator("object.varwin_apply_preset", text="Зона-триггер")
    op4.preset = 'TRIGGER_ZONE'

    row_p3 = box_presets.row(align=True)
    op5 = row_p3.operator("object.varwin_apply_preset", text="Площадка телепорта")
    op5.preset = 'TELEPORT_FLOOR'
    op6 = row_p3.operator("object.varwin_apply_preset", text="🏛️ Помещение (Ходьба внутри)")
    op6.preset = 'ROOM_ENVIRONMENT'

    # 7. Export Options
    layout.separator()
    box_exp = layout.box()
    box_exp.label(text="Сборка и экспорт", icon='EXPORT')
    box_exp.prop(props, "apply_modifiers")
    box_exp.prop(props, "generate_preview")

    row_btn = box_exp.row()
    row_btn.scale_y = 1.6
    row_btn.operator("object.varwin_quick_export", text="⚡ Собрать и отправить в Varwin", icon='IMPORT')

    row_save = box_exp.row()
    row_save.scale_y = 1.2
    row_save.operator("object.varwin_export_vwo", text="Экспорт в файл .vwo...", icon='FILE_FOLDER')


def draw_varwin_scene_ui(layout, context, scene, scene_props):
    """Draws full Varwin Scene Template inspector UI."""
    if not scene:
        return

    # Installation Checkbox (prominent)
    box_install = layout.box()
    row_inst = box_install.row()
    row_inst.prop(scene_props, "direct_install_varwin", icon='IMPORT')
    detected = get_varwin_data_path()
    if scene_props.direct_install_varwin:
        if detected:
            box_install.label(text=f"Цель: {detected}", icon='CHECKMARK')
        else:
            box_install.label(text="⚠️ VarwinData18 не найден! Проверьте путь в Preferences", icon='ERROR')

    # 1. Scene Metadata
    box_meta = layout.box()
    box_meta.label(text="1. Метаданные сцены", icon='WORLD')
    box_meta.prop(scene_props, "scene_name_ru")
    box_meta.prop(scene_props, "scene_name_en")
    box_meta.prop(scene_props, "description_ru")
    box_meta.prop(scene_props, "author_name")

    # 2. Geometry scope
    box_geo = layout.box()
    box_geo.label(text="2. Геометрия сцены в шаблон", icon='OUTLINER_OB_MESH')
    box_geo.prop(scene_props, "selected_only")
    mesh_count = len([o for o in scene.objects if o.type == 'MESH' and not o.hide_get()])
    box_geo.label(text=f"Всего видимых мешей в сцене: {mesh_count}")

    # 3. Spawn Point
    box_spawn = layout.box()
    box_spawn.label(text="3. Точка спавна игрока в VR", icon='ORIENTATION_GIMBAL')
    box_spawn.prop(scene_props, "spawn_mode")
    if scene_props.spawn_mode == 'CUSTOM':
        box_spawn.prop(scene_props, "spawn_position")
    elif scene_props.spawn_mode == 'CURSOR':
        cur = scene.cursor.location
        box_spawn.label(text=f"3D Курсор: ({cur.x:.2f}, {cur.y:.2f}, {cur.z:.2f})", icon='RESTRICT_SELECT_OFF')
    elif scene_props.spawn_mode == 'ACTIVE_OBJECT':
        act = context.active_object
        if act:
            box_spawn.label(text=f"Объект '{act.name}': ({act.location.x:.2f}, {act.location.y:.2f}, {act.location.z:.2f})", icon='OBJECT_DATA')
        else:
            box_spawn.label(text="Активный объект не выбран!", icon='ERROR')

    box_spawn.prop(scene_props, "spawn_rotation_z")

    # 4. Environment & Lighting
    box_env = layout.box()
    box_env.label(text="4. Освещение сцены и тени", icon='LIGHT_SUN')
    box_env.prop(scene_props, "export_scene_lights")
    box_env.prop(scene_props, "light_intensity")
    box_env.prop(scene_props, "light_color")
    box_env.prop(scene_props, "light_shadows")
    if scene_props.light_shadows != 'NONE':
        box_env.prop(scene_props, "shadow_strength")

    box_amb = box_env.box()
    box_amb.label(text="Рассеянный свет (заполнение теней):", icon='WORLD')
    box_amb.prop(scene_props, "ambient_intensity")
    box_amb.prop(scene_props, "ambient_color")

    row_lp = box_env.row(align=True)
    row_lp.label(text="Пресеты света:")
    op_sun = row_lp.operator("scene.varwin_apply_lighting_preset", text="Солнце")
    op_sun.preset = 'OUTDOOR'
    op_ind = row_lp.operator("scene.varwin_apply_lighting_preset", text="Интерьер")
    op_ind.preset = 'INDOOR_BRIGHT'
    op_atm = row_lp.operator("scene.varwin_apply_lighting_preset", text="Атмосфера")
    op_atm.preset = 'DRAMATIC'

    # 5. Export Actions
    layout.separator()
    box_exp = layout.box()
    box_exp.label(text="Сборка шаблона сцены", icon='EXPORT')
    box_exp.prop(scene_props, "generate_preview")

    row_btn = box_exp.row()
    row_btn.scale_y = 1.6
    row_btn.operator("scene.varwin_quick_export_vwt", text="⚡ Собрать сцену в Varwin", icon='IMPORT')

    row_save = box_exp.row()
    row_save.scale_y = 1.2
    row_save.operator("scene.varwin_export_vwt", text="Экспорт шаблона сцены (.vwst)...", icon='FILE_FOLDER')


# ==============================================================================
# OPERATORS WITH COMPLETE FILE BROWSER DIALOG PROPERTIES
# ==============================================================================

class OBJECT_OT_varwin_export(bpy.types.Operator, ExportHelper):
    """Экспорт 3D-объекта в автономный пакет Varwin Object (.vwo) с настройками физики и VR"""
    bl_idname = "object.varwin_export_vwo"
    bl_label = "Экспорт в Varwin Object (.vwo)"
    bl_options = {'PRESET', 'REGISTER', 'UNDO'}

    filename_ext = ".vwo"
    filter_glob: bpy.props.StringProperty(
        default="*.vwo",
        options={'HIDDEN'}
    )

    target_obj_name: bpy.props.StringProperty(
        name="Целевой объект",
        default=""
    )

    # Operator properties for the File Browser right sidebar
    direct_install_varwin: bpy.props.BoolProperty(
        name="Установить в Varwin",
        default=True,
        description="Опционально: зарегистрировать в локальной библиотеке Varwin XRMS"
    )
    export_scope: bpy.props.EnumProperty(
        name="Область экспорта",
        items=[
            ("SELECTED", "Выделенные меши", "Экспортировать все выделенные меши в единый объект Varwin (или активный, если выделен 1)"),
            ("ACTIVE", "Только активный меш", "Экспортировать только текущий активный меш"),
            ("VISIBLE", "Все видимые меши сцены", "Собрать всю видимую геометрию сцены в единый объект"),
        ],
        default="SELECTED"
    )
    selected_only: bpy.props.BoolProperty(
        name="Только выделенные",
        default=True,
        description="Экспортировать только выделенные меши в единый объект Varwin (иначе активный меш)"
    )
    embed_textures: bpy.props.BoolProperty(
        name="Внедрять текстуры (PBR)",
        default=True,
        description="Автоматически извлекать и упаковывать текстуры материалов (Image Texture) в Unity AssetBundle"
    )
    preserve_materials: bpy.props.BoolProperty(
        name="Защита материалов от оверрайда Varwin",
        default=True,
        description="Предотвращает принудительное перекрашивание всей модели в один цвет стандартным контроллером цвета Varwin"
    )
    object_name_ru: bpy.props.StringProperty(name="Название (RU)", default="Объект")
    object_name_en: bpy.props.StringProperty(name="Name (EN)", default="Object")

    use_rigidbody: bpy.props.BoolProperty(name="Включить Rigidbody", default=True)
    mass: bpy.props.FloatProperty(name="Масса (кг)", default=1.0, min=0.001)
    is_kinematic: bpy.props.BoolProperty(name="Кинематический", default=False)
    use_gravity: bpy.props.BoolProperty(name="Гравитация", default=True)
    drag: bpy.props.FloatProperty(name="Сопротивление", default=0.0)
    angular_drag: bpy.props.FloatProperty(name="Угловое сопр.", default=0.05)
    collision_detection: bpy.props.EnumProperty(
        name="Collision Detection",
        items=[
            ("0", "Discrete", "Дискретный"),
            ("1", "Continuous", "Непрерывный"),
            ("2", "Continuous Dynamic", "Динамический"),
            ("3", "Continuous Speculative", "Спекулятивный"),
        ],
        default="0"
    )

    collider_type: bpy.props.EnumProperty(
        name="Коллайдер",
        items=[
            ("CONVEX", "Convex Mesh (Выпуклый)", "Выпуклый меш для отдельных предметов"),
            ("MESH", "Mesh Collider (Помещение / Полый)", "Точный полигональный вогнутый меш (для помещений и зданий)"),
            ("BOX", "Box Collider", "Параллелепипед"),
            ("SPHERE", "Sphere Collider", "Сфера"),
            ("CAPSULE", "Capsule Collider", "Капсула"),
            ("NONE", "Без коллайдера", "Отключен")
        ],
        default="CONVEX"
    )
    is_trigger: bpy.props.BoolProperty(name="Триггер (Сенсор)", default=False)

    grabbable: bpy.props.BoolProperty(name="Хват в VR (Grabbable)", default=True)
    touchable: bpy.props.BoolProperty(name="Касание (Touchable)", default=True)
    usable: bpy.props.BoolProperty(name="Использование (Usable)", default=False)
    is_obstacle: bpy.props.BoolProperty(name="Препятствие (Obstacle)", default=True)
    teleport_area: bpy.props.BoolProperty(name="Зона телепорта", default=False)

    apply_modifiers: bpy.props.BoolProperty(name="Применить модификаторы", default=True)
    generate_preview: bpy.props.BoolProperty(name="Создать превью", default=True)

    def invoke(self, context, event):
        obj = get_target_mesh_object(context)
        if obj and hasattr(obj, 'varwin'):
            p = obj.varwin
            self.target_obj_name = obj.name
            self.direct_install_varwin = p.direct_install_varwin
            self.export_scope = getattr(p, 'export_scope', 'SELECTED')
            self.selected_only = p.selected_only
            self.embed_textures = getattr(p, 'embed_textures', True)
            self.preserve_materials = getattr(p, 'preserve_materials', True)
            self.object_name_ru = p.object_name_ru or obj.name
            self.object_name_en = p.object_name_en or obj.name
            self.use_rigidbody = p.use_rigidbody
            self.mass = p.mass
            self.is_kinematic = p.is_kinematic
            self.use_gravity = p.use_gravity
            self.drag = p.drag
            self.angular_drag = p.angular_drag
            self.collision_detection = p.collision_detection
            self.collider_type = p.collider_type
            self.is_trigger = p.is_trigger
            self.grabbable = p.grabbable
            self.touchable = p.touchable
            self.usable = p.usable
            self.is_obstacle = p.is_obstacle
            self.teleport_area = p.teleport_area
            self.apply_modifiers = p.apply_modifiers
            self.generate_preview = p.generate_preview

        env_export_dir = os.environ.get("VARWIN_DEFAULT_EXPORT_DIR", "").strip()
        if env_export_dir:
            os.makedirs(env_export_dir, exist_ok=True)
            safe_obj_name = "".join(c for c in (self.object_name_en or "VarwinObject") if c.isalnum() or c in (' ', '_', '-')).strip() or "VarwinObject"
            self.filepath = os.path.join(env_export_dir, f"{safe_obj_name}.vwo")

        return super().invoke(context, event)

    def draw(self, context):
        layout = self.layout

        box_install = layout.box()
        box_install.prop(self, "direct_install_varwin", icon='IMPORT')
        detected = get_varwin_data_path()
        if self.direct_install_varwin:
            if detected:
                box_install.label(text=f"Цель: {detected}", icon='CHECKMARK')
            else:
                box_install.label(text="⚠️ VarwinData18 не найден!", icon='ERROR')

        box_meta = layout.box()
        box_meta.label(text="Метаданные", icon='FILE_TEXT')
        box_meta.prop(self, "object_name_ru")
        box_meta.prop(self, "object_name_en")

        box_geo = layout.box()
        box_geo.label(text="Геометрия и материалы в .vwo", icon='OUTLINER_OB_MESH')
        box_geo.prop(self, "selected_only")
        box_geo.prop(self, "export_scope", text="Область")
        box_geo.prop(self, "embed_textures")
        box_geo.prop(self, "preserve_materials")

        box_phys = layout.box()
        box_phys.label(text="Физика Rigidbody", icon='PHYSICS')
        box_phys.prop(self, "use_rigidbody")
        if self.use_rigidbody:
            box_phys.prop(self, "mass")
            box_phys.prop(self, "is_kinematic")
            box_phys.prop(self, "use_gravity")
            box_phys.prop(self, "drag")
            box_phys.prop(self, "collision_detection")

        box_col = layout.box()
        box_col.label(text="Коллайдер", icon='MOD_BEVEL')
        box_col.prop(self, "collider_type")
        box_col.prop(self, "is_trigger")

        box_vr = layout.box()
        box_vr.label(text="VR Взаимодействие", icon='HAND')
        box_vr.prop(self, "grabbable")
        box_vr.prop(self, "touchable")
        box_vr.prop(self, "usable")
        box_vr.prop(self, "is_obstacle")
        box_vr.prop(self, "teleport_area")

        box_opts = layout.box()
        box_opts.prop(self, "apply_modifiers")
        box_opts.prop(self, "generate_preview")

    def execute(self, context):
        obj = get_target_mesh_object(context, self.target_obj_name)
        if not obj:
            self.report({'ERROR'}, "Не найден полигональный меш (Mesh) для экспорта!")
            return {'CANCELLED'}

        # Sync back to obj.varwin
        if hasattr(obj, 'varwin'):
            p = obj.varwin
            p.direct_install_varwin = self.direct_install_varwin
            p.export_scope = self.export_scope
            p.selected_only = (self.export_scope == 'SELECTED')
            p.embed_textures = self.embed_textures
            p.preserve_materials = self.preserve_materials
            p.object_name_ru = self.object_name_ru
            p.object_name_en = self.object_name_en
            p.use_rigidbody = self.use_rigidbody
            p.mass = self.mass
            p.is_kinematic = self.is_kinematic
            p.use_gravity = self.use_gravity
            p.drag = self.drag
            p.angular_drag = self.angular_drag
            p.collision_detection = self.collision_detection
            p.collider_type = self.collider_type
            p.is_trigger = self.is_trigger
            p.grabbable = self.grabbable
            p.touchable = self.touchable
            p.usable = self.usable
            p.is_obstacle = self.is_obstacle
            p.teleport_area = self.teleport_area
            p.apply_modifiers = self.apply_modifiers
            p.generate_preview = self.generate_preview

        scope = getattr(self, 'export_scope', 'SELECTED')
        if hasattr(self, 'selected_only') and not self.selected_only and scope == 'SELECTED':
            scope = 'VISIBLE'
        if scope == 'ACTIVE':
            target_objects = [obj]
        elif scope == 'VISIBLE':
            target_objects = [o for o in context.scene.objects if o.type == 'MESH' and not o.hide_get()]
            if not target_objects:
                target_objects = [obj]
        else:  # SELECTED
            if context.selected_objects:
                target_objects = [o for o in context.selected_objects if o.type == 'MESH' and not o.hide_get()]
                if not target_objects:
                    target_objects = [obj]
            else:
                target_objects = [obj]

        try:
            res = build_vwo_package(target_objects, self, self.filepath)
            msg = f"Успешно собран .vwo ({len(target_objects)} мешей, {res['triangles']} полигонов, {res['size'] // 1024} КБ)"
            if res.get('installed'):
                msg += f" | {res.get('install_message')}"
            else:
                msg += " | Сохранен на диск"
            self.report({'INFO'}, msg)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Ошибка экспорта .vwo: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


class SCENE_OT_varwin_export_vwt(bpy.types.Operator, ExportHelper):
    """Экспорт сцены Blender в готовый шаблон сцены Varwin Scene Template (.vwst)"""
    bl_idname = "scene.varwin_export_vwt"
    bl_label = "Экспорт шаблона сцены Varwin (.vwst)"
    bl_options = {'PRESET', 'REGISTER', 'UNDO'}

    filename_ext = ".vwst"
    filter_glob: bpy.props.StringProperty(
        default="*.vwst",
        options={'HIDDEN'}
    )

    direct_install_varwin: bpy.props.BoolProperty(
        name="Установить в Varwin",
        default=True,
        description="Опционально: зарегистрировать шаблон в локальной библиотеке Varwin XRMS"
    )
    scene_name_ru: bpy.props.StringProperty(name="Название (RU)", default="Новая сцена")
    scene_name_en: bpy.props.StringProperty(name="Scene Name (EN)", default="New Scene")
    selected_only: bpy.props.BoolProperty(
        name="Только выделенные меши",
        default=False,
        description="Экспортировать только выделенные меши (иначе все видимые в сцене)"
    )
    spawn_mode: bpy.props.EnumProperty(
        name="Точка спавна",
        items=[
            ("CURSOR", "3D Курсор", "Использовать положение 3D курсора"),
            ("ACTIVE_OBJECT", "Активный объект", "Положение активного объекта"),
            ("ORIGIN", "Центр (0, 0, 0)", "Начало координат"),
        ],
        default="CURSOR"
    )
    light_intensity: bpy.props.FloatProperty(name="Яркость солнца", default=1.0, min=0.0)
    light_color: bpy.props.FloatVectorProperty(name="Цвет солнца", subtype='COLOR', default=(1.0, 0.98, 0.92))
    light_shadows: bpy.props.EnumProperty(
        name="Тени солнца",
        items=[
            ("SOFT", "Мягкие тени (Рекомендуется)", "Мягкие полупрозрачные тени от солнца"),
            ("NONE", "Без теней (Интерьер)", "Отключает тени от крыши для равномерного освещения интерьеров"),
            ("HARD", "Резкие тени", "Жесткие контрастные тени"),
        ],
        default="SOFT"
    )
    shadow_strength: bpy.props.FloatProperty(name="Плотность теней", default=0.45, min=0.0, max=1.0)
    ambient_intensity: bpy.props.FloatProperty(name="Яркость окружения (эмбиент)", default=0.70, min=0.0, max=3.0)
    ambient_color: bpy.props.FloatVectorProperty(name="Цвет рассеянного света", subtype='COLOR', default=(0.68, 0.70, 0.75))
    export_scene_lights: bpy.props.BoolProperty(
        name="Экспорт источников света",
        default=False,
        description="Переносить ли источники света из Blender в шаблон Varwin (по умолчанию выключено во избежание пересвета интерьеров)"
    )
    generate_preview: bpy.props.BoolProperty(name="Создать превью", default=True)

    def invoke(self, context, event):
        scene = context.scene
        if scene and hasattr(scene, 'varwin_scene'):
            sp = scene.varwin_scene
            self.direct_install_varwin = sp.direct_install_varwin
            self.scene_name_ru = sp.scene_name_ru
            self.scene_name_en = sp.scene_name_en
            self.selected_only = sp.selected_only
            self.spawn_mode = sp.spawn_mode if sp.spawn_mode in ('CURSOR', 'ACTIVE_OBJECT', 'ORIGIN') else 'CURSOR'
            self.light_intensity = sp.light_intensity
            self.light_color = sp.light_color
            self.light_shadows = sp.light_shadows
            self.shadow_strength = getattr(sp, 'shadow_strength', 0.45)
            self.ambient_intensity = getattr(sp, 'ambient_intensity', 0.70)
            self.ambient_color = getattr(sp, 'ambient_color', (0.68, 0.70, 0.75))
            self.export_scene_lights = getattr(sp, 'export_scene_lights', False)
            self.generate_preview = sp.generate_preview

        env_export_dir = os.environ.get("VARWIN_DEFAULT_EXPORT_DIR", "").strip()
        if env_export_dir:
            os.makedirs(env_export_dir, exist_ok=True)
            safe_scn_name = "".join(c for c in (self.scene_name_en or "SceneTemplate") if c.isalnum() or c in (' ', '_', '-')).strip() or "SceneTemplate"
            self.filepath = os.path.join(env_export_dir, f"{safe_scn_name}.vwst")

        return super().invoke(context, event)

    def draw(self, context):
        layout = self.layout

        box_install = layout.box()
        box_install.prop(self, "direct_install_varwin", icon='IMPORT')
        detected = get_varwin_data_path()
        if self.direct_install_varwin:
            if detected:
                box_install.label(text=f"Цель: {detected}", icon='CHECKMARK')
            else:
                box_install.label(text="⚠️ VarwinData18 не найден!", icon='ERROR')

        box_meta = layout.box()
        box_meta.label(text="Метаданные сцены", icon='WORLD')
        box_meta.prop(self, "scene_name_ru")
        box_meta.prop(self, "scene_name_en")

        box_geo = layout.box()
        box_geo.label(text="Геометрия сцены", icon='OUTLINER_OB_MESH')
        box_geo.prop(self, "selected_only")

        box_spawn = layout.box()
        box_spawn.label(text="Точка спавна", icon='ORIENTATION_GIMBAL')
        box_spawn.prop(self, "spawn_mode")

        box_env = layout.box()
        box_env.label(text="Освещение и тени", icon='LIGHT_SUN')
        box_env.prop(self, "export_scene_lights")
        box_env.prop(self, "light_intensity")
        box_env.prop(self, "light_color")
        box_env.prop(self, "light_shadows")
        if self.light_shadows != 'NONE':
            box_env.prop(self, "shadow_strength")
        box_env.prop(self, "ambient_intensity")
        box_env.prop(self, "ambient_color")
        box_env.prop(self, "generate_preview")

    def execute(self, context):
        scene = context.scene
        if not scene:
            self.report({'ERROR'}, "Сцена не найдена!")
            return {'CANCELLED'}

        # Sync back to scene.varwin_scene
        if hasattr(scene, 'varwin_scene'):
            sp = scene.varwin_scene
            sp.direct_install_varwin = self.direct_install_varwin
            sp.scene_name_ru = self.scene_name_ru
            sp.scene_name_en = self.scene_name_en
            sp.selected_only = self.selected_only
            sp.spawn_mode = self.spawn_mode
            sp.light_intensity = self.light_intensity
            sp.light_color = self.light_color
            sp.light_shadows = self.light_shadows
            sp.shadow_strength = self.shadow_strength
            sp.ambient_intensity = self.ambient_intensity
            sp.ambient_color = self.ambient_color
            sp.export_scene_lights = self.export_scene_lights
            sp.generate_preview = self.generate_preview

        try:
            res = build_vwt_package(scene, self, self.filepath)
            msg = f"Шаблон сцены .vwst собран ({res.get('triangles', 0)} полигонов, {res['size'] // 1024} КБ)"
            if res.get('installed'):
                msg += f" | {res.get('install_message')}"
            else:
                msg += " | Сохранен на диск"
            self.report({'INFO'}, msg)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Ошибка сборки шаблона сцены: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


class OBJECT_OT_varwin_quick_export(bpy.types.Operator):
    """Быстрый экспорт активного объекта с опциональной установкой в Varwin"""
    bl_idname = "object.varwin_quick_export"
    bl_label = "Собрать и отправить в Varwin"
    bl_description = "Мгновенно собирает .vwo и опционально регистрирует в локальной библиотеке Varwin XRMS"

    def execute(self, context):
        obj = get_target_mesh_object(context)
        if not obj:
            self.report({'ERROR'}, "Не найден полигональный меш (Mesh)!")
            return {'CANCELLED'}

        props = obj.varwin
        name = props.object_name_en or obj.name
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip() or "VarwinObject"

        env_export_dir = os.environ.get("VARWIN_DEFAULT_EXPORT_DIR", "").strip()
        if env_export_dir:
            out_dir = env_export_dir
        elif bpy.data.filepath:
            out_dir = os.path.join(os.path.dirname(bpy.data.filepath), "Exported_VWO")
        else:
            out_dir = os.path.expanduser("~/Varwin_Exported_VWO")

        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{safe_name}.vwo")

        scope = getattr(props, 'export_scope', 'SELECTED')
        if hasattr(props, 'selected_only') and not props.selected_only and scope == 'SELECTED':
            scope = 'VISIBLE'
        if scope == 'ACTIVE':
            target_objects = [obj]
        elif scope == 'VISIBLE':
            target_objects = [o for o in context.scene.objects if o.type == 'MESH' and not o.hide_get()]
            if not target_objects:
                target_objects = [obj]
        else:  # SELECTED
            if context.selected_objects:
                target_objects = [o for o in context.selected_objects if o.type == 'MESH' and not o.hide_get()]
                if not target_objects:
                    target_objects = [obj]
            else:
                target_objects = [obj]

        try:
            res = build_vwo_package(target_objects, props, out_path)
            msg = f"Объект '{safe_name}.vwo' готов ({len(target_objects)} мешей, {res['triangles']} tris, {res['size'] // 1024} КБ)"
            if res.get('installed'):
                msg += " | Добавлен в библиотеку Varwin!"
            else:
                msg += " | Сохранен в папку проекта"
            self.report({'INFO'}, msg)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Ошибка: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


class SCENE_OT_varwin_quick_export_vwt(bpy.types.Operator):
    """Быстрый экспорт шаблона сцены со всей геометрией в Varwin"""
    bl_idname = "scene.varwin_quick_export_vwt"
    bl_label = "Собрать сцену в Varwin"
    bl_description = "Мгновенно собирает .vwst геометрию и регистрирует шаблон сцены в локальной библиотеке Varwin"

    def execute(self, context):
        scene = context.scene
        if not scene or not hasattr(scene, 'varwin_scene'):
            self.report({'ERROR'}, "Свойства сцены не найдены!")
            return {'CANCELLED'}

        props = scene.varwin_scene
        name = props.scene_name_en or "SceneTemplate"
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip() or "SceneTemplate"

        env_export_dir = os.environ.get("VARWIN_DEFAULT_EXPORT_DIR", "").strip()
        if env_export_dir:
            out_dir = env_export_dir
        elif bpy.data.filepath:
            out_dir = os.path.join(os.path.dirname(bpy.data.filepath), "Exported_VWT")
        else:
            out_dir = os.path.expanduser("~/Varwin_Exported_VWT")

        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{safe_name}.vwst")

        try:
            res = build_vwt_package(scene, props, out_path)
            msg = f"Шаблон сцены '{safe_name}.vwst' готов ({res.get('triangles', 0)} tris, {res['size'] // 1024} КБ)"
            if res.get('installed'):
                msg += " | Добавлен в каталог шаблонов Varwin!"
            else:
                msg += " | Сохранен в папку проекта"
            self.report({'INFO'}, msg)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Ошибка сборки сцены: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


class OBJECT_OT_varwin_apply_preset(bpy.types.Operator):
    """Применить предустановленные параметры физики и VR к объекту"""
    bl_idname = "object.varwin_apply_preset"
    bl_label = "Применить пресет физики"

    preset: bpy.props.EnumProperty(
        items=[
            ('DYNAMIC_LIGHT', "Легкий предмет (1 кг)", "Динамический интерактивный предмет"),
            ('DYNAMIC_HEAVY', "Тяжелый объект (25 кг)", "Массивный физический объект"),
            ('STATIC_PROP', "Статичный объект", "Архитектура и декорации, не сдвигаемые физикой"),
            ('TRIGGER_ZONE', "Сенсор / Триггер", "Невидимая или прозрачная зона событий"),
            ('TELEPORT_FLOOR', "Площадка телепортации", "Поверхность пола, на которую разрешена телепортация"),
            ('ROOM_ENVIRONMENT', "Помещение / Здание (Ходьба внутри)", "Огромная комната или архитектура: полый точный меш-коллайдер, кинематика, зона телепортации"),
        ]
    )

    def execute(self, context):
        obj = get_target_mesh_object(context)
        if not obj:
            return {'CANCELLED'}
        p = obj.varwin

        if self.preset == 'DYNAMIC_LIGHT':
            p.collider_type = 'CONVEX'
            p.use_rigidbody = True
            p.mass = 1.0
            p.use_gravity = True
            p.is_kinematic = False
            p.drag = 0.05
            p.angular_drag = 0.05
            p.is_trigger = False
            p.grabbable = True
            p.touchable = True
            p.usable = False
            p.is_obstacle = True
            p.teleport_area = False
            p.disable_scene_logic = False
        elif self.preset == 'DYNAMIC_HEAVY':
            p.collider_type = 'CONVEX'
            p.use_rigidbody = True
            p.mass = 25.0
            p.use_gravity = True
            p.is_kinematic = False
            p.drag = 0.1
            p.angular_drag = 0.2
            p.is_trigger = False
            p.grabbable = True
            p.touchable = True
            p.usable = False
            p.is_obstacle = True
            p.teleport_area = False
            p.disable_scene_logic = False
        elif self.preset == 'STATIC_PROP':
            p.collider_type = 'CONVEX'
            p.use_rigidbody = True
            p.mass = 1.0
            p.use_gravity = False
            p.is_kinematic = True
            p.is_trigger = False
            p.grabbable = False
            p.touchable = True
            p.usable = False
            p.is_obstacle = True
            p.teleport_area = False
            p.disable_scene_logic = False
        elif self.preset == 'TRIGGER_ZONE':
            p.collider_type = 'BOX'
            p.use_rigidbody = True
            p.mass = 1.0
            p.use_gravity = False
            p.is_kinematic = True
            p.is_trigger = True
            p.grabbable = False
            p.touchable = True
            p.usable = False
            p.is_obstacle = False
            p.teleport_area = False
            p.disable_scene_logic = False
        elif self.preset == 'TELEPORT_FLOOR':
            p.collider_type = 'BOX'
            p.use_rigidbody = True
            p.mass = 1.0
            p.use_gravity = False
            p.is_kinematic = True
            p.is_trigger = False
            p.grabbable = False
            p.touchable = False
            p.usable = False
            p.is_obstacle = False
            p.teleport_area = True
            p.disable_scene_logic = False
        elif self.preset == 'ROOM_ENVIRONMENT':
            p.collider_type = 'MESH'
            p.use_rigidbody = True
            p.mass = 1000.0
            p.use_gravity = False
            p.is_kinematic = True
            p.is_trigger = False
            p.grabbable = False
            p.touchable = True
            p.usable = False
            p.is_obstacle = True
            p.teleport_area = True
            p.disable_scene_logic = False

        self.report({'INFO'}, f"Применен пресет: {self.preset}")
        return {'FINISHED'}


class SCENE_OT_varwin_apply_lighting_preset(bpy.types.Operator):
    """Применить готовый пресет освещения сцены"""
    bl_idname = "scene.varwin_apply_lighting_preset"
    bl_label = "Применить пресет освещения"

    preset: bpy.props.EnumProperty(
        items=[
            ('OUTDOOR', "Солнечный день (Улица)", "Яркое солнце, прозрачные мягкие тени и небесный свет"),
            ('INDOOR_BRIGHT', "Светлый интерьер", "Равномерное светлое заполнение комнат без темных углов"),
            ('DRAMATIC', "Атмосферный / Контрастный", "Контрастный свет для подземелий и мистических сцен"),
            ('STUDIO', "Студия / Равномерный", "Мягкий всенаправленный студийный свет"),
        ]
    )

    def execute(self, context):
        sp = getattr(context.scene, 'varwin_scene', None)
        if not sp:
            return {'CANCELLED'}
        if self.preset == 'OUTDOOR':
            sp.light_intensity = 1.2
            sp.light_color = (1.0, 0.98, 0.92)
            sp.light_shadows = 'SOFT'
            sp.shadow_strength = 0.45
            sp.ambient_intensity = 0.65
            sp.ambient_color = (0.65, 0.70, 0.78)
        elif self.preset == 'INDOOR_BRIGHT':
            sp.light_intensity = 0.8
            sp.light_color = (1.0, 0.96, 0.90)
            sp.light_shadows = 'NONE'
            sp.shadow_strength = 0.35
            sp.ambient_intensity = 0.85
            sp.ambient_color = (0.75, 0.75, 0.75)
        elif self.preset == 'DRAMATIC':
            sp.light_intensity = 1.4
            sp.light_color = (1.0, 0.90, 0.75)
            sp.light_shadows = 'SOFT'
            sp.shadow_strength = 0.70
            sp.ambient_intensity = 0.40
            sp.ambient_color = (0.40, 0.42, 0.50)
        elif self.preset == 'STUDIO':
            sp.light_intensity = 0.6
            sp.light_color = (1.0, 1.0, 1.0)
            sp.light_shadows = 'NONE'
            sp.shadow_strength = 0.25
            sp.ambient_intensity = 0.95
            sp.ambient_color = (0.80, 0.80, 0.80)
        self.report({'INFO'}, f"Применен пресет света: {self.preset}")
        return {'FINISHED'}


# ==============================================================================
# ==============================================================================
# UNIFIED DRAW FUNCTIONS (Tabs: Object, Scene, Presets, System)
# ==============================================================================

def draw_varwin_presets_ui(layout, context, obj):
    """Draws Quick Presets panel for physics and VR interactivity."""
    box = layout.box()
    box.label(text="Быстрые пресеты физики и VR", icon='PRESET')
    if obj:
        box.label(text=f"Целевой меш: {obj.name}", icon='OBJECT_DATA')
    else:
        box.label(text="⚠️ Выберите полигональный меш (Mesh) в 3D виде", icon='INFO')

    col = box.column(align=True)
    col.scale_y = 1.3
    op1 = col.operator("object.varwin_apply_preset", text="🎈 Легкий предмет (1 кг, Grabbable, Динамика)", icon='PHYSICS')
    op1.preset = 'DYNAMIC_LIGHT'

    op2 = col.operator("object.varwin_apply_preset", text="🏋️ Тяжелый объект (25 кг, Grabbable, Инерция)", icon='OUTLINER_OB_FORCE_FIELD')
    op2.preset = 'DYNAMIC_HEAVY'

    op3 = col.operator("object.varwin_apply_preset", text="🏛 Статичный проп (Кинематика, Препятствие)", icon='MOD_BUILD')
    op3.preset = 'STATIC_PROP'

    op4 = col.operator("object.varwin_apply_preset", text="⚡ Сенсор / Зона событий (Триггер, Без коллизий)", icon='SELECT_SET')
    op4.preset = 'TRIGGER_ZONE'

    op5 = col.operator("object.varwin_apply_preset", text="🎯 Площадка телепортации (Зона телепорта)", icon='TRACKING')
    op5.preset = 'TELEPORT_FLOOR'

    op6 = col.operator("object.varwin_apply_preset", text="🏛️ Помещение / Зал (Ходьба внутри, Полый коллайдер)", icon='HOME')
    op6.preset = 'ROOM_ENVIRONMENT'


def draw_varwin_system_ui(layout, context):
    """Draws System and SDK status integration panel."""
    box = layout.box()
    box.label(text="Статус интеграции Varwin XRMS", icon='DESKTOP')
    box.label(text=f"Платформа: {sys.platform.capitalize()} | Blender {bpy.app.version_string}")

    path = get_varwin_data_path()
    if path:
        box.label(text="Каталог VarwinData18: Обнаружен", icon='CHECKMARK')
        box.label(text=path)
        db_path = os.path.join(path, "SQLite3", "database.db")
        if os.path.isfile(db_path):
            box.label(text="База данных: SQLite3 активна", icon='CHECKMARK')
        else:
            box.label(text="База данных: database.db не найден", icon='QUESTION')
    else:
        box.label(text="VarwinData18: Не обнаружен автоматически", icon='ERROR')
        box.label(text="Укажите путь в Edit > Preferences > Add-ons > Varwin")

    # Python Dependencies
    try:
        deps = get_dependency_status()
        box_dep = layout.box()
        box_dep.label(text="Зависимости Python:", icon='CONSOLE')
        row_u = box_dep.row()
        if deps['unitypy']:
            row_u.label(text=f"UnityPy: {deps['unitypy_version']}", icon='CHECKMARK')
        else:
            row_u.label(text="UnityPy: Не найден", icon='ERROR')
            row_u.operator("varwin.install_dependencies", text="Установить", icon='IMPORT')
        row_p = box_dep.row()
        if deps['pillow']:
            row_p.label(text=f"Pillow (PIL): {deps['pillow_version']}", icon='CHECKMARK')
        else:
            row_p.label(text="Pillow (PIL): Не найден (опционально)", icon='INFO')
    except Exception:
        pass

    box_tips = layout.box()
    box_tips.label(text="Стандарты Quest 2 (Snapdragon XR2, 90 FPS)", icon='HELP')
    box_tips.label(text="• Полигонаж: 1 500 – 4 000 полигонов на предмет")
    box_tips.label(text="• Материалы: 1 PBR материал / Атлас текстур")
    box_tips.label(text="• Масштаб: 1 юнит = 1 метр в физическом мире")
    box_tips.label(text="• Пивот: в точке хвата (рукоять / центр основания)")


def draw_varwin_unified_ui(layout, context):
    """Unified master drawer for Varwin settings with sub-tab navigation."""
    scene = context.scene
    sp = getattr(scene, 'varwin_scene', None)
    if not sp:
        return

    # 2x2 Sub-tabs switcher so labels are fully visible without truncation
    col_tabs = layout.column(align=True)
    r1 = col_tabs.row(align=True)
    r1.scale_y = 1.2
    r1.prop_enum(sp, "ui_tab", "OBJECT", text="📦 Объект (.vwo)")
    r1.prop_enum(sp, "ui_tab", "SCENE", text="🌐 Сцена (.vwst)")
    r2 = col_tabs.row(align=True)
    r2.scale_y = 1.2
    r2.prop_enum(sp, "ui_tab", "PRESETS", text="⚡ Пресеты")
    r2.prop_enum(sp, "ui_tab", "SYSTEM", text="⚙ SDK & Пути")

    tab = sp.ui_tab
    if tab == 'OBJECT':
        obj = get_target_mesh_object(context)
        if obj and hasattr(obj, 'varwin'):
            draw_varwin_object_ui(layout, context, obj, obj.varwin)
        else:
            box = layout.box()
            box.label(text="Выберите полигональный меш (Mesh) в сцене", icon='INFO')
            box.label(text="Настройки объекта привязываются к активному 3D-мешу.")
    elif tab == 'SCENE':
        draw_varwin_scene_ui(layout, context, scene, sp)
    elif tab == 'PRESETS':
        obj = get_target_mesh_object(context)
        draw_varwin_presets_ui(layout, context, obj)
    elif tab == 'SYSTEM':
        draw_varwin_system_ui(layout, context)

    layout.separator()
    draw_updater_ui(layout)


# ==============================================================================
# PROPERTIES EDITOR & 3D VIEWPORT PANELS
# ==============================================================================

class PROPERTIES_PT_varwin_main(bpy.types.Panel):
    """Единая панель настроек Varwin XRMS в окне Properties (ниже всех вкладок, в секции Текстуры)"""
    bl_label = "Varwin XRMS — Настройки аддона"
    bl_idname = "PROPERTIES_PT_varwin_main"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'texture'
    bl_icon = 'PREFERENCES'

    def draw(self, context):
        draw_varwin_unified_ui(self.layout, context)


class VIEW3D_PT_varwin_main(bpy.types.Panel):
    """Единая панель настроек Varwin XRMS на боковой N-панели 3D Viewport"""
    bl_label = "Varwin XRMS"
    bl_idname = "VIEW3D_PT_varwin_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Varwin'

    def draw(self, context):
        draw_varwin_unified_ui(self.layout, context)


class VARWIN_OT_switch_to_properties(bpy.types.Operator):
    """Быстрый переход к вкладке настроек Varwin в окне Properties"""
    bl_idname = "varwin.switch_to_properties"
    bl_label = "Настройки Varwin"
    bl_description = "Перейти к вкладке настроек Varwin XRMS в окне свойств"

    def execute(self, context):
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                area.spaces.active.context = 'TEXTURE'
                area.tag_redraw()
        return {'FINISHED'}


def properties_header_draw(self, context):
    layout = self.layout
    layout.separator()
    layout.operator("varwin.switch_to_properties", text="Varwin", icon='SETTINGS')


def cleanup_header_callbacks():
    funcs = getattr(bpy.types.PROPERTIES_HT_header, "_dyn_ui_initialize", lambda: [])()
    for f in list(funcs):
        if getattr(f, '__name__', '') == 'properties_header_draw':
            try:
                bpy.types.PROPERTIES_HT_header.remove(f)
            except Exception:
                pass


class OBJECT_PT_varwin_object(bpy.types.Panel):
    """Панель параметров Varwin Object во вкладке Object Properties"""
    bl_label = "Varwin Object (.vwo)"
    bl_idname = "OBJECT_PT_varwin_object"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'

    def draw(self, context):
        obj = get_target_mesh_object(context)
        if obj and hasattr(obj, 'varwin'):
            draw_varwin_object_ui(self.layout, context, obj, obj.varwin)
            self.layout.separator()
            draw_updater_ui(self.layout)


class SCENE_PT_varwin_scene(bpy.types.Panel):
    """Панель параметров Varwin Scene во вкладке Scene Properties"""
    bl_label = "Varwin Scene Template (.vwst)"
    bl_idname = "SCENE_PT_varwin_scene"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'scene'

    def draw(self, context):
        scene = context.scene
        if scene and hasattr(scene, 'varwin_scene'):
            draw_varwin_scene_ui(self.layout, context, scene, scene.varwin_scene)
            self.layout.separator()
            draw_updater_ui(self.layout)


class OBJECT_OT_varwin_separate_by_material(bpy.types.Operator):
    """Разделяет меш на отдельные объекты по слотам материалов с удалением неиспользуемых слотов"""
    bl_idname = "object.varwin_separate_by_material"
    bl_label = "Разделить по материалам"
    bl_description = "Разбивает геометрию на отдельные меши для каждого материала (для всех выделенных объектов)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if getattr(context, 'selected_objects', None):
            return any(o.type == 'MESH' and len(o.material_slots) > 1 for o in context.selected_objects)
        obj = context.active_object
        return bool(obj and obj.type == 'MESH' and len(obj.material_slots) > 1)

    def execute(self, context):
        selected_meshes = [o for o in context.selected_objects if o.type == 'MESH'] if getattr(context, 'selected_objects', None) else []
        if not selected_meshes and context.active_object and context.active_object.type == 'MESH':
            selected_meshes = [context.active_object]

        candidates = [o for o in selected_meshes if len(o.material_slots) > 1]
        if not candidates:
            self.report({'WARNING'}, "Ни один из выделенных объектов не содержит более одного материала!")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        all_resulting_objects = [o for o in selected_meshes if o not in candidates]
        total_separated = 0
        total_pieces = 0

        for target in candidates:
            orig_name = target.name
            try:
                bpy.ops.object.select_all(action='DESELECT')
                target.select_set(True)
                context.view_layer.objects.active = target

                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.separate(type='MATERIAL')
                bpy.ops.object.mode_set(mode='OBJECT')

                pieces = [o for o in context.selected_objects if o.type == 'MESH']
                for piece in pieces:
                    context.view_layer.objects.active = piece
                    bpy.ops.object.material_slot_remove_unused()
                    if piece not in all_resulting_objects:
                        all_resulting_objects.append(piece)

                total_separated += 1
                total_pieces += len(pieces)
            except Exception as e:
                if context.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                self.report({'WARNING'}, f"Не удалось разделить '{orig_name}': {e}")
                if target not in all_resulting_objects:
                    all_resulting_objects.append(target)

        bpy.ops.object.select_all(action='DESELECT')
        for o in all_resulting_objects:
            try:
                o.select_set(True)
            except Exception:
                pass

        if all_resulting_objects:
            context.view_layer.objects.active = all_resulting_objects[0]

        self.report({'INFO'}, f"Разделено объектов: {total_separated}, получено частей: {total_pieces} (всего объектов: {len(all_resulting_objects)})")
        return {'FINISHED'}


class OBJECT_OT_varwin_join_selected(bpy.types.Operator):
    """Объединяет выделенные меши в один объект с сохранением опорной точки активного объекта"""
    bl_idname = "object.varwin_join_selected"
    bl_label = "Объединить выделенные"
    bl_description = "Объединяет выделенные полигональные объекты в единый меш (Ctrl+J) с опорной точкой активного объекта"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        meshes = [o for o in getattr(context, 'selected_objects', []) if o.type == 'MESH']
        return len(meshes) > 1

    def execute(self, context):
        act = context.active_object
        selected_meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if not selected_meshes:
            self.report({'ERROR'}, "Нет выделенных мешей!")
            return {'CANCELLED'}

        if not act or act.type != 'MESH' or act not in selected_meshes:
            act = selected_meshes[0]
            context.view_layer.objects.active = act

        count = len(selected_meshes)
        try:
            bpy.ops.object.join()
            self.report({'INFO'}, f"{count} мешей успешно объединены в '{context.active_object.name}'!")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Не удалось объединить меши: {str(e)}")
            return {'CANCELLED'}


class OBJECT_OT_varwin_bake_texture(bpy.types.Operator):
    """Запекает процедурные ноды материалов активного объекта в текстурный файл PNG"""
    bl_idname = "object.varwin_bake_texture"
    bl_label = "Запечь текстуру"
    bl_description = "Запекает процедурные шейдеры (Noise, Voronoi, ColorRamp и др.) в отдельный PNG файл на диске и опционально связывает с Principled BSDF"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == 'MESH' and obj.data.materials and any(obj.data.materials))

    def execute(self, context):
        obj = context.active_object
        props = getattr(obj, 'varwin', None)
        if not props:
            self.report({'ERROR'}, "Свойства Varwin для объекта не найдены!")
            return {'CANCELLED'}

        res = int(getattr(props, 'bake_resolution', '1024'))
        channel = getattr(props, 'bake_channel', 'DIFFUSE')
        auto_apply = getattr(props, 'bake_auto_apply', True)

        from .texture_baker import bake_object_texture
        res_data = bake_object_texture(
            obj=obj,
            resolution=res,
            bake_type=channel,
            auto_apply=auto_apply
        )

        if not res_data.get('success'):
            self.report({'ERROR'}, res_data.get('error', 'Неизвестная ошибка запекания'))
            return {'CANCELLED'}

        filepath = res_data.get('filepath', '')
        self.report({'INFO'}, f"Текстура успешно запечена в файл: {filepath}")
        return {'FINISHED'}


class OBJECT_OT_varwin_open_textures_folder(bpy.types.Operator):
    """Открывает папку с сохраненными текстурами в проводнике системы"""
    bl_idname = "object.varwin_open_textures_folder"
    bl_label = "Открыть папку текстур"
    bl_description = "Открывает директорию с текстурами (//textures или Рабочий стол) в системном файловом менеджере"

    def execute(self, context):
        import subprocess, sys
        if bpy.data.is_saved:
            target_dir = bpy.path.abspath("//textures")
        else:
            home = os.path.expanduser("~")
            desktop = os.path.join(home, "Desktop")
            target_dir = desktop if os.path.isdir(desktop) else home

        os.makedirs(target_dir, exist_ok=True)
        try:
            if sys.platform == 'win32':
                os.startfile(target_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', target_dir])
            else:
                subprocess.Popen(['xdg-open', target_dir])
            self.report({'INFO'}, f"Открыта папка: {target_dir}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'WARNING'}, f"Не удалось открыть папку: {e}")
            return {'CANCELLED'}


classes = (
    OBJECT_OT_varwin_export,
    SCENE_OT_varwin_export_vwt,
    OBJECT_OT_varwin_quick_export,
    SCENE_OT_varwin_quick_export_vwt,
    OBJECT_OT_varwin_separate_by_material,
    OBJECT_OT_varwin_join_selected,
    OBJECT_OT_varwin_bake_texture,
    OBJECT_OT_varwin_open_textures_folder,
    OBJECT_OT_varwin_apply_preset,
    SCENE_OT_varwin_apply_lighting_preset,
    VARWIN_OT_switch_to_properties,
    VARWIN_OT_install_dependencies,
    OBJECT_PT_varwin_object,
    SCENE_PT_varwin_scene,
    PROPERTIES_PT_varwin_main,
    VIEW3D_PT_varwin_main,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    cleanup_header_callbacks()
    bpy.types.PROPERTIES_HT_header.append(properties_header_draw)

def unregister():
    cleanup_header_callbacks()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

