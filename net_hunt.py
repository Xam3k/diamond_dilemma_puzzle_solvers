"""Silver phantom hunt + solution renderer.

1. Enumerate ALL white solutions of the silver challenge directly on the rhombus
   net (free tile assignment, AllDifferent, blank boundary), dedupe physically.
2. Compare each to Jaap's two transcribed solutions (tile-per-cell).
3. For phantoms: list the edge CONTACTS (tile,edge)-(tile,edge) they use that
   neither Jaap solution uses -> the suspect readings enabling them.
4. Render every solution (ours + labels for Jaap matches) as SVG in
   solutions_view.html for visual inspection.
"""
import re, math
from ortools.sat.python import cp_model

JAAP1 = [[16,23,18,14,31, 7,10,13],[ 6,19, 9,17,26, 4,21,24],
         [30,11,22, 2,29,20,15, 3],[32,27, 5,28,12, 1, 8,25]]
JAAP2 = [[16,13,10,24,21, 3,18,23],[ 6,19, 9, 7,31, 4,26,20],
         [30,11,22, 2,29,14,15,17],[32,27, 5,28,12, 1, 8,25]]
W = [8, 8, 8, 8]
TLO, THI = 0, 32

white = []
for line in open("whites.txt"):
    m = re.findall(r"\b[01]{11}\b", line)
    if len(m) == 3:
        white.append(m)
rev = lambda p: p[::-1]
ZERO = "0" * 11

def build_net():
    cells = [(r, k) for r in range(len(W)) for k in range(W[r])]
    cid = {c: i for i, c in enumerate(cells)}
    isup = lambda r, k: k % 2 == 0
    adj = []
    for r in range(len(W)):
        for k in range(W[r] - 1):
            a, b = cid[(r, k)], cid[(r, k + 1)]
            sa, sb = (2, 2) if isup(r, k) else (1, 1)
            adj.append((a, sa, b, sb))
    for r in range(1, len(W)):
        for k in range(W[r]):
            if not isup(r, k) and 0 <= k - 1 < W[r - 1]:
                adj.append((cid[(r, k)], 0, cid[(r - 1, k - 1)], 0))
    used = set()
    for (a, sa, b, sb) in adj:
        used.add((a, sa)); used.add((b, sb))
    N = len(cells)
    bound = [(i, s) for i in range(N) for s in range(3) if (i, s) not in used]
    return cells, cid, adj, bound, N

cells, cid, adj, bound, N = build_net()
group = list(range(TLO, THI))
pats = sorted({white[t][e] for t in group for e in range(3)} |
              {rev(white[t][e]) for t in group for e in range(3)} | {ZERO})
pid = {p: i for i, p in enumerate(pats)}
rid = [pid[rev(p)] for p in pats]

m = cp_model.CpModel()
tv = [m.NewIntVar(0, N - 1, "") for _ in range(N)]
rv = [m.NewIntVar(0, 2, "") for _ in range(N)]
pe = [[m.NewIntVar(0, len(pats) - 1, "") for _ in range(3)] for _ in range(N)]
m.AddAllDifferent(tv)
link = []
for li, t in enumerate(group):
    for r in range(3):
        link.append((li, r, pid[white[t][(0 + r) % 3]],
                     pid[white[t][(1 + r) % 3]], pid[white[t][(2 + r) % 3]]))
for i in range(N):
    m.AddAllowedAssignments([tv[i], rv[i], pe[i][0], pe[i][1], pe[i][2]], link)
for (a, sa, b, sb) in adj:
    m.AddElement(pe[b][sb], rid, pe[a][sa])
for (i, s) in bound:
    m.Add(pe[i][s] == pid[ZERO])

class Coll(cp_model.CpSolverSolutionCallback):
    def __init__(self):
        super().__init__()
        self.sols = []
    def on_solution_callback(self):
        self.sols.append([(group[self.Value(tv[i])], self.Value(rv[i]))
                          for i in range(N)])

sv = cp_model.CpSolver()
sv.parameters.max_time_in_seconds = 400
sv.parameters.num_search_workers = 1
sv.parameters.cp_model_probing_level = 0
sv.parameters.enumerate_all_solutions = True
cb = Coll()
st = sv.Solve(m, cb)
print(f"net enumeration: {sv.StatusName(st)}, raw solutions={len(cb.sols)}")

def phys(sol):
    return tuple(tuple(white[t][(j + r) % 3] for j in range(3)) for (t, r) in sol)
dedup = {}
for s in cb.sols:
    dedup.setdefault(phys(s), s)
sols = list(dedup.values())
print(f"physically distinct: {len(sols)}")

def grid_of(sol):
    g = []
    i = 0
    for r in range(len(W)):
        g.append([sol[i + k][0] + 1 for k in range(W[r])])
        i += W[r]
    return g

