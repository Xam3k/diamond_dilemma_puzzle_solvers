"""Simulated-annealing / min-conflicts local search for a COMPLETE edge-matching.

State: a full placement -- every slot holds a distinct tile in some rotation.
Cost:  number of the 240 board edges whose two sides do NOT match (pattern vs reverse).
Goal:  drive cost to 0 (a complete matching). Local search sidesteps the blank-edge
branching that drowns systematic solvers, and is the standard tool for FINDING a
solution that is believed to exist.

Moves: rotate a random slot, or swap the tiles of two random slots (keeping/ rerolling
rotations). Metropolis acceptance with geometric cooling + periodic reheat/restart.
Incremental delta evaluation over affected edges only.

Usage: python sa_solver.py <instance.txt> [seconds] [seed]
Writes any 0-cost solution to <instance>.sa_solution.txt and best state to *.sa_best.txt.
"""
import sys, time, random
from sat_solver import load_instance

inst = sys.argv[1]
budget = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
n, adj, tiles, seed_slots, seed_tile = load_instance(inst)
rng = random.Random(seed)
rev = lambda p: p[::-1]

# precompute integer pattern ids and a reverse-match table for speed
pats = sorted({tiles[t][e] for t in range(n) for e in range(3)})
pid = {p: i for i, p in enumerate(pats)}
P = len(pats)
revid = [pid.get(rev(p), -1) for p in pats]
# tilepat[t][e] = pattern id of tile t edge e
tilepat = [[pid[tiles[t][e]] for e in range(3)] for t in range(n)]

# board edges as (slotA, edgeA, slotB, edgeB), each once
edges = []
seen = set()
edge_of_slot = [[] for _ in range(n)]   # edge indices touching slot s
for s in range(n):
    for j in range(3):
        b, k = adj[s][j]
        key = (min((s, j), (b, k)), max((s, j), (b, k)))
        if key in seen:
            continue
        seen.add(key)
        ei = len(edges)
        edges.append((s, j, b, k))
        edge_of_slot[s].append(ei)
        edge_of_slot[b].append(ei)
E = len(edges)

tile_at = list(range(n))           # slot -> tile (start identity permutation)
rng.shuffle(tile_at)
rot_at = [rng.randrange(3) for _ in range(n)]

def edge_bad(ei):
    s, j, b, k = edges[ei]
    pa = tilepat[tile_at[s]][(j + rot_at[s]) % 3]
    pb = tilepat[tile_at[b]][(k + rot_at[b]) % 3]
    return 0 if revid[pa] == pb else 1

cost = sum(edge_bad(ei) for ei in range(E))

def slot_cost(slots):
    eis = set()
    for s in slots:
        eis.update(edge_of_slot[s])
    return sum(edge_bad(ei) for ei in eis), eis

best = cost
t0 = time.time()
iters = 0
T = 3.0
reheats = 0
last_improve = 0

def save(path):
    with open(path, "w") as f:
        f.write(" ".join(f"{s}:{tile_at[s]}:{rot_at[s]}" for s in range(n)) + "\n")

print(f"[{time.strftime('%H:%M:%S')}] start cost={cost}/{E} edges, {n} tiles, "
      f"P={P} patterns", flush=True)

while cost > 0 and time.time() - t0 < budget:
    iters += 1
    if rng.random() < 0.5:
        # rotate move
        s = rng.randrange(n)
        old = rot_at[s]
        new = rng.choice([r for r in range(3) if r != old])
        before, eis = slot_cost([s])
        rot_at[s] = new
        after = sum(edge_bad(ei) for ei in eis)
        delta = after - before
        if delta <= 0 or rng.random() < pow(2.718281828, -delta / T):
            cost += delta
        else:
            rot_at[s] = old
    else:
        # swap move
        s1 = rng.randrange(n)
        s2 = rng.randrange(n)
        if s1 == s2:
            continue
        before, eis = slot_cost([s1, s2])
        tile_at[s1], tile_at[s2] = tile_at[s2], tile_at[s1]
        r1o, r2o = rot_at[s1], rot_at[s2]
        if rng.random() < 0.5:
            rot_at[s1] = rng.randrange(3); rot_at[s2] = rng.randrange(3)
        after = sum(edge_bad(ei) for ei in eis)
        delta = after - before
        if delta <= 0 or rng.random() < pow(2.718281828, -delta / T):
            cost += delta
        else:
            tile_at[s1], tile_at[s2] = tile_at[s2], tile_at[s1]
            rot_at[s1], rot_at[s2] = r1o, r2o

    if cost < best:
        best = cost
        last_improve = iters
        save(inst.replace(".txt", "") + ".sa_best.txt")
        if best <= 8:
            print(f"[{time.strftime('%H:%M:%S')}] new best cost={best} "
                  f"iters={iters} t={time.time()-t0:.0f}s", flush=True)
    # cooling + reheat when stuck
    T *= 0.99999
    if T < 0.05:
        T = 0.05
    if iters - last_improve > 400000:
        T = 2.0 + rng.random()
        last_improve = iters
        reheats += 1
    if (iters % 2000000) == 0:
        print(f"  iters={iters} cost={cost} best={best} T={T:.3f} reheats={reheats} "
              f"t={time.time()-t0:.0f}s", flush=True)

el = time.time() - t0
if cost == 0:
    save(inst.replace(".txt", "") + ".sa_solution.txt")
    print(f"[{time.strftime('%H:%M:%S')}] *** COMPLETE MATCHING FOUND *** "
          f"iters={iters} t={el:.0f}s -> {inst.replace('.txt','')}.sa_solution.txt", flush=True)
else:
    print(f"[{time.strftime('%H:%M:%S')}] stopped: best cost={best} mismatched edges "
          f"(of {E}); cost now={cost}; iters={iters} reheats={reheats} t={el:.0f}s", flush=True)
