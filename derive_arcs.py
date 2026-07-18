"""Derive within-tile gold-line arc pairings rigorously via triangle geometry.

A single closed loop is a simple curve => within each tile its arcs do not cross.
Model each tile as an equilateral triangle; endpoints sit at known 2D coordinates
(11 equally spaced points per edge). Among all perfect matchings of a tile's
endpoints, keep the NON-CROSSING ones (straight chords, no proper intersection),
and pick the physical one: threads pass through, so maximize different-edge arcs;
deterministic tie-break. Flag tiles where the max-different-edge non-crossing
matching is not unique (would need the image / Jaap to disambiguate).

Edges clockwise: edge j runs from vertex V[j] to V[j+1]; position p at fraction p/10.
Output: arcs.json = for each tile a list of arcs [[e,p],[e,p]] (endpoints paired).
"""
import json, re, math
from itertools import combinations

def parse(path):
    tiles = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.findall(r"\b[01]{11}\b", line)
        if len(m) == 3:
            tiles.append(m)
    return tiles

V = [(0.0, 0.0), (1.0, 0.0), (0.5, math.sqrt(3) / 2)]   # equilateral
def coord(e, p):
    a = V[e]; b = V[(e + 1) % 3]
    # the 11 points are INTERIOR: fractions (p+1)/12 along the edge (verified
    # against the tile images; corners are NOT endpoint positions)
    t = (p + 1) / 12.0
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

def seg_cross(p1, p2, p3, p4):
    # proper segment intersection (shared endpoints don't count as crossing)
    def o(a, b, c):
        v = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
        return (v > 1e-12) - (v < -1e-12)
    if p1 in (p3, p4) or p2 in (p3, p4):
        return False
    return o(p1,p2,p3) != o(p1,p2,p4) and o(p3,p4,p1) != o(p3,p4,p2)

def matchings(pts):
    if not pts:
        yield []
        return
    first = pts[0]
    for i in range(1, len(pts)):
        rest = pts[1:i] + pts[i+1:]
        for m in matchings(rest):
            yield [(first, pts[i])] + m

def derive(tiles):
    """Return (all_arcs, ambiguous) for a list of tiles (each = 3 bit-strings)."""
    all_arcs = []
    ambiguous = []
    for tid, tile in enumerate(tiles):
        eps = [(j, p) for j in range(3) for p, c in enumerate(tile[j]) if c == "1"]
        xy = {ep: coord(*ep) for ep in eps}
        best = None; best_key = None; n_best = 0
        for m in matchings(eps):
            ok = True
            for (a1, a2), (b1, b2) in combinations(m, 2):
                if seg_cross(xy[a1], xy[a2], xy[b1], xy[b2]):
                    ok = False; break
            if not ok:
                continue
            diff = sum(1 for (a, b) in m if a[0] != b[0])
            if best_key is None or diff > best_key:
                best_key, best, n_best = diff, m, 1
            elif diff == best_key:
                n_best += 1
        if best is None:
            all_arcs.append(None); ambiguous.append((tid, "no-noncrossing")); continue
        if n_best > 1:
            ambiguous.append((tid, f"{n_best} max-diff non-crossing matchings"))
        all_arcs.append([[list(a), list(b)] for a, b in best])
    return all_arcs, ambiguous


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "diamonddilemma.txt"
    out = sys.argv[2] if len(sys.argv) > 2 else "arcs.json"
    if src.endswith(".txt") and "instance" in src:
        from sat_solver import load_instance
        tiles = load_instance(src)[2]
    else:
        tiles = parse(src)
    all_arcs, ambiguous = derive(tiles)
    caps = sum(1 for a in all_arcs if a and any(x[0] == y[0] for x, y in a))
    print(f"tiles processed: {len(all_arcs)}; with same-edge cap arcs: {caps}")
    print(f"AMBIGUOUS tiles (non-unique wiring): {len(ambiguous)}")
    for x in ambiguous[:20]:
        print("  ", x)
    json.dump(all_arcs, open(out, "w"))
    print(f"{out} written.")
