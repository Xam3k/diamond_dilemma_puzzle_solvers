"""ledger_run.py -- distributed ROOT_UNIT sweep driver for solver3.exe.

Splits the exhaustive search into "units": unit u = (seed_slots[u/3], rotation
u%3) exactly as consumed by solver3.exe's ROOT_UNIT env var (see solver3.c,
main()'s outer seed x rotation loop). Each unit is a fully independent
top-level branch of the search tree, so units can be farmed out to worker
processes and their completion tracked persistently across restarts.

This script:
  1. reads/creates a ledger file (ledger.txt) of completed units, one line
     each: "unit <u> DONE nodes=<n> sols=<s>"
  2. spawns up to <workers> solver3.exe subprocesses, each claiming the next
     unit that is neither DONE nor currently claimed by another worker
     (claims are tracked in memory only -- restarting this script re-derives
     "done" from ledger.txt and simply re-claims everything else)
  3. on a worker's exit code 0 with an "UNIT u EXHAUSTED ..." marker in its
     log, appends a DONE line to ledger.txt (flushed + fsynced immediately);
     on anything else (exit code 3 / INCOMPLETE, crash, timeout without a
     marker, ...) the claim is simply released -- that unit can be retried
     later (in a future invocation, e.g. with a bigger --time-limit) but is
     NOT re-attempted automatically within this same run (it would just hit
     the same wall-clock cutoff again)
  4. prints a progress summary every ~60s: units done/total, current
     per-worker claims, and a loud banner if solutions3.txt is non-empty

Usage:
    python ledger_run.py <workers> <time_limit_per_unit_seconds> [max_wall_seconds]

Per-unit worker stdout+stderr is logged to unit_<u>.log (overwritten on each
attempt of that unit).
"""
import os
import re
import subprocess
import sys
import time

INSTANCE = "instance_gold.txt"
SOLVER = "./solver3.exe"
LEDGER_PATH = "ledger.txt"
SOLUTIONS_PATH = "solutions3.txt"
N_SLOTS = 160
N_EDGES = 240
PROGRESS_INTERVAL = 60.0
POLL_INTERVAL = 2.0

DONE_RE = re.compile(r"^unit (\d+) DONE")
EXHAUSTED_RE = re.compile(r"UNIT (\d+) EXHAUSTED nodes=(\d+) sols=(\d+)")
INCOMPLETE_RE = re.compile(r"UNIT (\d+) INCOMPLETE nodes=(\d+)")


def n_seed_slots_of(instance_path):
    """Token-for-token replica of solver3.c's parse_instance() layout, just
    to fish out n_seed_slots without invoking the solver. The instance file
    is a flat whitespace-separated token stream (fscanf-style), so a plain
    str.split() tokenizes it identically to the C parser regardless of line
    breaks."""
    toks = open(instance_path).read().split()
    idx = 0
    ns, ne = int(toks[idx]), int(toks[idx + 1]); idx += 2
    if ns != N_SLOTS or ne != N_EDGES:
        raise ValueError(f"unexpected instance header {ns} {ne} (expected {N_SLOTS} {N_EDGES})")
    idx += N_SLOTS * 3 * 2   # adjacency: N_SLOTS slots x 3 edges x (nb,kb)
    idx += N_SLOTS * 3       # tile patterns: N_SLOTS tiles x 3 pattern strings
    return int(toks[idx])    # n_seed_slots token


def load_done(ledger_path):
    done = {}
    if not os.path.exists(ledger_path):
        open(ledger_path, "w").close()
        return done
    with open(ledger_path) as f:
        for line in f:
            m = DONE_RE.match(line)
            if m:
                done[int(m.group(1))] = line.strip()
    return done


def append_ledger(ledger_path, unit, nodes, sols):
    with open(ledger_path, "a") as f:
        f.write(f"unit {unit} DONE nodes={nodes} sols={sols}\n")
        f.flush()
        os.fsync(f.fileno())


