"""Robust SAT runner with a watchdog thread for real observability.

Builds the matching CNF, solves in a worker thread via solve_limited(expect_interrupt
=True); the main thread logs CaDiCaL's conflict/decision/propagation counters every
STATS_EVERY seconds and enforces a hard wall-clock budget via interrupt(). Enumerates
solutions with blocking clauses. All logging flushed so a detached job can be tailed.

Usage: python run_sat.py <instance.txt> [max_solutions] [wall_seconds]
Solutions appended to <instance>.sat_solutions.txt: "slot:tile:rot ..." per line.
UNSAT on gold = no complete edge matching exists = Gold challenge impossible.
"""
import sys, time, threading
from collections import defaultdict
from pysat.formula import CNF, IDPool
from pysat.card import CardEnc, EncType
from pysat.solvers import Cadical153
from sat_solver import load_instance

STATS_EVERY = 15.0

def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

def main():
    inst = sys.argv[1]
    max_sols = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    wall = float(sys.argv[3]) if len(sys.argv) > 3 else 1800.0
    n, adj, tiles, seed_slots, seed_tile = load_instance(inst)
    rev = lambda p: p[::-1]

    t0 = time.time()
    pool = IDPool()
    X = lambda s, t, r: pool.id(("x", s, t, r))
    cnf = CNF()
    bep = [defaultdict(list) for _ in range(3)]
    for t in range(n):
        for r in range(3):
            for j in range(3):
                bep[j][tiles[t][(j + r) % 3]].append((t, r))
    for s in range(n):
        lits = [X(s, t, r) for t in range(n) for r in range(3)]
        cnf.append(lits)
        cnf.extend(CardEnc.atmost(lits, 1, vpool=pool, encoding=EncType.seqcounter))
    for t in range(n):
        lits = [X(s, t, r) for s in range(n) for r in range(3)]
        cnf.append(lits)
        cnf.extend(CardEnc.atmost(lits, 1, vpool=pool, encoding=EncType.seqcounter))
    seen = set()
    for s in range(n):
        for j in range(3):
            b, k = adj[s][j]
            key = (min((s, j), (b, k)), max((s, j), (b, k)))
            if key in seen:
                continue
            seen.add(key)
            for (A, eA, B, eB) in ((s, j, b, k), (b, k, s, j)):
                for t in range(n):
                    for r in range(3):
                        p = tiles[t][(eA + r) % 3]
                        sup = [X(B, t2, r2) for (t2, r2) in bep[eB][rev(p)] if t2 != t]
                        cnf.append([-X(A, t, r)] + sup)
    if len(seed_slots) < n:
        allowed = set(seed_slots)
        for s in range(n):
            if s not in allowed:
                for r in range(3):
                    cnf.append([-X(s, seed_tile, r)])
    log(f"CNF built: {pool.top} vars, {len(cnf.clauses)} clauses in {time.time()-t0:.1f}s")

    out_path = inst.replace(".txt", "") + ".sat_solutions.txt"
    solver = Cadical153(bootstrap_with=cnf)
    n_sols = 0
    stop = False

    while n_sols < max_sols and not stop:
        result = {}
        def worker():
            result["sat"] = solver.solve_limited(expect_interrupt=True)
            result["done"] = True
        th = threading.Thread(target=worker, daemon=True)
        slice_t0 = time.time()
        th.start()
        last = 0
        while th.is_alive():
            th.join(timeout=1.0)
            el = time.time() - t0
            if time.time() - slice_t0 - last >= STATS_EVERY:
                last = time.time() - slice_t0
                st = solver.accum_stats()
                log(f"solving... t={el:.0f}s conflicts={st.get('conflicts')} "
                    f"decisions={st.get('decisions')} props={st.get('propagations')} "
                    f"restarts={st.get('restarts')}")
            if time.time() - t0 > wall:
                log(f"WALL {wall:.0f}s reached -> interrupting")
                solver.interrupt()
                th.join()
                stop = True
                break
        if "sat" not in result:
            break
        sat = result["sat"]
        el = time.time() - t0
        if sat is None:
            log(f"INTERRUPTED at t={el:.0f}s (no result within wall) -- "
                f"{'enumeration incomplete' if n_sols else 'UNKNOWN: neither SAT nor UNSAT proven'}")
            break
        if sat is False:
            log(f"UNSAT at t={el:.0f}s -- "
                f"{'no MORE solutions (enumeration complete)' if n_sols else 'NO complete matching exists -> GOLD IMPOSSIBLE'}")
            break
        model = set(l for l in solver.get_model() if l > 0)
        placement = {}
        for s in range(n):
            for t in range(n):
                for r in range(3):
                    if X(s, t, r) in model:
                        placement[s] = (t, r)
        if len(placement) != n:
            log(f"ERROR: decoded {len(placement)}/{n} placements")
            break
        line = " ".join(f"{s}:{placement[s][0]}:{placement[s][1]}" for s in range(n))
        with open(out_path, "a") as f:
            f.write(line + "\n")
        n_sols += 1
        log(f"SOLUTION {n_sols} found at t={el:.0f}s -> {out_path}")
        solver.add_clause([-X(s, placement[s][0], placement[s][1]) for s in range(n)])
    log(f"DONE: {n_sols} solution(s), elapsed {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
