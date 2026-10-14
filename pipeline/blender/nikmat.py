"""Compiled Corona->PBR material specs (compile_materials.py) -> Blender node materials.

Node names used by the bake/export scripts:
  BSDF (Principled), BaseTex, TranslMix / Translucent / TranslTex (bake-only translucency branch),
  BakeShader (bake-only replacement for glass: Transparent BSDF) + material["nik"] JSON with flags.
"""
import json
import os

import bpy


def _img(tex_dir, name, color):
    im = bpy.data.images.load(os.path.join(tex_dir, name), check_existing=True)
    im.colorspace_settings.name = "sRGB" if color else "Non-Color"
    return im


def _uv_mapping(nt, uv, x, y):
    """Max tiling (or real-world size) -> Mapping node (glTF exporter writes KHR_texture_transform)"""
    if not uv:
        return None
    sx, sy = uv.get("scale") or [1, 1]
    if uv.get("realWorld"):
        sx, sy = (1.0 / sx if sx else 1.0), (1.0 / sy if sy else 1.0)
    if abs(sx - 1) < 1e-4 and abs(sy - 1) < 1e-4:
        return None
    tc = nt.nodes.new("ShaderNodeUVMap")
    tc.uv_map = "UVMap"
    tc.location = (x - 400, y)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.vector_type = "POINT"
    mp.inputs["Scale"].default_value = (sx, sy, 1.0)
    mp.location = (x - 200, y)
    nt.links.new(tc.outputs["UV"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def build_material(spec, tex_dir, mname=None):
    m = bpy.data.materials.new(mname or spec["name"])
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (900, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.name = "BSDF"
    bsdf.location = (500, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    uvvec = _uv_mapping(nt, spec.get("uv"), -400, 600)

    def tex(name, color, loc):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = _img(tex_dir, name, color)
        t.location = loc
        if uvvec is not None:
            nt.links.new(uvvec, t.inputs["Vector"])
        return t

    bc = spec.get("baseColor", [0.8, 0.8, 0.8])
    bsdf.inputs["Base Color"].default_value = (*bc[:3], 1.0)
    if spec.get("baseColorTex"):
        t = tex(spec["baseColorTex"], True, (-400, 300))
        t.name = "BaseTex"
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
        if spec.get("alphaMode") == "MASK":
            r = nt.nodes.new("ShaderNodeMath")
            r.operation = "ROUND"  # glTF exporter reads ROUND as alpha clip at 0.5
            nt.links.new(t.outputs["Alpha"], r.inputs[0])
            nt.links.new(r.outputs[0], bsdf.inputs["Alpha"])
    bsdf.inputs["Metallic"].default_value = spec.get("metallic", 0.0)
    bsdf.inputs["Roughness"].default_value = min(1.0, max(0.0, spec.get("roughness", 0.5)))
    if spec.get("roughnessTex"):
        t = tex(spec["roughnessTex"], False, (-400, 0))
        nt.links.new(t.outputs["Color"], bsdf.inputs["Roughness"])
    ior = spec.get("ior", 1.5) or 1.5
    bsdf.inputs["IOR"].default_value = ior if 1.0 < ior < 4 else 1.5
    if spec.get("specularLevel") is not None:  # glTF KHR_materials_specular
        bsdf.inputs["Specular IOR Level"].default_value = spec["specularLevel"]
    if spec.get("sheen"):  # glTF KHR_materials_sheen: soft fabric rim
        bsdf.inputs["Sheen Weight"].default_value = spec["sheen"]
        bsdf.inputs["Sheen Roughness"].default_value = 0.6
        bsdf.inputs["Sheen Tint"].default_value = (0.55, 0.5, 0.45, 1.0)
    if spec.get("normalTex"):
        t = tex(spec["normalTex"], False, (-400, -300))
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.uv_map = "UVMap"
        nm.inputs["Strength"].default_value = spec.get("normalScale", 1.0)
        nm.location = (0, -300)
        nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    m.use_backface_culling = not spec.get("doubleSided")
    nik = {}
    em = spec.get("emissive")
    if em and max(em) > 0:
        s = max(em)
        bsdf.inputs["Emission Color"].default_value = (em[0] / s, em[1] / s, em[2] / s, 1.0)
        bsdf.inputs["Emission Strength"].default_value = s
        nik["emissive"] = s
    tr_amt = spec.get("transmission") or 0
    if tr_amt > 0:
        bsdf.inputs["Transmission Weight"].default_value = min(1.0, tr_amt)
        # bake-only stand-in: light passes through (no caustic paths), a little absorption
        tp = nt.nodes.new("ShaderNodeBsdfTransparent")
        tp.name = "BakeShader"
        tp.inputs["Color"].default_value = (0.92, 0.92, 0.92, 1)
        tp.location = (500, -600)
        nik["glass"] = True
    tr = spec.get("translucency")
    if tr:
        tn = nt.nodes.new("ShaderNodeBsdfTranslucent")
        tn.name = "Translucent"
        tn.location = (500, -400)
        if tr.get("colorTex"):
            t = tex(tr["colorTex"], True, (-400, -650))
            t.name = "TranslTex"
            nt.links.new(t.outputs["Color"], tn.inputs["Color"])
        else:
            tn.inputs["Color"].default_value = (*tr["color"], 1)
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.name = "TranslMix"
        mix.inputs["Fac"].default_value = tr["fraction"]
        mix.location = (720, -200)
        nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
        nt.links.new(tn.outputs["BSDF"], mix.inputs[2])
        nik["translucency"] = {"fraction": tr["fraction"], "colorTex": tr.get("colorTex")}
    if spec.get("alphaMode") == "MASK":
        nik["cutout"] = True
    if spec.get("metallic", 0) >= 0.99:
        nik["metal"] = True
    if spec.get("origName"):
        nik["orig"] = spec["origName"]
    if spec.get("surface"):
        nik["surface"] = spec["surface"]
    if nik:
        m["nik"] = json.dumps(nik)
    return m


def nik_flags(mat):
    try:
        return json.loads(mat.get("nik", "{}"))
    except Exception:
        return {}
