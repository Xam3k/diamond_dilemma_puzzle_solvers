"""Validate loop_trace.count_loops on a constructed loop-consistent instance.

Build a valid instance directly: put 2 crossings on every board edge (random
positions), so every slot has 6 endpoints (even) -> derivable arcs, all edges
matched by construction. The gold graph is then a union of cycles. Cross-check the
tracer's cycle count against an independent union-find over the same graph.
"""
import json, random, collections
from derive_arcs import derive
from loop_trace import count_loops

rng = random.Random(12345)
g = json.load(open("geometry.json"))
n = len(g["slots"])
edges = g["edges"]
# adjacency in load_instance form: adj[s] = [(nbr,edge)]*3
adj = [[None, None, None] for _ in range(n)]
for e in edges:
    adj[e["slotA"]][e["edgeA"]] = (e["slotB"], e["edgeB"])
    adj[e["slotB"]][e["edgeB"]] = (e["slotA"], e["edgeA"])

# assign 2 crossing positions per board edge; fill both slots' bit strings
bits = [["0" * 11 for _ in range(3)] for _ in range(n)]
def setpos(s, j, positions):
    arr = list(bits[s][j])
    for p in positions:
        arr[p] = "1"
    bits[s][j] = "".join(arr)

for e in edges:
    sA, eA, sB, eB = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
    pos = rng.sample(range(11), 2)
    setpos(sA, eA, pos)
    setpos(sB, eB, [10 - p for p in pos])   # reversed across the boundary

tiles = ["".join(bits[s]) and bits[s] for s in range(n)]  # tiles[s] = [3 strings]
arcs, amb = derive([bits[s] for s in range(n)])
none_cnt = sum(1 for a in arcs if a is None)
print(f"constructed instance: {n} slots, ambiguous={len(amb)}, none-arcs={none_cnt}")
assert none_cnt == 0, "every slot should have even endpoints by construction"

placement = [(s, 0) for s in range(n)]   # identity placement
loops, ok, nn = count_loops(placement, n, adj, arcs, [bits[s] for s in range(n)])
print(f"tracer: nodes={nn} all_degree2={ok} loops={loops}")

# independent union-find on the same graph
parent = {}
def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
gph = collections.defaultdict(list)
nodes = set()
for s in range(n):
    for (a, b) in arcs[s]:
        ea, pa = a; eb, pb = b
        na = (s, ea, pa); nb = (s, eb, pb)   # rot 0
        gph[na].append(nb); gph[nb].append(na)
        nodes.add(na); nodes.add(nb)
for s in range(n):
    for j in range(3):
        b, k = adj[s][j]
        for p in range(11):
            nd = (s, j, p)
            if nd in nodes:
                gph[nd].append((b, k, 10 - p))
for nd in nodes:
    for m in gph[nd]:
        parent.setdefault(nd, nd); parent.setdefault(m, m); parent[find(nd)] = find(m)
comps = len({find(x) for x in nodes})
deg_ok = all(len(gph[nd]) == 2 for nd in nodes)
print(f"union-find: nodes={len(nodes)} components={comps} all_degree2={deg_ok}")
print("VALIDATED: tracer matches union-find" if (comps == loops and deg_ok and ok)
      else "*** MISMATCH ***")
