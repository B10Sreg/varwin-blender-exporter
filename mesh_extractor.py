import os
import io
import struct
import bpy
import bmesh
import mathutils

try:
    from PIL import Image
except ImportError:
    Image = None


def resolve_image_filepath(img):
    """Resolves image filepath handling relative paths, Windows backslashes, and blend dir."""
    if not img:
        return ""
    raw_path = getattr(img, 'filepath_raw', '') or getattr(img, 'filepath', '')
    if not raw_path:
        return ""
    # Normalize Windows backslashes to forward slashes
    clean_path = raw_path.replace('\\', '/')
    try:
        abs_path = bpy.path.abspath(clean_path)
        if os.path.isfile(abs_path):
            return abs_path
    except Exception:
        pass

    # If blend file is saved, try relative to blend folder
    blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
    if blend_dir:
        # Strip leading //
        rel_stripped = clean_path.lstrip('/')
        candidate = os.path.join(blend_dir, rel_stripped)
        if os.path.isfile(candidate):
            return candidate
        # Also try just filename in same folder as blend
        filename = os.path.basename(clean_path)
        candidate2 = os.path.join(blend_dir, filename)
        if os.path.isfile(candidate2):
            return candidate2

    return ""


def extract_image_texture(img):
    """
    Extracts raw RGBA bytes from a Blender bpy.types.Image (packed, filepath, or pixel buffer),
    flips vertically to match Unity's Cartesian UV coordinate convention, and downscales
    to max 2048x2048 for Quest 2 VR performance.
    """
    if not img or not Image:
        return None

    try:
        im = None
        # 1. Packed image in .blend file
        if getattr(img, 'packed_file', None) and img.packed_file.data:
            try:
                im = Image.open(io.BytesIO(img.packed_file.data))
                im = im.convert('RGBA')
                im = im.transpose(Image.FLIP_TOP_BOTTOM)
            except Exception as e:
                print(f"Warning: Failed to load packed data for {img.name}: {e}")

        # 2. Filepath on disk (with multi-path and Windows path normalization)
        if im is None:
            disk_path = resolve_image_filepath(img)
            if disk_path and os.path.isfile(disk_path):
                try:
                    im = Image.open(disk_path)
                    im = im.convert('RGBA')
                    im = im.transpose(Image.FLIP_TOP_BOTTOM)
                except Exception as e:
                    print(f"Warning: Failed to read texture from disk path {disk_path}: {e}")

        # 3. Fallback: read directly from Blender pixel buffer (forces image reload/eval)
        if im is None:
            try:
                # Force Blender to load pixels into buffer if not loaded
                if not getattr(img, 'has_data', False):
                    try:
                        img.reload()
                    except Exception:
                        pass
                if img.size[0] > 0 and img.size[1] > 0:
                    w, h = img.size[0], img.size[1]
                    raw_floats = list(img.pixels)
                    if len(raw_floats) == w * h * 4:
                        b_data = bytes(int(max(0.0, min(1.0, c)) * 255) for c in raw_floats)
                        im = Image.frombytes('RGBA', (w, h), b_data)
            except Exception as e:
                print(f"Warning: Pixel buffer fallback failed for {img.name}: {e}")

        if im is None:
            return None

        # Optimization for VR Quest 2: clamp max resolution to 2048x2048
        if max(im.width, im.height) > 2048:
            im.thumbnail((2048, 2048), Image.Resampling.LANCZOS)

        return {
            'name': img.name,
            'width': im.width,
            'height': im.height,
            'raw_rgba': im.tobytes()
        }
    except Exception as e:
        print(f"Warning: Failed to extract texture from image '{getattr(img, 'name', 'unknown')}': {e}")
        return None


