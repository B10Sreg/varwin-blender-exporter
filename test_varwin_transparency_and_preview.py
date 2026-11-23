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

from varwin_vwo_exporter import mesh_extractor, vwo_builder, ui, properties, varwin_preview

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
print('\n[TEST 4] Testing Varwin 1:1 Render Preview...')
assert hasattr(bpy.types, 'VIEW3D_PT_shading'), 'VIEW3D_PT_shading missing'
assert hasattr(bpy.types, 'VIEW3D_HT_header'), 'VIEW3D_HT_header missing'

bpy.ops.wm.read_homefile(use_empty=True)
scene = bpy.context.scene
scene.varwin_scene.render_preview_active = False
assert not scene.varwin_scene.render_preview_active

# Attach transparent material to a scene mesh so non-destructive proxy is compiled
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 1))
alpha_obj = bpy.context.active_object
alpha_obj.name = 'AlphaProxyCube'
test_transp_mat = bpy.data.materials.new('TestAutoAlpha')
if not test_transp_mat.node_tree:
    test_transp_mat.use_nodes = True
test_transp_mat.node_tree.nodes.get('Principled BSDF').inputs['Alpha'].default_value = 0.5
test_transp_mat.blend_method = 'HASHED'
alpha_obj.data.materials.append(test_transp_mat)

res = bpy.ops.varwin.toggle_render_preview()
assert res == {'FINISHED'}, f'Operator failed with {res}'
assert scene.varwin_scene.render_preview_active == True, 'Preview should be active'

active_mat = alpha_obj.data.materials[0]
assert active_mat is not None and active_mat.get('varwin_preview_proxy') == True, 'Expected non-destructive proxy material on mesh'
assert active_mat.blend_method == 'BLEND', f'Expected proxy blend_method=BLEND, got {active_mat.blend_method}'
assert active_mat.use_backface_culling == True, 'Expected Cull Back (use_backface_culling=True) on proxy'
print('  ✓ Varwin 1:1 Render Preview activated with non-destructive BLEND + Cull Back proxy!')

# Test Preset update
scene.varwin_scene.preview_lighting_preset = 'OUTDOOR'
print('  ✓ Switched preset to OUTDOOR')
scene.varwin_scene.preview_lighting_preset = 'INDOOR'
print('  ✓ Switched preset to INDOOR')
scene.varwin_scene.preview_lighting_preset = 'UNITY_SKYBOX'
print('  ✓ Switched preset to UNITY_SKYBOX')

# Test Operator toggle OFF & verify original material untouched
res_off = bpy.ops.varwin.toggle_render_preview()
assert res_off == {'FINISHED'}, f'Operator toggle off failed with {res_off}'
assert scene.varwin_scene.render_preview_active == False, 'Preview should be inactive'
assert alpha_obj.data.materials[0] == test_transp_mat, 'Original material should be restored'
assert test_transp_mat.blend_method == 'HASHED', 'Original material blend_method must remain untouched!'
assert bpy.data.materials.get('__VarwinPreview__TestAutoAlpha') is None, 'Temporary proxy should be deleted'
print('  ✓ Varwin Render Preview deactivated cleanly and restored original material untouched!')

# ---------------------------------------------------------
# TEST 5: Varwin Standard Material Display Mode & Operations
# ---------------------------------------------------------
print('\n[TEST 5] Testing Varwin Standard Material Enforcement & Non-Destructive Preview...')
scene = bpy.context.scene

# 5a. Create a mesh without material and a mesh with high-metallic material
bpy.ops.mesh.primitive_cube_add(location=(5, 5, 5))
unmat_cube = bpy.context.active_object
unmat_cube.name = "UnmatCube"
unmat_cube.data.materials.clear()

bpy.ops.mesh.primitive_cube_add(location=(2, 2, 2))
metal_cube = bpy.context.active_object
metal_cube.name = "MetalCube"
mat_metal = bpy.data.materials.new("SuperMetallic")
if not mat_metal.node_tree:
    mat_metal.use_nodes = True
