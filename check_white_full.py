"""Full white verification over all 160 tiles:
  1. bits<->arcs endpoint-set consistency (every set bit is an arc endpoint, once)
  2. odd endpoint counts (impossible)
  3. NON-CROSSING coherence: within a tile, white arcs are straight chords between
     interior points ((p+1)/12 along each edge); no two may properly intersect
     (a single-colour line system on a tile cannot self-cross).
Writes white_fixlist.txt (only flagged tiles, with evidence). Prints a summary.
"""
import re, math
from itertools import combinations

EDGE = {"B": 0, "L": 1, "R": 2}
EN = "BLR"
V = [(0.0, 0.0), (1.0, 0.0), (0.5, math.sqrt(3) / 2)]

def coord(e, p):                       # interior point p (0..10) -> xy
    a, b = V[e], V[(e + 1) % 3]
    t = (p + 1) / 12.0
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

def seg_cross(p1, p2, p3, p4):         # proper intersection (shared endpoints ok)
    def o(a, b, c):
        v = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
        return (v > 1e-12) - (v < -1e-12)
    if p1 in (p3, p4) or p2 in (p3, p4):
        return False
    return o(p1,p2,p3) != o(p1,p2,p4) and o(p3,p4,p1) != o(p3,p4,p2)

def parse_bits(path):
    out = {}
    for line in open(path):
        m = re.match(r"\s*(\d+):\s+([01]{11})\s+([01]{11})\s+([01]{11})", line)
        if m:
            out[int(m.group(1))] = [m.group(2), m.group(3), m.group(4)]
    return out

def parse_arcs(path):
    out = {}
    for line in open(path):
        m = re.match(r"\s*(\d+):\s*(.*)$", line)
        if not m:
            continue
        tid, body = int(m.group(1)), re.sub(r"\(.*?\)", "", m.group(2)).strip()
        if not body or body.upper().startswith(("AMBIGUOUS", "UNKNOWN")):
            out[tid] = None
            continue
        arcs, ok = [], True
        for tok in [t.strip() for t in body.split(",") if t.strip()]:
            am = re.match(r"^([BLR])(\d+)-([BLR])(\d+)$", tok)
            if not am:
                ok = False
                break
            arcs.append(((EDGE[am.group(1)], int(am.group(2)) - 1),
                         (EDGE[am.group(3)], int(am.group(4)) - 1)))
        out[tid] = arcs if ok else ("PARSE", body)
    return out

def eset(bits3):
    return {(e, p) for e in range(3) for p, c in enumerate(bits3[e]) if c == "1"}
def fmt(eps):
    return ", ".join(f"{EN[e]}{p+1}" for e, p in sorted(eps)) or "(none)"

bits = parse_bits("verify_white_bits.txt")
arcs = parse_arcs("verify_white_arcs.txt")

flags = []
n_odd = n_mismatch = n_cross = n_unparsed = n_ok = 0
for tid in range(1, 161):
    reasons = []
    b = bits.get(tid)
    if b is None:
        flags.append((tid, ["bits line missing"])); n_unparsed += 1; continue
    bs = eset(b)
    if len(bs) % 2:
        reasons.append("ODD endpoint count (impossible)"); n_odd += 1
    a = arcs.get(tid)
    if a is None:
        reasons.append("arcs UNKNOWN/AMBIGUOUS - please give a wiring")
    elif isinstance(a, tuple):
        reasons.append(f"arcs unparseable: '{a[1]}'"); n_unparsed += 1
    else:
        aset = set()
        for x, y in a:
            aset.add(x); aset.add(y)
        if aset != bs:
            only_b, only_a = bs - aset, aset - bs
            det = []
            if only_b: det.append("in bits only: " + fmt(only_b))
            if only_a: det.append("in arcs only: " + fmt(only_a))
            reasons.append("bits<->arcs disagree (" + "; ".join(det) + ")"); n_mismatch += 1
        else:
            xy = {ep: coord(*ep) for ep in bs}
            crossings = []
            for (a1, a2), (b1, b2) in combinations(a, 2):
                if seg_cross(xy[a1], xy[a2], xy[b1], xy[b2]):
                    crossings.append((f"{EN[a1[0]]}{a1[1]+1}-{EN[a2[0]]}{a2[1]+1}",
                                      f"{EN[b1[0]]}{b1[1]+1}-{EN[b2[0]]}{b2[1]+1}"))
            if crossings:
                reasons.append("CROSSING white arcs: " +
                               "; ".join(f"{x} x {y}" for x, y in crossings)); n_cross += 1
    if reasons:
        flags.append((tid, reasons, b, a))
    else:
        n_ok += 1

with open("white_fixlist.txt", "w", encoding="ascii") as f:
    f.write("# WHITE FIX LIST (all 160 tiles checked). Fix these in verify_white_bits.txt\n")
    f.write("# and verify_white_arcs.txt. Points 1..11 clockwise: B r->l, L b->t, R t->b.\n\n")
    for entry in flags:
        tid, reasons = entry[0], entry[1]
        f.write(f"tile {tid}:\n")
        if len(entry) > 2 and entry[2]:
            f.write(f"  bits -> {fmt(eset(entry[2]))}\n")
        if len(entry) > 3 and isinstance(entry[3], list):
            f.write("  arcs -> " + ", ".join(f"{EN[x[0]]}{x[1]+1}-{EN[y[0]]}{y[1]+1}"
                                             for x, y in entry[3]) + "\n")
        for r in reasons:
            f.write(f"  ! {r}\n")
        f.write("\n")

print(f"checked 160 tiles: OK={n_ok}  flagged={len(flags)}")
print(f"  odd-count: {n_odd} | bits<->arcs mismatch: {n_mismatch} | "
      f"crossing arcs: {n_cross} | unparsed/unknown: {n_unparsed}")
print("wrote white_fixlist.txt")
