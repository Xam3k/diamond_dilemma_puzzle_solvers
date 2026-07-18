"""Verify a (partial) assignment: every edge whose BOTH slots are placed must match.
Usage: python verify_partial.py <instance.txt> <partial.txt>
"""
import sys

inst, part = sys.argv[1], sys.argv[2]
lines = [l.strip() for l in open(inst) if l.strip()]
n_slots, n_edges = map(int, lines[0].split())
adj = []
for i in range(n_slots):
    v = list(map(int, lines[1 + i].split()))
    adj.append([(v[0], v[1]), (v[2], v[3]), (v[4], v[5])])
tiles = []
for i in range(n_slots):
    tiles.append(lines[1 + n_slots + i].split())

assign = {}  # slot -> (tile, rot)
for tok in open(part).read().split():
    s, t, r = map(int, tok.split(":"))
    assign[s] = (t, r)

# duplicate tile check
used = {}
dup = False
for s, (t, r) in assign.items():
    if t in used:
        print(f"DUPLICATE tile {t} in slots {used[t]} and {s}")
        dup = True
    used[t] = s

bad = 0
checked = 0
for s, (t, r) in assign.items():
    for j in range(3):
        ns, nk = adj[s][j]
        if ns not in assign or ns < s:
            continue
        nt, nr = assign[ns]
        pa = tiles[t][(j + r) % 3]
        pb = tiles[nt][(nk + nr) % 3]
        checked += 1
        if pa != pb[::-1]:
            bad += 1
            if bad <= 5:
                print(f"MISMATCH slot {s} edge {j} (tile {t} rot {r}, pat {pa}) "
                      f"vs slot {ns} edge {nk} (tile {nt} rot {nr}, pat {pb})")
print(f"placed={len(assign)} edges_checked={checked} mismatches={bad} duplicates={dup}")
print("PARTIAL:", "VALID" if bad == 0 and not dup else "INVALID")
