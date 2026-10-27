"""The room level: mesh actors, the Corona lights, sky, the client-render cameras, post process.

UnrealEditor.exe NobelKitchen.uproject -ExecutePythonScript=<this file>   (needs the editor world; run build_assets.py
first, or run_live.py for both at once). Rebuilds /Game/Nobel/Maps/L_Kitchen from scratch every time. NIK_QUIT=1 closes the editor when done.

Units: lights come from the Blender conversion (build_room.py) in watts: point / IES = radiant intensity P/(4 pi),
rect = peak intensity P/pi, sun = irradiance; x PHOT -> candela / lux. Exposure = the Corona EV (nik_ue.py).
"""
import math
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nik_ue import EXPOSURE_BIAS, GAME, PHOT, SCENE, WHITE_TEMP, slug  # noqa: E402

LEVEL = GAME + "/Maps/L_Kitchen"
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
LES = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def log(*a):
    unreal.log("NIK " + " ".join(str(x) for x in a))


def V(p):
    return unreal.Vector(float(p[0]), float(p[1]), float(p[2]))


def rot_from(fwd, up=None):
    f = V(fwd)
    if up is None or abs(f.dot(V(up))) > 0.99:
        up = (0, 0, 1) if abs(fwd[2]) < 0.99 else (1, 0, 0)
    return unreal.MathLibrary.make_rot_from_xz(f, V(up))


def srgb8(c):
    m = max(c) or 1.0
    enc = lambda x: 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
    r, g, b = [int(round(255 * max(0.0, min(1.0, enc(x / m))))) for x in c[:3]]
    return unreal.Color(r=r, g=g, b=b, a=255), m


def comp(actor, cls):
    return actor.get_component_by_class(cls)


def spawn(cls, loc, rot=None, label=None, folder=None):
    a = EAS.spawn_actor_from_class(cls, V(loc), rot or unreal.Rotator(0, 0, 0))
    if label:
        a.set_actor_label(label)
    if folder:
        a.set_folder_path(folder)
    a.tags = [unreal.Name("nik")]
    return a


FOLDER = {"lightmap": "Room/Architecture", "vertex": "Room/Furniture", "none": "Room/Glass_Emitters"}


def spawn_meshes(objects):
    n = 0
    for o in objects:
        sm = unreal.load_asset(GAME + "/Meshes/" + o["name"])
        if sm is None:
            log("WARN no mesh", o["name"])
            continue
        a = EAS.spawn_actor_from_object(sm, V(o["location"]), unreal.Rotator(0, 0, 0))
        a.set_actor_label(o["name"][3:])
        a.set_folder_path("Chandelier" if o["name"].startswith("SM_Chandelier") else
                          "Room/Hero" if o["bake"] is None else FOLDER.get(o["bake"], "Room"))
        a.tags = [unreal.Name("nik")]
        comp(a, unreal.StaticMeshComponent).set_mobility(unreal.ComponentMobility.STATIC)
        n += 1
    return n


def look_through(pid):
    """editor viewport at a client-render camera"""
    c = SCENE["cameras"][pid]
    f = c["forward"]
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
        V(c["location"]), unreal.Rotator(0, 0, math.degrees(math.atan2(f[1], f[0]))))


