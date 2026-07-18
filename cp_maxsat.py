"""CP-SAT MAX-placement: place as many tiles as possible such that every edge between
two placed slots matches. Returns a concrete best partial (deepest partial matching)
and an upper bound -- the state-of-the-art metric the brief asks for (TILES_PLACED).

Model:
  place[s] in {0,1}                      -- slot s is filled
  tile_of[s] 0..n-1, rot[s] 0..2         -- placement (meaningful when placed)
  pe[s][j]   0..P-1                       -- real pattern on edge j (linked to tile,rot)
  epat[s][j] 0..P                         -- effective pattern: pe if placed, else P (wildcard)
  - each real tile used at most once: AllDifferent(v) where v=tile_of if placed else unique
  - per edge (A,j)|(B,k): allowed (epat[A][j],epat[B][k]) = wildcard on either side, or
    reverse-compatible real patterns
  maximize sum(place)

Usage: python cp_maxsat.py <instance.txt> [wall_seconds] [workers]
Writes best partial to <instance>.maxsat_partial.txt: "slot:tile:rot ..." (placed only).
"""
import sys, time
from ortools.sat.python import cp_model
from sat_solver import load_instance


class Best(cp_model.CpSolverSolutionCallback):
    def __init__(self, place, tile_of, rot, n, out_path):
        super().__init__()
        self.place, self.tile_of, self.rot, self.n = place, tile_of, rot, n
        self.out_path = out_path
        self.best = -1
        self.t0 = time.time()

    def on_solution_callback(self):
        k = sum(int(self.Value(self.place[s])) for s in range(self.n))
        if k > self.best:
            self.best = k
            placed = [(s, self.Value(self.tile_of[s]), self.Value(self.rot[s]))
                      for s in range(self.n) if self.Value(self.place[s])]
            with open(self.out_path, "w") as f:
                f.write(" ".join(f"{s}:{t}:{r}" for s, t, r in placed) + "\n")
            print(f"[{time.strftime('%H:%M:%S')}] placed={k}/{self.n} "
                  f"at t={time.time()-self.t0:.0f}s -> {self.out_path}", flush=True)


def main():
    inst = sys.argv[1]
    wall = float(sys.argv[2]) if len(sys.argv) > 2 else 1800.0
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    n, adj, tiles, seed_slots, seed_tile = load_instance(inst)
    rev = lambda p: p[::-1]
    t0 = time.time()

    pats = sorted({tiles[t][e] for t in range(n) for e in range(3)} |
                  {rev(tiles[t][e]) for t in range(n) for e in range(3)})
    pid = {p: i for i, p in enumerate(pats)}
    P = len(pats)               # wildcard sentinel = P

    m = cp_model.CpModel()
    place = [m.NewBoolVar(f"p{s}") for s in range(n)]
    tile_of = [m.NewIntVar(0, n - 1, f"t{s}") for s in range(n)]
    rot = [m.NewIntVar(0, 2, f"r{s}") for s in range(n)]
    pe = [[m.NewIntVar(0, P - 1, f"pe{s}_{j}") for j in range(3)] for s in range(n)]
    epat = [[m.NewIntVar(0, P, f"e{s}_{j}") for j in range(3)] for s in range(n)]

    # at-most-once per real tile: v[s] = tile_of[s] if placed else unique sentinel n+s
    v = [m.NewIntVar(0, 2 * n, f"v{s}") for s in range(n)]
    for s in range(n):
        m.Add(v[s] == tile_of[s]).OnlyEnforceIf(place[s])
        m.Add(v[s] == n + s).OnlyEnforceIf(place[s].Not())
    m.AddAllDifferent(v)

    # link tile,rot -> pe (reused table)
    link = []
    for t in range(n):
        for r in range(3):
            link.append((t, r, pid[tiles[t][(0 + r) % 3]],
                         pid[tiles[t][(1 + r) % 3]], pid[tiles[t][(2 + r) % 3]]))
    for s in range(n):
        m.AddAllowedAssignments([tile_of[s], rot[s], pe[s][0], pe[s][1], pe[s][2]], link)
        for j in range(3):
            m.Add(epat[s][j] == pe[s][j]).OnlyEnforceIf(place[s])
            m.Add(epat[s][j] == P).OnlyEnforceIf(place[s].Not())

    # edge table: wildcard on either side, or reverse-compatible
    etable = []
    for a in range(P + 1):
        for b in range(P + 1):
            if a == P or b == P or pats[a] == rev(pats[b]):
                etable.append((a, b))
    seen = set()
    for s in range(n):
        for j in range(3):
            b, k = adj[s][j]
            key = (min((s, j), (b, k)), max((s, j), (b, k)))
            if key in seen:
                continue
            seen.add(key)
            m.AddAllowedAssignments([epat[s][j], epat[b][k]], etable)

    if len(seed_slots) < n:
        allowed = set(seed_slots)
        for s in range(n):
            if s not in allowed:
                m.Add(tile_of[s] != seed_tile)

    # optional warm-start hint from a prior partial: "slot:tile:rot ..."
    hint_file = None
    for a in sys.argv[2:]:
        if a.endswith(".txt"):
            hint_file = a
    if hint_file:
        toks = open(hint_file).read().split()
        hinted = 0
        for tok in toks:
            s, t, r = map(int, tok.split(":"))
            m.AddHint(place[s], 1)
            m.AddHint(tile_of[s], t)
            m.AddHint(rot[s], r)
            hinted += 1
        print(f"[{time.strftime('%H:%M:%S')}] warm-start hint: {hinted} placed slots "
              f"from {hint_file}", flush=True)

    # decision strategy: try to place slots (place=1) first
    m.AddDecisionStrategy(place, cp_model.CHOOSE_FIRST, cp_model.SELECT_MAX_VALUE)

    m.Maximize(sum(place))
    print(f"[{time.strftime('%H:%M:%S')}] maxsat model built: {n} slots, {P} patterns, "
          f"{len(etable)} edge-table rows, in {time.time()-t0:.1f}s", flush=True)

    out_path = inst.replace(".txt", "") + ".maxsat_partial.txt"
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = wall
    solver.parameters.num_search_workers = workers
    solver.parameters.cp_model_probing_level = 0
    solver.parameters.log_search_progress = True
    solver.parameters.log_to_stdout = True
    cb = Best(place, tile_of, rot, n, out_path)
    status = solver.Solve(m, cb)
    sname = solver.StatusName(status)
    print(f"[{time.strftime('%H:%M:%S')}] STATUS={sname} best_placed={cb.best}/{n} "
          f"upper_bound={solver.BestObjectiveBound():.0f} elapsed={time.time()-t0:.0f}s "
          f"conflicts={solver.NumConflicts()} branches={solver.NumBranches()}", flush=True)
    if sname == "OPTIMAL" and cb.best == n:
        print(">>> FULL 160/160 matching exists (optimum). Loop-check needed for Gold.", flush=True)
    elif sname == "OPTIMAL":
        print(f">>> PROVEN: at most {cb.best}/160 tiles can form a valid partial matching "
              f"-> NO complete matching -> GOLD IMPOSSIBLE.", flush=True)


if __name__ == "__main__":
    main()
