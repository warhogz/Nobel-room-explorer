"""Shared paths and the Corona -> Unreal conversion constants (imported by build_assets.py / build_level.py)."""
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("NIK_ROOT") or os.path.normpath(os.path.join(HERE, "..", ".."))
UE_DIR = os.path.join(ROOT, "build", "ue")
SCENE = json.load(open(os.path.join(UE_DIR, "scene.json"), encoding="utf-8"))
GAME = "/Game/Nobel"

# Corona works in radiometric units (W, W/(sr m2)); Unreal lights in candela / lux, emissive in nits
PHOT = 683.0
# Corona tone mapping of the villa: exposure 2.253 EV. Unreal manual exposure: scale = 2^bias / 1.2, so the same
# pixel = radiance * 2^2.253 needs bias = log2(1.2 * 2^2.253 / PHOT)
CORONA_EV = 2.253
EXPOSURE_BIAS = math.log2(1.2 * 2 ** CORONA_EV / PHOT)
WHITE_TEMP = 6300.0  # Corona white balance

# kitchen / hall boundary along x (cm from the island centre)
KITCHEN_X = 272.0

# Per-material corrections, by the original Max material name. Ported from web/src/three/Kitchen.tsx: only the ones
# that fix the conversion itself (missing maps, measured colours) - not the real-time lighting workarounds.
TWEAKS = {
    # honed travertine: its reflection map is missing from the archive -> IOR 3 alone reads as a wet mirror
    "travertine7567567": {"ior": 1.5, "roughness": 0.5, "dropRoughnessMap": True},
    "travertine": {"ior": 1.5, "roughness": 0.5, "dropRoughnessMap": True},
    # photo backdrops outside the windows: a print, not a mirror
    "Material #-2147483574": {"roughness": 1.0, "spec": 0.0},
    # bar stools: caramel nubuck in the renders. The nubuck scan stays (the web dropped it), repeated 8x like its
    # grain; tint = measured caramel [0.4, 0.2, 0.09] / the map's mean linear colour [0.32, 0.284, 0.257]
    "Material #2147455760": {"detail": 8, "tint": [1.25, 0.70, 0.35], "roughness": 0.78},
    # brass walls / ceiling: colours measured against renders 10 / 12
    # the brushed-brass maps swing roughness 0.28..0.55 on a fully metallic surface: under 250 lamps that is dark
    # vertical ribs and sparkle -> one calm satin roughness, and 40 % diffuse so the room's light bounces on it
    "Material #2147483647": {"tint": [2.06, 2.3, 2.48], "dropRoughnessMap": True, "roughness": 0.42, "metallic": 0.6},
    "Material #-2147483422": {"tint": [1.71, 1.89, 2.06], "dropRoughnessMap": True, "roughness": 0.42, "metallic": 0.6},
    "Material #-2147483644": {"tint": [1.0, 0.72, 0.5]},
    # upholstery with procedural Corona colour chains, measured on render 28
    # dining chair suede: no colour map in the scene and a flat normal map -> the bar-stool nubuck maps, tinted to
    # the camel measured on render 28 ([0.5, 0.25, 0.11] / the map's mean)
    "Material #-2147483443": {"maps": {"baseColorTex": "Material__2147455760_M12038_base_126c78a0.png",
                                       "normalTex": "Material__2147455760_M12038_nrm_58e39f33.png"},
                              "tint": [1.56, 0.88, 0.43], "detail": 6, "spec": 0.35, "roughness": 0.8},
    "Material #-2147483646": {"color": [0.5, 0.25, 0.11], "spec": 0.5, "roughness": 0.6},
    "Material #-2147483565": {"color": [0.06, 0.032, 0.016], "spec": 0.7, "roughness": 0.42},
    # sofa cushions: their gloss map is missing from the archive
    "Material #-214748313700675": {"roughness": 0.85},
    # chandelier gold leaf: the archive lost its reflection colour (black base, specular ~0) -> polished gold
    "Material #-2147483534": {"color": [1.0, 0.72, 0.33], "metallic": 1.0, "roughness": 0.18, "spec": 0.5},
    # the sculpture's flat flakes: same loss, satin amber gold in the renders
    "Material #-2147483537": {"color": [0.85, 0.55, 0.22], "metallic": 1.0, "roughness": 0.35, "spec": 0.5},
    # pleated floor lamp: translucent shade + diffuser lit by the bulb inside
    "Material #4931": {"glow": [0.34, 0.2, 0.09]},
    "Material #4880": {"glow": [1.0, 0.62, 0.3]},
}
# polished onyx / lacquered walnut: clear coat over the base
COATS = {
    "Material #-2147483589": {"clearcoat": 0.45, "clearcoatRoughness": 0.16, "minRoughness": 0.3},
    "Material #76111117": {"clearcoat": 0.45, "clearcoatRoughness": 0.28},
}
RELIEF = {"Material #-2147483589": 1.7, "travertine7567567": 1.6, "Material #76111117": 1.3,
          "Material #2147455760": 0.35, "Material #-2147483443": 0.4}
ONYX = "Material #-2147483589"
# backlit onyx glow (nits per unit of the translucency map): island and the kitchen shelf niche
ONYX_GLOW_NITS = 900.0
NICHE_GLOW_NITS = 220.0
ONYX_GLOW_COLOR = [1.0, 0.6, 0.28]
LAMP_GLOW_NITS = 1200.0


def slug(s, n=48):
    return re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_")[:n] or "x"


def tex_asset(fname):
    return "T_" + slug(os.path.splitext(fname)[0], 60)


def mi_name(mid, spec):
    return "MI_" + slug(spec.get("origName") or mid, 40) + "_" + slug(mid, 16)


def f0_specular(spec, tw):
    """Unreal Specular (F0 / 0.08) from the IOR and the Blender-style specular level (0.5 = plain Fresnel)"""
    if tw.get("spec") is not None:
        return tw["spec"]
    ior = tw.get("ior") or spec.get("ior") or 1.5
    if not 1.0 < ior < 10:
        ior = 1.5
    f0 = ((ior - 1) / (ior + 1)) ** 2 * 2 * spec.get("specularLevel", 0.5)
    return max(0.0, min(1.0, f0 / 0.08))