bsdf_metal = mat_metal.node_tree.nodes.get('Principled BSDF')
bsdf_metal.inputs['Metallic'].default_value = 1.0
metal_cube.data.materials.append(mat_metal)

# Activate Varwin Render Preview
res = bpy.ops.varwin.toggle_render_preview()
assert res == {'FINISHED'}
assert scene.varwin_scene.render_preview_active == True

# Check View Transform is set to Standard (Unity sRGB parity)
assert scene.view_settings.view_transform == 'Standard', f"Expected Standard view transform, got {scene.view_settings.view_transform}"
print("  ✓ Color Management view_transform set to Standard (Unity sRGB)")

# Check Metallic was clamped to <= 0.80 on proxy while original remains 1.0
metal_proxy = metal_cube.data.materials[0]
assert metal_proxy.get('varwin_preview_proxy') == True
proxy_bsdf = next(n for n in metal_proxy.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
assert abs(proxy_bsdf.inputs['Metallic'].default_value - 0.80) < 0.001, f"Expected proxy Metallic <= 0.80, got {proxy_bsdf.inputs['Metallic'].default_value}"
assert abs(bsdf_metal.inputs['Metallic'].default_value - 1.0) < 0.001, "Original Metallic must remain untouched (1.0)!"
assert metal_proxy.use_backface_culling == True
print("  ✓ Proxy Metallic clamped to 0.80 & Cull Back enabled non-destructively (original preserved at 1.0)")

# Check unassigned mesh received Varwin_Default_Standard_MAT during preview
assert len(unmat_cube.data.materials) > 0, "UnmatCube should have received a default material"
assert unmat_cube.data.materials[0].name == "Varwin_Default_Standard_MAT"
print("  ✓ Untextured mesh received Varwin_Default_Standard_MAT during preview")

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

# 5e. Toggle preview OFF and verify UnmatCube & MetalCube restore
res_off = bpy.ops.varwin.toggle_render_preview()
assert res_off == {'FINISHED'}
assert scene.varwin_scene.render_preview_active == False
assert bpy.context.view_layer.material_override is None
assert len(unmat_cube.data.materials) == 0, "UnmatCube should restore empty material slots"
assert metal_cube.data.materials[0] == mat_metal
print("  ✓ Varwin Render Preview deactivated and restored original slots cleanly")

# ---------------------------------------------------------
# TEST 6: 100% Unity Varwin Render Rig (Sun, Shadows, EEVEE Floor, LightPath)
# ---------------------------------------------------------
print('\n[TEST 6] Testing 100% Unity Varwin Render Rig (Sun angle, EEVEE Shadow Floor, Unity Forward)...')
scene = bpy.context.scene

# 6a. Activate Varwin Render Preview in FULL_UNITY mode
scene.varwin_scene.preview_render_mode = 'FULL_UNITY'
scene.varwin_scene.preview_use_ssao = False
res_rig = bpy.ops.varwin.toggle_render_preview()
assert res_rig == {'FINISHED'}
assert scene.varwin_scene.render_preview_active == True

# Check Render Engine is EEVEE and raytracing is OFF (Unity Forward RP parity)
assert 'EEVEE' in scene.render.engine, f"Expected EEVEE engine, got {scene.render.engine}"
if hasattr(scene.eevee, 'use_raytracing'):
    assert scene.eevee.use_raytracing == False, "EEVEE raytracing should be OFF for Unity Forward parity"
print("  ✓ Render Engine switched to EEVEE (Unity Forward mode, no Cycles-style raytrace noise)")

# Check Rig Collection exists
rig_col = bpy.data.collections.get("Varwin_Render_Preview_Rig")
assert rig_col is not None, "Varwin_Render_Preview_Rig collection not found!"
print("  ✓ Varwin_Render_Preview_Rig collection active in scene")

# Check Varwin Directional Sun Light
sun = rig_col.objects.get("Varwin_Preview_Sun")
assert sun is not None, "Varwin_Preview_Sun not found in rig!"
assert sun.data.type == 'SUN', f"Expected SUN light, got {sun.data.type}"
assert sun.data.energy == scene.varwin_scene.preview_sun_intensity
assert sun.get("varwin_preview_rig") == True
print(f"  ✓ Varwin Directional Sun created (energy={sun.data.energy}, angle={sun.data.angle:.4f} rad)")

# Check EEVEE Transparent Shadow Catcher Ground Floor
floor = rig_col.objects.get("Varwin_Preview_Floor")
assert floor is not None, "Varwin_Preview_Floor not found in rig!"
assert floor.get("varwin_preview_rig") == True
assert len(floor.data.materials) > 0 and floor.data.materials[0].name == "Varwin_Preview_Floor_MAT"
floor_mat_nodes = [n.type for n in floor.data.materials[0].node_tree.nodes]
assert 'SHADERTORGB' in floor_mat_nodes, f"EEVEE floor must use ShaderNodeShaderToRGB, got {floor_mat_nodes}"
if hasattr(floor, 'visible_shadow'):
    assert floor.visible_shadow == False, "Floor should not cast shadow onto itself"
print(f"  ✓ EEVEE Transparent Shadow Catcher Floor created (location.z={floor.location.z:.3f})")

# 6b. Test dynamic parameter updates including real Sun angle
scene.varwin_scene.preview_sun_intensity = 3.5
assert sun.data.energy == 3.5, "Sun intensity did not update dynamically!"
angle_before = sun.data.angle
scene.varwin_scene.preview_shadow_softness = 0.65
assert sun.data.angle > angle_before, f"Sun angle should increase with softness: {angle_before} -> {sun.data.angle}"
print("  ✓ Sun intensity & angular shadow softness updated dynamically")

scene.varwin_scene.preview_show_floor = False
assert floor.hide_viewport == True, "Floor visibility did not update!"
scene.varwin_scene.preview_show_floor = True
assert floor.hide_viewport == False, "Floor visibility did not restore!"
print("  ✓ Floor visibility dynamically toggled")

# 6c. Verify Exporter completely ignores preview rig objects
from varwin_vwo_exporter.mesh_extractor import is_collider_object, is_preview_rig_object
assert is_preview_rig_object(sun) == True, "Sun should be identified as preview rig object"
assert is_preview_rig_object(floor) == True, "Floor should be identified as preview rig object"
assert is_collider_object(floor) == True, "Floor should be excluded from collider generation"
print("  ✓ Exporter security check: Preview rig objects safely excluded from export")

# 6d. Toggle OFF and verify complete cleanup
res_clean = bpy.ops.varwin.toggle_render_preview()
assert res_clean == {'FINISHED'}
assert scene.varwin_scene.render_preview_active == False
assert bpy.data.collections.get("Varwin_Render_Preview_Rig") is None, "Rig collection should be deleted!"
assert bpy.data.objects.get("Varwin_Preview_Sun") is None, "Sun object should be deleted!"
assert bpy.data.objects.get("Varwin_Preview_Floor") is None, "Floor object should be deleted!"
print("  ✓ Varwin Render Rig cleaned up with 0 scene pollution!")

# ---------------------------------------------------------
# TEST 7: 1:1 WYSIWYG Parity Diagnostics, LightPath World, Colliders & Export Safety
# ---------------------------------------------------------
print('\n[TEST 7] Testing 1:1 WYSIWYG Parity, Diagnostics, Colliders & Export While Preview Active...')
bpy.ops.wm.read_homefile(use_empty=True)
scene = bpy.context.scene

# 7a. Create procedural unbaked material + glass material + collider
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.5))
proc_cube = bpy.context.active_object
proc_cube.name = "ProcCube"
mat_proc = bpy.data.materials.new("ProceduralBrick")
if not mat_proc.node_tree:
    mat_proc.use_nodes = True
