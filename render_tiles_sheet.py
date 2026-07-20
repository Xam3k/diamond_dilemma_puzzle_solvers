"""render_tiles_sheet.py -- render all 160 tiles as a catalog in Jaap's sheet
order, so the digitised data can be checked side-by-side against Jaap
Scherphuis's original tile sheets.

Layout matches how the tiles were digitised from his images (see
extract_tiles.py): 8 tiles per row, grouped by colour, silver (rows 1-4,
tiles 1-32), red (rows 5-10, tiles 33-80), blue (rows 11-20, tiles 81-160).
Every tile is an up-triangle with the SAME edge convention the data was read
with: edge 0 = bottom (R->L), edge 1 = left (L->T), edge 2 = right (T->R),
11 interior points per edge at fractions (p+1)/12. Within-tile wiring comes
from arcs.json (gold) / white_arcs.json (white), so each drawn tile shows
exactly the lines the data encodes.

Outputs: tiles_sheet_gold.svg, tiles_sheet_white.svg, tiles_view.html
Usage:   python render_tiles_sheet.py
"""
import json

tiles = json.load(open("tiles.json"))
gold_arcs = json.load(open("arcs.json"))
try:
    white_arcs = json.load(open("white_arcs.json"))
except FileNotFoundError:
    white_arcs = None

N = 160
COLS = 8
CW, CH = 72.0, 70.0          # cell width / height
PAD_TOP = 12.0               # room above triangle for the number
MARG_X, MARG_Y = 16.0, 16.0

def colour_of(t):
    return "silver" if t < 32 else ("red" if t < 80 else "blue")
BG = {"silver": "#e9e9e9", "red": "#f4d3d3", "blue": "#d6e4f6"}
GROUPS = [("Silver tiles 1 to 32", 0, 32), ("Red tiles 33 to 80", 32, 80),
          ("Blue tiles 81 to 160", 80, 160)]
fmt = lambda v: f"{v:.1f}"

def tri_corners(cx, cy):
    """Up-triangle in a cell centred horizontally at cx, top at cy.
    Returns corners ordered [R, L, T] so that edge index e runs
    pts[e] -> pts[(e+1)%3] == (0:R->L bottom, 1:L->T left, 2:T->R right)."""
    half = CW * 0.40
    h = half * 1.732
    T = (cx, cy)
    L = (cx - half, cy + h)
    R = (cx + half, cy + h)
    return [R, L, T]

def ep(pts, e, p):
    a, b = pts[e], pts[(e + 1) % 3]
    f = (p + 1) / 12.0
    return (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))

