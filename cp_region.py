"""Region-hypothesis test: can a tile GROUP gold-match a face subset, equator open?

Hypothesis: the designed gold solution places silver (32) on 2 faces, red (48) on 3,
blue (80) on the 5 faces of one pyramid — mirroring the colored challenges. Data file
assumed ordered silver(0-31), red(32-79), blue(80-159).

Model: slots = subset faces' 16 slots each; constrain ONLY edges internal to the
subset (boundary edges to other faces are left free); AllDifferent tile assignment
from the given group; channeled pattern-id model like cp_solver.

Usage: python cp_region.py <faces> <tilelo> <tilehi> [wall] [workers] [maxsol]
  e.g.  python cp_region.py T0,T1,T2,T3,T4 80 160 600 8 2
"""
import json, sys, time
from collections import defaultdict
from ortools.sat.python import cp_model

faces = sys.argv[1].split(",")
tlo, thi = int(sys.argv[2]), int(sys.argv[3])
wall = float(sys.argv[4]) if len(sys.argv) > 4 else 600.0
workers = int(sys.argv[5]) if len(sys.argv) > 5 else 8
max_sols = int(sys.argv[6]) if len(sys.argv) > 6 else 1

g = json.load(open("geometry.json"))
tiles_all = json.load(open("tiles.json"))
rev = lambda p: p[::-1]

slots = [s["idx"] for s in g["slots"] if s["face"] in faces]
sset = set(slots)
sidx = {s: i for i, s in enumerate(slots)}          # global slot -> local index
group = list(range(tlo, thi))                        # global tile ids
gidx = {t: i for i, t in enumerate(group)}
n = len(slots)
assert n == len(group), f"slots {n} != tiles {len(group)}"

# internal edges of the region
edges = [(e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]) for e in g["edges"]
         if e["slotA"] in sset and e["slotB"] in sset]
print(f"region {faces}: {n} slots, {len(edges)} internal edges, tiles [{tlo},{thi})",
      flush=True)

pats = sorted({tiles_all[t][e] for t in group for e in range(3)} |
              {rev(tiles_all[t][e]) for t in group for e in range(3)})
pid = {p: i for i, p in enumerate(pats)}
P = len(pats)
rev_id = [pid[rev(p)] for p in pats]

m = cp_model.CpModel()
tile_of = [m.NewIntVar(0, n - 1, f"t{i}") for i in range(n)]   # local tile index
rot = [m.NewIntVar(0, 2, f"r{i}") for i in range(n)]
pe = [[m.NewIntVar(0, P - 1, f"pe{i}_{j}") for j in range(3)] for i in range(n)]
m.AddAllDifferent(tile_of)
link = []
for li, t in enumerate(group):
    for r in range(3):
        link.append((li, r, pid[tiles_all[t][(0 + r) % 3]],
                     pid[tiles_all[t][(1 + r) % 3]], pid[tiles_all[t][(2 + r) % 3]]))
for i in range(n):
    m.AddAllowedAssignments([tile_of[i], rot[i], pe[i][0], pe[i][1], pe[i][2]], link)
for (sA, eA, sB, eB) in edges:
    m.AddElement(pe[sidx[sB]][eB], rev_id, pe[sidx[sA]][eA])


class Collect(cp_model.CpSolverSolutionCallback):
    def __init__(self):
        super().__init__()
        self.count = 0
        self.t0 = time.time()

    def on_solution_callback(self):
        self.count += 1
        line = " ".join(
            f"{slots[i]}:{group[self.Value(tile_of[i])]}:{self.Value(rot[i])}"
            for i in range(n))
        with open(f"region_{'_'.join(faces)}_{tlo}_{thi}.solutions.txt", "a") as f:
            f.write(line + "\n")
        print(f"[{time.strftime('%H:%M:%S')}] REGION SOLUTION {self.count} "
              f"t={time.time()-self.t0:.0f}s", flush=True)
        if self.count >= max_sols:
            self.StopSearch()


solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = wall
solver.parameters.num_search_workers = workers
solver.parameters.cp_model_probing_level = 0
cb = Collect()
t0 = time.time()
status = solver.Solve(m, cb)
print(f"[{time.strftime('%H:%M:%S')}] STATUS={solver.StatusName(status)} "
      f"solutions={cb.count} t={time.time()-t0:.0f}s "
      f"conflicts={solver.NumConflicts()} branches={solver.NumBranches()}", flush=True)
if solver.StatusName(status) == "INFEASIBLE":
    print(">>> group CANNOT gold-match this region (hypothesis refuted for this "
          "grouping/region)", flush=True)
