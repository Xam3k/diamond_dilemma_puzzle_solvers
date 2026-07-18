"""Sharp suspect finder: Jaap's FIXED silver arrangement + min arbitrary edits,
swept over candidate net interpretations. The correct net needs the fewest edits;
its edit set = precise digitization suspects.
"""
import re
from ortools.sat.python import cp_model

GRID = [[16,23,18,14,31, 7,10,13],
        [ 6,19, 9,17,26, 4,21,24],
        [30,11,22, 2,29,20,15, 3],
        [32,27, 5,28,12, 1, 8,25]]

white = []
for line in open("whites.txt"):
    m = re.findall(r"\b[01]{11}\b", line)
    if len(m) == 3:
        white.append(m)
rev = lambda p: p[::-1]
ZERO = "0" * 11

def build(up_par, d, chir):
    cells = [(r, k) for r in range(4) for k in range(8)]
    cid = {c: i for i, c in enumerate(cells)}
    isup = lambda r, k: (k % 2) == up_par
    adj = []
    for r in range(4):
        for k in range(7):
            a, b = cid[(r, k)], cid[(r, k + 1)]
            if isup(r, k):
                sa, sb = (2, 2) if not chir else (1, 1)
            else:
                sa, sb = (1, 1) if not chir else (2, 2)
            adj.append((a, sa, b, sb))
    for r in range(1, 4):
        for k in range(8):
            if not isup(r, k):
                kk = k + d
                if 0 <= kk < 8 and isup(r - 1, kk):
                    adj.append((cid[(r, k)], 0, cid[(r - 1, kk)], 0))
    if len(adj) != 40:
        return None
    used = set()
    for (a, sa, b, sb) in adj:
        used.add((a, sa)); used.add((b, sb))
    bound = [(i, s) for i in range(32) for s in range(3) if (i, s) not in used]
    return cells, adj, bound

def solve(up_par, d, chir, wall=60, verbose=False):
    built = build(up_par, d, chir)
    if built is None:
        return None
    cells, adj, bound = built
    tiles_at = [GRID[r][k] - 1 for (r, k) in cells]
    pats = sorted({white[t][e] for t in tiles_at for e in range(3)} |
                  {rev(white[t][e]) for t in tiles_at for e in range(3)} | {ZERO})
    pid = {p: i for i, p in enumerate(pats)}
    P = len(pats)
    rid = [pid[rev(p)] for p in pats]
    m = cp_model.CpModel()
    rv = [m.NewIntVar(0, 2, "") for _ in range(32)]
    rec = [[m.NewIntVar(0, P - 1, "") for _ in range(3)] for _ in range(32)]
    act = [[m.NewIntVar(0, P - 1, "") for _ in range(3)] for _ in range(32)]
    df = [[m.NewBoolVar("") for _ in range(3)] for _ in range(32)]
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
    m.Minimize(sum(df[i][j] for i in range(32) for j in range(3)))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = wall
    sv.parameters.num_search_workers = 8
    sv.parameters.cp_model_probing_level = 0
    st = sv.Solve(m)
    name = sv.StatusName(st)
    if name not in ("OPTIMAL", "FEASIBLE"):
        return (name, None, [])
    edits = []
    EN = "BLR"
    ipats = {v: k for k, v in pid.items()}
    for i, t in enumerate(tiles_at):
        r = sv.Value(rv[i])
        for j in range(3):
            if sv.Value(df[i][j]):
                te = (j + r) % 3
                edits.append((t + 1, EN[te], white[t][te],
                              ipats[sv.Value(act[i][j])]))
    return (name, int(sv.ObjectiveValue()), edits)

results = []
for up_par in (0, 1):
    for d in (-2, -1, 0, 1, 2):
        for chir in (False, True):
            r = solve(up_par, d, chir)
            if r and r[1] is not None:
                results.append((r[1], up_par, d, chir, r[0]))
                print(f"up_par={up_par} d={d:+d} chir={int(chir)}: "
                      f"min_edits={r[1]} ({r[0]})", flush=True)
results.sort()
if results:
    best = results[0]
    print(f"\nBEST net: up_par={best[1]} d={best[2]:+d} chir={int(best[3])} "
          f"-> re-solving longer for the sharp edit list:")
    name, val, edits = solve(best[1], best[2], best[3], wall=240)
    print(f"min_edits={val} ({name})")
    for t, e, old, new in edits:
        print(f"  SUSPECT tile {t} edge {e}: recorded {old} -> should read {new}")
