"""Generate check_sheet.html: all 160 tiles drawn upright from OUR data, same
order/layout as Jaap's sheets (8 per row; silver 1-32, red 33-80, blue 81-160),
for side-by-side visual verification against the website GIFs.

Per tile: gold arcs (olive, from diamonddilemma.txt + arcs.json wiring), white
endpoints (short white stubs, from whites.txt -- UNVERIFIED extraction), tile
number, and faint dots at all 11 positions of each edge as a position ruler.

Conventions (calibrated to the images): edge0 = bottom read RIGHT->LEFT,
edge1 = left read BOTTOM->TOP, edge2 = right read TOP->BOTTOM-RIGHT.
"""
import json, re, math

def parse(path):
    ts = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.findall(r"\b[01]{11}\b", line)
        if len(m) == 3:
            ts.append(m)
    return ts

gold = parse("diamonddilemma.txt")
white = parse("whites.txt")
arcs = json.load(open("arcs.json"))
assert len(gold) == 160 and len(white) == 160

W, H = 120.0, 120.0 * math.sqrt(3) / 2
PADX, PADY, GAP = 14, 30, 10

def corners(ox, oy):
    # upright triangle: L bottom-left, R bottom-right, T apex
    return ((ox, oy + H), (ox + W, oy + H), (ox + W / 2, oy))

def ep_xy(L, R, T, e, p):
    walks = {0: (R, L), 1: (L, T), 2: (T, R)}
    A, B = walks[e]
    t = (p + 1) / 12.0   # interior points: fractions 1/12..11/12
    return (A[0] + t * (B[0] - A[0]), A[1] + t * (B[1] - A[1]))

def tile_svg(tid, ox, oy, body):
    L, R, T = corners(ox, oy)
    cx, cy = (L[0] + R[0] + T[0]) / 3, (L[1] + R[1] + T[1]) / 3
    s = [f'<path d="M{L[0]:.1f},{L[1]:.1f}L{R[0]:.1f},{R[1]:.1f}'
         f'L{T[0]:.1f},{T[1]:.1f}Z" fill="{body}" stroke="#222" stroke-width="1.2"/>']
    # position ruler dots
    dots = []
    for e in range(3):
        for p in range(11):
            x, y = ep_xy(L, R, T, e, p)
            dots.append(f"M{x:.1f},{y:.1f}h.01")
    s.append(f'<path d="{" ".join(dots)}" stroke="#0006" stroke-width="1.6" '
             f'stroke-linecap="round"/>')
    # white stubs (unverified extraction)
    stubs = []
    for e in range(3):
        for p, ch in enumerate(white[tid][e]):
            if ch == "1":
                x, y = ep_xy(L, R, T, e, p)
                dx, dy = cx - x, cy - y
                n = math.hypot(dx, dy)
                stubs.append(f"M{x:.1f},{y:.1f}L{x + 14 * dx / n:.1f},{y + 14 * dy / n:.1f}")
    if stubs:
        s.append(f'<path d="{" ".join(stubs)}" stroke="#fff" stroke-width="3.4" '
                 f'fill="none" stroke-linecap="round"/>')
    # gold arcs
    ga = []
    for (a, b) in arcs[tid]:
        x1, y1 = ep_xy(L, R, T, a[0], a[1])
        x2, y2 = ep_xy(L, R, T, b[0], b[1])
        qx = (x1 + x2) / 2 * 0.65 + cx * 0.35
        qy = (y1 + y2) / 2 * 0.65 + cy * 0.35
        ga.append(f"M{x1:.1f},{y1:.1f}Q{qx:.1f},{qy:.1f} {x2:.1f},{y2:.1f}")
    if ga:
        s.append(f'<path d="{" ".join(ga)}" stroke="#8a7a00" stroke-width="2.6" '
                 f'fill="none" stroke-linecap="round"/>')
    s.append(f'<circle cx="{cx:.1f}" cy="{cy + 8:.1f}" r="11" fill="none" '
             f'stroke="#fff" stroke-width="1.4"/>')
    s.append(f'<text x="{cx:.1f}" y="{cy + 12:.1f}" text-anchor="middle" '
             f'font-size="11" fill="#fff" font-family="sans-serif">{tid + 1}</text>')
    return "".join(s)

SHEETS = [("Silver tiles 1-32", 0, 32, "#b9b9b9"),
          ("Red tiles 33-80", 32, 80, "#d55"),
          ("Blue tiles 81-160", 80, 160, "#57a")]
html = ["<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Diamond Dilemma - digitization check sheet</title></head>"
        "<body style='background:#f4eef4;font-family:sans-serif'>"
        "<h2>Digitization check sheet</h2>"
        "<p>Compare tile-by-tile with Jaap's sheets "
        "(<a href='https://www.jaapsch.net/puzzles/images/diamdil/tilessilver.gif'>silver</a>, "
        "<a href='https://www.jaapsch.net/puzzles/images/diamdil/tilesred.gif'>red</a>, "
        "<a href='https://www.jaapsch.net/puzzles/images/diamdil/tilesblue.gif'>blue</a>). "
        "<b>Olive curves</b> = our GOLD lines (data + derived wiring; verified vs bits). "
        "<b>White stubs</b> = our extracted WHITE endpoints (UNVERIFIED - please check "
        "positions, not arc shapes). Tiny dots mark the 11 positions per edge. "
        "Exact arc paths may differ from the drawing (only endpoints + pairing matter).</p>"]
for title, lo, hi, body in SHEETS:
    n = hi - lo
    nrows = (n + 7) // 8
    sw = PADX * 2 + 8 * (W + GAP)
    sh = PADY + nrows * (H + GAP + 16)
    html.append(f"<h3>{title}</h3><svg width='{sw:.0f}' height='{sh:.0f}' "
                f"xmlns='http://www.w3.org/2000/svg'>")
    for i in range(n):
        r, c = divmod(i, 8)
        ox = PADX + c * (W + GAP)
        oy = PADY / 2 + r * (H + GAP + 16)
        html.append(tile_svg(lo + i, ox, oy, body))
    html.append("</svg>")
html.append("</body></html>")
open("check_sheet.html", "w", encoding="utf-8").write("\n".join(html))
print("wrote check_sheet.html")
