# Diamond Dilemma: What I Tried That Didn't Work (and How I Decided)

*Companion to `SOLVERS.md`. Every abandoned approach, the measurement or
argument that killed it, and a note on whether the
rejection is airtight or could be overturned by a successor with more compute,
a better implementation, or a new idea. Read this before re-trying anything.*

---

## 0. The decision doctrine (how things got rejected)

Every idea passed through the same discipline, **measure first, one change at
a time**, using these yardsticks as a
rejection is only as good as its measurement:

1. **Prefix-race**, run two solver variants at equal wall time on the same
   seed and compare *decision prefixes* (`pfx=` in the stats line: the
   candidate ordinal at each depth of the current path) lexicographically. The
   variant further along the tree covered more. Used for: forced-pairs
   (adopted), oracle (adopted), forward checking (adopted).
2. **Exhaustive-count invariance**, truncate the tree (`DEPTH_CAP`) and
   compare *exact* node counts. A value-ordering change must keep the count
   identical (reorder-invariance = correctness); a pruning change must reduce
   it without losing solutions. Used for: rigidity, RARITY2, NEIGHBOR_FC.
3. **Nodes/score-to-target on planted instances**, `gen_loop_synthetic.py`
   creates instances with a known single-loop solution; compare how fast
   variants approach it. Caveat discovered late: **max-depth-reached is a
   misleading metric** (see §6.1).
4. **Instrumented rates**, add counters, measure the actual frequency of the
   phenomenon an optimization targets before building it (e.g. equivalence
   revisit rate, fill-order tie frequency).
5. **Unbiased tree-size estimation**, Knuth random-probe estimator
   (`ESTIMATE` mode), validated against an exact truncated count (4% error)
   before being trusted for the go/no-go on exhaustion.
6. **Independent re-scoring**, every record claim re-verified by
   `score_board.py`, which shares no code with any solver.
7. **Witness arguments**, where possible, soundness proven rather than
   tested (e.g. forward checking: any completable state supplies a viable
   candidate for every empty slot, so the prune can never fire on a viable
   branch).

---

## 1. Whole solver families that failed (goal: find the full gold solution)

### 1.1 CNF / CDCL SAT (`sat_solver.py`, `run_sat.py`)
- **Result:** correct but unusably slow ~127 conflicts/second.
- **Why (diagnosis):** my encoding, not necessarily SAT itself; the model was
  large and propagation-weak.
- **Still holds?** ⚠️ **Weak rejection.** A compact encoding run under a
  modern solver (kissat) was explicitly proposed and never executed.
  A successor should try: direct pattern-variable encoding, incremental
  assumptions per symmetry unit.

### 1.2 CP-SAT satisfaction on the full instance (`cp_solver.py`)
- **Result:** UNKNOWN after 1,955 s deterministic-time (8 workers); a later
  48 h / 2-worker attempt was killed by a reboot at 27.4 h having fixed only
  ~60 of 116,797 variables, extrapolated time to verdict: years.
- **Still holds?** Mostly. A 64–128-worker cloud attempt is qualitatively
  different and untried, but I deprioritized it because the puzzle is
  probably satisfiable (§5.3), making an UNSAT proof attempt moot and a SAT
  find astronomically lucky.

### 1.3 Frontier backtracker (`frontier_solver.py`)
- **Result:** validated on 0-blank synthetics; crawls on real gold, blank
  edges give ~138-way branching at the frontier.
- **Still holds?** Yes for the frontier-first ordering itself; superseded by
  the MRV fill-order of `solver2/3` which measures far better.

### 1.4 Min-conflicts / simulated annealing (`solver_mc.c`)
- **Result:** ~5M moves/s, never solved even the *easy* 0-blank synthetic
  (best ~25–50 mismatched edges of 240).
- **Diagnosis:** the permutation constraint means a single swap usually breaks
  more edges than it fixes → greedy stalls, hot search random-walks.
