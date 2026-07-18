"""bench.py -- benchmarking harness for Diamond Dilemma DFS solvers
(solver2.exe now; solver3.exe once it lands, same CLI).

Usage:
  python bench.py <binary> <instance> <node_budget> <seeds_csv> [order_file]

  binary       e.g. solver2.exe or solver3.exe (path resolved by the OS the same
               way any subprocess argv[0] is -- pass a path if it's not on PATH
               or in the current directory).
  instance     e.g. instance_gold.txt
  node_budget  passed straight through as the solver's <node_limit> CLI arg
               (0 = unlimited -- be careful, this instance is known-hard, see
               REPORT.md). Also used as the CSV's node_budget column.
  seeds_csv    comma-separated seeds, e.g. "1,2,3,4" -- passed straight through
               as the solver's <seed> CLI arg (0 = deterministic/no shuffle).
  order_file   optional. If given, bench.py sets env var ORDER_FILE=<abspath> for
               the child process. solver2.exe currently IGNORES this (it always
               builds its own internal fill order) -- harmless. solver3.exe is
               expected to honour it. Use this to compare solver2 vs solver3
               vs alternative orders from gen_orders.py.

Runs are SEQUENTIAL (one seed at a time, not parallel) so wall-clock timings are
clean and not skewed by CPU contention between runs.

Each run appends one row to bench_results.csv (created with a header if it
doesn't exist yet -- delete/rename that file to start a fresh comparison).
After running, bench.py prints (1) a summary of the seeds just run, and (2) a
grouped mean-per-(binary,order) summary over EVERY row accumulated so far in
bench_results.csv -- that second table is the actual side-by-side comparison
across binaries/orders that BENCH_README.md's workflow builds up over several
invocations.

Metric definitions (see BENCH_README.md for the full explanation + caveats):
  nodes          solver-reported final node count (last stats line).
  secs           WALL time measured by bench.py around the subprocess call
                 (not solver-reported "elapsed"), so it includes process
                 startup/teardown.
  nps            solver-reported nodes/sec (last stats line).
  max_depth      solver-reported deepest fill-order depth ever reached (a
                 running max kept by the solver, so exact regardless of
                 stats-line sampling).
  sols           solver-reported solution count (last stats line).
  cycles_pruned  solver3-only metric; blank ("") for solver2.
  d40_refutes    NEW metric this harness adds: count of times the solver's
                 periodically-reported `depth=` value drops from >=40 to <40
                 between two CONSECUTIVE stats lines -- a coarse proxy for
                 "dove into a deep subtree, then backed all the way out"
                 (a deep refutation). Stats lines print every ~10s or every
                 2^26 nodes (whichever first) -- see solver2.c print_stats
                 call sites -- so this is a SAMPLED, not exact, signal. This
                 script also explicitly excludes the solver's always-depth=0
                 final summary line (printed just before "DONE.") from the
                 sequence, since that's a dummy placeholder, not a real depth,
                 and would otherwise manufacture a spurious refutation on
                 every single run.
"""
import csv
import os
import re
import subprocess
import sys
import time
from collections import defaultdict

# Core 6 fields solver2.c's print_stats() always emits, in this fixed order:
#   nodes=%llu depth=%d max_depth=%d sol=%llu nps=%.0f best=%d
STATS_RE = re.compile(
    r'\bnodes=(?P<nodes>\d+)\b.*?'
    r'\bdepth=(?P<depth>\d+)\b.*?'
    r'\bmax_depth=(?P<max_depth>\d+)\b.*?'
    r'\bsol=(?P<sol>\d+)\b.*?'
    r'\bnps=(?P<nps>[\d.]+)\b.*?'
    r'\bbest=(?P<best>\d+)\b'
)
# Searched independently (position-agnostic) so it doesn't matter where solver3
# inserts this extra field relative to the core 6 above.
CYCLES_RE = re.compile(r'\bcycles_pruned=(?P<cycles_pruned>\d+)\b')

CSV_FIELDS = [
    "binary", "seed", "order", "nodes", "secs", "nps", "max_depth", "sols",
    "cycles_pruned", "d40_refutes", "instance", "node_budget", "timestamp",
]

D40_DEPTH_THRESHOLD = 40


def parse_stderr(stderr_text):
    """Returns a dict of final stats (nodes/depth/max_depth/sol/nps/best/
    cycles_pruned as strings, whichever were seen) plus d40_refutes (int)."""
    lines = stderr_text.splitlines()
    last = {}
    depths_seen = []

    for i, line in enumerate(lines):
        m = STATS_RE.search(line)
        if not m:
            continue
        gd = m.groupdict()
        # The solver's final call to print_stats() (immediately before it
        # prints a "DONE." line) always passes depth=0 as a dummy value, not
        # a real search depth -- exclude it from the refutation sequence.
        is_dummy_final = (i + 1 < len(lines) and lines[i + 1].startswith("DONE."))
        if not is_dummy_final:
            depths_seen.append(int(gd["depth"]))
        for k, v in gd.items():
            if v is not None:
                last[k] = v
        cm = CYCLES_RE.search(line)
        if cm:
            last["cycles_pruned"] = cm.group("cycles_pruned")

    d40 = 0
    for prev_depth, cur_depth in zip(depths_seen, depths_seen[1:]):
        if prev_depth >= D40_DEPTH_THRESHOLD and cur_depth < D40_DEPTH_THRESHOLD:
            d40 += 1

    return last, d40


