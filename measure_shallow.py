"""measure_shallow.py -- CP-SAT refutation-time / verdict-rate measurement
for shallow prefixes, per depth.

Consumes est_prefixes_<k>.txt files (dumped by solver3_est.exe EST_DUMP mode,
oracle req_ line format) and feeds them one at a time to a real
oracle_sidecar.py instance, timing each answer.

The two quantities that decide the shallow-enumeration strategy:
  time(k)     -- how long CP-SAT needs per depth-k subtree verdict
  infeas(k)   -- what fraction of depth-k survivors CP-SAT can refute
                 (FEASIBLE prefixes cannot be killed at this depth; the
                 strategy only works at depths where infeas is ~100%)

Usage: python measure_shallow.py [k1,k2,...] [per_k_limit] [sidecar_timeout_s]
"""
import os
import shutil
import subprocess
import sys
import time

DIR = "oracle_meas"
INSTANCE = "instance_gold.txt"


def main():
    ks = [int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "12,16,20,24").split(",")]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    timeout_s = sys.argv[3] if len(sys.argv) > 3 else "60"

    if os.path.isdir(DIR):
        shutil.rmtree(DIR)
    os.makedirs(DIR)

    log = open(DIR + "_sidecar.log", "w")
    sidecar = subprocess.Popen(
        [sys.executable, "oracle_sidecar.py", DIR, INSTANCE, timeout_s],
        stdout=log, stderr=subprocess.STDOUT)
    time.sleep(2.0)
    if sidecar.poll() is not None:
        print("FATAL: sidecar died on startup; see", DIR + "_sidecar.log")
        sys.exit(1)

    seq = 0
    results = {}  # k -> list of (seconds, verdict)
    try:
        for k in ks:
            path = f"est_prefixes_{k}.txt"
            if not os.path.exists(path):
                print(f"k={k}: no dump file, skipping")
                continue
            lines = [l.strip() for l in open(path) if l.strip()][:limit]
            res = []
            for line in lines:
                tmp = os.path.join(DIR, f"req_{seq}.txt.tmp")
                req = os.path.join(DIR, f"req_{seq}.txt")
                ans = os.path.join(DIR, f"ans_{seq}.txt")
                with open(tmp, "w") as f:
                    f.write(line + "\n")
                os.rename(tmp, req)
                t0 = time.perf_counter()
                verdict = None
                while time.perf_counter() - t0 < float(timeout_s) + 15:
                    if os.path.exists(ans):
                        try:
                            verdict = open(ans).read().strip().split()[0]
                        except (OSError, IndexError):
                            verdict = None
                        if verdict:
                            break
                    time.sleep(0.02)
                dt = time.perf_counter() - t0
                res.append((dt, verdict or "NOANSWER"))
                seq += 1
            results[k] = res
            n = len(res)
            times = sorted(r[0] for r in res)
            infeas = sum(1 for r in res if r[1] == "INFEASIBLE")
            feas = sum(1 for r in res if r[1] == "FEASIBLE")
            other = n - infeas - feas
            print(f"k={k:3d} n={n:3d} infeas={infeas} feas={feas} other={other} "
                  f"t_med={times[n // 2]:.3f}s t_mean={sum(times) / n:.3f}s t_max={times[-1]:.3f}s",
                  flush=True)
    finally:
        sidecar.terminate()
        try:
            sidecar.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sidecar.kill()
        log.close()

    with open("shallow_meas_result.txt", "w") as f:
        for k, res in results.items():
            for dt, v in res:
                f.write(f"{k} {dt:.4f} {v}\n")
        f.write("MEAS_ALLDONE\n")
    print("wrote shallow_meas_result.txt")


if __name__ == "__main__":
    main()
