"""rr_edges.py -- CP-SAT large-neighborhood solver for the E2-STYLE score:
maximize MATCHED EDGES on a FULL 160-tile board (mismatches allowed).

Why: tabu (single swap/rotate moves) stalls within seconds at a shallow local
minimum (190/240 warm). This solver instead frees a whole neighborhood of
slots and re-places its tiles OPTIMALLY (CP-SAT, AllDifferent permutation,
objective = matched edges touching the region) -- the large-neighborhood
escape that single-move local search lacks.

Also attacks the no-mismatch category automatically: after every new best-B
board, extract a perfect partial (greedy vertex cover on mismatched edges);
if it beats the incumbent Category-A record it is saved separately.

Neighborhoods: mismatch-guided ring (default), random ring, occasional
2-face region. Region size capped so every subsolve finishes.

Usage:  python rr_edges.py <start_full_board> <wall_s> [sub_s]
Env:    RE_WORKERS (8) RE_MAXF (26) RE_SEED RE_OUT (edges_best.txt)
        RE_A_OUT (rr_bestA_from_edges.txt)
"""
import json
import os
import random
import sys
import time

from ortools.sat.python import cp_model

start_file = sys.argv[1]
wall = float(sys.argv[2]) if len(sys.argv) > 2 else 1800.0
sub_wall = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
WORKERS = int(os.environ.get("RE_WORKERS", "8"))
MAXF = int(os.environ.get("RE_MAXF", "26"))
OUT = os.environ.get("RE_OUT", "edges_best.txt")
A_OUT = os.environ.get("RE_A_OUT", "rr_bestA_from_edges.txt")
rng = random.Random(int(os.environ.get("RE_SEED", "1")))

g = json.load(open("geometry.json"))
tiles = json.load(open("tiles.json"))
rev = lambda p: p[::-1]
n = 160
adj = [[None] * 3 for _ in range(n)]
EDGES = []
for e in g["edges"]:
    adj[e["slotA"]][e["edgeA"]] = (e["slotB"], e["edgeB"])
    adj[e["slotB"]][e["edgeB"]] = (e["slotA"], e["edgeA"])
    EDGES.append((e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]))

cur = {}
for tok in open(start_file).read().split():
    s, t, r = map(int, tok.split(":"))
    cur[s] = (t, r)
assert len(cur) == n, "start board must be FULL (160 slots)"

def pat(board, s, j):
    t, r = board[s]
    return tiles[t][(j + r) % 3]

def score(board):
    return sum(1 for a, ja, b, jb in EDGES if pat(board, a, ja) == rev(pat(board, b, jb)))

def mismatches(board):
    return [(a, ja, b, jb) for a, ja, b, jb in EDGES
            if pat(board, a, ja) != rev(pat(board, b, jb))]

def extract_perfect(board):
    """Greedy vertex cover on the mismatch graph -> perfect partial."""
    mis = mismatches(board)
    deg = {}
    for a, _, b, _ in mis:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    removed = set()
    for a, _, b, _ in sorted(mis, key=lambda m: -(deg[m[0]] + deg[m[2]])):
        if a in removed or b in removed:
            continue
        removed.add(a if deg[a] >= deg[b] else b)
    return {s: board[s] for s in board if s not in removed}

def save(board, path):
    with open(path, "w") as f:
        f.write(" ".join(f"{s}:{board[s][0]}:{board[s][1]}" for s in sorted(board)) + "\n")

GUIDE = {}
if os.environ.get("RE_GUIDE"):
    for tok in open(os.environ["RE_GUIDE"]).read().split():
        s, t, r = map(int, tok.split(":"))
        GUIDE[s] = (t, r)

def neighborhood():
    mis = mismatches(cur)
    roll = rng.random()
    # path relinking: center the ruin where cur disagrees with the guide
    # board, so optimal repair walks the incumbent toward the other basin.
    if GUIDE and roll < 0.4:
        diff = [s for s in range(n) if GUIDE.get(s) and cur[s] != GUIDE[s]]
        if diff:
            centers = rng.sample(diff, min(rng.choice([3, 4, 5]), len(diff)))
        else:
            centers = rng.sample(range(n), 4)
    elif mis and roll < 0.8:          # mismatch-guided ring
        a, _, b, _ = rng.choice(mis)
        centers = [a, b]
        extra = rng.sample(mis, min(len(mis), rng.choice([1, 2, 3])))
        for m in extra:
            centers += [m[0], m[2]]
    else:                              # random ring
        centers = rng.sample(range(n), rng.choice([3, 4, 5]))
    F = set(centers)
    for _ in range(2):
        F |= {adj[s][j][0] for s in list(F) for j in range(3)}
    F = list(F)
    if len(F) > MAXF:
        F = rng.sample(F, MAXF)
    return sorted(F)

