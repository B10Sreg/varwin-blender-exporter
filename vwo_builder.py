import os
import sys
import io
import json
import uuid
import math
import zipfile
import re
import datetime
import bpy
try:
    import UnityPy
except ImportError:
    UnityPy = None
import copy

from .mesh_extractor import extract_mesh_data, extract_scene_geometry
from .preview_generator import generate_preview_images
from .installer import install_vwo_to_varwin, install_scene_template_to_varwin

def sanitize_variable_name(name: str) -> str:
    """Converts a user name into a valid Blockly/Python variable name."""
    s = re.sub(r'[^a-zA-Z0-9_]', '', name)
    if not s or s[0].isdigit():
        s = 'obj_' + s
    return s[:1].lower() + s[1:] if s else 'varwinObject'


UNITY_48B_CHANNELS = [
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 3},   # 0: Position (12 bytes)
    {'stream': 0, 'offset': 12, 'format': 0, 'dimension': 3},  # 1: Normal (12 bytes)
    {'stream': 0, 'offset': 24, 'format': 0, 'dimension': 4},  # 2: Tangent (16 bytes)
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 0},   # 3: Color (0 bytes)
    {'stream': 0, 'offset': 40, 'format': 0, 'dimension': 2},  # 4: UV0 (8 bytes)
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 0},   # 5: UV1 (0 bytes)
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 0},
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 0},
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 0},
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 0},
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 0},
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 0},
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 0},
    {'stream': 0, 'offset': 0, 'format': 0, 'dimension': 0},
]


