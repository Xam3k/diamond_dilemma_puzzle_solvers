"""render_records.py -- render the two record boards as SVGs + a gallery page.

Two views are produced per record so a reader can either see the abstract
result or physically verify it against a real puzzle:

  "clean"  -- cream tiles, bold gold lines, mismatched edges (Category B)
              drawn as thick red strokes.
  "verify" -- each tile shaded its PHYSICAL colour (silver-grey / red / blue,
              matching the real puzzle) and labelled with its tile NUMBER
              (1..160, exactly as numbered in Jaap Scherphuis's gold data),
              so anyone who owns the puzzle can place each tile by hand and
              check the result. Gold lines are drawn faintly; empty holes are
              hatched; Category-B mismatches stay red.

Tile number -> physical colour mapping (verified: the silver/red/blue
challenge solvers, which use exactly these index ranges, reproduced Jaap's
published solution counts):
  tiles 1..32  silver-grey   (indices 0..31)
  tiles 33..80 red           (indices 32..79)
  tiles 81..160 blue         (indices 80..159)

Layout identical to gen_viz.py (unfolded bipyramid net: 5 columns, top face
Ti above / bottom face Bi below the equator).

Usage: python render_records.py
Outputs: record_A_142.svg, record_A_142_verify.svg,
         record_B_208.svg, record_B_208_verify.svg, records_view.html
"""
import json
import math

g = json.load(open("geometry.json"))
tiles = json.load(open("tiles.json"))
arcs = json.load(open("arcs.json"))
rev = lambda p: p[::-1]

W, H = 150.0, 150.0 * math.sqrt(3) / 2
YEQ = H + 30

# physical tile colour by tile index (see module docstring)
TILE_FILL = {"silver": "#c9c9c9", "red": "#eda3a3", "blue": "#9cc2e8"}
def colour_of(t):
    return "silver" if t < 32 else ("red" if t < 80 else "blue")

def face_anchor(face):
    kind, i = face[0], int(face[1])
    ei = (f"E{i}", (i * W, YEQ))
    ej = (f"E{(i + 1) % 5}", ((i + 1) * W, YEQ))
    apex = ("U", (i * W + W / 2, YEQ - H)) if kind == "T" else ("D", (i * W + W / 2, YEQ + H))
    return dict([ei, ej, apex])

axisof = {}
for s in g["slots"]:
    f, ty, b = s["face"], s["type"], tuple(s["bary"])
    if ty != "up" or sorted(b) != [0, 0, 3]:
        continue
    corner = s["corners"][b.index(3)]
    if isinstance(corner, str):
        axisof.setdefault(f, {})[("A", "B", "C")[b.index(3)]] = corner
for f in axisof:
    remaining = [k for k in face_anchor(f) if k not in axisof[f].values()]
    for letter in ("A", "B", "C"):
        if letter not in axisof[f]:
            axisof[f][letter] = remaining.pop()

def slot_corner_pts(s):
    f, ty = s["face"], s["type"]
    a, b, c = s["bary"]
    anch = face_anchor(f)
    ax = axisof[f]
    A, B, C = anch[ax["A"]], anch[ax["B"]], anch[ax["C"]]
    cs = ([(a + 1, b, c), (a, b + 1, c), (a, b, c + 1)] if ty == "up"
          else [(a, b + 1, c + 1), (a + 1, b, c + 1), (a + 1, b + 1, c)])
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

def render(pl, title, out_f, style, show_mismatch=False):
    """style: 'clean' or 'verify'."""
    verify = (style == "verify")
    slot_by_idx = {s["idx"]: s for s in g["slots"]}
    fills = {"silver": [], "red": [], "blue": [], "plain": []}
    empty_paths, gold_segs, mis_segs, grid, labels = [], [], [], [], []
    for s in g["slots"]:
        pts = slot_corner_pts(s)
        tri = (f"M{fmt(pts[0][0])},{fmt(pts[0][1])}L{fmt(pts[1][0])},{fmt(pts[1][1])}"
               f"L{fmt(pts[2][0])},{fmt(pts[2][1])}Z")
        grid.append(tri)
        sid = s["idx"]
        if sid not in pl:
            empty_paths.append(tri)
            continue
        t, r = pl[sid]
        fills[colour_of(t) if verify else "plain"].append(tri)
        cx = sum(p[0] for p in pts) / 3
        cy = sum(p[1] for p in pts) / 3
        if verify:
            labels.append((cx, cy, t + 1))
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

    gold_w = 1.1 if verify else 2.0
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -20 {5*W+20} {2*H+96}" '
           f'font-family="sans-serif">',
           f'<style>.g{{fill:none;stroke:#8a7a00;stroke-width:{gold_w};stroke-linecap:round;'
           f'opacity:{0.55 if verify else 1}}}'
           '.grid{fill:none;stroke:#555;stroke-width:.7}'
           '.mis{fill:none;stroke:#d22;stroke-width:3.4;stroke-linecap:round;opacity:.9}'
           '.num{font-size:7.5px;fill:#111;text-anchor:middle;font-weight:bold}'
           '.flb{font-size:13px;fill:#000;text-anchor:middle;font-weight:bold}</style>',
           f'<text x="{2.5*W}" y="-6" class="flb">{title}</text>',
           '<defs><pattern id="hx" width="6" height="6" patternUnits="userSpaceOnUse">'
           '<path d="M0,6L6,0" stroke="#b33" stroke-width="1.6"/></pattern></defs>']
    if verify:
        for grp in ("silver", "red", "blue"):
            svg.append(f'<path d="{chr(10).join(fills[grp])}" fill="{TILE_FILL[grp]}" stroke="none"/>')
    else:
        svg.append(f'<path d="{chr(10).join(fills["plain"])}" fill="#f2ead0" stroke="none"/>')
    if empty_paths:
        svg.append(f'<path d="{chr(10).join(empty_paths)}" fill="url(#hx)" stroke="#b33" stroke-width="1"/>')
    svg.append(f'<path class="grid" d="{chr(10).join(grid)}"/>')
    svg.append(f'<path class="g" d="{chr(10).join(gold_segs)}"/>')
    if mis_segs:
        svg.append(f'<path class="mis" d="{chr(10).join(mis_segs)}"/>')
    for (x, y, num) in labels:
        svg.append(f'<text x="{fmt(x)}" y="{fmt(y+2.6)}" class="num">{num}</text>')
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
          f"(empty slots hatched)", "record_A_142.svg", "clean")
