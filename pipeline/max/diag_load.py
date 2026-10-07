# Diagnostics: what the .max file declares vs. what actually loads.
import os
import time

from pymxs import runtime as rt

OUT = os.environ["NIK_OUT"]
MAXF = os.environ["NIK_MAX"]
f = open(os.path.join(OUT, "diag_load.txt"), "w", encoding="utf-8")


def w(*a):
    f.write(" ".join(str(x) for x in a) + "\n")
    f.flush()


names = rt.getMAXFileObjectNames(MAXF, quiet=True)
w("getMAXFileObjectNames:", len(names) if names is not None else None)
for n in list(names or [])[:40]:
    w("  ", n)

rt.resetMaxFile(rt.Name("noPrompt"))
t = time.time()
ok = rt.loadMaxFile(MAXF, useFileUnits=True, quiet=True, missingExtFilesAction=rt.Name("logmsg"),
                    missingDLLsAction=rt.Name("logmsg"), missingXRefsAction=rt.Name("logmsg"))
w("loadMaxFile ok=", ok, "secs=", round(time.time() - t, 1))
w("objects=", rt.objects.count, "geometry=", rt.geometry.count, "lights=", rt.lights.count,
  "cameras=", rt.cameras.count, "rootChildren=", rt.rootNode.children.count)
w("units", rt.units.SystemType, rt.units.SystemScale)
w("layers", rt.LayerManager.count)
w("xrefScenes", rt.xrefs.getXRefFileCount())
w("containers", len(list(rt.getClassInstances(rt.Container))))
try:
    for i in range(1, rt.fileProperties.getNumProperties(rt.Name("contents")) + 1):
        w("contents:", rt.fileProperties.getPropertyName(rt.Name("contents"), i), "=",
          rt.fileProperties.getPropertyValue(rt.Name("contents"), i))
except Exception as e:
    w("fileProperties err", e)
f.close()
