"""Orchestrator's independent verification of geometry.json (reads JSON only)."""
import json
from collections import Counter

g = json.load(open("geometry.json"))
tiles = json.load(open("tiles.json"))

slots, edges, sym = g["slots"], g["edges"], g["symmetry"]
ok = True
def check(name, cond):
    global ok
    print(("PASS" if cond else "FAIL"), name)
    ok = ok and cond

def key(p):  # hashable point id
    return json.dumps(p)

check("160 slots", len(slots) == 160)
check("240 edges", len(edges) == 240)
check("160 tiles, all 3x11", len(tiles) == 160 and all(
    len(t) == 3 and all(len(e) == 11 and set(e) <= {"0", "1"} for e in t) for t in tiles))

# Each slot: 3 directed edges forming a closed triangle walk over its corners
good = all(
    len(s["directed_edges"]) == 3
    and all(len(e) == 2 for e in s["directed_edges"])
    and all(key(s["directed_edges"][k][1]) == key(s["directed_edges"][(k + 1) % 3][0])
            for k in range(3))
    for s in slots)
check("slot edges form closed directed triangles", good)

# Adjacency: A's directed edge (u,v) must be B's (v,u); every (slot,edgeidx) used once
seen = Counter()
opp = True
for e in edges:
    sa, ea, sb, eb = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
    da = slots[sa]["directed_edges"][ea]
    db = slots[sb]["directed_edges"][eb]
    if not (key(da[0]) == key(db[1]) and key(da[1]) == key(db[0])):
        opp = False
    seen[(sa, ea)] += 1
    seen[(sb, eb)] += 1
check("all 240 adjacencies are opposite directed pairs", opp)
check("each of 480 (slot,edge) sides used exactly once",
      len(seen) == 480 and set(seen.values()) == {1})

flags = Counter(e["within_face"] for e in edges)
check("180 within-face / 60 cross-face", flags.get(True, 0) == 180 and flags.get(False, 0) == 60)

# Cross-face edges must connect slots on different faces; within-face on the same face
ff_ok = all((slots[e["slotA"]]["face"] == slots[e["slotB"]]["face"]) == e["within_face"]
            for e in edges)
check("within/cross flags consistent with slot faces", ff_ok)

# Symmetry: 10 perms; each maps (slot,edgeidx) consistently with adjacency
check("10 symmetry elements", len(sym) == 10)
adj = {}
for e in edges:
    adj[(e["slotA"], e["edgeA"])] = (e["slotB"], e["edgeB"])
    adj[(e["slotB"], e["edgeB"])] = (e["slotA"], e["edgeA"])
sym_ok, ident = True, 0
for p in sym:
    sm, em = p["slot_perm"], p["edge_perm"]
    if sm == list(range(160)):
        ident += 1
    if sorted(sm) != list(range(160)):
        sym_ok = False
        break
    for (sa, ea), (sb, eb) in adj.items():
        if adj[(sm[sa], em[sa][ea])] != (sm[sb], em[sb][eb]):
            sym_ok = False
            break
    if not sym_ok:
        break
check("symmetry perms preserve adjacency (incl. edge indices)", sym_ok)
check("exactly one identity element", ident == 1)

# Orbit structure: 16 orbits of size 10 under the group
orbit = list(range(160))
def find(x):
    while orbit[x] != x:
        orbit[x] = orbit[orbit[x]]
        x = orbit[x]
    return x
for p in sym:
    for s in range(160):
        a, b = find(s), find(p["slot_perm"][s])
        if a != b:
            orbit[a] = b
sizes = Counter(Counter(find(s) for s in range(160)).values())
check("16 slot orbits of size 10", sizes == Counter({10: 16}))

print("\nOVERALL:", "PASS" if ok else "FAIL")