render(A, f"Category A record: {len(A)}/160 tiles, physical colours + tile numbers "
          f"(empty slots hatched)", "record_A_142_verify.svg", "verify")
render(B, f"Category B record: {240-misB}/240 matched edges, full board "
          f"({misB} mismatches in red)", "record_B_208.svg", "clean", show_mismatch=True)
render(B, f"Category B record: {240-misB}/240 matched edges, physical colours + tile "
          f"numbers ({misB} mismatches in red)", "record_B_208_verify.svg", "verify",
       show_mismatch=True)

html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Diamond Dilemma, record boards</title>
<style>body{{font-family:sans-serif;max-width:1100px;margin:24px auto;padding:0 12px;color:#222}}
object{{width:100%;border:1px solid #ccc;margin:6px 0;background:#fff}}
h1{{font-size:22px}} h2{{font-size:17px}} h3{{font-size:14px;color:#555;margin:14px 0 2px}}
p{{line-height:1.5}} .sw{{display:inline-block;width:12px;height:12px;border:1px solid #999;
vertical-align:middle;margin:0 3px}}</style></head><body>
<h1>Diamond Dilemma (1988), best known results</h1>
<p>The gold challenge of the Diamond Dilemma puzzle, place all 160 tiles on the
pentagonal bipyramid so the gold lines form one closed loop, remains unsolved.
Below are the strongest known partial results, produced by the solvers in this
repository. Each is shown two ways: a clean gold-line view, and a physical
verification view in which every tile is shaded its real colour
(<span class="sw" style="background:#c9c9c9"></span>silver-grey tiles 1 to 32,
<span class="sw" style="background:#eda3a3"></span>red tiles 33 to 80,
<span class="sw" style="background:#9cc2e8"></span>blue tiles 81 to 160) and
labelled with its tile number, so anyone who owns the puzzle can lay the tiles
out by hand and check the result.</p>
<p>Tile data, the puzzle's history, and the published side-challenge solutions
used to validate the whole pipeline are due to
<a href="http://www.jaapsch.net/puzzles/diamdil.htm">Jaap Scherphuis's Diamond
Dilemma page</a> (and do explore
<a href="https://www.jaapsch.net/puzzles/">the rest of his puzzle site</a>).
Thank you, Jaap.</p>

<h2>Category A, most tiles with every touching edge matched: {len(A)}/160</h2>
<p>All 186 gold half-edges between placed tiles match perfectly; the 18 hatched
slots are holes that no remaining tile fits (each proven "dead", see
NEGATIVE_RESULTS.md). Robust against 120 perturbation kicks and a 102-slot
coordinated re-solve.</p>
<h3>gold-line view</h3><object data="record_A_142.svg" type="image/svg+xml"></object>
<h3>physical verification view (tile numbers + colours)</h3>
<object data="record_A_142_verify.svg" type="image/svg+xml"></object>

<h2>Category B, most matched edges with all 160 tiles placed: {240-misB}/240</h2>
<p>Eternity-II-style score: every tile is on the board; {misB} edges (red) do not
match. Produced by CP-SAT large-neighbourhood search (rr_edges.py); survived
about 1,600 provably-optimal 52 to 64-tile rearrangements and ten
degrade-reclimb restarts without improvement.</p>
<h3>gold-line view</h3><object data="record_B_208.svg" type="image/svg+xml"></object>
<h3>physical verification view (tile numbers + colours)</h3>
<object data="record_B_208_verify.svg" type="image/svg+xml"></object>

<p>How everything works: <b>SOLVERS.md</b>. What failed and why:
<b>NEGATIVE_RESULTS.md</b>. Re-score any board with
<code>python score_board.py &lt;board.txt&gt;</code>.</p>
<p style="color:#888;font-size:12px">Solvers, documentation, and some of the
code in this project were developed with the assistance of Claude AI models
(Anthropic).</p>
</body></html>"""
open("records_view.html", "w", encoding="utf-8").write(html)
print("wrote records_view.html")
