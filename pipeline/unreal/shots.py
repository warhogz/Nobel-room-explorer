"""Frames from temporary cameras, independent of the editor viewport (so the user can keep flying around).

build/ue/frames/shots.json: [{"name": "gv1", "loc": [x, y, z], "pitch": 0, "yaw": -50, "lens": 18, "size": [1600, 900]}, ...]
Run in the open editor (remote execution, NIK_PIPELINE set). Writes <name>.png; build/ue/frames/SHOTS_DONE at the end.
"""
import json
import os

import unreal

F = "C:/Users/hdog/Downloads/Telegram Desktop/NOBEL ISLAND KITCHEN (2)/NOBEL ISLAND KITCHEN/build/ue/frames"
PLAN = json.load(open(F + "/shots.json"))
DONE = F + "/SHOTS_DONE"
if os.path.exists(DONE):
    os.remove(DONE)
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
unreal.SystemLibrary.execute_console_command(None, "r.HighResScreenshotDelay 60")
cams = []
for s in PLAN:
    c = EAS.spawn_actor_from_class(unreal.CineCameraActor, unreal.Vector(*s["loc"]), unreal.Rotator(0, s.get("pitch", 0), s["yaw"]))
    c.set_actor_label("TmpShot_" + s["name"])
    cc = c.get_cine_camera_component()
    cc.set_editor_property("current_focal_length", s.get("lens", 18.0))
    fs = cc.get_editor_property("focus_settings")
    fs.set_editor_property("focus_method", unreal.CameraFocusMethod.DISABLE)
    cc.set_editor_property("focus_settings", fs)
    cams.append(c)
st = {"i": 0, "file": None, "t": 0.0, "done": False}


def tick(dt):
    if st["done"]:
        return
    if st["file"]:
        st["t"] += dt
        if not os.path.exists(st["file"]) and st["t"] < 120:
            return
        st["file"] = None
    if st["i"] >= len(PLAN):
        st["done"] = True
        for c in cams:
            EAS.destroy_actor(c)
        open(DONE, "w").write("ok")
        return
    s, c = PLAN[st["i"]], cams[st["i"]]
    st["i"] += 1
    p = "%s/%s.png" % (F, s["name"])
    if os.path.exists(p):
        os.remove(p)
    w, h = s.get("size", [1600, 900])
    unreal.AutomationLibrary.take_high_res_screenshot(w, h, p, camera=c)
    st["file"], st["t"] = p, 0.0


unreal.register_slate_post_tick_callback(tick)
