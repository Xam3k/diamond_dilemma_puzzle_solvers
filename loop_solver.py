"""Loop-following solver: search for a placement that is a full edge-matching AND
whose gold lines form exactly ONE loop through all 160 tiles.

Thread the loop: from the current exit endpoint, cross the shared boundary (pos p ->
10-p) into the neighbour slot. If that slot is unplaced, choose a tile+rotation with a
gold endpoint at the entry position (heavy constraint); follow that tile's arc to its
exit; continue. If placed, follow its (untraversed) arc. The loop must traverse every
arc of every tile and close only after all 160 tiles are woven in; premature closure or
a dead end triggers backtracking.

Usage: python loop_solver.py <instance.txt> [node_limit] [seed]
Verifies any solution with loop_trace and writes it to <instance>.loop_solution.txt.
"""
import json, sys, time
from sat_solver import load_instance
from derive_arcs import derive
from loop_trace import count_loops

import os
inst = sys.argv[1]
node_limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
USE_FC = os.environ.get("FC", "0") == "1"   # forward-checking (slow but prunes)
n, adj, tiles, seed_slots, seed_tile = load_instance(inst)
arcs_raw, amb = derive(tiles)
print(f"{inst}: {n} tiles, ambiguous wirings={len(amb)}", flush=True)

# total endpoints per tile / total arcs
tile_arcs = [a if a else [] for a in arcs_raw]
total_arcs = sum(len(a) for a in tile_arcs)

# arcmap[(t,r)]: dict slot-endpoint (sj,p) -> partner slot-endpoint (sj2,p2)
# tile-edge e sits on slot-edge sj = (e - r) % 3
def build_arcmap(t, r):
    d = {}
    for (a, b) in tile_arcs[t]:
        ea, pa = a; eb, pb = b
        sa = ((ea - r) % 3, pa); sb = ((eb - r) % 3, pb)
        d[sa] = sb; d[sb] = sa
    return d
arcmap = {}
for t in range(n):
    for r in range(3):
        arcmap[(t, r)] = build_arcmap(t, r)

# endpoint_index[(sj,p)] = list of (t,r) having a gold endpoint at slot-edge sj, pos p
endpoint_index = {}
for t in range(n):
    for r in range(3):
        for (sj, p) in arcmap[(t, r)]:
            endpoint_index.setdefault((sj, p), []).append((t, r))

slot_pl = [None] * n          # slot -> (t,r)
used = [False] * n
visited = set()               # visited slot-endpoints (s,sj,p)
nodes = 0
placed_now = 0
best_depth = 0
t0 = time.time()
use_sym = len(seed_slots) < n
rep = set(seed_slots)

def neighbor(s, sj, p):
    b, k = adj[s][sj]
    return (b, k, 10 - p)

rev = lambda p: p[::-1]
def edges_consistent(es, t, r):
    """All edges of slot es that border a placed slot must match (full matching)."""
    for j in range(3):
        b, k = adj[es][j]
        if slot_pl[b] is not None:
            tb, rb = slot_pl[b]
            if tiles[t][(j + r) % 3] != rev(tiles[tb][(k + rb) % 3]):
                return False
    return True

def has_candidate(nb):
    """Forward check: does some unused tile+rotation fit slot nb's placed neighbors?"""
    for t in range(n):
        if used[t]:
            continue
        for r in range(3):
            if edges_consistent(nb, t, r):
                return True
    return False

def fc_ok(es):
    """After placing at es, every unplaced neighbor must still have a candidate."""
    for j in range(3):
        b = adj[es][j][0]
        if slot_pl[b] is None and not has_candidate(b):
            return False
    return True

sols = []

