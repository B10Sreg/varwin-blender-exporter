"""
Varwin 1:1 WYSIWYG Viewport Render Preview Engine (Unity Built-in Forward RP Parity).

Compiles non-destructive proxy materials that match `mesh_extractor.py` and `vwo_builder.py`
exactly, configures Blender EEVEE to match Unity Built-in Forward lighting (Standard sRGB,
LightPath Skybox/Ambient separation, real Sun angular shadow softness, transparent EEVEE
shadow catcher floor, Backface Culling, and automatic collider/light hiding).
"""

import math
import bpy
import bmesh
import mathutils

from .mesh_extractor import (
    extract_material_properties,
    find_image_texture_node,
    is_collider_object,
    is_preview_rig_object,
)


_preview_state = {
    "viewport_states": {},
    "obj_materials": {},
    "scene_lights": {},
    "hidden_colliders": {},
    "hidden_collider_cols": {},
    "diagnostics": {
        "total_materials": 0,
        "unbaked_procedural": [],
        "dropped_normal": [],
        "dropped_roughness": [],
        "clamped_metallic": [],
        "transmission_to_alpha": [],
    },
}


def get_preview_diagnostics():
    """Returns a copy of the latest 1:1 material compatibility diagnostics."""
    diag = _preview_state.get("diagnostics", {})
    return {
        "total_materials": diag.get("total_materials", 0),
        "unbaked_procedural": list(diag.get("unbaked_procedural", [])),
        "dropped_normal": list(diag.get("dropped_normal", [])),
        "dropped_roughness": list(diag.get("dropped_roughness", [])),
        "clamped_metallic": list(diag.get("clamped_metallic", [])),
        "transmission_to_alpha": list(diag.get("transmission_to_alpha", [])),
    }


def _ensure_node_tree(datablock):
    if not datablock:
        return None
    if not getattr(datablock, "node_tree", None):
        try:
            datablock.use_nodes = True
        except Exception:
            pass
    return getattr(datablock, "node_tree", None)


def _get_eevee_engine_id(scene):
    try:
        items = [it.identifier for it in scene.render.bl_rna.properties["engine"].enum_items]
        if "BLENDER_EEVEE" in items:
            return "BLENDER_EEVEE"
        if "BLENDER_EEVEE_NEXT" in items:
            return "BLENDER_EEVEE_NEXT"
    except Exception:
        pass
    return "BLENDER_EEVEE"


def get_or_create_varwin_default_material(backface_culling=True):
    """Returns or creates the official Varwin Constructor default material (Constructor_Def_MAT)."""
    mat_name = "Varwin_Default_Standard_MAT"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(mat_name)
    nt = _ensure_node_tree(mat)
    if nt:
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.5
            bsdf.inputs["Metallic"].default_value = 0.0
    mat.use_backface_culling = bool(backface_culling)
    mat["varwin_standard_shader"] = "Varwin/Standard"
    mat["varwin_default_constructor"] = True
    return mat


def _find_mix_sockets(mix_node):
    """Safely resolves Factor, A, B, and Result sockets on ShaderNodeMix across Blender 4.x/5.x."""
    fac_in = mix_node.inputs.get("Factor") or mix_node.inputs[0]
    a_in = None
    b_in = None
    res_out = None
    for s in mix_node.inputs:
        if s.type == "RGBA" and s.name in ("A", "Color1"):
            a_in = s
        elif s.type == "RGBA" and s.name in ("B", "Color2"):
            b_in = s
    if a_in is None and len(mix_node.inputs) > 6:
        a_in = mix_node.inputs[6]
    if b_in is None and len(mix_node.inputs) > 7:
        b_in = mix_node.inputs[7]
    for s in mix_node.outputs:
        if s.type == "RGBA" and s.name in ("Result", "Color"):
            res_out = s
            break
    if res_out is None and len(mix_node.outputs) > 2:
        res_out = mix_node.outputs[2]
    return fac_in, a_in, b_in, res_out


