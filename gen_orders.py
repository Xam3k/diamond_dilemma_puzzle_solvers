"""gen_orders.py -- generate alternative STATIC FILL ORDERS for the Diamond Dilemma
DFS solvers (solver2.exe / solver3.exe), as plain text files: N_SLOTS (160) lines,
one slot index per line, no header, no comments (so a C parser can just `while
(fscanf(f, "%d", &s) == 1) order[i++] = s;`).

Read solver2.c's build_fill_order() before touching this file -- order_default.txt
below is a faithful line-by-line port of that exact function, done in Python so we
can inspect/study it (and reuse its scoring machinery for the other three orders)
without recompiling or instrumenting the C code.

solver2.c's own words on its order (see its header comment):
  "STATIC FILL ORDER: greedy BFS-style order precomputed at startup, maximising
   already-ordered neighbours (2-constrained placements first). Tie-break by
   rarest required-pattern potential."

Four orders are produced here:
  order_default.txt    -- faithful port of solver2's own greedy order, from the
                           instance's seed slot (sorted seed_slots[0]).
  order_bottleneck.txt -- same scorer (max earlier-neighbours, tie-break rarity),
                           but seeded in face B3 (empirically the hardest region)
                           and phase-priority-restricted to fill B3, then B4,
                           before falling back to the unrestricted greedy for the
                           rest of the board ("growing outward").
  order_perimeter.txt  -- greedy MINIMUM OPEN BOUNDARY LENGTH order (open
                           boundary = number of edges from the ordered set to the
                           unordered set).
  order_blankdefer.txt -- greedy max-earlier-neighbours order with a
                           "T-faces-first" / compactness tie-break. See the
                           honesty note in its docstring below re: what the
                           "blank pressure" idea in the spec reduced to.

IMPORTANT MATH NOTE -- read this before "fixing" (c) or (d) to look more
different from (a):

  Every slot in this instance has exactly 3 neighbours (N_EDGES=240,
  N_SLOTS=160, and 3*160/2 == 240 -> the slot-adjacency graph is 3-regular).
  On a k-regular graph, adding a slot s to the ordered set changes the open
  boundary length by exactly (k - 2*con(s)), where con(s) = number of s's
  neighbours already ordered. That is a strictly DEcreasing function of con(s)
  alone. So "minimise resulting open-boundary length" (order_perimeter's stated
  primary criterion) and "maximise already-ordered neighbours" (order_default's
  primary criterion) produce the IDENTICAL ranking on this graph -- they can only
  diverge in how ties are broken. The same is true of "minimise adjacent
  unordered slots" (order_blankdefer's literal spec: that's just (3 - con(s))
  again, another decreasing function of con(s)).

  We still implement each spec LITERALLY (compute the real open-boundary delta,
  the real adjacent-unordered count, etc.) rather than silently swapping in a
  different metric -- but this means the actual differentiator between
  order_default / order_perimeter / order_blankdefer is entirely in their
  tie-break rules, not their primary metric. We picked genuinely different,
  documented tie-breaks for each (see the three build_order_* functions) so the
  four output files are not near-duplicates of each other.

Usage:
  python gen_orders.py [instance_file] [geometry_file] [outdir]
  Defaults: instance_gold.txt, geometry.json, this script's own directory.
"""
import json
import os
import sys

REV = lambda p: p[::-1]


def load_instance(path):
    """Same format/logic as sat_solver.py's load_instance(), copied here (not
    imported) deliberately: sat_solver.py unconditionally imports the `pysat`
    package at module scope, which is a third-party dependency this script
    must not require just to parse a text file (spec: stdlib + numpy only)."""
    data = [l.strip() for l in open(path) if l.strip()]
    n_slots, n_edges = map(int, data[0].split())
    adj = []
    for i in range(n_slots):
        v = list(map(int, data[1 + i].split()))
        adj.append([(v[0], v[1]), (v[2], v[3]), (v[4], v[5])])
    tiles = [data[1 + n_slots + i].split() for i in range(n_slots)]
    n_seed = int(data[1 + 2 * n_slots])
    seed_slots = list(map(int, data[2 + 2 * n_slots].split()))
    assert len(seed_slots) == n_seed
    seed_tile = int(data[3 + 2 * n_slots])
    return n_slots, adj, tiles, seed_slots, seed_tile


# ============================================================
# Shared graph / pattern-table helpers
# ============================================================
def build_neighbors(n, adj):
    """neighbors[s] = [nb0, nb1, nb2], the 3 neighbour slots of s (edge order
    matches adj[s][j] = (nb, nb_edge))."""
    return [[adj[s][j][0] for j in range(3)] for s in range(n)]