- **Still holds?** Yes for single-move local search, re-confirmed twice more
  (tabu §4.1, and the B-metric tabu plateau §4.3). Large-neighbourhood moves
  are the fix (that's `rr_edges.py`).

### 1.5 Parallel tempering (`ptemper.c`)
- **Result:** cold replica drifts away from the warm-start basin; never beat
  136 (the then-record).
- **Still holds?** Probably; same single-move pathology as §1.4.

### 1.6 Max-clique / add-only branch & bound (`clique_solver.c`)
- **Result:** cold = 97/160 at ~5k nodes/s; warm-started from 136 it is
  *structurally stuck* an add-only method cannot remove-and-rearrange the
  dead holes.
- **Still holds?** Yes, the 18-dead-holes analysis (§4.2) proves rearrangement
  is required, which add-only B&B cannot do by definition.

### 1.7 Belief / survey propagation (`bp_solver.py`)
- **Result:** loopy BP never converges on gold (iterations pinned at max
  across damping 0.9 / field 0.3 sweeps); on a *satisfiable* synthetic reaches
  only 4/160 (default) to 18/160 (tuned).
- **Diagnosis:** SP's success regime is sparse random graphs near the SAT
  phase transition; this is a dense, structured, hard-permutation factor
  graph, the classic BP failure case.
- **Still holds?** Yes, with high confidence; the mechanism mismatch is
  fundamental, not a tuning issue.

---

## 2. Solver-3 features rejected by measurement

### 2.1 Equivalence memo-cache (transposition table)
- **Hypothesis:** the DFS revisits equivalent board states; caching would prune.
- **Measurement:** `EQUIV_STATS` instrumentation, then an *unsampled* recheck:
  true revisit rate **0.006%** over 486M probes (earlier sampled estimate
  0.004% over 13.3M).
- **Verdict:** dead: a cache can save at most 0.006% of work before its own
  overhead. Cost of measurement: ~2 minutes. **Still holds?** Yes at these
  depths; a successor caching *at shallow depths only* would face the same
  measured rate (it was measured per-depth).

### 2.2 Rigidity value-ordering (`RIGIDITY=1`, kept but off)
- **Hypothesis (E2 lore):** try hard-to-place tiles first.
- **Measurement:** (a) exhaustive-count invariance passed (3,421,617 nodes,
  byte-identical → implementation correct); (b) on hard planted instances,
  identical progress to the default ordering (both reach depth 145/142 in
  400M nodes).
- **Diagnosis:** MRV *slot* ordering already forces rigid tiles early, the
  slot picks the tile, so tile-side ordering is subsumed.
- **Still holds?** For this fill order, yes. A *piece-based* search (pick tile
  first, then slot) is a different architecture where rigidity ordering would
  matter, this is untried (§7.3).

### 2.3 Frequency-weighted fill-order tiebreak (`RARITY2=1/2`, kept but off)
- **Hypothesis (my edge-imbalance idea):** better rarity measure in the
  MRV tiebreak exploits the unequal pattern distribution.
- **Measurement:** three formulas (min-count, frequency-weighted sum,
  product/joint), **byte-identical node counts** on units 14/17/23
  (206,432,173 / 5,516,520,741 / 4,557,468,981). Diagnostic counter showed
  ties are frequent (94/160 fill steps) but tied slots have *identical*
  rarity under every formula (local board symmetry), slot index decides
  regardless.
- **Verdict:** the fill order is structurally locked by MRV + geometry; no
  rarity refinement can move it. **Still holds?** For rarity-*based* tiebreaks,
  yes (proven, not sampled). Non-rarity tiebreaks (lookahead, centrality)
  were never tried (§7.2).

### 2.4 Position-frequency exploitation
- Rejected by argument: per-position frequency is a strictly coarser signal
  than the per-pattern supply/demand counting already active. Never measured
  separately. ⚠️ Argument-only rejection.

---

## 3. Strategies rejected by measurement or analysis

### 3.1 Full exhaustion of the search space
- **Measurement chain:** Knuth estimator (validated 4% vs exact truncated
  count) → T ≈ 3×10¹⁶ nodes robust reading (heavy-tail caveat: raw total
  5×10¹⁸ was one freak probe). Throughput 1.5×10¹² nodes/day on 8 cores.
  Forward-checking re-measurement showed node reduction *saturates*
  (5.3× @cap10, 8.5× @cap12, 8.3× @cap14) and wall-clock gain is only 1.41×.
- **Verdict:** 50+ core-years even optimistically; $50k–500k on cloud. Dead.
- **Still holds?** Unless someone finds a >100× pruning idea, yes. The
  estimator (`ESTIMATE` mode) is there to re-run against any improved engine
  *re-measure T before dismissing a new pruning idea*.

### 3.2 Shallow refutation (enumerate depth-k frontier, CP-SAT each subtree)
- **Hypothesis:** CP-SAT kills subtrees in 0.1 s from depth 12+; enumerate a
  shallow frontier and refute everything.
- **Measurement:** `refute_pilot.py` ran the actual cascade on unit 14's exact
  frontier, generation by generation: kill rates *oscillate* with depth
  (21.5% @8, 66% @10, 89% @12, 78% @14, 34% @16, 98% @18 at 3 s budget) and
  timeout-branching products explode exactly at the "face-opening" depths
  (×156 and ×64 growth at gens 8 and 10). Estimated full-cascade generations:
  7.8k → 1.2M → ~78M → … divergent; costlier than plain DFS even for the
  smallest unit.
- **Key insight preserved:** the hardness lives at *face-opening plies*
  (low constraint), not deep. Probe-sampled frontiers had hidden this
  (probe bias oversamples narrow branches; the uniform frontier is much
  harder). **Still holds?** The pilot is rerunnable in minutes against any
  stronger CP-SAT model; a model that fixes the depth-8–16 hardness bump
  would revive this strategy. That is the precise gap to attack.

### 3.3 Meet-in-the-middle over the equator
- **Rejected analytically, no compute spent:** splitting into two 80-slot
  halves requires matching not only the 10-edge interface (~11¹⁰ states,
  manageable) but the *tile partition*, C(160,80) ≈ 9×10⁴⁶ possible splits;
  half-enumeration is astronomically larger than the whole-tree estimate. The
  earlier region-hypothesis refutation (CP-SAT proved colors do NOT partition
  by faces) removed the only obvious structure that could have pinned the
  split.
- **Still holds?** Unless a constraint is found that pins ≳70 of the 80 tile
  choices per half, yes.

### 3.4 The UNSAT-proof direction
- **Dropped on priors, not proof:** the puzzle was sold as solvable and the
  three sibling challenges (silver/red/blue) all verified solvable against
  Jaap's published counts. The observed "zero FEASIBLE in ~75k oracle calls"
  is *weak* evidence for UNSAT, those verdicts cover ~0.01% of the space and
  dead partial boards dominate any solvable instance too.
- **Still holds?** This is a judgment call, not a measurement. A successor
  who believes UNSAT should run massive parallel CP-SAT, nothing I did
  refutes that path; I only priced it (uncertain odds, five-figure bill).

---

## 4. High-score dead ends: Category A (perfect partial, record 142)

### 4.1 Tabu / extraction route to partials
- Warm tabu on the mismatch objective, then vertex-cover extraction: best 134
  tiles, worse than direct methods. Mismatch count is a poor proxy for
  max-placement.

### 4.2 Everything that tried to beat 142
The 142 board's structure (verified by `analyze_partial.py`): 18 isolated
holes, each fully surrounded, **zero free tiles fit any hole** ("all dead"),
17/18 in the bottom pyramid. Attempts, in order:
- **Focused bottom-pyramid repair + path relinking** (RR_FOCUS/RR_GUIDE,
  vs the clique-140 partial): 90 min × 8 cores, nothing.
- **ILS perturbation kicks** (`RR_KICK`): 966 iterations, **120 kicks**, never
  escaped, every kick climbed straight back to exactly 142.
- **Coordinated all-holes repair** (`RR_ALLHOLES=2`): freed **102 of 160
  slots** in one CP-SAT solve (280 s, twice), still 142. ⚠️ Caveat: the
  solves returned FEASIBLE, *not proven optimal*, a longer/parallel solve of
  the same 102-slot model is the one loose end here.
- **Cross-basin evidence:** 5+ independent method families converge at ≤142.
- **Verdict:** 142 is a robust local, very likely global, maximum. **Still
  holds?** The strongest remaining attack is a *proof*: massive parallel
  CP-SAT max-placement to certify 142 optimal (or find 143). Priced but not
  run.

### 4.3 Simulated-annealing acceptance inside ruin-recreate
- Designed, then discarded *before running*: the CP-SAT repair step always
  maximizes over the freed region, so it can never return a worse board,
  SA-style acceptance of worse repairs is structurally impossible without
  changing the repair itself. Kicks (deliberate eviction) were the correct
  replacement. Recorded here because the reasoning error (bolting SA onto a
  monotone repair) is easy to repeat.

---

## 5. High-score dead ends: Category B (matched edges, record 208)

### 5.1 Cold-started anything
- Cold tabu: plateaus at cost 91 (149 matched) in ~100 s, then **zero
  improvement for 800 s** (6 seeds). Cold LNS from the 132-partial jam-board:
  climbed 161→192 then flattened, never threatened the leader.
- **Lesson:** warm-start from the best Category-A board (186 edges free).

### 5.2 Single-move tabu as the engine
- Warm tabu improved 186→190 in 116 iterations (<1 s) then froze for 180 s.
  Instantaneous plateau + huge iteration throughput = move-set limitation,
  not landscape limit, proven by `rr_edges.py` immediately climbing
  190→198→…→208 from the same start.

### 5.3 At the 208 frontier (current, still being probed)
- **52-slot optimal repairs:** ~1,200 subsolves (only 1 timeout), zero gain.
- **Path relinking toward the 192-basin** (`RE_GUIDE`): 3,140 iterations,
  zero gain, notable because the same trick made the historic 138→142 jump
  on Category A. Crossover does *not* automatically transfer across metrics.
- Escalation history for calibration: 44-slot regions broke the 205 desert
  (205→206→208); 52-slot did nothing at 208. Being tested now: 64-slot/120 s
  and kick-restart. If both fail, the local-hardware phase ends at 208.

---

## 6. Measurement fallacies I caught (check yourself against these)

### 6.1 Max-depth-reached is not progress
Deep `max_depth` under weak pruning is usually a long walk inside a *provably
dead* corridor. Concrete case: baseline reached depth 145 on a planted
instance where forward-checking "only" reached 59, because FC refused the
dead corridor the baseline was touring. Consequence: the earlier claim
"random seed shuffles hurt solution-finding (79 vs 145)" is **weakly
grounded**, treat seed-diversity-for-hunting as *open*, not settled.

### 6.2 Probe-sampled frontiers are biased easy
Knuth-probe sampling reaches narrow (constrained) branches disproportionately.
The shallow-refutation strategy looked great on probe samples (100% kill @12)
and collapsed on the uniform frontier (22% kill @8). Always validate against
an exact frontier slice.

### 6.3 CP-SAT multi-worker enumeration silently drops solutions
`enumerate_all_solutions` with >1 worker returned varying subsets across runs
(caused a phantom solution count during silver validation). All enumeration
must use `num_search_workers=1`. Optimization (single-solution/objective) runs
are fine multi-worker.

### 6.4 Batch completion time ≠ item completion time
Two production stalls came from this: (a) un-capped batches let one
billion-node "monster" prefix freeze a whole batch for days; (b) after
per-item caps were added, 300-item batches still made *banking* unbounded.
Fix: cap per-item work AND keep batches small (`PREFIX_NODE_CAP`, batch=10).

### 6.5 Eyeballing beats solution-fitting: twice it didn't
During data verification, hand-corrections of tile readings were twice
overruled by ground-truth min-edit fits against Jaap's published solutions
(tiles 11/17, the 86/98 inversion). Method: fix the known arrangement, let
CP-SAT find the minimum set of data edits explaining it, intersect across two
independent solutions. Trust the fits.

---

## 7. Not rejected: simply never tried (the open shelf)

These carry *no* negative evidence; they were deprioritized on expected
value. Fair game for successors:

1. **Kissat/compact CNF retry** (§1.1), the SAT rejection is the weakest one
   in this document.
2. **Non-rarity fill-order tiebreaks**, 1-ply lookahead (actual candidate
   count given current board), graph centrality, boundary-length
   minimization.
3. **Piece-based search** (pick tile, choose slot), different architecture;
   rigidity ordering would become meaningful there. Expected worse branching,
   never measured.
4. **Precomputed 2/3-tile "super-tile" tables ranked by joint placeability** , 
   plausible but predicted-null (single-tile version was subsumed by MRV);
   cheap to measure with the exhaustive-count harness.
5. **Loop-aware CP-SAT (lazy subtour elimination)**, cuts that forbid
   sub-loops in the oracle/maxsat models. Never needed (zero FEASIBLE
   verdicts to date) but becomes decisive the moment feasible completions
   appear; also the missing ingredient in a 142-optimality proof that
   accounts for the loop rule.
6. **A CP-SAT model tuned for the face-opening hardness bump** (§3.2), the
   one discovery that would revive shallow refutation, which remains the only
   known path to full exhaustion below 10¹⁶ nodes.
7. **Cloud-scale basin portfolio for Category B**, dozens of parallel
   `rr_edges.py` lineages + periodic relinking. The local evidence (each
   basin plateaus individually; fresh basins climb fast) neither proves nor
   refutes that breadth beats depth here; it is the natural next experiment
   if the project continues.

---

*Much of this document, and the code it describes, was produced with the assistance of Claude AI models (Anthropic), under human direction and review.*
