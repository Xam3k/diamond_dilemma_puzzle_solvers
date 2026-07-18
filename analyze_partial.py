"""Analyze why the best partial stops where it does: locate empty slots, unplaced
tiles, and check the structure of the obstruction. Read-only on a partial file."""
import sys, json
from collections import defaultdict
from sat_solver import load_instance

inst, part = sys.argv[1], sys.argv[2]
n, adj, tiles, seed_slots, seed_tile = load_instance(inst)
rev = lambda p: p[::-1]

assign = {}
for tok in open(part).read().split():
    s, t, r = map(int, tok.split(":"))
    assign[s] = (t, r)
placed = set(assign)
empty = [s for s in range(n) if s not in placed]
used_tiles = {t for t, r in assign.values()}
free_tiles = [t for t in range(n) if t not in used_tiles]
print(f"placed={len(placed)} empty={len(empty)} free_tiles={len(free_tiles)}")

# empty-region connectivity (within the 240-edge adjacency, restricted to empty slots)
adjset = defaultdict(set)
for s in range(n):
    for (b, k) in adj[s]:
        adjset[s].add(b)
seen = set()
comps = []
for s in empty:
    if s in seen:
        continue
    stack, comp = [s], []
    seen.add(s)
    while stack:
        x = stack.pop(); comp.append(x)
        for y in adjset[x]:
            if y in empty and y not in seen:
                seen.add(y); stack.append(y)
    comps.append(sorted(comp))
comps.sort(key=len, reverse=True)
print(f"empty-region components: {[len(c) for c in comps]}")

# how many placed neighbors does each empty slot have? (3 = fully surrounded hole)
deg = {s: sum(1 for b in adjset[s] if b in placed) for s in empty}
from collections import Counter
print(f"empty-slot placed-neighbor counts: {dict(sorted(Counter(deg.values()).items()))}")

# face distribution of empty slots
faceof = {}
g = json.load(open("geometry.json"))
for sl in g["slots"]:
    faceof[sl["idx"]] = sl["face"]
print(f"empty slots by face: {dict(sorted(Counter(faceof[s] for s in empty).items()))}")

# candidate check: for each empty slot, how many (free_tile,rot) satisfy ALL its placed-neighbor edges?
def fits(s):
    cnt = 0
    for t in free_tiles:
        for r in range(3):
            ok = True
            for j, (b, k) in enumerate(adj[s]):
                if b in placed:
                    tb, rb = assign[b]
                    if tiles[t][(j + r) % 3] != rev(tiles[tb][(k + rb) % 3]):
                        ok = False; break
            if ok:
                cnt += 1
    return cnt
fitc = {s: fits(s) for s in empty}
print(f"empty-slot fitting-(tile,rot) counts: {dict(sorted(Counter(fitc.values()).items()))}")
dead = [s for s in empty if fitc[s] == 0]
print(f"DEAD empty slots (no free tile fits placed neighbors): {len(dead)} -> {dead[:20]}")