def _analyze_original_material(orig_mat):
    """Inspects original material nodes for 1:1 Varwin export compatibility warnings & image ref."""
    info = {
        "image": None,
        "unbaked_procedural": False,
        "dropped_normal": False,
        "dropped_roughness": False,
        "clamped_metallic": False,
        "transmission_to_alpha": False,
    }
    if not orig_mat or not getattr(orig_mat, "node_tree", None):
        return info

    bsdf = next((n for n in orig_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if not bsdf:
        return info

    bc_in = bsdf.inputs.get("Base Color")
    if bc_in and bc_in.is_linked:
        tex_node = find_image_texture_node(bc_in)
        if tex_node and getattr(tex_node, "image", None):
            info["image"] = tex_node.image
        else:
            info["unbaked_procedural"] = True

    norm_in = bsdf.inputs.get("Normal")
    if norm_in and norm_in.is_linked:
        info["dropped_normal"] = True

    rough_in = bsdf.inputs.get("Roughness")
    if rough_in and rough_in.is_linked:
        info["dropped_roughness"] = True

    met_in = bsdf.inputs.get("Metallic")
    if met_in and not met_in.is_linked and float(met_in.default_value) > 0.801:
        info["clamped_metallic"] = True

    trans_in = bsdf.inputs.get("Transmission Weight", bsdf.inputs.get("Transmission"))
    if trans_in:
        if trans_in.is_linked or float(trans_in.default_value) > 0.01:
            info["transmission_to_alpha"] = True

    return info


def build_varwin_proxy_material(
    orig_mat,
    clamp_metallic=True,
    backface_culling=True,
    auto_alpha=True,
):
    """
    Creates or updates a non-destructive `__VarwinPreview__<name>` material that mirrors
    what Unity/Varwin Standard Shader actually renders from `extract_material_properties`.
    """
    if not orig_mat:
        return get_or_create_varwin_default_material(backface_culling=backface_culling), {}

    if orig_mat.get("varwin_preview_proxy"):
        orig_name = orig_mat.get("varwin_orig_material", "")
        real = bpy.data.materials.get(orig_name)
        if real and not real.get("varwin_preview_proxy"):
            orig_mat = real
        else:
            return orig_mat, {}

    props = extract_material_properties(orig_mat)
    analysis = _analyze_original_material(orig_mat)

    proxy_name = f"__VarwinPreview__{orig_mat.name}"
    proxy = bpy.data.materials.get(proxy_name)
    if not proxy:
        proxy = bpy.data.materials.new(proxy_name)

    proxy["varwin_preview_proxy"] = True
    proxy["varwin_orig_material"] = orig_mat.name
    proxy["varwin_standard_shader"] = "Varwin/Standard"
    proxy.use_backface_culling = bool(backface_culling)

    nt = _ensure_node_tree(proxy)
    nt.nodes.clear()

    out_node = nt.nodes.new("ShaderNodeOutputMaterial")
    out_node.location = (420, 0)

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (120, 0)
    nt.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])

    col = props["color"]
    tint_rgba = (float(col[0]), float(col[1]), float(col[2]), 1.0)
    alpha_scalar = float(col[3]) if len(col) > 3 else 1.0

    img = analysis["image"]
    tex_node = None
    if img is not None:
        tex_node = nt.nodes.new("ShaderNodeTexImage")
        tex_node.location = (-360, 140)
        tex_node.image = img

        # Unity Standard Shader evaluates Base Color as (_MainTex * _Color)
        mix_col = nt.nodes.new("ShaderNodeMix")
        mix_col.data_type = "RGBA"
        mix_col.blend_type = "MULTIPLY"
        mix_col.location = (-120, 140)
        fac_in, a_in, b_in, res_out = _find_mix_sockets(mix_col)
        fac_in.default_value = 1.0
        b_in.default_value = tint_rgba
        nt.links.new(tex_node.outputs["Color"], a_in)
        nt.links.new(res_out, bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = tint_rgba

    # Metallic: extract_material_properties clamps to 0.80; allow toggling clamp_metallic for inspection
    raw_metallic = props["metallic"]
    if not clamp_metallic and orig_mat.node_tree:
        orig_bsdf = next((n for n in orig_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if orig_bsdf and "Metallic" in orig_bsdf.inputs and not orig_bsdf.inputs["Metallic"].is_linked:
            raw_metallic = max(0.0, min(1.0, float(orig_bsdf.inputs["Metallic"].default_value)))
    bsdf.inputs["Metallic"].default_value = min(raw_metallic, 0.80) if clamp_metallic else raw_metallic

    # Roughness from scalar Glossiness (Unity _Glossiness = 1.0 - roughness)
    bsdf.inputs["Roughness"].default_value = max(0.04, min(1.0, 1.0 - float(props["glossiness"])))

    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = 1.5
    spec_in = bsdf.inputs.get("Specular IOR Level", bsdf.inputs.get("Specular"))
    if spec_in:
        spec_in.default_value = 0.5
    for zero_sock in ("Coat Weight", "Sheen Weight", "Subsurface Weight", "Transmission Weight", "Transmission"):
        if zero_sock in bsdf.inputs:
            bsdf.inputs[zero_sock].default_value = 0.0

    # Emission matching Unity _EmissionEnabled / _EmissionColor
    ecol = props["emission"]
    if max(ecol[0], ecol[1], ecol[2]) > 0.01:
        em_in = bsdf.inputs.get("Emission Color", bsdf.inputs.get("Emission"))
        if em_in:
            em_in.default_value = (float(ecol[0]), float(ecol[1]), float(ecol[2]), 1.0)
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 1.0
    else:
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 0.0

    # Transparency matching Unity Mode 0 (Opaque), Mode 1 (Cutout), Mode 3 (Transparent)
    has_tex_alpha = bool(props.get("texture") and props["texture"].get("has_alpha") and tex_node is not None)
    if auto_alpha and props.get("is_transparent", False):
        if has_tex_alpha:
            mul_a = nt.nodes.new("ShaderNodeMath")
            mul_a.operation = "MULTIPLY"
            mul_a.location = (-120, -140)
            mul_a.inputs[1].default_value = alpha_scalar
            nt.links.new(tex_node.outputs["Alpha"], mul_a.inputs[0])
            alpha_socket = mul_a.outputs["Value"]
        else:
            alpha_socket = None

        if props.get("blend_mode") == "CUTOUT":
            if alpha_socket is not None:
                gt = nt.nodes.new("ShaderNodeMath")
                gt.operation = "GREATER_THAN"
                gt.location = (0, -140)
                gt.inputs[1].default_value = 0.5
                nt.links.new(alpha_socket, gt.inputs[0])
                nt.links.new(gt.outputs["Value"], bsdf.inputs["Alpha"])
            else:
                bsdf.inputs["Alpha"].default_value = 1.0 if alpha_scalar >= 0.5 else 0.0

            if hasattr(proxy, "surface_render_method"):
                proxy.surface_render_method = "DITHERED"
            if hasattr(proxy, "blend_method"):
                try:
                    proxy.blend_method = "CLIP"
                except Exception:
                    pass
            if hasattr(proxy, "alpha_threshold"):
                proxy.alpha_threshold = 0.5
        else:
            if alpha_socket is not None:
                nt.links.new(alpha_socket, bsdf.inputs["Alpha"])
            else:
                bsdf.inputs["Alpha"].default_value = max(0.0, min(1.0, alpha_scalar))

            if hasattr(proxy, "surface_render_method"):
                proxy.surface_render_method = "BLENDED"
            if hasattr(proxy, "blend_method"):
                proxy.blend_method = "BLEND"
            if hasattr(proxy, "use_transparent_shadow"):
                proxy.use_transparent_shadow = True
            if hasattr(proxy, "show_transparent_back"):
                proxy.show_transparent_back = False
            if hasattr(proxy, "use_raytrace_refraction"):
                proxy.use_raytrace_refraction = False
    else:
        bsdf.inputs["Alpha"].default_value = 1.0
        if hasattr(proxy, "surface_render_method"):
            proxy.surface_render_method = "DITHERED"
        if hasattr(proxy, "blend_method"):
            proxy.blend_method = "OPAQUE"

    return proxy, analysis


def _resolve_real_material(mat):
    if not mat:
        return None
    if mat.get("varwin_preview_proxy"):
        orig_name = mat.get("varwin_orig_material", "")
        return bpy.data.materials.get(orig_name)
    return mat


def apply_preview_proxies(context, scene, vws):
    """
    Rebuilds and applies 1:1 Varwin proxy materials non-destructively while updating
    compatibility diagnostics for the scene.
    """
    if not scene:
        return

    strict_parity = bool(getattr(vws, "preview_strict_parity", True))
    clamp_metallic = bool(getattr(vws, "preview_clamp_metallic", True))
    backface_culling = bool(getattr(vws, "preview_backface_culling", True))
    auto_alpha = bool(getattr(vws, "preview_auto_alpha", True))

    diag = {
        "total_materials": 0,
        "unbaked_procedural": [],
        "dropped_normal": [],
        "dropped_roughness": [],
        "clamped_metallic": [],
        "transmission_to_alpha": [],
    }
    analyzed_names = set()
    saved_objs = _preview_state["obj_materials"]

    def_mat = get_or_create_varwin_default_material(backface_culling=backface_culling)

    for obj in list(scene.objects):
        if obj.type != "MESH" or is_preview_rig_object(obj) or is_collider_object(obj):
            continue

        # Snapshot original material slot names on first activation
        if obj.name not in saved_objs:
            slot_names = []
            for m in obj.data.materials:
                real = _resolve_real_material(m)
                slot_names.append(real.name if real else None)
            saved_objs[obj.name] = slot_names

        orig_names = saved_objs[obj.name]

        if not strict_parity:
            # Restore user materials but assign default material to empty meshes
            obj.data.materials.clear()
            if orig_names:
                for mname in orig_names:
                    mat = bpy.data.materials.get(mname) if mname else def_mat
                    obj.data.materials.append(mat or def_mat)
            else:
                obj.data.materials.append(def_mat)
            continue

        obj.data.materials.clear()
        if not orig_names:
            obj.data.materials.append(def_mat)
            continue

        for mname in orig_names:
            orig_mat = bpy.data.materials.get(mname) if mname else None
            if not orig_mat:
                obj.data.materials.append(def_mat)
                continue

            proxy, analysis = build_varwin_proxy_material(
                orig_mat,
                clamp_metallic=clamp_metallic,
                backface_culling=backface_culling,
                auto_alpha=auto_alpha,
            )
            obj.data.materials.append(proxy)

            if orig_mat.name not in analyzed_names:
                analyzed_names.add(orig_mat.name)
                diag["total_materials"] += 1
                if analysis.get("unbaked_procedural"):
                    diag["unbaked_procedural"].append(orig_mat.name)
                if analysis.get("dropped_normal"):
                    diag["dropped_normal"].append(orig_mat.name)
                if analysis.get("dropped_roughness"):
                    diag["dropped_roughness"].append(orig_mat.name)
                if analysis.get("clamped_metallic"):
                    diag["clamped_metallic"].append(orig_mat.name)
                if analysis.get("transmission_to_alpha"):
                    diag["transmission_to_alpha"].append(orig_mat.name)

    _preview_state["diagnostics"] = diag

    # View Layer clay override
    vl = getattr(context, "view_layer", None) if context else None
    if not vl and getattr(scene, "view_layers", None):
        vl = scene.view_layers[0] if len(scene.view_layers) > 0 else None
    if vl:
        if getattr(vws, "preview_material_mode", "STANDARD_PBR") == "DEFAULT_CLAY":
            vl.material_override = def_mat
        else:
            vl.material_override = None


def restore_preview_proxies(scene):
    """Restores exact original material slots and removes temporary `__VarwinPreview__*` materials."""
    saved_objs = _preview_state["obj_materials"]
    for obj_name, orig_names in list(saved_objs.items()):
        obj = bpy.data.objects.get(obj_name)
        if not obj or obj.type != "MESH" or not obj.data:
            continue
        obj.data.materials.clear()
        for mname in orig_names:
            mat = bpy.data.materials.get(mname) if mname else None
            obj.data.materials.append(mat)
    saved_objs.clear()

    # Clear View Layer override
    if scene and getattr(scene, "view_layers", None):
        for vl in scene.view_layers:
            if vl.material_override and (
                vl.material_override.get("varwin_preview_proxy")
                or vl.material_override.name == "Varwin_Default_Standard_MAT"
            ):
                vl.material_override = None

    # Remove all temporary proxy materials (keep Varwin_Default_Standard_MAT if assigned manually)
    for mat in list(bpy.data.materials):
        if mat.get("varwin_preview_proxy"):
            try:
                bpy.data.materials.remove(mat, do_unlink=True)
            except Exception:
                pass


def _get_or_create_eevee_shadow_floor_mat(shadow_strength=0.45):
    """
    Creates an EEVEE-compatible transparent shadow catcher material using
    `Diffuse BSDF -> ShaderToRGB -> RGBToBW -> MapRange -> MixShader(Transparent, Diffuse)`.
    """
    mat_name = "Varwin_Preview_Floor_MAT"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(mat_name)

    mat["varwin_preview_proxy"] = True
    mat.use_backface_culling = False
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    if hasattr(mat, "use_transparent_shadow"):
        mat.use_transparent_shadow = True

    nt = _ensure_node_tree(mat)
    nt.nodes.clear()

    out_node = nt.nodes.new("ShaderNodeOutputMaterial")
    out_node.location = (520, 0)

    mix_sh = nt.nodes.new("ShaderNodeMixShader")
    mix_sh.location = (300, 0)
    nt.links.new(mix_sh.outputs["Shader"], out_node.inputs["Surface"])

    transp = nt.nodes.new("ShaderNodeBsdfTransparent")
    transp.location = (60, 80)
    nt.links.new(transp.outputs["BSDF"], mix_sh.inputs[1])

    shadow_tint = nt.nodes.new("ShaderNodeBsdfDiffuse")
    shadow_tint.location = (60, -80)
    shadow_tint.inputs["Color"].default_value = (0.04, 0.05, 0.08, 1.0)
    nt.links.new(shadow_tint.outputs["BSDF"], mix_sh.inputs[2])

    lit_probe = nt.nodes.new("ShaderNodeBsdfDiffuse")
    lit_probe.location = (-520, 220)
    lit_probe.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)

    s2rgb = nt.nodes.new("ShaderNodeShaderToRGB")
    s2rgb.location = (-320, 220)
    nt.links.new(lit_probe.outputs["BSDF"], s2rgb.inputs["Shader"])

    rgb2bw = nt.nodes.new("ShaderNodeRGBToBW")
    rgb2bw.location = (-130, 220)
    nt.links.new(s2rgb.outputs["Color"], rgb2bw.inputs["Color"])

    map_r = nt.nodes.new("ShaderNodeMapRange")
    map_r.location = (60, 240)
    map_r.clamp = True
    map_r.inputs["From Min"].default_value = 0.0
    map_r.inputs["From Max"].default_value = 0.55
    map_r.inputs["To Min"].default_value = max(0.0, min(0.95, float(shadow_strength)))
    map_r.inputs["To Max"].default_value = 0.0
    nt.links.new(rgb2bw.outputs["Val"], map_r.inputs["Value"])
    nt.links.new(map_r.outputs["Result"], mix_sh.inputs["Fac"])

    return mat


def _get_preset_colors(preset):
    """Returns (skybox_ground, skybox_horizon, skybox_sky, sun_color) for each preset."""
    if preset == "UNITY_SKYBOX":
        return (
            (0.22, 0.20, 0.18, 1.0),  # Unity default procedural ground (#5D5852 approx linear)
            (0.68, 0.76, 0.86, 1.0),  # Bright Unity horizon
            (0.18, 0.36, 0.72, 1.0),  # Unity cerulean sky
            (1.0, 0.96, 0.88),
        )
    if preset == "OUTDOOR":
        return (
            (0.26, 0.24, 0.18, 1.0),
            (0.68, 0.74, 0.80, 1.0),
            (0.24, 0.48, 0.84, 1.0),
            (1.0, 0.96, 0.88),
        )
    if preset == "INDOOR":
        return (
            (0.20, 0.18, 0.16, 1.0),
            (0.38, 0.36, 0.34, 1.0),
            (0.45, 0.42, 0.38, 1.0),
            (1.0, 0.92, 0.82),
        )
    # STUDIO
    return (
        (0.16, 0.17, 0.19, 1.0),
        (0.38, 0.40, 0.44, 1.0),
        (0.30, 0.36, 0.46, 1.0),
        (1.0, 0.98, 0.94),
    )


def _build_varwin_world_nodes(world, preset, amb_str, scene_props=None):
    """
    Constructs `Varwin_Preview_World` using `ShaderNodeLightPath` to separate:
    - Camera/Glossy rays: Procedural Unity Skybox gradient for viewport background & reflections.
    - Diffuse/Ambient rays: Exact `vwo_builder.py` `m_AmbientMode = 3` flat ambient probe color.
    """
    if not world:
        return
    nt = _ensure_node_tree(world)
    if not nt:
        return

    nt.nodes.clear()

    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-740, 120)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-560, 120)
    nt.links.new(tc.outputs["Normal"], sep.inputs["Vector"])

    map_range = nt.nodes.new("ShaderNodeMapRange")
    map_range.location = (-380, 120)
    map_range.inputs["From Min"].default_value = -1.0
    map_range.inputs["From Max"].default_value = 1.0
    map_range.inputs["To Min"].default_value = 0.0
    map_range.inputs["To Max"].default_value = 1.0
    nt.links.new(sep.outputs["Z"], map_range.inputs["Value"])

    # 1. Skybox branch (Camera + Glossy rays)
    ground_c, horizon_c, sky_c, sun_col = _get_preset_colors(preset)
    sky_ramp = nt.nodes.new("ShaderNodeValToRGB")
    sky_ramp.location = (-160, 220)
    sky_ramp.color_ramp.elements[0].position = 0.42
    sky_ramp.color_ramp.elements[0].color = ground_c
    sky_ramp.color_ramp.elements[1].position = 0.62
    sky_ramp.color_ramp.elements[1].color = sky_c
    el_mid = sky_ramp.color_ramp.elements.new(0.50)
    el_mid.color = horizon_c
    nt.links.new(map_range.outputs["Result"], sky_ramp.inputs["Fac"])

    bg_sky = nt.nodes.new("ShaderNodeBackground")
    bg_sky.location = (120, 220)
    bg_sky.inputs["Strength"].default_value = 0.75
    nt.links.new(sky_ramp.outputs["Color"], bg_sky.inputs["Color"])

    # 2. Flat Unity Ambient branch (Diffuse rays matching vwo_builder.py:1445-1471)
    amb_col = tuple(float(c) for c in getattr(scene_props, "ambient_color", (0.68, 0.70, 0.75))[:3]) if scene_props else (0.68, 0.70, 0.75)
    amb_scale = max(0.0, float(amb_str))
    amb_r = max(0.05, min(1.0, (amb_col[0] * 0.4 + sun_col[0] * 0.6) * amb_scale))
    amb_g = max(0.05, min(1.0, (amb_col[1] * 0.4 + sun_col[1] * 0.6) * amb_scale))
    amb_b = max(0.05, min(1.0, (amb_col[2] * 0.4 + sun_col[2] * 0.6) * amb_scale))

    amb_ramp = nt.nodes.new("ShaderNodeValToRGB")
    amb_ramp.location = (-160, -60)
    amb_ramp.color_ramp.elements[0].position = 0.45
    amb_ramp.color_ramp.elements[0].color = (amb_r * 0.90, amb_g * 0.90, amb_b * 0.90, 1.0)
    amb_ramp.color_ramp.elements[1].position = 0.55
    amb_ramp.color_ramp.elements[1].color = (amb_r, amb_g, amb_b, 1.0)
    nt.links.new(map_range.outputs["Result"], amb_ramp.inputs["Fac"])

    bg_amb = nt.nodes.new("ShaderNodeBackground")
    bg_amb.location = (120, -60)
    bg_amb.inputs["Strength"].default_value = 1.0
    nt.links.new(amb_ramp.outputs["Color"], bg_amb.inputs["Color"])

    # 3. Light Path switch: Camera or Glossy -> Skybox, Diffuse -> Flat Unity Ambient
    lp = nt.nodes.new("ShaderNodeLightPath")
    lp.location = (-160, 420)
    cam_or_glossy = nt.nodes.new("ShaderNodeMath")
    cam_or_glossy.operation = "MAXIMUM"
    cam_or_glossy.location = (120, 420)
    nt.links.new(lp.outputs["Is Camera Ray"], cam_or_glossy.inputs[0])
    nt.links.new(lp.outputs["Is Glossy Ray"], cam_or_glossy.inputs[1])

    mix_world = nt.nodes.new("ShaderNodeMixShader")
    mix_world.location = (360, 120)
    nt.links.new(cam_or_glossy.outputs["Value"], mix_world.inputs["Fac"])
    nt.links.new(bg_amb.outputs["Background"], mix_world.inputs[1])
    nt.links.new(bg_sky.outputs["Background"], mix_world.inputs[2])

    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (560, 120)
    nt.links.new(mix_world.outputs["Shader"], out.inputs["Surface"])


