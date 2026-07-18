"""Solver-free diagnosis: measure support-clause sizes my encoding produces,
and how the all-zero (palindromic) pattern participates. Fast, deterministic."""
import sys
from collections import defaultdict, Counter
from sat_solver import load_instance

inst = sys.argv[1]
n, adj, tiles, seed_slots, seed_tile = load_instance(inst)
rev = lambda p: p[::-1]

# placements putting a given pattern on slot-edge j
by_edge_pat = [defaultdict(list) for _ in range(3)]
for t in range(n):
    for r in range(3):
        for j in range(3):
            by_edge_pat[j][tiles[t][(j + r) % 3]].append((t, r))

ZERO = "0" * 11
zero_edges = sum(1 for t in range(n) for e in range(3) if tiles[t][e] == ZERO)
print(f"instance {inst}: {n} slots, zero-edges={zero_edges}")

# clause-size distribution for support clauses
sizes = Counter()
big = 0
seen = set()
for s in range(n):
    for j in range(3):
        b, k = adj[s][j]
        key = (min((s, j), (b, k)), max((s, j), (b, k)))
        if key in seen:
            continue
        seen.add(key)
        for (A, eA, B, eB) in ((s, j, b, k), (b, k, s, j)):
            for t in range(n):
                for r in range(3):
                    p = tiles[t][(eA + r) % 3]
                    support = [1 for (t2, r2) in by_edge_pat[eB][rev(p)] if t2 != t]
                    sz = 1 + len(support)
                    sizes[sz] += 1
                    if sz > big:
                        big = sz

total = sum(sizes.values())
print(f"support clauses: {total}, max clause size: {big}")
# show the tail of the size distribution
for sz in sorted(sizes)[-12:]:
    print(f"  size {sz}: {sizes[sz]} clauses")
# how many placements carry the all-zero pattern on some edge -> drives clause width
zcount = len(by_edge_pat[0][ZERO])
print(f"placements with zero on edge0: {zcount} (x3 edges ~ width of a blank support clause)")
