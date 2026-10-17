import bpy
import os
import time

def ensure_object_uv(obj):
    """Checks if obj has UV layers. If not, creates Smart UV Project."""
    if not obj or obj.type != 'MESH':
        return False
    
    mesh = obj.data
    if not mesh.uv_layers:
        orig_active = bpy.context.view_layer.objects.active
        orig_mode = bpy.context.mode
        try:
            bpy.context.view_layer.objects.active = obj
            if orig_mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception as e:
            print(f"Warning: Failed to generate Smart UV for '{obj.name}': {e}")
            return False
        finally:
            if orig_active:
                bpy.context.view_layer.objects.active = orig_active
    return bool(mesh.uv_layers)


def bake_object_texture(obj, output_dir=None, resolution=2048, bake_type='DIFFUSE', auto_apply=True):
    """
    Bakes active object's material node tree into a Texture image file (PNG).
    
    Args:
        obj: bpy.types.Object of type MESH
        output_dir: directory path to save PNG. Defaults to //textures or ~/Desktop
        resolution: int (1024, 2048, 4096)
        bake_type: 'DIFFUSE' (Base Color), 'ROUGHNESS', 'COMBINED', 'NORMAL'
        auto_apply: bool, if True, automatically links the baked texture to the Principled BSDF
    
    Returns:
        dict: {
            'success': bool,
            'filepath': str,
            'image_name': str,
            'error': str
        }
    """
    if not obj or obj.type != 'MESH':
        return {'success': False, 'error': 'Объект не выбран или не является полигональным мешем (Mesh)!'}
    
    if not obj.data.materials or not any(obj.data.materials):
        return {'success': False, 'error': f"Объект '{obj.name}' не содержит материалов для запекания!"}
    
    # 1. Ensure UVs exist
    if not ensure_object_uv(obj):
        return {'success': False, 'error': f"У объекта '{obj.name}' отсутствует UV-развертка и не удалось её создать!"}
    
    # 2. Determine target save directory
    if not output_dir or not os.path.isdir(output_dir):
        if bpy.data.is_saved:
            output_dir = bpy.path.abspath("//textures")
        else:
            home = os.path.expanduser("~")
            desktop = os.path.join(home, "Desktop")
            output_dir = desktop if os.path.isdir(desktop) else home
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Clean file name
    safe_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in obj.name)
    suffix = "BaseColor" if bake_type == 'DIFFUSE' else bake_type.capitalize()
    img_filename = f"{safe_name}_{suffix}_{int(time.time())}.png"
    target_filepath = os.path.join(output_dir, img_filename)
    
    # Save current render settings
    scene = bpy.context.scene
    orig_engine = scene.render.engine
    orig_device = getattr(scene.cycles, 'device', 'CPU') if hasattr(scene, 'cycles') else 'CPU'
    orig_samples = getattr(scene.cycles, 'bake_samples', 64) if hasattr(scene, 'cycles') else 64
    
    created_images = []
    temp_nodes = []
    
    try:
        # Switch engine to Cycles for baking
        scene.render.engine = 'CYCLES'
        if hasattr(scene, 'cycles'):
            scene.cycles.bake_samples = 16  # Fast clean bake for procedural textures
        
        # Create image container in Blender
        bake_img = bpy.data.images.new(
            name=f"Baked_{safe_name}_{suffix}",
            width=resolution,
            height=resolution,
            alpha=True,
            float_buffer=False
        )
        created_images.append(bake_img)
        
        # Inject temporary Image Texture nodes into all materials of obj
        materials_to_bake = [m for m in obj.data.materials if m and m.use_nodes and m.node_tree]
        if not materials_to_bake:
            # Material without nodes -> enable nodes
            for m in obj.data.materials:
                if m and not m.use_nodes:
                    m.use_nodes = True
                    materials_to_bake.append(m)
        
        for mat in materials_to_bake:
            nodes = mat.node_tree.nodes
            t_node = nodes.new('ShaderNodeTexImage')
            t_node.name = "__VARWIN_BAKE_TARGET__"
            t_node.image = bake_img
            # Important: make node active so Cycles bakes into it!
            nodes.active = t_node
            t_node.select = True
            temp_nodes.append((mat, t_node))
        
        # Select target object as active
        orig_active = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        
        # Execute bake
        if bake_type == 'DIFFUSE':
            bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'})
        elif bake_type == 'ROUGHNESS':
            bpy.ops.object.bake(type='ROUGHNESS')
        elif bake_type == 'NORMAL':
            bpy.ops.object.bake(type='NORMAL')
        elif bake_type == 'COMBINED':
            bpy.ops.object.bake(type='COMBINED')
        else:
            bpy.ops.object.bake(type=bake_type)
        
        # Save baked image to file
        bake_img.filepath_raw = target_filepath
        bake_img.file_format = 'PNG'
        bake_img.save()
        
        # If auto_apply requested: connect baked texture to Principled BSDF
        if auto_apply:
            for mat, t_node in temp_nodes:
                nodes = mat.node_tree.nodes
                links = mat.node_tree.links
                bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
                if bsdf:
                    if bake_type == 'DIFFUSE':
                        links.new(t_node.outputs['Color'], bsdf.inputs['Base Color'])
                    elif bake_type == 'ROUGHNESS' and 'Roughness' in bsdf.inputs:
                        links.new(t_node.outputs['Color'], bsdf.inputs['Roughness'])
                    elif bake_type == 'NORMAL' and 'Normal' in bsdf.inputs:
                        norm_node = nodes.new('ShaderNodeNormalMap')
                        links.new(t_node.outputs['Color'], norm_node.inputs['Color'])
                        links.new(norm_node.outputs['Normal'], bsdf.inputs['Normal'])
                    t_node.name = f"Varwin_Baked_{suffix}"
                else:
                    t_node.name = f"Varwin_Baked_{suffix}"
            # Cleared temp nodes list so we don't delete them
            temp_nodes.clear()
        
        return {
            'success': True,
            'filepath': target_filepath,
            'image_name': bake_img.name,
            'error': None
        }
        
    except Exception as e:
        return {'success': False, 'error': f"Ошибка при запекании текстуры: {str(e)}"}
        
    finally:
        # Cleanup temporary nodes if bake failed or auto_apply is False
        for mat, t_node in temp_nodes:
            try:
                if t_node.name in mat.node_tree.nodes:
                    mat.node_tree.nodes.remove(t_node)
            except Exception:
                pass
        
        # Restore scene settings
        scene.render.engine = orig_engine
        if hasattr(scene, 'cycles'):
            scene.cycles.device = orig_device
            scene.cycles.bake_samples = orig_samples
        if orig_active:
            bpy.context.view_layer.objects.active = orig_active
