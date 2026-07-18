"""Replay the planted solution through a faithful Python reimplementation of the
solver's candidate logic. At each step, pick the MRV slot exactly like solver.c
(min candidate count among frontier, tie -> lowest slot index) and check that the
planted (tile, rot) for that slot is among the candidates.
Usage: python replay_planted.py <instance.txt> <planted.txt>
"""
import sys
from collections import defaultdict

inst, planted = sys.argv[1], sys.argv[2]
data = [l.strip() for l in open(inst) if l.strip()]
n_slots, n_edges = map(int, data[0].split())
adj = []
for i in range(n_slots):
    v = list(map(int, data[1 + i].split()))
    adj.append([(v[0], v[1]), (v[2], v[3]), (v[4], v[5])])
tiles = [data[1 + n_slots + i].split() for i in range(n_slots)]
seed_tile = int(data[-1])

assign = {}
for tok in open(planted).read().split():
    s, t, r = map(int, tok.split(":"))
    assign[s] = (t, r)

rev = lambda p: p[::-1]
pat_list = defaultdict(list)  # pattern -> [(tile, edge)]
for t in range(n_slots):
    for e in range(3):
        pat_list[tiles[t][e]].append((t, e))

slot_tile = [-1] * n_slots
slot_rot = [-1] * n_slots
used = [False] * n_slots

def get_candidates(s):
    req, has = [None] * 3, [False] * 3
    for j in range(3):
        nb, kb = adj[s][j]
        if slot_tile[nb] >= 0:
            nb_pat = tiles[slot_tile[nb]][(kb + slot_rot[nb]) % 3]
            req[j] = rev(nb_pat)
            has[j] = True
    drive = next((j for j in range(3) if has[j]), -1)
    assert drive >= 0
    out = []
    for (t, e) in pat_list.get(req[drive], []):
        if used[t]:
            continue
        r = (e - drive) % 3
        if all(not has[j] or tiles[t][(j + r) % 3] == req[j] for j in range(3)):
            out.append((t, r))
    return sorted(out)

def place(s, t, r):
    slot_tile[s], slot_rot[s], used[t] = t, r, True

# seed: planted placement of seed tile
seed_slot = next(s for s, (t, r) in assign.items() if t == seed_tile)
place(seed_slot, *assign[seed_slot])
print(f"seed: slot {seed_slot} tile {assign[seed_slot][0]} rot {assign[seed_slot][1]}")

stats = []
for step in range(1, n_slots):
    # frontier: empty slots with >=1 placed neighbor; MRV with lowest-index tie-break
    best_s, best_c = -1, None
    for s in range(n_slots):
        if slot_tile[s] >= 0:
            continue
        if not any(slot_tile[adj[s][j][0]] >= 0 for j in range(3)):
            continue
        c = get_candidates(s)
        if best_c is None or len(c) < len(best_c):
            best_s, best_c = s, c
            if len(c) == 0:
                break
    pt, pr = assign[best_s]
    if (pt, pr) not in best_c:
        print(f"STEP {step}: FAIL at slot {best_s}: planted ({pt},{pr}) not in "
              f"candidates {best_c[:10]}{'...' if len(best_c) > 10 else ''}")
        sys.exit(1)
    place(best_s, pt, pr)
    rank = best_c.index((pt, pr))
    stats.append((len(best_c), rank))
    if step % 40 == 0 or step == n_slots - 1:
        print(f"step {step}: slot {best_s} <- planted ({pt},{pr}); "
              f"cands={len(best_c)}, planted_rank={rank}")

n_branch = sum(1 for c, r in stats if c > 1)
n_disc = sum(1 for c, r in stats if r > 0)
total_disc = sum(r for c, r in stats)
print(f"levels with >1 candidate: {n_branch}; levels where planted not first "
      f"(discrepancies): {n_disc}; total discrepancy weight: {total_disc}")
print("REPLAY COMPLETE: planted solution is reachable by the solver's candidate logic.")
