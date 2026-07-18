"""Min-EDIT repair: how many white edge-readings must change (to anything) for the
silver challenge to be solvable on a 2-face region? Reports the edited edges of
the optimum (candidate suspects) and the magnitude of remaining data error.

Usage: python edit_solver.py <faces> <tilelo> <tilehi> [wall]
"""
import json, re, sys
from ortools.sat.python import cp_model

faces = sys.argv[1].split(",")
tlo, thi = int(sys.argv[2]), int(sys.argv[3])
wall = float(sys.argv[4]) if len(sys.argv) > 4 else 300.0

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
P = len(pats)
rid = [pid[rev(p)] for p in pats]

m = cp_model.CpModel()
tv = [m.NewIntVar(0, n - 1, "") for _ in range(n)]
rv = [m.NewIntVar(0, 2, "") for _ in range(n)]
rec = [[m.NewIntVar(0, P - 1, "") for _ in range(3)] for _ in range(n)]  # recorded
act = [[m.NewIntVar(0, P - 1, "") for _ in range(3)] for _ in range(n)]  # actual
df = [[m.NewBoolVar("") for _ in range(3)] for _ in range(n)]            # edited?
m.AddAllDifferent(tv)
link = []
for li, t in enumerate(group):
    for r in range(3):
        link.append((li, r, pid[white[t][(0 + r) % 3]],
                     pid[white[t][(1 + r) % 3]], pid[white[t][(2 + r) % 3]]))
for i in range(n):
    m.AddAllowedAssignments([tv[i], rv[i], rec[i][0], rec[i][1], rec[i][2]], link)
    for j in range(3):
        m.Add(act[i][j] == rec[i][j]).OnlyEnforceIf(df[i][j].Not())
        m.Add(act[i][j] != rec[i][j]).OnlyEnforceIf(df[i][j])
for (sA, eA, sB, eB) in internal:
    m.AddElement(act[sidx[sB]][eB], rid, act[sidx[sA]][eA])
for (sA, eA) in boundary:
    m.Add(act[sidx[sA]][eA] == pid[ZERO])
m.Minimize(sum(df[i][j] for i in range(n) for j in range(3)))

sv = cp_model.CpSolver()
sv.parameters.max_time_in_seconds = wall
sv.parameters.num_search_workers = 8
sv.parameters.cp_model_probing_level = 0
st = sv.Solve(m)
name = sv.StatusName(st)
print(f"STATUS={name}")
if name in ("OPTIMAL", "FEASIBLE"):
    print(f"min_edits={int(sv.ObjectiveValue())} "
          f"({'PROVEN minimal' if name == 'OPTIMAL' else 'upper bound'})")
    EN = "BLR"
    ipats = {v: k for k, v in pid.items()}
    for i in range(n):
        t = group[sv.Value(tv[i])]
        r = sv.Value(rv[i])
        for j in range(3):
            if sv.Value(df[i][j]):
                te = (j + r) % 3
                print(f"  EDIT: tile {t+1} edge {EN[te]}: recorded "
                      f"{white[t][te]} -> used {ipats[sv.Value(act[i][j])]}")
