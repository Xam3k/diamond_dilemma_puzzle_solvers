"""Minimal-flips repair for a white challenge: allow each tile-edge WHITE reading
to be reversed (direction miscount) at cost 1; minimize flips such that the
challenge (region tiling + white matching + blank boundary) becomes solvable.
The optimal flip set = the suspect edges to re-verify against the images.

Usage: python flip_solver.py <faces> <tilelo> <tilehi> [wall]
  e.g. python flip_solver.py T0,T1 0 32 240
"""
import json, re, sys, time
from ortools.sat.python import cp_model

faces = sys.argv[1].split(",")
tlo, thi = int(sys.argv[2]), int(sys.argv[3])
wall = float(sys.argv[4]) if len(sys.argv) > 4 else 240.0

g = json.load(open("geometry.json"))
white = []
for line in open("whites.txt"):
    m = re.findall(r"\b[01]{11}\b", line)
    if len(m) == 3:
        white.append(m)
rev = lambda p: p[::-1]
ZERO = "0" * 11

slots = [s["idx"] for s in g["slots"] if s["face"] in faces]
sset = set(slots)
sidx = {s: i for i, s in enumerate(slots)}
group = list(range(tlo, thi))
n = len(slots)
assert n == len(group)

internal, boundary = [], []
seen = set()
for e in g["edges"]:
    sA, eA, sB, eB = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
    if sA in sset and sB in sset:
        key = (min((sA, eA), (sB, eB)), max((sA, eA), (sB, eB)))
        if key not in seen:
            seen.add(key)
            internal.append((sA, eA, sB, eB))
    elif sA in sset:
        boundary.append((sA, eA))
    elif sB in sset:
        boundary.append((sB, eB))

pats = sorted({white[t][e] for t in group for e in range(3)} |
              {rev(white[t][e]) for t in group for e in range(3)} | {ZERO})
pid = {p: i for i, p in enumerate(pats)}
rid = [pid[rev(p)] for p in pats]

m = cp_model.CpModel()
tv = [m.NewIntVar(0, n - 1, "") for _ in range(n)]
rv = [m.NewIntVar(0, 2, "") for _ in range(n)]
pe = [[m.NewIntVar(0, len(pats) - 1, "") for _ in range(3)] for _ in range(n)]
fb = [[m.NewBoolVar("") for _ in range(3)] for _ in range(n)]   # tile-edge k flipped
m.AddAllDifferent(tv)

# link rows: (tile_idx, rot, fb for tile-edges 0..2, pe for slot-edges 0..2)
link = []
for li, t in enumerate(group):
    for r in range(3):
        for mask in range(8):
            row = [li, r]
            ok = True
            fbs = [0, 0, 0]
            pes = [0, 0, 0]
            for te in range(3):
                flipped = (mask >> te) & 1
                p = white[t][te]
                if flipped:
                    if p == rev(p):   # palindrome: flip is a no-op, forbid to avoid free cost
                        ok = False
                        break
                    p = rev(p)
                fbs[te] = flipped
            if not ok:
                continue
            for j in range(3):
                te = (j + r) % 3
                p = white[t][te]
                if (mask >> te) & 1:
                    p = rev(p)
                pes[j] = pid[p]
            link.append((li, r, fbs[0], fbs[1], fbs[2], pes[0], pes[1], pes[2]))
for i in range(n):
    m.AddAllowedAssignments(
        [tv[i], rv[i], fb[i][0], fb[i][1], fb[i][2], pe[i][0], pe[i][1], pe[i][2]], link)

for (sA, eA, sB, eB) in internal:
    m.AddElement(pe[sidx[sB]][eB], rid, pe[sidx[sA]][eA])
for (sA, eA) in boundary:
    m.Add(pe[sidx[sA]][eA] == pid[ZERO])

m.Minimize(sum(fb[i][k] for i in range(n) for k in range(3)))

sv = cp_model.CpSolver()
sv.parameters.max_time_in_seconds = wall
sv.parameters.num_search_workers = 8
sv.parameters.cp_model_probing_level = 0
st = sv.Solve(m)
name = sv.StatusName(st)
print(f"STATUS={name}", flush=True)
if name in ("OPTIMAL", "FEASIBLE"):
    total = int(sv.ObjectiveValue())
    print(f"min_flips={total} ({'PROVEN minimal' if name=='OPTIMAL' else 'upper bound'})")
    EN = "BLR"
    for i in range(n):
        t = group[sv.Value(tv[i])]
        for k in range(3):
            if sv.Value(fb[i][k]):
                print(f"  SUSPECT: tile {t+1} edge {EN[k]}: recorded "
                      f"{white[t][k]} -> should be {rev(white[t][k])}")