best_board = dict(cur)
best_score = score(cur)
bestA = 142  # incumbent Category-A record (rr_best.txt) -- only save if beaten
print(f"start: B={best_score}/240 from {start_file}", flush=True)

t0 = time.time()
it = 0
cur_score = best_score
while time.time() - t0 < wall and best_score < 240:
    it += 1
    Fl = neighborhood()
    Fset = set(Fl)
    fi = {s: i for i, s in enumerate(Fl)}
    avail = [cur[s][0] for s in Fl]
    nf = len(Fl)

    pats = sorted({p for t in range(n) for p in tiles[t]} |
                  {rev(p) for t in range(n) for p in tiles[t]})
    pid = {p: i for i, p in enumerate(pats)}
    P = len(pats)

    m = cp_model.CpModel()
    tv = [m.NewIntVar(0, nf - 1, "") for _ in range(nf)]
    rv = [m.NewIntVar(0, 2, "") for _ in range(nf)]
    pe = [[m.NewIntVar(0, P - 1, "") for _ in range(3)] for _ in range(nf)]
    m.AddAllDifferent(tv)
    link = []
    for k, t in enumerate(avail):
        for r in range(3):
            link.append((k, r, pid[tiles[t][(0 + r) % 3]],
                         pid[tiles[t][(1 + r) % 3]], pid[tiles[t][(2 + r) % 3]]))
    for i in range(nf):
        m.AddAllowedAssignments([tv[i], rv[i], pe[i][0], pe[i][1], pe[i][2]], link)

    match_tbl = [(a, b, 1 if pats[a] == rev(pats[b]) else 0)
                 for a in range(P) for b in range(P)]
    mvars = []
    seen = set()
    for s in Fl:
        for j in range(3):
            b, k = adj[s][j]
            if b in Fset:
                key = (min((s, j), (b, k)), max((s, j), (b, k)))
                if key in seen:
                    continue
                seen.add(key)
                mv = m.NewBoolVar("")
                m.AddAllowedAssignments([pe[fi[s]][j], pe[fi[b]][k], mv], match_tbl)
                mvars.append(mv)
            else:
                need = pid[rev(pat(cur, b, k))]
                mv = m.NewBoolVar("")
                m.Add(pe[fi[s]][j] == need).OnlyEnforceIf(mv)
                m.Add(pe[fi[s]][j] != need).OnlyEnforceIf(mv.Not())
                mvars.append(mv)
    for i, s in enumerate(Fl):
        m.AddHint(tv[i], avail.index(cur[s][0]))
        m.AddHint(rv[i], cur[s][1])
    m.Maximize(sum(mvars))

    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = sub_wall
    sv.parameters.num_search_workers = WORKERS
    sv.parameters.cp_model_probing_level = 0
    sv.parameters.random_seed = rng.randrange(1 << 30)
    st = sv.Solve(m)
    if sv.StatusName(st) not in ("OPTIMAL", "FEASIBLE"):
        print(f"it{it}: F={nf} {sv.StatusName(st)} skip", flush=True)
        continue

    cand = dict(cur)
    for i, s in enumerate(Fl):
        cand[s] = (avail[sv.Value(tv[i])], sv.Value(rv[i]))
    new_score = score(cand)
    if new_score >= cur_score:
        cur = cand
        cur_score = new_score
        if new_score > best_score:
            best_score = new_score
            best_board = dict(cur)
            save(best_board, OUT)
            print(f"it{it}: B IMPROVED -> {best_score}/240 "
                  f"(mis={240 - best_score}, F={nf}, t={time.time() - t0:.0f}s)", flush=True)
            ext = extract_perfect(best_board)
            if len(ext) > bestA:
                bestA = len(ext)
                save(ext, A_OUT)
                print(f"*** CATEGORY-A RECORD: extracted {bestA}-tile PERFECT partial "
                      f"-> {A_OUT} ***", flush=True)
            if best_score == 240:
                print("*** 240/240 = FULL MATCHING FOUND ***", flush=True)

print(f"DONE B={best_score}/240 bestA_extracted<={bestA} iters={it} "
      f"t={time.time() - t0:.0f}s", flush=True)