def scan_log(path):
    """Return ('EXHAUSTED', nodes, sols) or ('INCOMPLETE', nodes, None) or
    (None, None, None) if neither marker is found (crash / kill / OOM / ...)."""
    try:
        with open(path, errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return None, None, None
    m = EXHAUSTED_RE.search(text)
    if m:
        return "EXHAUSTED", int(m.group(2)), int(m.group(3))
    m = INCOMPLETE_RE.search(text)
    if m:
        return "INCOMPLETE", int(m.group(2)), None
    return None, None, None


LOCKFILE = "ledger_run.lock"

def acquire_lock():
    # refuse to start if another driver is alive (stale lock = dead PID -> ok)
    if os.path.exists(LOCKFILE):
        try:
            pid = int(open(LOCKFILE).read().strip())
        except ValueError:
            pid = None
        if pid is not None:
            r = os.system(f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul')
            if r == 0:
                print(f"[ledger_run] FATAL: another driver (pid {pid}) holds {LOCKFILE}; refusing to start.")
                sys.exit(2)
    with open(LOCKFILE, "w") as f:
        f.write(str(os.getpid()))

def main():
    acquire_lock()
    if len(sys.argv) < 3:
        print("Usage: python ledger_run.py <workers> <time_limit_per_unit_seconds> [max_wall_seconds]")
        return 1

    workers = int(sys.argv[1])
    time_limit = float(sys.argv[2])
    max_wall = float(sys.argv[3]) if len(sys.argv) > 3 else None

    n_seed = n_seed_slots_of(INSTANCE)
    n_units = n_seed * 3
    print(f"[ledger_run] instance={INSTANCE} n_seed_slots={n_seed} n_units={n_units} "
          f"workers={workers} time_limit_per_unit={time_limit}s max_wall={max_wall}", flush=True)

    done = load_done(LEDGER_PATH)
    if done:
        print(f"[ledger_run] resuming: {len(done)}/{n_units} units already DONE per {LEDGER_PATH}", flush=True)

    claims = {}             # unit -> {"proc","log","path","start"}
    skip_this_run = set()   # units that went non-DONE this run; left for a future (bigger-budget) run
    t0 = time.time()
    last_progress = 0.0

    def pick_next_unit():
        for u in range(n_units):
            if u in done or u in claims or u in skip_this_run:
                continue
            return u
        return None

    def launch(u):
        log_path = f"unit_{u}.log"
        lf = open(log_path, "w")
        env = os.environ.copy()
        env["ROOT_UNIT"] = str(u)
        env["TIME_LIMIT"] = str(time_limit)
        # node_limit=0 (unlimited; TIME_LIMIT is the real gate), seed=0
        # (deterministic candidate order, so a re-run of the same unit at a
        # bigger TIME_LIMIT explores the identical prefix before going deeper).
        env["FORCED_PAIRS"] = "1"
        proc = subprocess.Popen(
            ["python", "run_hybrid.py", INSTANCE, "0", str(u + 1), "4000000",
             str(time_limit)],
            stdout=lf, stderr=lf, env=dict(env, ORACLE_DIR=f"oracle_u{u}"))
        claims[u] = {"proc": proc, "log": lf, "path": log_path, "start": time.time()}
        print(f"[ledger_run] launched unit {u} (pid={proc.pid}) -> {log_path}", flush=True)

    def reap():
        finished = [u for u, c in claims.items() if c["proc"].poll() is not None]
        for u in finished:
            c = claims.pop(u)
            c["log"].close()
            rc = c["proc"].returncode
            status, nodes, sols = scan_log(c["path"])
            if rc == 0 and status == "EXHAUSTED":
                append_ledger(LEDGER_PATH, u, nodes, sols)
                done[u] = f"unit {u} DONE nodes={nodes} sols={sols}"
                print(f"[ledger_run] unit {u} DONE (nodes={nodes} sols={sols})", flush=True)
            else:
                skip_this_run.add(u)
                print(f"[ledger_run] unit {u} NOT done (rc={rc} status={status} nodes={nodes}); "
                      f"released -- retry later with a bigger time limit", flush=True)

    try:
        while True:
            reap()

            while len(claims) < workers:
                if max_wall is not None and time.time() - t0 >= max_wall:
                    break
                u = pick_next_unit()
                if u is None:
                    break
                launch(u)

            elapsed = time.time() - t0
            if elapsed - last_progress >= PROGRESS_INTERVAL:
                last_progress = elapsed
                sol_size = os.path.getsize(SOLUTIONS_PATH) if os.path.exists(SOLUTIONS_PATH) else 0
                claim_list = ", ".join(str(u) for u in sorted(claims)) or "none"
                print(f"[ledger_run] t={elapsed:.0f}s done={len(done)}/{n_units} "
                      f"claims=[{claim_list}] skipped_this_run={len(skip_this_run)}", flush=True)
                if sol_size > 0:
                    print("=" * 60, flush=True)
                    print(f"*** SOLUTION(S) FOUND -- {SOLUTIONS_PATH} is {sol_size} bytes! ***", flush=True)
                    print("=" * 60, flush=True)

            if len(done) >= n_units:
                print(f"[ledger_run] ALL {n_units} UNITS DONE.", flush=True)
                break
            if not claims and pick_next_unit() is None:
                if max_wall is not None and time.time() - t0 >= max_wall:
                    print("[ledger_run] max_wall_seconds reached with no workers running. Stopping.", flush=True)
                else:
                    print(f"[ledger_run] no more launchable units this run "
                          f"({len(skip_this_run)} parked as not-done). Stopping.", flush=True)
                break

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("[ledger_run] interrupted; terminating workers...", flush=True)
        for c in claims.values():
            c["proc"].terminate()

    print(f"[ledger_run] final: done={len(done)}/{n_units} skipped_this_run={len(skip_this_run)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
