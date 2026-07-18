# Diamond Dilemma benchmarking harness

Two scripts, stdlib-only (Python 3, no third-party deps):

- `gen_orders.py` -- generates four alternative static fill orders as plain text
  files (`order_default.txt`, `order_bottleneck.txt`, `order_perimeter.txt`,
  `order_blankdefer.txt`), each 160 lines / one slot index per line, from
  `instance_gold.txt` + `geometry.json`. Prints a constraint histogram (how many
  slots have 0/1/2/3 already-ordered neighbours) for each order -- the key
  quality metric for a fill order.
- `bench.py` -- runs a solver binary (`solver2.exe`, or `solver3.exe` once it
  exists) once per seed, sequentially, at a fixed node budget, optionally with
  an `ORDER_FILE` env var pointing at one of the files above. Appends rows to
  `bench_results.csv` and prints comparison tables.

Both are designed so `solver3.exe` (loop-pruning DFS, same CLI, stats add
`cycles_pruned=...`) drops in as a parameter -- nothing here is solver2-specific
except the exact stats-line format they both share.

## Quick start: a first benchmark

Run these from the `diamond-dilemma` directory (so relative paths like
`instance_gold.txt`, `solutions2.txt`, `best2_partial.txt` resolve the way the
solver binaries expect):

```
# 1. Generate the alternative orders (one-time, or whenever instance/geometry change).
#    Also prints each order's constraint histogram to stdout -- read it once.
python gen_orders.py

# 2. Baseline: solver2, its own built-in order, 4 seeds, a modest node budget
#    (20M nodes keeps each run to a reasonable wall time on this hard instance).
python bench.py solver2.exe instance_gold.txt 20000000 1,2,3,4

# 3. Same solver2, but pointed at each alternative order file. solver2.exe
#    currently IGNORES ORDER_FILE (ignores env var, always builds its own
#    order) -- these three runs are a no-op-order control: a sanity check that
#    passing an unused env var doesn't change solver2's numbers, and a
#    placeholder you re-run once solver3 exists.
python bench.py solver2.exe instance_gold.txt 20000000 1,2,3,4 order_bottleneck.txt
python bench.py solver2.exe instance_gold.txt 20000000 1,2,3,4 order_perimeter.txt
python bench.py solver2.exe instance_gold.txt 20000000 1,2,3,4 order_blankdefer.txt

# 4. Once solver3.exe exists and honours ORDER_FILE, repeat with solver3.exe:
python bench.py solver3.exe instance_gold.txt 20000000 1,2,3,4
python bench.py solver3.exe instance_gold.txt 20000000 1,2,3,4 order_bottleneck.txt
python bench.py solver3.exe instance_gold.txt 20000000 1,2,3,4 order_perimeter.txt
python bench.py solver3.exe instance_gold.txt 20000000 1,2,3,4 order_blankdefer.txt
```

That's solver2 vs solver3 x 4 seeds x (built-in order + 3 alternative orders) =
32 rows, all accumulated in one `bench_results.csv`. Every `bench.py` invocation
APPENDS to that file (delete or rename it to start a fresh comparison) and
prints two tables:

1. a summary of just the seeds it ran this invocation;
2. a **grouped mean-per-(binary, order)** table over every row accumulated so
   far in `bench_results.csv` -- this second table is the actual side-by-side
   comparison you want, and it grows as you run more configurations.

## Reading the metrics

| column | meaning |
|---|---|
| `nodes` | solver-reported final node count (its last stats line before exiting). |
| `secs` | WALL-clock time measured by `bench.py` around the subprocess call (NOT solver-reported "elapsed") -- includes process startup, so use this (not `nodes/nps`) for cross-run timing comparisons. |
| `nps` | solver-reported nodes/sec at its last stats line. |
| `max_depth` | deepest fill-order depth ever reached (a running max the solver keeps internally) -- exact, independent of how many stats lines got printed. |
| `sols` | solutions found. Almost certainly 0 on the real gold instance within any practical node budget -- see `REPORT.md`: no full 160-tile matching is currently known to exist. |
| `cycles_pruned` | solver3-only. Blank (`""`) for solver2, which doesn't report it. Number of times the loop-cycle check rejected a subtree. |
| `d40_refutes` | **new metric this harness adds.** See below. |