def contacts(sol):
    out = set()
    for (a, sa, b, sb) in adj:
        ta, ra = sol[a]; tb, rb = sol[b]
        ea, eb = (sa + ra) % 3, (sb + rb) % 3
        out.add(tuple(sorted([(ta + 1, ea), (tb + 1, eb)])))
    return out

jgrids = {"JAAP1": JAAP1, "JAAP2": JAAP2}
jaap_contacts = set()
labels = []
for si, s in enumerate(sols):
    gme = grid_of(s)
    tag = next((nm for nm, jg in jgrids.items() if gme == jg), None)
    labels.append(tag or f"EXTRA{si+1}")
    print(f"sol{si+1}: {'matches ' + tag if tag else 'NO Jaap match (phantom?)'}")
for si, s in enumerate(sols):
    if labels[si].startswith("JAAP"):
        jaap_contacts |= contacts(s)
EN = "BLR"
for si, s in enumerate(sols):
    if not labels[si].startswith("JAAP"):
        extra = contacts(s) - jaap_contacts
        print(f"{labels[si]}: contacts not used by any Jaap solution:")
        for (ta, ea), (tb, eb) in sorted(extra):
            print(f"    tile {ta} {EN[ea]}  <->  tile {tb} {EN[eb]}")

# ---------- render all solutions ----------
import json
warcs = json.load(open("white_arcs.json"))
S = 120
H = S * math.sqrt(3) / 2
def cell_pts(r, k):
    x0 = -r * S / 2 + 40 + r * 0  # shear left per row
    xb = x0 + (k // 2) * S + (S if k % 2 else 0) * 0
    xL = x0 + (k / 2) * S if k % 2 == 0 else x0 + ((k - 1) / 2) * S + S / 2
    y0, y1 = 30 + r * H, 30 + (r + 1) * H
    if k % 2 == 0:   # up: corners br, bl, apex ; slots B(br->bl) L(bl->ap) R(ap->br)
        bl = (xL, y1); br = (xL + S, y1); ap = (xL + S / 2, y0)
        return {"corners": [bl, br, ap],
                "slots": {0: (br, bl), 1: (bl, ap), 2: (ap, br)}}
    else:            # down: corners tl, tr, apex ; slots T(tl->tr) R(tr->ap) L(ap->tl)
        tl = (xL, y0); tr = (xL + S, y0); ap = (xL + S / 2, y1)
        return {"corners": [tl, tr, ap],
                "slots": {0: (tl, tr), 1: (tr, ap), 2: (ap, tl)}}

def render(sol, title):
    parts = [f"<h3>{title}</h3>"]
    wdt = max(W) * S + 80 + len(W) * S // 2
    hgt = len(W) * H + 60
    parts.append(f'<svg width="{wdt:.0f}" height="{hgt:.0f}" '
                 f'style="background:#999">')
    i = 0
    for r in range(len(W)):
        for k in range(W[r]):
            cp = cell_pts(r, k)
            c = cp["corners"]
            parts.append(f'<polygon points="{c[0][0]:.1f},{c[0][1]:.1f} '
                         f'{c[1][0]:.1f},{c[1][1]:.1f} {c[2][0]:.1f},{c[2][1]:.1f}" '
                         f'fill="#b9b9b9" stroke="#222"/>')
            t, rot = sol[i]
            cx = sum(p[0] for p in c) / 3
            cy = sum(p[1] for p in c) / 3
            for (a, b) in warcs[t]:
                pts = []
                for (e, p) in (a, b):
                    j = (e - rot) % 3
                    A, B = cp["slots"][j]
                    f = (p + 1) / 12
                    pts.append((A[0] + f * (B[0] - A[0]), A[1] + f * (B[1] - A[1])))
                qx = (pts[0][0] + pts[1][0]) / 2 * 0.6 + cx * 0.4
                qy = (pts[0][1] + pts[1][1]) / 2 * 0.6 + cy * 0.4
                parts.append(f'<path d="M{pts[0][0]:.1f},{pts[0][1]:.1f} '
                             f'Q{qx:.1f},{qy:.1f} {pts[1][0]:.1f},{pts[1][1]:.1f}" '
                             f'stroke="#fff" stroke-width="4" fill="none"/>')
            parts.append(f'<text x="{cx:.0f}" y="{cy+4:.0f}" text-anchor="middle" '
                         f'font-size="13" fill="#333">{t+1}</text>')
            i += 1
    parts.append("</svg>")
    return "\n".join(parts)

html = ["<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Silver solutions</title></head><body style='font-family:sans-serif'>",
        "<h2>Silver challenge: all physically-distinct white solutions (our data)</h2>",
        "<p>White curves = white lines (drawn schematically; only endpoints+topology "
        "meaningful). Compare with Jaap's images.</p>"]
for si, s in enumerate(sols):
    html.append(render(s, f"Solution {si+1} — {labels[si]}"))
html.append("</body></html>")
open("solutions_view.html", "w", encoding="utf-8").write("\n".join(html))
print("wrote solutions_view.html")
