"""Frames from the client-render cameras (Cam_030 / 08 / 10 / 12 / 28) for the comparison with the Corona renders.

In the open editor (Output Log, Python):  exec(open(r"<this file>").read())
Lumen frames at the render resolution go to build/ue/frames/<view>.png. NIK_VIEWS="10,12" picks views; the first
frame waits NIK_SETTLE seconds (Lumen / virtual textures / shaders settle), then one view every 6 s.
"""
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else
                os.environ.get("NIK_PIPELINE", os.path.join(os.environ.get("NIK_ROOT", ""), "pipeline", "unreal")))
from nik_ue import SCENE, UE_DIR  # noqa: E402

OUT = os.path.join(UE_DIR, "frames")
os.makedirs(OUT, exist_ok=True)
views = [v for v in os.environ.get("NIK_VIEWS", ",".join(SCENE["cameras"])).split(",") if v]
cams = {a.get_actor_label(): a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        if isinstance(a, unreal.CineCameraActor)}
st = {"t": 0.0, "next": float(os.environ.get("NIK_SETTLE", "20")), "i": 0, "done": False}
DONE = os.path.join(OUT, "DONE")
if os.path.exists(DONE):
    os.remove(DONE)
# each shot renders 60 frames first: Lumen, MegaLights and TSR need their history (one frame is pure noise)
unreal.SystemLibrary.execute_console_command(None, "r.HighResScreenshotDelay 60")


def tick(dt):
    if st["done"]:
        return
    st["t"] += dt
    if st["t"] < st["next"]:
        return
    if st["i"] >= len(views):
        st["done"] = True  # (unregistering from inside the callback is avoided, see run_live.py)
        open(DONE, "w").write(",".join(views))
        unreal.log("NIK frames done -> " + OUT)
        return
    pid = views[st["i"]]
    cam = cams.get("Cam_" + pid)
    w, h = SCENE["cameras"][pid]["resolution"]
    if cam:
        unreal.AutomationLibrary.take_high_res_screenshot(w, h, os.path.join(OUT, pid + ".png"), camera=cam)
        unreal.log("NIK frame " + pid)
    st["i"] += 1
    st["next"] = st["t"] + 6.0


st["h"] = unreal.register_slate_post_tick_callback(tick)
