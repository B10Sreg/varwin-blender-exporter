import bpy
import bmesh
import struct
import mathutils

def extract_material_properties(mat):
    """
    Extracts PBR properties (Base Color, Metallic, Roughness, Glossiness, Emission)
    from a Blender Material (Principled BSDF or basic diffuse).
    """
    if not mat:
        return {
            'name': 'DefaultMaterial',
            'color': (0.8, 0.8, 0.8, 1.0),
            'metallic': 0.0,
            'roughness': 0.5,
            'glossiness': 0.5,
            'emission': (0.0, 0.0, 0.0, 1.0)
        }

    base_color = (0.8, 0.8, 0.8, 1.0)
    metallic = 0.0
    roughness = 0.5
    emission = (0.0, 0.0, 0.0, 1.0)

    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                if 'Base Color' in node.inputs:
                    base_color = tuple(float(c) for c in node.inputs['Base Color'].default_value[:4])
                if 'Metallic' in node.inputs:
                    metallic = float(node.inputs['Metallic'].default_value)
                if 'Roughness' in node.inputs:
                    roughness = float(node.inputs['Roughness'].default_value)
                if 'Emission Color' in node.inputs or 'Emission' in node.inputs:
                    em_input = node.inputs.get('Emission Color', node.inputs.get('Emission'))
                    raw_em = tuple(float(c) for c in em_input.default_value[:4])
                    em_strength = 1.0
                    if 'Emission Strength' in node.inputs:
                        em_strength = float(node.inputs['Emission Strength'].default_value)
                    if em_strength > 0.0:
                        emission = (raw_em[0] * em_strength, raw_em[1] * em_strength, raw_em[2] * em_strength, 1.0)
                    else:
                        emission = (0.0, 0.0, 0.0, 1.0)
                break
    else:
        base_color = tuple(float(c) for c in mat.diffuse_color[:4])
        metallic = float(getattr(mat, 'metallic', 0.0))
        roughness = float(getattr(mat, 'roughness', 0.5))

    return {
        'name': mat.name,
        'color': base_color,
        'metallic': max(0.0, min(1.0, metallic)),
        'roughness': max(0.0, min(1.0, roughness)),
        'glossiness': max(0.0, min(1.0, 1.0 - roughness)),
        'emission': emission
    }


