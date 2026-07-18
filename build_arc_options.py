"""Build arcs_options.json: per tile, ALL plausible within-tile wirings.
Sources: (a) every max-different-edge non-crossing matching from geometry
(derive_arcs), (b) the stroke-traced image wiring when clean and sane (no
degenerate corner arcs). Loop checks then iterate the product over uncertain tiles.
"""
import json, math, re
from itertools import combinations
from derive_arcs import parse, coord, seg_cross, matchings

tiles = parse("diamonddilemma.txt")
img = json.load(open("arcs_image2.json"))

def norm(m):
    return frozenset(frozenset((tuple(a), tuple(b))) for a, b in m)

def degenerate(arc):
    # With interior points at (p+1)/12, no two positions coincide (corners are
    # not endpoint positions), so no arc is degenerate. Kept for interface.
    return False

options = []
for tid, tile in enumerate(tiles):
    eps = [(j, p) for j in range(3) for p, c in enumerate(tile[j]) if c == "1"]
    xy = {ep: coord(*ep) for ep in eps}
    best_key, opts = None, []
    for m in matchings(eps):
        ok = True
        for (a1, a2), (b1, b2) in combinations(m, 2):
            if seg_cross(xy[a1], xy[a2], xy[b1], xy[b2]):
                ok = False
                break
        if not ok:
            continue
        if any(degenerate(((a[0], a[1]), (b[0], b[1]))) for a, b in m):
            continue
        diff = sum(1 for (a, b) in m if a[0] != b[0])
        if best_key is None or diff > best_key:
            best_key, opts = diff, [m]
        elif diff == best_key:
            opts.append(m)
    cand = {norm(m) for m in opts}
    v = img[str(tid)]
    if v["clean"]:
        iarcs = [((a[0], a[1]), (b[0], b[1])) for a, b in v["arcs"]]
        if len(iarcs) == len(eps) // 2 and not any(degenerate(a) for a in iarcs):
            cand.add(norm(iarcs))
    ser = []
    for m in cand:
        arcs = sorted(tuple(sorted(map(tuple, fs))) for fs in m)
        ser.append([[list(a), list(b)] for a, b in arcs])
    options.append(ser)

json.dump(options, open("arcs_options.json", "w"))
counts = [len(o) for o in options]
from collections import Counter
print("options per tile distribution:", dict(sorted(Counter(counts).items())))
multi = [i for i, c in enumerate(counts) if c > 1]
print(f"tiles with >1 wiring option: {len(multi)} -> {multi}")
zero = [i for i, c in enumerate(counts) if c == 0]
print("tiles with NO valid wiring (must not happen):", zero)
