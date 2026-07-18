"""Validate our white data against Jaap's PUBLISHED silver solution (solsilver1).

The solution image is a 4x8 sheared triangle strip (rows shift left going down):
  row r, cell k: UP-triangle if k even, DOWN if k odd.
  Adjacency: (r,k)~(r,k+1) via slant edges; DOWN (r,k) shares its top edge with
  UP (r-1,k-2) (derived from the shear geometry).
Tiles per cell transcribed from the image; rotations are free variables; each
tile-edge white reading may be 'corrected' (reversed) at cost 1. Minimize cost
s.t. all internal edges match (reversed patterns) and all boundary edges blank.
Tries both chirality conventions (in case the drawn net mirrors our edge order).
"""
import re, sys
from ortools.sat.python import cp_model

GRID = [[16,23,18,14,31, 7,10,13],
        [ 6,19, 9,17,26, 4,21,24],
        [30,11,22, 2,29,20,15, 3],
        [32,27, 5,28,12, 1, 8,25]]

white = []
for line in open("whites.txt"):
    m = re.findall(r"\b[01]{11}\b", line)
    if len(m) == 3:
        white.append(m)
rev = lambda p: p[::-1]
ZERO = "0" * 11

# cells and edges. For an UP cell define edges in CW order as (B, L, R) like our
# tile convention; for DOWN cell (apex down) define (T, R, L) analogously CW.
# We only need CONSISTENT per-cell cyclic edge slots 0,1,2 and the adjacency map
# saying which edge-slot of each cell meets which edge-slot of the neighbor.
# Geometry (shear rule):
#  UP (r,k):   edge slots: 0=bottom, 1=left-slant, 2=right-slant
#  DOWN (r,k): edge slots: 0=top,    1=right-slant, 2=left-slant
#  (These orders are one chirality; the mirrored variant swaps 1<->2 meanings.)
# Adjacencies:
#  (r,k) up  ~ (r,k+1) down : up's right-slant (2) meets down's left-slant (2)
#  (r,k) down~ (r,k+1) up   : down's right-slant (1) meets up's left-slant (1)
#  DOWN (r,k) top (0) meets UP (r-1,k-2) bottom (0)
def build(chir):
    cells = [(r, k) for r in range(4) for k in range(8)]
    cid = {c: i for i, c in enumerate(cells)}
    adj = []      # (cellA, slotA, cellB, slotB)
    for r in range(4):
        for k in range(7):
            a, b = cid[(r, k)], cid[(r, k + 1)]
            if k % 2 == 0:   # up ~ down
                sa, sb = (2, 2) if not chir else (1, 1)
            else:            # down ~ up
                sa, sb = (1, 1) if not chir else (2, 2)
            adj.append((a, sa, b, sb))
    for r in range(1, 4):
        for k in range(1, 8, 2):
            if 0 <= k - 2 < 8:
                adj.append((cid[(r, k)], 0, cid[(r - 1, k - 2)], 0))
    # boundary slots = all (cell,slot) not in adj
    used = set()
    for (a, sa, b, sb) in adj:
        used.add((a, sa)); used.add((b, sb))
    bound = [(i, s) for i in range(32) for s in range(3) if (i, s) not in used]
    return cells, cid, adj, bound

def solve(chir):
    cells, cid, adj, bound = build(chir)
    tiles_at = [GRID[r][k] - 1 for (r, k) in cells]   # 0-based tile ids
    pats = sorted({white[t][e] for t in tiles_at for e in range(3)} |
                  {rev(white[t][e]) for t in tiles_at for e in range(3)} | {ZERO})
    pid = {p: i for i, p in enumerate(pats)}
    rid = [pid[rev(p)] for p in pats]
    m = cp_model.CpModel()
    rv = [m.NewIntVar(0, 2, "") for _ in range(32)]
    pe = [[m.NewIntVar(0, len(pats) - 1, "") for _ in range(3)] for _ in range(32)]
    fb = [[m.NewBoolVar("") for _ in range(3)] for _ in range(32)]
    for i, t in enumerate(tiles_at):
        rows = []
        for r in range(3):
            for mask in range(8):
                ok, fbs, pes = True, [0, 0, 0], [0, 0, 0]
                for te in range(3):
                    if (mask >> te) & 1:
                        if white[t][te] == rev(white[t][te]):
                            ok = False; break
                        fbs[te] = 1
                if not ok:
                    continue
                for j in range(3):
                    te = (j + r) % 3
                    p = white[t][te]
                    if (mask >> te) & 1:
                        p = rev(p)
                    pes[j] = pid[p]
                rows.append((r, fbs[0], fbs[1], fbs[2], pes[0], pes[1], pes[2]))
        m.AddAllowedAssignments([rv[i], fb[i][0], fb[i][1], fb[i][2],
                                 pe[i][0], pe[i][1], pe[i][2]], rows)
    for (a, sa, b, sb) in adj:
        m.AddElement(pe[b][sb], rid, pe[a][sa])
    for (i, s) in bound:
        m.Add(pe[i][s] == pid[ZERO])
    m.Minimize(sum(fb[i][k] for i in range(32) for k in range(3)))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = 120
    sv.parameters.num_search_workers = 8
    sv.parameters.cp_model_probing_level = 0
    st = sv.Solve(m)
    name = sv.StatusName(st)
    out = [f"chirality={chir}: {name}"]
    if name in ("OPTIMAL", "FEASIBLE"):
        out.append(f"  min_corrections={int(sv.ObjectiveValue())}")
        EN = "BLR"
        for i, t in enumerate(tiles_at):
            for k in range(3):
                if sv.Value(fb[i][k]):
                    out.append(f"  SUSPECT tile {t+1} edge {EN[k]}: {white[t][k]}"
                               f" -> {rev(white[t][k])}")
    return "\n".join(out)

print(solve(False))
print(solve(True))
