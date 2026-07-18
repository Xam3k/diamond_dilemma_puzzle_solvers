"""Generate a planted SINGLE-LOOP instance: a Hamiltonian cycle on the slot-
adjacency graph, realized as the gold loop. Each slot is visited once -> exactly 2
endpoints on 2 of its edges -> one unambiguous arc -> the identity placement is a
single loop covering all 160 tiles. Then scramble (permute tiles + random rotations).

Writes instance_loop_<seed>.txt (solver input) and instance_loop_<seed>.planted.txt.
Usage: python gen_loop_synthetic.py <seed>
"""
import json, sys, random
from loop_trace import count_loops
from derive_arcs import derive

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
rng = random.Random(seed)
g = json.load(open("geometry.json"))
n = len(g["slots"])
adj = [[None, None, None] for _ in range(n)]
for e in g["edges"]:
    adj[e["slotA"]][e["edgeA"]] = (e["slotB"], e["edgeB"])
    adj[e["slotB"]][e["edgeB"]] = (e["slotA"], e["edgeA"])
# neighbor slot -> which of my edges leads to it
edge_to = [{adj[s][j][0]: j for j in range(3)} for s in range(n)]
nbrs = [[adj[s][j][0] for j in range(3)] for s in range(n)]

# ---- find a Hamiltonian cycle by the backbite (rotation) heuristic ----
def hamilton():
    nbrset = [set(nbrs[s]) for s in range(n)]
    best = None
    for attempt in range(60):
        path = [rng.randrange(n)]
        inpath = [False] * n
        inpath[path[0]] = True
        pos = {path[0]: 0}
        stuck = 0
        while len(path) < n and stuck < 200000:
            h = path[-1]
            ext = [v for v in nbrs[h] if not inpath[v]]
            if ext:
                v = min(ext, key=lambda x: sum(1 for w in nbrs[x] if not inpath[w]))
                path.append(v); inpath[v] = True; pos[v] = len(path) - 1
                stuck = 0
            else:
                # backbite: pick a neighbor w of head already in path; reverse tail after w
                w = rng.choice(nbrs[h])
                i = pos[w]
                if i >= len(path) - 1:
                    stuck += 1; continue
                path[i + 1:] = path[i + 1:][::-1]
                for idx in range(i + 1, len(path)):
                    pos[path[idx]] = idx
                stuck += 1
        if len(path) == n:
            # close to a cycle: rotate until both ends adjacent
            for _ in range(200000):
                if path[0] in nbrset[path[-1]]:
                    return path
                # backbite at the head to change the endpoint
                h = path[-1]
                cand = [v for v in nbrs[h] if pos[v] < len(path) - 1]
                if not cand:
                    break
                w = rng.choice(cand); i = pos[w]
                path[i + 1:] = path[i + 1:][::-1]
                for idx in range(i + 1, len(path)):
                    pos[path[idx]] = idx
    return None

cycle = hamilton()
if not cycle:
    print("no Hamiltonian cycle found; retry with another seed")
    sys.exit(1)
print(f"Hamiltonian cycle found (len {len(cycle)})")

# realize crossings: for each consecutive (u,v), set a crossing on their shared edge
bits = [["0"] * 11 for _ in range(n)]
bits = [[list("0" * 11) for _ in range(3)] for _ in range(n)]
for i in range(n):
    u = cycle[i]; v = cycle[(i + 1) % n]
    ju = edge_to[u][v]; kv = edge_to[v][u]
    p = rng.randrange(1, 10)
    bits[u][ju][p] = "1"
    bits[v][kv][10 - p] = "1"
tiles_planted = ["".join  # placeholder
                 ] if False else [["".join(bits[s][j]) for j in range(3)] for s in range(n)]

# derive arcs from the planted bits; identity placement must be a single loop
arcs, amb = derive(tiles_planted)
placement = [(s, 0) for s in range(n)]
loops, ok, nn = count_loops(placement, n, adj, arcs, tiles_planted)
print(f"planted identity placement: nodes={nn} degree2={ok} loops={loops} ambiguous={len(amb)}")
if not (ok and loops == 1):
    print("WARNING: planted instance is not a clean single loop under derived arcs.")

# scramble: random permutation of tiles + random rotation
perm = list(range(n)); rng.shuffle(perm)            # perm[newtile] = original slot's tile
# tile id 'newtile' carries the patterns of original slot perm[newtile], rotated by rot
rot_of = [rng.randrange(3) for _ in range(n)]
scram_tiles = []
for newtile in range(n):
    base = tiles_planted[perm[newtile]]
    r = rot_of[newtile]
    scram_tiles.append([base[(j - r) % 3] for j in range(3)])  # rotate patterns
# planted solution: slot s holds tile = index newtile with perm[newtile]==s, rotation r
slot_to_newtile = {perm[nt]: nt for nt in range(n)}
planted_sol = []
for s in range(n):
    nt = slot_to_newtile[s]
    planted_sol.append((s, nt, rot_of[nt]))

# write instance file (same format as gen_instance/gen_synthetic): all slots are seeds
out = f"instance_loop_{seed}.txt"
with open(out, "w") as f:
    f.write(f"{n} {len(g['edges'])}\n")
    for s in range(n):
        f.write(" ".join(f"{adj[s][j][0]} {adj[s][j][1]}" for j in range(3)) + "\n")
    for s in range(n):
        f.write(" ".join(scram_tiles[s]) + "\n")
    f.write(f"{n}\n")
    f.write(" ".join(str(s) for s in range(n)) + "\n")
    f.write("0\n")
with open(f"instance_loop_{seed}.planted.txt", "w") as f:
    f.write(" ".join(f"{s}:{t}:{r}" for s, t, r in planted_sol) + "\n")
print(f"wrote {out} and planted solution")
