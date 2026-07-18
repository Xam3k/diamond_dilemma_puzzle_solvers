"""Systematic region-hypothesis sweep.

Face-adjacency graph of the bipyramid = pentagonal prism: Ti~Ti+1, Bi~Bi+1, Ti~Bi.
Hypothesis family: the designed gold solution confines silver (tiles 0-31) to a
connected 2-face region, red (32-79) to a connected 3-face region, blue (80-159) to a
connected 5-face region, partitioning the 10 faces.

Enumerate ALL connected (2,3,5) partitions, dedup by the order-10 rotation group,
then CP-SAT-test each component (cheapest first: silver, red, blue) with caching.
A component test constrains only region-internal edges (boundaries open) -> INFEASIBLE
is a proof that the color group cannot tile that region shape.

Usage: python partition_test.py [wall_per_test]
"""
import json, sys, time
from collections import defaultdict
from ortools.sat.python import cp_model

wall = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
T = [f"T{i}" for i in range(5)]
B = [f"B{i}" for i in range(5)]
FACES = T + B
FADJ = defaultdict(set)
for i in range(5):
    FADJ[T[i]] |= {T[(i + 1) % 5], T[(i - 1) % 5], B[i]}
    FADJ[B[i]] |= {B[(i + 1) % 5], B[(i - 1) % 5], T[i]}

# rotation group (order 10) acting on faces: rho^k and rho^k * tau
def rho(f):
    k = int(f[1]); return f[0] + str((k + 1) % 5)
def tau(f):
    k = int(f[1]); return ("B" if f[0] == "T" else "T") + str((-k - 1) % 5)
GROUP = []
for k in range(5):
    def mk(k=k, flip=False):
        def g(f):
            for _ in range(k):
                f = rho(f)
            return tau(f) if flip else f
        return g
    GROUP.append(mk(k, False)); GROUP.append(mk(k, True))

def canon(fs):
    return min(tuple(sorted(g(f) for f in fs)) for g in GROUP)

def connected(fs):
    fs = set(fs)
    if not fs:
        return False
    seen = {next(iter(fs))}
    stack = [next(iter(fs))]
    while stack:
        x = stack.pop()
        for y in FADJ[x]:
            if y in fs and y not in seen:
                seen.add(y); stack.append(y)
    return seen == fs

from itertools import combinations
# enumerate partitions: choose silver-2 connected, red-3 connected from rest,
# blue-5 = remainder connected
partitions = []
seen_part = set()
for s2 in combinations(FACES, 2):
    if not connected(s2):
        continue
    rest1 = [f for f in FACES if f not in s2]
    for r3 in combinations(rest1, 3):
        if not connected(r3):
            continue
        b5 = tuple(f for f in rest1 if f not in r3)
        if not connected(b5):
            continue
        # canonical form of the whole partition under the group
        pk = min(tuple((tuple(sorted(g(f) for f in s2)),
                        tuple(sorted(g(f) for f in r3)),
                        tuple(sorted(g(f) for f in b5)))) for g in GROUP)
        if pk in seen_part:
            continue
        seen_part.add(pk)
        partitions.append((tuple(sorted(s2)), tuple(sorted(r3)), tuple(sorted(b5))))
print(f"connected (2,3,5) partitions up to symmetry: {len(partitions)}", flush=True)

# region test with caching by (canonical faceset, group)
g_geo = json.load(open("geometry.json"))
tiles_all = json.load(open("tiles.json"))
rev = lambda p: p[::-1]
slot_face = {s["idx"]: s["face"] for s in g_geo["slots"]}
cache = {}

def test_region(faces, tlo, thi):
    key = (canon(faces), tlo, thi)
    if key in cache:
        return cache[key]
    fs = set(faces)
    slots = [i for i in range(160) if slot_face[i] in fs]
    group = list(range(tlo, thi))
    sidx = {s: i for i, s in enumerate(slots)}
    n = len(slots)
    edges = [(e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]) for e in g_geo["edges"]
             if e["slotA"] in sidx and e["slotB"] in sidx]
    pats = sorted({tiles_all[t][e] for t in group for e in range(3)} |
                  {rev(tiles_all[t][e]) for t in group for e in range(3)})
    pid = {p: i for i, p in enumerate(pats)}
    rid = [pid[rev(p)] for p in pats]
    m = cp_model.CpModel()
    tv = [m.NewIntVar(0, n - 1, "") for _ in range(n)]
    rv = [m.NewIntVar(0, 2, "") for _ in range(n)]
    pe = [[m.NewIntVar(0, len(pats) - 1, "") for _ in range(3)] for _ in range(n)]
    m.AddAllDifferent(tv)
    link = []
    for li, t in enumerate(group):
        for r in range(3):
            link.append((li, r, pid[tiles_all[t][(0 + r) % 3]],
                         pid[tiles_all[t][(1 + r) % 3]], pid[tiles_all[t][(2 + r) % 3]]))
    for i in range(n):
        m.AddAllowedAssignments([tv[i], rv[i], pe[i][0], pe[i][1], pe[i][2]], link)
    for (sA, eA, sB, eB) in edges:
        m.AddElement(pe[sidx[sB]][eB], rid, pe[sidx[sA]][eA])
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = wall
    sv.parameters.num_search_workers = 8
    sv.parameters.cp_model_probing_level = 0
    st = sv.StatusName(sv.Solve(m))
    cache[key] = st
    return st

# sweep: silver first (cheapest), short-circuit
t0 = time.time()
alive = []
for (s2, r3, b5) in partitions:
    st_s = test_region(s2, 0, 32)
    if st_s == "INFEASIBLE":
        print(f"silver {s2}: INFEASIBLE -> partition dead", flush=True)
        continue
    st_r = test_region(r3, 32, 80)
    if st_r == "INFEASIBLE":
        print(f"silver {s2} ok; red {r3}: INFEASIBLE -> dead", flush=True)
        continue
    st_b = test_region(b5, 80, 160)
    print(f"PARTITION s={s2} r={r3} b={b5}: silver={st_s} red={st_r} blue={st_b}",
          flush=True)
    if st_b != "INFEASIBLE":
        alive.append((s2, r3, b5, st_s, st_r, st_b))
print(f"\nSURVIVING partitions: {len(alive)} (t={time.time()-t0:.0f}s)", flush=True)
for a in alive:
    print("  ", a, flush=True)