def _sync_scene_lights_for_preview(scene, vws, sun_obj):
    """Hides non-exported lights or disables point-light shadows to match Quest 2 / Unity parity."""
    saved_lights = _preview_state["scene_lights"]
    export_lights = bool(getattr(vws, "export_scene_lights", False))

    # Restore previous mutations before re-applying
    for name, info in list(saved_lights.items()):
        obj = bpy.data.objects.get(name)
        if obj and obj.type == "LIGHT":
            obj.hide_viewport = info["hide_viewport"]
            if obj.data:
                obj.data.energy = info["energy"]
                if hasattr(obj.data, "use_shadow"):
                    obj.data.use_shadow = info["use_shadow"]
    saved_lights.clear()

    user_sun = None
    for obj in scene.objects:
        if obj.type != "LIGHT" or is_preview_rig_object(obj):
            continue
        saved_lights[obj.name] = {
            "hide_viewport": obj.hide_viewport,
            "energy": getattr(obj.data, "energy", 1.0) if obj.data else 1.0,
            "use_shadow": getattr(obj.data, "use_shadow", True) if obj.data else True,
        }
        if not export_lights:
            obj.hide_viewport = True
        elif obj.data and obj.data.type == "SUN" and not obj.hide_get() and user_sun is None:
            user_sun = obj
            # Mirror user sun orientation into Varwin_Preview_Sun and hide original to avoid double lighting
            obj.hide_viewport = True
        elif obj.data and obj.data.type == "POINT":
            if hasattr(obj.data, "use_shadow"):
                obj.data.use_shadow = False

    if user_sun and sun_obj:
        sun_obj.matrix_world = user_sun.matrix_world.copy()
        if user_sun.data and sun_obj.data:
            sun_obj.data.color = tuple(user_sun.data.color[:3])


