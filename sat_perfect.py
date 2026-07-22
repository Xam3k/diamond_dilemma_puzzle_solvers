"""sat_perfect.py -- compact CNF: does a PERFECTLY-MATCHED gold board exist?

Encodes "assign each slot a (tile, rotation) so that it is a permutation of
the tiles and every internal edge matches" as CNF and runs a modern CDCL
solver (Cadical via pysat). A perfectly-matched FULL board (all 160 tiles,
240/240 edges) is a necessary condition for the gold solution, so:

  SAT   -> a 240/240 board exists; save it and loop-check it (single loop =
           the puzzle is SOLVED; multiple loops = a matching-solution that
           still fails the loop rule).
  UNSAT -> NO perfectly-matched full board exists = the gold challenge is
           UNSOLVABLE (an impossibility proof).

This retries the question cp_solver.py left at UNKNOWN, with a leaner encoding
under a different solver.

Encoding (channelled, avoids O(n^2) pairwise edge clauses):
  x(s,t,r)  slot s holds tile t at rotation r
  e(s,j,d)  slot s presents dense pattern d on its edge j
  - exactly-one (t,r) per slot; exactly-one (s,r) per tile
  - x(s,t,r) -> e(s,j, dense(tiles[t][(j+r)%3]))   for j in 0,1,2
  - at-most-one e(s,j,*)
  - edge (sA,jA)|(sB,jB): e(sA,jA,d) -> e(sB,jB, rev(d))   for every d

Usage:
  python sat_perfect.py [--subset board.txt] [--wall SECONDS]
    --subset : restrict to the slots+tiles used by board.txt (validation:
               the 142-partial is a KNOWN-SAT sub-problem, so the encoder
               must return SAT -- a completeness check on real data).
    default  : the full 160-tile question.
"""
import json
import sys
import time

from pysat.card import CardEnc, EncType
from pysat.formula import IDPool
from pysat.solvers import Cadical195

g = json.load(open("geometry.json"))
tiles = json.load(open("tiles.json"))
rev = lambda p: p[::-1]
n = 160

# dense pattern ids
pats = sorted({p for t in range(n) for p in tiles[t]} |
              {rev(p) for t in range(n) for p in tiles[t]})
pid = {p: i for i, p in enumerate(pats)}
revd = {i: pid[rev(p)] for p, i in pid.items()}

# ---- parse args ----
subset_file = None
wall = 1800.0
a = sys.argv[1:]
while a:
    if a[0] == "--subset":
        subset_file = a[1]; a = a[2:]
    elif a[0] == "--wall":
        wall = float(a[1]); a = a[2:]
    else:
        a = a[1:]

if subset_file:
    board = {}
    for tok in open(subset_file).read().split():
        s, t, r = map(int, tok.split(":"))
        board[s] = (t, r)
    SLOTS = sorted(board)
    TILES = sorted({t for t, _ in board.values()})
    print(f"SUBSET validation: {len(SLOTS)} slots, {len(TILES)} tiles "
          f"(must be SAT; {subset_file} witnesses it)", flush=True)
else:
    SLOTS = list(range(n))
    TILES = list(range(n))
    print(f"FULL question: {len(SLOTS)} slots, {len(TILES)} tiles "
          f"(SAT=>240/240 board exists; UNSAT=>puzzle unsolvable)", flush=True)

Sset, Tset = set(SLOTS), set(TILES)
vp = IDPool()
def X(s, t, r):
    return vp.id(("x", s, t, r))
def E(s, j, d):
    return vp.id(("e", s, j, d))

clauses = []

# pattern shown on slot-edge j by tile t at rotation r
def dpat(t, j, r):
    return pid[tiles[t][(j + r) % 3]]

# slot: exactly one (t,r)
for s in SLOTS:
    lits = [X(s, t, r) for t in TILES for r in range(3)]
    clauses.extend(CardEnc.equals(lits=lits, bound=1, vpool=vp,
                                  encoding=EncType.seqcounter).clauses)
