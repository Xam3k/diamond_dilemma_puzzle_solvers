"""count_loops.py -- count CLOSED gold loops and open paths in any board file.

A closed loop is a connected component of the gold-line graph in which every
endpoint is joined on both sides (degree 2 everywhere). Such a component can
never be extended, so a board containing one can NOT be part of the true
single-loop solution: it is a structural dead end no matter how many edges
match.

Nodes are physical gold-line endpoints: (board_edge, position) normalised to
slotA's reading direction, since a point at position p on slotA's edge is the
same physical point as position 10-p on slotB's facing edge.

Usage: python count_loops.py <board.txt> [more boards...]
"""
import json
import sys
from collections import defaultdict

g = json.load(open("geometry.json"))
arcs = json.load(open("arcs.json"))

# board edge lookup: (slot, local_edge) -> (edge_id, is_slotA)
edge_of = {}
for i, e in enumerate(g["edges"]):
    edge_of[(e["slotA"], e["edgeA"])] = (i, True)
    edge_of[(e["slotB"], e["edgeB"])] = (i, False)

def analyse(path):
    pl = {}
    for tok in open(path).read().split():
        s, t, r = map(int, tok.split(":"))
        pl[s] = (t, r)

    adj = defaultdict(list)          # node -> list of neighbour nodes (via arcs)
    for s, (t, r) in pl.items():
        for (A_, B_) in arcs[t]:
            ends = []
            for (e, p) in (A_, B_):
                j = (e - r) % 3                    # tile edge e sits on slot edge j
                i, is_a = edge_of[(s, j)]
                ends.append((i, p if is_a else 10 - p))
            adj[ends[0]].append(ends[1])
            adj[ends[1]].append(ends[0])

    seen, closed, open_paths, closed_sizes = set(), 0, 0, []
    for start in adj:
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m in adj[n]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        # closed iff every node in the component has degree 2
        if all(len(adj[n]) == 2 for n in comp):
            closed += 1
            closed_sizes.append(len(comp))
        else:
            open_paths += 1

    print(f"{path}")
    print(f"  tiles placed        : {len(pl)}")
    print(f"  CLOSED gold loops   : {closed}   sizes(points)={sorted(closed_sizes, reverse=True)[:12]}")
    print(f"  open gold paths     : {open_paths}")
    verdict = ("CANNOT be extended to the single-loop solution "
               "(contains closed sub-loops)" if closed else
               "no closed sub-loop, still loop-feasible")
    print(f"  verdict             : {verdict}\n")
    return closed

if __name__ == "__main__":
    for p in (sys.argv[1:] or ["rr_best.txt", "edges_208_checkpoint.txt"]):
        analyse(p)
