"""frontier_ledger.py (v2) -- crash-resilient, ADAPTIVE sub-unit driver.

Each ROOT_UNIT is decomposed into depth-K0 frontier prefixes, processed in
batches by N workers with a PER-PREFIX NODE CAP. A prefix whose subtree
exceeds the cap is not allowed to stall its batch: it is DEFERRED, and the
driver automatically decomposes the deferred prefixes DELTA levels deeper
(K0 -> K0+DELTA -> ...) and enqueues those children. Recursion bottoms out
because subtrees shrink with depth. This bounds every job's runtime (~cap
nodes/prefix) so cheap work banks immediately and monster branches get
subdivided instead of blocking.

Every completed batch is banked in frontier_ledger.txt (atomic append +
fsync) with a pointer to its child frontier (if any), so a crash/reboot
loses only in-flight batches and the whole adaptive tree is reconstructed
on restart. Engine: solver3_sub.exe, FORCED_PAIRS + NEIGHBOR_FC (no oracle
in v1 -- process count == core count for clean many-core scaling).

Usage:
  python frontier_ledger.py <workers> <K0> <batch> <node_cap> [DELTA] [units]
  e.g. python frontier_ledger.py 6 6 300 500000000 6 14,17,23
"""
import os
import subprocess
import sys
import time

SOLVER = "./solver3_sub.exe"
INSTANCE = "instance_gold.txt"
LEDGER = "frontier_ledger.txt"
LOCKFILE = "frontier_ledger.lock"


def acquire_lock():
    if os.path.exists(LOCKFILE):
        try:
            pid = int(open(LOCKFILE).read().strip())
        except (ValueError, OSError):
            pid = None
        if pid is not None and os.system(f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul') == 0:
            print(f"[fl] FATAL: another driver (pid {pid}) holds {LOCKFILE}.")
            sys.exit(2)
    with open(LOCKFILE, "w") as f:
        f.write(str(os.getpid()))


def count_lines(path):
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path) as f:
        for _ in f:
            n += 1
    return n


def depth_of(ffile, k0, delta):
    # child frontiers carry one "_c<start>" segment per decomposition level
    return k0 + delta * ffile.count("_c")


def ensure_root_frontier(u, k0):
    path = f"fr_u{u}_d{k0}.txt"
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    env = dict(os.environ, FORCED_PAIRS="1", ROOT_UNIT=str(u),
               DEPTH_CAP=str(k0), FRONTIER_FILE=path)
    with open(f"frgen_u{u}.log", "w") as lf:
        subprocess.run([SOLVER, INSTANCE, "0", "0"], env=env, stdout=lf,
                       stderr=subprocess.STDOUT)
    return path if os.path.exists(path) else None


def decompose(defer_file, child_ffile, child_depth):
    """Expand deferred prefixes DELTA levels deeper -> child_ffile. Returns child count."""
    env = dict(os.environ, FORCED_PAIRS="1", PREFIX_FILE=defer_file,
               DEPTH_CAP=str(child_depth), FRONTIER_FILE=child_ffile)
    with open("frdecomp.log", "w") as lf:
        subprocess.run([SOLVER, INSTANCE, "0", "0"], env=env, stdout=lf,
                       stderr=subprocess.STDOUT)
    return count_lines(child_ffile)