def follow(start, head):
    """Thread the loop from exit endpoint `head`=(s,sj,p). Return True if a full
    single-loop placement is completed."""
    global nodes
    while True:
        s, sj, p = head
        es, ek, ep = neighbor(s, sj, p)        # entry endpoint in neighbor
        entry = (es, ek, ep)
        if slot_pl[es] is None:
            # place a tile here matching the entry endpoint
            cands = [(t, r) for (t, r) in endpoint_index.get((ek, ep), [])
                     if not used[t]]
            if use_sym:
                cands = [(t, r) for (t, r) in cands if t != seed_tile or es in rep]
            for (t, r) in cands:
                global nodes
                nodes += 1
                if node_limit and nodes > node_limit:
                    return False
                if not edges_consistent(es, t, r):
                    continue
                # place
                global placed_now, best_depth
                slot_pl[es] = (t, r); used[t] = True
                placed_now += 1
                if placed_now > best_depth:
                    best_depth = placed_now
                    if best_depth % 10 == 0 or best_depth > 150:
                        print(f"  depth={best_depth} nodes={nodes} t={time.time()-t0:.0f}s",
                              flush=True)
                ex = arcmap[(t, r)][(ek, ep)]      # arc partner -> exit
                exit_ep = (es, ex[0], ex[1])
                visited.add(entry); visited.add(exit_ep)
                if (not USE_FC or fc_ok(es)) and follow(start, exit_ep):
                    return True
                visited.discard(entry); visited.discard(exit_ep)
                slot_pl[es] = None; used[t] = False; placed_now -= 1
            return False
        else:
            # neighbor already placed
            (t, r) = slot_pl[es]
            if (ek, ep) not in arcmap[(t, r)]:
                return False                       # no endpoint here -> mismatch
            if entry in visited:
                # arc already traversed -> we are closing the loop
                if entry == start:
                    # closed. success iff everything woven in
                    if all(used) and len(visited) == 2 * total_arcs:
                        return True
                    return False                   # premature / multi-loop
                return False
            ex = arcmap[(t, r)][(ek, ep)]
            exit_ep = (es, ex[0], ex[1])
            visited.add(entry); visited.add(exit_ep)
            head = exit_ep
            # loop continues (no branching); iterate
            if exit_ep == start:                   # closed onto start via this arc
                if all(used) and len(visited) == 2 * total_arcs:
                    return True
                return False


def solve():
    # choose seed slot + seed tile/rotation, then pick a starting arc and thread
    seed_candidates = seed_slots if use_sym else [0]
    for s0 in (seed_candidates if use_sym else range(n)):
        for t0_ in range(n):
            if use_sym and t0_ != seed_tile:
                continue
            for r0 in range(3):
                if not arcmap[(t0_, r0)]:
                    continue
                # start the loop on one endpoint of this tile's first arc
                slot_pl[s0] = (t0_, r0); used[t0_] = True
                # pick the lexicographically first arc-endpoint as exit
                ep0 = sorted(arcmap[(t0_, r0)])[0]
                start = (s0, ep0[0], ep0[1])
                partner = arcmap[(t0_, r0)][ep0]
                exit_ep = (s0, partner[0], partner[1])
                visited.clear(); visited.add(start); visited.add(exit_ep)
                if follow(start, exit_ep):
                    return [slot_pl[s] for s in range(n)]
                slot_pl[s0] = None; used[t0_] = False
                visited.clear()
        if not use_sym:
            break   # for non-sym, trying all seed tiles in slot 0 suffices
    return None

res = solve()
dt = time.time() - t0
if res:
    loops, ok, nn = count_loops(res, n, adj, tile_arcs, tiles)
    print(f"SOLUTION found in {nodes} nodes, {dt:.1f}s; tracer: loops={loops} ok={ok}",
          flush=True)
    if ok and loops == 1:
        with open(inst.replace(".txt", "") + ".loop_solution.txt", "w") as f:
            f.write(" ".join(f"{s}:{res[s][0]}:{res[s][1]}" for s in range(n)) + "\n")
        print("*** VERIFIED SINGLE-LOOP GOLD SOLUTION ***", flush=True)
    else:
        print("solver returned but tracer disagrees -- bug", flush=True)
else:
    print(f"no single-loop solution found (nodes={nodes}, {dt:.1f}s, "
          f"limit={'hit' if node_limit and nodes>node_limit else 'exhausted/none'})",
          flush=True)