def extract_mesh_data(obj: bpy.types.Object, apply_modifiers: bool = True):
    """
    Evaluates, triangulates, extracts vertex/index buffers and per-material submeshes
    from Blender object ready for direct injection into UnityFS AssetBundle.
    """
    if obj.type != 'MESH':
        raise ValueError(f"Объект '{obj.name}' не является полигональным мешем (тип: {obj.type})")

    # Evaluate with modifiers
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph) if apply_modifiers else obj
    mesh = eval_obj.to_mesh()

    # Triangulate via bmesh
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()

    mesh.calc_loop_triangles()

    has_uv = bool(mesh.uv_layers.active)
    uv_data = mesh.uv_layers.active.data if has_uv else None

    # Collect materials info
    materials = []
    if obj.material_slots:
        for slot in obj.material_slots:
            materials.append(extract_material_properties(slot.material))
    if not materials:
        materials.append(extract_material_properties(None))

    num_materials = len(materials)

    # Group loop_triangles by material_index
    triangles_by_mat = {i: [] for i in range(num_materials)}
    for tri in mesh.loop_triangles:
        poly = mesh.polygons[tri.polygon_index]
        m_idx = poly.material_index if 0 <= poly.material_index < num_materials else 0
        triangles_by_mat[m_idx].append(tri)

    vertices_data = []
    submesh_indices_list = []
    vert_map = {}

    min_x, max_x = float('inf'), float('-inf')
    min_y, max_y = float('inf'), float('-inf')
    min_z, max_z = float('inf'), float('-inf')

    submesh_aabbs = []
    active_materials = []

    for m_idx in range(num_materials):
        tris = triangles_by_mat[m_idx]
        if not tris:
            continue

        active_materials.append(materials[m_idx])
        sub_indices = []
        s_min_x, s_max_x = float('inf'), float('-inf')
        s_min_y, s_max_y = float('inf'), float('-inf')
        s_min_z, s_max_z = float('inf'), float('-inf')

        for tri in tris:
            # Unity left-handed: flip winding order (0, 2, 1)
            for loop_idx in (tri.loops[0], tri.loops[2], tri.loops[1]):
                loop = mesh.loops[loop_idx]
                v = mesh.vertices[loop.vertex_index]

                # Coordinate conversion: Blender (x, y, z) -> Unity (x, z, y)
                px = float(v.co.x)
                py = float(v.co.z)
                pz = float(v.co.y)

                norm = loop.normal
                nx = float(norm.x)
                ny = float(norm.z)
                nz = float(norm.y)

                if has_uv:
                    u = float(uv_data[loop_idx].uv[0])
                    v_coord = float(uv_data[loop_idx].uv[1])
                else:
                    u, v_coord = 0.0, 0.0

                min_x = min(min_x, px)
                max_x = max(max_x, px)
                min_y = min(min_y, py)
                max_y = max(max_y, py)
                min_z = min(min_z, pz)
                max_z = max(max_z, pz)

                s_min_x = min(s_min_x, px)
                s_max_x = max(s_max_x, px)
                s_min_y = min(s_min_y, py)
                s_max_y = max(s_max_y, py)
                s_min_z = min(s_min_z, pz)
                s_max_z = max(s_max_z, pz)

                key = (
                    round(px, 5), round(py, 5), round(pz, 5),
                    round(nx, 4), round(ny, 4), round(nz, 4),
                    round(u, 4), round(v_coord, 4)
                )

                if key not in vert_map:
                    new_idx = len(vertices_data)
                    vert_map[key] = new_idx
                    # Standard 48-byte vertex layout
                    v_bytes = struct.pack(
                        '<3f3f4f2f',
                        px, py, pz,
                        nx, ny, nz,
                        1.0, 0.0, 0.0, 1.0,  # Tangent
                        u, v_coord            # UV
                    )
                    vertices_data.append(v_bytes)
                    sub_indices.append(new_idx)
                else:
                    sub_indices.append(vert_map[key])

        submesh_indices_list.append(sub_indices)
        sub_cx = (s_min_x + s_max_x) * 0.5
        sub_cy = (s_min_y + s_max_y) * 0.5
        sub_cz = (s_min_z + s_max_z) * 0.5
        sub_ex = max(0.001, (s_max_x - s_min_x) * 0.5)
        sub_ey = max(0.001, (s_max_y - s_min_y) * 0.5)
        sub_ez = max(0.001, (s_max_z - s_min_z) * 0.5)
        submesh_aabbs.append((sub_cx, sub_cy, sub_cz, sub_ex, sub_ey, sub_ez))

    # Free evaluated mesh
    if apply_modifiers:
        eval_obj.to_mesh_clear()

    if not vertices_data:
        min_x = max_x = min_y = max_y = min_z = max_z = 0.0

    cx = (min_x + max_x) * 0.5
    cy = (min_y + max_y) * 0.5
    cz = (min_z + max_z) * 0.5
    ex = max(0.001, (max_x - min_x) * 0.5)
    ey = max(0.001, (max_y - min_y) * 0.5)
    ez = max(0.001, (max_z - min_z) * 0.5)

    use_32bit = len(vertices_data) > 65535
    fmt_char = 'I' if use_32bit else 'H'

    all_raw_ib = []
    submesh_descriptors = []
    byte_offset = 0

    for i, sub_idxs in enumerate(submesh_indices_list):
        raw_sub = struct.pack(f'<{len(sub_idxs)}{fmt_char}', *sub_idxs)
        all_raw_ib.append(raw_sub)

        first_v = min(sub_idxs) if sub_idxs else 0
        v_count = (max(sub_idxs) - first_v + 1) if sub_idxs else 0
        aabb = submesh_aabbs[i]

        submesh_descriptors.append({
            'firstByte': byte_offset,
            'indexCount': len(sub_idxs),
            'topology': 0,
            'baseVertex': 0,
            'firstVertex': first_v,
            'vertexCount': v_count,
            'localAABB': {
                'm_Center': {'x': aabb[0], 'y': aabb[1], 'z': aabb[2]},
                'm_Extent': {'x': aabb[3], 'y': aabb[4], 'z': aabb[5]}
            }
        })
        byte_offset += len(raw_sub)

    total_index_count = sum(len(s) for s in submesh_indices_list)

    return {
        'vertex_count': len(vertices_data),
        'triangle_count': total_index_count // 3,
        'raw_vertex_data': b''.join(vertices_data),
        'raw_index_buffer': b''.join(all_raw_ib),
        'index_format': 1 if use_32bit else 0,
        'index_count': total_index_count,
        'submeshes': submesh_descriptors,
        'materials': active_materials if active_materials else materials,
        'aabb_center': {'x': cx, 'y': cy, 'z': cz},
        'aabb_extent': {'x': ex, 'y': ey, 'z': ez},
        'dimensions': {'x': ex * 2.0, 'y': ey * 2.0, 'z': ez * 2.0},
        'radius': (ex**2 + ey**2 + ez**2)**0.5
    }


