"""score_board.py -- independent scorer for any board file ("slot:tile:rot ...").

Reports BOTH score categories:
  A) perfect-partial: placed tiles, and whether ALL touched edges match
     (a valid Category-A board has zero mismatches among placed-placed edges)
  B) matched edges: edges with both sides placed AND patterns mutually reversed

Conventions mirrored from ruin_recreate.py / cp solvers (independently of
tabu_solver.c): tile edge (j+r)%3 lies on slot edge j; two facing edges match
iff pattern == reversed(partner pattern).

Usage: python score_board.py <board.txt> [--edges]  (--edges lists mismatches)
"""
import json
import sys

g = json.load(open("geometry.json"))
tiles = json.load(open("tiles.json"))
rev = lambda p: p[::-1]

cur = {}
for tok in open(sys.argv[1]).read().split():
    s, t, r = map(int, tok.split(":"))
    cur[s] = (t, r)

used = [t for t, _ in cur.values()]
assert len(set(used)) == len(used), "DUPLICATE TILE USED!"

def pat(s, j):
    t, r = cur[s]
    return tiles[t][(j + r) % 3]

matched = mismatched = open_edges = 0
mis_list = []
for e in g["edges"]:
    a, ja, b, jb = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
    if a in cur and b in cur:
        if pat(a, ja) == rev(pat(b, jb)):
            matched += 1
        else:
            mismatched += 1
            mis_list.append((a, ja, b, jb))
    else:
        open_edges += 1

n_edges = len(g["edges"])
print(f"board={sys.argv[1]}")
print(f"tiles placed         : {len(cur)}/160")
print(f"edges matched        : {matched}/{n_edges}")
print(f"edges mismatched     : {mismatched}")
print(f"edges w/ open side   : {open_edges}")
print(f"Category A valid     : {mismatched == 0}")
print(f"Category A score     : {len(cur) if mismatched == 0 else 'n/a (has mismatches)'}")
print(f"Category B score     : {matched}/{n_edges}")
if "--edges" in sys.argv and mis_list:
    for a, ja, b, jb in mis_list:
        print(f"  MISMATCH slot{a}.e{ja} ({pat(a,ja)}) vs slot{b}.e{jb} ({pat(b,jb)})")