nt_p = mat_proc.node_tree
bsdf_p = nt_p.nodes.get("Principled BSDF")
noise_n = nt_p.nodes.new("ShaderNodeTexNoise")
nt_p.links.new(noise_n.outputs["Color"], bsdf_p.inputs["Base Color"])
bsdf_p.inputs["Metallic"].default_value = 0.95
proc_cube.data.materials.append(mat_proc)

bpy.ops.mesh.primitive_cube_add(size=1.0, location=(2, 0, 0.5))
glass_cube = bpy.context.active_object
glass_cube.name = "PreviewGlassCube"
mat_g = bpy.data.materials.new("RealGlass")
if not mat_g.node_tree:
    mat_g.use_nodes = True
bsdf_g = mat_g.node_tree.nodes.get("Principled BSDF")
bsdf_g.inputs["Transmission Weight"].default_value = 0.95
glass_cube.data.materials.append(mat_g)

bpy.ops.mesh.primitive_cube_add(size=1.2, location=(0, 0, 0.5))
col_box = bpy.context.active_object
col_box.name = "Col_TestBox"
col_box["varwin_collider"] = True
col_box.hide_viewport = False

# Activate 1:1 Preview
scene.varwin_scene.preview_hide_colliders = True
res7 = bpy.ops.varwin.toggle_render_preview()
assert res7 == {'FINISHED'}

