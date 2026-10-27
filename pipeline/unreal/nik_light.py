"""Light-group controls of the room level (in the editor): the LightMix of the Unreal scene.

Groups: kitchen (all artificial lights, folder Lights/kitchen), pol (the 8 floor uplights), env (suns + sky light),
emissive (EmissiveScale / GlowScale of the material instances). The base intensities are the ones build_level.py set;
they are kept in build/ue/light_base.json so gains are always relative to the conversion.
"""
import json
import os

import unreal

from nik_ue import GAME, UE_DIR

BASE = os.path.join(UE_DIR, "light_base.json")
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MEL = unreal.MaterialEditingLibrary


def _group(a):
    f = str(a.get_folder_path())
    if f.startswith("Lights/"):
        g = f.split("/")[1]
        return g if g in ("kitchen", "pol", "ostrov") else "env"
    return None


def _comp(a):
    for cls in (unreal.LocalLightComponent, unreal.DirectionalLightComponent, unreal.SkyLightComponent):
        c = a.get_component_by_class(cls)
        if c:
            return c
    return None


def _instances():
    return [unreal.load_asset(p) for p in unreal.EditorAssetLibrary.list_assets(GAME + "/Materials/Instances")]


def base():
    """intensities as built (recorded on first use)"""
    if os.path.exists(BASE):
        return json.load(open(BASE))
    b = {"lights": {}, "emissive": {}}
    for a in EAS.get_all_level_actors():
        c = _comp(a) if _group(a) else None
        if c:
            b["lights"][a.get_actor_label()] = c.intensity
    for mi in _instances():
        if not isinstance(mi, unreal.MaterialInstanceConstant) or mi.parent.get_name() != "M_Nik":
            continue
        ec = MEL.get_material_instance_vector_parameter_value(mi, "EmissiveColor")
        glow = MEL.get_material_instance_scalar_parameter_value(mi, "GlowScale")
        if max(ec.r, ec.g, ec.b) > 0 or glow > 0:  # only the emitters
            b["emissive"][mi.get_name()] = [MEL.get_material_instance_scalar_parameter_value(mi, "EmissiveScale"), glow]
    json.dump(b, open(BASE, "w"), indent=0)
    return b


def set_gains(gains):
    """gains: {"kitchen": k, "pol": k, "env": k, "emissive": k} (missing = 1)"""
    b = base()
    for a in EAS.get_all_level_actors():
        g = _group(a)
        if not g:
            continue
        c = _comp(a)
        v = b["lights"].get(a.get_actor_label())
        if c is None or v is None:
            continue
        k = gains.get(g, 1.0)
        c.set_editor_property("intensity", v * k)
        c.set_visibility(k > 0)
    ke = gains.get("emissive", 1.0)
    for mi in _instances():
        e = b["emissive"].get(mi.get_name())
        if e and (e[0] or e[1]):
            MEL.set_material_instance_scalar_parameter_value(mi, "EmissiveScale", e[0] * ke)
            MEL.set_material_instance_scalar_parameter_value(mi, "GlowScale", e[1] * ke)
            MEL.update_material_instance(mi)
