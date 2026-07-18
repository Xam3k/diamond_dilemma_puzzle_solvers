"""CP-SAT attack on Diamond Dilemma matching instances (channeled formulation).

Variables (all small-domain):
  tile_of[s] in 0..159   -- which tile sits in slot s
  rot[s]     in 0..2      -- its rotation
  pe[s][j]   in 0..P-1    -- pattern-id placed on slot s's edge j
Constraints:
  - AllDifferent(tile_of)                         (each tile used once)
  - table [tile_of[s],rot[s],pe[s][j]]            (links placement to its 3 edge patterns)
  - for each board edge (A,j)|(B,k):  pe[A][j] == rev_id[ pe[B][k] ]   via AddElement
    (the two sides of a shared edge carry reverse patterns -> a match)
  - symmetry breaking: seed tile only in seed slots (skipped when all slots are seeds)

Pattern-ids keep domains ~83 instead of 480, so presolve stays cheap. CP-SAT gives
native time limits, multi-core search, and a solution callback for enumeration.

Usage: python cp_solver.py <instance.txt> [max_solutions] [wall_seconds] [workers]
Solutions appended to <instance>.cp_solutions.txt: "slot:tile:rot ..." per line.
INFEASIBLE on gold = no complete edge matching exists = Gold challenge impossible.
"""
import sys, time
from collections import defaultdict
from ortools.sat.python import cp_model
from sat_solver import load_instance


class Collector(cp_model.CpSolverSolutionCallback):
    def __init__(self, tile_of, rot, n, out_path, max_sols):
        super().__init__()
        self.tile_of, self.rot, self.n = tile_of, rot, n
        self.out_path, self.max_sols = out_path, max_sols
        self.count = 0
        self.t0 = time.time()

    def on_solution_callback(self):
        line = " ".join(f"{s}:{self.Value(self.tile_of[s])}:{self.Value(self.rot[s])}"
                         for s in range(self.n))
        with open(self.out_path, "a") as f:
            f.write(line + "\n")
        self.count += 1
        print(f"[{time.strftime('%H:%M:%S')}] SOLUTION {self.count} "
              f"at t={time.time()-self.t0:.0f}s -> {self.out_path}", flush=True)
        if self.count >= self.max_sols:
            self.StopSearch()


def main():
    inst = sys.argv[1]
    max_sols = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    wall = float(sys.argv[3]) if len(sys.argv) > 3 else 1800.0
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    verbose = "-v" in sys.argv
    n, adj, tiles, seed_slots, seed_tile = load_instance(inst)
    rev = lambda p: p[::-1]
    t0 = time.time()

    # pattern-id table
    pats = sorted({tiles[t][e] for t in range(n) for e in range(3)} |
                  {rev(tiles[t][e]) for t in range(n) for e in range(3)})
    pid = {p: i for i, p in enumerate(pats)}
    P = len(pats)
    rev_id = [pid[rev(p)] for p in pats]   # rev_id[i] = id of reverse of pattern i

    m = cp_model.CpModel()
    tile_of = [m.NewIntVar(0, n - 1, f"t{s}") for s in range(n)]
    rot = [m.NewIntVar(0, 2, f"r{s}") for s in range(n)]
    pe = [[m.NewIntVar(0, P - 1, f"pe{s}_{j}") for j in range(3)] for s in range(n)]
    m.AddAllDifferent(tile_of)

    # link placement -> edge patterns (same table reused for all slots)
    link_table = []
    for t in range(n):
        for r in range(3):
            link_table.append((t, r,
                               pid[tiles[t][(0 + r) % 3]],
                               pid[tiles[t][(1 + r) % 3]],
                               pid[tiles[t][(2 + r) % 3]]))
    for s in range(n):
        m.AddAllowedAssignments([tile_of[s], rot[s], pe[s][0], pe[s][1], pe[s][2]],
                                link_table)

    # cross-edge reverse-compatibility via Element: pe[A][j] == rev_id[pe[B][k]]
    seen = set()
    n_edges = 0
    board_edges = []
    for s in range(n):
        for j in range(3):
            b, k = adj[s][j]
            key = (min((s, j), (b, k)), max((s, j), (b, k)))
            if key in seen:
                continue
            seen.add(key)
            m.AddElement(pe[b][k], rev_id, pe[s][j])
            board_edges.append((s, j))
            n_edges += 1

    # (Removed a redundant blank-cardinality constraint: the Element matching already
    # forces blank<->blank, so "exactly 23 blank board edges" is automatic -- it added
    # only presolve overhead, no pruning.)

    if len(seed_slots) < n:
        allowed = set(seed_slots)
        for s in range(n):
            if s not in allowed:
                m.Add(tile_of[s] != seed_tile)

    print(f"[{time.strftime('%H:%M:%S')}] model built: {n} slots, {P} patterns, "
          f"{n_edges} edges, link_table={len(link_table)} rows, in {time.time()-t0:.1f}s",
          flush=True)

    out_path = inst.replace(".txt", "") + ".cp_solutions.txt"
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = wall
    solver.parameters.num_search_workers = workers
    # The default probing presolve churns for minutes on the table-expanded
    # Boolean encoding without reaching search; disable it. The CDCL/LNS core
    # is strong on its own.
    solver.parameters.cp_model_probing_level = 0
    if verbose:
        solver.parameters.log_search_progress = True
        solver.parameters.log_to_stdout = True
    cb = Collector(tile_of, rot, n, out_path, max_sols)
    status = solver.Solve(m, cb)
    sname = solver.StatusName(status)
    print(f"[{time.strftime('%H:%M:%S')}] STATUS={sname} solutions={cb.count} "
          f"elapsed={time.time()-t0:.0f}s conflicts={solver.NumConflicts()} "
          f"branches={solver.NumBranches()} walltime={solver.WallTime():.0f}s", flush=True)
    if sname == "INFEASIBLE" and cb.count == 0:
        print(">>> NO complete edge matching exists -> GOLD IMPOSSIBLE", flush=True)


if __name__ == "__main__":
    main()
