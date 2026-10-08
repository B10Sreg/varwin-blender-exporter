bl_info = {
    "name": "Varwin VWO & Scene Exporter",
    "author": "Antigravity & B10Sreg",
    "version": (1, 1, 0),
    "blender": (4, 2, 0),
    "location": "Properties > Object / Scene | 3D Viewport > Sidebar > Varwin | File > Export",
    "description": "Кроссплатформенный экспорт 3D-моделей (.vwo) и шаблонов сцен (.vwt) в Varwin XRMS со всеми возможностями Unity SDK (Rigidbody, Colliders, VR Interaction, Spawns)",
    "doc_url": "https://varwin.com",
    "category": "Import-Export",
}

import bpy
from . import properties
from . import ui

def menu_func_export(self, context):
    self.layout.operator(ui.OBJECT_OT_varwin_export.bl_idname, text="Varwin Object (.vwo)")
    self.layout.operator(ui.SCENE_OT_varwin_export_vwt.bl_idname, text="Varwin Scene Template (.vwt)")

def cleanup_export_menu():
    """Removes all Varwin callbacks from File > Export menu to eliminate duplicates."""
    funcs = getattr(bpy.types.TOPBAR_MT_file_export, "_dyn_ui_initialize", lambda: [])()
    for f in list(funcs):
        mod = getattr(f, '__module__', '')
        name = getattr(f, '__name__', '')
        if name == 'menu_func_export' and 'varwin' in mod:
            try:
                bpy.types.TOPBAR_MT_file_export.remove(f)
            except Exception:
                pass

def register():
    properties.register()
    ui.register()
    cleanup_export_menu()
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

def unregister():
    cleanup_export_menu()
    ui.unregister()
    properties.unregister()

if __name__ == "__main__":
    register()
