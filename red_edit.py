"""Fixed-arrangement min-edit fit for RED against Jaap's solution (trapezoid fan,
rows 9/11/13/15). Sweeps net parameter variants; correct net should hit
min_edits=4 (the proven free-placement optimum on T0,T1,T2).
"""
import re
from ortools.sat.python import cp_model

GRID = [[55,54,79,34,71,46,57,43,74],
        [40,70,36,76,49,41,65,63,62,47,78],
        [59,64,58,69,51,33,53,75,67,35,56,37,44],
        [80,45,66,48,77,52,68,39,60,61,38,73,42,72,50]]
W = [9, 11, 13, 15]

white = []
for line in open("whites.txt"):
    m = re.findall(r"\b[01]{11}\b", line)
    if len(m) == 3:
        white.append(m)
rev = lambda p: p[::-1]
ZERO = "0" * 11

def build(up_par, d, chir):
    cells = [(r, k) for r in range(4) for k in range(W[r])]
    cid = {c: i for i, c in enumerate(cells)}
    N = len(cells)
    isup = lambda r, k: (k % 2) == up_par
    adj = []
    for r in range(4):
        for k in range(W[r] - 1):
            a, b = cid[(r, k)], cid[(r, k + 1)]
            if isup(r, k):
                sa, sb = (2, 2) if not chir else (1, 1)
            else:
                sa, sb = (1, 1) if not chir else (2, 2)
            adj.append((a, sa, b, sb))
    for r in range(1, 4):
        for k in range(W[r]):
            if not isup(r, k):
                kk = k + d
                if 0 <= kk < W[r - 1] and isup(r - 1, kk):
                    adj.append((cid[(r, k)], 0, cid[(r - 1, kk)], 0))
    if len(adj) != 62:
        return None
    used = set()
    for (a, sa, b, sb) in adj:
        used.add((a, sa)); used.add((b, sb))
    bound = [(i, s) for i in range(N) for s in range(3) if (i, s) not in used]
    return cells, adj, bound, N

def solve(up_par, d, chir, wall=60):
    built = build(up_par, d, chir)
    if built is None:
        return None
    cells, adj, bound, N = built
    tiles_at = [GRID[r][k] - 1 for (r, k) in cells]
    pats = sorted({white[t][e] for t in tiles_at for e in range(3)} |
                  {rev(white[t][e]) for t in tiles_at for e in range(3)} | {ZERO})
    pid = {p: i for i, p in enumerate(pats)}
    P = len(pats)
    rid = [pid[rev(p)] for p in pats]
    m = cp_model.CpModel()
    rv = [m.NewIntVar(0, 2, "") for _ in range(N)]
    rec = [[m.NewIntVar(0, P - 1, "") for _ in range(3)] for _ in range(N)]
    act = [[m.NewIntVar(0, P - 1, "") for _ in range(3)] for _ in range(N)]
    df = [[m.NewBoolVar("") for _ in range(3)] for _ in range(N)]
    for i, t in enumerate(tiles_at):
        rows = [(r, pid[white[t][(0 + r) % 3]], pid[white[t][(1 + r) % 3]],
                 pid[white[t][(2 + r) % 3]]) for r in range(3)]
        m.AddAllowedAssignments([rv[i], rec[i][0], rec[i][1], rec[i][2]], rows)
        for j in range(3):
            m.Add(act[i][j] == rec[i][j]).OnlyEnforceIf(df[i][j].Not())
            m.Add(act[i][j] != rec[i][j]).OnlyEnforceIf(df[i][j])
    for (a, sa, b, sb) in adj:
        m.AddElement(act[b][sb], rid, act[a][sa])
    for (i, s) in bound:
        m.Add(act[i][s] == pid[ZERO])
    m.Minimize(sum(df[i][j] for i in range(N) for j in range(3)))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = wall
    sv.parameters.num_search_workers = 8
    sv.parameters.cp_model_probing_level = 0
    st = sv.Solve(m)
    name = sv.StatusName(st)
    if name not in ("OPTIMAL", "FEASIBLE"):
        return (name, None, [])
    EN = "BLR"
    ipats = {v: k for k, v in pid.items()}
    edits = []
    for i, t in enumerate(tiles_at):
        r = sv.Value(rv[i])
        for j in range(3):
            if sv.Value(df[i][j]):
                te = (j + r) % 3
                edits.append((t + 1, EN[te], white[t][te],
                              ipats[sv.Value(act[i][j])]))
    return (name, int(sv.ObjectiveValue()), edits)

best = None
for up_par in (0, 1):
    for d in (-2, -1, 0, 1):
        for chir in (False, True):
            r = solve(up_par, d, chir)
            if r and r[1] is not None:
                print(f"up_par={up_par} d={d:+d} chir={int(chir)}: "
                      f"min_edits={r[1]} ({r[0]})", flush=True)
                if best is None or r[1] < best[0]:
                    best = (r[1], up_par, d, chir)
if best:
    print(f"\nBEST net {best[1:]} -> sharp list:")
    name, val, edits = solve(best[1], best[2], best[3], wall=240)
    print(f"min_edits={val} ({name})")
    for t, e, old, new in edits:
        print(f"  SUSPECT tile {t} edge {e}: recorded {old} -> should read {new}")
