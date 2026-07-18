"""run_hybrid.py -- launch the oracle sidecar + one solver3.exe hybrid run.

Wires together oracle_sidecar.py (persistent CP-SAT "stuck-subtree oracle"
service) and solver3.exe (DFS + single-loop pruning, now with the ORACLE_DIR
sidecar-request feature) for a single combined run:

  1. cleans (removes + recreates) the ORACLE_DIR working directory so stale
     req_/ans_/completion_ files from a previous run can't confuse either
     side (a fresh req_0.txt from this run must not collide with an old
     ans_0.txt from a previous run).
  2. launches oracle_sidecar.py against that directory (logs to
     sidecar.log), and gives it a moment to import ortools before the
     solver starts issuing requests.
  3. launches solver3.exe with ORACLE_DIR/ORACLE_MIN set (env), plus a
     passthrough of any ROOT_UNIT/TIME_LIMIT already present in this
     process's environment (env=os.environ.copy() inherits them
     automatically; TIME_LIMIT is additionally settable via a CLI arg here
     for convenience), and the usual positional args (instance, node_limit,
     seed) (logs to hybrid_solver.log).
  4. waits for solver3.exe to exit, relays the tail of its log, then tears
     down the sidecar.
  5. if the sidecar ever found a genuine single-loop Gold solution
     (ORACLE_DIR/GOLD_SOLUTION.txt), prints a loud banner pointing at it.

Usage:
  python run_hybrid.py <instance> <node_limit> <seed> [oracle_min] [time_limit]

  instance    e.g. instance_gold.txt
  node_limit  solver3.exe's node_limit arg (0 = unlimited; use time_limit or
              Ctrl-C to bound the run instead)
  seed        solver3.exe's candidate-shuffle seed (0 = deterministic order)
  oracle_min  ORACLE_MIN env override (default 4000000, matching solver3.c's
              own default)
  time_limit  optional TIME_LIMIT env override (seconds); if omitted, any
              TIME_LIMIT already set in this process's environment is
              inherited unchanged (plain passthrough).
"""
import os
import sys
import shutil
import subprocess
import time

ORACLE_DIR = os.environ.get("ORACLE_DIR", "oracle_dir")
SOLVER = os.environ.get("SOLVER_BIN", "./solver3.exe")
SIDECAR = "oracle_sidecar.py"
SIDECAR_TIMEOUT_S = "8"
SIDECAR_STARTUP_GRACE_S = 1.5
LOG_TAIL_LINES = 40


def clean_oracle_dir(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def tail_file(path, n_lines):
    try:
        with open(path, errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n_lines:])
    except FileNotFoundError:
        return "(no log file)"


def main():
    if len(sys.argv) < 4:
        print(f"Usage: python {sys.argv[0]} <instance> <node_limit> <seed> [oracle_min] [time_limit]")
        sys.exit(1)

    instance = sys.argv[1]
    node_limit = sys.argv[2]
    seed = sys.argv[3]
    oracle_min = sys.argv[4] if len(sys.argv) > 4 else "4000000"
    time_limit = sys.argv[5] if len(sys.argv) > 5 else None

    clean_oracle_dir(ORACLE_DIR)
    print(f"[run_hybrid] ORACLE_DIR='{ORACLE_DIR}' cleaned", flush=True)

    sidecar_log = open(ORACLE_DIR + "_sidecar.log", "w")
    sidecar = subprocess.Popen(
        [sys.executable, SIDECAR, ORACLE_DIR, instance, SIDECAR_TIMEOUT_S],
        stdout=sidecar_log, stderr=subprocess.STDOUT)
    print(f"[run_hybrid] sidecar pid={sidecar.pid} -> {ORACLE_DIR}_sidecar.log", flush=True)

    # Give the sidecar a moment to import ortools and start its scan loop
    # before the solver can possibly write its first request.
    time.sleep(SIDECAR_STARTUP_GRACE_S)
    if sidecar.poll() is not None:
        sidecar_log.close()
        print(f"[run_hybrid] FATAL: sidecar exited immediately (rc={sidecar.returncode}); "
              f"see sidecar log:\n{tail_file(ORACLE_DIR + '_sidecar.log', LOG_TAIL_LINES)}", flush=True)
        sys.exit(1)

    env = os.environ.copy()
    env["ORACLE_DIR"] = ORACLE_DIR
    env["ORACLE_MIN"] = str(oracle_min)
    if time_limit is not None:
        env["TIME_LIMIT"] = str(time_limit)
    # ROOT_UNIT (and TIME_LIMIT, if not overridden above) pass through
    # automatically via env=os.environ.copy() -- nothing else to do.

    solver_log = open(ORACLE_DIR + "_solver.log", "w")
    solver = subprocess.Popen(
        [SOLVER, instance, str(node_limit), str(seed)],
        stdout=solver_log, stderr=subprocess.STDOUT, env=env)
    print(f"[run_hybrid] solver3.exe pid={solver.pid} node_limit={node_limit} seed={seed} "
          f"ORACLE_MIN={oracle_min}" + (f" TIME_LIMIT={time_limit}" if time_limit else "")
          + " -> {ORACLE_DIR}_solver.log", flush=True)

    try:
        while True:
            rc = solver.poll()
            if rc is not None:
                print(f"[run_hybrid] solver3.exe exited rc={rc}", flush=True)
                break
            time.sleep(2.0)
    except KeyboardInterrupt:
        print("[run_hybrid] interrupted; terminating solver3.exe...", flush=True)
        solver.terminate()
        try:
            solver.wait(timeout=5)
        except subprocess.TimeoutExpired:
            solver.kill()

    solver_log.close()
    print("----- solver3.exe log tail -----", flush=True)
    print(tail_file(ORACLE_DIR + "_solver.log", LOG_TAIL_LINES), flush=True)

    print("[run_hybrid] tearing down sidecar...", flush=True)
    sidecar.terminate()
    try:
        sidecar.wait(timeout=5)
    except subprocess.TimeoutExpired:
        sidecar.kill()
    sidecar_log.close()

    print("----- oracle_sidecar.py log tail -----", flush=True)
    print(tail_file(ORACLE_DIR + "_sidecar.log", LOG_TAIL_LINES), flush=True)

    gold_path = os.path.join(ORACLE_DIR, "GOLD_SOLUTION.txt")
    if os.path.exists(gold_path):
        print("=" * 70, flush=True)
        print(f"*** GOLD SOLUTION FOUND -- see {gold_path} ***", flush=True)
        print("=" * 70, flush=True)
    else:
        print("[run_hybrid] no GOLD_SOLUTION.txt this run.", flush=True)


if __name__ == "__main__":
    main()