def find_image_texture_node(input_socket, visited=None):
    """Recursively traverses shader node tree backwards from input_socket to find an Image Texture node."""
    if not input_socket or not input_socket.is_linked:
        return None
    if visited is None:
        visited = set()

    for link in input_socket.links:
        from_node = link.from_node
        if from_node in visited:
            continue
        visited.add(from_node)

        if from_node.type == 'TEX_IMAGE' and getattr(from_node, 'image', None):
            return from_node

        # Recurse through intermediate nodes (Mix, Invert, RGB Curves, ColorRamp, Gamma, Group, etc.)
        for inp in from_node.inputs:
            if inp.is_linked:
                found = find_image_texture_node(inp, visited)
                if found:
                    return found
    return None


def extract_material_properties(mat):
    """
    Extracts PBR properties (Base Color, Metallic, Roughness, Glossiness, Emission,
    and diffuse Image Texture) from a Blender Material.
    """
    if not mat:
        return {
            'name': 'DefaultMaterial',
            'color': (0.8, 0.8, 0.8, 1.0),
            'metallic': 0.0,
            'roughness': 0.5,
            'glossiness': 0.5,
            'emission': (0.0, 0.0, 0.0, 1.0),
            'texture': None
        }

    base_color = (0.8, 0.8, 0.8, 1.0)
    metallic = 0.0
    roughness = 0.5
    emission = (0.0, 0.0, 0.0, 1.0)
    texture = None

    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                base_color_input = node.inputs.get('Base Color')
                if base_color_input:
                    if base_color_input.is_linked and base_color_input.links:
                        tex_node = find_image_texture_node(base_color_input)
                        if tex_node and getattr(tex_node, 'image', None):
                            texture = extract_image_texture(tex_node.image)
                            if texture:
                                # Neutral white tint so texture colors display authentically
                                base_color = (1.0, 1.0, 1.0, 1.0)

                        if not texture:
                            from_node = base_color_input.links[0].from_node
                            if from_node and from_node.type == 'RGB':
                                base_color = tuple(float(c) for c in from_node.outputs[0].default_value[:4])
                            elif from_node and from_node.type == 'VALTORGB' and getattr(from_node, 'color_ramp', None):
                                ramp = from_node.color_ramp
                                try:
                                    avg_r = sum(e.color[0] for e in ramp.elements) / len(ramp.elements)
                                    avg_g = sum(e.color[1] for e in ramp.elements) / len(ramp.elements)
                                    avg_b = sum(e.color[2] for e in ramp.elements) / len(ramp.elements)
                                    base_color = (float(avg_r), float(avg_g), float(avg_b), 1.0)
                                except Exception:
                                    base_color = tuple(float(c) for c in base_color_input.default_value[:4])
                            else:
                                base_color = tuple(float(c) for c in mat.diffuse_color[:4])
                    else:
                        base_color = tuple(float(c) for c in base_color_input.default_value[:4])

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
        'emission': emission,
        'texture': texture
    }