# Check Diagnostics
diag = varwin_preview.get_preview_diagnostics()
assert "ProceduralBrick" in diag["unbaked_procedural"], f"Expected ProceduralBrick in diagnostics, got {diag}"
assert "ProceduralBrick" in diag["clamped_metallic"], f"Expected ProceduralBrick in clamped_metallic, got {diag}"
assert "RealGlass" in diag["transmission_to_alpha"], f"Expected RealGlass in transmission_to_alpha, got {diag}"
print("  ✓ Diagnostics accurately reported unbaked procedural, clamped metallic & glass conversion")

# Check procedural proxy has NO TEX_NOISE (flat color like Unity export)
proc_proxy = proc_cube.data.materials[0]
assert proc_proxy.get("varwin_preview_proxy") == True
assert not any(n.type == "TEX_NOISE" for n in proc_proxy.node_tree.nodes), "Proxy should NOT include unbaked Noise node!"

# Check glass proxy has Transmission=0 and BLEND
glass_proxy = glass_cube.data.materials[0]
glass_proxy_bsdf = next(n for n in glass_proxy.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
assert glass_proxy_bsdf.inputs["Transmission Weight"].default_value == 0.0
assert glass_proxy.blend_method == "BLEND"
print("  ✓ Procedural & Glass proxies match Unity export 1:1")

# Check LightPath world
world_nodes = [n.type for n in scene.world.node_tree.nodes]
assert "LIGHT_PATH" in world_nodes, f"Expected ShaderNodeLightPath in Varwin_Preview_World, got {world_nodes}"
print("  ✓ Varwin_Preview_World separates Skybox & Ambient via ShaderNodeLightPath")

# Check collider hidden during preview
assert col_box.hide_viewport == True, "Collider should be hidden during 1:1 preview"

# Check .vwo export WHILE preview is active exports original material names!
out_vwo_active = '/tmp/test_preview_active_export.vwo'
if os.path.exists(out_vwo_active):
    os.remove(out_vwo_active)
proc_cube.varwin.direct_install_varwin = False
proc_cube.varwin.primary_collider_type = 'BOX'
vwo_builder.build_vwo_package(proc_cube, proc_cube.varwin, out_vwo_active)
assert os.path.isfile(out_vwo_active)
exported_mat_names = []
with zipfile.ZipFile(out_vwo_active) as z:
    env = UnityPy.load(z.read('bundle'))
    for o in env.objects:
        if o.type.name == 'Material':
            exported_mat_names.append(o.read_typetree().get('m_Name', ''))
assert 'ProceduralBrick' in exported_mat_names, f"Expected original material name in export, got {exported_mat_names}"
assert not any('__VarwinPreview__' in n for n in exported_mat_names), f"Proxy name leaked into export: {exported_mat_names}"
print("  ✓ Export while 1:1 preview is active cleanly resolves original materials!")

# Turn preview OFF and verify collider restored
res7_off = bpy.ops.varwin.toggle_render_preview()
assert res7_off == {'FINISHED'}
assert col_box.hide_viewport == False, "Collider visibility should restore when preview ends"
print("  ✓ Collider visibility restored on preview exit")

print('\n=== ALL 7 TEST SUITES PASSED WITH 100% SUCCESS! ===')
