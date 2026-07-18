"""Trace the gold-line graph for a placement and COUNT closed loops.

Node = (slot, edge_index 0..2, position 0..10) at every set endpoint.
Each node has degree 2:
  - within-tile arc: from arcs.json (tile-local edges), mapped through rotation
  - cross-tile link: pos p on slot s edge j  <->  pos 10-p on neighbor edge
So the gold lines decompose into disjoint cycles. A Gold solution needs exactly 1.

Placement convention (matches the rest of the project): tile t with rotation r in
slot s puts tile-edge (j+r)%3 on slot-edge j. A position p runs along the edge in the
tile's clockwise sense, preserved by rotation; reversed across a shared boundary.

API: count_loops(placement, adj, tiles_arcs) -> (n_loops, ok, detail)
CLI: python loop_trace.py <instance.txt> <placement.txt> [arcs.json]
"""
import json, sys
from sat_solver import load_instance


def build(instance):
    n, adj, tiles, seed_slots, seed_tile = load_instance(instance)
    return n, adj, tiles


def count_loops(placement, n, adj, arcs, tiles):
    """placement[s] = (tile, rot). Returns (n_loops, all_degree2, n_nodes)."""
    # within-tile arc map per slot, expressed in SLOT-edge coords:
    # tile-edge e sits on slot-edge j with e=(j+r)%3  =>  j=(e-r)%3
    nbr = {}   # (s,j,p) -> neighbor node via within-tile arc
    cross = {} # (s,j,p) -> neighbor node across boundary
    nodes = set()
    for s in range(n):
        t, r = placement[s]
        for (a, b) in arcs[t]:
            ea, pa = a; eb, pb = b
            ja = (ea - r) % 3
            jb = (eb - r) % 3
            na = (s, ja, pa); nb = (s, jb, pb)
            nbr[na] = nb; nbr[nb] = na
            nodes.add(na); nodes.add(nb)
    # cross links from adjacency
    for s in range(n):
        for j in range(3):
            b, k = adj[s][j]
            for p in range(11):
                node = (s, j, p)
                if node in nodes:
                    cross[node] = (b, k, 10 - p)
    # verify degree 2: every node has both an arc-neighbor and a cross-neighbor that exists
    ok = True
    for nd in nodes:
        if nd not in nbr or nd not in cross or cross[nd] not in nodes:
            ok = False
            break
    if not ok:
        return (-1, False, len(nodes))
    # trace cycles: alternate arc, cross, arc, cross, ...
    seen = set()
    loops = 0
    for start in nodes:
        if start in seen:
            continue
        loops += 1
        cur = start
        use_arc = True
        while cur not in seen:
            seen.add(cur)
            cur = nbr[cur] if use_arc else cross[cur]
            use_arc = not use_arc
    return (loops, True, len(nodes))


def load_placement(path):
    pl = {}
    for tok in open(path).read().split():
        s, t, r = map(int, tok.split(":"))
        pl[s] = (t, r)
    return pl


if __name__ == "__main__":
    inst, place = sys.argv[1], sys.argv[2]
    arcs = json.load(open(sys.argv[3] if len(sys.argv) > 3 else "arcs.json"))
    n, adj, tiles = build(inst)
    pl = load_placement(place)
    if len(pl) != n:
        print(f"NOTE: placement covers {len(pl)}/{n} slots; loop count needs a FULL placement.")
    else:
        loops, ok, nn = count_loops([pl[s] for s in range(n)], n, adj, arcs, tiles)
        print(f"nodes(endpoints)={nn} all_degree2={ok} LOOPS={loops}")
        print("SINGLE LOOP -> GOLD SOLUTION!" if (ok and loops == 1) else
              f"{loops} loops (need exactly 1)")
