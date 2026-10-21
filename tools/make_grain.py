#!/usr/bin/env python3
"""Lift the film grain out of a flat, dark patch of a photo into a tile for the theme.

usage: make_grain.py PHOTO OUT.png [x y size] [bg_luma] [strength] [radius]
The grain is the photo minus a lightly blurred copy of itself (radius px), so only
the finest speckle and clumps stay and slow shading or texture is left behind. Light grain becomes white
pixels and dark grain black pixels, each with just enough alpha to shift a
background of bg_luma by the same amount the photo shifts, so the tile laid over
the app reproduces the photo's grain at the same strength and clump size.
"""
import sys
import numpy as np
from PIL import Image, ImageFilter

photo, out = sys.argv[1], sys.argv[2]
x, y, size = (int(v) for v in sys.argv[3:6]) if len(sys.argv) > 5 else (1200, 1700, 256)
bg = float(sys.argv[6]) if len(sys.argv) > 6 else 32.0
strength = float(sys.argv[7]) if len(sys.argv) > 7 else 1.0
radius = float(sys.argv[8]) if len(sys.argv) > 8 else 1.2

im = Image.open(photo).convert("L")
pad = 16
patch = im.crop((x - pad, y - pad, x + size + pad, y + size + pad))
smooth = patch.filter(ImageFilter.GaussianBlur(radius))
n = (np.asarray(patch, float) - np.asarray(smooth, float))[pad:-pad, pad:-pad]
n = (n - n.mean()) * strength
light = n > 0
alpha = np.where(light, n / (255.0 - bg), -n / bg)
rgba = np.zeros((size, size, 2), np.uint8)
rgba[..., 0] = np.where(light, 255, 0)
rgba[..., 1] = np.clip(alpha * 255, 0, 160).round()
Image.fromarray(rgba, "LA").save(out, optimize=True)
print(f"grain std {n.std():.2f} levels, patch mean {np.asarray(patch, float).mean():.1f}, wrote {out}")