def _restore_scene_lights():
    saved_lights = _preview_state["scene_lights"]
    for name, info in list(saved_lights.items()):
        obj = bpy.data.objects.get(name)
        if obj and obj.type == "LIGHT":
            obj.hide_viewport = info["hide_viewport"]
            if obj.data:
                obj.data.energy = info["energy"]
                if hasattr(obj.data, "use_shadow"):
                    obj.data.use_shadow = info["use_shadow"]
    saved_lights.clear()


def _sync_colliders_visibility(scene, hide_colliders=True):
    saved_cols = _preview_state["hidden_colliders"]
    saved_col_collections = _preview_state["hidden_collider_cols"]

    if not hide_colliders:
        _restore_colliders_visibility()
        return

    for obj in scene.objects:
        if is_preview_rig_object(obj):
            continue
        if is_collider_object(obj):
            if obj.name not in saved_cols:
                saved_cols[obj.name] = obj.hide_viewport
            obj.hide_viewport = True

    if getattr(scene, "view_layers", None):
        for vl in scene.view_layers:
            for lc in vl.layer_collection.children:
                if "collider" in lc.name.lower():
                    if lc.name not in saved_col_collections:
                        saved_col_collections[lc.name] = lc.hide_viewport
                    lc.hide_viewport = True


def _restore_colliders_visibility():
    saved_cols = _preview_state["hidden_colliders"]
    for name, orig_hide in list(saved_cols.items()):
        obj = bpy.data.objects.get(name)
        if obj:
            obj.hide_viewport = orig_hide
    saved_cols.clear()

    saved_col_collections = _preview_state["hidden_collider_cols"]
    if bpy.context and getattr(bpy.context, "scene", None):
        for vl in bpy.context.scene.view_layers:
            for lc in vl.layer_collection.children:
                if lc.name in saved_col_collections:
                    lc.hide_viewport = saved_col_collections[lc.name]
    saved_col_collections.clear()


