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

from .mesh_extractor import extract_mesh_data, extract_object_geometry, extract_scene_geometry
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


def build_vwo_package(obj_or_objects, props, output_filepath: str):
    """
    Main pipeline: extracts mesh(es), patches Unity AssetBundles, generates metadata,
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

    # Resolve target mesh objects and reference/pivot object
    if isinstance(obj_or_objects, (list, tuple)):
        mesh_objs = [o for o in obj_or_objects if o and o.type == 'MESH']
        root_obj = None
        if bpy.context and bpy.context.active_object in mesh_objs:
            root_obj = bpy.context.active_object
        elif mesh_objs:
            root_obj = mesh_objs[0]
    else:
        root_obj = obj_or_objects
        scope = getattr(props, 'export_scope', None)
        if scope == 'ACTIVE':
            mesh_objs = [root_obj]
        elif scope == 'VISIBLE':
            mesh_objs = [o for o in bpy.context.scene.objects if o.type == 'MESH' and not o.hide_get()] if (bpy.context and bpy.context.scene) else [root_obj]
        else:  # 'SELECTED' (default) or legacy selected_only
            sel_meshes = [o for o in bpy.context.selected_objects if o.type == 'MESH' and not o.hide_get()] if (bpy.context and getattr(bpy.context, 'selected_objects', None)) else []
            if sel_meshes:
                mesh_objs = sel_meshes
                if root_obj not in mesh_objs:
                    root_obj = mesh_objs[0]
            else:
                mesh_objs = [root_obj]

    if not mesh_objs:
        raise ValueError("Не найдено полигональных мешей (Mesh) для экспорта в объект .vwo!")

    obj = root_obj

    # Use convex.vwo as the universal clean base template (single mesh, single renderer, no extraneous UI screens/TMP)
    # The mesh itself provides authentic geometry and collision.
    template_name = 'convex.vwo'
    collider_type = getattr(props, 'collider_type', 'CONVEX')

    template_path = os.path.join(templates_dir, template_name)
    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"Шаблонный файл {template_name} не найден в {templates_dir}")

    # 1. Extract geometry and binary buffers from Blender object(s)
    mesh_info = extract_object_geometry(
        mesh_objs,
        root_obj=root_obj,
        apply_modifiers=getattr(props, 'apply_modifiers', True)
    )

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
            if o.type.name == 'GameObject':
                data = o.read()
                go_name = getattr(data, 'm_Name', getattr(data, 'name', ''))
                if go_name in ('VCylinder', 'VSphere', 'CapsuleCollider', 'TutorialDisplay', 'Woodenoldtable', safe_asset_name):
                    tree = o.read_typetree()
                    tree['m_Name'] = safe_asset_name
                    o.save_typetree(tree)

        # C. In-place patch Materials, Textures, and MeshRenderer
        base_mat_obj = None
        orig_mat_pid = None
        target_sf = None
        tex_tpl = None
        for bf in env.files.values():
            if hasattr(bf, 'files'):
                for sf in bf.files.values():
                    if hasattr(sf, 'objects'):
                        for pid, o in sf.objects.items():
                            if o.type.name == 'Material' and not base_mat_obj:
                                base_mat_obj = o
                                orig_mat_pid = pid
                                target_sf = sf
                            elif o.type.name == 'Texture2D' and not tex_tpl:
                                tex_tpl = o
                    if base_mat_obj and tex_tpl:
                        break
            if base_mat_obj and tex_tpl:
                break

        mat_pids = []
        tex_pids = []
        if base_mat_obj and target_sf:
            extracted_mats = mesh_info.get('materials', [])
            embed_tex = getattr(props, 'embed_textures', True)
            preserve = getattr(props, 'preserve_materials', True)
            has_multiple_or_textures = (len(extracted_mats) > 1 or any(m.get('texture') for m in extracted_mats))

            for i, m_info in enumerate(extracted_mats):
                # C.0. Inject Texture2D if material has an Image Texture
                tex_pid = None
                tex_data = m_info.get('texture')
                if embed_tex and tex_data and tex_tpl:
                    new_tex = copy.copy(tex_tpl)
                    tex_pid = orig_mat_pid - 50000 - i * 10
                    new_tex.path_id = tex_pid
                    t_tree = new_tex.read_typetree()
                    t_tree['m_Name'] = f"{m_info.get('name', f'Mat_{i}')}_MainTex"
                    t_tree['m_Width'] = tex_data['width']
                    t_tree['m_Height'] = tex_data['height']
                    t_tree['m_CompleteImageSize'] = tex_data['width'] * tex_data['height'] * 4
                    t_tree['m_TextureFormat'] = 4  # RGBA32 uncompressed standard
                    t_tree['m_MipCount'] = 1
                    t_tree['m_IsReadable'] = True
                    t_tree['image data'] = tex_data['raw_rgba']
                    t_tree['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
                    new_tex.save_typetree(t_tree)
                    target_sf.objects[tex_pid] = new_tex
                    tex_pids.append(tex_pid)

                # C.0b. Clone or configure Material
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
                ecol = m_info.get('emission', (0.0, 0.0, 0.0, 1.0))

                # Dual-layer protection against Varwin's VisualizationBehaviour:
                # 1) Engine level: AddBehavioursAtRuntime=0 & DisableSceneLogic=1
                # 2) Material level: apply tiny delta (0.001) so CanAddBehaviour (materials.All(m => m.color == firstColor)) returns False!
                if preserve and has_multiple_or_textures:
                    delta = 0.001 * (i % 7 + 1)
                    col = (col[0], max(0.0, col[1] - delta), col[2], col[3] if len(col) > 3 else 1.0)

                for c in tree.get('m_SavedProperties', {}).get('m_Colors', []):
                    if c[0] == '_Color':
                        c[1]['r'] = float(col[0])
                        c[1]['g'] = float(col[1])
                        c[1]['b'] = float(col[2])
                        c[1]['a'] = float(col[3]) if len(col) > 3 else 1.0
                    elif c[0] == '_EmissionColor':
                        c[1]['r'] = float(ecol[0])
                        c[1]['g'] = float(ecol[1])
                        c[1]['b'] = float(ecol[2])
                        c[1]['a'] = 1.0

                # Link Texture2D to _MainTex
                if tex_pid:
                    for t_env in tree.get('m_SavedProperties', {}).get('m_TexEnvs', []):
                        if t_env[0] == '_MainTex':
                            t_env[1]['m_Texture'] = {'m_FileID': 0, 'm_PathID': tex_pid}
                            t_env[1]['m_Scale'] = {'x': 1.0, 'y': 1.0}
                            t_env[1]['m_Offset'] = {'x': 0.0, 'y': 0.0}

                is_emissive = max(ecol[0], ecol[1], ecol[2]) > 0.01
                if is_emissive:
                    if 'm_ValidKeywords' in tree:
                        tree['m_ValidKeywords'] = ['_EMISSION']
                    if 'm_ShaderKeywords' in tree:
                        tree['m_ShaderKeywords'] = '_EMISSION'
                else:
                    if 'm_ValidKeywords' in tree:
                        tree['m_ValidKeywords'] = []
                    if 'm_ShaderKeywords' in tree:
                        tree['m_ShaderKeywords'] = ''

                # Unity Standard Shader renders pitch black if metallic == 1.0 without baked reflection cubemap.
                # Clamp metallic to 0.80 to keep specular sheen while preserving diffuse lighting!
                met = min(float(m_info.get('metallic', 0.0)), 0.80)
                gloss = float(m_info.get('glossiness', 0.5))
                floats = tree.get('m_SavedProperties', {}).get('m_Floats', [])
                tree['m_SavedProperties']['m_Floats'] = [
                    (k, (1.0 if is_emissive else 0.0) if k == '_EmissionEnabled' else
                        (met if k == '_Metallic' else (gloss if k == '_Glossiness' else v)))
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
        for o in env.objects:
            if o.type.name == 'MeshRenderer':
                tree = o.read_typetree()
                if mat_pids:
                    tree['m_Materials'] = [{'m_FileID': 0, 'm_PathID': pid} for pid in mat_pids]
                # Ensure object receives dynamic lighting from Light Probes & Reflection Probes correctly when moved
                tree['m_LightProbeUsage'] = 1  # Blend Probes (samples surrounding light probes dynamically)
                tree['m_ReflectionProbeUsage'] = 1  # Blend Probes
                tree['m_ReceiveShadows'] = 1
                tree['m_CastShadows'] = 1
                # Disable baked lightmap so moving the object doesn't cause lighting artifacts
                tree['m_LightmapIndex'] = 65535
                tree['m_LightmapIndexDynamic'] = 65535
                o.save_typetree(tree)
                break

        # C.2b. Comprehensive patch of AssetBundle (m_Name, m_PreloadTable, and m_Container aliases)
        # This registers cloned materials/textures for eager preloading AND registers both the original
        # template path and custom alias paths (e.g. assets/.../name.prefab, name.prefab) so Varwin can
        # always instantiate the prefab regardless of whether it looks it up by AssetName or template key.
        for o in env.objects:
            if o.type.name == 'AssetBundle':
                tree = o.read_typetree()
                tree['m_Name'] = new_bname
                tree['m_AssetBundleName'] = new_bname

                prefab_info = None
                for path, info in tree.get('m_Container', []):
                    if path.endswith('.prefab'):
                        prefab_info = info
                        break
                if not prefab_info and tree.get('m_Container'):
                    prefab_info = tree['m_Container'][0][1]

                # Preload table for multi-material and textures
                preload_table = tree.get('m_PreloadTable', [])
                existing_pids = {entry.get('m_PathID') for entry in preload_table}
                for pid in mat_pids + tex_pids:
                    if pid not in existing_pids:
                        preload_table.append({'m_FileID': 0, 'm_PathID': pid})
                tree['m_PreloadTable'] = preload_table

                total_preloads = len(preload_table)
                if prefab_info:
                    prefab_info['preloadSize'] = total_preloads

                # Build comprehensive container entries preserving existing template keys while adding aliases
                container_entries = dict(tree.get('m_Container', []))
                for path, info in list(container_entries.items()):
                    info['preloadSize'] = total_preloads

                if prefab_info:
                    container_entries[new_prefab_path] = prefab_info
                    container_entries[new_prefab_path.lower()] = prefab_info
                    container_entries[f"assets/objects/{clean_name}_{clean_root}/{clean_name}.prefab"] = prefab_info
                    container_entries[f"{clean_name}.prefab"] = prefab_info
                    container_entries[f"{clean_name}"] = prefab_info
                    container_entries[f"{safe_asset_name}.prefab"] = prefab_info
                    container_entries[f"{safe_asset_name}"] = prefab_info

                tree['m_Container'] = sorted(container_entries.items(), key=lambda x: x[0])
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
        is_concave_mesh = (collider_type in ('MESH', 'MESH_CONCAVE'))
        for o in env.objects:
            if o.type.name == 'Rigidbody':
                tree = o.read_typetree()
                tree['m_Mass'] = float(getattr(props, 'mass', 1.0))
                if is_concave_mesh:
                    # Unity PhysX strictly forbids non-convex MeshCollider with non-kinematic Rigidbody
                    tree['m_UseGravity'] = False
                    tree['m_IsKinematic'] = True
                else:
                    tree['m_UseGravity'] = bool(getattr(props, 'use_gravity', True))
                    tree['m_IsKinematic'] = bool(getattr(props, 'is_kinematic', False)) if getattr(props, 'use_rigidbody', True) else True
                tree['m_Drag'] = float(getattr(props, 'drag', 0.0))
                tree['m_AngularDrag'] = float(getattr(props, 'angular_drag', 0.05))
                tree['m_Constraints'] = int(constraints)
                cd_val = getattr(props, 'collision_detection', 0)
                cd_map = {'DISCRETE': 0, 'CONTINUOUS': 1, 'CONTINUOUS_DYNAMIC': 2, 'CONTINUOUS_SPECULATIVE': 3}
                tree['m_CollisionDetection'] = cd_map.get(str(cd_val).upper(), int(cd_val) if str(cd_val).isdigit() else 0)
                interp_val = getattr(props, 'interpolate', 0)
                interp_map = {'NONE': 0, 'INTERPOLATE': 1, 'EXTRAPOLATE': 2}
                tree['m_Interpolate'] = interp_map.get(str(interp_val).upper(), int(interp_val) if str(interp_val).isdigit() else 0)
                o.save_typetree(tree)
                break

        # E. In-place patch Colliders
        for o in env.objects:
            if o.type.name == 'MeshCollider':
                tree = o.read_typetree()
                if is_concave_mesh:
                    # Non-convex (hollow) mesh collider: hugs walls, floor, and ceiling, leaving interior completely free for player walking!
                    tree['m_Convex'] = False
                    tree['m_Enabled'] = True
                elif collider_type == 'CONVEX':
                    tree['m_Convex'] = True
                    tree['m_Enabled'] = True
                else:
                    tree['m_Convex'] = False
                    tree['m_Enabled'] = False
                tree['m_IsTrigger'] = bool(getattr(props, 'is_trigger', False))
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

                        # CRITICAL FIX: Protect materials against Varwin's runtime color override!
                        # When preserve_materials is True (default), disable AddBehavioursAtRuntime
                        # and mark DisableSceneLogic = True. This completely disables Varwin's
                        # VisualizationBehaviour so Varwin never replaces MeshRenderer.sharedMaterials
                        # with LitMaterials and never crushes all submeshes into a single color!
                        if preserve:
                            cb['DisableSceneLogic'] = True

                        tree['ConfigBlockly'] = json.dumps(cb, ensure_ascii=False)
                    except Exception as e:
                        print(f"Warning: Failed to update ConfigBlockly: {e}")

                    tree['Name'] = safe_asset_name
                    tree['Guid'] = new_guid
                    tree['RootGuid'] = new_root_guid
                    tree['AuthorName'] = getattr(props, 'author_name', '') or "Blender Artist"
                    if preserve:
                        tree['DisableSceneLogic'] = 1
                        tree['AddBehavioursAtRuntime'] = 0
                    o.save_typetree(tree)
                    break

        out_buf = io.BytesIO()
        out_buf.write(env.file.save())
        template_files[bname] = out_buf.getvalue()

    # 6. Update bundle.json - preserve AssetName from the template!
    # CRITICAL: AssetName must exactly match the prefab name INSIDE the binary AssetBundle.
    # Our exporter reuses a VCylinder template bundle, so the binary always contains
    # 'VCylinder.prefab'. Overwriting AssetName with clean_name causes
    # ArgumentException: The Object you want to instantiate is null.
    # We only update the Assembly list, never AssetName.
    if 'bundle.json' in template_files:
        bjson = json.loads(template_files['bundle.json'].decode('utf-8'))
        # DO NOT change bjson['AssetName'] - keep original value from template (e.g. 'VCylinder')
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
    if preserve:
        install_meta['DisableSceneLogic'] = True
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

    # 1.1. Extract Point Lights from scene (if enabled)
    export_lights = getattr(scene_props, 'export_scene_lights', False)
    scene_point_lights = []
    if export_lights:
        for obj in scene.objects:
            if obj.type == 'LIGHT' and obj.data and obj.data.type == 'POINT' and not obj.hide_get():
                loc = obj.matrix_world.translation if hasattr(obj, 'matrix_world') else obj.location
                # Convert Blender coords (X, Y, Z) to Unity coords (X, Z, Y)
                ux = float(loc.x)
                uy = float(loc.z)
                uz = float(loc.y)
                col = tuple(float(c) for c in obj.data.color[:3])
                # Blender Point lights use Watts (e.g. 100W - 280W). Unity Point lights expect intensity in 0.5 - 2.5 range
                energy = float(getattr(obj.data, 'energy', 25.0))
                # Scale: 100W in Blender ~ 0.5 - 1.2 in Unity realtime
                intensity = max(0.1, min(2.0, (energy / 150.0) if energy > 10.0 else (energy / 15.0)))
                cutoff = getattr(obj.data, 'cutoff_distance', 0.0)
                range_val = float(cutoff) if cutoff > 0.5 else min(10.0, max(3.0, (energy ** 0.5) * 0.75))
                scene_point_lights.append({
                    'name': obj.name,
                    'pos': (ux, uy, uz),
                    'color': col,
                    'intensity': intensity,
                    'range': range_val
                })

    # 1.2. Extract Sun Light if present in scene (and export_lights is enabled)
    sun_obj = next((o for o in scene.objects if o.type == 'LIGHT' and o.data and o.data.type == 'SUN' and not o.hide_get()), None) if export_lights else None
    sun_rot_quat = None
    if sun_obj:
        sun_color = tuple(float(c) for c in sun_obj.data.color[:3])
        # In Blender, sun energy is in lux or W/m² (often 1.0 - 5.0). Clamp to max 2.0 for Unity
        sun_intensity = min(2.0, max(0.0, float(getattr(sun_obj.data, 'energy', 1.0))))
        try:
            import mathutils
            b_dir = (sun_obj.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
            dx, dy, dz = float(b_dir.x), float(b_dir.z), float(b_dir.y)
            pitch = math.asin(max(-1.0, min(1.0, -dy)))
            yaw = math.atan2(dx, dz)
            sun_rot_quat = (
                math.cos(yaw / 2.0) * math.sin(pitch / 2.0),
                math.sin(yaw / 2.0) * math.cos(pitch / 2.0),
                -math.sin(yaw / 2.0) * math.sin(pitch / 2.0),
                math.cos(yaw / 2.0) * math.cos(pitch / 2.0),
            )
        except Exception:
            sun_rot_quat = None
    else:
        sun_color = tuple(float(c) for c in getattr(scene_props, 'light_color', (1.0, 0.98, 0.92))[:3])
        sun_intensity = float(getattr(scene_props, 'light_intensity', 1.0))

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
    for pl in scene_point_lights:
        keep_names.add(pl['name'])

    floor_mesh = mesh_info.get('floor_mesh', mesh_info)
    collision_mesh = mesh_info.get('collision_mesh', mesh_info)

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
            embed_tex = getattr(scene_props, 'embed_textures', True)
            tex_tpl = shared_sf.objects.get(29)
            if not tex_tpl:
                for o in shared_sf.objects.values():
                    if o.type.name == 'Texture2D':
                        tex_tpl = o
                        break

            for i, m_info in enumerate(extracted_mats):
                tex_pid = None
                tex_data = m_info.get('texture')
                if embed_tex and tex_data and tex_tpl:
                    new_tex = copy.copy(tex_tpl)
                    tex_pid = 2900 + i
                    new_tex.path_id = tex_pid
                    t_tree = new_tex.read_typetree()
                    t_tree['m_Name'] = f"{m_info.get('name', f'SceneMat_{i}')}_MainTex"
                    t_tree['m_Width'] = tex_data['width']
                    t_tree['m_Height'] = tex_data['height']
                    t_tree['m_CompleteImageSize'] = tex_data['width'] * tex_data['height'] * 4
                    t_tree['m_TextureFormat'] = 4  # RGBA32
                    t_tree['m_MipCount'] = 1
                    t_tree['m_IsReadable'] = True
                    t_tree['image data'] = tex_data['raw_rgba']
                    t_tree['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
                    new_tex.save_typetree(t_tree)
                    shared_sf.objects[tex_pid] = new_tex

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
                ecol = m_info.get('emission', (0.0, 0.0, 0.0, 1.0))
                is_emissive = max(ecol[0], ecol[1], ecol[2]) > 0.01

                has_em_prop = False
                for c in tree.get('m_SavedProperties', {}).get('m_Colors', []):
                    if c[0] == '_Color':
                        c[1]['r'] = float(col[0])
                        c[1]['g'] = float(col[1])
                        c[1]['b'] = float(col[2])
                        c[1]['a'] = float(col[3]) if len(col) > 3 else 1.0
                    elif c[0] == '_EmissionColor':
                        has_em_prop = True
                        c[1]['r'] = float(ecol[0])
                        c[1]['g'] = float(ecol[1])
                        c[1]['b'] = float(ecol[2])
                        c[1]['a'] = 1.0

                if not has_em_prop and 'm_SavedProperties' in tree and 'm_Colors' in tree['m_SavedProperties']:
                    tree['m_SavedProperties']['m_Colors'].append((
                        '_EmissionColor',
                        {'r': float(ecol[0]), 'g': float(ecol[1]), 'b': float(ecol[2]), 'a': 1.0}
                    ))

                # Link Texture2D to _MainTex
                if tex_pid:
                    for t_env in tree.get('m_SavedProperties', {}).get('m_TexEnvs', []):
                        if t_env[0] == '_MainTex':
                            t_env[1]['m_Texture'] = {'m_FileID': 1, 'm_PathID': tex_pid}

                if is_emissive:
                    if 'm_ValidKeywords' in tree:
                        tree['m_ValidKeywords'] = ['_EMISSION']
                    if 'm_ShaderKeywords' in tree:
                        tree['m_ShaderKeywords'] = '_EMISSION'
                    tree['m_LightmapFlags'] = 2
                else:
                    if 'm_ValidKeywords' in tree:
                        tree['m_ValidKeywords'] = []
                    if 'm_ShaderKeywords' in tree:
                        tree['m_ShaderKeywords'] = ''

                # Clamp metallic to 0.80 to prevent black rendering without cubemap
                met = min(float(m_info.get('metallic', 0.0)), 0.80)
                gloss = float(m_info.get('glossiness', 0.5))
                floats = tree.get('m_SavedProperties', {}).get('m_Floats', [])
                tree['m_SavedProperties']['m_Floats'] = [
                    (k, (1.0 if is_emissive else 0.0) if k == '_EmissionEnabled' else
                        (met if k == '_Metallic' else (gloss if k == '_Glossiness' else v)))
                    for k, v in floats
                ]
                m_obj.save_typetree(tree)
                vwt_mat_pids.append(m_pid)

        # 4.1b. Inject Point Lights into BuildPlayer-VarwinSampleScene
        scene_sf = None
        for bf in env.files.values():
            if hasattr(bf, 'files'):
                for sf_name, sf in bf.files.items():
                    if sf_name == 'BuildPlayer-VarwinSampleScene':
                        scene_sf = sf
                        break
            if scene_sf:
                break

        if scene_sf and 12 in scene_sf.objects and 80 in scene_sf.objects and 219 in scene_sf.objects:
            go_tpl = scene_sf.objects[12]
            tf_tpl = scene_sf.objects[80]
            lt_tpl = scene_sf.objects[219]

            for idx, pl in enumerate(scene_point_lights):
                go_pid = 7000 + idx * 3
                tf_pid = 7001 + idx * 3
                lt_pid = 7002 + idx * 3

                # Clone GameObject
                new_go = copy.copy(go_tpl)
                new_go.path_id = go_pid
                scene_sf.objects[go_pid] = new_go
                gtree = new_go.read_typetree()
                gtree['m_Name'] = pl['name']
                gtree['m_IsActive'] = True
                gtree['m_Layer'] = 0
                gtree['m_Tag'] = 0
                gtree['m_Component'] = [
                    {'component': {'m_FileID': 0, 'm_PathID': tf_pid}},
                    {'component': {'m_FileID': 0, 'm_PathID': lt_pid}}
                ]
                new_go.save_typetree(gtree)

                # Clone Transform
                new_tf = copy.copy(tf_tpl)
                new_tf.path_id = tf_pid
                scene_sf.objects[tf_pid] = new_tf
                ttree = new_tf.read_typetree()
                ttree['m_GameObject'] = {'m_FileID': 0, 'm_PathID': go_pid}
                ttree['m_LocalPosition'] = {
                    'x': float(pl['pos'][0]),
                    'y': float(pl['pos'][1]),
                    'z': float(pl['pos'][2])
                }
                ttree['m_LocalRotation'] = {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0}
                ttree['m_LocalScale'] = {'x': 1.0, 'y': 1.0, 'z': 1.0}
                ttree['m_Father'] = {'m_FileID': 0, 'm_PathID': 0}
                ttree['m_Children'] = []
                new_tf.save_typetree(ttree)

                # Clone Light
                new_lt = copy.copy(lt_tpl)
                new_lt.path_id = lt_pid
                scene_sf.objects[lt_pid] = new_lt
                ltree = new_lt.read_typetree()
                ltree['m_GameObject'] = {'m_FileID': 0, 'm_PathID': go_pid}
                ltree['m_Enabled'] = True
                ltree['m_Type'] = 2  # Point Light
                ltree['m_Intensity'] = float(pl['intensity'])
                ltree['m_Range'] = float(pl['range'])
                ltree['m_Color'] = {
                    'r': float(pl['color'][0]),
                    'g': float(pl['color'][1]),
                    'b': float(pl['color'][2]),
                    'a': 1.0
                }
                ltree['m_Lightmapping'] = 4  # Realtime
                if 'm_BakingOutput' in ltree:
                    ltree['m_BakingOutput']['isBaked'] = False
                    ltree['m_BakingOutput']['lightmapBakeType'] = 4
                if 'm_Shadows' in ltree:
                    ltree['m_Shadows']['m_Type'] = 0  # Disable shadows for Point Lights for Quest 2 90 FPS performance
                new_lt.save_typetree(ltree)

        # 4.1c. Clone Mesh 31 to Mesh 32 for dedicated physical wall/floor collisions (excluding ceilings)
        if shared_sf and 31 in shared_sf.objects:
            mesh32 = copy.copy(shared_sf.objects[31])
            mesh32.path_id = 32
            shared_sf.objects[32] = mesh32
            m32_tree = mesh32.read_typetree()
            m32_tree['m_Name'] = 'BaseWallCollision'
            m32_tree['m_VertexData']['m_VertexCount'] = collision_mesh['vertex_count']
            m32_tree['m_VertexData']['m_DataSize'] = collision_mesh['raw_vertex_data']
            m32_tree['m_VertexData']['m_Channels'] = UNITY_48B_CHANNELS
            m32_tree['m_IndexBuffer'] = collision_mesh['raw_index_buffer']
            m32_tree['m_IndexFormat'] = collision_mesh['index_format']
            m32_tree['m_SubMeshes'] = collision_mesh.get('submeshes', [{
                'firstByte': 0,
                'indexCount': collision_mesh['index_count'],
                'topology': 0,
                'baseVertex': 0,
                'firstVertex': 0,
                'vertexCount': collision_mesh['vertex_count'],
                'localAABB': {
                    'm_Center': collision_mesh['aabb_center'],
                    'm_Extent': collision_mesh['aabb_extent']
                }
            }])
            m32_tree['m_LocalAABB'] = {
                'm_Center': collision_mesh['aabb_center'],
                'm_Extent': collision_mesh['aabb_extent']
            }
            mesh32.save_typetree(m32_tree)

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
                    tree['m_VertexData']['m_VertexCount'] = floor_mesh['vertex_count']
                    tree['m_VertexData']['m_DataSize'] = floor_mesh['raw_vertex_data']
                    tree['m_VertexData']['m_Channels'] = UNITY_48B_CHANNELS
                    tree['m_IndexBuffer'] = floor_mesh['raw_index_buffer']
                    tree['m_IndexFormat'] = floor_mesh['index_format']
                    tree['m_SubMeshes'] = [{
                        'firstByte': 0,
                        'indexCount': floor_mesh['index_count'],
                        'topology': 0,
                        'baseVertex': 0,
                        'firstVertex': 0,
                        'vertexCount': floor_mesh['vertex_count'],
                        'localAABB': {
                            'm_Center': floor_mesh['aabb_center'],
                            'm_Extent': floor_mesh['aabb_extent']
                        }
                    }]
                    tree['m_LocalAABB'] = {
                        'm_Center': floor_mesh['aabb_center'],
                        'm_Extent': floor_mesh['aabb_extent']
                    }
                    o.save_typetree(tree)

        # 4.3. Update MeshRenderer on Base and clear baked lightmap indices
        for o in env.objects:
            if o.type.name == 'MeshRenderer':
                tree = o.read_typetree()
                if vwt_mat_pids:
                    tree['m_Materials'] = [{'m_FileID': 1, 'm_PathID': pid} for pid in vwt_mat_pids]
                else:
                    tree['m_Materials'] = [{'m_FileID': 1, 'm_PathID': 25}]
                # Disable baked lightmap so Unity renders pure realtime & ambient lighting on the new mesh
                tree['m_LightmapIndex'] = 65535
                tree['m_LightmapIndexDynamic'] = 65535
                tree['m_LightmapTilingOffset'] = {'x': 1.0, 'y': 1.0, 'z': 0.0, 'w': 0.0}
                tree['m_LightmapTilingOffsetDynamic'] = {'x': 1.0, 'y': 1.0, 'z': 0.0, 'w': 0.0}
                o.save_typetree(tree)
            elif o.type.name == 'LightmapSettings':
                tree = o.read_typetree()
                tree['m_Lightmaps'] = []
                if 'm_GISettings' in tree:
                    tree['m_GISettings']['m_EnableBakedLightmaps'] = False
                    tree['m_GISettings']['m_EnableRealtimeLightmaps'] = False
                o.save_typetree(tree)

        # 4.4. Reset Transform on Base, TeleportArea, and BaseCollision to remove -90 tilt and 180 deg rotation
        base_go_pids = set()
        for o in env.objects:
            if o.type.name == 'GameObject':
                tree = o.read_typetree()
                gname = tree.get('m_Name')
                if gname in ('Base', 'BaseCollision', 'TeleportArea'):
                    base_go_pids.add(o.path_id)
                if gname == 'Base':
                    tree['m_Tag'] = 20000  # Tag 20000 ('TeleportArea') - essential for Varwin teleport raycast
                    tree['m_Layer'] = 10   # Layer 10 (Location)
                    o.save_typetree(tree)
                elif gname in ('BaseCollision', 'TeleportArea'):
                    tree['m_Tag'] = 20000  # Tag 20000 ('TeleportArea') - dedicated walkable teleport floor
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
                # Base (49) uses Mesh 32 (walls + floor collision, NO ceiling)
                if o.path_id == 207 or go_ref == 49:
                    tree['m_Mesh'] = {'m_FileID': 1, 'm_PathID': 32}
                    tree['m_Enabled'] = True
                    tree['m_IsTrigger'] = False
                    tree['m_Convex'] = False
                    o.save_typetree(tree)
                # BaseCollision (64) uses Mesh 39 (walkable floor ONLY with TeleportArea tag)
                elif o.path_id == 210 or go_ref == 64:
                    tree['m_Mesh'] = {'m_FileID': 1, 'm_PathID': 39}
                    tree['m_Enabled'] = True
                    tree['m_IsTrigger'] = False
                    tree['m_Convex'] = False
                    o.save_typetree(tree)

        # 4.5. Dynamic lookup for Spawn Point Transform and Directional Light
        spawn_tf_pid = None
        light_tf_pid = None
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
                    comps = tree.get('m_Component', [])
                    if len(comps) >= 1:
                        light_tf_pid = comps[0]['component']['m_PathID']
                    if len(comps) >= 2:
                        light_pid = comps[-1]['component']['m_PathID']

        for o in env.objects:
            if o.type.name == 'Transform' and (o.path_id == spawn_tf_pid or o.path_id in (9, 103)):
                tree = o.read_typetree()
                tree['m_LocalPosition'] = {'x': float(sx), 'y': float(sy), 'z': float(sz)}
                tree['m_LocalRotation'] = {'x': 0.0, 'y': float(rot_y), 'z': 0.0, 'w': float(rot_w)}
                o.save_typetree(tree)
            elif o.type.name == 'Transform' and sun_rot_quat and (o.path_id == light_tf_pid or o.path_id == 80):
                tree = o.read_typetree()
                tree['m_LocalRotation'] = {
                    'x': float(sun_rot_quat[0]),
                    'y': float(sun_rot_quat[1]),
                    'z': float(sun_rot_quat[2]),
                    'w': float(sun_rot_quat[3]),
                }
                o.save_typetree(tree)
            elif o.type.name == 'Light' and (o.path_id == light_pid or o.path_id in (14, 219)):
                tree = o.read_typetree()
                # Apply user-specified sun intensity directly without arbitrary caps
                tree['m_Intensity'] = float(sun_intensity)
                tree['m_Color'] = {
                    'r': float(sun_color[0]),
                    'g': float(sun_color[1]),
                    'b': float(sun_color[2]),
                    'a': 1.0
                }
                tree['m_Lightmapping'] = 4
                if 'm_BakingOutput' in tree:
                    tree['m_BakingOutput']['isBaked'] = False
                    tree['m_BakingOutput']['lightmapBakeType'] = 4

                if 'm_Shadows' in tree:
                    shadow_type = getattr(scene_props, 'light_shadows', 'SOFT')
                    shadow_str = float(getattr(scene_props, 'shadow_strength', 0.45))
                    if shadow_type == 'HARD':
                        tree['m_Shadows']['m_Type'] = 1
                        tree['m_Shadows']['m_Strength'] = max(0.0, min(1.0, shadow_str))
                    elif shadow_type == 'SOFT':
                        tree['m_Shadows']['m_Type'] = 2
                        tree['m_Shadows']['m_Strength'] = max(0.0, min(1.0, shadow_str))
                    else:
                        tree['m_Shadows']['m_Type'] = 0
                o.save_typetree(tree)
            elif o.type.name == 'RenderSettings':
                tree = o.read_typetree()
                # Mode 3: Flat Ambient Color (Directly evaluated in Forward Pixel Shader, prevents pitch-black surfaces!)
                tree['m_AmbientMode'] = 3

                amb_intensity = float(getattr(scene_props, 'ambient_intensity', 0.70))
                amb_col = tuple(float(c) for c in getattr(scene_props, 'ambient_color', (0.68, 0.70, 0.75))[:3])

                if sun_obj:
                    # Blend daylight sun color into ambient
                    amb_r = max(0.20, min(1.0, (amb_col[0] * 0.4 + float(sun_color[0]) * 0.6) * amb_intensity))
                    amb_g = max(0.20, min(1.0, (amb_col[1] * 0.4 + float(sun_color[1]) * 0.6) * amb_intensity))
                    amb_b = max(0.20, min(1.0, (amb_col[2] * 0.4 + float(sun_color[2]) * 0.6) * amb_intensity))
                else:
                    amb_r = max(0.20, min(1.0, amb_col[0] * amb_intensity))
                    amb_g = max(0.20, min(1.0, amb_col[1] * amb_intensity))
                    amb_b = max(0.20, min(1.0, amb_col[2] * amb_intensity))

                tree['m_AmbientIntensity'] = 1.0
                tree['m_AmbientSkyColor'] = {
                    'r': amb_r,
                    'g': amb_g,
                    'b': amb_b,
                    'a': 1.0
                }
                tree['m_AmbientEquatorColor'] = tree['m_AmbientSkyColor']
                tree['m_AmbientGroundColor'] = {
                    'r': amb_r * 0.90,
                    'g': amb_g * 0.90,
                    'b': amb_b * 0.90,
                    'a': 1.0
                }

                # Tint subtractive shadows with ambient so shadows don't drop to black voids
                if 'm_SubtractiveShadowColor' in tree:
                    tree['m_SubtractiveShadowColor'] = {
                        'r': max(0.35, amb_r * 0.8),
                        'g': max(0.35, amb_g * 0.8),
                        'b': max(0.35, amb_b * 0.8),
                        'a': 1.0
                    }

                # Set uniform Spherical Harmonics ambient probe to eliminate directional black voids on walls/ceilings!
                if 'm_AmbientProbe' in tree:
                    probe = {}
                    for k in range(27):
                        probe[f'sh[{k:2d}]'] = 0.0
                    # SH0 constant term in Unity Spherical Harmonics
                    probe['sh[ 0]'] = float(amb_r)
                    probe['sh[ 9]'] = float(amb_g)
                    probe['sh[18]'] = float(amb_b)
                    tree['m_AmbientProbe'] = probe

                tree['m_ReflectionIntensity'] = 0.6
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
        'objects_merged': mesh_info['objects_merged'],
        'point_lights_injected': len(scene_point_lights)
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
