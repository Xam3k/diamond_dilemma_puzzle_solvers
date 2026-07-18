"""Solve a colored (white-line) challenge: place a tile GROUP on a face region so
white lines match on internal edges AND no white line exits (boundary tile-edges
must be blank). Exact satisfaction first; if infeasible, minimize violated
constraints to localize remaining data errors.

Usage: python cp_white_challenge.py <faces> <tilelo> <tilehi> [wall] [maxsol]
  e.g. python cp_white_challenge.py T0,T1 0 32 120 4   (silver on shape T-T)
Tiles are 0-based [tilelo,tilehi). White patterns from whites.txt.
"""
import json, re, sys, time
from ortools.sat.python import cp_model

faces = sys.argv[1].split(",")
tlo, thi = int(sys.argv[2]), int(sys.argv[3])
wall = float(sys.argv[4]) if len(sys.argv) > 4 else 120.0
max_sols = int(sys.argv[5]) if len(sys.argv) > 5 else 4

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
assert n == len(group), f"{n} slots vs {len(group)} tiles"

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
print(f"region {faces}: {n} slots, {len(internal)} internal edges, "
      f"{len(boundary)} boundary sides", flush=True)

pats = sorted({white[t][e] for t in group for e in range(3)} |
              {rev(white[t][e]) for t in group for e in range(3)} | {ZERO})
pid = {p: i for i, p in enumerate(pats)}
rid = [pid.get(rev(p), -1) for p in pats]

def build(soft):
    m = cp_model.CpModel()
    tv = [m.NewIntVar(0, n - 1, "") for _ in range(n)]
    rv = [m.NewIntVar(0, 2, "") for _ in range(n)]
    pe = [[m.NewIntVar(0, len(pats) - 1, "") for _ in range(3)] for _ in range(n)]
    m.AddAllDifferent(tv)
    link = []
    for li, t in enumerate(group):
        for r in range(3):
            link.append((li, r, pid[white[t][(0 + r) % 3]],
                         pid[white[t][(1 + r) % 3]], pid[white[t][(2 + r) % 3]]))
    for i in range(n):
        m.AddAllowedAssignments([tv[i], rv[i], pe[i][0], pe[i][1], pe[i][2]], link)
    viol = []
    ok_pairs = [(a, b) for a in range(len(pats)) for b in range(len(pats))
                if rid[a] == b]
    for (sA, eA, sB, eB) in internal:
        if soft:
            v = m.NewBoolVar("")
            tbl_ok = m.NewBoolVar("")
            m.AddAllowedAssignments([pe[sidx[sA]][eA], pe[sidx[sB]][eB]],
                                    ok_pairs).OnlyEnforceIf(tbl_ok)
            m.AddForbiddenAssignments([pe[sidx[sA]][eA], pe[sidx[sB]][eB]],
                                      ok_pairs).OnlyEnforceIf(tbl_ok.Not())
            m.Add(v == 1).OnlyEnforceIf(tbl_ok.Not())
            m.Add(v == 0).OnlyEnforceIf(tbl_ok)
            viol.append(v)
        else:
            m.AddAllowedAssignments([pe[sidx[sA]][eA], pe[sidx[sB]][eB]], ok_pairs)
    for (sA, eA) in boundary:
        if soft:
            v = m.NewBoolVar("")
            m.Add(pe[sidx[sA]][eA] == pid[ZERO]).OnlyEnforceIf(v.Not())
            m.Add(pe[sidx[sA]][eA] != pid[ZERO]).OnlyEnforceIf(v)
            viol.append(v)
        else:
            m.Add(pe[sidx[sA]][eA] == pid[ZERO])
    if soft:
        m.Minimize(sum(viol))
    return m, tv, rv, viol

class Coll(cp_model.CpSolverSolutionCallback):
    def __init__(self, tv, rv):
        super().__init__()
        self.tv, self.rv = tv, rv
        self.sols = []
    def on_solution_callback(self):
        self.sols.append([(slots[i], group[self.Value(self.tv[i])],
                           self.Value(self.rv[i])) for i in range(n)])
        print(f"  SOLUTION {len(self.sols)}", flush=True)
        if len(self.sols) >= max_sols:
            self.StopSearch()

# exact
m, tv, rv, _ = build(soft=False)
sv = cp_model.CpSolver()
sv.parameters.max_time_in_seconds = wall
sv.parameters.num_search_workers = 8
sv.parameters.cp_model_probing_level = 0
sv.parameters.enumerate_all_solutions = True
cb = Coll(tv, rv)
st = sv.Solve(m, cb)
print(f"EXACT: {sv.StatusName(st)} solutions={len(cb.sols)}", flush=True)
for k, sol in enumerate(cb.sols):
    with open(f"white_{'_'.join(faces)}_{tlo}_{thi}_sol{k+1}.txt", "w") as f:
        f.write(" ".join(f"{s}:{t}:{r}" for s, t, r in sol) + "\n")

if not cb.sols:
    m2, tv2, rv2, viol = build(soft=True)
    sv2 = cp_model.CpSolver()
    sv2.parameters.max_time_in_seconds = wall
    sv2.parameters.num_search_workers = 8
    sv2.parameters.cp_model_probing_level = 0
    st2 = sv2.Solve(m2)
    if sv2.StatusName(st2) in ("OPTIMAL", "FEASIBLE"):
        print(f"SOFT: {sv2.StatusName(st2)} min_violations="
              f"{int(sv2.ObjectiveValue())} of {len(viol)} constraints", flush=True)
    else:
        print(f"SOFT: {sv2.StatusName(st2)}", flush=True)