def build_dense_tables(n, tiles):
    """Faithful-in-spirit port of solver2.c's build_dense_ids() + build_spd_lists().

    solver2.c assigns a dense id to every distinct raw tile-edge pattern, THEN
    (in a loop whose bound re-reads the growing n_dense) also assigns dense ids
    to the REVERSE of every such pattern not already present. Because reversal
    is an involution, that closure step is order-independent: the final SET of
    dense patterns is just {p : p is some tile's edge pattern} union {reverse(p)
    for p in that set}. We build that set directly instead of replicating the
    C loop's exact iteration order (order doesn't matter for anything we use --
    the rarity metric below is a MIN over all dense ids, which is
    permutation-invariant).

    Returns:
      tile_dpat[t][e] -- dense id of tile t's raw edge pattern e
      min_per_edge[j] -- min over ALL dense ids d of spd_count[d][j], i.e. the
                         worst-case (smallest) candidate-list length solver2
                         could see for slot-edge position j, over every possible
                         required pattern. This is solver2's rarity proxy,
                         precomputed once since it doesn't depend on the
                         in-progress fill order (see rarity_of()).
      n_dense
    """
    seen = set()
    raw_patterns = []
    for t in range(n):
        for e in range(3):
            p = tiles[t][e]
            if p not in seen:
                seen.add(p)
                raw_patterns.append(p)

    closure = set(raw_patterns)
    for p in raw_patterns:
        closure.add(REV(p))

    dense_ids = {p: i for i, p in enumerate(sorted(closure))}
    n_dense = len(dense_ids)

    tile_dpat = [[dense_ids[tiles[t][e]] for e in range(3)] for t in range(n)]

    spd_count = [[0, 0, 0] for _ in range(n_dense)]
    for t in range(n):
        for r in range(3):
            for j in range(3):
                d = tile_dpat[t][(j + r) % 3]
                spd_count[d][j] += 1

    min_per_edge = [min(spd_count[d][j] for d in range(n_dense)) for j in range(3)]

    return tile_dpat, min_per_edge, n_dense


def con_of(s, neighbors, ordered):
    """Number of s's 3 neighbours that are already in the ordered set."""
    return sum(1 for nb in neighbors[s] if ordered[nb])


def constrained_js(s, neighbors, ordered):
    """Slot-edge indices (0..2) of s whose neighbour is already ordered."""
    return [j for j in range(3) if ordered[neighbors[s][j]]]


def rarity_of(cj, min_per_edge):
    """solver2's rarity proxy: sum, over currently-constrained edges, of the
    worst-case (min) candidate-list length for that edge position. Lower =
    solver2 judged this slot's real candidate list is likely to be *shorter*
    once placed, so it's preferred (fill the tightest spots first)."""
    return sum(min_per_edge[j] for j in cj)


def histogram(con_hist):
    h = {0: 0, 1: 0, 2: 0, 3: 0}
    for c in con_hist:
        h[c] = h.get(c, 0) + 1
    return h


# ============================================================
# (a) order_default -- faithful port of solver2.c build_fill_order()
# ============================================================
def build_order_default(n, neighbors, seed, min_per_edge):
    ordered = [False] * n
    order = [seed]
    ordered[seed] = True
    con_hist = [0]

    while len(order) < n:
        cands = [s for s in range(n) if not ordered[s] and con_of(s, neighbors, ordered) > 0]
        if not cands:
            best_s = next(s for s in range(n) if not ordered[s])
            best_con = 0
        else:
            def key(s):
                con = con_of(s, neighbors, ordered)
                rarity = rarity_of(constrained_js(s, neighbors, ordered), min_per_edge)
                return (-con, rarity, s)
            best_s = min(cands, key=key)
            best_con = con_of(best_s, neighbors, ordered)
        ordered[best_s] = True
        order.append(best_s)
        con_hist.append(best_con)
    return order, con_hist


