"""Render the current best partial gold matching as an SVG on the unfolded bipyramid.

Net layout: 5 columns; column i has top face Ti (up-triangle, apex U) above and
bottom face Bi (down-triangle, apex D) below, sharing the equator edge Ei-Ei+1 —
so cross-equator matches join visibly. Top-top / bottom-bottom adjacencies are cut
by the net (they wrap in 3D).

Usage: python gen_viz.py <partial.txt> <out.svg>
"""
import json, math, sys

partial_f = sys.argv[1] if len(sys.argv) > 1 else "rr_best.txt"
out_f = sys.argv[2] if len(sys.argv) > 2 else "viz.svg"

g = json.load(open("geometry.json"))
tiles = json.load(open("tiles.json"))
arcs = json.load(open("arcs.json"))

pl = {}
for tok in open(partial_f).read().split():
    s, t, r = map(int, tok.split(":"))
    pl[s] = (t, r)

W, H = 150.0, 150.0 * math.sqrt(3) / 2
YEQ = H + 30

# face -> corner-label anchors in net coords
def face_anchor(face):
    kind, i = face[0], int(face[1])
    ei = (f"E{i}", (i * W, YEQ))
    ej = (f"E{(i + 1) % 5}", ((i + 1) * W, YEQ))
    if kind == "T":
        return dict([ei, ej, ("U", (i * W + W / 2, YEQ - H))])
    return dict([ei, ej, ("D", (i * W + W / 2, YEQ + H))])

# face -> which vertex label is bary axis A/B/C: from corner slots
axisof = {}
for s in g["slots"]:
    f, ty, b = s["face"], s["type"], tuple(s["bary"])
    if ty == "up" and b in ((3, 0, 0), (0, 3, 0), (0, 0, 3)):
        # corner c0=(a+1,b,c): for (3,0,0) that's (4,0,0)=A etc.
        vertex = s["corners"][b.index(3)] if False else None
        # c0=(a+1,b,c),c1=(a,b+1,c),c2=(a,b,c+1): the pure vertex is at index of the 3
        idx = b.index(3)
        vlabel = s["corners"][idx]
        assert isinstance(vlabel, str), (f, b, s["corners"])
        axisof.setdefault(f, {})["ABC"[idx]] = vlabel

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
    pts = []
    for (x, y, z) in cs:
        px = (x * A[0] + y * B[0] + z * C[0]) / 4
        py = (x * A[1] + y * B[1] + z * C[1]) / 4
        pts.append((px, py))
    return pts

def fmt(v):
    return f"{v:.1f}"

group_fill = {"silver": "#c9c9c9", "red": "#e88", "blue": "#8ad"}
def group_of(t):
    return "silver" if t < 32 else ("red" if t < 80 else "blue")

paths = {"silver": [], "red": [], "blue": []}
empty_paths = []
gold_segs = []
labels = []
grid = []

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
    paths[group_of(t)].append(tri)
    cx = sum(p[0] for p in pts) / 3
    cy = sum(p[1] for p in pts) / 3
    labels.append((cx, cy, t + 1))
    # gold arcs: tile edge e -> slot edge (e-r)%3; pos p at p/10 along slot edge
    def ep_xy(e, p):
        j = (e - r) % 3
        a, b = pts[j], pts[(j + 1) % 3]
        t = (p + 1) / 12.0   # interior points: fractions 1/12..11/12
        return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    for (A_, B_) in arcs[t]:
        x1, y1 = ep_xy(*A_)
        x2, y2 = ep_xy(*B_)
        qx, qy = (x1 + x2) / 2 * 0.7 + cx * 0.3, (y1 + y2) / 2 * 0.7 + cy * 0.3
        gold_segs.append(f"M{fmt(x1)},{fmt(y1)}Q{fmt(qx)},{fmt(qy)} {fmt(x2)},{fmt(y2)}")

face_lbls = []
for i in range(5):
    face_lbls.append((i * W + W / 2, YEQ - H - 8, f"T{i}"))
    face_lbls.append((i * W + W / 2, YEQ + H + 16, f"B{i}"))

n_placed = len(pl)
svg = []
svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -20 {5*W+20} {2*H+90}" '
           f'font-family="sans-serif">')
svg.append('<style>.g{fill:none;stroke:#8a7a00;stroke-width:2.2;stroke-linecap:round}'
           '.grid{fill:none;stroke:#555;stroke-width:.6}'
           '.lbl{font-size:7px;fill:#333;text-anchor:middle}'
           '.flb{font-size:13px;fill:#000;text-anchor:middle;font-weight:bold}</style>')
svg.append(f'<text x="{2.5*W}" y="-6" class="flb">Diamond Dilemma GOLD - best partial '
           f'matching {n_placed}/160 (empty slots hatched)</text>')
svg.append('<defs><pattern id="hx" width="6" height="6" patternUnits="userSpaceOnUse">'
           '<path d="M0,6L6,0" stroke="#b33" stroke-width="1.6"/></pattern></defs>')
for grp, plist in paths.items():
    svg.append(f'<path d="{chr(10).join(plist)}" fill="{group_fill[grp]}" stroke="none"/>')
svg.append(f'<path d="{chr(10).join(empty_paths)}" fill="url(#hx)" stroke="#b33" '
           f'stroke-width="1"/>')
svg.append(f'<path class="grid" d="{chr(10).join(grid)}"/>')
svg.append(f'<path class="g" d="{chr(10).join(gold_segs)}"/>')
for (x, y, t) in labels:
    svg.append(f'<text x="{fmt(x)}" y="{fmt(y+2)}" class="lbl">{t}</text>')
for (x, y, s_) in face_lbls:
    svg.append(f'<text x="{fmt(x)}" y="{fmt(y)}" class="flb">{s_}</text>')
svg.append('</svg>')
open(out_f, "w", encoding="utf-8").write("\n".join(svg))
print(f"wrote {out_f}: {n_placed}/160 placed, {len(gold_segs)} gold arcs, "
      f"{len(empty_paths)} empty slots")
