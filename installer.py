import os
import sys
import json
import sqlite3
import zipfile

def get_varwin_data_path():
    """
    Auto-detects VarwinData18 path across Windows, Linux, macOS,
    with environment variable checks and add-on preferences override.
    """
    # 1. Check Blender Addon Preferences override
    try:
        import bpy
        addon_prefs = bpy.context.preferences.addons.get('varwin_vwo_exporter')
        if addon_prefs and getattr(addon_prefs.preferences, 'custom_varwin_data_path', ''):
            custom_path = addon_prefs.preferences.custom_varwin_data_path.strip()
            if os.path.isdir(custom_path):
                return custom_path
    except Exception:
        pass

    # 2. Check Environment Variables
    for env_var in ['VARWIN_DATA_PATH', 'VARWINDATA_PATH', 'VARWIN_PATH']:
        val = os.environ.get(env_var)
        if val and os.path.isdir(val):
            return val

    # 3. Check OS-specific standard directories
    candidates = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        localappdata = os.environ.get("LOCALAPPDATA")
        userprofile = os.environ.get("USERPROFILE")
        if appdata:
            candidates.append(os.path.join(appdata, "VarwinData18"))
            candidates.append(os.path.join(appdata, "Varwin XRMS", "VarwinData18"))
        if localappdata:
            candidates.append(os.path.join(localappdata, "VarwinData18"))
        if userprofile:
            candidates.append(os.path.join(userprofile, ".config", "VarwinData18"))
        for drive in ["C:", "D:", "E:"]:
            candidates.append(os.path.join(drive, "\\VarwinData18"))
            candidates.append(os.path.join(drive, "\\ProgramData", "VarwinData18"))
    elif sys.platform == "darwin": # macOS
        home = os.path.expanduser("~")
        candidates.append(os.path.join(home, "Library", "Application Support", "VarwinData18"))
        candidates.append(os.path.join(home, ".config", "VarwinData18"))
    else: # Linux / Unix
        home = os.path.expanduser("~")
        xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
        candidates.append(os.path.join(xdg_config, "VarwinData18"))
        candidates.append(os.path.join(home, ".config", "VarwinData18"))
        candidates.append(os.path.join(home, ".varwin", "VarwinData18"))
        candidates.append("/var/opt/VarwinData18")

    # Priority to directories that already have SQLite3/database.db
    for p in candidates:
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "SQLite3", "database.db")):
            return p

    # Fallback to any existing directory
    for p in candidates:
        if os.path.isdir(p):
            return p

    return None


def install_vwo_to_varwin(vwo_filepath: str):
    """
    Directly unpacks and registers .vwo into local Varwin XRMS SQLite database and assets directory.
    Returns (success: bool, message: str)
    """
    data_dir = get_varwin_data_path()
    if not data_dir:
        return False, "Локальный каталог VarwinData18 не найден. Укажите его вручную в настройках аддона."

    db_path = os.path.join(data_dir, "SQLite3", "database.db")
    if not os.path.isfile(db_path):
        return False, f"База данных Varwin не найдена по пути: {db_path}"

    if not os.path.isfile(vwo_filepath):
        return False, f"Файл .vwo не найден: {vwo_filepath}"

    # Read install.json from vwo archive
    with zipfile.ZipFile(vwo_filepath, 'r') as z:
        if 'install.json' not in z.namelist():
            return False, "Невалидный .vwo архив: отсутствует install.json"
        install_meta = json.loads(z.read('install.json').decode('utf-8'))

    guid = install_meta.get('Guid')
    root_guid = install_meta.get('RootGuid')
    if not guid or not root_guid:
        return False, "install.json не содержит корректных Guid или RootGuid"

    # Destination directory: Api/data/objects/resources/<xx>/<guid>/
    resources_dir = os.path.join(data_dir, "Api", "data", "objects", "resources", guid[:2], guid)
    os.makedirs(resources_dir, exist_ok=True)

    # Extract all files
    with zipfile.ZipFile(vwo_filepath, 'r') as z:
        z.extractall(resources_dir)

    # Insert into SQLite database
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        cur.execute("SELECT id FROM objects WHERE guid = ?", (guid,))
        existing = cur.fetchone()
        if not existing:
            obj_name_en = install_meta.get('Name', {}).get('en', '')
            if obj_name_en:
                cur.execute("SELECT id FROM objects WHERE name LIKE ?", (f'%"{obj_name_en}"%',))
                existing = cur.fetchone()

        if existing:
            # Update existing
            cur.execute("""
                UPDATE objects SET
                    guid = ?, root_guid = ?,
                    name = ?, description = ?, config = ?, author = ?,
                    mobile_ready = 1, linux_ready = 1, size = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                guid, root_guid,
                json.dumps(install_meta.get('Name', {})),
                json.dumps(install_meta.get('Description', {})),
                json.dumps(install_meta.get('Config', {})),
                json.dumps(install_meta.get('Author', {})),
                os.path.getsize(vwo_filepath),
                existing[0]
            ))
            object_id = existing[0]
            action = "обновлен"
        else:
            # Find admin/owner user_id (default to 3 or 1)
            cur.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
            user_row = cur.fetchone()
            owner_id = user_row[0] if user_row else 3

            cur.execute("""
                INSERT INTO objects (
                    guid, root_guid, config, embedded, content_license_id, author,
                    mobile_ready, linux_ready, sdk_version, locked, disable_scene_logic,
                    name, description, module_name, type_name, default_variable_name,
                    created_by, updated_by, owned_by, public, changelog, size
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                guid,
                root_guid,
                json.dumps(install_meta.get('Config', {})),
                0,
                1,
                json.dumps(install_meta.get('Author', {})),
                1,
                1,
                install_meta.get('SdkVersion', '18.5.442'),
                0,
                0,
                json.dumps(install_meta.get('Name', {})),
                json.dumps(install_meta.get('Description', {})),
                install_meta.get('ModuleName', ''),
                install_meta.get('TypeName', ''),
                install_meta.get('DefaultVariableName', 'obj'),
                owner_id,
                owner_id,
                owner_id,
                1,
                json.dumps(install_meta.get('Changelog', {})),
                os.path.getsize(vwo_filepath)
            ))
            object_id = cur.lastrowid
            action = "добавлен"

        conn.commit()
        return True, f"Объект успешно {action} в локальную библиотеку Varwin XRMS (ID: {object_id}, GUID: {guid})"

    except Exception as e:
        conn.rollback()
        return False, f"Ошибка записи в базу Varwin: {str(e)}"
    finally:
        conn.close()