def build_vwo_package(obj, props, output_filepath: str):
    """
    Main pipeline: extracts mesh, patches Unity AssetBundles, generates metadata,
    packs into standalone .vwo archive, and optionally installs into local Varwin.
    """
    global UnityPy
    if UnityPy is None:
        try:
            import UnityPy
        except ImportError:
            raise RuntimeError(
                "Для работы экспорта необходима библиотека UnityPy! "
                "Установите её в 1 клик на вкладке 'SDK & Пути' или в Edit > Preferences > Add-ons."
            )

    addon_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(addon_dir, "templates")

    # Select base template according to chosen collider
    collider_type = getattr(props, 'collider_type', 'CONVEX')
    if collider_type == 'SPHERE':
        template_name = 'sphere.vwo'
    elif collider_type == 'CAPSULE':
        template_name = 'capsule.vwo'
    elif collider_type == 'BOX':
        template_name = 'box.vwo'
    else:  # CONVEX or NONE
        template_name = 'convex.vwo'

    template_path = os.path.join(templates_dir, template_name)
    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"Шаблонный файл {template_name} не найден в {templates_dir}")

    # 1. Extract geometry and binary buffers from Blender object
    mesh_info = extract_mesh_data(obj, apply_modifiers=getattr(props, 'apply_modifiers', True))

    # 2. Extract template package contents
    template_files = {}
    with zipfile.ZipFile(template_path, 'r') as ztpl:
        for fname in ztpl.namelist():
            template_files[fname] = ztpl.read(fname)

    # 3. Calculate collider dimensions & centers
    cx = mesh_info['aabb_center']['x']
    cy = mesh_info['aabb_center']['y']
    cz = mesh_info['aabb_center']['z']
    ex = mesh_info['aabb_extent']['x']
    ey = mesh_info['aabb_extent']['y']
    ez = mesh_info['aabb_extent']['z']

    auto_fit = getattr(props, 'auto_fit_bounds', True)
    if auto_fit:
        box_size = {'x': ex * 2.0, 'y': ey * 2.0, 'z': ez * 2.0}
        box_center = {'x': cx, 'y': cy, 'z': cz}
        sphere_radius = max(ex, ey, ez)
        sphere_center = {'x': cx, 'y': cy, 'z': cz}
        capsule_radius = max(ex, ez)
        capsule_height = ey * 2.0
        capsule_center = {'x': cx, 'y': cy, 'z': cz}
    else:
        # User defined bounds (convert Blender Z-up to Unity Y-up)
        box_size = {'x': props.box_size[0], 'y': props.box_size[2], 'z': props.box_size[1]}
        box_center = {'x': props.box_center[0], 'y': props.box_center[2], 'z': props.box_center[1]}
        sphere_radius = props.sphere_radius
        sphere_center = {'x': props.sphere_center[0], 'y': props.sphere_center[2], 'z': props.sphere_center[1]}
        capsule_radius = props.capsule_radius
        capsule_height = props.capsule_height
        capsule_center = {'x': props.capsule_center[0], 'y': props.capsule_center[2], 'z': props.capsule_center[1]}

    # Constraints bitmask
    constraints = 0
    if getattr(props, 'freeze_pos_x', False): constraints |= 2
    if getattr(props, 'freeze_pos_y', False): constraints |= 4
    if getattr(props, 'freeze_pos_z', False): constraints |= 8
    if getattr(props, 'freeze_rot_x', False): constraints |= 16
    if getattr(props, 'freeze_rot_y', False): constraints |= 32
    if getattr(props, 'freeze_rot_z', False): constraints |= 64

    raw_name = getattr(props, 'object_name_en', '') or obj.name
    safe_asset_name = "".join(c for c in raw_name if c.isalnum() or c == '_').strip() or "VarwinAsset"

    # Deterministic GUIDs based on object name so re-exporting updates the existing item instead of creating duplicates
    new_guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"varwin.object.{safe_asset_name}"))
    new_root_guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"varwin.object.root.{safe_asset_name}"))
    clean_root = new_root_guid.replace("-", "")
    clean_name = sanitize_variable_name(getattr(props, 'object_name_en', '') or obj.name).lower()

    # VR flags config
    vr_config = {
        'grabbable': bool(getattr(props, 'grabbable', True)),
        'touchable': bool(getattr(props, 'touchable', True)),
        'usable': bool(getattr(props, 'usable', False)),
        'isObstacle': bool(getattr(props, 'is_obstacle', True)),
        'teleportArea': bool(getattr(props, 'teleport_area', False)),
    }

    # 5. Patch each AssetBundle (Windows, Linux, Android/Quest)
    bundle_configs = {
        'bundle': '',
        'linux_bundle': 'linux_',
        'android_bundle': 'android_'
    }

    new_prefab_path = f"assets/basic-content-pack/objects/{clean_name}_{clean_root}/{clean_name}.prefab"

    for bname, prefix in bundle_configs.items():
        if bname not in template_files:
            continue

        env = UnityPy.load(io.BytesIO(template_files[bname]))

        # A. Assign globally unique CAB identifier
        new_cab = f"CAB-{uuid.uuid4().hex}"
        new_files = {}
        for k, v in env.file.files.items():
            if k.endswith('.resS'):
                new_k = f"{new_cab}.resS"
            else:
                new_k = new_cab
            new_files[new_k] = v
            if hasattr(v, 'name'):
                v.name = new_k
        env.file.files = new_files

        # B. Assign unique bundle name & container asset path
        new_bname = f"{prefix}{clean_name}_{clean_root}"
        for o in env.objects:
            if o.type.name == 'AssetBundle':
                tree = o.read_typetree()
                tree['m_Name'] = new_bname
                tree['m_AssetBundleName'] = new_bname

                prefab_info = None
                for path, info in tree['m_Container']:
                    if path.endswith('.prefab'):
                        prefab_info = info
                        break
                if not prefab_info and tree['m_Container']:
                    prefab_info = tree['m_Container'][0][1]

                container_entries = {
                    new_prefab_path: prefab_info,
                    f"assets/objects/{clean_name}_{clean_root}/{clean_name}.prefab": prefab_info,
                    f"{clean_name}.prefab": prefab_info,
                    f"{clean_name}": prefab_info,
                    f"{safe_asset_name}.prefab": prefab_info,
                    f"{safe_asset_name}": prefab_info,
                }
                container_entries[new_prefab_path.lower()] = prefab_info

                for path, info in tree['m_Container']:
                    if not path.endswith('.prefab'):
                        new_p = path.lower().replace('vcylinder', f'{clean_name}_{clean_root}')
                        container_entries[new_p] = info

                tree['m_Container'] = sorted(container_entries.items(), key=lambda x: x[0])
                o.save_typetree(tree)
            elif o.type.name == 'GameObject':
                data = o.read()
                go_name = getattr(data, 'm_Name', getattr(data, 'name', ''))
                if go_name in ('VCylinder', 'VSphere', 'CapsuleCollider', 'TutorialDisplay', 'Woodenoldtable', safe_asset_name):
                    tree = o.read_typetree()
                    tree['m_Name'] = safe_asset_name
                    o.save_typetree(tree)

        # C. In-place patch Materials and MeshRenderer
        base_mat_obj = None
        orig_mat_pid = None
        target_sf = None
        for bf in env.files.values():
            if hasattr(bf, 'files'):
                for sf in bf.files.values():
                    if hasattr(sf, 'objects'):
                        for pid, o in sf.objects.items():
                            if o.type.name == 'Material':
                                base_mat_obj = o
                                orig_mat_pid = pid
                                target_sf = sf
                                break
                    if base_mat_obj:
                        break
            if base_mat_obj:
                break

        mat_pids = []
        if base_mat_obj and target_sf:
            extracted_mats = mesh_info.get('materials', [])
            for i, m_info in enumerate(extracted_mats):
                if i == 0:
                    m_obj = base_mat_obj
                    m_pid = orig_mat_pid
                else:
                    m_obj = copy.copy(base_mat_obj)
                    m_pid = orig_mat_pid - (i + 1) * 1000
                    m_obj.path_id = m_pid
                    target_sf.objects[m_pid] = m_obj

                tree = m_obj.read_typetree()
                tree['m_Name'] = m_info.get('name', f'Material_{i}')
                col = m_info.get('color', (0.8, 0.8, 0.8, 1.0))
                for c in tree.get('m_SavedProperties', {}).get('m_Colors', []):
                    if c[0] == '_Color':
                        c[1]['r'] = float(col[0])
                        c[1]['g'] = float(col[1])
                        c[1]['b'] = float(col[2])
                        c[1]['a'] = float(col[3]) if len(col) > 3 else 1.0
                    elif c[0] == '_EmissionColor':
                        ecol = m_info.get('emission', (0.0, 0.0, 0.0, 1.0))
                        c[1]['r'] = float(ecol[0])
                        c[1]['g'] = float(ecol[1])
                        c[1]['b'] = float(ecol[2])
                        c[1]['a'] = 1.0

                # Unity Standard Shader renders pitch black if metallic == 1.0 without baked reflection cubemap.
                # Clamp metallic to 0.80 to keep specular sheen while preserving diffuse lighting!
                met = min(float(m_info.get('metallic', 0.0)), 0.80)
                gloss = float(m_info.get('glossiness', 0.5))
                floats = tree.get('m_SavedProperties', {}).get('m_Floats', [])
                tree['m_SavedProperties']['m_Floats'] = [
                    (k, met if k == '_Metallic' else (gloss if k == '_Glossiness' else v))
                    for k, v in floats
                ]
                m_obj.save_typetree(tree)
                mat_pids.append(m_pid)

        # C.1. In-place patch Mesh
        for o in env.objects:
            if o.type.name == 'Mesh':
                tree = o.read_typetree()
                tree['m_Name'] = f"{safe_asset_name}_Mesh"
                tree['m_VertexData']['m_VertexCount'] = mesh_info['vertex_count']
                tree['m_VertexData']['m_DataSize'] = mesh_info['raw_vertex_data']
                tree['m_VertexData']['m_Channels'] = UNITY_48B_CHANNELS
                tree['m_IndexBuffer'] = mesh_info['raw_index_buffer']
                tree['m_IndexFormat'] = mesh_info['index_format']
                tree['m_SubMeshes'] = mesh_info.get('submeshes', [{
                    'firstByte': 0,
                    'indexCount': mesh_info['index_count'],
                    'topology': 0,
                    'baseVertex': 0,
                    'firstVertex': 0,
                    'vertexCount': mesh_info['vertex_count'],
                    'localAABB': {
                        'm_Center': {'x': cx, 'y': cy, 'z': cz},
                        'm_Extent': {'x': ex, 'y': ey, 'z': ez}
                    }
                }])
                tree['m_LocalAABB'] = {
                    'm_Center': {'x': cx, 'y': cy, 'z': cz},
                    'm_Extent': {'x': ex, 'y': ey, 'z': ez}
                }
                o.save_typetree(tree)
                break

        # C.2. In-place patch MeshRenderer
        if mat_pids:
            for o in env.objects:
                if o.type.name == 'MeshRenderer':
                    tree = o.read_typetree()
                    tree['m_Materials'] = [{'m_FileID': 0, 'm_PathID': pid} for pid in mat_pids]
                    o.save_typetree(tree)
                    break

        # C.3. Reset Transform to identity
        for o in env.objects:
            if o.type.name == 'Transform':
                tree = o.read_typetree()
                tree['m_LocalPosition'] = {'x': 0.0, 'y': 0.0, 'z': 0.0}
                tree['m_LocalRotation'] = {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0}
                o.save_typetree(tree)
                break

        # D. In-place patch Rigidbody
        for o in env.objects:
            if o.type.name == 'Rigidbody':
                tree = o.read_typetree()
                tree['m_Mass'] = float(getattr(props, 'mass', 1.0))
                tree['m_UseGravity'] = bool(getattr(props, 'use_gravity', True))
                tree['m_IsKinematic'] = bool(getattr(props, 'is_kinematic', False)) if getattr(props, 'use_rigidbody', True) else True
                tree['m_Drag'] = float(getattr(props, 'drag', 0.0))
                tree['m_AngularDrag'] = float(getattr(props, 'angular_drag', 0.05))
                tree['m_Constraints'] = int(constraints)
                tree['m_CollisionDetection'] = int(getattr(props, 'collision_detection', 0))
                tree['m_Interpolate'] = int(getattr(props, 'interpolate', 0))
                o.save_typetree(tree)
                break

        # E. In-place patch Colliders
        for o in env.objects:
            if o.type.name == 'MeshCollider':
                tree = o.read_typetree()
                tree['m_Convex'] = True
                tree['m_IsTrigger'] = bool(getattr(props, 'is_trigger', False))
                tree['m_Enabled'] = (collider_type == 'CONVEX')
                o.save_typetree(tree)
            elif o.type.name == 'BoxCollider':
                tree = o.read_typetree()
                tree['m_Size'] = box_size
                tree['m_Center'] = box_center
                tree['m_IsTrigger'] = bool(getattr(props, 'is_trigger', False))
                tree['m_Enabled'] = (collider_type == 'BOX')
                o.save_typetree(tree)
            elif o.type.name == 'SphereCollider':
                tree = o.read_typetree()
                tree['m_Radius'] = float(sphere_radius)
                tree['m_Center'] = sphere_center
                tree['m_IsTrigger'] = bool(getattr(props, 'is_trigger', False))
                tree['m_Enabled'] = (collider_type == 'SPHERE')
                o.save_typetree(tree)
            elif o.type.name == 'CapsuleCollider':
                tree = o.read_typetree()
                tree['m_Radius'] = float(capsule_radius)
                tree['m_Height'] = float(capsule_height)
                tree['m_Direction'] = int(getattr(props, 'capsule_direction', 1))
                tree['m_Center'] = capsule_center
                tree['m_IsTrigger'] = bool(getattr(props, 'is_trigger', False))
                tree['m_Enabled'] = (collider_type == 'CAPSULE')
                o.save_typetree(tree)

        # F. In-place patch Varwin Object Descriptor MonoBehaviour
        for o in env.objects:
            if o.type.name == 'MonoBehaviour':
                tree = o.read_typetree()
                if 'ConfigBlockly' in tree:
                    try:
                        cb = json.loads(tree['ConfigBlockly'])
                        cb['Guid'] = new_guid
                        cb['RootGuid'] = new_root_guid
                        cb['Name'] = {
                            'ru': getattr(props, 'object_name_ru', '') or obj.name,
                            'en': getattr(props, 'object_name_en', '') or obj.name
                        }
                        cb['Description'] = {
                            'ru': getattr(props, 'description_ru', ''),
                            'en': getattr(props, 'description_en', '')
                        }
                        cb['Author'] = {
                            'Name': getattr(props, 'author_name', '') or "Blender Artist",
                            'Email': "dev@varwin.local",
                            'Url': "https://varwin.com"
                        }
                        if 'Config' not in cb or not isinstance(cb['Config'], dict):
                            cb['Config'] = {}
                        cb['Config'].update(vr_config)
                        tree['ConfigBlockly'] = json.dumps(cb, ensure_ascii=False)
                    except Exception:
                        pass

                    tree['Name'] = safe_asset_name
                    tree['Guid'] = new_guid
                    tree['RootGuid'] = new_root_guid
                    tree['AuthorName'] = getattr(props, 'author_name', '') or "Blender Artist"
                    o.save_typetree(tree)
                    break

        out_buf = io.BytesIO()
        out_buf.write(env.file.save())
        template_files[bname] = out_buf.getvalue()

    # 6. Update bundle.json with unique AssetName
    if 'bundle.json' in template_files:
        bjson = json.loads(template_files['bundle.json'].decode('utf-8'))
        bjson['AssetName'] = safe_asset_name
        template_files['bundle.json'] = json.dumps(bjson, indent=2).encode('utf-8')

    # 7. Update manifests with unique asset paths
    for mname in ['bundle.manifest', 'linux_bundle.manifest', 'android_bundle.manifest']:
        if mname in template_files:
            mtext = template_files[mname].decode('utf-8', errors='ignore')
            lines = mtext.splitlines()
            new_lines = []
            in_assets = False
            for line in lines:
                if line.startswith('Assets:'):
                    in_assets = True
                    new_lines.append(line)
                    new_lines.append(f"- {new_prefab_path}")
                elif in_assets and line.strip().startswith('-'):
                    continue
                elif in_assets and not line.strip().startswith('-'):
                    in_assets = False
                    new_lines.append(line)
                else:
                    new_lines.append(line)
            template_files[mname] = ('\n'.join(new_lines) + '\n').encode('utf-8')

    # 8. Generate fresh metadata (install.json)
    install_meta = json.loads(template_files['install.json'].decode('utf-8'))
    install_meta['Guid'] = new_guid
    install_meta['RootGuid'] = new_root_guid
    install_meta['Name'] = {
        'ru': getattr(props, 'object_name_ru', '') or obj.name,
        'en': getattr(props, 'object_name_en', '') or obj.name
    }
    install_meta['Description'] = {
        'ru': getattr(props, 'description_ru', ''),
        'en': getattr(props, 'description_en', '')
    }
    install_meta['Author'] = {
        'Name': getattr(props, 'author_name', '') or "Blender Artist",
        'Email': "dev@varwin.local",
        'Url': "https://varwin.com"
    }
    install_meta['License'] = {
        'Code': getattr(props, 'license_code', 'cc-by'),
        'Version': "4.0"
    }
    install_meta['DefaultVariableName'] = sanitize_variable_name(getattr(props, 'object_name_en', '') or obj.name)
    install_meta['MobileReady'] = True
    install_meta['LinuxReady'] = True
    if 'Config' not in install_meta or not isinstance(install_meta['Config'], dict):
        install_meta['Config'] = {}
    install_meta['Config'].update(vr_config)

    template_files['install.json'] = json.dumps(install_meta, indent=2, ensure_ascii=False).encode('utf-8')

    # 9. Generate Previews & Icons
    if getattr(props, 'generate_preview', True):
        out_temp_dir = os.path.dirname(output_filepath)
        previews = generate_preview_images(obj, out_temp_dir, title=getattr(props, 'object_name_ru', '') or obj.name, is_scene=False)
        for pname, pdata in previews.items():
            if pdata:
                template_files[pname] = pdata

    # 10. Write final .vwo ZIP file
    os.makedirs(os.path.dirname(os.path.abspath(output_filepath)), exist_ok=True)
    with zipfile.ZipFile(output_filepath, 'w', compression=zipfile.ZIP_DEFLATED) as out_zip:
        for fname, data in template_files.items():
            out_zip.writestr(fname, data)

    result_info = {
        'vwo_path': output_filepath,
        'size': os.path.getsize(output_filepath),
        'guid': new_guid,
        'root_guid': new_root_guid,
        'vertices': mesh_info['vertex_count'],
        'triangles': mesh_info['triangle_count']
    }

    # 11. Optional 1-Click Install to local Varwin XRMS
    if getattr(props, 'direct_install_varwin', True):
        ok, msg = install_vwo_to_varwin(output_filepath)
        result_info['installed'] = ok
        result_info['install_message'] = msg
    else:
        result_info['installed'] = False
        result_info['install_message'] = "Сохранен локально (без импорта в Varwin)"

    return result_info


