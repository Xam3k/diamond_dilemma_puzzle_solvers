"""Decisive test: does conf_budget bound a Cadical153 solve_limited call?
Build synth_8 CNF, then time three budgeted slices. If each returns None in
seconds, the budgeted loop is viable for progress+wall. If it blocks for minutes,
conf_budget is ignored and we must use a separate killable process."""
import time
from collections import defaultdict
from pysat.formula import CNF, IDPool
from pysat.card import CardEnc, EncType
from pysat.solvers import Cadical153
from sat_solver import load_instance

n, adj, tiles, seed_slots, seed_tile = load_instance("instance_synth_8.txt")
rev = lambda p: p[::-1]
pool = IDPool(); X = lambda s, t, r: pool.id(("x", s, t, r)); cnf = CNF()
bep = [defaultdict(list) for _ in range(3)]
for t in range(n):
    for r in range(3):
        for j in range(3):
            bep[j][tiles[t][(j + r) % 3]].append((t, r))
for s in range(n):
    lits = [X(s, t, r) for t in range(n) for r in range(3)]
    cnf.append(lits); cnf.extend(CardEnc.atmost(lits, 1, vpool=pool, encoding=EncType.seqcounter))
for t in range(n):
    lits = [X(s, t, r) for s in range(n) for r in range(3)]
    cnf.append(lits); cnf.extend(CardEnc.atmost(lits, 1, vpool=pool, encoding=EncType.seqcounter))
seen = set()
for s in range(n):
    for j in range(3):
        b, k = adj[s][j]
        key = (min((s, j), (b, k)), max((s, j), (b, k)))
        if key in seen: continue
        seen.add(key)
        for (A, eA, B, eB) in ((s, j, b, k), (b, k, s, j)):
            for t in range(n):
                for r in range(3):
                    p = tiles[t][(eA + r) % 3]
                    sup = [X(B, t2, r2) for (t2, r2) in bep[eB][rev(p)] if t2 != t]
                    cnf.append([-X(A, t, r)] + sup)
print(f"CNF: {pool.top} vars {len(cnf.clauses)} clauses", flush=True)
sv = Cadical153(bootstrap_with=cnf)
for i in range(3):
    sv.conf_budget(20000)
    t0 = time.time()
    res = sv.solve_limited(expect_interrupt=False)
    st = sv.accum_stats()
    print(f"slice {i}: res={res} dt={time.time()-t0:.1f}s conflicts={st.get('conflicts')} "
          f"decisions={st.get('decisions')}", flush=True)
print("budget test done", flush=True)
