"""oracle_probe.py -- viability probe for a "stuck-subtree CP-SAT oracle" hybrid.

Idea being tested: solver3.c (exhaustive DFS with static fill order + single-loop
pruning) occasionally gets stuck in an enormous subtree at some mid-search depth
d. If, instead of exhaustively DFS-ing that subtree, we handed the RESIDUAL board
(everything placed so far, at depths 0..d-1) to a CP-SAT solver and asked "is this
residual board completable at all as a plain edge matching?" (ignoring the single-
loop constraint -- that's a necessary-condition relaxation), an INFEASIBLE answer
would let the DFS prune the *entire* subtree in one CP-SAT call instead of
`subtree_nodes` DFS steps. This script empirically checks whether that trade is
worth it, using dumps collected by solver3.c's STUCK_DUMP instrumentation.

Residual CP-SAT model (mirrors cp_solver.py / cp_region.py's channeled formulation):
  - variables only for the EMPTY slots (slots not in the dump's placed board)
  - tile_of[i] in 0..n_empty-1 -- LOCAL index into the list of unused tiles
    (n_empty == n_unused_tiles always, since total slots == total tiles)
  - rot[i] in 0..2
  - pe[i][j] in 0..P-1 -- pattern-id on empty slot i's edge j
  - AllDifferent(tile_of)                                  (each unused tile once)
  - AllowedAssignments[tile_of[i],rot[i],pe[i][0..2]]      (placement -> patterns)
  - internal empty<->empty board edges: AddElement reverse-match (as cp_solver.py)
  - empty<->placed board edges: the placed side's pattern is a FIXED constant, so
    pe[empty][j] == pid[required_pattern] is a plain Add, no Element needed.
  - cp_model_probing_level = 0 (per house style; probing churns without helping
    on this table-heavy encoding)

Usage:
  python oracle_probe.py <dumpfile> <instance> [per_call_timeout=10] [max_probes=100]

Per dump line, records depth / subtree_nodes (from the dump) / status / solve_secs.
FEASIBLE probes also get their full completed board written to
oracle_completion_<i>.txt ("slot:tile:rot" for all 160 slots) -- such a board
satisfies the plain matching relaxation and is worth loop-checking as a full
candidate solution.

Final report (printed and written to oracle_probe_report.txt): one row per depth
bucket (40-59, 60-79, 80-99, 100-120) with n_probes, %INFEASIBLE, %FEASIBLE,
%UNKNOWN, median solve time, and the decision metric:
  est. node-equivalents saved per oracle call = %INFEASIBLE * median_subtree_nodes
  cost per oracle call (in node-equivalents)  = median_solve_secs * NODES_PER_SEC
  verdict: ORACLE PAYS (saved > 3x cost) / MARGINAL (saved > cost) / LOSES (else)
"""
import sys
import time
import statistics
from ortools.sat.python import cp_model

NODES_PER_SEC = 7_600_000  # solver3.c's observed raw DFS throughput (nodes/sec)
DEPTH_BUCKETS = [(40, 59), (60, 79), (80, 99), (100, 120)]


def load_instance(path):
    """Same format solver3.c's parse_instance / sat_solver.load_instance read."""
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


def parse_dump_line(line):
    """'d <depth> n <subtree_nodes> B <slot:tile:rot> ...' -> (depth, subtree_nodes, {slot: (tile, rot)})"""
    toks = line.split()
    if len(toks) < 5 or toks[0] != "d" or toks[2] != "n" or toks[4] != "B":
        return None
    depth = int(toks[1])
    subtree_nodes = int(toks[3])
    placed = {}
    for tok in toks[5:]:
        s, t, r = tok.split(":")
        placed[int(s)] = (int(t), int(r))
    if len(placed) != depth:
        # Not fatal -- just a sanity mismatch worth flagging; keep going, the
        # dump line itself is still usable (placed dict is authoritative).
        sys.stderr.write(
            f"WARNING: dump line claims depth={depth} but has {len(placed)} placed slots\n")
    return depth, subtree_nodes, placed


