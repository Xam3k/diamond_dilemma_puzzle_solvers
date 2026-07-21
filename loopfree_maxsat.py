"""loopfree_maxsat.py -- global CP-SAT max-placement with LAZY LOOP CUTS.

Finds the largest partial board that is simultaneously
  (a) perfectly matched  (every edge between two placed tiles matches), and
  (b) loop-feasible      (contains NO closed gold sub-loop),
which is the only kind of partial that could still grow into the real
single-loop solution.

Lazy subtour elimination: solve; if the incumbent contains a closed loop,
forbid exactly the (tile, rotation, placed) assignment of the slots carrying
that loop, and re-solve. Such a cut can never remove a loop-free board,
because any board sharing that sub-assignment necessarily contains the same
closed loop. Therefore:

  * a returned board with >= TARGET tiles is a genuine new record, and
  * INFEASIBLE at TARGET proves no loop-free board that large exists.

Usage: python loopfree_maxsat.py <start_board> <target> [wall_s] [workers]
"""
import json
import os
import sys
import time

from ortools.sat.python import cp_model
from loops_lib import count_closed, closed_loop_slots

start_file = sys.argv[1]
target = int(sys.argv[2])
wall = float(sys.argv[3]) if len(sys.argv) > 3 else 900.0
workers = int(sys.argv[4]) if len(sys.argv) > 4 else 8

g = json.load(open("geometry.json"))
tiles = json.load(open("tiles.json"))
rev = lambda p: p[::-1]
n = 160

hint = {}
for tok in open(start_file).read().split():
    s, t, r = map(int, tok.split(":"))
    hint[s] = (t, r)
print(f"start hint: {len(hint)} tiles, closed loops={count_closed(hint)}, target>={target}",
      flush=True)

pats = sorted({p for t in range(n) for p in tiles[t]} |
              {rev(p) for t in range(n) for p in tiles[t]})
pid = {p: i for i, p in enumerate(pats)}
P = len(pats)                      # P == wildcard (slot not placed)

m = cp_model.CpModel()
place = [m.NewBoolVar(f"p{s}") for s in range(n)]
tv = [m.NewIntVar(0, n - 1, f"t{s}") for s in range(n)]
rv = [m.NewIntVar(0, 2, f"r{s}") for s in range(n)]
pe = [[m.NewIntVar(0, P - 1, "") for _ in range(3)] for _ in range(n)]
ep = [[m.NewIntVar(0, P, "") for _ in range(3)] for _ in range(n)]
v = [m.NewIntVar(0, 2 * n, "") for _ in range(n)]
for s in range(n):
    m.Add(v[s] == tv[s]).OnlyEnforceIf(place[s])
    m.Add(v[s] == n + s).OnlyEnforceIf(place[s].Not())
m.AddAllDifferent(v)

link = []
for t in range(n):
    for r in range(3):
        link.append((t, r, pid[tiles[t][(0 + r) % 3]],
                     pid[tiles[t][(1 + r) % 3]], pid[tiles[t][(2 + r) % 3]]))
for s in range(n):
    m.AddAllowedAssignments([tv[s], rv[s], pe[s][0], pe[s][1], pe[s][2]], link)
    for j in range(3):
        m.Add(ep[s][j] == pe[s][j]).OnlyEnforceIf(place[s])
        m.Add(ep[s][j] == P).OnlyEnforceIf(place[s].Not())

etable = [(a, b) for a in range(P + 1) for b in range(P + 1)
          if a == P or b == P or pats[a] == rev(pats[b])]
for e in g["edges"]:
    m.AddAllowedAssignments([ep[e["slotA"]][e["edgeA"]], ep[e["slotB"]][e["edgeB"]]], etable)

m.Add(sum(place) >= target)
m.Maximize(sum(place))
for s in range(n):
    if s in hint:
        m.AddHint(place[s], 1); m.AddHint(tv[s], hint[s][0]); m.AddHint(rv[s], hint[s][1])
    else:
        m.AddHint(place[s], 0)

sv = cp_model.CpSolver()
sv.parameters.num_search_workers = workers
sv.parameters.cp_model_probing_level = 0

t0 = time.time()
cuts = 0
while True:
    left = wall - (time.time() - t0)
    if left <= 5:
        print(f"TIME OUT after {cuts} cuts (no verdict)", flush=True)
        break
    sv.parameters.max_time_in_seconds = left
    st = sv.Solve(m)
    name = sv.StatusName(st)
    if name == "INFEASIBLE":
        print(f"INFEASIBLE at >={target} after {cuts} loop cuts", flush=True)
        print(f"PROOF: no loop-free perfectly-matched board with >={target} tiles exists.",
              flush=True)
        break
    if name not in ("OPTIMAL", "FEASIBLE"):
        print(f"status={name} after {cuts} cuts (no verdict)", flush=True)
        break
    board = {s: (sv.Value(tv[s]), sv.Value(rv[s])) for s in range(n) if sv.Value(place[s])}
    nloops = count_closed(board)
    if nloops == 0:
        out = f"loopfree_{len(board)}.txt"
        with open(out, "w") as f:
            f.write(" ".join(f"{s}:{board[s][0]}:{board[s][1]}" for s in sorted(board)) + "\n")
        print(f"*** LOOP-FREE BOARD FOUND: {len(board)} tiles, 0 closed loops -> {out} "
              f"(after {cuts} cuts, {time.time()-t0:.0f}s) ***", flush=True)
        break
    bad = sorted(closed_loop_slots(board))
    vars_, tup = [], []
    for s in bad:
        vars_ += [tv[s], rv[s], place[s]]
        tup += [sv.Value(tv[s]), sv.Value(rv[s]), 1]
    m.AddForbiddenAssignments(vars_, [tuple(tup)])
    cuts += 1
    if cuts % 5 == 0:
        print(f"  {cuts} cuts, last board {len(board)} tiles / {nloops} loops, "
              f"{time.time()-t0:.0f}s", flush=True)