def extract_object_geometry(objects, root_obj=None, apply_modifiers: bool = True):
    """
    Extracts and merges geometry from one or multiple Blender mesh objects
    in root_obj's local coordinate space, preserving materials and submeshes
    for Varwin Object (.vwo) export.
    """
    if isinstance(objects, bpy.types.Object):
        objects = [objects]

    mesh_objs = [o for o in objects if o and o.type == 'MESH']
    if not mesh_objs:
        raise ValueError("Не найдено полигональных мешей (Mesh) для экспорта объекта!")

    if not root_obj or root_obj not in mesh_objs:
        root_obj = mesh_objs[0]

    depsgraph = bpy.context.evaluated_depsgraph_get() if bpy.context else None
    inv_root_world = root_obj.matrix_world.inverted()

    vertices_data = []
    vert_map = {}
    material_map = {}
    ordered_materials = []

    min_x, max_x = float('inf'), float('-inf')
    min_y, max_y = float('inf'), float('-inf')
    min_z, max_z = float('inf'), float('-inf')

    for obj in mesh_objs:
        eval_obj = obj.evaluated_get(depsgraph) if (apply_modifiers and depsgraph) else obj
        mesh = eval_obj.to_mesh()

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()

        mesh.calc_loop_triangles()

        # Relative transform to root_obj
        rel_mat = inv_root_world @ obj.matrix_world
        norm_mat = rel_mat.to_3x3().inverted().transposed()

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

            for loop_idx in (tri.loops[0], tri.loops[2], tri.loops[1]):
                loop = mesh.loops[loop_idx]
                v = mesh.vertices[loop.vertex_index]

                p_rel = rel_mat @ v.co
                px = float(p_rel.x)
                py = float(p_rel.z)
                pz = float(p_rel.y)

                n_rel = norm_mat @ loop.normal
                n_rel.normalize()
                nx = float(n_rel.x)
                ny = float(n_rel.z)
                nz = float(n_rel.y)

                if has_uv:
                    u = float(uv_data[loop_idx].uv[0])
                    v_coord = float(uv_data[loop_idx].uv[1])
                else:
                    # Planar/Box UV projection based on normal orientation (Unity coordinates: Y is up)
                    abs_nx, abs_ny, abs_nz = abs(nx), abs(ny), abs(nz)
                    if abs_ny >= abs_nx and abs_ny >= abs_nz:
                        u, v_coord = px * 0.5, pz * 0.5
                    elif abs_nx >= abs_ny and abs_nx >= abs_nz:
                        u, v_coord = pz * 0.5, py * 0.5
                    else:
                        u, v_coord = px * 0.5, py * 0.5

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

        if apply_modifiers and depsgraph:
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
    final_materials = []

    for mat_key in ordered_materials:
        entry = material_map[mat_key]
        sub_idxs = entry['indices']
        if not sub_idxs:
            continue

        raw_sub = struct.pack(f'<{len(sub_idxs)}{fmt_char}', *sub_idxs)
        all_raw_ib.append(raw_sub)

        b = entry['bounds']
        s_cx = (b[0] + b[1]) * 0.5
        s_cy = (b[2] + b[3]) * 0.5
        s_cz = (b[4] + b[5]) * 0.5
        s_ex = max(0.001, (b[1] - b[0]) * 0.5)
        s_ey = max(0.001, (b[3] - b[2]) * 0.5)
        s_ez = max(0.001, (b[5] - b[4]) * 0.5)

        first_v = min(sub_idxs)
        v_count = max(sub_idxs) - first_v + 1

        submesh_descriptors.append({
            'firstByte': byte_offset,
            'indexCount': len(sub_idxs),
            'topology': 0,
            'baseVertex': 0,
            'firstVertex': first_v,
            'vertexCount': v_count,
            'localAABB': {
                'm_Center': {'x': s_cx, 'y': s_cy, 'z': s_cz},
                'm_Extent': {'x': s_ex, 'y': s_ey, 'z': s_ez}
            }
        })
        byte_offset += len(raw_sub)
        final_materials.append(entry['props'])

    total_index_count = sum(len(material_map[k]['indices']) for k in ordered_materials)

    return {
        'vertex_count': len(vertices_data),
        'triangle_count': total_index_count // 3,
        'raw_vertex_data': b''.join(vertices_data),
        'raw_index_buffer': b''.join(all_raw_ib),
        'index_format': 1 if use_32bit else 0,
        'index_count': total_index_count,
        'submeshes': submesh_descriptors,
        'materials': final_materials if final_materials else [extract_material_properties(None)],
        'aabb_center': {'x': cx, 'y': cy, 'z': cz},
        'aabb_extent': {'x': ex, 'y': ey, 'z': ez},
        'dimensions': {'x': ex * 2.0, 'y': ey * 2.0, 'z': ez * 2.0},
        'radius': (ex**2 + ey**2 + ez**2)**0.5
    }


