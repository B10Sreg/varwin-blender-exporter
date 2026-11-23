#!/usr/bin/env python3
"""
Automated Test Suite for Varwin VWO Exporter:
1. PBR Material Extraction (Alpha, Transmission, Cutout, Opaque)
2. .vwo Object Export (Unity Standard Shader Mode 3 Transparent, keywords, queue 3000)
3. .vwt Scene Export (Scene materials transparent in Unity AssetBundles)
4. Varwin Render Preview (Viewport Shading tray integration, Material Preview, auto-alpha)
"""

import sys
import os
import bpy
import zipfile
import UnityPy

print('=== STARTING TEST SUITE FOR TRANSPARENCY & VARWIN RENDER PREVIEW ===')

# Enable Addon
addon_name = 'varwin_vwo_exporter'
if addon_name not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=addon_name)
print('Addon enabled successfully!')

from varwin_vwo_exporter import mesh_extractor, vwo_builder, ui, properties

# ---------------------------------------------------------
# TEST 1: Material Extraction
# ---------------------------------------------------------
print('\n[TEST 1] Testing Material Property Extraction...')
# 1a. Alpha material
mat_alpha = bpy.data.materials.new('MatAlpha')
mat_alpha.use_nodes = True
bsdf_alpha = mat_alpha.node_tree.nodes.get('Principled BSDF')
bsdf_alpha.inputs['Alpha'].default_value = 0.35
bsdf_alpha.inputs['Base Color'].default_value = (0.2, 0.4, 0.8, 1.0)

p_alpha = mesh_extractor.extract_material_properties(mat_alpha)
assert p_alpha['is_transparent'] == True, f'Expected is_transparent=True, got {p_alpha["is_transparent"]}'
assert abs(p_alpha['alpha'] - 0.35) < 0.001, f'Expected alpha=0.35, got {p_alpha["alpha"]}'
assert abs(p_alpha['color'][3] - 0.35) < 0.001, f'Expected color[3]=0.35, got {p_alpha["color"][3]}'
assert p_alpha['blend_mode'] == 'TRANSPARENT', f'Expected blend_mode=TRANSPARENT, got {p_alpha["blend_mode"]}'
print('  ✓ MatAlpha extracted correctly: is_transparent=True, alpha=0.35')

# 1b. Glass / Transmission material
mat_glass = bpy.data.materials.new('MatGlass')
mat_glass.use_nodes = True
bsdf_glass = mat_glass.node_tree.nodes.get('Principled BSDF')
bsdf_glass.inputs['Transmission Weight'].default_value = 0.95

p_glass = mesh_extractor.extract_material_properties(mat_glass)
assert p_glass['is_transparent'] == True, 'Glass should be transparent'
assert abs(p_glass['transmission'] - 0.95) < 0.001, f'Expected transmission=0.95, got {p_glass["transmission"]}'
assert p_glass['alpha'] < 0.5, f'Glass should have reduced alpha, got {p_glass["alpha"]}'
print('  ✓ MatGlass extracted correctly: is_transparent=True, transmission=0.95, alpha reduced')

# 1c. Transparent Node material
mat_transp = bpy.data.materials.new('MatTranspNode')
mat_transp.use_nodes = True
mat_transp.node_tree.nodes.new('ShaderNodeBsdfTransparent')
p_transp = mesh_extractor.extract_material_properties(mat_transp)
assert p_transp['is_transparent'] == True, 'BSDF_TRANSPARENT should be transparent'
print('  ✓ MatTranspNode extracted correctly: is_transparent=True')

# 1d. Opaque material
mat_opaque = bpy.data.materials.new('MatOpaque')
mat_opaque.use_nodes = True
p_opaque = mesh_extractor.extract_material_properties(mat_opaque)
assert p_opaque['is_transparent'] == False, 'Opaque material should not be transparent'
assert p_opaque['alpha'] == 1.0, f'Expected alpha=1.0, got {p_opaque["alpha"]}'
print('  ✓ MatOpaque extracted correctly: is_transparent=False, alpha=1.0')

# ---------------------------------------------------------
# TEST 2: Object (.vwo) Export with Transparent Material
# ---------------------------------------------------------
print('\n[TEST 2] Testing .vwo Object Export with Transparency...')
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1.0)
cube = bpy.context.active_object
cube.name = 'GlassCube'
mat_cube = bpy.data.materials.new('WindowGlass')
mat_cube.use_nodes = True
bsdf = mat_cube.node_tree.nodes.get('Principled BSDF')
bsdf.inputs['Alpha'].default_value = 0.25
bsdf.inputs['Base Color'].default_value = (0.5, 0.7, 1.0, 1.0)
bsdf.inputs['Metallic'].default_value = 0.1
bsdf.inputs['Roughness'].default_value = 0.05
cube.data.materials.append(mat_cube)

cube.varwin.direct_install_varwin = False
cube.varwin.primary_collider_type = 'BOX'

out_vwo = '/tmp/test_transparent_cube.vwo'
if os.path.exists(out_vwo):
    os.remove(out_vwo)

