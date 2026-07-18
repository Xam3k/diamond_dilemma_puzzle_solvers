"""Blue ground-truth fit, per band (internal edges only, no boundary constraint).
Band A = trapezoid rows 9/11/13/15 (3 faces); Band B = rhombus 4x8 (2 faces).
Sweeps net params; min-edits under Jaap's arrangement names blue's data errors.
"""
import re, sys
from ortools.sat.python import cp_model

GRID_A = [[102,118,110,121,103,140,134, 97, 86],
          [155,150,129,136, 94,159,126,130,151,107,131],
          [108, 82,116,146,139, 88,114,135,149, 99,100, 89,147],
          [148,144, 81,120, 91,122,113,117,101,141,105,109,128, 84, 92]]
GRID_B = [[104,138, 87,152,133,154,156,158],
          [111,127,106,124, 93, 98,112,119],
          [145,160, 96,137,143, 90,132,115],
          [ 85,123,153,125,157, 83,142, 95]]

white = []
for line in open("whites.txt"):
    m = re.findall(r"\b[01]{11}\b", line)
    if len(m) == 3:
        white.append(m)
rev = lambda p: p[::-1]

def fit(GRID, W, up_par, d, chir, wall=90):
    cells = [(r, k) for r in range(len(W)) for k in range(W[r])]
    cid = {c: i for i, c in enumerate(cells)}
    N = len(cells)
    isup = lambda r, k: (k % 2) == up_par
    adj = []
    for r in range(len(W)):
        for k in range(W[r] - 1):
            a, b = cid[(r, k)], cid[(r, k + 1)]
            if isup(r, k):
                sa, sb = (2, 2) if not chir else (1, 1)
            else:
                sa, sb = (1, 1) if not chir else (2, 2)
            adj.append((a, sa, b, sb))
    for r in range(1, len(W)):
        for k in range(W[r]):
            if not isup(r, k):
                kk = k + d
                if 0 <= kk < W[r - 1] and isup(r - 1, kk):
                    adj.append((cid[(r, k)], 0, cid[(r - 1, kk)], 0))
    tiles_at = [GRID[r][k] - 1 for (r, k) in cells]
    pats = sorted({white[t][e] for t in tiles_at for e in range(3)} |
                  {rev(white[t][e]) for t in tiles_at for e in range(3)})
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
    ip = {v: k for k, v in pid.items()}
    edits = []
    for i, t in enumerate(tiles_at):
        r = sv.Value(rv[i])
        for j in range(3):
            if sv.Value(df[i][j]):
                te = (j + r) % 3
                edits.append((t + 1, EN[te], white[t][te], ip[sv.Value(act[i][j])]))
    return (name, int(sv.ObjectiveValue()), edits)

for band, GRID, W in [("A/trapezoid", GRID_A, [9, 11, 13, 15]),
                      ("B/rhombus", GRID_B, [8, 8, 8, 8])]:
    best = None
    for up_par in (0, 1):
        for d in (-1, 1):
            for chir in (False, True):
                r = fit(GRID, W, up_par, d, chir, wall=60)
                if r[1] is not None:
                    print(f"band {band} up_par={up_par} d={d:+d} chir={int(chir)}: "
                          f"min_edits={r[1]} ({r[0]})", flush=True)
                    if best is None or r[1] < best[0]:
                        best = (r[1], up_par, d, chir)
    if best:
        name, val, edits = fit(GRID, W, best[1], best[2], best[3], wall=300)
        print(f"BAND {band} BEST {best[1:]} -> min_edits={val} ({name})")
        for t, e, old, new in edits:
            print(f"  SUSPECT tile {t} edge {e}: {old} -> {new}")
