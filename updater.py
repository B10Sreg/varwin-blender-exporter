import os
import re
import json
import shutil
import zipfile
import threading
import urllib.request
import bpy

# Global cache for update status
_update_lock = threading.Lock()
_current_version_str = "1.8.0"
_current_version_tuple = (1, 8, 0)
_latest_version_str = None
_latest_version_tuple = None
_update_available = False
_check_status = "up to date"  # "up to date", "checking...", "update available", "error"
_download_url = None
_last_error = ""


def _parse_version(v_str: str):
    """Parses 'v1.7.2' or '1.7.2' into (1, 7, 2)."""
    if not v_str:
        return (0, 0, 0)
    cleaned = re.sub(r'^[^\d]*', '', v_str)
    parts = re.split(r'[^\d]+', cleaned)
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
    return tuple(nums) if nums else (0, 0, 0)


def get_current_addon_version():
    """Gets version from bl_info in __init__.py or fallback."""
    global _current_version_str, _current_version_tuple
    try:
        from . import bl_info
        v = bl_info.get("version", (1, 7, 2))
        _current_version_tuple = tuple(v)
        _current_version_str = ".".join(str(x) for x in v)
    except Exception:
        pass
    return _current_version_str, _current_version_tuple


def check_github_release_sync():
    """Performs GitHub API query and updates global state."""
    global _latest_version_str, _latest_version_tuple, _update_available, _check_status, _download_url, _last_error
    
    curr_str, curr_tuple = get_current_addon_version()
    api_url = "https://api.github.com/repos/B10Sreg/varwin-blender-exporter/releases/latest"
    req = urllib.request.Request(api_url, headers={
        "User-Agent": "Blender-Varwin-Updater",
        "Accept": "application/vnd.github.v3+json"
    })

    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            tag = data.get("tag_name", "").strip()
            latest_tuple = _parse_version(tag)
            latest_str = ".".join(str(x) for x in latest_tuple)

            # Find release zip asset
            dl_url = None
            for asset in data.get("assets", []):
                aname = asset.get("name", "").lower()
                if aname.endswith(".zip"):
                    dl_url = asset.get("browser_download_url")
                    break
            
            if not dl_url:
                dl_url = data.get("zipball_url")

            with _update_lock:
                _latest_version_str = latest_str
                _latest_version_tuple = latest_tuple
                _download_url = dl_url

                if latest_tuple > curr_tuple:
                    _update_available = True
                    _check_status = "update available"
                else:
                    _update_available = False
                    _check_status = "up to date"
                _last_error = ""

    except Exception as e:
        with _update_lock:
            _check_status = "error"
            _last_error = str(e)


def check_github_release_async():
    """Runs GitHub check in background thread to never block Blender UI."""
    global _check_status
    with _update_lock:
        _check_status = "checking..."
    t = threading.Thread(target=check_github_release_sync, daemon=True)
    t.start()


class VARWIN_OT_check_update(bpy.types.Operator):
    """Проверить наличие обновлений аддона на GitHub"""
    bl_idname = "varwin.check_update"
    bl_label = "Проверить обновления"
    bl_description = "Проверить наличие новой версии аддона в GitHub репозитории"

    def execute(self, context):
        check_github_release_sync()
        if _update_available:
            self.report({'INFO'}, f"Доступна новая версия: v{_latest_version_str}")
        elif _check_status == "error":
            self.report({'WARNING'}, f"Ошибка проверки обновлений: {_last_error}")
        else:
            self.report({'INFO'}, f"Аддон v{_current_version_str} обновлен до последней версии")
        
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


class VARWIN_OT_install_update(bpy.types.Operator):
    """Скачать и установить последнюю версию аддона с GitHub"""
    bl_idname = "varwin.install_update"
    bl_label = "Обновить аддон"
    bl_description = "Автоматически скачать и установить новую версию аддона с GitHub"

    def execute(self, context):
        global _download_url, _update_available, _check_status

        if not _download_url:
            check_github_release_sync()

        if not _download_url:
            self.report({'ERROR'}, "Не удалось получить ссылку для загрузки обновления")
            return {'CANCELLED'}

        addon_dir = os.path.dirname(os.path.abspath(__file__))
        temp_zip = os.path.join(bpy.app.tempdir, "varwin_vwo_update.zip")
        extract_dir = os.path.join(bpy.app.tempdir, "varwin_vwo_update_extracted")

        try:
            # 1. Download asset
            req = urllib.request.Request(_download_url, headers={
                "User-Agent": "Blender-Varwin-Updater"
            })
            with urllib.request.urlopen(req, timeout=30) as resp, open(temp_zip, 'wb') as out_f:
                out_f.write(resp.read())

            # 2. Extract into temp
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)
            os.makedirs(extract_dir, exist_ok=True)

            with zipfile.ZipFile(temp_zip, 'r') as z:
                z.extractall(extract_dir)

            # Determine source folder inside zip
            src_files_dir = extract_dir
            subdirs = [os.path.join(extract_dir, d) for d in os.listdir(extract_dir) if os.path.isdir(os.path.join(extract_dir, d))]
            if len(subdirs) == 1 and os.path.exists(os.path.join(subdirs[0], "__init__.py")):
                src_files_dir = subdirs[0]

            # 3. Copy files into addon directory
            for item in os.listdir(src_files_dir):
                s = os.path.join(src_files_dir, item)
                d = os.path.join(addon_dir, item)
                if os.path.isdir(s):
                    if os.path.exists(d):
                        shutil.rmtree(d)
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)

            # Cleanup temp files
            try:
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
                if os.path.exists(extract_dir):
                    shutil.rmtree(extract_dir)
            except Exception:
                pass

            # 4. Reload addon in Blender
            try:
                bpy.ops.preferences.addon_disable(module="varwin_vwo_exporter")
                bpy.ops.preferences.addon_enable(module="varwin_vwo_exporter")
            except Exception:
                pass

            _update_available = False
            _check_status = "up to date"
            self.report({'INFO'}, f"Аддон успешно обновлен до версии v{_latest_version_str or 'latest'}!")
            
            for area in context.screen.areas:
                area.tag_redraw()
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Ошибка при установке обновления: {e}")
            return {'CANCELLED'}


def draw_updater_ui(layout):
    """
    Renders status line matching the reference screenshot:
    'Addon 1.8 · up to date' [ 🔄 ]
    or
    'Addon 1.7.2 · Доступна v1.8.0' [ Обновить ]
    """
    curr_str, _ = get_current_addon_version()

    row = layout.row(align=True)
    row.alignment = 'EXPAND'

    if _update_available and _latest_version_str:
        sub = row.row(align=True)
        sub.alert = True
        sub.label(text=f"Addon {curr_str} · Доступна v{_latest_version_str}", icon='INFO')
        row.operator("varwin.install_update", text="Обновить", icon='IMPORT')
    elif _check_status == "checking...":
        row.label(text=f"Addon {curr_str} · проверка...", icon='TIME')
    else:
        row.label(text=f"Addon {curr_str} · up to date")
        op = row.operator("varwin.check_update", text="", icon='FILE_REFRESH', emboss=False)


classes = (
    VARWIN_OT_check_update,
    VARWIN_OT_install_update,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