def _apply_eevee_unity_settings(scene, vws):
    if not hasattr(scene, "eevee"):
        return
    eevee = scene.eevee
    if "eevee_settings" not in _preview_state:
        _preview_state["eevee_settings"] = {
            "use_raytracing": getattr(eevee, "use_raytracing", False),
            "use_fast_gi": getattr(eevee, "use_fast_gi", False),
            "fast_gi_method": getattr(eevee, "fast_gi_method", "GLOBAL_ILLUMINATION"),
            "fast_gi_distance": getattr(eevee, "fast_gi_distance", 4.0),
            "fast_gi_quality": getattr(eevee, "fast_gi_quality", 1.0),
            "fast_gi_bias": getattr(eevee, "fast_gi_bias", 0.05),
            "indirect_light_intensity": getattr(eevee, "indirect_light_intensity", 1.0),
            "shadow_ray_count": getattr(eevee, "shadow_ray_count", 1),
            "shadow_resolution_scale": getattr(eevee, "shadow_resolution_scale", 1.0),
            "use_shadows": getattr(eevee, "use_shadows", True),
        }

    use_ssao = bool(getattr(vws, "preview_use_ssao", False)) if vws else False
    shadow_mode = getattr(vws, "light_shadows", "SOFT") if vws else "SOFT"
    try:
        eevee.use_raytracing = False
        eevee.use_fast_gi = use_ssao
        if use_ssao:
            eevee.fast_gi_method = "AMBIENT_OCCLUSION_ONLY" if hasattr(eevee, "fast_gi_method") else "GLOBAL_ILLUMINATION"
            eevee.fast_gi_distance = 1.5
            eevee.fast_gi_quality = 1.0
            eevee.fast_gi_bias = 0.05
        if hasattr(eevee, "indirect_light_intensity"):
            eevee.indirect_light_intensity = 0.6
        eevee.shadow_ray_count = 2
        eevee.shadow_resolution_scale = 1.0
        eevee.use_shadows = shadow_mode != "NONE"
    except Exception:
        pass