def _pack_triangles(triangles_list):
    """
    Packs a list of triangles [ (v0, v1, v2), ... ] where each v is (px, py, pz, nx, ny, nz, u, v)
    into vertex and index buffers matching Unity 48-byte layout.
    """
    v_data = []
    v_map = {}
    indices = []
    min_x, max_x = float('inf'), float('-inf')
    min_y, max_y = float('inf'), float('-inf')
    min_z, max_z = float('inf'), float('-inf')

    for tri in triangles_list:
        for vert in tri:
            px, py, pz, nx, ny, nz, u, v_coord = vert
            min_x = min(min_x, px)
            max_x = max(max_x, px)
            min_y = min(min_y, py)
            max_y = max(max_y, py)
            min_z = min(min_z, pz)
            max_z = max(max_z, pz)
            key = (round(px, 5), round(py, 5), round(pz, 5), round(nx, 4), round(ny, 4), round(nz, 4))
            if key not in v_map:
                idx = len(v_data)
                v_map[key] = idx
                v_data.append(struct.pack('<3f3f4f2f', px, py, pz, nx, ny, nz, 1.0, 0.0, 0.0, 1.0, u, v_coord))
                indices.append(idx)
            else:
                indices.append(v_map[key])

    if not v_data:
        min_x = max_x = min_y = max_y = min_z = max_z = 0.0

    cx = (min_x + max_x) * 0.5
    cy = (min_y + max_y) * 0.5
    cz = (min_z + max_z) * 0.5
    ex = max(0.001, (max_x - min_x) * 0.5)
    ey = max(0.001, (max_y - min_y) * 0.5)
    ez = max(0.001, (max_z - min_z) * 0.5)

    use_32bit = len(v_data) > 65535
    fmt_char = 'I' if use_32bit else 'H'
    raw_ib = struct.pack(f'<{len(indices)}{fmt_char}', *indices)

    return {
        'vertex_count': len(v_data),
        'triangle_count': len(indices) // 3,
        'raw_vertex_data': b''.join(v_data),
        'raw_index_buffer': raw_ib,
        'index_format': 1 if use_32bit else 0,
        'index_count': len(indices),
        'submeshes': [{
            'firstByte': 0,
            'indexCount': len(indices),
            'topology': 0,
            'baseVertex': 0,
            'firstVertex': 0,
            'vertexCount': len(v_data),
            'localAABB': {
                'm_Center': {'x': cx, 'y': cy, 'z': cz},
                'm_Extent': {'x': ex, 'y': ey, 'z': ez}
            }
        }],
        'aabb_center': {'x': cx, 'y': cy, 'z': cz},
        'aabb_extent': {'x': ex, 'y': ey, 'z': ez}
    }


