"""Calibration captures in the open editor: every light group alone, as linear HDR (EXR), from the render cameras.

Plan: build/ue/frames/calib/plan.json  {"views": ["10", ...], "configs": [{"name": "kitchen", "gains": {...}}, ...],
                                       "png": ["all"]}   (configs listed in "png" also get the tone-mapped PNG)
Out: build/ue/frames/calib/<config>_<view>.exr (+ .png), DONE when finished. Gains are reset to 1 at the end.
Run by remote execution / Python console with NIK_PIPELINE set (see render_views.py).
"""
import json
import os
import sys

import unreal

sys.path.insert(0, os.environ.get("NIK_PIPELINE", os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ""))
import nik_light  # noqa: E402
from nik_ue import SCENE, UE_DIR  # noqa: E402

OUT = os.path.join(UE_DIR, "frames", "calib")
PLAN = json.load(open(os.path.join(OUT, "plan.json")))
DONE = os.path.join(OUT, "DONE")
if os.path.exists(DONE):
    os.remove(DONE)
unreal.SystemLibrary.execute_console_command(None, "r.HighResScreenshotDelay 60")
# linear captures: tone mapper off, exposure 6 EV down (no clipping; x64 = the normal exposure)
LINEAR_EV = 6.0
pp = [a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
      if isinstance(a, unreal.PostProcessVolume)][0]
BIAS = pp.settings.auto_exposure_bias


def linear(on):
    s = pp.settings
    s.set_editor_property("auto_exposure_bias", BIAS - LINEAR_EV if on else BIAS)
    pp.settings = s
    unreal.SystemLibrary.execute_console_command(None, "ShowFlag.Tonemapper %d" % (0 if on else 1))


linear(True)
cams = {a.get_actor_label(): a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        if isinstance(a, unreal.CineCameraActor)}

steps = []
for cfg in PLAN["configs"]:
    steps.append(("gains", cfg["gains"]))
    for pid in PLAN["views"]:
        steps.append(("shot", pid, cfg["name"], True))
        if cfg["name"] in PLAN.get("png", []):
            steps.append(("shot", pid, cfg["name"], False))
steps.append(("gains", {}))
st = {"i": 0, "wait": 1.0, "done": False, "file": None, "t": 0.0}


def tick(dt):
    if st["done"]:
        return
    if st["file"]:
        # the next request would cancel this one: wait until the frame is on disk (warm-up at a few fps takes ~10 s)
        st["t"] += dt
        if not os.path.exists(st["file"]) and st["t"] < 90:
            return
        unreal.log("NIK calib %s after %.1fs" % ("got" if os.path.exists(st["file"]) else "TIMEOUT", st["t"]))
        st["file"] = None
    st["wait"] -= dt
    if st["wait"] > 0:
        return
    if st["i"] >= len(steps):
        st["done"] = True
        linear(False)
        open(DONE, "w").write("ok")
        unreal.log("NIK calib done")
        return
    s = steps[st["i"]]
    st["i"] += 1
    unreal.log("NIK calib step %d/%d %s" % (st["i"], len(steps), s[:3]))
    if s[0] == "gains":
        nik_light.set_gains(s[1])
        st["wait"] = 2.0
    else:
        _, pid, name, hdr = s
        w, h = SCENE["cameras"][pid]["resolution"]
        path = os.path.join(OUT, "%s_%s.%s" % (name, pid, "exr" if hdr else "png"))
        if os.path.exists(path):
            os.remove(path)
        unreal.AutomationLibrary.take_high_res_screenshot(w // 2, h // 2, path, camera=cams["Cam_" + pid],
                                                          capture_hdr=hdr)
        st["file"], st["t"], st["wait"] = path, 0.0, 0.5


unreal.register_slate_post_tick_callback(tick)
