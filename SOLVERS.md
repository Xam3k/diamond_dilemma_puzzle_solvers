# Diamond Dilemma — How Every Solver Works

*A code-level tour of each solver in this project: what it searches for, how, and
exactly where in the source each mechanism lives. Line numbers are current as of
2026-07-17 and drift as files are edited — function names are the stable anchors.*

---

## 0. Shared foundations: board, tiles, matching, loops

Everything below rests on the same data model.

**The board** is a pentagonal bipyramid: 10 triangular faces × 16 triangular
slots = **160 slots**, connected by **240 internal edges** (each edge joins two
slots). `geometry.py` derives this and writes `geometry.json`, whose `edges`
list holds entries `{slotA, edgeA, slotB, edgeB}` meaning: slot A's local edge
`edgeA` (0/1/2) touches slot B's local edge `edgeB`. Every solver loads this
adjacency.

**The tiles**: 160 triangles, each with a gold-line pattern on its 3 edges.
A pattern is an 11-character bitstring — the 11 interior points of an edge
(at fractions (p+1)/12 along the edge), bit=1 where a gold line ends at that
point. Tile data originates from Jaap's `diamonddilemma.txt` (gold, verified
perfect) and is loaded as `tiles.json` (`tiles[t][e]` = pattern string of tile
t, edge e).

**The matching rule**: a tile placed with rotation `r` presents its pattern
`tiles[t][(j+r) % 3]` on slot-edge `j`. Two facing tiles match iff their
patterns are **mutual reversals**: `pat_A == reverse(pat_B)` (the same physical
points seen from opposite sides). This convention is implemented independently
in at least three places that cross-validate each other: `solver3.c`
(`rev_dense[]`, built in `build_dense_ids()` ~line 1075), `ruin_recreate.py`
(`rev = lambda p: p[::-1]`), and `score_board.py`.

**The single-loop rule** (gold challenge only): a full solution needs all 240
edges matched AND the gold lines forming **exactly one closed loop**. The
within-tile wiring (which endpoint connects to which) is `arcs.json` /
`arcs_flat.txt` — 365 arcs, human-verified. Whether a set of placed tiles
closes loops is decided by union-find over arc endpoints (see §1.4).

**The two score categories** (high-score work):
- **Category A** — max tiles placed with *zero* mismatched edges. Record: **142/160** (`rr_best.txt`).
- **Category B** — max matched edges with *all 160* tiles placed, mismatches allowed (Eternity-II-style). Record: **208/240** (`edges_best.txt` / `edges_208_checkpoint.txt`).

---

## 1. `solver3.c` — the exhaustive DFS engine ("find the solution or prove none")

*~2,700 lines of C. Compiled variants: `solver3.exe` (production),
`solver3_sub.exe` (with batch modes), `solver3_est.exe`, `solver3_bench.exe`,
`solver3_linux` (EPYC ELF). Compile: `zig cc -O3 -o solver3.exe solver3.c`.*

### 1.1 Startup pipeline (`main()`, ~line 2441)

1. **`parse_instance()`** (~813) reads the instance file (tile patterns per slot-seed layout).
2. **`build_edge_ids()`** (~870) numbers the 240 board edges; **`load_arcs()`** (~1053) loads the verified gold-arc wiring for the loop check.
3. **`build_dense_ids()`** (~1075) maps the ~22 distinct pattern strings to small integers ("dense ids") and builds `rev_dense[d]` = dense id of the reversed pattern. All matching becomes integer comparison.
4. **`build_spd_lists()`** (~1135): `spd_list[d][j]` = every `(tile, rot)` pair that shows pattern `d` on slot-edge `j` — the O(1) candidate generator for slots with one constrained neighbour.
5. **`build_fill_order()`** (~1154): computes the **static order in which slots are filled** (see §1.2).
6. **`build_pair_tables()`** (~1281): for every fill position with ≥2 already-placed neighbours, precomputes `pair_table[ord][dA*n_dense+dB]` = the exact candidate list satisfying *both* neighbour constraints simultaneously. This is why deep search is fast: 2-constraint candidate lookup is a single table index.
7. **`build_forced_pairs()`** (~697): finds pattern pairs that occur exactly once as (pattern, reverse) across all tiles — 7 of them — meaning those two tiles *must* be adjacent in any solution. Checked during search via `fp_check()` when `FORCED_PAIRS=1`.

