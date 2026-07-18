"""Cross-check user-verified files, then rebuild canonical data from them.

1. GOLD: verify_gold_arcs.txt (human-verified wiring) vs verify_gold_bits.txt /
   diamonddilemma.txt: per tile, the multiset of arc endpoints must equal the set
   bits exactly. On success rebuild arcs.json (ground truth now, no options).
2. WHITE (tiles 1..UPTO): same consistency between verify_white_arcs.txt and
   verify_white_bits.txt; plus even endpoint counts; report per-set pairing
   invariants for silver(1-32) and red(33-80). Rebuild whites.txt for 1..UPTO
   (keep old extraction beyond), and write white_arcs.json (None beyond UPTO).
"""
import json, re, sys
from collections import Counter

UPTO = int(sys.argv[1]) if len(sys.argv) > 1 else 82
EDGE = {"B": 0, "L": 1, "R": 2}

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
        tid, body = int(m.group(1)), m.group(2).strip()
        if not body or body.startswith(("AMBIGUOUS", "UNKNOWN")):
            out[tid] = None
            continue
        body = re.sub(r"\(.*?\)", "", body)   # drop "(ambiguous - guess)" notes
        arcs = []
        ok = True
        for tok in [t.strip() for t in body.split(",") if t.strip()]:
            am = re.match(r"^([BLR])(\d+)-([BLR])(\d+)$", tok)
            if not am:
                ok = False
                break
            arcs.append(((EDGE[am.group(1)], int(am.group(2)) - 1),
                         (EDGE[am.group(3)], int(am.group(4)) - 1)))
        out[tid] = arcs if ok else ("PARSE_ERROR", body)
    return out

def bits_set(bits3):
    return Counter((e, p) for e in range(3) for p, c in enumerate(bits3[e]) if c == "1")

def endpoints_of(arcs):
    c = Counter()
    for a, b in arcs:
        c[a] += 1
        c[b] += 1
    return c

# ---------- GOLD ----------
gbits = parse_bits("verify_gold_bits.txt")
garcs = parse_arcs("verify_gold_arcs.txt")
bad = []
for tid in range(1, 161):
    a = garcs.get(tid)
    if a is None or (isinstance(a, tuple) and a[0] == "PARSE_ERROR"):
        bad.append((tid, "unparsed", a[1] if isinstance(a, tuple) else "missing"))
        continue
    if endpoints_of(a) != bits_set(gbits[tid]):
        want = sorted(bits_set(gbits[tid]))
        got = sorted(endpoints_of(a))
        bad.append((tid, "mismatch", f"bits={want} arcs={got}"))
print(f"GOLD arcs<->bits: {160 - len(bad)}/160 consistent")
for t in bad[:12]:
    print("  BAD", t)

if not bad:
    arcs_json = [[[list(a), list(b)] for a, b in garcs[tid]] for tid in range(1, 161)]
    json.dump(arcs_json, open("arcs.json", "w"))
    json.dump([[m] for m in arcs_json], open("arcs_options.json", "w"))
    print("arcs.json REBUILT from human-verified wiring (single ground-truth option).")

# ---------- WHITE (1..UPTO) ----------
wbits = parse_bits("verify_white_bits.txt")
warcs = parse_arcs("verify_white_arcs.txt")
wbad, wodd, wunk = [], [], []
for tid in range(1, UPTO + 1):
    b = wbits.get(tid)
    if b is None:
        wbad.append((tid, "bits missing", ""))
        continue
    n1 = sum(e.count("1") for e in b)
    if n1 % 2:
        wodd.append(tid)
    a = warcs.get(tid)
    if a is None:
        wunk.append(tid)
        continue
    if isinstance(a, tuple):
        wbad.append((tid, "arc parse", a[1]))
        continue
    if endpoints_of(a) != bits_set(b):
        wbad.append((tid, "mismatch",
                     f"bits={sorted(bits_set(b))} arcs={sorted(endpoints_of(a))}"))
print(f"\nWHITE 1..{UPTO}: odd-count tiles: {wodd}")
print(f"WHITE arcs<->bits inconsistent/unparsed: {len(wbad)}; arcs UNKNOWN: {wunk}")
for t in wbad[:12]:
    print("  BAD", t)

# pairing invariant per challenge set (only within fully covered sets)
for name, lo, hi in [("silver", 1, 32), ("red", 33, 80)]:
    if hi <= UPTO:
        edges = [e for t in range(lo, hi + 1) for e in wbits[t]]
        cnt = Counter(edges)
        unb = [(p, c, cnt.get(p[::-1], 0)) for p, c in sorted(cnt.items())
               if c != cnt.get(p[::-1], 0)]
        print(f"{name} ({lo}-{hi}): unbalanced white pattern classes = {len(unb)}")
        for u in unb[:8]:
            print("   ", u)

# rebuild whites.txt: user-verified for 1..UPTO, previous extraction beyond
old = []
for line in open("whites.txt"):
    m = re.findall(r"\b[01]{11}\b", line)
    if len(m) == 3:
        old.append(m)
with open("whites.txt", "w", encoding="ascii") as f:
    f.write("# WHITE endpoints; tiles 1..%d HUMAN-VERIFIED, rest auto-extracted\n" % UPTO)
    f.write("# (11 bits per edge: bottom R->L, left L->T, right T->R; tile 1 first)\n")
    for tid in range(1, 161):
        row = wbits[tid] if tid <= UPTO and tid in wbits else old[tid - 1]
        f.write(" ".join(row) + ("\n" if tid % 8 else "\n\n"))
# white arcs json (0-based tiles; None where unknown/unverified)
wa = []
for tid in range(1, 161):
    a = warcs.get(tid) if tid <= UPTO else None
    wa.append([[list(x), list(y)] for x, y in a] if isinstance(a, list) else None)
json.dump(wa, open("white_arcs.json", "w"))
print(f"\nwhites.txt rebuilt (1..{UPTO} human-verified); white_arcs.json written "
      f"({sum(1 for x in wa if x)} tiles with verified wiring).")
