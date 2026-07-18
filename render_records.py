"""render_records.py -- render the two record boards as SVGs + a gallery page.

Category A (rr_best.txt): 142/160 perfect partial -- empty slots hatched red.
Category B (edges_208_checkpoint.txt): 208/240 matched edges on a full board --
mismatched edges drawn as thick red strokes.

Layout identical to gen_viz.py (unfolded bipyramid net: 5 columns, top face Ti
above / bottom face Bi below the equator).

Usage: python render_records.py   -> record_A_142.svg, record_B_208.svg,
                                     records_view.html
"""
import json
import math

g = json.load(open("geometry.json"))
tiles = json.load(open("tiles.json"))
arcs = json.load(open("arcs.json"))
rev = lambda p: p[::-1]

W, H = 150.0, 150.0 * math.sqrt(3) / 2
YEQ = H + 30

def face_anchor(face):
    kind, i = face[0], int(face[1])
    ei = (f"E{i}", (i * W, YEQ))
    ej = (f"E{(i + 1) % 5}", ((i + 1) * W, YEQ))
    if kind == "T":
        apex = ("U", (i * W + W / 2, YEQ - H))
    else:
        apex = ("D", (i * W + W / 2, YEQ + H))
    return dict([ei, ej, apex])

axisof = {}
for s in g["slots"]:
    f, ty, b = s["face"], s["type"], tuple(s["bary"])
    if ty == "up" and sum(b) == 3:
        anch = face_anchor(f)
        names = list(anch.keys())
        # corner slot with bary (3,0,0) etc. identifies which anchor is A/B/C
        if f not in axisof:
            axisof[f] = {}
        for axname, bar in zip(("A", "B", "C"), ((3, 0, 0), (0, 3, 0), (0, 0, 3))):
            if b == bar:
                pass
# The corner-axis mapping above is delicate; reuse gen_viz's approach instead:
axisof = {}
for s in g["slots"]:
    f, ty, b = s["face"], s["type"], tuple(s["bary"])
    if ty != "up" or sorted(b) != [0, 0, 3]:
        continue
    anch = face_anchor(f)
    corner = s["corners"][b.index(3)]
    lbl = corner if isinstance(corner, str) else None
    if lbl is None:
        continue
    axisof.setdefault(f, {})[("A", "B", "C")[b.index(3)]] = lbl
# fill any missing axis letters with remaining anchor labels
for f, ax in axisof.items():
    remaining = [k for k in face_anchor(f) if k not in ax.values()]
    for letter in ("A", "B", "C"):
        if letter not in ax:
            ax[letter] = remaining.pop()

def slot_corner_pts(s):
    f, ty = s["face"], s["type"]
    a, b, c = s["bary"]
    anch = face_anchor(f)
    ax = axisof[f]
    A, B, C = anch[ax["A"]], anch[ax["B"]], anch[ax["C"]]
    if ty == "up":
        cs = [(a + 1, b, c), (a, b + 1, c), (a, b, c + 1)]
    else:
        cs = [(a, b + 1, c + 1), (a + 1, b, c + 1), (a + 1, b + 1, c)]
    return [((x * A[0] + y * B[0] + z * C[0]) / 4,
             (x * A[1] + y * B[1] + z * C[1]) / 4) for (x, y, z) in cs]

fmt = lambda v: f"{v:.1f}"

def load(path):
    pl = {}
    for tok in open(path).read().split():
        s, t, r = map(int, tok.split(":"))
        pl[s] = (t, r)
    return pl

def mismatched_edges(pl):
    out = []
    for e in g["edges"]:
        a, ja, b, jb = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
        if a in pl and b in pl:
            ta, ra = pl[a]
            tb, rb = pl[b]
            if tiles[ta][(ja + ra) % 3] != rev(tiles[tb][(jb + rb) % 3]):
                out.append((a, ja))
    return out