### `d40_refutes`, in detail

Counts how many times the solver's periodically-printed `depth=` value drops
from >=40 to <40 between two *consecutive* stats lines -- a proxy for "the
search dove into a >=40-deep subtree, then backtracked all the way out" (a deep
refutation).

**Caveats -- read before trusting this number:**

- Stats lines print only every ~10 seconds OR every 2^26 (~67M) nodes, whichever
  comes first (see `solver2.c`'s `print_stats` call sites in `dfs()`). This is a
  **sampled** signal, not an exact backtrack count. A short run may produce 0 or
  1 stats lines total, giving `d40_refutes=0` even if refutations happened
  between samples that were never observed.
- The solver's very last stats line -- printed immediately before its final
  `"DONE. nodes=... solutions=..."` line -- always reports `depth=0` as a
  placeholder (it's `print_stats(0)` called unconditionally after the search
  loop ends), **not** the actual final search depth. `bench.py` explicitly
  excludes that one line from the depth sequence so it doesn't manufacture a
  spurious "refutation" on every single run. If you write your own parser,
  do the same (look for the stats line immediately preceding a `DONE.` line).
- Treat `d40_refutes` as directional evidence aggregated across **many**
  seeds/runs (hence the per-configuration mean and the `/min` normalisation),
  not as a precise per-run count.

## "Smartness pays" -- how to judge a change (solver3's loop pruning, or an alternative order)

Compare **mean `d40_refutes`/min** and **mean `max_depth`** at **comparable `nps`**
across the grouped summary table's rows:

- **Accept:** higher `d40_refutes`/min and/or higher `max_depth`, at roughly the
  same (or only mildly lower) `nps`. The extra bookkeeping (a loop-cycle check,
  a smarter fill order) is finding and cutting off dead subtrees faster than
  before -- the classic "fewer, better nodes explored" win.
- **Reject:** `nps` drops by more than ~3x relative to the baseline **without**
  a compensating jump in `d40_refutes`/min or `max_depth`. The added smartness
  is costing more per-node than it saves -- net loser, revert or simplify it.
- **Ambiguous:** anything in between -- run more seeds before concluding
  anything (the harness is built for exactly this: just invoke `bench.py`
  again with more seeds; `bench_results.csv` accumulates and the grouped
  summary's mean tightens up).

## Known limitations

- Sequential only, by design (one seed at a time) -- for clean wall-clock
  comparisons, not maximum throughput. Don't run two `bench.py` invocations
  against the same instance at the same time on the same machine.
- `solver2.exe` (and presumably `solver3.exe`) append their own solutions to
  `solutions2.txt` / `best2_partial.txt` in the working directory as a side
  effect of running. `bench.py` does not touch, rotate, or clean these files.
- The four `order_*.txt` files are design artifacts for `solver3` (and for
  studying `solver2`'s own greedy logic offline); `solver2.exe` ignores
  `ORDER_FILE` entirely, so any `bench.py` run against `solver2.exe` with an
  `order_file` argument is really a regression check ("does an unused env var
  change anything" -- it shouldn't).
- `gen_orders.py`'s `order_perimeter.txt` and `order_blankdefer.txt` primary
  selection metrics both reduce to the SAME ranking as `order_default.txt`'s
  primary metric ("maximise already-ordered neighbours"), because the
  slot-adjacency graph is 3-regular (every slot has exactly 3 neighbours) --
  see the large comment at the top of `gen_orders.py` for the derivation. The
  four orders only differ in their tie-break rules. Read that comment before
  assuming the four orders differ more than they actually do.