def main():
    if len(sys.argv) < 5:
        print(__doc__); sys.exit(1)
    workers = int(sys.argv[1])
    k0 = int(sys.argv[2])
    batch = int(sys.argv[3])
    node_cap = int(sys.argv[4])
    delta = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    if len(sys.argv) > 6:
        units = [int(x) for x in sys.argv[6].split(",") if x != ""]
    else:
        units = list(range(48))

    acquire_lock()

    # ---- load ledger: banked labels + child pointers ----
    banked = set()
    child_of = {}
    if os.path.exists(LEDGER):
        for line in open(LEDGER):
            p = line.split()
            if len(p) >= 2 and p[1] == "DONE":
                banked.add(p[0])
                ch = "-"
                for tok in p:
                    if tok.startswith("child="):
                        ch = tok.split("=", 1)[1]
                child_of[p[0]] = ch
    print(f"[fl] workers={workers} K0={k0} batch={batch} node_cap={node_cap} "
          f"DELTA={delta} units={units} banked={len(banked)}", flush=True)

    def label(ffile, start):
        return f"{ffile}:{start}"

    # ---- reconstruct the pending work queue from the persisted tree ----
    queue = []              # list of (label, unit, ffile, start, count)
    scan = []
    unit_of = {}
    for u in units:
        rf = ensure_root_frontier(u, k0)
        if rf:
            scan.append(rf); unit_of[rf] = u
        else:
            print(f"[fl] WARN unit {u}: no root frontier", flush=True)
    seen_ffile = set()
    while scan:
        ff = scan.pop()
        if ff in seen_ffile:
            continue
        seen_ffile.add(ff)
        u = unit_of.get(ff, -1)
        npref = count_lines(ff)
        for start in range(0, npref, batch):
            lab = label(ff, start)
            if lab in banked:
                ch = child_of.get(lab, "-")
                if ch and ch != "-" and os.path.exists(ch):
                    scan.append(ch); unit_of[ch] = u
            else:
                queue.append((lab, u, ff, start, batch))
    print(f"[fl] {len(queue)} batches pending across {len(seen_ffile)} frontiers", flush=True)

    ledger_fh = open(LEDGER, "a")

    def bank(lab, sols, child):
        ledger_fh.write(f"{lab} DONE sols={sols} child={child}\n")
        ledger_fh.flush(); os.fsync(ledger_fh.fileno())

    running = {}   # slot -> (proc, lab, u, ff, start, log, defer, lf)

    def launch(slot):
        lab, u, ff, start, cnt = queue.pop()
        safe = lab.replace(":", "_").replace(".", "_").replace("/", "_")
        log = f"job_{safe}.log"
        defer = f"defer_{safe}.txt"
        for stale in (log, defer):
            if os.path.exists(stale):
                os.remove(stale)
        env = dict(os.environ, FORCED_PAIRS="1", NEIGHBOR_FC="1",
                   PREFIX_FILE=ff, PREFIX_START=str(start), PREFIX_COUNT=str(batch),
                   PREFIX_NODE_CAP=str(node_cap), DEFER_FILE=defer)
        env.pop("ROOT_UNIT", None); env.pop("ORACLE_DIR", None)
        lf = open(log, "w")
        proc = subprocess.Popen([SOLVER, INSTANCE, "0", "0"], env=env,
                                stdout=lf, stderr=subprocess.STDOUT)
        running[slot] = (proc, lab, u, ff, start, log, defer, lf)

    def reap(slot):
        proc, lab, u, ff, start, log, defer, lf = running[slot]
        if proc.poll() is None:
            return False
        lf.close()
        text = open(log, errors="replace").read() if os.path.exists(log) else ""
        exhausted = "PREFIX_BATCH EXHAUSTED" in text
        sols = 0
        for ln in text.splitlines():
            if ln.startswith("PREFIX_BATCH EXHAUSTED"):
                for tok in ln.split():
                    if tok.startswith("sols="):
                        sols = int(tok.split("=")[1])
        child = "-"
        if exhausted and os.path.exists(defer) and count_lines(defer) > 0:
            # decompose deferred prefixes DELTA deeper, enqueue children
            cd = depth_of(ff, k0, delta) + delta
            child = f"{ff[:-4]}_c{start}.txt"
            nkids = decompose(defer, child, cd)
            if nkids > 0:
                for cs in range(0, nkids, batch):
                    queue.append((label(child, cs), u, child, cs, batch))
                unit_of[child] = u
            else:
                child = "-"
        if exhausted:
            bank(lab, sols, child)
            if sols > 0:
                os.system(f"copy solutions3.txt GOLD_{lab.replace(':','_').replace('.','_')}.txt >nul 2>&1")
                print("=" * 70, flush=True)
                print(f"*** GOLD: {lab} produced {sols} solution(s)! ***", flush=True)
                print("=" * 70, flush=True)
        else:
            print(f"[fl] {lab} NOT done (rc={proc.returncode}); released", flush=True)
        if os.path.exists(defer):
            os.remove(defer)
        if os.path.exists(log):
            os.remove(log)
        del running[slot]
        return True

    banked_run = 0
    t0 = time.time()
    last = 0
    while queue or running:
        for slot in range(workers):
            if slot not in running and queue:
                launch(slot)
        time.sleep(1.0)
        for slot in list(running.keys()):
            if reap(slot):
                banked_run += 1
        now = int(time.time() - t0)
        if now - last >= 60:
            last = now
            print(f"[fl] progress: pending={len(queue)} running={len(running)} "
                  f"banked_this_run={banked_run}", flush=True)

    ledger_fh.close()
    print(f"[fl] ALL DONE: banked_this_run={banked_run}", flush=True)


if __name__ == "__main__":
    main()
