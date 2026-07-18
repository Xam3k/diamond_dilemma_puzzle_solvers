"""Extract within-tile gold arcs by STROKE TRACING (gold lines are bent polylines).

Per tile: gold mask -> dilate (bridge white-line / number-circle overdraws) ->
connected components -> map each component to the true endpoints (from bit data)
it touches. Clean tile = every component touches exactly 2 endpoints and counts
match. Output arcs; flag unclean tiles for manual reading.

Output: arcs_image2.json {tile: {"arcs": [...], "clean": bool, "note": str}}
"""
import json, re
import numpy as np
from PIL import Image

def parse(path):
    ts = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.findall(r"[01]{11}", line)
        if len(m) == 3:
            ts.append(m)
    return ts

tiles = parse("diamonddilemma.txt")
SHEETS = [("tilessilver", 0, 32, 4), ("tilesred", 32, 80, 6), ("tilesblue", 80, 160, 10)]
bg = np.array([164, 74, 164])
gold = np.array([116, 118, 4])

def segs(v, minlen=10):
    out, s = [], None
    for i, x in enumerate(v > 0):
        if x and s is None:
            s = i
        if not x and s is not None:
            if i - s >= minlen:
                out.append((s, i))
            s = None
    if s is not None:
        out.append((s, len(v)))
    return out

def dilate(mask, it=3):
    m = mask.copy()
    for _ in range(it):
        m = (m | np.roll(m, 1, 0) | np.roll(m, -1, 0)
             | np.roll(m, 1, 1) | np.roll(m, -1, 1))
    return m

def label(mask):
    lab = np.zeros(mask.shape, dtype=int)
    cur = 0
    H, W = mask.shape
    for y0 in range(H):
        for x0 in range(W):
            if mask[y0, x0] and lab[y0, x0] == 0:
                cur += 1
                stack = [(y0, x0)]
                lab[y0, x0] = cur
                while stack:
                    y, x = stack.pop()
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = y + dy, x + dx
                            if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] \
                                    and lab[ny, nx] == 0:
                                lab[ny, nx] = cur
                                stack.append((ny, nx))
    return lab, cur

results = {}
for sheet, lo, hi, nrows in SHEETS:
    im = np.asarray(Image.open(f"img/{sheet}.png").convert("RGB")).astype(int)
    not_bg = (np.abs(im - bg).sum(axis=2) > 60)
    gold_m = (np.abs(im - gold).sum(axis=2) < 110)
    rows = segs(not_bg.sum(axis=1))
    cols = segs(not_bg.sum(axis=0))
    for k in range(hi - lo):
        r, c = divmod(k, 8)
        (y0, y1), (x0, x1) = rows[r], cols[c]
        pad = 2
        gm = gold_m[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
        nb = not_bg[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
        oy, ox = max(0, y0 - pad), max(0, x0 - pad)
        ys, xs = np.nonzero(nb)
        T = np.array([xs[ys == ys.min()].mean(), ys.min()])
        yb = ys.max()
        xsb = xs[ys >= yb - 2]
        L = np.array([float(xsb.min()), float(yb)])
        R = np.array([float(xsb.max()), float(yb)])
        walks = {0: (R, L), 1: (L, T), 2: (T, R)}   # data edge -> image walk (rot 0)
        tile = tiles[lo + k]
        eps = [(e, p) for e in range(3) for p, ch in enumerate(tile[e]) if ch == "1"]
        coords = {}
        for (e, p) in eps:
            A, B = walks[e]
            coords[(e, p)] = A + ((p + 1) / 12.0) * (B - A)
        gd = dilate(gm, 3)
        lab, nc = label(gd)
        # assign each true endpoint to the nearest component containing gold nearby
        comp_of = {}
        for ep, xy in coords.items():
            xi, yi = int(round(xy[0])), int(round(xy[1]))
            best = None
            for rad in range(2, 9):
                y_lo, y_hi = max(0, yi - rad), min(gd.shape[0], yi + rad + 1)
                x_lo, x_hi = max(0, xi - rad), min(gd.shape[1], xi + rad + 1)
                sub = lab[y_lo:y_hi, x_lo:x_hi]
                subg = gm[y_lo:y_hi, x_lo:x_hi]
                vals = sub[(sub > 0)]
                if vals.size:
                    # prefer component with actual gold pixels near
                    valsg = sub[(sub > 0) & dilate(subg, 1)]
                    best = int(np.bincount(valsg if valsg.size else vals).argmax()
                               if (valsg if valsg.size else vals).size else 0)
                    break
            comp_of[ep] = best
        groups = {}
        for ep, cmp_ in comp_of.items():
            groups.setdefault(cmp_, []).append(ep)
        arcs, clean, notes = [], True, []
        for cmp_, members in groups.items():
            if cmp_ is None:
                clean = False; notes.append(f"unassigned {members}"); continue
            if len(members) == 2:
                arcs.append([list(members[0]), list(members[1])])
            else:
                clean = False
                notes.append(f"component {cmp_} touches {len(members)}: {members}")
        results[lo + k] = {"arcs": arcs, "clean": clean, "note": "; ".join(notes)}
    print(f"{sheet} done", flush=True)

json.dump(results, open("arcs_image2.json", "w"))
nclean = sum(1 for v in results.values() if v["clean"])
print(f"clean stroke-traced tiles: {nclean}/160")
print("unclean:", sorted(k for k, v in results.items() if not v["clean"]))
