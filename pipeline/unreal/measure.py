"""Average sRGB of the same regions in the Unreal frame (build/ue/frames/<view>.png) and the Corona render.

python measure.py [views]   -> per region: ref, ours, ratio (linear, per channel)
Regions are in render pixels (the frames are captured at the render resolution); 10 / 12 come from web/src/dev/measure.ts.
"""
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
FRAMES = os.path.join(ROOT, "build", "ue", "frames")
REF = {"030": "030", "08": "8", "10": "10", "12": "12", "28": "28"}
REGIONS = {
    "10": {"wallR": [870, 650, 1050, 900], "ceiling": [500, 60, 800, 200], "floor": [100, 1350, 400, 1550],
           "island": [200, 1000, 330, 1150], "seat": [690, 1040, 800, 1080], "niche": [80, 720, 330, 900],
           "wallL": [0, 500, 60, 900]},
    "12": {"ceiling": [300, 50, 800, 300], "wallL": [20, 350, 150, 650], "hallWall": [720, 640, 980, 760],
           "hallRoof": [420, 600, 700, 700], "island": [300, 1150, 650, 1350], "floor": [300, 1420, 800, 1550],
           "hallFloor": [900, 1200, 1100, 1300]},
    "28": {"roof": [300, 150, 1100, 450], "wallL": [60, 700, 250, 1000], "chairs": [250, 1150, 1150, 1350],
           "floor": [200, 1650, 1200, 1950], "backWall": [550, 850, 850, 1000]},
    "030": {"wallBack": [700, 300, 1100, 600], "island": [900, 950, 1200, 1250], "floor": [100, 1250, 700, 1400],
            "niche": [100, 450, 300, 800], "hall": [1500, 600, 1900, 900]},
    "08": {"wallL": [50, 500, 300, 1000], "niche": [700, 850, 1100, 1050], "floor": [300, 1700, 1100, 1950],
           "ceiling": [400, 50, 1000, 250], "seat": [500, 1250, 900, 1350]},
}


def lin(x):
    x = x / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def ref_image(pid):
    d = os.path.join(ROOT, "3DMAX", "JPG")
    f = [x for x in os.listdir(d) if x.startswith(REF[pid] + "_") and "copy." in x][0]
    return Image.open(os.path.join(d, f)).convert("RGB")


def measure(pid):
    ours = Image.open(os.path.join(FRAMES, pid + ".png")).convert("RGB")
    ref = ref_image(pid)
    if ours.size != ref.size:
        ours = ours.resize(ref.size, Image.LANCZOS)
    a, r = np.asarray(ours, np.float32), np.asarray(ref, np.float32)
    out = {}
    for name, (x0, y0, x1, y1) in REGIONS[pid].items():
        oa, ra = a[y0:y1, x0:x1].reshape(-1, 3), r[y0:y1, x0:x1].reshape(-1, 3)
        out[name] = (ra.mean(0), oa.mean(0), lin(ra).mean(0) / np.maximum(lin(oa).mean(0), 1e-4))
    return out


if __name__ == "__main__":
    allr = []
    for pid in (sys.argv[1].split(",") if len(sys.argv) > 1 else REGIONS):
        print("==", pid)
        for name, (ref, ours, ratio) in measure(pid).items():
            allr.append(ratio)
            print("  %-9s ref %s ours %s  ref/ours lin %s" % (name, np.round(ref).astype(int), np.round(ours).astype(int),
                                                           np.round(ratio, 2)))
    g = np.exp(np.log(np.array(allr)).mean(0))
    print("geometric mean ref/ours (linear):", np.round(g, 3), "-> EV %.2f" % np.log2(g.mean()))
