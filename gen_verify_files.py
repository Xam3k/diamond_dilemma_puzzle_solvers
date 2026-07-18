"""Generate the four manual-verification files for tile-by-tile checking.

CONVENTIONS (all files):
- Tile #N = tile numbered N in Jaap's sheet images (silver 1-32, red 33-80, blue 81-160).
- Each tile has 3 edges, denoted B (bottom), L (left), R (right) with the tile drawn
  upright, number readable.
- Each edge has 11 points numbered 1..11 CLOCKWISE around the tile:
    B: counted right -> left,  L: counted bottom -> top,  R: counted top -> bottom.
  Point k sits at fraction k/12 along the edge (points are interior; corners are
  not points).
- Bit strings: 11 chars, char k (1st..11th) = point k, '1' = a line touches there.

Files:
  verify_gold_bits.txt   - gold bits (SOURCE: Jaap's own data; check anyway)
  verify_white_bits.txt  - white bits (OUR extraction; noisy - please correct)
  verify_gold_arcs.txt   - our current belief of gold internal connections
  verify_white_arcs.txt  - best-effort white internal connections
Arc notation: B3-L5 means the line touching bottom point 3 connects to left point 5.
"""
import json, re
from derive_arcs import parse, derive

gold = parse("diamonddilemma.txt")
white = parse("whites.txt")
gold_opts = json.load(open("arcs_options.json"))

EDGE = "BLR"

def arcstr(m):
    out = []
    for (a, b) in m:
        (ea, pa), (eb, pb) = a, b
        out.append(f"{EDGE[ea]}{pa+1}-{EDGE[eb]}{pb+1}")
    return ", ".join(sorted(out))

HDR = """# Diamond Dilemma manual verification file
# Tile #N = Jaap's sheet numbering. Edges: B=bottom, L=left, R=right (tile upright).
# Points 1..11 clockwise: B right->left, L bottom->top, R top->bottom.
# Point k is at fraction k/12 along the edge (corners are NOT points).
# Format: 'N: <B bits> <L bits> <R bits>'. Mark corrections by editing the line.
"""

with open("verify_gold_bits.txt", "w", encoding="ascii") as f:
    f.write(HDR)
    f.write("# GOLD lines. Source: Jaap's own data file (high trust) - verify anyway.\n\n")
    for i, t in enumerate(gold):
        f.write(f"{i+1:3d}: {t[0]} {t[1]} {t[2]}\n")
        if i % 8 == 7:
            f.write("\n")

with open("verify_white_bits.txt", "w", encoding="ascii") as f:
    f.write(HDR)
    f.write("# WHITE lines. Source: OUR image extraction (noisy!). '!ODD' = provably\n"
            "# wrong (odd endpoint count); please fix those first.\n\n")
    for i, t in enumerate(white):
        n = sum(e.count("1") for e in t)
        flag = "   !ODD" if n % 2 else ""
        f.write(f"{i+1:3d}: {t[0]} {t[1]} {t[2]}{flag}\n")
        if i % 8 == 7:
            f.write("\n")

AHDR = """# Diamond Dilemma internal-connection (wiring) verification file
# Same conventions as the bits files (B/L/R, points 1..11 clockwise).
# 'B3-L5' = the line at bottom point 3 connects inside the tile to left point 5.
# Lines starting 'N:' = our single current belief.
# Lines with 'A)' and 'B)' = two plausible options - please write which is right
#   (or a different pairing if both are wrong).
"""

with open("verify_gold_arcs.txt", "w", encoding="ascii") as f:
    f.write(AHDR)
    f.write("# GOLD line connections (from geometry + Jaap's tile drawings).\n\n")
    for i in range(160):
        opts = gold_opts[i]
        ms = [[((a[0], a[1]), (b[0], b[1])) for a, b in m] for m in opts]
        if len(ms) == 1:
            f.write(f"{i+1:3d}: {arcstr(ms[0])}\n")
        else:
            f.write(f"{i+1:3d}: AMBIGUOUS\n")
            for tag, m in zip("AB", ms):
                f.write(f"     {tag}) {arcstr(m)}\n")
        if i % 8 == 7:
            f.write("\n")

wopts, wamb = derive(white)
with open("verify_white_arcs.txt", "w", encoding="ascii") as f:
    f.write(AHDR)
    f.write("# WHITE line connections (best-effort from our noisy bits - fix bits "
            "first,\n# then correct these).\n\n")
    amb_ids = {t for t, _ in wamb}
    for i in range(160):
        if wopts[i] is None:
            f.write(f"{i+1:3d}: UNKNOWN (bits invalid)\n")
        else:
            m = [((a[0], a[1]), (b[0], b[1])) for a, b in wopts[i]]
            tag = "  (ambiguous - guess)" if i in amb_ids else ""
            f.write(f"{i+1:3d}: {arcstr(m)}{tag}\n")
        if i % 8 == 7:
            f.write("\n")

print("wrote verify_gold_bits.txt, verify_white_bits.txt, "
      "verify_gold_arcs.txt, verify_white_arcs.txt")
