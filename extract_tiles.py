"""Extract gold-line endpoints and arcs from Jaap's tile sheet images.

Step 1 (this run): locate tile triangles on a sheet, extract border gold endpoints
for each tile, and CALIBRATE the edge-order/direction convention against our bit
data (diamonddilemma.txt order, assumed silver 1-32, red 33-80, blue 81-160).

Sheets: 8 tiles per row; silver 4 rows (32), red 6 rows (48), blue 10 rows (80).
Gold color ~ (116,118,4); background ~ (164,74,164).
"""
import sys, json
import numpy as np
from PIL import Image

SHEET = sys.argv[1] if len(sys.argv) > 1 else "tilessilver"
ROWS = {"tilessilver": 4, "tilesred": 6, "tilesblue": 10}[SHEET]
BASE = {"tilessilver": 0, "tilesred": 32, "tilesblue": 80}[SHEET]

im = np.asarray(Image.open(f"img/{SHEET}.png").convert("RGB")).astype(int)
H, W, _ = im.shape
bg = np.array([164, 74, 164])
gold = np.array([116, 118, 4])

not_bg = (np.abs(im - bg).sum(axis=2) > 60)          # tile body mask
gold_m = (np.abs(im - gold).sum(axis=2) < 90)         # gold-line mask

# --- locate tile bounding boxes: split columns x rows by projection ---
colsum = not_bg.sum(axis=0)
rowsum = not_bg.sum(axis=1)
def segments(v, minlen=10):
    seg, s = [], None
    for i, x in enumerate(v > 0):
        if x and s is None:
            s = i
        if not x and s is not None:
            if i - s >= minlen:
                seg.append((s, i))
            s = None
    if s is not None and len(v) - s >= minlen:
        seg.append((s, len(v)))
    return seg
rows = segments(rowsum)
cols = segments(colsum)
print(f"{SHEET}: detected {len(rows)} rows x {len(cols)} cols", flush=True)
assert len(rows) == ROWS and len(cols) == 8, "grid detection failed"

def tile_box(k):
    r, c = divmod(k, 8)
    return rows[r], cols[c]

def tile_corners(k):
    """Up-triangle corners in image coords: apex T, bottom-left L, bottom-right R."""
    (y0, y1), (x0, x1) = tile_box(k)
    sub = not_bg[y0:y1, x0:x1]
    ys, xs = np.nonzero(sub)
    top_i = ys.argmin()
    T = (x0 + xs[ys == ys.min()].mean(), y0 + ys.min())
    yb = ys.max()
    xs_b = xs[ys >= yb - 2]
    L = (x0 + xs_b.min(), y0 + yb)
    R = (x0 + xs_b.max(), y0 + yb)
    return np.array(T), np.array(L), np.array(R)

def border_gold_endpoints(k):
    """Gold pixels near the triangle border -> list of (edge_label, t in [0,1]).
    Edges labelled by corner pair: 'RL' bottom (R->L), 'LT' left (L->T),
    'TR' right (T->R) -- a CLOCKWISE walk R->L->T->R as SEEN in the image.
    """
    T, L, R = tile_corners(k)
    (y0, y1), (x0, x1) = tile_box(k)
    pts = []
    gy, gx = np.nonzero(gold_m[y0:y1, x0:x1])
    P = np.stack([gx + x0, gy + y0], axis=1).astype(float)
    if len(P) == 0:
        return []
    out = []
    for name, A, B in (("RL", R, L), ("LT", L, T), ("TR", T, R)):
        AB = B - A
        ab2 = AB @ AB
        tproj = ((P - A) @ AB) / ab2
        dvec = P - A
        crossv = AB[0] * dvec[:, 1] - AB[1] * dvec[:, 0]
        d = np.abs(crossv) / np.sqrt(ab2)
        near = (d < 6.0) & (tproj > -0.02) & (tproj < 1.02)
        if not near.any():
            continue
        pts_t, pts_d = tproj[near], d[near]
        idx = np.argsort(pts_t)
        pts_t, pts_d = pts_t[idx], pts_d[idx]
        # cluster by gaps in t
        clusters = [[0]]
        for i in range(1, len(pts_t)):
            if pts_t[i] - pts_t[clusters[-1][-1]] < 0.06:
                clusters[-1].append(i)
            else:
                clusters.append([i])
        for cl in clusters:
            ct, cd = pts_t[cl], pts_d[cl]
            if cd.min() > 4.0:
                continue                     # line passes near edge but not touching
            if len(ct) >= 3 and np.ptp(cd) > 1.5:
                # extrapolate t at d=0 (endpoint ON the border)
                A1 = np.stack([cd, np.ones_like(cd)], axis=1)
                coef, *_ = np.linalg.lstsq(A1, ct, rcond=None)
                t0 = float(coef[1])
            else:
                t0 = float(ct[cd.argmin()])
            out.append((name, min(1.0, max(0.0, t0))))
    return out

def to_bits(eps):
    """Convert endpoint list to 3 bit-strings in image-walk order RL,LT,TR;
    t maps to position round(t*10)."""
    bits = {n: ["0"] * 11 for n in ("RL", "LT", "TR")}
    for n, t in eps:
        p = int(round(t * 10))
        p = min(10, max(0, p))
        bits[n][p] = "1"
    return {n: "".join(b) for n, b in bits.items()}

# calibrate on first 8 tiles against known data
import re
data = [re.findall(r"[01]{11}", l) for l in open("diamonddilemma.txt")]
data = [d for d in data if len(d) == 3]

def variants(bits3):
    """All 6 cyclic-order x direction interpretations of image edges vs data edges."""
    names = ["RL", "LT", "TR"]
    res = {}
    for start in range(3):
        for flip in (False, True):
            order = [names[(start + (i if not flip else -i)) % 3] for i in range(3)]
            v = []
            for nm in order:
                s = bits3[nm]
                v.append(s if not flip else s[::-1])
            res[(start, flip)] = v
    return res

match_count = {}
for k in range(8):
    eps = border_gold_endpoints(k)
    b3 = to_bits(eps)
    want = data[BASE + k]
    for key, v in variants(b3).items():
        # compare as cyclic rotations too
        ok = any(v[i % 3] == want[0] and v[(i + 1) % 3] == want[1]
                 and v[(i + 2) % 3] == want[2] for i in range(3))
        match_count[key] = match_count.get(key, 0) + (1 if ok else 0)
print("convention match counts (start,flip) over 8 tiles:", match_count, flush=True)
best = max(match_count, key=match_count.get)
print("BEST:", best, "matches", match_count[best], "/8", flush=True)
