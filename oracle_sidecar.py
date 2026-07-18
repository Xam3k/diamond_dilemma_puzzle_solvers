"""oracle_sidecar.py -- persistent CP-SAT "stuck-subtree oracle" service for solver3.c.

Companion to the ORACLE_DIR feature added to solver3.c. solver3.c (see its
ORACLE_DIR comment block) drops a request file when one of its DFS frames at
depth [40,120] has chewed through more than ORACLE_MIN nodes without
finishing: "is the residual board (everything placed at ancestor depths
0..depth-1) still completable at all as a plain edge matching?" (the loop
constraint is deliberately relaxed -- INFEASIBLE of matching alone is a sound
prune, since matching is necessary for matching+single-loop). This process
answers those requests forever, one at a time, oldest first.

Protocol (mirrors solver3.c's ORACLE_DIR comment block exactly):
  <dir>/req_<seq>.txt   -- written by the solver (atomically, via rename):
                           "d <depth> n <nodes_so_far> B <slot:tile:rot> ..."
                           (same line format as STUCK_DUMP; oracle_probe.py's
                           parse_dump_line() reads it unchanged)
  <dir>/ans_<seq>.txt   -- written by this process (also atomically, via a
                           .tmp + os.replace): one word, INFEASIBLE / FEASIBLE
                           / UNKNOWN
  <dir>/completion_<seq>.txt -- written (FEASIBLE only): full "slot:tile:rot"
                           x 160 board satisfying the matching relaxation
  <dir>/GOLD_SOLUTION.txt -- written (FEASIBLE only, and only if the
                           completed board's gold arcs form EXACTLY one
                           closed loop): the actual Gold challenge solution

The residual CP-SAT model is exactly oracle_probe.py's build_residual_model()
(channeled tile/rot/pattern-id formulation, AllDifferent over unused tiles,
Element-based reverse-match on empty<->empty board edges, fixed constants on
empty<->placed edges) -- imported and reused verbatim, not reimplemented.
Per request: 2 search workers, cp_model_probing_level=0 (per house style --
probing churns without helping on this table-heavy encoding), the given
per-call timeout (CLI arg, default 8s). The model is rebuilt fresh for every
request rather than cached/updated incrementally -- individual solves are
~0.1-1s (validated in oracle_probe.py's viability report), so the rebuild
cost is negligible and this keeps the sidecar simple and obviously correct.

Malformed / partially-written request files (a request file whose content
doesn't parse, e.g. read mid-write by an OS that ever fails to make
solver3.c's rename() look atomic) are retried once after a 50ms pause, then
skipped (left for a future scan pass -- the file's mtime doesn't change, so
it will keep getting retried on each pass until it either parses or is
answered by a later, luckier read).

Usage:
  python oracle_sidecar.py <dir> <instance> [timeout=8]

Runs forever (Ctrl-C to stop); prints one status line per request served.
"""
import sys
import os
import time
import json

from oracle_probe import load_instance, build_residual_model, solve_probe, parse_dump_line
from loop_trace import count_loops

POLL_IDLE_SECONDS = 0.05
MALFORMED_RETRY_SECONDS = 0.05
ARCS_PATH = "arcs.json"


def scan_pending(dirpath):
    """Return sorted (ascending) seq numbers of req_<seq>.txt files that don't
    yet have a matching ans_<seq>.txt."""
    pending = []
    try:
        names = os.listdir(dirpath)
    except FileNotFoundError:
        return pending
    for name in names:
        if not (name.startswith("req_") and name.endswith(".txt")):
            continue
        mid = name[len("req_"):-len(".txt")]
        if not mid.isdigit():
            continue
        seq = int(mid)
        if not os.path.exists(os.path.join(dirpath, f"ans_{seq}.txt")):
            pending.append(seq)
    pending.sort()
    return pending