vwo_builder.build_vwo_package(cube, cube.varwin, out_vwo)
assert os.path.isfile(out_vwo), 'VWO file was not created!'
print(f'  ✓ VWO package built: {os.path.getsize(out_vwo)} bytes')

# Inspect AssetBundle inside .vwo
found_transp_mat = False
with zipfile.ZipFile(out_vwo) as z:
    for b_name in ['bundle', 'linux_bundle']:
        data = z.read(b_name)
        env = UnityPy.load(data)
        for obj in env.objects:
            if obj.type.name == 'Material':
                tree = obj.read_typetree()
                if tree.get('m_Name') == 'WindowGlass':
                    floats = dict(tree.get('m_SavedProperties', {}).get('m_Floats', []))
                    for c in tree.get('m_SavedProperties', {}).get('m_Colors', []):
                        if c[0] == '_Color':
                            assert abs(c[1]['a'] - 0.25) < 0.01, f'Expected _Color.a=0.25, got {c[1]["a"]}'

                    assert floats.get('_Mode') == 3.0, f'Expected _Mode=3.0, got {floats.get("_Mode")}'
                    assert floats.get('_SrcBlend') == 1.0, f'Expected _SrcBlend=1.0, got {floats.get("_SrcBlend")}'
                    assert floats.get('_DstBlend') == 10.0, f'Expected _DstBlend=10.0, got {floats.get("_DstBlend")}'
                    assert floats.get('_ZWrite') == 0.0, f'Expected _ZWrite=0.0, got {floats.get("_ZWrite")}'
                    assert tree.get('m_CustomRenderQueue') == 3000, f'Expected m_CustomRenderQueue=3000, got {tree.get("m_CustomRenderQueue")}'
                    assert tree.get('stringTagMap') == [('RenderType', 'Transparent')], f'Unexpected stringTagMap: {tree.get("stringTagMap")}'
                    assert '_ALPHAPREMULTIPLY_ON' in tree.get('m_ValidKeywords', []), f'Missing _ALPHAPREMULTIPLY_ON in {tree.get("m_ValidKeywords")}'
                    found_transp_mat = True

assert found_transp_mat, 'Transparent material was not found in VWO!'
print('  ✓ TEST 2 PASSED: VWO correctly packages Unity Standard Shader in Mode 3 (Transparent)!')

# ---------------------------------------------------------
# TEST 3: Scene (.vwt) Export with Transparent Material
# ---------------------------------------------------------
print('\n[TEST 3] Testing .vwt Scene Export with Transparency...')
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_plane_add(size=10.0)
floor = bpy.context.active_object
floor.name = 'Floor'

bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 1.0))
glass_wall = bpy.context.active_object
glass_wall.name = 'GlassWall'
mat_wall = bpy.data.materials.new('GlassWallMat')
mat_wall.use_nodes = True
b_wall = mat_wall.node_tree.nodes.get('Principled BSDF')
b_wall.inputs['Alpha'].default_value = 0.20
glass_wall.data.materials.append(mat_wall)

scene = bpy.context.scene
scene.varwin_scene.direct_install_varwin = False
scene.varwin_scene.scene_template_name = 'TransparentScene'

out_vwt = '/tmp/test_transparent_scene.vwt'
if os.path.exists(out_vwt):
    os.remove(out_vwt)

vwo_builder.build_vwt_package(scene, scene.varwin_scene, out_vwt)
assert os.path.isfile(out_vwt), 'VWT file was not created!'
print(f'  ✓ VWT package built: {os.path.getsize(out_vwt)} bytes')

# Inspect AssetBundle inside .vwt
found_scene_transp = False
with zipfile.ZipFile(out_vwt) as z:
    for b_name in ['bundle', 'linux_bundle']:
        data = z.read(b_name)
        env = UnityPy.load(data)
        for obj in env.objects:
            if obj.type.name == 'Material':
                tree = obj.read_typetree()
                if 'GlassWallMat' in tree.get('m_Name', ''):
                    floats = dict(tree.get('m_SavedProperties', {}).get('m_Floats', []))
                    assert floats.get('_Mode') == 3.0, f'Scene mat expected _Mode=3.0, got {floats.get("_Mode")}'
                    assert tree.get('m_CustomRenderQueue') == 3000, f'Scene mat expected queue=3000, got {tree.get("m_CustomRenderQueue")}'
                    assert '_ALPHAPREMULTIPLY_ON' in tree.get('m_ValidKeywords', []), f'Missing _ALPHAPREMULTIPLY_ON in {tree.get("m_ValidKeywords")}'
                    found_scene_transp = True
assert found_scene_transp, 'Transparent material was not found in scene!'
print('  ✓ TEST 3 PASSED: VWT scene materials preserve transparency and Unity Mode 3!')

# ---------------------------------------------------------
# TEST 4: Varwin Render Preview Operator & UI
# ---------------------------------------------------------
print('\n[TEST 4] Testing Varwin Render Preview...')
assert hasattr(bpy.types, 'VIEW3D_PT_shading'), 'VIEW3D_PT_shading missing'
assert hasattr(bpy.types, 'VIEW3D_HT_header'), 'VIEW3D_HT_header missing'

