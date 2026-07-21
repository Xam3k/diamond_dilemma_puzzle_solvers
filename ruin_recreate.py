"""Ruin-&-recreate matheuristic for the gold matching score.

Start from the best known partial (132/160). Repeatedly:
  1. RUIN: free a neighborhood F = (all empty slots) + BFS ring around a random
     subset of them (radius 1-2), leaving all other placements FIXED.
  2. RECREATE: solve max-placement EXACTLY on F with CP-SAT (boundary constrained
     by fixed patterns), randomized seed for diversification.
  3. Accept (cannot be worse than current within F); save on improvement.
Targeted exact repair around actual obstructions >> generic LNS. Reaching 160 = full
matching found.

Usage: python ruin_recreate.py <start_partial> <wall_seconds> [subsolve_seconds]
Best state continuously saved to rr_best.txt; log to stdout (flushed).
"""
import json, random, sys, time
from loops_lib import count_closed, closed_loop_slots
from collections import defaultdict
from ortools.sat.python import cp_model

import os, json as _json
start_file = sys.argv[1]
wall = float(sys.argv[2]) if len(sys.argv) > 2 else 1800.0
sub_wall = float(sys.argv[3]) if len(sys.argv) > 3 else 45.0
WORKERS = int(os.environ.get("RR_WORKERS", "8"))
BIG_PROB = float(os.environ.get("RR_BIG", "0.0"))   # prob of a large (face-band) ruin
FOCUS = set(x for x in os.environ.get("RR_FOCUS", "").split(",") if x)  # faces for big ruin
GUIDE_F = os.environ.get("RR_GUIDE", "")            # path-relinking guide partial file
guide = {}
if GUIDE_F:
    for _tok in open(GUIDE_F).read().split():
        _s, _t, _r = map(int, _tok.split(":"))
        guide[_s] = (_t, _r)
_face_of = None
def _faces():
    global _face_of
    if _face_of is None:
        g = _json.load(open("geometry.json"))
        _face_of = {s["idx"]: s["face"] for s in g["slots"]}
    return _face_of
rng = random.Random(int(os.environ.get("RR_SEED","20260702")))

g = json.load(open("geometry.json"))
tiles = json.load(open("tiles.json"))
rev = lambda p: p[::-1]
n = 160
adj = [[None] * 3 for _ in range(n)]
for e in g["edges"]:
    adj[e["slotA"]][e["edgeA"]] = (e["slotB"], e["edgeB"])
    adj[e["slotB"]][e["edgeB"]] = (e["slotA"], e["edgeA"])

cur = {}   # slot -> (tile, rot)  -- the wandering working solution
for tok in open(start_file).read().split():
    s, t, r = map(int, tok.split(":"))
    cur[s] = (t, r)
best_score = len(cur)
cur_score = best_score
best = dict(cur)                  # best-ever snapshot (what we save)
print(f"start: {best_score}/160 from {start_file}", flush=True)

# Iterated Local Search: the CP-SAT repair always MAXIMIZES placement, so it
# can never worsen the incumbent -- the search does a plateau random walk and
# gets trapped in the all-dead-holes basin. RR_KICK enables perturbation
# escapes: after RR_KICK_STUCK repairs with no NEW BEST, deliberately DEGRADE
# the working solution (free a big region, keep only a random FEASIBLE
# sub-placement so several tiles are evicted), then resume climbing from that
# worse-but-different state. `best` is preserved throughout.
NOLOOP = int(os.environ.get("RR_NOLOOP", "0"))   # reject repairs that close a gold sub-loop
KICK_ON = int(os.environ.get("RR_KICK", "0"))
KICK_STUCK = int(os.environ.get("RR_KICK_STUCK", "40"))
KICK_EVICT = int(os.environ.get("RR_KICK_EVICT", "6"))   # tiles to drop on a kick
MAXF = int(os.environ.get("RR_MAXF", "0"))               # cap freed-region size (0=off)
stuck = 0

def save(path):
    with open(path, "w") as f:
        f.write(" ".join(f"{s}:{best[s][0]}:{best[s][1]}" for s in sorted(best)) + "\n")

ALLHOLES_RING = int(os.environ.get("RR_ALLHOLES", "0"))  # free ALL holes + this-radius ring