def build_residual_model(n_slots, adj, tiles, placed):
    """Build the CP-SAT model for the residual (empty-slot) board.

    Returns (model, tile_of, rot, pe, empty_slots, unused_tiles, pid, id_to_pat)
    or None if the dump's placed set is already full (nothing to solve).
    """
    rev = lambda p: p[::-1]

    empty_slots = [s for s in range(n_slots) if s not in placed]
    used_tiles = {t for (t, r) in placed.values()}
    unused_tiles = [t for t in range(n_slots) if t not in used_tiles]
    n = len(empty_slots)
    assert n == len(unused_tiles), (
        f"empty slots ({n}) != unused tiles ({len(unused_tiles)}) -- "
        f"placed board is inconsistent")

    if n == 0:
        return None

    sidx = {s: i for i, s in enumerate(empty_slots)}   # global empty slot -> local index

    # pattern-id universe: only need patterns that can appear among unused tiles
    # (plus their reverses, since placed-side requirements are reverses of
    # whatever pattern is already on the board).
    pats = sorted({tiles[t][e] for t in unused_tiles for e in range(3)} |
                  {rev(tiles[t][e]) for t in unused_tiles for e in range(3)})
    pid = {p: i for i, p in enumerate(pats)}
    P = len(pats)
    rev_id = [pid[rev(p)] for p in pats]

    m = cp_model.CpModel()
    tile_of = [m.NewIntVar(0, n - 1, f"t{i}") for i in range(n)]
    rot = [m.NewIntVar(0, 2, f"r{i}") for i in range(n)]
    pe = [[m.NewIntVar(0, P - 1, f"pe{i}_{j}") for j in range(3)] for i in range(n)]
    m.AddAllDifferent(tile_of)

    link = []
    for li, t in enumerate(unused_tiles):
        for r in range(3):
            link.append((li, r,
                         pid[tiles[t][(0 + r) % 3]],
                         pid[tiles[t][(1 + r) % 3]],
                         pid[tiles[t][(2 + r) % 3]]))
    for i in range(n):
        m.AddAllowedAssignments([tile_of[i], rot[i], pe[i][0], pe[i][1], pe[i][2]], link)

    seen = set()
    for s in empty_slots:
        for j in range(3):
            b, k = adj[s][j]
            if b in placed:
                # empty -> placed: fixed required pattern = rev of the placed
                # side's actual pattern on edge k.
                pt, pr = placed[b]
                placed_pattern = tiles[pt][(k + pr) % 3]
                required = rev(placed_pattern)
                if required not in pid:
                    # The placed board demands a pattern that doesn't even exist
                    # among the unused tiles -- trivially infeasible. Encode as
                    # an unsatisfiable literal rather than special-casing status.
                    m.Add(pe[sidx[s]][j] == P)  # P is out of domain [0,P-1] -> UNSAT
                else:
                    m.Add(pe[sidx[s]][j] == pid[required])
            else:
                # empty -> empty (internal): reverse-match via Element, once per edge
                key = (min((s, j), (b, k)), max((s, j), (b, k)))
                if key in seen:
                    continue
                seen.add(key)
                m.AddElement(pe[sidx[b]][k], rev_id, pe[sidx[s]][j])

    return ModelBundle(m, tile_of, rot, pe, empty_slots, unused_tiles, pid, pats)


class ModelBundle:
    __slots__ = ("m", "tile_of", "rot", "pe", "empty_slots", "unused_tiles", "pid", "pats")

    def __init__(self, m, tile_of, rot, pe, empty_slots, unused_tiles, pid, pats):
        self.m = m
        self.tile_of = tile_of
        self.rot = rot
        self.pe = pe
        self.empty_slots = empty_slots
        self.unused_tiles = unused_tiles
        self.pid = pid
        self.pats = pats


def solve_probe(bundle, timeout):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers = 2
    solver.parameters.cp_model_probing_level = 0
    t0 = time.time()
    status = solver.Solve(bundle.m)
    dt = time.time() - t0
    return solver, status, dt


def write_completion(path, n_slots, placed, bundle, solver):
    board = dict(placed)
    for i, s in enumerate(bundle.empty_slots):
        local_t = solver.Value(bundle.tile_of[i])
        t = bundle.unused_tiles[local_t]
        r = solver.Value(bundle.rot[i])
        board[s] = (t, r)
    assert len(board) == n_slots
    with open(path, "w") as f:
        f.write(" ".join(f"{s}:{board[s][0]}:{board[s][1]}" for s in range(n_slots)) + "\n")


