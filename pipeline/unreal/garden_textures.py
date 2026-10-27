"""Procedural, seamless garden textures (no downloads): mown lawn, macro variation, clipped-hedge leaves.

python garden_textures.py <out dir>
  lawn_bc.png / lawn_n.png      2048 px = 1.5 m: short blades seen from above (sRGB albedo / OpenGL normal)
  macro.png                     512 px tileable greyscale noise (patches of slightly drier grass, ~30 m)
  hedge_bc.png / hedge_n.png    2048 px = 0.6 m: opaque layered leaves, dark gaps (an opaque Nanite surface needs no alpha)
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
S = 2048
rng = np.random.default_rng(5)


def save_rgb(a, name):
    Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8), "RGB").save(os.path.join(OUT, name))


def normal_from_height(h, strength):
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * strength
    dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * strength
    n = np.dstack([-dx, dy, np.ones_like(h)])  # OpenGL: +Y up in the image
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n * 0.5 + 0.5


def blur_wrap(a, r):
    """gaussian blur that wraps (the textures tile)"""
    pad = int(r * 3) + 1
    big = np.pad(a, ((pad, pad), (pad, pad)) + ((0, 0),) * (a.ndim - 2), mode="wrap")
    im = Image.fromarray(np.clip(big * 255, 0, 255).astype(np.uint8))
    im = im.filter(ImageFilter.GaussianBlur(r))
    return np.asarray(im, np.float32)[pad:-pad, pad:-pad] / 255.0


def fft_noise(n, beta, seed):
    """tileable 1/f^beta noise in 0..1"""
    r = np.random.default_rng(seed)
    f = np.fft.fftfreq(n)
    fx, fy = np.meshgrid(f, f)
    k = np.sqrt(fx * fx + fy * fy)
    k[0, 0] = 1.0
    spec = (r.normal(size=(n, n)) + 1j * r.normal(size=(n, n))) / k ** (beta / 2)
    spec[0, 0] = 0
    a = np.real(np.fft.ifft2(spec))
    a = (a - a.min()) / (a.max() - a.min())
    return a.astype(np.float32)


# ------------------------------------------------------------------ macro noise
macro = fft_noise(512, 2.2, 1)
Image.fromarray((macro * 255).astype(np.uint8), "L").save(os.path.join(OUT, "macro.png"))

# ------------------------------------------------------------------ lawn: blades from above
img = np.zeros((S, S, 3), np.float32)
hgt = np.zeros((S, S), np.float32)
base = fft_noise(S, 2.6, 2)
img[:] = np.array([0.10, 0.20, 0.05]) * (0.7 + 0.6 * base[..., None])  # the soil-ish shade between blades
pal_root = np.array([0.07, 0.15, 0.04])
pal_mid = np.array([0.16, 0.30, 0.07])
pal_tip = np.array([0.30, 0.45, 0.11])
N_BLADES = 105000
CH = 8000
for c0 in range(0, N_BLADES, CH):
    n = min(CH, N_BLADES - c0)
    x0 = rng.uniform(0, S, n)
    y0 = rng.uniform(0, S, n)
    ang = rng.uniform(0, 2 * np.pi, n)
    L = rng.uniform(26, 58, n)
    curl = rng.uniform(-0.9, 0.9, n)
    bright = rng.uniform(0.75, 1.25, n)
    tint = rng.uniform(0.0, 1.0, n)  # yellower <-> bluer green
    K = 14
    t = np.linspace(0, 1, K)[None, :]
    a = ang[:, None] + curl[:, None] * t * 0.9
    xs = x0[:, None] + np.cos(a) * L[:, None] * t
    ys = y0[:, None] + np.sin(a) * L[:, None] * t
    col = np.where(t[..., None] < 0.5, pal_root + (pal_mid - pal_root) * (t[..., None] / 0.5),
                   pal_mid + (pal_tip - pal_mid) * ((t[..., None] - 0.5) / 0.5))
    col = col * bright[:, None, None]
    col[..., 0] *= 0.85 + 0.3 * tint[:, None]
    col[..., 2] *= 1.15 - 0.3 * tint[:, None]
    hh = (0.25 + 0.75 * t) * np.ones((n, 1)) * rng.uniform(0.7, 1.0, n)[:, None]
    for off in (-1, 0, 1):  # blade width 3 px
        px = np.mod((xs + off * np.sin(a)).astype(np.int64), S).ravel()
        py = np.mod((ys - off * np.cos(a)).astype(np.int64), S).ravel()
        img[py, px] = col.reshape(-1, 3)
        hgt[py, px] = hh.ravel()
img = np.clip(img, 0, 1)
hgt = blur_wrap(hgt, 1.2)
# tone: mean a clean mown-lawn green
mean = img.reshape(-1, 3).mean(0)
img *= np.array([0.30, 0.50, 0.14]) / np.maximum(mean, 1e-4) * 0.68
save_rgb(np.clip(img, 0, 1) ** (1 / 2.2), "lawn_bc.png")  # stored sRGB
save_rgb(normal_from_height(hgt, 5.0), "lawn_n.png")

# ------------------------------------------------------------------ hedge leaves: layered, opaque
LW, LH = 112, 54  # a laurel/boxwood leaf ~33 x 16 mm at 0.29 mm/px


def leaf_sprite():
    """RGBA colour sprite (shaded leaf with a vein) and its height sprite"""
    W, H = LW * 2, LH * 2  # drawn at 2x, shrunk for antialiasing
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    u = (xx / W) * 2 - 1  # -1..1 along the leaf
    v = (yy / H) * 2 - 1
    # outline: pointed ellipse
    half = np.clip(1 - np.abs(u) ** 1.6, 0, 1) ** 0.7 * 0.95
    inside = np.abs(v) < half
    alpha = inside.astype(np.float32)
    shade = 0.62 + 0.38 * (1 - np.abs(v) / np.maximum(half, 1e-3)).clip(0, 1) ** 0.6  # rounded: lighter centre
    vein = (np.abs(v) < 0.035 * (1 - np.abs(u))) * 0.22
    sheen = np.exp(-((u + 0.25) ** 2 * 6 + (v + 0.2) ** 2 * 14)) * 0.18
    g = np.clip((shade + vein + sheen) * 0.85, 0, 1) * alpha  # uint8 below: values above 1 would wrap to black
    rgb = np.dstack([g, g, g])
    dome = (1 - np.abs(v) / np.maximum(half, 1e-3)).clip(0, 1) ** 0.5 * alpha
    cs = Image.fromarray((np.dstack([rgb, alpha]) * 255).astype(np.uint8), "RGBA").resize((LW, LH), Image.LANCZOS)
    hs = Image.fromarray((dome * 255).astype(np.uint8), "L").resize((LW, LH), Image.LANCZOS)
    return cs, hs


spr_c, spr_h = leaf_sprite()
spr_a = spr_c.split()[3]
spr_g = spr_c.split()[0]
col_canvas = Image.new("RGB", (S, S), (11, 20, 8))
hgt_canvas = Image.new("L", (S, S), 0)
PASSES = 7
PER_PASS = 900
leaf_dark = np.array([16, 38, 14])
leaf_main = np.array([36, 80, 26])
leaf_new = np.array([84, 128, 38])  # young growth
for p in range(PASSES):
    k = p / (PASSES - 1)
    for _ in range(PER_PASS):
        cx, cy = rng.uniform(0, S, 2)
        a = rng.uniform(0, 360)
        sc = rng.uniform(0.8, 1.15)
        w, h = int(LW * sc), int(LH * sc)
        tint = leaf_main + (leaf_new - leaf_main) * (rng.random() ** 3) * (0.35 + 0.65 * k)
        tint = leaf_dark + (tint - leaf_dark) * (0.35 + 0.65 * k)  # deeper layers darker
        tint = tint * rng.uniform(0.85, 1.12)
        col = Image.merge("RGB", [spr_g.point(lambda v, c=float(tint[i]): int(min(255, v * c / 200.0 * 1.55)))
                                  for i in range(3)]).resize((w, h), Image.LANCZOS)
        al = spr_a.resize((w, h), Image.LANCZOS)
        hh = spr_h.point(lambda v, f=0.55 + 0.45 * k: int(v * f * 0.45 + 255 * (0.12 + 0.88 * k) * 0.55)).resize((w, h),
                                                                                                         Image.LANCZOS)
        rc, ra, rh = (col.rotate(a, expand=True, resample=Image.BICUBIC), al.rotate(a, expand=True, resample=Image.BICUBIC),
                      hh.rotate(a, expand=True, resample=Image.BICUBIC))
        for ox in (-S, 0, S):
            for oy in (-S, 0, S):
                px, py = int(cx - rc.width / 2) + ox, int(cy - rc.height / 2) + oy
                if px > S or py > S or px + rc.width < 0 or py + rc.height < 0:
                    continue
                col_canvas.paste(rc, (px, py), ra)
                hgt_canvas.paste(rh, (px, py), ra)
col_a = np.asarray(col_canvas, np.float32) / 255.0
# slight ambient occlusion from the height field: gaps and under-leaf shadow darker
hg = np.asarray(hgt_canvas, np.float32) / 255.0
ao = 0.55 + 0.45 * np.clip((hg - blur_wrap(hg, 7.0)) * 6 + 0.6, 0, 1)
col_a *= ao[..., None]
save_rgb(np.clip(col_a, 0, 1), "hedge_bc.png")  # the leaf palette is already sRGB
save_rgb(normal_from_height(blur_wrap(hg, 1.0), 3.5), "hedge_n.png")
m = col_a.reshape(-1, 3).mean(0)
print("textures ->", OUT, "lawn mean (linear)", np.round(mean, 3), "hedge mean (linear)", np.round(m, 3))