def build_vwt_package(scene, scene_props, output_filepath: str):
    """
    Builds a complete Varwin Scene Template (.vwt) package:
    1. Extracts and merges all visible meshes from the Blender scene into environment geometry.
    2. Injects geometry into Mesh: Base (visual) and Mesh: BaseCollision (physics collider).
    3. Configures VR Player Spawn Point and Directional Lighting.
    4. Deactivates extra template props.
    5. Updates localized metadata and generates scene preview images.
    6. Packs into .vwt ZIP and optionally installs into local Varwin XRMS.
    """
    global UnityPy
    if UnityPy is None:
        try:
            import UnityPy
        except ImportError:
            raise RuntimeError(
                "Для работы экспорта необходима библиотека UnityPy! "
                "Установите её в 1 клик на вкладке 'SDK & Пути' или в Edit > Preferences > Add-ons."
            )

    addon_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(addon_dir, "templates")
    template_path = os.path.join(templates_dir, "scene.vwt")

    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"Базовый шаблон сцены scene.vwt не найден в {templates_dir}")

    # 1. Extract combined scene geometry
    selected_only = getattr(scene_props, 'selected_only', False)
    mesh_info = extract_scene_geometry(scene, selected_only=selected_only)

    # 2. Read template contents
    template_files = {}
    with zipfile.ZipFile(template_path, 'r') as ztpl:
        for fname in ztpl.namelist():
            template_files[fname] = ztpl.read(fname)

    # 3. Determine Spawn Point coordinates (Blender Z-up to Unity Y-up: X->X, Y->Z, Z->Y)
    spawn_mode = getattr(scene_props, 'spawn_mode', 'CURSOR')
    if spawn_mode == 'CURSOR' and hasattr(scene, 'cursor'):
        loc = scene.cursor.location
        sx = loc.x
        sy = loc.z
        sz = loc.y
    elif spawn_mode == 'ACTIVE_OBJECT' and bpy.context and bpy.context.active_object:
        loc = bpy.context.active_object.location
        sx = loc.x
        sy = loc.z
        sz = loc.y
    elif spawn_mode == 'CUSTOM' and hasattr(scene_props, 'spawn_position'):
        sx = scene_props.spawn_position[0]
        sy = scene_props.spawn_position[2]
        sz = scene_props.spawn_position[1]
    else:  # ORIGIN
        sx = 0.0
        sy = 0.0
        sz = 0.0

    spawn_angle = getattr(scene_props, 'spawn_rotation_z', 0.0)
    spawn_rad = math.radians(spawn_angle)
    rot_y = math.sin(spawn_rad / 2.0)
    rot_w = math.cos(spawn_rad / 2.0)

    # 4. Patch AssetBundles with the extracted scene mesh & spawn point
    keep_names = {
        '[World Descriptor]', '[Spawn Point]', '[Camera Preview]',
        'Base', 'BaseCollision', 'TeleportArea', 'Directional Light_BAKED',
        'Directional Light', 'Lighting', 'Main Camera'
    }

    for bname in ['bundle', 'linux_bundle', 'android_bundle']:
        if bname not in template_files:
            continue

        env = UnityPy.load(io.BytesIO(template_files[bname]))

        # 4.1. Clone Materials in sharedAssets for each extracted material
        base_mat_obj = None
        shared_sf = None
        for bf in env.files.values():
            if hasattr(bf, 'files'):
                for sf_name, sf in bf.files.items():
                    if 'sharedAssets' in sf_name:
                        shared_sf = sf
                        if 25 in sf.objects:
                            base_mat_obj = sf.objects[25]
                        break

        vwt_mat_pids = []
        if base_mat_obj and shared_sf:
            extracted_mats = mesh_info.get('materials', [])
            for i, m_info in enumerate(extracted_mats):
                if i == 0:
                    m_obj = base_mat_obj
                    m_pid = 25
                else:
                    m_obj = copy.copy(base_mat_obj)
                    m_pid = 2500 + i
                    m_obj.path_id = m_pid
                    shared_sf.objects[m_pid] = m_obj

                tree = m_obj.read_typetree()
                tree['m_Name'] = m_info.get('name', f'SceneMaterial_{i}')
                col = m_info.get('color', (0.8, 0.8, 0.8, 1.0))
                for c in tree.get('m_SavedProperties', {}).get('m_Colors', []):
                    if c[0] == '_Color':
                        c[1]['r'] = float(col[0])
                        c[1]['g'] = float(col[1])
                        c[1]['b'] = float(col[2])
                        c[1]['a'] = float(col[3]) if len(col) > 3 else 1.0
                    elif c[0] == '_EmissionColor':
                        ecol = m_info.get('emission', (0.0, 0.0, 0.0, 1.0))
                        c[1]['r'] = float(ecol[0])
                        c[1]['g'] = float(ecol[1])
                        c[1]['b'] = float(ecol[2])
                        c[1]['a'] = 1.0

                # Clamp metallic to 0.80 to prevent black rendering without cubemap
                met = min(float(m_info.get('metallic', 0.0)), 0.80)
                gloss = float(m_info.get('glossiness', 0.5))
                floats = tree.get('m_SavedProperties', {}).get('m_Floats', [])
                tree['m_SavedProperties']['m_Floats'] = [
                    (k, met if k == '_Metallic' else (gloss if k == '_Glossiness' else v))
                    for k, v in floats
                ]
                m_obj.save_typetree(tree)
                vwt_mat_pids.append(m_pid)

        # 4.2. Patch environment geometry meshes
        for o in env.objects:
            if o.type.name == 'Mesh':
                tree = o.read_typetree()
                m_name = tree.get('m_Name')
                if m_name == 'Base':
                    tree['m_VertexData']['m_VertexCount'] = mesh_info['vertex_count']
                    tree['m_VertexData']['m_DataSize'] = mesh_info['raw_vertex_data']
                    tree['m_VertexData']['m_Channels'] = UNITY_48B_CHANNELS
                    tree['m_IndexBuffer'] = mesh_info['raw_index_buffer']
                    tree['m_IndexFormat'] = mesh_info['index_format']
                    tree['m_SubMeshes'] = mesh_info.get('submeshes', [{
                        'firstByte': 0,
                        'indexCount': mesh_info['index_count'],
                        'topology': 0,
                        'baseVertex': 0,
                        'firstVertex': 0,
                        'vertexCount': mesh_info['vertex_count'],
                        'localAABB': {
                            'm_Center': mesh_info['aabb_center'],
                            'm_Extent': mesh_info['aabb_extent']
                        }
                    }])
                    tree['m_LocalAABB'] = {
                        'm_Center': mesh_info['aabb_center'],
                        'm_Extent': mesh_info['aabb_extent']
                    }
                    o.save_typetree(tree)
                elif m_name == 'BaseCollision':
                    tree['m_VertexData']['m_VertexCount'] = mesh_info['vertex_count']
                    tree['m_VertexData']['m_DataSize'] = mesh_info['raw_vertex_data']
                    tree['m_VertexData']['m_Channels'] = UNITY_48B_CHANNELS
                    tree['m_IndexBuffer'] = mesh_info['raw_index_buffer']
                    tree['m_IndexFormat'] = mesh_info['index_format']
                    tree['m_SubMeshes'] = [{
                        'firstByte': 0,
                        'indexCount': mesh_info['index_count'],
                        'topology': 0,
                        'baseVertex': 0,
                        'firstVertex': 0,
                        'vertexCount': mesh_info['vertex_count'],
                        'localAABB': {
                            'm_Center': mesh_info['aabb_center'],
                            'm_Extent': mesh_info['aabb_extent']
                        }
                    }]
                    tree['m_LocalAABB'] = {
                        'm_Center': mesh_info['aabb_center'],
                        'm_Extent': mesh_info['aabb_extent']
                    }
                    o.save_typetree(tree)

        # 4.3. Update MeshRenderer on Base
        for o in env.objects:
            if o.type.name == 'MeshRenderer':
                tree = o.read_typetree()
                if vwt_mat_pids:
                    tree['m_Materials'] = [{'m_FileID': 1, 'm_PathID': pid} for pid in vwt_mat_pids]
                else:
                    tree['m_Materials'] = [{'m_FileID': 1, 'm_PathID': 25}]
                o.save_typetree(tree)

        # 4.4. Reset Transform on Base, TeleportArea, and BaseCollision to remove -90 tilt and 180 deg rotation
        base_go_pids = set()
        for o in env.objects:
            if o.type.name == 'GameObject':
                tree = o.read_typetree()
                gname = tree.get('m_Name')
                if gname in ('Base', 'BaseCollision', 'TeleportArea'):
                    base_go_pids.add(o.path_id)
                if gname in ('BaseCollision', 'TeleportArea'):
                    tree['m_Tag'] = 20000  # Tag with 'TeleportArea'
                    tree['m_Layer'] = 0    # Layer 0 (Default)
                    o.save_typetree(tree)

        for o in env.objects:
            if o.type.name == 'Transform':
                tree = o.read_typetree()
                go_ref = tree.get('m_GameObject', {}).get('m_PathID')
                if go_ref in base_go_pids or o.path_id in (117, 127, 128):
                    tree['m_LocalPosition'] = {'x': 0.0, 'y': 0.0, 'z': 0.0}
                    tree['m_LocalRotation'] = {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0}
                    tree['m_LocalScale'] = {'x': 1.0, 'y': 1.0, 'z': 1.0}
                    o.save_typetree(tree)
            elif o.type.name == 'MeshCollider':
                tree = o.read_typetree()
                go_ref = tree.get('m_GameObject', {}).get('m_PathID')
                # Disable MeshCollider on Base (visual mesh) so BaseCollision under TeleportArea is the sole physical & teleport collider
                if o.path_id == 207 or go_ref == 49:
                    tree['m_Enabled'] = False
                    o.save_typetree(tree)
                elif o.path_id == 210 or go_ref == 64:
                    tree['m_Enabled'] = True
                    tree['m_IsTrigger'] = False
                    tree['m_Convex'] = False
                    o.save_typetree(tree)

        # 4.5. Dynamic lookup for Spawn Point Transform and Directional Light
        spawn_tf_pid = None
        light_pid = None
        for o in env.objects:
            if o.type.name == 'GameObject':
                tree = o.read_typetree()
                gname = tree.get('m_Name')
                if gname and gname not in keep_names:
                    tree['m_IsActive'] = False
                    o.save_typetree(tree)
                elif gname == '[Spawn Point]':
                    for c in tree.get('m_Component', []):
                        spawn_tf_pid = c['component']['m_PathID']
                        break
                elif gname and 'Directional Light' in gname:
                    for c in tree.get('m_Component', []):
                        pid = c['component']['m_PathID']
                        light_pid = pid

        for o in env.objects:
            if o.type.name == 'Transform' and (o.path_id == spawn_tf_pid or o.path_id in (9, 103)):
                tree = o.read_typetree()
                tree['m_LocalPosition'] = {'x': float(sx), 'y': float(sy), 'z': float(sz)}
                tree['m_LocalRotation'] = {'x': 0.0, 'y': float(rot_y), 'z': 0.0, 'w': float(rot_w)}
                o.save_typetree(tree)
            elif o.type.name == 'Light' and (o.path_id == light_pid or o.path_id in (14, 219)):
                tree = o.read_typetree()
                tree['m_Intensity'] = float(getattr(scene_props, 'light_intensity', 1.0))
                lcol = getattr(scene_props, 'light_color', (1.0, 0.95, 0.85))
                tree['m_Color'] = {
                    'r': float(lcol[0]),
                    'g': float(lcol[1]),
                    'b': float(lcol[2]),
                    'a': 1.0
                }
                tree['m_Lightmapping'] = 4
                if 'm_BakingOutput' in tree:
                    tree['m_BakingOutput']['isBaked'] = False
                    tree['m_BakingOutput']['lightmapBakeType'] = 4

                # Disable shadows on Directional Light if NONE (recommended for interiors so ceilings do not occlude)
                shadow_mode = getattr(scene_props, 'light_shadows', 'NONE')
                if 'm_Shadows' in tree:
                    tree['m_Shadows']['m_Type'] = 2 if shadow_mode == 'SOFT' else 0
                o.save_typetree(tree)
            elif o.type.name == 'RenderSettings':
                tree = o.read_typetree()
                # Enable Gradient Ambient Mode (1: Trilight) so interiors are evenly and richly lit
                tree['m_AmbientMode'] = 1
                tree['m_AmbientIntensity'] = 1.0
                lcol = getattr(scene_props, 'light_color', (1.0, 0.95, 0.82))
                tree['m_AmbientSkyColor'] = {
                    'r': min(1.0, float(lcol[0]) * 0.95),
                    'g': min(1.0, float(lcol[1]) * 0.90),
                    'b': min(1.0, float(lcol[2]) * 0.78),
                    'a': 1.0
                }
                tree['m_AmbientEquatorColor'] = {
                    'r': min(1.0, float(lcol[0]) * 0.80),
                    'g': min(1.0, float(lcol[1]) * 0.76),
                    'b': min(1.0, float(lcol[2]) * 0.65),
                    'a': 1.0
                }
                tree['m_AmbientGroundColor'] = {
                    'r': min(1.0, float(lcol[0]) * 0.50),
                    'g': min(1.0, float(lcol[1]) * 0.46),
                    'b': min(1.0, float(lcol[2]) * 0.38),
                    'a': 1.0
                }
                tree['m_ReflectionIntensity'] = 1.0
                o.save_typetree(tree)

        out_buf = io.BytesIO()
        out_buf.write(env.file.save())
        template_files[bname] = out_buf.getvalue()

    # 5. Generate deterministic GUIDs so re-exporting updates the existing scene template instead of duplicating
    raw_sname = getattr(scene_props, 'scene_name_en', '') or "MotorcycleGarage"
    safe_template_name = "".join(c for c in raw_sname if c.isalnum() or c == '_').strip() or "SceneTemplate"
    new_guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"varwin.scene.{safe_template_name}"))
    new_root_guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"varwin.scene.root.{safe_template_name}"))

    # 6. Update install.json
    install_meta = json.loads(template_files['install.json'].decode('utf-8'))
    install_meta['Guid'] = new_guid
    install_meta['RootGuid'] = new_root_guid
    install_meta['Name'] = {
        'ru': getattr(scene_props, 'scene_name_ru', '') or "Новая сцена",
        'en': getattr(scene_props, 'scene_name_en', '') or "New Scene"
    }
    install_meta['Description'] = {
        'ru': getattr(scene_props, 'description_ru', ''),
        'en': getattr(scene_props, 'description_en', '')
    }
    install_meta['Author'] = {
        'Name': getattr(scene_props, 'author_name', '') or "Blender Artist",
        'Email': "dev@varwin.local",
        'Url': "https://varwin.com"
    }
    install_meta['BuiltAt'] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    install_meta['MobileReady'] = True
    install_meta['LinuxReady'] = True
    template_files['install.json'] = json.dumps(install_meta, indent=2, ensure_ascii=False).encode('utf-8')

    # 7. Update bundle.json
    if 'bundle.json' in template_files:
        bjson = json.loads(template_files['bundle.json'].decode('utf-8'))
        bjson['name'] = getattr(scene_props, 'scene_name_en', '') or "New Scene"
        bjson['description'] = getattr(scene_props, 'description_en', '') or ""
        template_files['bundle.json'] = json.dumps(bjson, indent=2, ensure_ascii=False).encode('utf-8')

    # 8. Generate preview graphics
    if getattr(scene_props, 'generate_preview', True):
        out_temp_dir = os.path.dirname(output_filepath)
        previews = generate_preview_images(
            None,
            out_temp_dir,
            title=getattr(scene_props, 'scene_name_ru', '') or "Новая сцена",
            is_scene=True
        )
        for pname, pdata in previews.items():
            if pdata:
                template_files[pname] = pdata

    # 9. Write final .vwt ZIP file
    os.makedirs(os.path.dirname(os.path.abspath(output_filepath)), exist_ok=True)
    with zipfile.ZipFile(output_filepath, 'w', compression=zipfile.ZIP_DEFLATED) as out_zip:
        for fname, data in template_files.items():
            out_zip.writestr(fname, data)

    result_info = {
        'vwt_path': output_filepath,
        'size': os.path.getsize(output_filepath),
        'guid': new_guid,
        'root_guid': new_root_guid,
        'vertices': mesh_info['vertex_count'],
        'triangles': mesh_info['triangle_count'],
        'objects_merged': mesh_info['objects_merged']
    }

    # 10. Optional 1-Click Install to local Varwin XRMS
    if getattr(scene_props, 'direct_install_varwin', True):
        ok, msg = install_scene_template_to_varwin(output_filepath)
        result_info['installed'] = ok
        result_info['install_message'] = msg
    else:
        result_info['installed'] = False
        result_info['install_message'] = "Сохранен локально (без импорта в Varwin)"

    return result_info
