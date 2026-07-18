"""SAT/CDCL attack on Diamond Dilemma matching instances.

Encoding:
  vars x[s,t,r] (1-based): tile t with rotation r sits in slot s.
  - exactly-one placement per slot, exactly-one (slot,rot) per tile (seqcounter AMO)
  - support clauses per directed edge side: x[A,t,r] -> OR of compatible x[B,t',r']
    (pattern at A's side must equal reverse of pattern at B's side)
  - symmetry breaking: the instance's seed tile may only sit in the instance's seed
    slots (skip when all 160 slots are seeds, i.e. synthetic instances)

Usage: python sat_solver.py <instance.txt> [max_solutions] [--solver cadical]
Solutions appended to <instance>.sat_solutions.txt, one line each: "slot:tile:rot ..."
Exit prints SAT count or UNSAT. UNSAT on the gold instance = no complete edge
matching exists = the Gold challenge is impossible.
"""
import sys
import time
from collections import defaultdict

from pysat.formula import CNF, IDPool
from pysat.card import CardEnc, EncType
from pysat.solvers import Cadical153


def load_instance(path):
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


def main():
    inst = sys.argv[1]
    max_sols = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    n, adj, tiles, seed_slots, seed_tile = load_instance(inst)
    rev = lambda p: p[::-1]

    t0 = time.time()
    pool = IDPool()
    X = lambda s, t, r: pool.id(("x", s, t, r))
    cnf = CNF()

    # index: (slot_edge_pos j, pattern) -> [(t, r)] placements putting pattern on edge j
    by_edge_pat = [defaultdict(list) for _ in range(3)]
    for t in range(n):
        for r in range(3):
            for j in range(3):
                by_edge_pat[j][tiles[t][(j + r) % 3]].append((t, r))

    # exactly-one per slot
    for s in range(n):
        lits = [X(s, t, r) for t in range(n) for r in range(3)]
        cnf.append(lits)
        cnf.extend(CardEnc.atmost(lits, 1, vpool=pool, encoding=EncType.seqcounter))

    # exactly-one per tile
    for t in range(n):
        lits = [X(s, t, r) for s in range(n) for r in range(3)]
        cnf.append(lits)
        cnf.extend(CardEnc.atmost(lits, 1, vpool=pool, encoding=EncType.seqcounter))

    # support clauses, both directions of every board edge
    seen_edge = set()
    for s in range(n):
        for j in range(3):
            b, k = adj[s][j]
            key = (min((s, j), (b, k)), max((s, j), (b, k)))
            if key in seen_edge:
                continue
            seen_edge.add(key)
            for (A, eA, B, eB) in ((s, j, b, k), (b, k, s, j)):
                for t in range(n):
                    for r in range(3):
                        p = tiles[t][(eA + r) % 3]
                        support = [X(B, t2, r2)
                                   for (t2, r2) in by_edge_pat[eB][rev(p)]
                                   if t2 != t]
                        cnf.append([-X(A, t, r)] + support)

    # symmetry breaking (only if the instance restricts seeds)
    if len(seed_slots) < n:
        allowed = set(seed_slots)
        for s in range(n):
            if s not in allowed:
                for r in range(3):
                    cnf.append([-X(s, seed_tile, r)])

    print(f"CNF built: {pool.top} vars, {len(cnf.clauses)} clauses "
          f"in {time.time()-t0:.1f}s", flush=True)

    out_path = inst.replace(".txt", "") + ".sat_solutions.txt"
    n_sols = 0
    with Cadical153(bootstrap_with=cnf) as solver:
        while n_sols < max_sols:
            t1 = time.time()
            sat = solver.solve()
            dt = time.time() - t1
            if not sat:
                print(f"UNSAT after {dt:.1f}s "
                      f"({'no MORE solutions' if n_sols else 'NO complete matching exists'})",
                      flush=True)
                break
            model = set(l for l in solver.get_model() if l > 0)
            placement = {}
            for s in range(n):
                for t in range(n):
                    for r in range(3):
                        if X(s, t, r) in model:
                            placement[s] = (t, r)
            assert len(placement) == n, f"decoded {len(placement)} placements"
            line = " ".join(f"{s}:{placement[s][0]}:{placement[s][1]}" for s in range(n))
            with open(out_path, "a") as f:
                f.write(line + "\n")
            n_sols += 1
            print(f"SOLUTION {n_sols} found in {dt:.1f}s -> {out_path}", flush=True)
            # block this exact solution (slot-placement combination)
            solver.add_clause([-X(s, placement[s][0], placement[s][1]) for s in range(n)])
    print(f"done: {n_sols} solution(s)")


if __name__ == "__main__":
    main()
