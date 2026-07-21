"""make_loopfree.py -- extract the largest easy LOOP-FEASIBLE partial from a board.

A board containing a closed gold sub-loop can never be extended to the single
required loop. Breaking a closed loop needs only ONE tile removed from it, so
a board with k closed loops is at most k tiles away from being loop-feasible
(fewer if loops share tiles).

This greedily removes a small hitting set of tiles (each removal kills as many
remaining closed loops as possible) and writes the result, which is then:
  - zero mismatched edges (removal never creates a mismatch)
  - zero closed sub-loops  -> a valid prefix of a potential solution

Usage: python make_loopfree.py <board.txt> [out.txt]
"""
import json
import sys
from collections import defaultdict

g = json.load(open("geometry.json"))
arcs = json.load(open("arcs.json"))
tiles = json.load(open("tiles.json"))
rev = lambda p: p[::-1]

edge_of = {}
for i, e in enumerate(g["edges"]):
    edge_of[(e["slotA"], e["edgeA"])] = (i, True)
    edge_of[(e["slotB"], e["edgeB"])] = (i, False)

def build(pl):
    """adjacency over endpoints, plus which slots own each arc"""
    adj = defaultdict(list)
    owner = defaultdict(set)          # frozenset(node pair) -> slots
    for s, (t, r) in pl.items():
        for (A_, B_) in arcs[t]:
            ends = []
            for (e, p) in (A_, B_):
                j = (e - r) % 3
                i, is_a = edge_of[(s, j)]
                ends.append((i, p if is_a else 10 - p))
            adj[ends[0]].append(ends[1])
            adj[ends[1]].append(ends[0])
            owner[frozenset(ends)].add(s)
    return adj, owner

def closed_loops(pl):
    """list of (set_of_slots_on_loop)"""
    adj, owner = build(pl)
    seen, loops = set(), []
    for start in adj:
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            n = stack.pop(); comp.append(n)
            for m in adj[n]:
                if m not in seen:
                    seen.add(m); stack.append(m)
        if all(len(adj[n]) == 2 for n in comp):
            compset = set(comp)
            slots = set()
            for key, ss in owner.items():
                if key <= compset:
                    slots |= ss
            loops.append(slots)
    return loops

def mismatches(pl):
    n = 0
    for e in g["edges"]:
        a, ja, b, jb = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
        if a in pl and b in pl:
            ta, ra = pl[a]; tb, rb = pl[b]
            if tiles[ta][(ja + ra) % 3] != rev(tiles[tb][(jb + rb) % 3]):
                n += 1
    return n

src = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else src.replace(".txt", "_loopfree.txt")
pl = {}
for tok in open(src).read().split():
    s, t, r = map(int, tok.split(":")); pl[s] = (t, r)

print(f"start: {len(pl)} tiles, {mismatches(pl)} mismatches, "
      f"{len(closed_loops(pl))} closed loops")

removed = []
while True:
    loops = closed_loops(pl)
    if not loops:
        break
    # greedy: remove the slot that lies on the most remaining closed loops
    cnt = defaultdict(int)
    for L in loops:
        for s in L:
            cnt[s] += 1
    victim = max(cnt, key=lambda s: (cnt[s], -s))
    pl.pop(victim)
    removed.append(victim)

print(f"removed {len(removed)} tiles: {sorted(removed)}")
print(f"result: {len(pl)} tiles, {mismatches(pl)} mismatches, "
      f"{len(closed_loops(pl))} closed loops")
with open(out, "w") as f:
    f.write(" ".join(f"{s}:{pl[s][0]}:{pl[s][1]}" for s in sorted(pl)) + "\n")
print(f"wrote {out}")
