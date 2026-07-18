"""Extract ground-truth within-tile gold ARC connectivity from Jaap's tile sheets.

Uses the bit data as ground truth for endpoint positions; the image only supplies
CONNECTIVITY: project each true endpoint (edge, pos) to image coords, then for each
endpoint pair score gold-pixel coverage along the straight segment; choose the
perfect matching maximizing coverage. Tries all 3 rotations per tile, keeps the best.

Image edge mapping (calibrated): image walk RL (bottom, R->L), LT (left, L->T),
TR (right, T->R) corresponds to data edges (0,1,2) up to per-tile rotation; bit
position p at fraction p/10 along the walk direction.

Output: arcs_image.json  = per tile: {"rot":r, "arcs":[[[e,p],[e,p]],...],
        "score": avg coverage, "margin": best - second_best}
Compare with derived arcs.json to settle the ambiguous tiles.
"""
import json, re, sys
from itertools import combinations
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
SHEETS = [("tilessilver", 0, 32, 4, (172, 170, 172)),
          ("tilesred", 32, 80, 6, (252, 2, 4)),
          ("tilesblue", 80, 160, 10, (4, 2, 252))]
bg = np.array([164, 74, 164])
gold = np.array([116, 118, 4])

def matchings(pts):
    if not pts:
        yield []
        return
    a = pts[0]
    for i in range(1, len(pts)):
        for m in matchings(pts[1:i] + pts[i + 1:]):
            yield [(a, pts[i])] + m

results = {}
for sheet, lo, hi, nrows, bodyc in SHEETS:
    im = np.asarray(Image.open(f"img/{sheet}.png").convert("RGB")).astype(int)
    not_bg = (np.abs(im - bg).sum(axis=2) > 60)
    gold_m = (np.abs(im - gold).sum(axis=2) < 110)
    body_m = (np.abs(im - np.array(bodyc)).sum(axis=2) < 90)
    # grid
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
    rows = segs(not_bg.sum(axis=1))
    cols = segs(not_bg.sum(axis=0))
    assert len(rows) == nrows and len(cols) == 8, f"{sheet} grid fail"
    # distance transform substitute: precompute gold pixel coords per tile
    for k in range(hi - lo):
        r, c = divmod(k, 8)
        (y0, y1), (x0, x1) = rows[r], cols[c]
        sub = not_bg[y0:y1, x0:x1]
        ys, xs = np.nonzero(sub)
        T = np.array([x0 + xs[ys == ys.min()].mean(), y0 + ys.min()])
        yb = ys.max()
        xsb = xs[ys >= yb - 2]
        L = np.array([x0 + xsb.min(), y0 + yb])
        R = np.array([x0 + xsb.max(), y0 + yb])
        gy, gx = np.nonzero(gold_m[y0:y1, x0:x1])
        G = np.stack([gx + x0, gy + y0], axis=1).astype(float)
        walks = {"RL": (R, L), "LT": (L, T), "TR": (T, R)}
        names = ["RL", "LT", "TR"]
        tile = tiles[lo + k]
        eps_all = [(e, p) for e in range(3) for p, ch in enumerate(tile[e]) if ch == "1"]

        def coords(rot):
            # data edge (e) -> image walk names[(e - rot) % 3]? mapping: image edge i
            # corresponds to data edge (i + rot) % 3. So data edge e -> image i=(e-rot)%3.
            d = {}
            for (e, p) in eps_all:
                nm = names[(e - rot) % 3]
                A, B = walks[nm]
                d[(e, p)] = A + (p / 10.0) * (B - A)
            return d

        def cover(a, b):
            n = max(10, int(np.hypot(*(b - a)) / 2))
            ts = np.linspace(0.08, 0.92, n)
            pts = a[None, :] + ts[:, None] * (b - a)[None, :]
            if len(G) == 0:
                return 0.0
            dmin = np.sqrt(((pts[:, None, :] - G[None, :, :]) ** 2).sum(-1)).min(1)
            hit = dmin < 3.0
            # non-hit samples on plain tile body = real misses; on occluders
            # (white lines, number circles, outlines) = excluded from scoring
            xi = np.clip(pts[:, 0].round().astype(int), 0, im.shape[1] - 1)
            yi = np.clip(pts[:, 1].round().astype(int), 0, im.shape[0] - 1)
            onbody = body_m[yi, xi]
            miss = (~hit) & onbody
            usable = hit.sum() + miss.sum()
            if usable < max(3, n * 0.25):
                return 0.5      # mostly occluded: uninformative, neutral score
            return float(hit.sum() / usable)

        def crossing_pairs(m, cd):
            def seg_cross(p1, p2, p3, p4):
                def o(a, b, c):
                    v = float((b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]))
                    return int(v > 1e-9) - int(v < -1e-9)
                return (o(p1,p2,p3) != o(p1,p2,p4)) and (o(p3,p4,p1) != o(p3,p4,p2))
            cnt = 0
            for (a1, a2), (b1, b2) in combinations(m, 2):
                if seg_cross(cd[a1], cd[a2], cd[b1], cd[b2]):
                    cnt += 1
            return cnt

        rot = 0                       # sheets drawn in data orientation
        cd = coords(rot)
        pairsc = {}
        for a, b in combinations(eps_all, 2):
            pairsc[(a, b)] = cover(cd[a], cd[b])
        scored = []
        for m in matchings(eps_all):
            sc = sum(pairsc[(a, b)] if (a, b) in pairsc else pairsc[(b, a)]
                     for a, b in m) / max(1, len(m))
            scored.append((sc, crossing_pairs(m, cd), m))
        # prefer high coverage; among near-ties (within 0.03) prefer fewer crossings
        scored.sort(key=lambda x: (-x[0], x[1]))
        top_sc = scored[0][0]
        cands = [s for s in scored if s[0] >= top_sc - 0.03]
        cands.sort(key=lambda x: (x[1], -x[0]))
        sc, ncross, arcs = cands[0]
        # margin vs best DIFFERENT matching outside the tie-tolerance
        others = [s[0] for s in scored if frozenset(map(frozenset, s[2]))
                  != frozenset(map(frozenset, arcs))]
        margin = sc - max(others) if others else 1.0
        results[lo + k] = {"rot": rot, "score": round(sc, 3),
                           "margin": round(margin, 3), "ncross": ncross,
                           "arcs": [[list(a), list(b)] for a, b in arcs]}
    print(f"{sheet}: done ({hi-lo} tiles)", flush=True)

json.dump(results, open("arcs_image.json", "w"))
scores = [v["score"] for v in results.values()]
print(f"avg coverage score: {np.mean(scores):.3f}; tiles with score<0.75: "
      f"{sorted(k for k, v in results.items() if v['score'] < 0.75)}", flush=True)
print(f"low-margin (<0.05) tiles: "
      f"{sorted(k for k, v in results.items() if v['margin'] < 0.05)}", flush=True)
