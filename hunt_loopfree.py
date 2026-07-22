"""hunt_loopfree.py -- search for the best LOOP-FEASIBLE board (Category C).

135 is the largest loop-free sub-board of the specific 142-tile record, but a
DIFFERENT perfectly-matched board (same 142 score, different tile arrangement)
can have a loop structure whose loop-free extraction is larger. This walks the
plateau of high-scoring perfectly-matched boards with ruin-and-recreate, and
at every board evaluates the greedy loop-free extraction, keeping the best.

The repair maximizes tiles placed (perfect matching) exactly like
ruin_recreate; the novelty is the SECONDARY objective evaluated on each
result: len(loopfree_greedy(board)). Accept a move if it does not lower the
matched-tile score (plateau diversification), so the walk keeps exploring
142-configs while the loop-free best ratchets up.

Usage:  python hunt_loopfree.py <start_perfect_board> <wall_s> [sub_s]
Env:    HL_WORKERS(4) HL_MAXF(16) HL_SEED HL_OUT(loopfree_best.txt)
"""
import json
import os
import random
import sys
import time

from ortools.sat.python import cp_model
from loops_lib import loopfree_greedy, count_closed

start_file = sys.argv[1]
wall = float(sys.argv[2]) if len(sys.argv) > 2 else 1800.0
sub_wall = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
WORKERS = int(os.environ.get("HL_WORKERS", "4"))
MAXF = int(os.environ.get("HL_MAXF", "16"))
OUT = os.environ.get("HL_OUT", "loopfree_best.txt")
rng = random.Random(int(os.environ.get("HL_SEED", "1")))

g = json.load(open("geometry.json"))
tiles = json.load(open("tiles.json"))
rev = lambda p: p[::-1]
n = 160
adj = [[None] * 3 for _ in range(n)]
for e in g["edges"]:
    adj[e["slotA"]][e["edgeA"]] = (e["slotB"], e["edgeB"])
    adj[e["slotB"]][e["edgeB"]] = (e["slotA"], e["edgeA"])

cur = {}
for tok in open(start_file).read().split():
    s, t, r = map(int, tok.split(":"))
    cur[s] = (t, r)
cur_lf = len(loopfree_greedy(cur))

def loopfree_len(board):
    return len(loopfree_greedy(board))

base = dict(cur); base_lf = loopfree_len(cur)
stuck = 0
best_lf = loopfree_len(cur)
best_lf_board = loopfree_greedy(cur)
print(f"start: {len(cur)} tiles, loop-free extraction {best_lf}", flush=True)

def neighborhood():
    empty = [s for s in range(n) if s not in cur]
    # centre the ruin on tiles that lie on closed loops (breaking/reshaping
    # loops is exactly what changes the loop-free extraction), else random.
    from loops_lib import closed_loop_slots
    loops = list(closed_loop_slots(cur))
    if loops and rng.random() < 0.6:
        centers = rng.sample(loops, min(rng.choice([2, 3, 4]), len(loops)))
    else:
        pool = empty if empty else list(range(n))
        centers = rng.sample(pool, min(rng.choice([3, 4]), len(pool)))
    F = set(centers)
    for _ in range(2):
        F |= {adj[s][j][0] for s in list(F) for j in range(3)}
    F = list(F)
    if len(F) > MAXF:
        F = rng.sample(F, MAXF)
    return sorted(F)

pats = sorted({p for t in range(n) for p in tiles[t]} |
              {rev(p) for t in range(n) for p in tiles[t]})
pid = {p: i for i, p in enumerate(pats)}
P = len(pats)

