"""Trace the ELEKTROMIX. logotype bitmap into two SVG groups (black / orange).

The source scan has three flat colours (near-white paper, black ink, #FB6100
orange ink), so a luma threshold plus a hue test separates the two ink groups
cleanly. Each group is written to its own SVG so the renderer can give them
different materials.

    python3 trace.py [source.jpg]
"""
import os
import sys

import numpy as np
import potrace
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    HERE, 'source', 'elektromix_logo.jpg')

im = Image.open(SRC).convert('RGB')
# crop off the photographed paper edge (a few dark pixels along the border)
im = im.crop((4, 4, im.width - 4, im.height - 4))
a = np.asarray(im).astype(np.int16)
R, G, B = a[..., 0], a[..., 1], a[..., 2]
luma = 0.299 * R + 0.587 * G + 0.114 * B

# paper is ~249 grey, ink is 0 or #FB6100 -> threshold at the midpoint
ink = luma < 140
# orange: strong red, mid green, low blue ("MIX"; the trailing period is black)
orange = ink & (R > 150) & (G > 40) & (G < 190) & (B < 120) & ((R - B) > 90)
black = ink & ~orange


def clean(mask, iters=1):
    """Open the mask to drop the JPEG speckle that rings the ink edges."""
    m = mask.copy()
    for _ in range(iters):
        p = np.pad(m, 1, constant_values=False)
        m = p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    for _ in range(iters):
        p = np.pad(m, 1, constant_values=False)
        m = p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    return m


black = clean(black)
orange = clean(orange)
print('black px', black.sum(), 'orange px', orange.sum())

H, W = black.shape


def trace(mask, name):
    # potracer thresholds non-bool data against 255*blacklevel and then inverts,
    # so hand it a bool array with ink=False to get ink as the traced foreground.
    bmp = potrace.Bitmap(~mask)
    path = bmp.trace(turdsize=12, alphamax=1.0, opttolerance=0.2,
                     turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
    d = []
    n = 0
    for curve in path:
        n += 1
        s = curve.start_point
        d.append(f'M{s.x:.2f},{s.y:.2f}')
        for seg in curve:
            e = seg.end_point
            if seg.is_corner:
                c = seg.c
                d.append(f'L{c.x:.2f},{c.y:.2f}L{e.x:.2f},{e.y:.2f}')
            else:
                d.append(f'C{seg.c1.x:.2f},{seg.c1.y:.2f} '
                         f'{seg.c2.x:.2f},{seg.c2.y:.2f} {e.x:.2f},{e.y:.2f}')
        d.append('Z')
    print(f'{name}: {n} contours')
    return ''.join(d)


d_black = trace(black, 'black')     # 7 letters + period + 2 counters = 10
d_orange = trace(orange, 'orange')

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<g id="ink_black" fill="#000000" fill-rule="evenodd"><path d="{d_black}"/></g>
<g id="ink_orange" fill="#f5670a" fill-rule="evenodd"><path d="{d_orange}"/></g>
</svg>'''
with open(os.path.join(HERE, 'logo_traced.svg'), 'w') as f:
    f.write(svg)

# separate files so the Blender import keeps the two colour groups apart
for name, dd, col in (('black', d_black, '#000000'), ('orange', d_orange, '#fb6100')):
    with open(os.path.join(HERE, f'logo_{name}.svg'), 'w') as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
                f'viewBox="0 0 {W} {H}"><path fill="{col}" fill-rule="evenodd" '
                f'd="{dd}"/></svg>')
print('wrote SVGs', W, H)