def neighborhood():
    empty = [s for s in range(n) if s not in cur]
    # Coordinated all-holes ruin: free every hole plus a ring of `ALLHOLES_RING`
    # around them, and let one big CP-SAT solve rearrange the whole bottleneck
    # jointly (the holes are a coordination problem, not independent). Use with
    # a long subsolve budget.
    if ALLHOLES_RING > 0:
        F = set(empty)
        frontier = set(empty)
        for _ in range(ALLHOLES_RING):
            nxt = set()
            for s in frontier:
                for j in range(3):
                    nxt.add(adj[s][j][0])
            F |= nxt
            frontier = nxt
        return F
    # occasionally free a large region: 1-2 whole faces (16 slots each) + all holes.
    # RR_FOCUS restricts the freed faces to the bottleneck region.
    if BIG_PROB > 0 and rng.random() < BIG_PROB:
        fo = _faces()
        pool = sorted(FOCUS) if FOCUS else sorted(set(fo.values()))
        faces = rng.sample(pool, min(rng.choice([1, 2]), len(pool)))
        F = set(empty) | {s for s in range(n) if fo[s] in faces}
        return F
    # path relinking: sometimes center the ruin where cur disagrees with the guide,
    # so exact repair walks the current solution toward a different-basin partial.
    if guide and rng.random() < 0.5:
        diff = [s for s in range(n) if s in guide and cur.get(s) != guide[s]]
        pool = diff if diff else empty if empty else list(range(n))
        centers = rng.sample(pool, min(rng.choice([6, 10, 14]), len(pool)))
        F = set(centers)
        for s in list(centers):
            for j in range(3):
                F.add(adj[s][j][0])
        return F
    k = rng.choice([6, 8, 10, 14])
    centers = rng.sample(empty, min(k, len(empty))) if empty else [rng.randrange(n)]
    radius = rng.choice([1, 2, 2])
    F = set(centers)          # only the sampled holes + their ring (keep F small)
    frontier = set(centers)
    for _ in range(radius):
        nxt = set()
        for s in frontier:
            for j in range(3):
                nxt.add(adj[s][j][0])
        F |= nxt
        frontier = nxt
    # RR_MAXF caps the freed-region size so every CP-SAT subsolve finishes fast
    # (large regions return UNKNOWN and waste the iteration). Empty slots are
    # kept preferentially; the rest is subsampled.
    if MAXF > 0 and len(F) > MAXF:
        holes = [s for s in F if s not in cur]
        others = [s for s in F if s in cur]
        keep = set(holes[:MAXF])
        if len(keep) < MAXF:
            keep |= set(rng.sample(others, min(MAXF - len(keep), len(others))))
        F = keep
    return F

