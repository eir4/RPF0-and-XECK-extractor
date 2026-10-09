# xeck_blender_fix.py  -  run INSIDE Blender (Scripting tab > Open > Run Script) after importing a .glb made by xeck_ripper.
# Written against the Blender 4.x Python API; NOT run by the author (no Blender available) - if a line errors, send me the message.
# It reads the shader name / role / texture names stored as custom properties on every material (from the XECK itself) and:
#   hair, fins, ponytail, lashes, stubble materials (role in {hair, fins, lashes, stubble}):
#       Render Method = Dithered, Transparent Shadows off, Light Probe Volume (backface culling) off, backface culling off  (your settings)
#   hair shells (shader long_hair*): alpha = texture alpha x diffuseColor.a (0.113) raised toward the silhouette with a Layer Weight node
#   pong_stubble (China): Base Color = scalp texture x colour factor (#D2B8BC from the GLB); Alpha = red channel of the TILED stubble texture (uv set 2)
#   pong_nodraw: hidden
import bpy

def set_flag(mat, names, value):
    for n in names:
        if hasattr(mat, n):
            try: setattr(mat, n, value); return True
            except Exception: pass
    return False

def common_hair_settings(mat):
    try: mat.surface_render_method = "DITHERED"
    except Exception: mat.blend_method = "HASHED"
    set_flag(mat, ("use_transparent_shadow",), False)
    set_flag(mat, ("use_backface_culling_lightprobe_volume", "lightprobe_volume_single_sided"), False)
    set_flag(mat, ("use_backface_culling",), False)

def users(mat):
    return [ob for ob in bpy.data.objects if ob.type == "MESH" and any(s.material == mat for s in ob.material_slots)]

def img_node(nt, key):
    return next((n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image and key in n.image.name.lower()), None)

def fix_stubble(mat, bsdf):
    """China buzz cut, as set up by hand: Base Color = scalp texture (layout uv) x colour factor; Alpha = RED channel of the TILED stubble texture (uv set 2)."""
    nt = mat.node_tree
    scalp, stub = img_node(nt, "scalp"), img_node(nt, "stubble")
    obs = users(mat)
    if not (scalp and stub and obs and len(obs[0].data.uv_layers) > 1): print("stubble: nodes/uv layers not found for", mat.name); return
    uv2 = nt.nodes.new("ShaderNodeUVMap"); uv2.uv_map = obs[0].data.uv_layers[1].name           # tiled set
    stub.extension = "REPEAT"; nt.links.new(uv2.outputs["UV"], stub.inputs["Vector"])
    sep = nt.nodes.new("ShaderNodeSeparateColor"); nt.links.new(stub.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Red"], bsdf.inputs["Alpha"])
    # base colour: keep the importer's (scalp x factor) wiring; the factor itself comes from the GLB (#D2B8BC for China)

def fix_material(mat):
    shader = str(mat.get("shader", "")); role = str(mat.get("role", ""))
    if not shader or not mat.use_nodes: return
    nt = mat.node_tree; bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None: return
    if shader.startswith("pong_nodraw"):
        for ob in users(mat): ob.hide_viewport = ob.hide_render = True
        return
    if role not in ("hair", "fins", "lashes", "stubble"): return
    common_hair_settings(mat)
    if role == "stubble": fix_stubble(mat, bsdf); return
    if shader.startswith("long_hair") and not shader.startswith("long_hair_shadow") and role == "hair":
        a = mat.get("diffuseColor"); fa = float(a[3]) if a and len(a) > 3 else 0.113
        alink = next((l for l in nt.links if l.to_node == bsdf and l.to_socket.name == "Alpha"), None)
        lw = nt.nodes.new("ShaderNodeLayerWeight"); lw.inputs["Blend"].default_value = 0.5
        rng = nt.nodes.new("ShaderNodeMapRange"); rng.inputs["To Min"].default_value = fa; rng.inputs["To Max"].default_value = 1.0
        nt.links.new(lw.outputs["Fresnel"], rng.inputs["Value"])
        mul = nt.nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"
        if alink: nt.links.new(alink.from_socket, mul.inputs[0])
        else: mul.inputs[0].default_value = 1.0
        nt.links.new(rng.outputs["Result"], mul.inputs[1]); nt.links.new(mul.outputs["Value"], bsdf.inputs["Alpha"])

for m in bpy.data.materials: fix_material(m)
print("xeck_blender_fix: done")