# tile: exactly one (s,r)
for t in TILES:
    lits = [X(s, t, r) for s in SLOTS for r in range(3)]
    clauses.extend(CardEnc.equals(lits=lits, bound=1, vpool=vp,
                                  encoding=EncType.seqcounter).clauses)
# x -> e links, and collect which patterns actually occur per (s,j)
occ = {}
for s in SLOTS:
    for t in TILES:
        for r in range(3):
            for j in range(3):
                d = dpat(t, j, r)
                clauses.append([-X(s, t, r), E(s, j, d)])
                occ.setdefault((s, j), set()).add(d)
# reverse link e(s,j,d) -> OR of x(s,t,r) that present d  (ties e to a REAL
# tile; without this the solver can set a phantom e to fake an edge match)
pres = {}
for s in SLOTS:
    for t in TILES:
        for r in range(3):
            for j in range(3):
                pres.setdefault((s, j, dpat(t, j, r)), []).append(X(s, t, r))
for (s, j, d), xs in pres.items():
    clauses.append([-E(s, j, d)] + xs)
# at-most-one e(s,j,*)
for (s, j), ds in occ.items():
    dl = sorted(ds)
    for i in range(len(dl)):
        for k in range(i + 1, len(dl)):
            clauses.append([-E(s, j, dl[i]), -E(s, j, dl[k])])
# edge match (internal edges only). If a slot presents pattern d on this edge,
# the facing slot must present rev(d); if NO available tile can present rev(d)
# there, then d is impossible on this edge (forbid it) -- never reference an
# unachievable pattern var (that was the phantom-match bug).
for e in g["edges"]:
    a1, j1, b1, k1 = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
    if a1 in Sset and b1 in Sset:
        oa, ob = occ.get((a1, j1), set()), occ.get((b1, k1), set())
        for d in oa:
            if revd[d] in ob:
                clauses.append([-E(a1, j1, d), E(b1, k1, revd[d])])
            else:
                clauses.append([-E(a1, j1, d)])
        for d in ob:
            if revd[d] in oa:
                clauses.append([-E(b1, k1, d), E(a1, j1, revd[d])])
            else:
                clauses.append([-E(b1, k1, d)])

print(f"CNF: {vp.top} vars, {len(clauses)} clauses", flush=True)

solver = Cadical195(bootstrap_with=clauses)
t0 = time.time()
res = solver.solve()          # (wall-bounded externally by the caller)
dt = time.time() - t0
if res is None:
    print(f"UNKNOWN after {dt:.0f}s", flush=True)
    sys.exit(0)
if not res:
    print(f"UNSAT after {dt:.0f}s", flush=True)
    if not subset_file:
        print("PROOF: no perfectly-matched full gold board exists => "
              "the gold challenge is UNSOLVABLE.", flush=True)
    else:
        print("(subset UNSAT -- encoder COMPLETENESS BUG, the witness board "
              "should have satisfied it)", flush=True)
    sys.exit(0)

# SAT: decode
model = set(v for v in solver.get_model() if v > 0)
place = {}
for s in SLOTS:
    for t in TILES:
        for r in range(3):
            if X(s, t, r) in model:
                place[s] = (t, r)
# independent verification
mm = 0
for e in g["edges"]:
    a1, j1, b1, k1 = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
    if a1 in place and b1 in place:
        ta, ra = place[a1]; tb, rb = place[b1]
        if tiles[ta][(j1 + ra) % 3] != rev(tiles[tb][(k1 + rb) % 3]):
            mm += 1
print(f"SAT after {dt:.0f}s: {len(place)} tiles placed, {mm} mismatched edges "
      f"(independent check)", flush=True)
out = "sat_perfect_subset.txt" if subset_file else "sat_perfect_FULL.txt"
with open(out, "w") as f:
    f.write(" ".join(f"{s}:{place[s][0]}:{place[s][1]}" for s in sorted(place)) + "\n")
print(f"wrote {out}", flush=True)
if not subset_file and mm == 0:
    print("*** A PERFECTLY-MATCHED FULL BOARD EXISTS -- loop-check it next! ***", flush=True)
