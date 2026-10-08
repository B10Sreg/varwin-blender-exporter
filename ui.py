import bpy
import os
import sys
from bpy_extras.io_utils import ExportHelper
from .vwo_builder import build_vwo_package, build_vwt_package
from .installer import get_varwin_data_path
from .deps import VARWIN_OT_install_dependencies, get_dependency_status

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

    # 2. Physics & Rigidbody
    box_phys = layout.box()
    box_phys.label(text="2. Физика Rigidbody (PhysX)", icon='PHYSICS')
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

    # 3. Collider Settings
    box_col = layout.box()
    box_col.label(text="3. Форма Коллайдера", icon='MOD_BEVEL')
    box_col.prop(props, "collider_type")
    box_col.prop(props, "is_trigger")

    if props.collider_type != 'NONE':
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

    # 4. VR Interaction Flags (Varwin Unity SDK)
    box_vr = layout.box()
    box_vr.label(text="4. Взаимодействие в VR (Varwin SDK)", icon='HAND')
    box_vr.prop(props, "grabbable")
    box_vr.prop(props, "touchable")
    box_vr.prop(props, "usable")
    box_vr.prop(props, "is_obstacle")
    box_vr.prop(props, "teleport_area")

    # 5. Quick Presets
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

    # 6. Export Options
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
    box_env.label(text="4. Освещение сцены", icon='LIGHT_SUN')
    box_env.prop(scene_props, "light_intensity")
    box_env.prop(scene_props, "light_color")

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
    row_save.operator("scene.varwin_export_vwt", text="Экспорт шаблона сцены (.vwt)...", icon='FILE_FOLDER')


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
            ("CONVEX", "Convex Mesh", "Выпуклый меш"),
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

        try:
            res = build_vwo_package(obj, self, self.filepath)
            msg = f"Успешно собран .vwo ({res['triangles']} полигонов, {res['size'] // 1024} КБ)"
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
    """Экспорт сцены Blender в готовый шаблон сцены Varwin Scene Template (.vwt)"""
    bl_idname = "scene.varwin_export_vwt"
    bl_label = "Экспорт шаблона сцены Varwin (.vwt)"
    bl_options = {'PRESET', 'REGISTER', 'UNDO'}

    filename_ext = ".vwt"
    filter_glob: bpy.props.StringProperty(
        default="*.vwt",
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
            self.generate_preview = sp.generate_preview

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
        box_env.label(text="Освещение", icon='LIGHT_SUN')
        box_env.prop(self, "light_intensity")
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
            sp.generate_preview = self.generate_preview

        try:
            res = build_vwt_package(scene, self, self.filepath)
            msg = f"Шаблон сцены .vwt собран ({res.get('triangles', 0)} полигонов, {res['size'] // 1024} КБ)"
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

        if bpy.data.filepath:
            out_dir = os.path.join(os.path.dirname(bpy.data.filepath), "Exported_VWO")
        else:
            out_dir = os.path.expanduser("~/Varwin_Exported_VWO")

        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{safe_name}.vwo")

        try:
            res = build_vwo_package(obj, props, out_path)
            msg = f"Объект '{safe_name}.vwo' готов ({res['triangles']} tris, {res['size'] // 1024} КБ)"
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
    bl_description = "Мгновенно собирает .vwt геометрию и регистрирует шаблон сцены в локальной библиотеке Varwin"

    def execute(self, context):
        scene = context.scene
        if not scene or not hasattr(scene, 'varwin_scene'):
            self.report({'ERROR'}, "Свойства сцены не найдены!")
            return {'CANCELLED'}

        props = scene.varwin_scene
        name = props.scene_name_en or "SceneTemplate"
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip() or "SceneTemplate"

        if bpy.data.filepath:
            out_dir = os.path.join(os.path.dirname(bpy.data.filepath), "Exported_VWT")
        else:
            out_dir = os.path.expanduser("~/Varwin_Exported_VWT")

        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{safe_name}.vwt")

        try:
            res = build_vwt_package(scene, props, out_path)
            msg = f"Шаблон сцены '{safe_name}.vwt' готов ({res.get('triangles', 0)} tris, {res['size'] // 1024} КБ)"
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
        ]
    )

    def execute(self, context):
        obj = get_target_mesh_object(context)
        if not obj:
            return {'CANCELLED'}
        p = obj.varwin

        if self.preset == 'DYNAMIC_LIGHT':
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
        elif self.preset == 'DYNAMIC_HEAVY':
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
        elif self.preset == 'STATIC_PROP':
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
        elif self.preset == 'TRIGGER_ZONE':
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
        elif self.preset == 'TELEPORT_FLOOR':
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

        self.report({'INFO'}, f"Применен пресет: {self.preset}")
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
    r1.prop_enum(sp, "ui_tab", "SCENE", text="🌐 Сцена (.vwt)")
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


class SCENE_PT_varwin_scene(bpy.types.Panel):
    """Панель параметров Varwin Scene во вкладке Scene Properties"""
    bl_label = "Varwin Scene Template (.vwt)"
    bl_idname = "SCENE_PT_varwin_scene"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'scene'

    def draw(self, context):
        scene = context.scene
        if scene and hasattr(scene, 'varwin_scene'):
            draw_varwin_scene_ui(self.layout, context, scene, scene.varwin_scene)


classes = (
    OBJECT_OT_varwin_export,
    SCENE_OT_varwin_export_vwt,
    OBJECT_OT_varwin_quick_export,
    SCENE_OT_varwin_quick_export_vwt,
    OBJECT_OT_varwin_apply_preset,
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