def start():
    """fresh level with everything but the meshes: lights, sky, cameras, post process"""
    # the level is created by prepare.py (commandlet) and opened as the editor startup map: no level switching
    # from Python while the editor ticks
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world is None or world.get_path_name().split(".")[0] != LEVEL:
        LES.load_level(LEVEL)
    for a in EAS.get_all_level_actors():
        if unreal.Name("nik") in a.tags:
            EAS.destroy_actor(a)
    log("level", LEVEL)
    # ------------------------------------------------------------------ lights
    IES = {}
    suns = []
    counts = {}
    for L in SCENE["lights"]:
        t = L["type"]
        if t == "SUN":
            suns.append(L)
            continue
        color, cm = srgb8(L["color"])
        folder = "Lights/" + L["group"]
        if t == "AREA":
            a = spawn(unreal.RectLight, L["location"], rot_from(L["forward"], L["up"]), L["name"], folder)
            c = comp(a, unreal.RectLightComponent)
            c.set_editor_property("intensity_units", unreal.LightUnits.CANDELAS)
            c.set_editor_property("intensity", L["watts"] * cm / math.pi * PHOT)
            c.set_editor_property("source_width", max(0.5, L["size"] * 100))
            c.set_editor_property("source_height", max(0.5, L["sizeY"] * 100))
            if L.get("spread", 180) < 170:
                c.set_editor_property("barn_door_angle", max(5.0, L["spread"] / 2))
                c.set_editor_property("barn_door_length", 20.0)
        else:
            a = spawn(unreal.PointLight, L["location"], rot_from(L["forward"], L["up"]), L["name"], folder)
            c = comp(a, unreal.PointLightComponent)
            c.set_editor_property("intensity_units", unreal.LightUnits.CANDELAS)
            c.set_editor_property("intensity", L["watts"] * cm / (4 * math.pi) * PHOT)
            c.set_editor_property("source_radius", max(0.5, L["radius"] * 100))
            if L.get("ies"):
                key = "IES_" + slug(os.path.splitext(os.path.basename(L["ies"]))[0])
                prof = IES.setdefault(key, unreal.load_asset(GAME + "/IES/" + key))
                if prof:
                    c.set_editor_property("ies_texture", prof)
                    c.set_editor_property("use_ies_brightness", False)
        c.set_editor_property("light_color", color)
        c.set_editor_property("attenuation_radius", 3000.0)
        c.set_editor_property("cast_shadows", True)
        c.set_mobility(unreal.ComponentMobility.MOVABLE)
        counts[t] = counts.get(t, 0) + 1
    log("lights", counts, "ies profiles", {k: bool(v) for k, v in IES.items()})

    # daylight: the strongest Corona sun drives the atmosphere, the others fill like in the Corona LightMix
    suns.sort(key=lambda s: -s["watts"])
    for i, L in enumerate(suns):
        color, cm = srgb8(L["color"])
        a = spawn(unreal.DirectionalLight, L["location"], rot_from(L["forward"]), L["name"], "Lights/env")
        c = comp(a, unreal.DirectionalLightComponent)
        c.set_editor_property("intensity", L["watts"] * cm * PHOT)
        c.set_editor_property("light_color", color)
        c.set_editor_property("light_source_angle", max(0.53, L.get("angle", 0.53)))
        c.set_editor_property("atmosphere_sun_light", i < 2)
        c.set_editor_property("atmosphere_sun_light_index", i if i < 2 else 0)
        c.set_mobility(unreal.ComponentMobility.MOVABLE)
    spawn(unreal.SkyAtmosphere, (0, 0, 0), label="SkyAtmosphere", folder="Lights/env")
    sky = spawn(unreal.SkyLight, (0, 0, 400), label="SkyLight", folder="Lights/env")
    sc = comp(sky, unreal.SkyLightComponent)
    sc.set_editor_property("real_time_capture", True)
    sc.set_mobility(unreal.ComponentMobility.MOVABLE)
    sc.set_editor_property("intensity", float(SCENE.get("envStrength", 1.0)))
    log("suns", len(suns))

    # ------------------------------------------------------------------ cameras of the client renders
    for pid, c in SCENE["cameras"].items():
        f = c["forward"]
        yaw = math.degrees(math.atan2(f[1], f[0]))
        a = spawn(unreal.CineCameraActor, c["location"], unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw),
                  "Cam_%s" % pid, "Cameras")
        cc = a.get_cine_camera_component()
        fb = cc.get_editor_property("filmback")
        fb.set_editor_property("sensor_width", c["sensor"][0])
        fb.set_editor_property("sensor_height", c["sensor"][1])
        fb.set_editor_property("sensor_vertical_offset", c["shiftMm"])  # Corona two-point perspective
        cc.set_editor_property("filmback", fb)
        cc.set_editor_property("current_focal_length", c["lens"])
        fs = cc.get_editor_property("focus_settings")
        fs.set_editor_property("focus_method", unreal.CameraFocusMethod.DISABLE)
        cc.set_editor_property("focus_settings", fs)
        if c.get("near"):
            cc.set_editor_property("override_custom_near_clipping_plane", True)
            cc.set_editor_property("custom_near_clipping_plane", c["near"])
        cc.set_editor_property("constrain_aspect_ratio", True)
        log("camera", pid, c["corona"], "yaw %.1f lens %.1f" % (yaw, c["lens"]))

    # walking start: where render 10 stands
    spawn(unreal.PlayerStart, SCENE["cameras"]["10"]["location"], unreal.Rotator(0, 0, math.degrees(math.atan2(
        SCENE["cameras"]["10"]["forward"][1], SCENE["cameras"]["10"]["forward"][0]))), "PlayerStart")

    # ------------------------------------------------------------------ post process (Corona tone mapping, Lumen quality)
    pp = spawn(unreal.PostProcessVolume, (0, 0, 0), label="PP_Corona", folder="Lights")
    pp.set_editor_property("unbound", True)
    s = pp.settings


    def put(name, value):
        try:
            s.set_editor_property("override_" + name, True)
        except Exception:
            pass
        s.set_editor_property(name, value)


    put("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
    put("auto_exposure_apply_physical_camera_exposure", False)
    put("auto_exposure_bias", EXPOSURE_BIAS)
    put("white_temp", WHITE_TEMP)
    put("bloom_intensity", 0.35)
    put("bloom_threshold", 1.5)
    put("vignette_intensity", 0.25)
    put("lumen_final_gather_quality", 2.0)
    put("lumen_scene_lighting_quality", 2.0)
    put("lumen_scene_detail", 2.0)
    put("lumen_reflection_quality", 2.0)
    put("lumen_max_trace_distance", 20000.0)
    put("lumen_scene_view_distance", 20000.0)
    put("path_tracing_max_bounces", 32)
    put("path_tracing_samples_per_pixel", 2048)
    put("path_tracing_enable_denoiser", True)
    put("motion_blur_amount", 0.0)
    pp.settings = s
    log("exposure bias %.2f" % EXPOSURE_BIAS)
    look_through("10")


def finish():
    unreal.EditorLoadingAndSavingUtils.save_current_level()
    log("level saved")


if __name__ == "__main__":
    start()
    log("mesh actors", spawn_meshes(SCENE["objects"]))
    finish()
    if os.environ.get("NIK_QUIT") == "1":
        unreal.SystemLibrary.quit_editor()