# ============================================================
# (b) order_bottleneck -- same scorer, seeded in B3, phase-priority B3 -> B4 -> rest
# ============================================================
def build_order_bottleneck(n, neighbors, face_of, min_per_edge):
    b3 = [s for s in range(n) if face_of[s] == 'B3']

    def in_b3_deg(s):
        return sum(1 for nb in neighbors[s] if face_of[nb] == 'B3')

    # Seed = the B3 slot with the most B3-internal neighbours (most "interior"
    # to the bottleneck region), tie-break lowest index.
    seed = min(b3, key=lambda s: (-in_b3_deg(s), s))

    ordered = [False] * n
    order = [seed]
    ordered[seed] = True
    con_hist = [0]

    # Phase priority: fill reachable B3 slots first, then reachable B4 slots,
    # then fall back to the unrestricted board. A slot that never becomes
    # reachable while its phase has priority (e.g. only bordering a face that
    # hasn't been touched yet) simply falls through to the final phase --
    # this is a soft priority, not a hard partition.
    phases = [{'B3'}, {'B4'}, None]

    while len(order) < n:
        chosen = None
        for faces in phases:
            pool = [s for s in range(n)
                    if not ordered[s]
                    and (faces is None or face_of[s] in faces)
                    and con_of(s, neighbors, ordered) > 0]
            if pool:
                def key(s):
                    con = con_of(s, neighbors, ordered)
                    rarity = rarity_of(constrained_js(s, neighbors, ordered), min_per_edge)
                    return (-con, rarity, s)
                chosen = min(pool, key=key)
                break
        if chosen is None:
            chosen = next(s for s in range(n) if not ordered[s])
        best_con = con_of(chosen, neighbors, ordered)
        ordered[chosen] = True
        order.append(chosen)
        con_hist.append(best_con)
    return order, con_hist, seed


# ============================================================
# (c) order_perimeter -- minimise resulting open-boundary length
# ============================================================
def build_order_perimeter(n, neighbors, seed, min_per_edge):
    """Primary criterion (literal spec): minimise the resulting open-boundary
    length after adding s. As explained in the module docstring, on this
    3-regular graph that is mathematically the SAME ranking as "maximise
    con(s)" -- so this reduces to order_default's primary criterion. The real
    differentiator is the tie-break, which we make a genuine 1-hop LOOKAHEAD
    (distinct from order_default's tile-pattern-rarity tie-break):

      lookahead(s) = sum, over s's still-UNORDERED neighbours nb, of con(nb)
                     (nb's OWN count of already-ordered neighbours, before s
                     is added).

    Maximising lookahead prefers slots whose unordered neighbours are already
    close to fully surrounded -- i.e. adding s tends to finish off small
    pockets rather than nibbling many barely-touched neighbours, which is the
    concrete way to keep the open frontier *compact* (short) a step or two
    ahead, not just at this single step (where every candidate with equal con
    already produces an identical immediate boundary length).
    """
    ordered = [False] * n
    order = [seed]
    ordered[seed] = True
    con_hist = [0]

    while len(order) < n:
        cands = [s for s in range(n) if not ordered[s] and con_of(s, neighbors, ordered) > 0]
        if not cands:
            best_s = next(s for s in range(n) if not ordered[s])
            best_con = 0
        else:
            def key(s):
                con = con_of(s, neighbors, ordered)
                lookahead = sum(con_of(nb, neighbors, ordered)
                                 for nb in neighbors[s] if not ordered[nb])
                rarity = rarity_of(constrained_js(s, neighbors, ordered), min_per_edge)
                return (-con, -lookahead, rarity, s)
            best_s = min(cands, key=key)
            best_con = con_of(best_s, neighbors, ordered)
        ordered[best_s] = True
        order.append(best_s)
        con_hist.append(best_con)
    return order, con_hist


# ============================================================
# (d) order_blankdefer
# ============================================================
def build_order_blankdefer(n, neighbors, seed, face_of):
    """The spec's original idea (defer slots adjacent to many blank-capable
    positions, scored via a "blank pressure" count) doesn't reduce to a clean,
    cheap proxy from the bit data alone (blank-ness is a property of PATTERNS,
    not of slots, and which pattern lands where is exactly what's undecided
    during order construction) -- the spec acknowledges this and asks for the
    simplified fallback instead:

      "implement (d) as greedy max-earlier-neighbours but tie-broken by
       MINIMIZING the number of adjacent unordered slots (compactness)."

    We implement that literally. As explained in the module docstring, on this
    3-regular graph "minimise adjacent unordered slots" == (3 - con(s)), a
    strictly decreasing function of con(s) -- i.e. a NO-OP tie-break, since we
    already sort by max con(s) first. We keep it anyway for fidelity to the
    spec text (and because it costs nothing), but add the spec's OTHER stated
    preference ("prefer slots in faces T0..T4 first") as the real, distinct
    tie-break: among slots tied on con(s), prefer top-hemisphere (T-face)
    slots over bottom-hemisphere (B-face) slots, then lowest index.
    """
    ordered = [False] * n
    order = [seed]
    ordered[seed] = True
    con_hist = [0]

    def face_rank(s):
        return 0 if face_of[s].startswith('T') else 1

    while len(order) < n:
        cands = [s for s in range(n) if not ordered[s] and con_of(s, neighbors, ordered) > 0]
        if not cands:
            best_s = next(s for s in range(n) if not ordered[s])
        else:
            def key(s):
                con = con_of(s, neighbors, ordered)
                unordered_adj = 3 - con  # literal spec metric; see docstring -- a no-op given `con` above
                return (-con, unordered_adj, face_rank(s), s)
            best_s = min(cands, key=key)
        best_con = con_of(best_s, neighbors, ordered)
        ordered[best_s] = True
        order.append(best_s)
        con_hist.append(best_con)
    return order, con_hist