t0 = time.time()
it = 0
while time.time() - t0 < wall and best_lf < 160:
    it += 1
    Fl = neighborhood()
    Fset = set(Fl)
    fi = {s: i for i, s in enumerate(Fl)}
    avail = [t for t in range(n) if t not in {v[0] for s, v in cur.items() if s not in Fset}]
    nf, na = len(Fl), len(avail)
    ai = {t: k for k, t in enumerate(avail)}

    m = cp_model.CpModel()
    place = [m.NewBoolVar("") for _ in range(nf)]
    tv = [m.NewIntVar(0, na - 1, "") for _ in range(nf)]
    rv = [m.NewIntVar(0, 2, "") for _ in range(nf)]
    pe = [[m.NewIntVar(0, P - 1, "") for _ in range(3)] for _ in range(nf)]
    ep = [[m.NewIntVar(0, P, "") for _ in range(3)] for _ in range(nf)]
    v = [m.NewIntVar(0, na + nf, "") for _ in range(nf)]
    for i in range(nf):
        m.Add(v[i] == tv[i]).OnlyEnforceIf(place[i])
        m.Add(v[i] == na + i).OnlyEnforceIf(place[i].Not())
    m.AddAllDifferent(v)
    link = []
    for k, t in enumerate(avail):
        for r in range(3):
            link.append((k, r, pid[tiles[t][r % 3]], pid[tiles[t][(1 + r) % 3]],
                         pid[tiles[t][(2 + r) % 3]]))
    for i in range(nf):
        m.AddAllowedAssignments([tv[i], rv[i], pe[i][0], pe[i][1], pe[i][2]], link)
        for j in range(3):
            m.Add(ep[i][j] == pe[i][j]).OnlyEnforceIf(place[i])
            m.Add(ep[i][j] == P).OnlyEnforceIf(place[i].Not())
    seen = set()
    for s in Fl:
        for j in range(3):
            b, k = adj[s][j]
            if b in Fset:
                key = (min((s, j), (b, k)), max((s, j), (b, k)))
                if key in seen:
                    continue
                seen.add(key)
                tbl = [(a, c) for a in range(P + 1) for c in range(P + 1)
                       if a == P or c == P or pats[a] == rev(pats[c])]
                m.AddAllowedAssignments([ep[fi[s]][j], ep[fi[b]][k]], tbl)
            elif b in cur:
                tb, rb = cur[b]
                need = pid[rev(tiles[tb][(k + rb) % 3])]
                m.AddAllowedAssignments([ep[fi[s]][j]], [(need,), (P,)])
    for i, s in enumerate(Fl):
        if s in cur and cur[s][0] in ai:
            m.AddHint(place[i], 1); m.AddHint(tv[i], ai[cur[s][0]]); m.AddHint(rv[i], cur[s][1])
        else:
            m.AddHint(place[i], 0)
    m.Maximize(sum(place))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = sub_wall
    sv.parameters.num_search_workers = WORKERS
    sv.parameters.cp_model_probing_level = 0
    sv.parameters.random_seed = rng.randrange(1 << 30)
    st = sv.Solve(m)
    if sv.StatusName(st) not in ("OPTIMAL", "FEASIBLE"):
        continue
    cand = {s: cur[s] for s in cur if s not in Fset}
    for i, s in enumerate(Fl):
        if sv.Value(place[i]):
            cand[s] = (avail[sv.Value(tv[i])], sv.Value(rv[i]))
    lf = loopfree_len(cand)
    # accept on the LOOP-FREE objective itself (plateau moves allowed); the
    # matched-tile count may rise or fall as long as the loop-free extraction
    # does not shrink.
    if lf < cur_lf:
        stuck += 1
        if stuck >= 60:                # kick: jump to a fresh 142 board region
            stuck = 0
            cur = dict(base); cur_lf = base_lf
        continue
    stuck = 0
    cur = cand
    cur_lf = lf
    if lf > best_lf:
        best_lf = lf
        best_lf_board = loopfree_greedy(cand)
        with open(OUT, "w") as f:
            f.write(" ".join(f"{s}:{best_lf_board[s][0]}:{best_lf_board[s][1]}"
                             for s in sorted(best_lf_board)) + "\n")
        print(f"it{it}: LOOP-FREE IMPROVED -> {best_lf}/160 "
              f"(from a {len(cand)}-tile board, {count_closed(cand)} loops, "
              f"t={time.time()-t0:.0f}s)", flush=True)

print(f"DONE best loop-free={best_lf}/160 iters={it} t={time.time()-t0:.0f}s", flush=True)
