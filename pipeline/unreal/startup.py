"""Project startup script (DefaultEngine.ini: PythonScriptPluginSettings.StartupScripts).

-ExecutePythonScript quits the editor once its script returns, so the live build is requested with a flag file
instead: build/ue/LIVE_BUILD present -> it is removed and run_live.py builds the room in this editor session.
"""
import os
import sys

HERE = r"C:/Users/hdog/Downloads/Telegram Desktop/NOBEL ISLAND KITCHEN (2)/NOBEL ISLAND KITCHEN/pipeline/unreal"
FLAG = os.path.join(HERE, "..", "..", "build", "ue", "LIVE_BUILD")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if os.path.exists(FLAG):
    os.remove(FLAG)
    import run_live  # noqa: F401,E402  (registers its tick callback)