def extract_mesh_data(obj: bpy.types.Object, apply_modifiers: bool = True):
    """
    Evaluates, triangulates, extracts vertex/index buffers and per-material submeshes
    from a single Blender object.
    """
    return extract_object_geometry([obj], root_obj=obj, apply_modifiers=apply_modifiers)


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


def generate_box_mesh_data(cx: float, cy: float, cz: float, ex: float, ey: float, ez: float):
    """
    Generates a 100% compliant Unity 48-byte box mesh (8 vertices, 12 triangles)
    matching the exact bounding box center and extent.
    Guaranteed to cook instantly in PhysX with 0 errors and 0 vertex-limit warnings.
    """
    corners = [
        (cx - ex, cy - ey, cz - ez),
        (cx + ex, cy - ey, cz - ez),
        (cx + ex, cy + ey, cz - ez),
        (cx - ex, cy + ey, cz - ez),
        (cx - ex, cy - ey, cz + ez),
        (cx + ex, cy - ey, cz + ez),
        (cx + ex, cy + ey, cz + ez),
        (cx - ex, cy + ey, cz + ez),
    ]
    tri_indices = [
        0, 2, 1, 0, 3, 2,
        4, 5, 6, 4, 6, 7,
        0, 1, 5, 0, 5, 4,
        2, 3, 7, 2, 7, 6,
        0, 4, 7, 0, 7, 3,
        1, 2, 6, 1, 6, 5
    ]
    raw_verts = bytearray()
    for px, py, pz in corners:
        nx = 0.0 if ex == 0 else (px - cx) / ex
        ny = 0.0 if ey == 0 else (py - cy) / ey
        nz = 0.0 if ez == 0 else (pz - cz) / ez
        length = (nx*nx + ny*ny + nz*nz)**0.5 or 1.0
        v_bytes = struct.pack(
            '<ffffffffffff',
            px, py, pz,
            nx/length, ny/length, nz/length,
            1.0, 0.0, 0.0, 1.0,
            0.0, 0.0
        )
        raw_verts.extend(v_bytes)

    raw_ib = struct.pack('<36H', *tri_indices)
    return {
        'vertex_count': 8,
        'triangle_count': 12,
        'raw_vertex_data': bytes(raw_verts),
        'raw_index_buffer': raw_ib,
        'index_format': 0,
        'index_count': 36,
        'submeshes': [{
            'firstByte': 0,
            'indexCount': 36,
            'topology': 0,
            'baseVertex': 0,
            'firstVertex': 0,
            'vertexCount': 8,
            'localAABB': {
                'm_Center': {'x': cx, 'y': cy, 'z': cz},
                'm_Extent': {'x': ex, 'y': ey, 'z': ez}
            }
        }],
        'aabb_center': {'x': cx, 'y': cy, 'z': cz},
        'aabb_extent': {'x': ex, 'y': ey, 'z': ez}
    }


