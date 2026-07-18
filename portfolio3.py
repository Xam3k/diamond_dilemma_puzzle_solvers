"""Run a portfolio of solver3.exe processes (different seeds explore different
subtrees first). Reports deepest partial across all, stops all on first full
solution. Merges status to portfolio_status.txt every ~30s.

Usage: python portfolio.py <node_limit_per_proc> <n_procs> <wall_seconds>
"""
import subprocess, sys, time, os, re, signal

node_limit = sys.argv[1] if len(sys.argv) > 1 else "100000000000"
nproc = int(sys.argv[2]) if len(sys.argv) > 2 else 8
wall = float(sys.argv[3]) if len(sys.argv) > 3 else 3600.0

procs = []
logs = []
for s in range(1, nproc + 1):
    lf = open(f"s3_seed{s}.log", "w")
    p = subprocess.Popen(["./solver3.exe", "instance_gold.txt", node_limit, str(s)],
                         stdout=lf, stderr=lf)
    procs.append(p); logs.append(f"s3_seed{s}.log")
print(f"launched {nproc} solver2 procs, node_limit={node_limit}", flush=True)

def deepest(lf):
    best = 0
    try:
        with open(lf, errors="replace") as f:
            for line in f:
                for m in re.findall(r"best=(\d+)|best_depth=(\d+)|max_depth=(\d+)", line):
                    for g in m:
                        if g:
                            best = max(best, int(g))
                if "SOLUTION" in line or "sol=1" in line.replace(" ", ""):
                    return best, True
    except FileNotFoundError:
        pass
    return best, False

t0 = time.time()
solved = False
while time.time() - t0 < wall:
    time.sleep(30)
    alive = sum(1 for p in procs if p.poll() is None)
    overall = 0
    sol_seed = None
    for i, lf in enumerate(logs):
        d, sol = deepest(lf)
        overall = max(overall, d)
        if sol:
            sol_seed = i + 1
    with open("portfolio_status.txt", "w") as f:
        f.write(f"t={time.time()-t0:.0f}s alive={alive}/{nproc} "
                f"deepest_partial={overall}/160 solution={'seed'+str(sol_seed) if sol_seed else 'none'}\n")
    print(f"t={time.time()-t0:.0f}s alive={alive} deepest={overall}/160 "
          f"{'*** SOLUTION seed '+str(sol_seed)+' ***' if sol_seed else ''}", flush=True)
    if sol_seed:
        solved = True
        break
    if alive == 0:
        print("all procs exited", flush=True)
        break

for p in procs:
    if p.poll() is None:
        p.terminate()
print(f"portfolio done. solved={solved}", flush=True)