### 1.2 Fill order (`build_fill_order()`, ~1154)

Greedy most-constrained-first (MRV): start from a seed slot; repeatedly pick the
unfilled slot with the most already-ordered neighbours (ties broken by a
rarity score, then slot index). Measured findings: this order is strong
(deterministic order reached depth 145 on planted instances where random
shuffles managed 79); the rarity tiebreak is **inert** — 94/160 steps have
ties, but tied slots are locally symmetric so all three tested rarity formulas
produce identical orders (`RARITY2` env, kept but off).

### 1.3 The DFS core (`dfs()`, ~1878)

`dfs(depth)` fills `fill_order[depth]`. For each candidate `(tile, rot)` from
the appropriate table (0-, 1-, or 2/3-constraint branch of the function), a
gauntlet of prunes runs **in increasing cost order**:

1. **`tile_used[t]`** — each tile used once.
2. **Third-constraint check** (3-neighbour slots): direct pattern comparison.
3. **`dry_check_would_close()`** (~1560) — *loop pruning*: would placing this tile close a gold cycle before the board is complete? A closed sub-loop can never grow into the single full loop (proven: subsets of one cycle's arcs always form paths), so closing early = prune. Counted in `cycles_pruned` (billions fire in practice).
4. **`fp_check()`** — the 7 forced adjacencies (env `FORCED_PAIRS=1`; adopted after a 3-seed race).
5. **`supply_remove()` / `demand_update_place()` / `supply_demand_ok()`** (~1430–1500) — global counting: for every pattern, are there still enough unused tile-edges to satisfy every open board edge that will demand it? An E2-style "colour counting" prune.
6. **`apply_loop_unions()`** (~1575) — commits the placement's arcs into the union-find (see §1.4); rejects if a cycle actually closes.
7. **`neighbor_fc_dead()`** (~1836) — *forward checking* (env `NEIGHBOR_FC=1`, adopted: 8.5× fewer nodes, 1.41× wall): after placing, every still-empty neighbour must have ≥1 unused `(tile, rot)` satisfying **all** its placed-neighbour constraints; if any neighbour is unfillable the placement is undone immediately. Sound by a witness argument: in any completable position the completion itself supplies a viable candidate.

Only survivors recurse. At `depth == 160`, `closed_cycles == 1` is required —
acceptance means a **true single-loop gold solution** (written by
`write_solution()`, ~1630).

### 1.4 The loop union-find (~1500–1628)

Each board edge has 11 point positions; each placed tile's arcs connect pairs
of points. Endpoints are nodes (240 edges × 11 positions, normalised to one
side); `apply_loop_unions()` unions the two endpoints of each arc, with an
**undo trail** (`uf_trail`, no path compression) so backtracking restores state
exactly (`undo_loop_unions()`). Joining two endpoints already in the same
component = a cycle closed → `closed_cycles++`. The check that a *hypothetical*
placement closes a cycle without committing it is `dry_check_would_close()`.

### 1.5 Symmetry units (`ROOT_UNIT`, main loop ~2540)

The board's rotation group has order 10, so the root of the search is split
into **48 units** = 16 seed-slot choices × 3 rotations (`seed_slots[]`,
`unit_si`/`unit_r`). `ROOT_UNIT=u` runs exactly one unit and exits with
`UNIT u EXHAUSTED nodes=… sols=…` (rc 0) or `UNIT u INCOMPLETE` (rc 3) — the
markers the ledger drivers bank on. Measured unit sizes span 7 orders of
magnitude (Knuth estimate, §1.8): 3.8×10¹¹ (unit 14) to ~10¹⁶ (unit 4);
total T ≈ 3×10¹⁶ → full exhaustion needs ~50+ core-years → **infeasible**;
the sweep is paused with 4,667 sub-batches permanently banked.

### 1.6 The CP-SAT oracle sidecar (`oracle_sidecar.py` + hooks in solver3.c)

The user-conceived "endgame oracle", validated at 60:1 payoff. When a subtree
consumes ≥ `ORACLE_MIN` (4M) nodes without resolving (`maybe_ask_oracle()`,
entry-node accounting at dfs() top ~1880), the solver writes the current
prefix to `ORACLE_DIR/req_<seq>.txt` in the format
`d <depth> n <nodes> B slot:tile:rot …` (`oracle_roundtrip()`, ~600) and polls
for `ans_<seq>.txt`.

`oracle_sidecar.py` (persistent Python process): `scan_pending()` (line 62)
finds unanswered requests; for each it builds a CP-SAT **completion model** —
can the remaining tiles legally fill the remaining slots? (matching only; the
loop rule is *not* encoded). Verdicts:
- **INFEASIBLE** (the norm: 100% of ~75k calls to date, median ~0.1–0.4 s) → solver hard-prunes the entire subtree (`g_prune_below` mechanism in dfs()).
- **FEASIBLE** → `write_completion_and_check()` (line 109) loop-checks the found completion; a single loop would be written as `GOLD_SOLUTION.txt` (never happened).

`run_hybrid.py` wires one solver + one sidecar together (cleans the oracle
dir, starts sidecar, starts solver with env, relays logs, tears down; env
passthrough for `ROOT_UNIT`/`TIME_LIMIT`/`SOLVER_BIN`, per-unit
`ORACLE_DIR` for parallel safety).

### 1.7 Batch / frontier machinery (crash-resilience + many-core decomposition)

Three solver3 modes, composable via env:
- **`FRONTIER_FILE` + `DEPTH_CAP=k`**: instead of descending past depth k, dump every depth-k node as a prefix line and return (`dfs()` top, ~1880). Enumerates a unit's *frontier* (e.g. unit 14 at k=6: 157,298 prefixes in ~1 s).
- **`PREFIX_FILE`** (`run_prefix_file()`, ~2337): re-root the search at each prefix listed in a file — rebuilds the fill order for the prefix's seed, places the prefix with full bookkeeping, then dfs()'s its subtree. With `PREFIX_START`/`PREFIX_COUNT` it processes only a slice; prints `PREFIX_BATCH EXHAUSTED start=… count=… sols=… deferred=…`.
- **`PREFIX_NODE_CAP` + `DEFER_FILE`**: a prefix whose subtree exceeds the node budget is *abandoned* (not stalled) and appended to the defer file for deeper decomposition.

**`frontier_ledger.py`** (the adaptive driver) orchestrates these: decompose
each unit into depth-K0 prefixes (`ensure_root_frontier()`, line 61), process
fixed-size batches across N workers (`launch()`/`reap()`, lines 153/170), bank
every completed batch in `frontier_ledger.txt` (atomic append+fsync, `bank()`,
line 147), and **recursively decompose deferred monsters** DELTA levels deeper
(`decompose()`, line 73), enqueueing the children. On restart it walks the
persisted child-pointers and resumes exactly (survived a reboot with zero
banked loss). PID lockfile prevents the double-driver accident that once
corrupted a run. Hard-won tuning lessons encoded in the defaults: small
batches (banking frequency is bounded by batch worst-case), per-prefix caps
(one billion-node monster must never stall a batch).

### 1.8 The Knuth tree-size estimator (`estimate_unit()`, ~2229)

`ESTIMATE=N` runs N random root-to-leaf probes per unit: at each depth,
`est_enumerate()` (~2125) lists the children that dfs() would actually visit
(all prunes applied), one is chosen uniformly, and the product of branching
factors along the way yields an unbiased estimate of the unit's node count
(Knuth 1975). Validated against exact truncated counts (4% error at
DEPTH_CAP=12). `EST_DUMP=k1,k2` dumps sample surviving prefixes; the depth
profile it produced killed the shallow-refutation strategy (survivors explode
~100×/2 plies around depth 8–12). Caveat: heavy-tailed — single freak probes
can dominate; treat per-unit numbers as order-of-magnitude.

---

## 2. High-score solvers (Category A: perfect partial)

### 2.1 `cp_maxsat.py` — CP-SAT max-placement (baseline; produced 132)

One global CP-SAT model (docstring, lines 1–15): booleans `place[s]`;
`tile_of[s]`/`rot[s]`; per-edge *effective patterns* `epat[s][j]` that take a
wildcard value P when unplaced; `AddAllDifferent` over a channelled
`v[s] = tile_of[s] if placed else n+s`; per-edge allowed-assignment tables
permitting wildcard-or-matching; objective `Maximize(sum(place))`. Notes:
`cp_model_probing_level=0` is mandatory (presolve churns otherwise) and
enumeration-completeness requires `num_search_workers=1` (multi-worker CP-SAT
silently drops solutions — a bug we caught during the silver/red/blue
validation).

### 2.2 `ruin_recreate.py` — LNS matheuristic (champion; produced 142)

The record-holder for Category A. Loop (main body, ~line 96 on):
1. **RUIN** — `neighborhood()` (line 76) frees a slot set F: all current holes + a BFS ring around random centers; variants: `RR_BIG` (free 1–2 whole faces), `RR_FOCUS` (restrict big ruins to the bottleneck faces), `RR_GUIDE` (path relinking: center ruins where the incumbent disagrees with a guide partial — the cross-basin trick that produced the historic 138), `RR_ALLHOLES` (free *every* hole + N-ring at once).
2. **RECREATE** — a CP-SAT model over F only (built at ~line 114): freed tiles may be placed or left out (`place[i]`), permutation via AllDifferent channelling, edge tables exactly as in cp_maxsat but only for edges touching F, **warm hints** = incumbent placement, objective = maximize placements. Sub-solve budget `sub_wall` seconds.
3. **ACCEPT** if `new_score >= cur_score` (plateau moves allowed for diversification); `best` snapshot saved to `RR_OUT` on strict improvement.
4. **ILS kicks** (`RR_KICK…`, added 2026-07-16): after N non-improving repairs, deliberately evict hole-adjacent "wall" tiles and re-climb (the `best` snapshot is protected).

Measured verdict: 142 is a *deep* local maximum — all 18 holes "dead" (zero
free tiles fit; `analyze_partial.py` verifies this), and it survived 120 kicks
and a coordinated 102-slot all-holes re-solve. 142 is very likely the true
Category-A maximum (unproven).

### 2.3 `analyze_partial.py` — diagnosis tool

Given instance + partial: hole locations/components, placed-neighbour counts,
per-hole fitting-(tile,rot) counts (the "dead holes" finding), face
distribution (17/18 holes bottom-pyramid).

---

## 3. High-score solvers (Category B: E2-style matched edges, full board)

### 3.1 `tabu_solver.c` — single-move tabu search (baseline; ceiling ~190 warm)

Full 160-tile assignment always; cost = # mismatched board edges (0 = solved).
Moves: swap two tiles (with re-rotation) or rotate one tile in place; fully
incremental delta-cost evaluation (`edge-cost helpers`, ~line 126); classic
tabu tenure + aspiration + hard restart on long stalls (header comment, lines
15–48). `TABU_WARM` warm-starts from a partial (holes jam-filled). Also
extracts a perfect partial from its best full board by greedy vertex cover on
the mismatch graph (`mc_partial_best.txt`). **Measured limitation:** plateaus
within ~100 s (cold: cost 91; warm from the 142 board: cost 50 = 190 matched
after 116 iterations, then frozen). The move set is too local — this
motivated the LNS below.

### 3.2 `rr_edges.py` — CP-SAT large-neighbourhood edge maximiser (champion; 208/240)

The Category-B record holder; structure mirrors ruin_recreate but on the
mismatch objective with a **full board** (no place/not-place — a pure
permutation of the freed tiles):

1. **Neighbourhood** (`neighborhood()`): 40% path-relink toward `RE_GUIDE`
   board if set (centers where incumbent differs from guide) / else 70–80%
   *mismatch-guided* (centers = endpoints of sampled mismatched edges + ring) /
   else random ring; capped at `RE_MAXF` slots.
2. **Model** (main loop): `tv[i]` (which freed tile) + `rv[i]` (rotation),
   `AddAllDifferent(tv)`, tile→pattern channelling via `AddAllowedAssignments`
   link tuples; per touched edge a Bool `mv` reified through a pattern-pair
   table (`match_tbl`: (patA, patB, 1/0)); boundary edges to fixed tiles reify
   equality with the required pattern. Objective `Maximize(sum(mvars))`;
   incumbent as hints; per-iteration seed randomised.
3. **Accept** if score ≥ current (recomputed by the independent `score()` —
   never trusts the model's own count); saves `RE_OUT` on record.
4. **Category-A auto-extraction** (`extract_perfect()`): after every new best,
   greedy vertex cover on the mismatch graph → if the perfect partial beats
   142 it is saved to `RE_A_OUT` (`*** CATEGORY-A RECORD ***`). Trigger needs
   mismatches ≤ ~17; currently 32.

**Campaign so far** (all on 8 local cores): 186 (=142 board) → 190 (warm tabu)
→ 198 (90-s smoke) → 205 (2-h run) → 206 → 208 (44-slot regions). Since then
208 has survived ~4,300 *optimal* 52-slot repairs, path-relinking toward a
second basin (which independently climbed 161→192 from the old 132 partial),
and is currently being attacked by 64-slot/120-s repairs plus a kick-restart
(8 random swaps down to 173, re-climbing). Pattern: cost of each +1 edge grows
super-linearly — the E2 signature.

### 3.3 `score_board.py` — independent verifier

Scores any board file on both categories from `geometry.json` + `tiles.json`
alone (shares no code with any solver); asserts no duplicate tiles; `--edges`
lists each mismatch. Used to audit every record claim (all verified).

---

## 4. Verification & data-integrity tools (the reason we trust the data)

- `check_verified.py` / `check_white_full.py` — rebuild tiles from the
  human-verification files; bits↔arcs consistency, odd-endpoint and
  arc-crossing checks.
- `cp_white_challenge.py` / `cp_white_1w.py` — solve the silver/red/blue
  challenges (white lines). Outcome: **our counts exactly match Jaap's
  published 2/1/1** — the end-to-end proof that tile data + conventions +
  solver stack are correct.
- `rhombus_edit.py` / `red_edit.py` / `blue_band_edit.py` — min-edit CP-SAT
  fitters that located ~15 single-position digitisation errors against known
  solutions.
- `loop_trace.py`, `gen_loop_synthetic.py` — loop counting and planted
  single-loop instance generation (solver validation).

---

## 5. Records & provenance

| Result | Value | Solver | File |
|---|---|---|---|
| Category A (perfect partial) | **142/160 tiles** (186/240 edges) | `ruin_recreate.py` (cross-basin seed) | `rr_best.txt` |
| Category B (matched edges, full board) | **208/240** | `rr_edges.py` | `edges_best.txt`, checkpoint `edges_208_checkpoint.txt` |
| Exhaustive coverage | 4,667 sub-batches banked; units 14/17/23 partial | `frontier_ledger.py` + `solver3_sub.exe` | `frontier_ledger.txt` |
| Tree size (why exhaustion is off) | T ≈ 3×10¹⁶ nodes (~50+ core-years) | `ESTIMATE` mode | `est_result.txt` |
| Pipeline validation | silver 2 / red 1 / blue 1 = Jaap exactly | `cp_white_1w.py` et al. | `solutions_view.html` |