def render(arcs, out_f, line_col, title, line_w=1.5, halo=False):
    rows_total = sum((hi - lo + COLS - 1) // COLS for _, lo, hi in GROUPS)
    Wpx = MARG_X * 2 + COLS * CW
    Hpx = MARG_Y + 40 + rows_total * (CH + PAD_TOP) + len(GROUPS) * 26 + 20
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{Wpx:.0f}" height="{Hpx:.0f}" '
           f'viewBox="0 0 {Wpx:.0f} {Hpx:.0f}" font-family="sans-serif">',
           '<style>.tri{stroke:#666;stroke-width:.8;}'
           f'.ln{{fill:none;stroke:{line_col};stroke-width:{line_w};stroke-linecap:round}}'
           '.halo{fill:none;stroke:#333;stroke-width:2.6;stroke-linecap:round;opacity:.5}'
           '.num{font-size:9px;fill:#111;text-anchor:middle;font-weight:bold}'
           '.hdr{font-size:15px;fill:#000;font-weight:bold}'
           '.ttl{font-size:16px;fill:#000;font-weight:bold}</style>',
           f'<rect x="0" y="0" width="{Wpx:.0f}" height="{Hpx:.0f}" fill="#fff"/>',
           f'<text x="{MARG_X}" y="24" class="ttl">{title}</text>']
    y = MARG_Y + 40
    for name, lo, hi in GROUPS:
        svg.append(f'<text x="{MARG_X}" y="{y+4:.0f}" class="hdr">{name}</text>')
        y += 20
        for k in range(lo, hi):
            col = (k - lo) % COLS
            if col == 0 and k > lo:
                y += CH + PAD_TOP
            cx = MARG_X + col * CW + CW / 2
            cyt = y + PAD_TOP
            pts = tri_corners(cx, cyt)
            tricol = BG[colour_of(k)]
            svg.append(f'<path class="tri" fill="{tricol}" d="M{fmt(pts[0][0])},{fmt(pts[0][1])}'
                       f'L{fmt(pts[1][0])},{fmt(pts[1][1])}L{fmt(pts[2][0])},{fmt(pts[2][1])}Z"/>')
            cxc = sum(p[0] for p in pts) / 3
            cyc = sum(p[1] for p in pts) / 3
            segs = []
            for (A_, B_) in arcs[k]:
                x1, y1 = ep(pts, *A_)
                x2, y2 = ep(pts, *B_)
                qx = (x1 + x2) / 2 * 0.68 + cxc * 0.32
                qy = (y1 + y2) / 2 * 0.68 + cyc * 0.32
                segs.append(f"M{fmt(x1)},{fmt(y1)}Q{fmt(qx)},{fmt(qy)} {fmt(x2)},{fmt(y2)}")
            d = " ".join(segs)
            if d and halo:
                svg.append(f'<path class="halo" d="{d}"/>')
            if d:
                svg.append(f'<path class="ln" d="{d}"/>')
            svg.append(f'<text x="{fmt(cx)}" y="{fmt(y+8)}" class="num">{k+1}</text>')
        y += CH + PAD_TOP
    svg.append('</svg>')
    open(out_f, "w", encoding="utf-8").write("\n".join(svg))
    print(f"wrote {out_f}")

render(gold_arcs, "tiles_sheet_gold.svg", "#747604",
       "Diamond Dilemma, all 160 tiles, GOLD lines (Jaap's sheet order)")
if white_arcs is not None:
    render(white_arcs, "tiles_sheet_white.svg", "#ffffff",
           "Diamond Dilemma, all 160 tiles, WHITE lines (Jaap's sheet order)",
           line_w=1.4, halo=True)

html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Diamond Dilemma, tile catalog</title>
<style>body{font-family:sans-serif;max-width:900px;margin:24px auto;padding:0 12px;color:#222}
object{width:100%;border:1px solid #ccc;margin:6px 0;background:#fff}
h1{font-size:21px} h2{font-size:16px} p{line-height:1.5}</style></head><body>
<h1>Diamond Dilemma, all 160 tiles (digitised)</h1>
<p>These are the 160 tiles exactly as encoded in this repository, drawn in the
same order and arrangement as
<a href="http://www.jaapsch.net/puzzles/diamdil.htm">Jaap Scherphuis's</a>
original tile sheets: 8 per row, grouped silver (1 to 32), red (33 to 80),
blue (81 to 160). Put this next to Jaap's sheets and compare tile by tile to
confirm the digitisation is faithful. Each tile is an up-triangle with edge 0
along the bottom (read right to left), edge 1 up the left side, edge 2 down
the right side, which is the convention the data was read with.</p>
<h2>Gold lines (the gold challenge)</h2>
<p>Source data: <code>diamonddilemma.txt</code> (Jaap's own values) to
<code>tiles.json</code>, with within-tile wiring in <code>arcs.json</code>.</p>
<object data="tiles_sheet_gold.svg" type="image/svg+xml"></object>
<h2>White lines (the silver / red / blue challenges)</h2>
<p>Source data: <code>whites.txt</code>, wiring in <code>white_arcs.json</code>.
Drawn white with a grey halo for visibility.</p>
<object data="tiles_sheet_white.svg" type="image/svg+xml"></object>
<p style="color:#888;font-size:12px">Rendered by render_tiles_sheet.py.
Some of the code and documentation in this project was produced with the
assistance of Claude AI models (Anthropic), under human direction and review.</p>
</body></html>"""
open("tiles_view.html", "w", encoding="utf-8").write(html)
print("wrote tiles_view.html")
