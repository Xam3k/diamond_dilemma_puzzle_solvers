"""refute_pilot.py -- pilot of the recursive shallow-refutation strategy.

Feeds an exact frontier (from solver3 FRONTIER_FILE) generation by
generation to a CP-SAT sidecar:
  INFEASIBLE -> dead, subtree eliminated.
  timeout    -> expanded 2 plies deeper (solver3 PREFIX_FILE), children
                join the next generation.
  FEASIBLE   -> logged LOUDLY (sidecar auto-loop-checks; single loop = GOLD).

Per generation it samples at most `cap` items (measurement pilot, not a
full proof run) and reports: kill rate, timeout rate, verdict times, and
the branching of expanded timeouts -- the numbers that decide whether the
full strategy converges and what it costs.

Usage:
  python refute_pilot.py <frontier_file> <start_depth> [budget_s] [cap] [max_depth]
"""
import os
import random
import shutil
import subprocess
import sys
import time

DIR = "oracle_pilot"
INSTANCE = "instance_gold.txt"
SOLVER = "./solver3_est.exe"


def feed(sidecar_dir, seq, line, budget_s):
    tmp = os.path.join(sidecar_dir, f"req_{seq}.txt.tmp")
    req = os.path.join(sidecar_dir, f"req_{seq}.txt")
    ans = os.path.join(sidecar_dir, f"ans_{seq}.txt")
    with open(tmp, "w") as f:
        f.write(line + "\n")
    os.rename(tmp, req)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < budget_s + 20:
        if os.path.exists(ans):
            try:
                v = open(ans).read().strip().split()[0]
            except (OSError, IndexError):
                v = ""
            if v:
                return v, time.perf_counter() - t0
        time.sleep(0.02)
    return "NOANSWER", time.perf_counter() - t0


def expand(lines, depth_to, out_path):
    """Expand prefixes 2 plies via solver3 PREFIX_FILE; returns children lines."""
    pf = "pilot_expand_in.txt"
    with open(pf, "w") as f:
        f.write("\n".join(lines) + "\n")
    env = dict(os.environ, FORCED_PAIRS="1", PREFIX_FILE=pf,
               DEPTH_CAP=str(depth_to), FRONTIER_FILE=out_path)
    subprocess.run([SOLVER, INSTANCE, "0", "0"], env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(out_path):
        return []
    return [l.strip() for l in open(out_path) if l.strip()]


def main():
    frontier_file = sys.argv[1]
    k = int(sys.argv[2])
    budget = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0
    cap = int(sys.argv[4]) if len(sys.argv) > 4 else 800
    max_depth = int(sys.argv[5]) if len(sys.argv) > 5 else 16

    random.seed(1)
    if os.path.isdir(DIR):
        shutil.rmtree(DIR)
    os.makedirs(DIR)
    log = open(DIR + "_sidecar.log", "w")
    sidecar = subprocess.Popen(
        [sys.executable, "oracle_sidecar.py", DIR, INSTANCE, str(budget)],
        stdout=log, stderr=subprocess.STDOUT)
    time.sleep(2.0)
    if sidecar.poll() is not None:
        print("FATAL: sidecar died; see", DIR + "_sidecar.log")
        sys.exit(1)

    gen = [l.strip() for l in open(frontier_file) if l.strip()]
    seq = 0
    report = []
    try:
        while gen and k <= max_depth:
            sample = gen if len(gen) <= cap else random.sample(gen, cap)
            frac = len(sample) / len(gen)
            n_inf = n_feas = n_to = 0
            t_sum = 0.0
            times = []
            timeouts = []
            for line in sample:
                v, dt = feed(DIR, seq, line, budget)
                seq += 1
                t_sum += dt
                times.append(dt)
                if v == "INFEASIBLE":
                    n_inf += 1
                elif v == "FEASIBLE":
                    n_feas += 1
                    print(f"*** FEASIBLE at k={k}! line: {line[:120]}...", flush=True)
                else:
                    n_to += 1
                    timeouts.append(line)
            times.sort()
            msg = (f"k={k:3d} gen_size={len(gen)} sampled={len(sample)} "
                   f"infeas={n_inf} feas={n_feas} timeout={n_to} "
                   f"kill={n_inf / len(sample):.1%} t_med={times[len(times) // 2]:.2f}s "
                   f"t_mean={t_sum / len(sample):.2f}s")
            print(msg, flush=True)
            report.append(msg)

            if not timeouts:
                print(f"generation k={k} fully killed -- cascade CONVERGED", flush=True)
                break
            children = expand(timeouts, k + 2, f"pilot_children_{k + 2}.txt")
            branching = len(children) / len(timeouts)
            # scale estimated next generation back up by the sampling fraction
            est_next = int(len(children) / frac)
            msg = (f"    expanded {len(timeouts)} timeouts -> {len(children)} children "
                   f"(branch={branching:.1f}); est full next gen ~{est_next}")
            print(msg, flush=True)
            report.append(msg)
            gen = children
            k += 2
    finally:
        sidecar.terminate()
        try:
            sidecar.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sidecar.kill()
        log.close()

    with open("pilot_result.txt", "w") as f:
        f.write("\n".join(report) + "\nPILOT_ALLDONE\n")
    print("wrote pilot_result.txt")


if __name__ == "__main__":
    main()
