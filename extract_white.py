"""Digitize the WHITE (colored-challenge) lines from Jaap's tile sheets.

Same border-endpoint method as the gold calibration (distance-band projection,
cluster, extrapolate contact position to the border, snap to 0..10), but with the
white mask. The number circle/digits are white too but sit centrally, outside the
border bands. Output whites.txt in the same format/order as diamonddilemma.txt.

Self-consistency checks (no ground truth exists for white):
  - every tile has an even white endpoint count
  - per color group, non-blank patterns satisfy count(P) == count(rev(P))
  - blank-edge counts sufficient for region boundaries (silver>=16, red>=20ish, blue>=20)
"""
import json
import numpy as np
from PIL import Image
from collections import Counter

SHEETS = [("tilessilver", 0, 32, 4, 200), ("tilesred", 32, 80, 6, 140), ("tilesblue", 80, 160, 10, 140)]
bg = np.array([164, 74, 164])
white = np.array([252, 254, 252])

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

def dilate(mask, it=2):
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

def border_endpoints(P, T, L, R, comp_ids):
    """Component-aware contacts: for each white stroke component and each edge,
    a COMPACT contact blob (t-extent < 0.12) = one endpoint; elongated contact =
    stroke running parallel to the edge -> rejected. comp_ids aligns with P rows."""
    out = []
    for ei, (A, B) in enumerate(((R, L), (L, T), (T, R))):
        AB = B - A
        ab2 = AB @ AB
        ablen = np.sqrt(ab2)
        u = AB / ablen                              # unit tangent of the edge
        tproj = ((P - A) @ AB) / ab2
        dvec = P - A
        crossv = AB[0] * dvec[:, 1] - AB[1] * dvec[:, 0]
        d = np.abs(crossv) / ablen
        near = (d < 6.5) & (tproj > -0.02) & (tproj < 1.02)
        if not near.any():
            continue
        for cid in np.unique(comp_ids[near]):
            sel = near & (comp_ids == cid)
            ts = np.sort(tproj[sel])
            clusters = [[ts[0]]]
            for t in ts[1:]:
                if t - clusters[-1][-1] < 0.08:
                    clusters[-1].append(t)
                else:
                    clusters.append([t])
            for cl in clusters:
                tc = float(np.median(cl))
                # direction test: pixels of this component within 9px of the
                # contact point; principal axis must be transversal to the edge
                cpt = A + tc * AB
                dd = np.sqrt(((P - cpt) ** 2).sum(1))
                loc = (comp_ids == cid) & (dd < 9.0)
                if loc.sum() < 4:
                    continue
                Q = P[loc] - P[loc].mean(0)
                cov = Q.T @ Q
                evals, evecs = np.linalg.eigh(cov)
                axis = evecs[:, -1]                 # principal direction
                cosang = abs(float(axis @ u))
                if cosang > 0.85:                    # <~32deg from edge: parallel
                    continue
                out.append((ei, tc))
    return out

all_bits = []
for sheet, lo, hi, nrows, wthr in SHEETS:
    im = np.asarray(Image.open(f"img/{sheet}.png").convert("RGB")).astype(int)
    not_bg = (np.abs(im - bg).sum(axis=2) > 60)
    white_m = (im.min(axis=2) > wthr)
    rows = segs(not_bg.sum(axis=1))
    cols = segs(not_bg.sum(axis=0))
    assert len(rows) == nrows and len(cols) == 8
    for k in range(hi - lo):
        r, c = divmod(k, 8)
        (y0, y1), (x0, x1) = rows[r], cols[c]
        sub = not_bg[y0:y1, x0:x1]
        ys, xs = np.nonzero(sub)
        T = np.array([x0 + xs[ys == ys.min()].mean(), y0 + ys.min()], dtype=float)
        yb = ys.max()
        xsb = xs[ys >= yb - 2]
        L = np.array([x0 + xsb.min(), y0 + yb], dtype=float)
        R = np.array([x0 + xsb.max(), y0 + yb], dtype=float)
        # component labelling on the tile's white mask (minus number circle)
        pad = 2
        oy, ox = max(0, y0 - pad), max(0, x0 - pad)
        wm = white_m[oy:y1 + pad, ox:x1 + pad].copy()
        cx, cy = (T + L + R) / 3
        yy, xx = np.mgrid[0:wm.shape[0], 0:wm.shape[1]]
        wm &= ((xx + ox - cx) ** 2 + (yy + oy - cy) ** 2) > 22 ** 2
        lab, nc = label(dilate(wm, 2))
        wy, wx = np.nonzero(wm)
        P = np.stack([wx + ox, wy + oy], axis=1).astype(float)
        cids = lab[wy, wx]
        # drop tiny components (specks)
        sizes = np.bincount(cids, minlength=nc + 1)
        keep = sizes[cids] >= 12
        P, cids = P[keep], cids[keep]
        bits = [["0"] * 11 for _ in range(3)]
        if len(P):
            for (ei, t) in border_endpoints(P, T, L, R, cids):
                # points sit at fractions (p+1)/12 along the edge (interior points,
                # corners excluded) -- verified against gold ground truth
                p = int(round(t * 12 - 1))
                bits[ei][min(10, max(0, p))] = "1"
        all_bits.append(["".join(b) for b in bits])
    print(f"{sheet}: extracted", flush=True)

with open("whites.txt", "w", encoding="ascii") as f:
    f.write("# WHITE line endpoints, same format/order/conventions as diamonddilemma.txt\n")
    f.write("# (11 bits per edge: bottom R->L, left L->T, right T->R; tile 1 first)\n")
    for i, b in enumerate(all_bits):
        f.write(" ".join(b) + (f"   #{i+1}\n" if i % 8 == 0 else "\n"))
        if i % 8 == 7:
            f.write("\n")

# self-consistency checks
print("\n=== self-consistency ===")
odd = [i + 1 for i, b in enumerate(all_bits) if sum(e.count("1") for e in b) % 2]
print(f"tiles with ODD white endpoint count (extraction errors): {len(odd)} -> {odd}")
for name, lo, hi in (("silver", 0, 32), ("red", 32, 80), ("blue", 80, 160)):
    pats = [e for b in all_bits[lo:hi] for e in b]
    cnt = Counter(pats)
    viol = [(p, cnt[p], cnt.get(p[::-1], 0)) for p in sorted(cnt)
            if p != "0" * 11 and cnt[p] != cnt.get(p[::-1], 0)]
    print(f"{name}: blanks={cnt.get('0'*11, 0)}/{3*(hi-lo)} edges, "
          f"invariant violations={len(viol)}")
    for v in viol[:8]:
        print("   ", v)
