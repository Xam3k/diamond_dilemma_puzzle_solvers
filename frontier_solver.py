"""Exhaustive frontier-ordered backtracker for the Diamond Dilemma matching problem.

Key idea (from the structural analysis): when a slot is constrained on TWO already-
placed edges, the number of compatible (tile,rot) candidates collapses to ~0.35.
So we precompute a STATIC fill order that maximizes, for each slot, the number of
its neighbors that come earlier in the order. Then backtracking is near-deterministic
(mostly 0 or 1 candidate per slot) and can plausibly EXHAUST the space -- finding a
full 160-matching or proving none exists.

Symmetry breaking (gold): the board's rotation group has order 10 (no reflections --
tiles can't be mirrored). Tile 0 may only sit in an orbit-representative slot.

Usage: python frontier_solver.py <instance.txt> [mode] [node_limit]
  mode: "first" (stop at first full matching, default) | "count" (count all) |
        "max" (track deepest partial)
"""
import sys, time
from sat_solver import load_instance

inst = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "first"
node_limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
n, adj, tiles, seed_slots, seed_tile = load_instance(inst)
rev_s = lambda p: p[::-1]

# pattern -> list of (tile, rot) that place it on slot-edge j  (precomputed per j)
from collections import defaultdict
place_by = [defaultdict(list) for _ in range(3)]
for t in range(n):
    for r in range(3):
        for j in range(3):
            place_by[j][tiles[t][(j + r) % 3]].append((t, r))

# ---- precompute static fill order maximizing earlier-placed neighbors ----
neigh = [[adj[s][j] for j in range(3)] for s in range(n)]   # [(slot,edge)]*3
# start from a seed slot (orbit rep if symmetry breaking present)
start = seed_slots[0]
order = [start]
inorder = {start}
# greedy: repeatedly add the slot (adjacent to the placed set) with the most
# already-ordered neighbors; tie-break by lowest index for determinism
while len(order) < n:
    best, best_cnt = -1, -1
    for s in range(n):
        if s in inorder:
            continue
        cnt = sum(1 for (b, k) in neigh[s] if b in inorder)
        if cnt > best_cnt or (cnt == best_cnt and (best == -1 or s < best)):
            if cnt > 0 or len(order) == 0:
                best, best_cnt = s, cnt
    order.append(best)
    inorder.add(best)
pos = {s: i for i, s in enumerate(order)}
# how many neighbors of order[i] are EARLIER in the order (the constraint count)
constr_hist = defaultdict(int)
for i, s in enumerate(order):
    c = sum(1 for (b, k) in neigh[s] if pos[b] < i)
    constr_hist[c] += 1
print(f"fill order built. constraint-count histogram (earlier-placed neighbors): "
      f"{dict(sorted(constr_hist.items()))}", flush=True)

use_sym = len(seed_slots) < n
rep_slots = set(seed_slots) if use_sym else None

slot_tile = [-1] * n
slot_rot = [-1] * n
used = [False] * n
nodes = 0
sols = 0
best_depth = 0
t0 = time.time()
sys.setrecursionlimit(10000)

def candidates(s):
    # constraints from earlier-placed neighbors
    req = {}
    for j, (b, k) in enumerate(neigh[s]):
        if slot_tile[b] >= 0:
            tb, rb = slot_tile[b], slot_rot[b]
            req[j] = rev_s(tiles[tb][(k + rb) % 3])
    if not req:
        # unconstrained (only the very first slot): all tiles x rot
        return [(t, r) for t in range(n) if not used[t] for r in range(3)]
    drive = next(iter(req))
    out = []
    for (t, r) in place_by[drive][req[drive]]:
        if used[t]:
            continue
        if all(tiles[t][(j + r) % 3] == req[j] for j in req):
            out.append((t, r))
    return out

def dfs(i):
    global nodes, sols, best_depth
    if i > best_depth:
        best_depth = i
    if i == n:
        sols += 1
        with open(inst.replace(".txt", "") + ".frontier_solutions.txt", "a") as f:
            f.write(" ".join(f"{s}:{slot_tile[s]}:{slot_rot[s]}" for s in range(n)) + "\n")
        print(f"[{time.strftime('%H:%M:%S')}] FULL MATCHING #{sols} at "
              f"nodes={nodes} t={time.time()-t0:.0f}s", flush=True)
        return mode != "first"   # True = keep searching
    s = order[i]
    for (t, r) in candidates(s):
        if use_sym and t == seed_tile and s not in rep_slots:
            continue
        nodes += 1
        if node_limit and nodes > node_limit:
            return False
        slot_tile[s], slot_rot[s], used[t] = t, r, True
        cont = dfs(i + 1)
        slot_tile[s], slot_rot[s], used[t] = -1, -1, False
        if not cont:
            return False
        if (nodes & 0xFFFFFF) == 0:
            print(f"  ...nodes={nodes} depth~{i} best_depth={best_depth} "
                  f"sols={sols} t={time.time()-t0:.0f}s", flush=True)
    return True

keep = dfs(0)
exhausted = (node_limit == 0) or (nodes <= node_limit)
print(f"[{time.strftime('%H:%M:%S')}] DONE mode={mode} sols={sols} nodes={nodes} "
      f"best_depth={best_depth}/{n} exhausted={exhausted and keep} t={time.time()-t0:.0f}s",
      flush=True)
if sols == 0 and exhausted and keep:
    print(">>> EXHAUSTIVE: NO complete edge-matching exists -> GOLD IMPOSSIBLE", flush=True)