def _apply_sun_params(sun_obj, vws):
    if not sun_obj or not sun_obj.data:
        return
    preset = getattr(vws, "preview_lighting_preset", "UNITY_SKYBOX") if vws else "UNITY_SKYBOX"
    _, _, _, preset_sun_col = _get_preset_colors(preset)

    sun_obj.data.energy = float(getattr(vws, "preview_sun_intensity", 1.5)) if vws else 1.5
    if preset == "OUTDOOR" and vws:
        sun_obj.data.color = tuple(float(c) for c in getattr(vws, "light_color", preset_sun_col)[:3])
    else:
        sun_obj.data.color = preset_sun_col

    softness = float(getattr(vws, "preview_shadow_softness", 0.06)) if vws else 0.06
    shadow_mode = getattr(vws, "light_shadows", "SOFT") if vws else "SOFT"
    if hasattr(sun_obj.data, "use_shadow"):
        sun_obj.data.use_shadow = shadow_mode != "NONE"
    if shadow_mode == "HARD":
        sun_obj.data.angle = math.radians(0.5)
    else:
        sun_obj.data.angle = math.radians(0.5 + max(0.0, softness) * 12.0)
    if hasattr(sun_obj.data, "shadow_soft_size"):
        sun_obj.data.shadow_soft_size = softness