def install_scene_template_to_varwin(vwt_filepath: str):
    """
    Directly unpacks and registers .vwt into local Varwin XRMS SQLite database and scene-templates directory.
    Returns (success: bool, message: str)
    """
    data_dir = get_varwin_data_path()
    if not data_dir:
        return False, "Локальный каталог VarwinData18 не найден. Укажите его вручную в настройках аддона."

    db_path = os.path.join(data_dir, "SQLite3", "database.db")
    if not os.path.isfile(db_path):
        return False, f"База данных Varwin не найдена по пути: {db_path}"

    if not os.path.isfile(vwt_filepath):
        return False, f"Файл шаблона сцены не найден: {vwt_filepath}"

    # Read install.json from vwt archive
    with zipfile.ZipFile(vwt_filepath, 'r') as z:
        if 'install.json' not in z.namelist():
            return False, "Невалидный архив шаблона: отсутствует install.json"
        install_meta = json.loads(z.read('install.json').decode('utf-8'))

    guid = install_meta.get('Guid')
    root_guid = install_meta.get('RootGuid')
    if not guid or not root_guid:
        return False, "install.json не содержит корректных Guid или RootGuid"

    # Destination directory: Api/data/scene-templates/resources/<xx>/<guid>/
    resources_dir = os.path.join(data_dir, "Api", "data", "scene-templates", "resources", guid[:2], guid)
    os.makedirs(resources_dir, exist_ok=True)

    # Extract all files
    with zipfile.ZipFile(vwt_filepath, 'r') as z:
        z.extractall(resources_dir)

    # Insert into SQLite database
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        cur.execute("SELECT id FROM scene_templates WHERE guid = ?", (guid,))
        existing = cur.fetchone()
        if not existing:
            tpl_name_en = install_meta.get('Name', {}).get('en', '')
            if tpl_name_en:
                cur.execute("SELECT id FROM scene_templates WHERE name LIKE ?", (f'%"{tpl_name_en}"%',))
                existing = cur.fetchone()

        if existing:
            cur.execute("""
                UPDATE scene_templates SET
                    guid = ?, root_guid = ?,
                    name = ?, description = ?, config = ?, author = ?,
                    mobile_ready = 1, linux_ready = 1, size = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                guid, root_guid,
                json.dumps(install_meta.get('Name', {})),
                json.dumps(install_meta.get('Description', {})),
                json.dumps(install_meta.get('Config', {})),
                json.dumps(install_meta.get('Author', {})),
                os.path.getsize(vwt_filepath),
                existing[0]
            ))
            template_id = existing[0]
            action = "обновлен"
        else:
            cur.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
            user_row = cur.fetchone()
            owner_id = user_row[0] if user_row else 3

            cur.execute("""
                INSERT INTO scene_templates (
                    guid, root_guid, config, content_license_id, author,
                    mobile_ready, linux_ready, sdk_version,
                    name, description,
                    created_by, updated_by, owned_by, public, changelog, size,
                    built_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                guid,
                root_guid,
                json.dumps(install_meta.get('Config', {})),
                1,
                json.dumps(install_meta.get('Author', {})),
                1,
                1,
                install_meta.get('SdkVersion', '18.5.442'),
                json.dumps(install_meta.get('Name', {})),
                json.dumps(install_meta.get('Description', {})),
                owner_id,
                owner_id,
                owner_id,
                1,
                json.dumps(install_meta.get('Changelog', {})),
                os.path.getsize(vwt_filepath)
            ))
            template_id = cur.lastrowid
            action = "добавлен"

        conn.commit()
        return True, f"Шаблон сцены успешно {action} в локальную библиотеку Varwin XRMS (ID: {template_id}, GUID: {guid})"

    except Exception as e:
        conn.rollback()
        return False, f"Ошибка записи шаблона сцены в базу Varwin: {str(e)}"
    finally:
        conn.close()