def extract_scene_geometry(scene, selected_only: bool = False, apply_modifiers: bool = True):
    """
    Extracts and merges visible meshes from the Blender scene in world space,
    preserving materials and creating per-material submeshes for Scene Template (.vwt).
    Also generates dedicated floor_mesh (for TeleportArea BaseCollision) and
    collision_mesh (for Base MeshCollider, omitting ceilings).
    """
    if selected_only and bpy.context and bpy.context.selected_objects:
        mesh_objs = [o for o in bpy.context.selected_objects if o.type == 'MESH' and not o.hide_get()]
    else:
        mesh_objs = [o for o in scene.objects if o.type == 'MESH' and not o.hide_get()]

    if not mesh_objs:
        raise ValueError("В сцене нет видимых полигональных мешей для экспорта в шаблон сцены!")

    depsgraph = bpy.context.evaluated_depsgraph_get()

    vertices_data = []
    vert_map = {}

    min_x, max_x = float('inf'), float('-inf')
    min_y, max_y = float('inf'), float('-inf')
    min_z, max_z = float('inf'), float('-inf')

    # Collect materials across all scene meshes
    material_map = {}  # mat_name -> (index, mat_props, [tri_indices], [s_min, s_max])
    ordered_materials = []

    floor_triangles = []
    collision_triangles = []
    all_triangles = []

    for obj in mesh_objs:
        eval_obj = obj.evaluated_get(depsgraph) if apply_modifiers else obj
        mesh = eval_obj.to_mesh()

        # Triangulate
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()

        mesh.calc_loop_triangles()

        mat_world = obj.matrix_world
        norm_mat = mat_world.to_3x3().inverted().transposed()

        has_uv = bool(mesh.uv_layers.active)
        uv_data = mesh.uv_layers.active.data if has_uv else None

        obj_materials = []
        if obj.material_slots:
            for slot in obj.material_slots:
                obj_materials.append(extract_material_properties(slot.material))
        if not obj_materials:
            obj_materials.append(extract_material_properties(None))

        for tri in mesh.loop_triangles:
            poly = mesh.polygons[tri.polygon_index]
            slot_idx = poly.material_index if 0 <= poly.material_index < len(obj_materials) else 0
            mat_props = obj_materials[slot_idx]
            mat_key = mat_props['name']

            if mat_key not in material_map:
                material_map[mat_key] = {
                    'props': mat_props,
                    'indices': [],
                    'bounds': [float('inf'), float('-inf'), float('inf'), float('-inf'), float('inf'), float('-inf')]
                }
                ordered_materials.append(mat_key)

            entry = material_map[mat_key]
            tri_verts = []

            for loop_idx in (tri.loops[0], tri.loops[2], tri.loops[1]):
                loop = mesh.loops[loop_idx]
                v = mesh.vertices[loop.vertex_index]

                # World space position: Blender (x, y, z) -> Unity (x, z, y)
                w_pos = mat_world @ v.co
                px = float(w_pos.x)
                py = float(w_pos.z)
                pz = float(w_pos.y)

                # World normal
                w_norm = (norm_mat @ loop.normal).normalized()
                nx = float(w_norm.x)
                ny = float(w_norm.z)
                nz = float(w_norm.y)

                if has_uv:
                    u = float(uv_data[loop_idx].uv[0])
                    v_coord = float(uv_data[loop_idx].uv[1])
                else:
                    # Planar UV mapping based on normal orientation (Unity coords: Y is up)
                    abs_nx, abs_ny, abs_nz = abs(nx), abs(ny), abs(nz)
                    if abs_ny >= abs_nx and abs_ny >= abs_nz:
                        u, v_coord = px * 0.5, pz * 0.5
                    elif abs_nx >= abs_ny and abs_nx >= abs_nz:
                        u, v_coord = pz * 0.5, py * 0.5
                    else:
                        u, v_coord = px * 0.5, py * 0.5

                tri_verts.append((px, py, pz, nx, ny, nz, u, v_coord))

                min_x = min(min_x, px)
                max_x = max(max_x, px)
                min_y = min(min_y, py)
                max_y = max(max_y, py)
                min_z = min(min_z, pz)
                max_z = max(max_z, pz)

                b = entry['bounds']
                b[0] = min(b[0], px)
                b[1] = max(b[1], px)
                b[2] = min(b[2], py)
                b[3] = max(b[3], py)
                b[4] = min(b[4], pz)
                b[5] = max(b[5], pz)

                key = (
                    round(px, 5), round(py, 5), round(pz, 5),
                    round(nx, 4), round(ny, 4), round(nz, 4),
                    round(u, 4), round(v_coord, 4)
                )

                if key not in vert_map:
                    new_idx = len(vertices_data)
                    vert_map[key] = new_idx
                    v_bytes = struct.pack(
                        '<3f3f4f2f',
                        px, py, pz,
                        nx, ny, nz,
                        1.0, 0.0, 0.0, 1.0,
                        u, v_coord
                    )
                    vertices_data.append(v_bytes)
                    entry['indices'].append(new_idx)
                else:
                    entry['indices'].append(vert_map[key])

            # Classify triangle
            avg_ny = (tri_verts[0][4] + tri_verts[1][4] + tri_verts[2][4]) / 3.0
            avg_py = (tri_verts[0][1] + tri_verts[1][1] + tri_verts[2][1]) / 3.0

            # 1. Walkable floor (normal up, near floor level)
            if avg_ny > 0.6 and avg_py <= 0.35:
                floor_triangles.append(tri_verts)

            # 2. Collision (walls, pillars, floors - exclude ceiling above 1.8m facing down or high geometry)
            is_ceiling = (avg_ny < -0.5 and avg_py > 1.8) or (avg_py > 2.65 and avg_ny < -0.2)
            if not is_ceiling:
                collision_triangles.append(tri_verts)

            all_triangles.append(tri_verts)

        if apply_modifiers:
            eval_obj.to_mesh_clear()

    if not vertices_data:
        min_x = max_x = min_y = max_y = min_z = max_z = 0.0

    cx = (min_x + max_x) * 0.5
    cy = (min_y + max_y) * 0.5
    cz = (min_z + max_z) * 0.5
    ex = max(0.001, (max_x - min_x) * 0.5)
    ey = max(0.001, (max_y - min_y) * 0.5)
    ez = max(0.001, (max_z - min_z) * 0.5)

    use_32bit = len(vertices_data) > 65535
    fmt_char = 'I' if use_32bit else 'H'

    all_raw_ib = []
    submesh_descriptors = []
    final_materials = []
    byte_offset = 0

    for mat_key in ordered_materials:
        entry = material_map[mat_key]
        sub_idxs = entry['indices']
        if not sub_idxs:
            continue

        raw_sub = struct.pack(f'<{len(sub_idxs)}{fmt_char}', *sub_idxs)
        all_raw_ib.append(raw_sub)

        b = entry['bounds']
        sub_cx = (b[0] + b[1]) * 0.5
        sub_cy = (b[2] + b[3]) * 0.5
        sub_cz = (b[4] + b[5]) * 0.5
        sub_ex = max(0.001, (b[1] - b[0]) * 0.5)
        sub_ey = max(0.001, (b[3] - b[2]) * 0.5)
        sub_ez = max(0.001, (b[5] - b[4]) * 0.5)

        first_v = min(sub_idxs) if sub_idxs else 0
        v_count = (max(sub_idxs) - first_v + 1) if sub_idxs else 0

        submesh_descriptors.append({
            'firstByte': byte_offset,
            'indexCount': len(sub_idxs),
            'topology': 0,
            'baseVertex': 0,
            'firstVertex': first_v,
            'vertexCount': v_count,
            'localAABB': {
                'm_Center': {'x': sub_cx, 'y': sub_cy, 'z': sub_cz},
                'm_Extent': {'x': sub_ex, 'y': sub_ey, 'z': sub_ez}
            }
        })
        byte_offset += len(raw_sub)
        final_materials.append(entry['props'])

    total_index_count = sum(len(material_map[k]['indices']) for k in ordered_materials)

    # Fallbacks if floor or collision filters were too strict
    if not floor_triangles:
        floor_triangles = [t for t in all_triangles if (t[0][4] + t[1][4] + t[2][4]) / 3.0 > 0.5]
    if not floor_triangles:
        floor_triangles = all_triangles

    if not collision_triangles:
        collision_triangles = all_triangles

    floor_mesh_dict = _pack_triangles(floor_triangles)
    collision_mesh_dict = _pack_triangles(collision_triangles)

    return {
        'vertex_count': len(vertices_data),
        'triangle_count': total_index_count // 3,
        'raw_vertex_data': b''.join(vertices_data),
        'raw_index_buffer': b''.join(all_raw_ib),
        'index_format': 1 if use_32bit else 0,
        'index_count': total_index_count,
        'submeshes': submesh_descriptors,
        'materials': final_materials,
        'aabb_center': {'x': cx, 'y': cy, 'z': cz},
        'aabb_extent': {'x': ex, 'y': ey, 'z': ez},
        'dimensions': {'x': ex * 2.0, 'y': ey * 2.0, 'z': ez * 2.0},
        'radius': (ex**2 + ey**2 + ez**2)**0.5,
        'objects_merged': len(mesh_objs),
        'floor_mesh': floor_mesh_dict,
        'collision_mesh': collision_mesh_dict
    }