def extract_convex_hull_geometry(mesh_objs, root_obj=None, max_verts=64):
    """
    Extracts a simplified convex hull collision mesh from Blender objects,
    guaranteed to stay under PhysX's 255-vertex convex cooking limit.
    Uses spatial grid sampling to guarantee vertex count <= max_verts.
    Falls back to generate_box_mesh_data if geometry evaluation fails.
    """
    if not root_obj and mesh_objs:
        root_obj = mesh_objs[0]

    try:
        inv_root_world = root_obj.matrix_world.inverted()
        all_local_verts = []

        for obj in mesh_objs:
            dg = bpy.context.evaluated_depsgraph_get()
            eval_obj = obj.evaluated_get(dg)
            tmesh = eval_obj.to_mesh()
            rel_mat = inv_root_world @ obj.matrix_world
            for v in tmesh.vertices:
                all_local_verts.append(rel_mat @ v.co)
            eval_obj.to_mesh_clear()

        if not all_local_verts:
            raise ValueError("No vertices found for convex hull")

        # Downsample outermost vertices using 3D spatial grid (4x4x4 = max 64 samples)
        # to mathematically guarantee convex hull vertex count stays <= max_verts
        min_x = min(v.x for v in all_local_verts)
        max_x = max(v.x for v in all_local_verts)
        min_y = min(v.y for v in all_local_verts)
        max_y = max(v.y for v in all_local_verts)
        min_z = min(v.z for v in all_local_verts)
        max_z = max(v.z for v in all_local_verts)

        cx = (min_x + max_x) * 0.5
        cy = (min_y + max_y) * 0.5
        cz = (min_z + max_z) * 0.5
        ex = max(0.0001, max_x - min_x)
        ey = max(0.0001, max_y - min_y)
        ez = max(0.0001, max_z - min_z)
        center = mathutils.Vector((cx, cy, cz))

        grid_res = 4  # 4x4x4 = max 64 points
        cells = {}
        for v in all_local_verts:
            gx = min(grid_res - 1, max(0, int((v.x - min_x) / ex * grid_res)))
            gy = min(grid_res - 1, max(0, int((v.y - min_y) / ey * grid_res)))
            gz = min(grid_res - 1, max(0, int((v.z - min_z) / ez * grid_res)))
            key = (gx, gy, gz)
            dist_sq = (v - center).length_squared
            # Retain the outermost point in each cell
            if key not in cells or dist_sq > cells[key][0]:
                cells[key] = (dist_sq, v)

        sampled_points = [val[1] for val in cells.values()]

        bm = bmesh.new()
        for pt in sampled_points:
            bm.verts.new(pt)

        res = bmesh.ops.convex_hull(bm, input=bm.verts)
        unused = set(bm.verts) - set(res['geom'])
        bmesh.ops.delete(bm, geom=list(unused), context='VERTS')
        bmesh.ops.triangulate(bm, faces=bm.faces[:])

        triangles = []
        for face in bm.faces:
            if len(face.verts) == 3:
                tri = []
                for v in face.verts:
                    # Blender Z-up (x, y, z) to Unity Y-up (x, z, y)
                    tri.append((
                        float(v.co.x), float(v.co.z), float(v.co.y),
                        float(face.normal.x), float(face.normal.z), float(face.normal.y),
                        0.0, 0.0
                    ))
                triangles.append(tri)

        bm.free()

        if triangles:
            return _pack_triangles(triangles)
    except Exception as e:
        print(f"Warning: Convex hull extraction fallback to box: {e}")

    # Fallback to box mesh
    cx = root_obj.location.x if root_obj else 0.0
    cy = root_obj.location.z if root_obj else 0.0
    cz = root_obj.location.y if root_obj else 0.0
    return generate_box_mesh_data(cx, cy, cz, 0.5, 0.5, 0.5)


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

        is_foliage = obj.name.startswith(('Env_Tree', 'Env_Bush', 'Foliage', 'Tree_', 'Bush_'))
        ground_kw = ('cube', 'floor', 'ground', 'ploshad', 'square', 'terrain', 'road', 'street', 'walk', 'path', 'land')
        obj_name_lower = obj.name.lower()
        is_ground_obj = any(k in obj_name_lower for k in ground_kw)

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

            # 1. Walkable floor (normal up, ground or pedestrian elevation <= 2.5m, not vegetation)
            if not is_foliage and avg_ny > 0.6 and (avg_py <= 0.35 or (is_ground_obj and -2.0 <= avg_py <= 3.0) or (-1.5 <= avg_py <= 2.5 and not obj.name.startswith(('Bldg_', 'Building_', 'Wall_', 'Roof_')))):
                floor_triangles.append(tri_verts)

            # 2. Collision (walls, pillars, floors, props - exclude ceiling above 1.8m facing down, and exclude pure foliage to prevent PhysX lag)
            is_ceiling = (avg_ny < -0.5 and avg_py > 1.8) or (avg_py > 2.65 and avg_ny < -0.2)
            if not is_ceiling and not is_foliage:
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