def read_req_with_retry(path):
    """Read + parse a request file. Retries once after MALFORMED_RETRY_SECONDS
    if the content is missing/malformed (guards against reading a request
    file mid-write); returns None if still unreadable after the retry."""
    for attempt in range(2):
        try:
            with open(path) as f:
                line = f.readline()
            if line.strip():
                parsed = parse_dump_line(line)
                if parsed is not None:
                    return parsed
        except OSError:
            pass
        if attempt == 0:
            time.sleep(MALFORMED_RETRY_SECONDS)
    return None


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def write_completion_and_check(dirpath, seq, n_slots, adj, tiles, arcs, placed, bundle, solver):
    """Reconstruct the full board from the CP-SAT solution, write
    completion_<seq>.txt, then loop-check it (count_loops from loop_trace.py).
    If it's a genuine single-loop Gold solution, also write GOLD_SOLUTION.txt
    and print a loud banner. Returns True iff GOLD_SOLUTION.txt was written."""
    board = dict(placed)
    for i, s in enumerate(bundle.empty_slots):
        local_t = solver.Value(bundle.tile_of[i])
        t = bundle.unused_tiles[local_t]
        r = solver.Value(bundle.rot[i])
        board[s] = (t, r)
    assert len(board) == n_slots

    board_line = " ".join(f"{s}:{board[s][0]}:{board[s][1]}" for s in range(n_slots)) + "\n"
    comp_path = os.path.join(dirpath, f"completion_{seq}.txt")
    with open(comp_path, "w") as f:
        f.write(board_line)

    placement = [board[s] for s in range(n_slots)]
    n_loops, ok, n_nodes = count_loops(placement, n_slots, adj, arcs, tiles)

    if ok and n_loops == 1:
        gold_path = os.path.join(dirpath, "GOLD_SOLUTION.txt")
        with open(gold_path, "w") as f:
            f.write(board_line)
        print("=" * 70, flush=True)
        print(f"*** GOLD SOLUTION FOUND -- req_{seq} completion is a single closed loop! ***", flush=True)
        print(f"*** written to {gold_path} ***", flush=True)
        print("=" * 70, flush=True)
        return True

    print(f"    [probe {seq}] completion loop-check: nodes={n_nodes} all_degree2={ok} loops={n_loops} (need 1)",
          flush=True)
    return False


def main():
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <dir> <instance> [timeout=8]")
        sys.exit(1)

    dirpath = sys.argv[1]
    instance = sys.argv[2]
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0

    os.makedirs(dirpath, exist_ok=True)

    n_slots, adj, tiles, seed_slots, seed_tile = load_instance(instance)
    arcs = json.load(open(ARCS_PATH))

    print(f"[oracle_sidecar] watching '{dirpath}' instance={instance} per_call_timeout={timeout}s "
          f"arcs={ARCS_PATH}", flush=True)

    served = 0
    n_infeas = n_feas = n_unk = 0

    while True:
        pending = scan_pending(dirpath)
        if not pending:
            time.sleep(POLL_IDLE_SECONDS)
            continue

        for seq in pending:
            req_path = os.path.join(dirpath, f"req_{seq}.txt")
            ans_path = os.path.join(dirpath, f"ans_{seq}.txt")
            if os.path.exists(ans_path):
                continue  # answered by a previous pass already (shouldn't happen, but cheap to check)

            parsed = read_req_with_retry(req_path)
            if parsed is None:
                print(f"[oracle_sidecar] req_{seq}: malformed/unreadable after retry, skipping this pass",
                      flush=True)
                continue

            depth, subtree_nodes, placed = parsed
            t0 = time.time()

            bundle = build_residual_model(n_slots, adj, tiles, placed)
            if bundle is None:
                # Board already full in the request -- nothing left to place,
                # trivially "feasible" (though this should not normally occur,
                # since solver3.c only asks at depth < N_SLOTS).
                write_atomic(ans_path, "FEASIBLE\n")
                served += 1
                n_feas += 1
                print(f"[oracle_sidecar] req_{seq} depth={depth} nodes={subtree_nodes} "
                      f"-> FEASIBLE (board already full) served={served}", flush=True)
                continue

            solver, status, dt = solve_probe(bundle, timeout)
            sname = solver.StatusName(status)
            if sname in ("FEASIBLE", "OPTIMAL"):
                verdict = "FEASIBLE"
            elif sname == "INFEASIBLE":
                verdict = "INFEASIBLE"
            else:
                verdict = "UNKNOWN"

            write_atomic(ans_path, verdict + "\n")

            gold_found = False
            if verdict == "FEASIBLE":
                gold_found = write_completion_and_check(dirpath, seq, n_slots, adj, tiles, arcs,
                                                         placed, bundle, solver)

            served += 1
            if verdict == "INFEASIBLE":
                n_infeas += 1
            elif verdict == "FEASIBLE":
                n_feas += 1
            else:
                n_unk += 1

            print(f"[oracle_sidecar] req_{seq} depth={depth} nodes={subtree_nodes} -> {verdict} "
                  f"solve_s={dt:.3f} served={served} (infeas={n_infeas} feas={n_feas} unk={n_unk})"
                  + (" *** GOLD ***" if gold_found else ""), flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[oracle_sidecar] interrupted, exiting.", flush=True)