def setup_varwin_render_rig(context, scene, vws):
    """
    Creates and activates the 1:1 Varwin Render Rig:
    - Unity Built-in Forward EEVEE configuration (no Cycles-style raytrace noise, 0.6 reflection probe)
    - Directional Sun Light with real angular shadow softness (`sun.data.angle`)
    - Transparent EEVEE Shadow Catcher floor right below `z_min` (no Z-fighting)
    - LightPath World splitting Skybox background/glossy from flat Unity Ambient
    - Collider hiding and non-exported scene light isolation
    """
    if not scene:
        return None

    _apply_eevee_unity_settings(scene, vws)

    col_name = "Varwin_Render_Preview_Rig"
    col = bpy.data.collections.get(col_name)
    if not col:
        col = bpy.data.collections.new(col_name)
        scene.collection.children.link(col)

    # 1. Varwin Directional Sun Light
    sun_obj = col.objects.get("Varwin_Preview_Sun")
    if not sun_obj:
        sun_data = bpy.data.lights.new(name="Varwin_Preview_Sun_Light", type="SUN")
        sun_obj = bpy.data.objects.new(name="Varwin_Preview_Sun", object_data=sun_data)
        col.objects.link(sun_obj)
    sun_obj["varwin_preview_rig"] = True
    sun_obj.hide_render = True
    sun_obj.rotation_euler = (math.radians(50), math.radians(-15), math.radians(-30))
    _apply_sun_params(sun_obj, vws)

    # 2. Varwin Transparent Shadow Catcher Floor
    z_min = 0.0
    meshes = [
        o for o in scene.objects
        if o.type == "MESH" and not is_preview_rig_object(o) and not is_collider_object(o)
    ]
    if meshes:
        all_z = []
        for o in meshes:
            try:
                for corner in o.bound_box:
                    all_z.append((o.matrix_world @ mathutils.Vector(corner)).z)
            except Exception:
                pass
        if all_z:
            z_min = min(all_z)

    floor_obj = col.objects.get("Varwin_Preview_Floor")
    if not floor_obj:
        mesh = bpy.data.meshes.new("Varwin_Preview_Floor_Mesh")
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=80.0)
        bm.to_mesh(mesh)
        bm.free()
        floor_obj = bpy.data.objects.new(name="Varwin_Preview_Floor", object_data=mesh)
        col.objects.link(floor_obj)

    floor_obj["varwin_preview_rig"] = True
    floor_obj.hide_render = True
    floor_obj.hide_select = True
    floor_obj.location = (0.0, 0.0, z_min - 0.002)
    if hasattr(floor_obj, "visible_shadow"):
        floor_obj.visible_shadow = False
    if hasattr(floor_obj, "is_shadow_catcher"):
        floor_obj.is_shadow_catcher = True

    shadow_str = float(getattr(vws, "shadow_strength", 0.45)) if vws else 0.45
    floor_mat = _get_or_create_eevee_shadow_floor_mat(shadow_str)
    floor_obj.data.materials.clear()
    floor_obj.data.materials.append(floor_mat)

    show_floor = bool(getattr(vws, "preview_show_floor", True)) if vws else True
    floor_obj.hide_viewport = not show_floor

    # 3. LightPath World (Skybox + Flat Unity Ambient)
    w_name = "Varwin_Preview_World"
    world = bpy.data.worlds.get(w_name)
    if not world:
        world = bpy.data.worlds.new(w_name)
    preset = getattr(vws, "preview_lighting_preset", "UNITY_SKYBOX") if vws else "UNITY_SKYBOX"
    amb_str = float(getattr(vws, "preview_ambient_intensity", 0.55)) if vws else 0.55
    _build_varwin_world_nodes(world, preset, amb_str, scene_props=vws)
    scene.world = world

    # 4. Sync scene lights & colliders
    _sync_scene_lights_for_preview(scene, vws, sun_obj)
    _sync_colliders_visibility(scene, bool(getattr(vws, "preview_hide_colliders", True)) if vws else True)

    return col


def cleanup_varwin_render_rig(scene):
    """Safely removes the Varwin preview rig, world, and restores lights, colliders, and EEVEE."""
    if not scene:
        return

    _restore_scene_lights()
    _restore_colliders_visibility()

    if hasattr(scene, "eevee") and "eevee_settings" in _preview_state:
        saved_ev = _preview_state.pop("eevee_settings", {})
        for k, v in saved_ev.items():
            try:
                setattr(scene.eevee, k, v)
            except Exception:
                pass

    col_name = "Varwin_Render_Preview_Rig"
    col = bpy.data.collections.get(col_name)
    if col:
        for obj in list(col.objects):
            try:
                col.objects.unlink(obj)
            except Exception:
                pass
            data = obj.data
            try:
                bpy.data.objects.remove(obj)
            except Exception:
                pass
            if data:
                if isinstance(data, bpy.types.Mesh):
                    try:
                        bpy.data.meshes.remove(data)
                    except Exception:
                        pass
                elif isinstance(data, bpy.types.Light):
                    try:
                        bpy.data.lights.remove(data)
                    except Exception:
                        pass
        if col.name in scene.collection.children:
            try:
                scene.collection.children.unlink(col)
            except Exception:
                pass
        try:
            bpy.data.collections.remove(col)
        except Exception:
            pass

    floor_mat = bpy.data.materials.get("Varwin_Preview_Floor_MAT")
    if floor_mat:
        try:
            bpy.data.materials.remove(floor_mat, do_unlink=True)
        except Exception:
            pass


def update_varwin_render_rig_params(scene, vws):
    """Updates existing live Varwin preview rig parameters in real time."""
    if not scene or not vws or not getattr(vws, "render_preview_active", False):
        return

    _apply_eevee_unity_settings(scene, vws)
    _sync_colliders_visibility(scene, bool(getattr(vws, "preview_hide_colliders", True)))

    col = bpy.data.collections.get("Varwin_Render_Preview_Rig")
    if not col:
        return

    preset = getattr(vws, "preview_lighting_preset", "UNITY_SKYBOX")
    sun_obj = col.objects.get("Varwin_Preview_Sun")
    _apply_sun_params(sun_obj, vws)

    floor_obj = col.objects.get("Varwin_Preview_Floor")
    if floor_obj:
        floor_obj.hide_viewport = not getattr(vws, "preview_show_floor", True)
        shadow_str = float(getattr(vws, "shadow_strength", 0.45))
        _get_or_create_eevee_shadow_floor_mat(shadow_str)

    world = bpy.data.worlds.get("Varwin_Preview_World")
    if world:
        amb_str = getattr(vws, "preview_ambient_intensity", 0.55)
        _build_varwin_world_nodes(world, preset, amb_str, scene_props=vws)