scene = bpy.context.scene
scene.varwin_scene.render_preview_active = False
assert not scene.varwin_scene.render_preview_active

# Add a transparent material to test auto_alpha
test_transp_mat = bpy.data.materials.new('TestAutoAlpha')
test_transp_mat.use_nodes = True
test_transp_mat.node_tree.nodes.get('Principled BSDF').inputs['Alpha'].default_value = 0.5
test_transp_mat.blend_method = 'HASHED'

res = bpy.ops.varwin.toggle_render_preview()
assert res == {'FINISHED'}, f'Operator failed with {res}'
assert scene.varwin_scene.render_preview_active == True, 'Preview should be active'
assert test_transp_mat.blend_method == 'BLEND', f'Expected blend_method=BLEND, got {test_transp_mat.blend_method}'
print('  ✓ Varwin Render Preview activated, transparent material blend_method set to BLEND!')

# Test Preset update
scene.varwin_scene.preview_lighting_preset = 'OUTDOOR'
print('  ✓ Switched preset to OUTDOOR')
scene.varwin_scene.preview_lighting_preset = 'INDOOR'
print('  ✓ Switched preset to INDOOR')

# Test Operator toggle OFF
res_off = bpy.ops.varwin.toggle_render_preview()
assert res_off == {'FINISHED'}, f'Operator toggle off failed with {res_off}'
assert scene.varwin_scene.render_preview_active == False, 'Preview should be inactive'
print('  ✓ Varwin Render Preview deactivated cleanly!')

# ---------------------------------------------------------
# TEST 5: Varwin Standard Material Display Mode & Operations
# ---------------------------------------------------------
print('\n[TEST 5] Testing Varwin Standard Material Enforcement & Preview...')
scene = bpy.context.scene

# 5a. Create a mesh without material and a high-metallic material
bpy.ops.mesh.primitive_cube_add(location=(5, 5, 5))
unmat_cube = bpy.context.active_object
unmat_cube.name = "UnmatCube"
unmat_cube.data.materials.clear()

mat_metal = bpy.data.materials.new("SuperMetallic")
mat_metal.use_nodes = True
bsdf_metal = mat_metal.node_tree.nodes.get('Principled BSDF')
bsdf_metal.inputs['Metallic'].default_value = 1.0

# Activate Varwin Render Preview
res = bpy.ops.varwin.toggle_render_preview()
assert res == {'FINISHED'}
assert scene.varwin_scene.render_preview_active == True

# Check View Transform is set to Standard (Unity sRGB parity)
assert scene.view_settings.view_transform == 'Standard', f"Expected Standard view transform, got {scene.view_settings.view_transform}"
print("  ✓ Color Management view_transform set to Standard (Unity sRGB)")

# Check Metallic was clamped to <= 0.80
assert abs(bsdf_metal.inputs['Metallic'].default_value - 0.80) < 0.001, f"Expected Metallic <= 0.80, got {bsdf_metal.inputs['Metallic'].default_value}"
print("  ✓ Metallic automatically clamped to 0.80 in Varwin preview mode")

# Check unassigned mesh received Varwin_Default_Standard_MAT
assert len(unmat_cube.data.materials) > 0, "UnmatCube should have received a default material"
assert unmat_cube.data.materials[0].name == "Varwin_Default_Standard_MAT"
print("  ✓ Untextured mesh received Varwin_Default_Standard_MAT")

# 5b. Test preview_material_mode switching
scene.varwin_scene.preview_material_mode = 'DEFAULT_CLAY'
assert bpy.context.view_layer.material_override is not None
assert bpy.context.view_layer.material_override.name == "Varwin_Default_Standard_MAT"
print("  ✓ preview_material_mode = 'DEFAULT_CLAY' activates material_override")

scene.varwin_scene.preview_material_mode = 'STANDARD_PBR'
assert bpy.context.view_layer.material_override is None
print("  ✓ preview_material_mode = 'STANDARD_PBR' clears material_override")

# 5c. Test varwin.new_standard_material operator
res_new_mat = bpy.ops.varwin.new_standard_material(material_name="CustomVarwinMat")
assert res_new_mat == {'FINISHED'}
new_mat = bpy.data.materials.get("CustomVarwinMat")
assert new_mat is not None
assert new_mat.get("varwin_standard_shader") == "Varwin/Standard"
print("  ✓ varwin.new_standard_material created new Varwin/Standard material")

# 5d. Test varwin.convert_to_standard_material operator
res_conv = bpy.ops.varwin.convert_to_standard_material()
assert res_conv == {'FINISHED'}
print("  ✓ varwin.convert_to_standard_material ran successfully")

# 5e. Toggle preview OFF
res_off = bpy.ops.varwin.toggle_render_preview()
assert res_off == {'FINISHED'}
assert scene.varwin_scene.render_preview_active == False
assert bpy.context.view_layer.material_override is None
print("  ✓ Varwin Render Preview deactivated and restored original settings cleanly")

print('\n=== ALL 5 TEST SUITES PASSED WITH 100% SUCCESS! ===')