t0 = time.time()
it = 0
while time.time() - t0 < wall and best_score < 160:
    it += 1
    F = neighborhood()
    fixed = {s: cur[s] for s in cur if s not in F}
    avail = [t for t in range(n) if all(cur.get(s, (None,))[0] != t for s in fixed)]
    avail = [t for t in range(n) if t not in {v[0] for v in fixed.values()}]
    Fl = sorted(F)
    fi = {s: i for i, s in enumerate(Fl)}
    nf, na = len(Fl), len(avail)
    ai = {t: k for k, t in enumerate(avail)}

    pats = sorted({tiles[t][e] for t in range(n) for e in range(3)} |
                  {rev(tiles[t][e]) for t in range(n) for e in range(3)})
    pid = {p: i for i, p in enumerate(pats)}
    P = len(pats)                      # wildcard id = P (unplaced)

    m = cp_model.CpModel()
    place = [m.NewBoolVar("") for _ in range(nf)]
    tv = [m.NewIntVar(0, na - 1, "") for _ in range(nf)]
    rv = [m.NewIntVar(0, 2, "") for _ in range(nf)]
    pe = [[m.NewIntVar(0, P - 1, "") for _ in range(3)] for _ in range(nf)]
    ep = [[m.NewIntVar(0, P, "") for _ in range(3)] for _ in range(nf)]
    v = [m.NewIntVar(0, na + nf, "") for _ in range(nf)]
    for i in range(nf):
        m.Add(v[i] == tv[i]).OnlyEnforceIf(place[i])
        m.Add(v[i] == na + i).OnlyEnforceIf(place[i].Not())
    m.AddAllDifferent(v)
    link = []
    for k, t in enumerate(avail):
        for r in range(3):
            link.append((k, r, pid[tiles[t][(0 + r) % 3]],
                         pid[tiles[t][(1 + r) % 3]], pid[tiles[t][(2 + r) % 3]]))
    for i in range(nf):
        m.AddAllowedAssignments([tv[i], rv[i], pe[i][0], pe[i][1], pe[i][2]], link)
        for j in range(3):
            m.Add(ep[i][j] == pe[i][j]).OnlyEnforceIf(place[i])
            m.Add(ep[i][j] == P).OnlyEnforceIf(place[i].Not())
    # edges
    seen = set()
    for s in Fl:
        for j in range(3):
            b, k = adj[s][j]
            if b in F:
                key = (min((s, j), (b, k)), max((s, j), (b, k)))
                if key in seen:
                    continue
                seen.add(key)
                tbl = [(a, c) for a in range(P + 1) for c in range(P + 1)
                       if a == P or c == P or pats[a] == rev(pats[c])]
                m.AddAllowedAssignments([ep[fi[s]][j], ep[fi[b]][k]], tbl)
            elif b in fixed:
                tb, rb = fixed[b]
                need = pid[rev(tiles[tb][(k + rb) % 3])]
                m.AddAllowedAssignments([ep[fi[s]][j]], [(need,), (P,)])
            # else: outside slot is empty this iteration -> edge unconstrained
    # warm-start hint. In guide mode, bias the freed slots toward the guide partial
    # (path relinking); otherwise toward the incumbent so FEASIBLE >= current.
    for i, s in enumerate(Fl):
        src = None
        if guide and s in guide and guide[s][0] in ai:
            src = guide[s]
        elif s in cur and cur[s][0] in ai:
            src = cur[s]
        if src is not None:
            m.AddHint(place[i], 1)
            m.AddHint(tv[i], ai[src[0]])
            m.AddHint(rv[i], src[1])
        else:
            m.AddHint(place[i], 0)

    m.Maximize(sum(place))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = sub_wall
    sv.parameters.num_search_workers = WORKERS
    sv.parameters.cp_model_probing_level = 0
    sv.parameters.random_seed = rng.randrange(1 << 30)
    # Lazy subtour elimination: solve, and if the repair closes a gold loop,
    # forbid exactly that arrangement of the offending freed slots and re-solve.
    MAXCUT = int(os.environ.get("RR_MAXCUT", "12"))
    cand = None
    cuts = 0
    for _attempt in range(MAXCUT if NOLOOP else 1):
        st = sv.Solve(m)
        if sv.StatusName(st) not in ("OPTIMAL", "FEASIBLE"):
            break
        trial = dict(cur)
        for s_ in Fl:
            trial.pop(s_, None)
        for i, s_ in enumerate(Fl):
            if sv.Value(place[i]):
                trial[s_] = (avail[sv.Value(tv[i])], sv.Value(rv[i]))
        if not NOLOOP or count_closed(trial) == 0:
            cand = trial
            break
        bad = closed_loop_slots(trial) & set(Fl)
        if not bad:
            break                      # loop lies wholly in the fixed region
        idx = [fi[s_] for s_ in sorted(bad)]
        vars_ = []
        tup = []
        for i in idx:
            vars_ += [tv[i], rv[i], place[i]]
            tup += [sv.Value(tv[i]), sv.Value(rv[i]), sv.Value(place[i])]
        m.AddForbiddenAssignments(vars_, [tuple(tup)])
        cuts += 1
    if cand is None:
        print(f"it{it}: F={nf} no loop-free repair after {cuts} cuts (skip)", flush=True)
        stuck += 1
        continue
    got = sum(1 for s_ in Fl if s_ in cand)
    new_score = len(fixed) + got
    if new_score >= cur_score:
        cur.clear(); cur.update(cand)
        cur_score = new_score
        if new_score > best_score:
            best_score = new_score
            best = dict(cur)
            save(os.environ.get("RR_OUT","rr_best.txt"))
            stuck = 0
            print(f"it{it}: IMPROVED -> {best_score}/160 (F={nf}, "
                  f"t={time.time()-t0:.0f}s)", flush=True)
            if best_score == 160:
                print("*** FULL MATCHING FOUND ***", flush=True)
        else:
            stuck += 1
            print(f"it{it}: move cur={cur_score}/160 best={best_score} (F={nf})", flush=True)
    else:
        stuck += 1
        print(f"it{it}: sub-opt {new_score} < cur={cur_score} (F={nf}) — keep", flush=True)

    # ILS perturbation: when stuck, evict several hole-adjacent "wall" tiles so
    # the trapped dead holes can be rearranged, then climb again from the worse
    # state (best is preserved).
    if KICK_ON and stuck >= KICK_STUCK and best_score < 160:
        stuck = 0
        empties = [s for s in range(n) if s not in cur]
        wall_slots = list({adj[e][j][0] for e in empties for j in range(3) if adj[e][j][0] in cur})
        pool = wall_slots if len(wall_slots) >= KICK_EVICT else list(cur.keys())
        victims = rng.sample(pool, min(KICK_EVICT, len(pool)))
        for s in victims:
            cur.pop(s, None)
        cur_score = len(cur)
        print(f"it{it}: KICK evicted {len(victims)} -> cur={cur_score}/160 "
              f"(best={best_score})", flush=True)
save(os.environ.get("RR_OUT","rr_best.txt").replace(".txt","_final.txt"))
print(f"DONE best={best_score}/160 iters={it} t={time.time()-t0:.0f}s", flush=True)