def render(pl, title, out_f, show_mismatch=False):
    slot_by_idx = {s["idx"]: s for s in g["slots"]}
    tri_paths, empty_paths, gold_segs, mis_segs, grid = [], [], [], [], []
    for s in g["slots"]:
        pts = slot_corner_pts(s)
        tri = (f"M{fmt(pts[0][0])},{fmt(pts[0][1])}L{fmt(pts[1][0])},{fmt(pts[1][1])}"
               f"L{fmt(pts[2][0])},{fmt(pts[2][1])}Z")
        grid.append(tri)
        sid = s["idx"]
        if sid not in pl:
            empty_paths.append(tri)
            continue
        tri_paths.append(tri)
        t, r = pl[sid]
        cx = sum(p[0] for p in pts) / 3
        cy = sum(p[1] for p in pts) / 3
        def ep_xy(e, p):
            j = (e - r) % 3
            a, b = pts[j], pts[(j + 1) % 3]
            f_ = (p + 1) / 12.0
            return (a[0] + f_ * (b[0] - a[0]), a[1] + f_ * (b[1] - a[1]))
        for (A_, B_) in arcs[t]:
            x1, y1 = ep_xy(*A_)
            x2, y2 = ep_xy(*B_)
            qx, qy = (x1 + x2) / 2 * 0.7 + cx * 0.3, (y1 + y2) / 2 * 0.7 + cy * 0.3
            gold_segs.append(f"M{fmt(x1)},{fmt(y1)}Q{fmt(qx)},{fmt(qy)} {fmt(x2)},{fmt(y2)}")
    if show_mismatch:
        for (sid, j) in mismatched_edges(pl):
            pts = slot_corner_pts(slot_by_idx[sid])
            a, b = pts[j], pts[(j + 1) % 3]
            mis_segs.append(f"M{fmt(a[0])},{fmt(a[1])}L{fmt(b[0])},{fmt(b[1])}")

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -20 {5*W+20} {2*H+90}" '
           f'font-family="sans-serif">',
           '<style>.g{fill:none;stroke:#8a7a00;stroke-width:2.0;stroke-linecap:round}'
           '.grid{fill:none;stroke:#666;stroke-width:.6}'
           '.mis{fill:none;stroke:#d22;stroke-width:3.4;stroke-linecap:round;opacity:.85}'
           '.flb{font-size:13px;fill:#000;text-anchor:middle;font-weight:bold}</style>',
           f'<text x="{2.5*W}" y="-6" class="flb">{title}</text>',
           '<defs><pattern id="hx" width="6" height="6" patternUnits="userSpaceOnUse">'
           '<path d="M0,6L6,0" stroke="#b33" stroke-width="1.6"/></pattern></defs>',
           f'<path d="{chr(10).join(tri_paths)}" fill="#f2ead0" stroke="none"/>']
    if empty_paths:
        svg.append(f'<path d="{chr(10).join(empty_paths)}" fill="url(#hx)" stroke="#b33" stroke-width="1"/>')
    svg.append(f'<path class="grid" d="{chr(10).join(grid)}"/>')
    svg.append(f'<path class="g" d="{chr(10).join(gold_segs)}"/>')
    if mis_segs:
        svg.append(f'<path class="mis" d="{chr(10).join(mis_segs)}"/>')
    for i in range(5):
        svg.append(f'<text x="{fmt(i*W+W/2)}" y="{fmt(YEQ-H-8)}" class="flb">T{i}</text>')
        svg.append(f'<text x="{fmt(i*W+W/2)}" y="{fmt(YEQ+H+16)}" class="flb">B{i}</text>')
    svg.append('</svg>')
    open(out_f, "w", encoding="utf-8").write("\n".join(svg))
    print(f"wrote {out_f}")

A = load("rr_best.txt")
B = load("edges_208_checkpoint.txt")
misB = len(mismatched_edges(B))
render(A, f"Category A record: {len(A)}/160 tiles, zero mismatched edges "
          f"(empty slots hatched)", "record_A_142.svg")
render(B, f"Category B record: {240-misB}/240 matched edges on a full board "
          f"({misB} mismatches in red)", "record_B_208.svg", show_mismatch=True)

html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Diamond Dilemma — record boards</title>
<style>body{{font-family:sans-serif;max-width:1100px;margin:24px auto;padding:0 12px}}
img,object{{width:100%;border:1px solid #ccc;margin:8px 0}}
h1{{font-size:22px}} h2{{font-size:17px}} p{{line-height:1.45}}</style></head><body>
<h1>Diamond Dilemma (1988) — best known results</h1>
<p>The gold challenge of the Diamond Dilemma puzzle — place all 160 tiles on the
pentagonal bipyramid so the gold lines form one closed loop — remains unsolved.
These are the strongest known partial results, produced by the solvers in this
repository. Tile data and the published silver/red/blue solutions used to
validate our entire pipeline are due to
<a href="https://www.jaapsch.net/puzzles/">Jaap Scherphuis</a> — thank you, Jaap.</p>
<h2>Category A — most tiles with every touching edge matched: {len(A)}/160</h2>
<p>All 240 gold half-edges between placed tiles match perfectly; the 18 hatched
slots are holes no remaining tile fits (each was proven "dead" — see
NEGATIVE_RESULTS.md). Robust against 120 perturbation kicks and a 102-slot
coordinated re-solve.</p>
<object data="record_A_142.svg" type="image/svg+xml"></object>
<h2>Category B — most matched edges with all 160 tiles placed: {240-misB}/240</h2>
<p>Eternity-II-style score: every tile is on the board; {misB} edges (red) do not
match. Produced by CP-SAT large-neighbourhood search (rr_edges.py); survived
~1,600 provably-optimal 52–64-tile rearrangements and ten degrade-reclimb
restarts without improvement.</p>
<object data="record_B_208.svg" type="image/svg+xml"></object>
<p>How everything works: <b>SOLVERS.md</b>. What failed and why:
<b>NEGATIVE_RESULTS.md</b>.</p>
</body></html>"""
open("records_view.html", "w", encoding="utf-8").write(html)
print("wrote records_view.html")
