"""Sample a render's ink pixels and compare against the brand colours."""
import sys
import numpy as np
from PIL import Image

TARGET_ORANGE = np.array([251, 97, 0])

for path in sys.argv[1:]:
    a = np.asarray(Image.open(path).convert('RGB')).astype(int)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    # orange front faces: saturated warm pixels, ignoring near-white highlights
    om = (R > 140) & ((R - B) > 70) & ((R - G) > 45) & (G < 210)
    if om.sum():
        med = np.median(a[om], axis=0)
        hue_ratio = med[1] / max(med[0], 1)
        print(f'{path}')
        print(f'  orange px {om.sum():>7}  median RGB {med.astype(int)} '
              f'  G/R {hue_ratio:.3f} (target {97/251:.3f})')
        print(f'  p10/p90 R {np.percentile(a[om][:,0],10):.0f}/'
              f'{np.percentile(a[om][:,0],90):.0f}  '
              f'G {np.percentile(a[om][:,1],10):.0f}/{np.percentile(a[om][:,1],90):.0f}')
        clipped = ((a[om] >= 254).all(axis=1)).mean()
        print(f'  fully-clipped share {clipped*100:.1f}%')
    # black front faces: dark neutral pixels
    bm = (R < 90) & (abs(R - G) < 14) & (abs(G - B) < 16)
    if bm.sum():
        print(f'  black  px {bm.sum():>7}  median RGB '
              f'{np.median(a[bm], axis=0).astype(int)}')
    print(f'  frame mean luma {(0.299*R + 0.587*G + 0.114*B).mean():.1f}')