# ============================================================
# Main
# ============================================================
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    instance_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "instance_gold.txt")
    geometry_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "geometry.json")
    outdir = sys.argv[3] if len(sys.argv) > 3 else here

    n, adj, tiles, seed_slots, seed_tile = load_instance(instance_path)
    neighbors = build_neighbors(n, adj)
    _tile_dpat, min_per_edge, n_dense = build_dense_tables(n, tiles)

    with open(geometry_path) as f:
        geom = json.load(f)
    face_of = [None] * n
    for slot in geom["slots"]:
        face_of[slot["idx"]] = slot["face"]
    missing = [i for i, f in enumerate(face_of) if f is None]
    if missing:
        raise SystemExit(f"geometry.json missing 'face' for slot idx(s): {missing[:10]}...")

    default_seed = sorted(seed_slots)[0]

    print(f"instance: {instance_path}")
    print(f"n_slots={n}  n_dense_patterns={n_dense}  "
          f"min_per_edge={min_per_edge}  (solver2 rarity proxy inputs)")
    print(f"instance seed_tile={seed_tile}  default seed slot (sorted seed_slots[0])={default_seed}")
    print()

    def emit(name, order, con_hist, note):
        assert len(order) == n, f"{name}: order length {len(order)} != {n}"
        assert sorted(order) == list(range(n)), f"{name}: order is not a permutation of 0..{n-1}"
        path = os.path.join(outdir, name)
        with open(path, "w") as f:
            for s in order:
                f.write(f"{s}\n")
        h = histogram(con_hist)
        print(f"{name}")
        print(f"  {note}")
        print(f"  constraint histogram (# slots by earlier-neighbour count at "
              f"placement time): 0-con={h[0]} 1-con={h[1]} 2-con={h[2]} 3-con={h[3]}  "
              f"(n={len(order)})")
        print(f"  wrote {path}")
        print()

    order_a, hist_a = build_order_default(n, neighbors, default_seed, min_per_edge)
    emit("order_default.txt", order_a, hist_a,
         f"greedy max-earlier-neighbours from seed slot {default_seed}; "
         "tie-break = min solver2 rarity proxy. Faithful port of solver2.c "
         "build_fill_order().")

    order_b, hist_b, seed_b = build_order_bottleneck(n, neighbors, face_of, min_per_edge)
    emit("order_bottleneck.txt", order_b, hist_b,
         f"same scorer as order_default, seeded at slot {seed_b} (face B3, most "
         "B3-internal neighbours); phase-priority B3 -> B4 -> rest of board "
         "('growing outward').")

    order_c, hist_c = build_order_perimeter(n, neighbors, default_seed, min_per_edge)
    emit("order_perimeter.txt", order_c, hist_c,
         "minimise resulting open-boundary length (== maximise earlier-neighbours "
         "on this 3-regular graph -- see module docstring); tie-break = maximise "
         "1-hop lookahead exposure of unordered neighbours, then min rarity, then index.")

    order_d, hist_d = build_order_blankdefer(n, neighbors, default_seed, face_of)
    emit("order_blankdefer.txt", order_d, hist_d,
         "greedy max-earlier-neighbours; tie-break = min adjacent-unordered-slots "
         "(a no-op given the primary metric here, kept for spec fidelity), then "
         "prefer T-faces (T0-T4) over B-faces (B0-B4), then index. See docstring "
         "for the honesty note re: the original 'blank pressure' idea.")

    # Sanity check for the bottleneck phasing: how much of the early order is
    # actually B3/B4, given the "soft priority" (not hard partition) design.
    faces_b = [face_of[s] for s in order_b]
    b3_in_first16 = sum(1 for f in faces_b[:16] if f == 'B3')
    b4_in_first32 = sum(1 for f in faces_b[16:32] if f == 'B4')
    print(f"order_bottleneck sanity: {b3_in_first16}/16 of positions 0-15 are face B3; "
          f"{b4_in_first32}/16 of positions 16-31 are face B4 "
          "(expect both close to 16/16 if B3 and B4 are each internally connected).")


if __name__ == "__main__":
    main()
