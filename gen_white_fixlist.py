"""Produce white_fixlist.txt: the small set of tiles (1..UPTO) whose white data
still needs a second look, with three-witness evidence per tile:
  U-bits = user's verify_white_bits.txt, U-arcs = user's verify_white_arcs.txt,
  AUTO   = automated image extraction (pre-user whites backup if present).
Flag a tile if: odd endpoint count, U-arcs vs U-bits mismatch, or U vs AUTO differ.
"""
import re
from collections import Counter

UPTO = 82
EDGE = {"B": 0, "L": 1, "R": 2}
EN = "BLR"

def parse_bits(path):
    out = {}
    for line in open(path):
        m = re.match(r"\s*(\d+):\s+([01]{11})\s+([01]{11})\s+([01]{11})", line)
        if m:
            out[int(m.group(1))] = [m.group(2), m.group(3), m.group(4)]
    return out

def parse_plain(path):
    rows = []
    for line in open(path):
        m = re.findall(r"\b[01]{11}\b", line)
        if len(m) == 3:
            rows.append(m)
    return rows

def parse_arcs(path):
    out = {}
    for line in open(path):
        m = re.match(r"\s*(\d+):\s*(.*)$", line)
        if not m:
            continue
        tid, body = int(m.group(1)), re.sub(r"\(.*?\)", "", m.group(2)).strip()
        arcs = []
        for tok in [t.strip() for t in body.split(",") if t.strip()]:
            am = re.match(r"^([BLR])(\d+)-([BLR])(\d+)$", tok)
            if am:
                arcs.append(((EDGE[am.group(1)], int(am.group(2)) - 1),
                             (EDGE[am.group(3)], int(am.group(4)) - 1)))
        out[tid] = arcs
    return out

def setof(bits3):
    return {(e, p) for e in range(3) for p, c in enumerate(bits3[e]) if c == "1"}

def fmt(eps):
    return ", ".join(f"{EN[e]}{p+1}" for e, p in sorted(eps)) or "(none)"

ub = parse_bits("verify_white_bits.txt")
ua = parse_arcs("verify_white_arcs.txt")
# AUTO extraction = the pre-user machine extraction, regenerate reference from images
auto = None
try:
    import subprocess
    # use the last auto whites if a backup exists; else skip AUTO witness
    auto = parse_plain("whites_auto_backup.txt")
except Exception:
    auto = None

lines = ["# WHITE FIX LIST - only these tiles need re-checking (tiles 1..%d)" % UPTO,
         "# For each: what your bits say vs what your arcs imply (and AUTO extraction).",
         "# Please correct verify_white_bits.txt and verify_white_arcs.txt for these.",
         ""]
nflag = 0
for tid in range(1, UPTO + 1):
    reasons = []
    b = ub.get(tid)
    bs = setof(b) if b else set()
    n1 = len(bs)
    if b is None:
        reasons.append("bits line missing/unparsed")
    elif n1 % 2:
        reasons.append("ODD endpoint count (impossible)")
    a = ua.get(tid)
    as_ = set()
    if a:
        for x, y in a:
            as_.add(x); as_.add(y)
    if a is not None and b is not None and as_ != bs:
        only_b = bs - as_
        only_a = as_ - bs
        det = []
        if only_b:
            det.append("in bits only: " + fmt(only_b))
        if only_a:
            det.append("in arcs only: " + fmt(only_a))
        reasons.append("bits<->arcs disagree (" + "; ".join(det) + ")")
    if auto and b is not None:
        at = setof(auto[tid - 1])
        if at != bs:
            reasons.append("differs from AUTO extraction (auto: " + fmt(at) + ")")
    if reasons:
        nflag += 1
        lines.append(f"tile {tid}:")
        lines.append(f"  your bits -> {fmt(bs)}")
        if a is not None:
            lines.append(f"  your arcs -> {fmt(as_)}  ({', '.join(EN[x[0]]+str(x[1]+1)+'-'+EN[y[0]]+str(y[1]+1) for x,y in a)})")
        for r in reasons:
            lines.append(f"  ! {r}")
        lines.append("")
open("white_fixlist.txt", "w", encoding="ascii").write("\n".join(lines))
print(f"white_fixlist.txt written: {nflag} tiles flagged of {UPTO}")