def run_once(binary, instance, node_budget, seed, order_file):
    cmd = [binary, instance, str(node_budget), str(seed)]
    env = os.environ.copy()
    if order_file:
        env["ORDER_FILE"] = os.path.abspath(order_file)

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    wall = time.perf_counter() - t0

    last, d40 = parse_stderr(proc.stderr)

    return {
        "nodes": int(last.get("nodes", 0)),
        "secs": wall,
        "nps": float(last.get("nps", 0.0)),
        "max_depth": int(last.get("max_depth", 0)),
        "sols": int(last.get("sol", 0)),
        "cycles_pruned": last.get("cycles_pruned", ""),
        "d40_refutes": d40,
        "returncode": proc.returncode,
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-15:]),
    }


def _mean(values):
    vals = [float(v) for v in values if v not in ("", None)]
    return (sum(vals) / len(vals)) if vals else float("nan")


def _fmt(x, spec="{:.1f}"):
    return spec.format(x) if x == x else "n/a"  # x == x is False for NaN


def print_table(rows, group_cols):
    """rows: list of dict-like rows (values may be strings, as read from CSV).
    group_cols: e.g. ('binary', 'order') or () for a single ungrouped summary."""
    groups = defaultdict(list)
    for r in rows:
        key = tuple(r[c] for c in group_cols) if group_cols else ()
        groups[key].append(r)

    header = "  " + "".join(f"{c:<14}" for c in group_cols) + \
        f"{'n':>3} {'nodes':>13} {'secs':>8} {'nps':>10} {'max_depth':>10} " \
        f"{'sols':>5} {'cyc_pruned':>10} {'d40/min':>8}"
    print(header)
    for key in sorted(groups.keys()):
        grp = groups[key]
        n = len(grp)
        nodes_m = _mean([r["nodes"] for r in grp])
        secs_m = _mean([r["secs"] for r in grp])
        nps_m = _mean([r["nps"] for r in grp])
        md_m = _mean([r["max_depth"] for r in grp])
        sols_m = _mean([r["sols"] for r in grp])
        cyc_m = _mean([r["cycles_pruned"] for r in grp])
        d40permin = _mean([
            (float(r["d40_refutes"]) / (float(r["secs"]) / 60.0)) if float(r["secs"]) > 0 else 0.0
            for r in grp
        ])
        label = "".join(f"{v:<14}" for v in key)
        print(f"  {label}{n:>3} {nodes_m:>13.0f} {secs_m:>8.2f} {nps_m:>10.0f} "
              f"{md_m:>10.1f} {sols_m:>5.1f} {_fmt(cyc_m, '{:>10.0f}'):>10} "
              f"{d40permin:>8.2f}")


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        print("Usage: python bench.py <binary> <instance> <node_budget> <seeds_csv> [order_file]")
        sys.exit(1)

    binary, instance, node_budget_s, seeds_csv = sys.argv[1:5]
    order_file = sys.argv[5] if len(sys.argv) > 5 else None
    node_budget = int(node_budget_s)
    seeds = [int(s) for s in seeds_csv.split(",") if s.strip() != ""]
    if not seeds:
        print("No seeds parsed from seeds_csv.", file=sys.stderr)
        sys.exit(1)
    if order_file and not os.path.exists(order_file):
        print(f"WARNING: order_file '{order_file}' does not exist "
              "(passing ORDER_FILE env var to the child anyway; it may ignore "
              "or error on it).", file=sys.stderr)

    order_label = os.path.basename(order_file) if order_file else "none"
    csv_path = os.path.join(os.getcwd(), "bench_results.csv")
    write_header = not os.path.exists(csv_path)

    rows_this_run = []
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()

        for seed in seeds:
            print(f"[bench] {binary} instance={instance} seed={seed} "
                  f"order={order_label} node_budget={node_budget} ...", flush=True)
            try:
                r = run_once(binary, instance, node_budget, seed, order_file)
            except OSError as e:
                print(f"  ERROR launching '{binary}': {e}", file=sys.stderr)
                continue

            if r["returncode"] != 0:
                print(f"  WARNING: '{binary}' exited with code {r['returncode']}. "
                      f"Last stderr lines:\n{r['stderr_tail']}", file=sys.stderr)

            row = {
                "binary": os.path.basename(binary),
                "seed": seed,
                "order": order_label,
                "nodes": r["nodes"],
                "secs": f"{r['secs']:.3f}",
                "nps": r["nps"],
                "max_depth": r["max_depth"],
                "sols": r["sols"],
                "cycles_pruned": r["cycles_pruned"],
                "d40_refutes": r["d40_refutes"],
                "instance": os.path.basename(instance),
                "node_budget": node_budget,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            writer.writerow(row)
            f.flush()
            rows_this_run.append(row)
            print(f"  -> nodes={row['nodes']} secs={row['secs']} nps={row['nps']:.0f} "
                  f"max_depth={row['max_depth']} sols={row['sols']} "
                  f"cycles_pruned={row['cycles_pruned'] or 'n/a'} "
                  f"d40_refutes={row['d40_refutes']}", flush=True)

    print()
    print(f"=== this run: {binary}, order={order_label}, {len(rows_this_run)}/{len(seeds)} seeds completed ===")
    if rows_this_run:
        print_table(rows_this_run, group_cols=())
    else:
        print("  (no successful runs)")

    if os.path.exists(csv_path):
        with open(csv_path, newline="") as f:
            all_rows = list(csv.DictReader(f))
        print()
        print(f"=== accumulated comparison across all rows in {csv_path} ===")
        print_table(all_rows, group_cols=("binary", "order"))


if __name__ == "__main__":
    main()