def main():
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <dumpfile> <instance> [per_call_timeout=10] [max_probes=100]")
        sys.exit(1)

    dumpfile = sys.argv[1]
    instance = sys.argv[2]
    per_call_timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    max_probes = int(sys.argv[4]) if len(sys.argv) > 4 else 100

    n_slots, adj, tiles, seed_slots, seed_tile = load_instance(instance)

    with open(dumpfile) as f:
        lines = [l for l in (ln.strip() for ln in f) if l]

    if len(lines) > max_probes:
        print(f"[info] dumpfile has {len(lines)} lines; capping to first {max_probes}")
        lines = lines[:max_probes]

    records = []  # dicts: depth, subtree_nodes, status, solve_seconds

    for i, line in enumerate(lines):
        parsed = parse_dump_line(line)
        if parsed is None:
            sys.stderr.write(f"WARNING: skipping malformed dump line {i}: {line!r}\n")
            continue
        depth, subtree_nodes, placed = parsed

        bundle = build_residual_model(n_slots, adj, tiles, placed)
        if bundle is None:
            sys.stderr.write(f"[probe {i}] depth={depth} board already full -- skipping\n")
            continue

        solver, status, dt = solve_probe(bundle, per_call_timeout)
        sname = solver.StatusName(status)
        print(f"[probe {i}] depth={depth} subtree_nodes={subtree_nodes} "
              f"status={sname} solve_s={dt:.2f}", flush=True)

        if sname == "FEASIBLE" or sname == "OPTIMAL":
            comp_path = f"oracle_completion_{i}.txt"
            write_completion(comp_path, n_slots, placed, bundle, solver)
            print(f"    -> completion saved to {comp_path} (worth a loop-closure check)")
            sname = "FEASIBLE"  # normalize (no objective, OPTIMAL == FEASIBLE here)
        elif sname == "INFEASIBLE":
            pass
        else:
            sname = "UNKNOWN"  # UNKNOWN / MODEL_INVALID / timeout-without-answer

        records.append({
            "depth": depth,
            "subtree_nodes": subtree_nodes,
            "status": sname,
            "solve_seconds": dt,
        })

    report_lines = []
    report_lines.append("Stuck-subtree CP-SAT oracle viability report")
    report_lines.append(f"  dumpfile={dumpfile} instance={instance} "
                         f"per_call_timeout={per_call_timeout}s probes_run={len(records)}")
    report_lines.append("")
    header = (f"{'bucket':>10} {'n_probes':>9} {'%INFEAS':>8} {'%FEAS':>7} {'%UNK':>6} "
              f"{'med_solve_s':>12} {'saved_nodeeq':>13} {'cost_nodeeq':>12} {'verdict':>10}")
    report_lines.append(header)
    report_lines.append("-" * len(header))

    for lo, hi in DEPTH_BUCKETS:
        bucket_recs = [r for r in records if lo <= r["depth"] <= hi]
        n_probes = len(bucket_recs)
        bucket_str = f"{lo}-{hi}"
        if n_probes == 0:
            report_lines.append(f"{bucket_str:>10} {0:>9} {'--':>8} {'--':>7} {'--':>6} "
                                 f"{'--':>12} {'--':>13} {'--':>12} {'NO DATA':>10}")
            continue

        n_infeas = sum(1 for r in bucket_recs if r["status"] == "INFEASIBLE")
        n_feas = sum(1 for r in bucket_recs if r["status"] == "FEASIBLE")
        n_unk = sum(1 for r in bucket_recs if r["status"] == "UNKNOWN")
        pct_infeas = 100.0 * n_infeas / n_probes
        pct_feas = 100.0 * n_feas / n_probes
        pct_unk = 100.0 * n_unk / n_probes
        med_solve = statistics.median(r["solve_seconds"] for r in bucket_recs)
        med_subtree = statistics.median(r["subtree_nodes"] for r in bucket_recs)

        saved_nodeeq = (pct_infeas / 100.0) * med_subtree
        cost_nodeeq = med_solve * NODES_PER_SEC

        if cost_nodeeq <= 0:
            verdict = "ORACLE PAYS"
        elif saved_nodeeq > 3 * cost_nodeeq:
            verdict = "ORACLE PAYS"
        elif saved_nodeeq > cost_nodeeq:
            verdict = "MARGINAL"
        else:
            verdict = "LOSES"

        report_lines.append(
            f"{bucket_str:>10} {n_probes:>9} {pct_infeas:>7.1f}% {pct_feas:>6.1f}% {pct_unk:>5.1f}% "
            f"{med_solve:>12.3f} {saved_nodeeq:>13.0f} {cost_nodeeq:>12.0f} {verdict:>10}")

    report_lines.append("")
    report_lines.append(f"NODES_PER_SEC assumed = {NODES_PER_SEC:,} (raw DFS throughput)")
    report_lines.append("saved_nodeeq  = %INFEASIBLE * median_subtree_nodes  (nodes the DFS would "
                         "have chewed through before failing this subtree, now skipped in one call)")
    report_lines.append("cost_nodeeq   = median_solve_seconds * NODES_PER_SEC  (the DFS-node-equivalent "
                         "budget spent on the CP-SAT call itself)")
    report_lines.append("Verdict: ORACLE PAYS if saved > 3x cost, MARGINAL if saved > cost, else LOSES.")

    report = "\n".join(report_lines)
    print("\n" + report)
    with open("oracle_probe_report.txt", "w") as f:
        f.write(report + "\n")
    print("\n[info] report written to oracle_probe_report.txt")


if __name__ == "__main__":
    main()