def update_varwin_render_preview_mode(context):
    """Handles runtime toggle between 100% Unity Render (EEVEE) and Material Preview."""
    scene = getattr(context, "scene", None) or bpy.context.scene
    vws = getattr(scene, "varwin_scene", None)
    if not vws or not vws.render_preview_active:
        return

    render_mode = getattr(vws, "preview_render_mode", "FULL_UNITY")
    target_shading = "RENDERED" if render_mode == "FULL_UNITY" else "MATERIAL"
    preset_lights = {
        "UNITY_SKYBOX": "studio.exr",
        "STUDIO": "studio.exr",
        "OUTDOOR": "forest.exr",
        "INDOOR": "interior.exr",
    }
    target_light = preset_lights.get(vws.preview_lighting_preset, "studio.exr")

    if render_mode == "FULL_UNITY":
        setup_varwin_render_rig(context, scene, vws)
    else:
        col = bpy.data.collections.get("Varwin_Render_Preview_Rig")
        if col:
            floor_obj = col.objects.get("Varwin_Preview_Floor")
            if floor_obj:
                floor_obj.hide_viewport = True

    wm = context.window_manager
    windows = getattr(wm, "windows", []) or ([context.window] if getattr(context, "window", None) else [])
    for window in windows:
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        sh = space.shading
                        sh.type = target_shading
                        if target_shading == "MATERIAL":
                            try:
                                sh.studio_light = target_light
                            except Exception:
                                pass
                            sh.use_scene_lights = False
                            sh.use_scene_world = False
                        else:
                            sh.use_scene_lights = True
                            sh.use_scene_world = True
                area.tag_redraw()


def toggle_varwin_render_preview(context):
    """Activates or deactivates 1:1 Varwin Render Preview cleanly and non-destructively."""
    scene = context.scene
    vws = scene.varwin_scene
    new_state = not vws.render_preview_active
    vws.render_preview_active = new_state

    render_mode = getattr(vws, "preview_render_mode", "FULL_UNITY")
    target_shading = "RENDERED" if render_mode == "FULL_UNITY" else "MATERIAL"

    preset_lights = {
        "UNITY_SKYBOX": "studio.exr",
        "STUDIO": "studio.exr",
        "OUTDOOR": "forest.exr",
        "INDOOR": "interior.exr",
    }
    target_light = preset_lights.get(vws.preview_lighting_preset, "studio.exr")

    if new_state:
        if "engine" not in _preview_state:
            _preview_state["engine"] = getattr(scene.render, "engine", "BLENDER_EEVEE")
        if "world" not in _preview_state:
            _preview_state["world"] = scene.world
        if "view_transform" not in _preview_state:
            _preview_state["view_transform"] = getattr(scene.view_settings, "view_transform", "AgX")
        if "look" not in _preview_state:
            _preview_state["look"] = getattr(scene.view_settings, "look", "None")
        if "exposure" not in _preview_state:
            _preview_state["exposure"] = float(getattr(scene.view_settings, "exposure", 0.0))
        if "gamma" not in _preview_state:
            _preview_state["gamma"] = float(getattr(scene.view_settings, "gamma", 1.0))

        try:
            scene.render.engine = _get_eevee_engine_id(scene)
        except Exception:
            pass
        try:
            scene.view_settings.view_transform = "Standard"
        except Exception:
            pass
        try:
            scene.view_settings.look = "None"
        except Exception:
            pass
        try:
            scene.view_settings.exposure = 0.0
            scene.view_settings.gamma = 1.0
        except Exception:
            pass

        if render_mode == "FULL_UNITY":
            setup_varwin_render_rig(context, scene, vws)
        else:
            _sync_colliders_visibility(scene, bool(getattr(vws, "preview_hide_colliders", True)))

        apply_preview_proxies(context, scene, vws)
    else:
        restore_preview_proxies(scene)
        cleanup_varwin_render_rig(scene)

        if "world" in _preview_state:
            scene.world = _preview_state.pop("world", None)
        if "engine" in _preview_state:
            try:
                scene.render.engine = _preview_state.pop("engine", "BLENDER_EEVEE")
            except Exception:
                pass
        if "view_transform" in _preview_state:
            try:
                scene.view_settings.view_transform = _preview_state.pop("view_transform", "AgX")
            except Exception:
                pass
        if "look" in _preview_state:
            try:
                scene.view_settings.look = _preview_state.pop("look", "None")
            except Exception:
                pass
        if "exposure" in _preview_state:
            try:
                scene.view_settings.exposure = _preview_state.pop("exposure", 0.0)
            except Exception:
                pass
        if "gamma" in _preview_state:
            try:
                scene.view_settings.gamma = _preview_state.pop("gamma", 1.0)
            except Exception:
                pass

    wm = context.window_manager
    windows = getattr(wm, "windows", [])
    if not windows and getattr(context, "window", None):
        windows = [context.window]

    vp_states = _preview_state["viewport_states"]
    for window in windows:
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        sh = space.shading
                        sp_key = space.as_pointer()
                        if new_state:
                            if sp_key not in vp_states:
                                vp_states[sp_key] = {
                                    "shading_type": str(sh.type),
                                    "studio_light": str(getattr(sh, "studio_light", "studio.exr")),
                                    "use_scene_lights": bool(getattr(sh, "use_scene_lights", False)),
                                    "use_scene_world": bool(getattr(sh, "use_scene_world", False)),
                                }
                            sh.type = target_shading
                            if target_shading == "MATERIAL":
                                try:
                                    sh.studio_light = target_light
                                except Exception:
                                    pass
                                sh.use_scene_lights = False
                                sh.use_scene_world = False
                            else:
                                sh.use_scene_lights = True
                                sh.use_scene_world = True
                        else:
                            saved = vp_states.pop(sp_key, {})
                            try:
                                sh.type = saved.get("shading_type", "SOLID")
                            except Exception:
                                pass
                            if hasattr(sh, "studio_light") and "studio_light" in saved:
                                try:
                                    sh.studio_light = saved["studio_light"]
                                except Exception:
                                    pass
                            if hasattr(sh, "use_scene_lights") and "use_scene_lights" in saved:
                                sh.use_scene_lights = bool(saved["use_scene_lights"])
                            if hasattr(sh, "use_scene_world") and "use_scene_world" in saved:
                                sh.use_scene_world = bool(saved["use_scene_world"])
                area.tag_redraw()

    return new_state
