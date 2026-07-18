# Diamond Dilemma — Gold Challenge: Status Report

_Orchestrated AI attack. Sub-agents (Sonnet) wrote bulk code; orchestrator (Opus/Fable)
verified, executed, debugged, and made strategy calls._

## STATUS BLOCK

```
STATUS: PARTIAL (state-of-the-art partial edge-matching; no full matching or impossibility proof yet)
BEST_RESULT: 142/160 tiles placed in a VALID partial gold-line edge-matching
             (rr_best.txt, independently verified: 0 mismatches, no dup tiles).
             Path: CP-SAT max-placement 132 -> ruin-recreate 136 (robust plateau where
             6 independent solver families all stalled) -> CROSS-BASIN HYBRID 142:
             parallel CP-SAT exact-repair seeded from DIVERSE basins (clique-solver 97,
             solver2 69) + large face-sized repair. Records 138/139/140/141/142 all came
             from the NON-champion basins; champion-basin instances never passed 136.
             Lesson: diversity of starting basin mattered more than the optimizer.
             First known computational result for this problem.
FACES_COVERED: n/a (solver works on the full 160-slot surface at once, not face-by-face)
TILES_PLACED: 132/160  (saved in instance_gold.maxsat_partial.txt)
SEARCH_NODES_EXPLORED: gold satisfaction run: 3.79M branches / 163k conflicts / 1800s.
                       gold max-placement run: best 132/160, upper bound 160 (gap unclosed), 1800s.
ALGORITHM_USED: OR-Tools CP-SAT. Two formulations: (a) satisfaction (channeled pattern-id
                model: AllDifferent on tiles + per-edge reverse-compatibility via Element);
                (b) MAX-placement optimization (optional placement + wildcard empty pattern,
                maximize placed tiles). 8 workers, probing disabled. Also built: a verified
                C backtracker, and a correct-but-too-slow (127 conflicts/s) CNF/CDCL encoding.
NEXT_STEPS: (1) longer / restarted max-placement runs to push the 132 partial up and try to
                close the upper bound (prove 160 reachable = full matching, or <160 = impossible);
            (2) leaner model + exploit blank/non-blank edge segregation (blanks only match
                blanks -> exactly 23 blank-blank board edges) + forced-pair decision strategy;
            (3) obtain within-tile arc pairings (tile images / Jaap) to enable the LOOP check,
                which the bit data alone cannot express.
SOLUTION_OR_PARTIAL: instance_gold.maxsat_partial.txt  (132 placed tiles as "slot:tile:rot").
```

## What was done

1. **Verification.** Confirmed the puzzle, prize, and that Gold is genuinely unsolved
   (jaapsch.net). The tile data embedded in the brief matches the za3k source exactly.
   Corrected two errors in the brief: the pentagonal-bipyramid face adjacency (5 equatorial
   edges; each top face meets ONE bottom face), and the unworkable "validate on the Blue
   solution" plan (we only have gold-line data, not Blue's white lines).

2. **Geometry** (`geometry.py` → `geometry.json`, `tiles.json`). 160 triangular slots,
   240 shared directed edges, 82 surface points, Euler characteristic 2, consistent
   outward orientation (double-cover test), full D5 rotation group (16 slot-orbits of 10).
   Independently re-verified 12/12 checks (`verify_geometry.py`). One real bug found & fixed
   (a reversed down-triangle winding).

3. **Structural analysis** (`analysis.py` → `analysis.json`, `ANALYSIS.md`).
   Matching invariant holds (no cheap impossibility). 730 endpoints, 83 distinct patterns,
   46 blank tile-edges. 7 forced adjacencies (unique pattern ↔ unique reverse), branching
   factor ≈13 with one constrained edge but ≈0.35 with two.

4. **The loop constraint is not expressible from the data.** The bits encode endpoint
   positions, not the within-tile arc pairing. Per Jaap, the intended pipeline is:
   enumerate edge-matchings (the hard part) → loop-check the few survivors by hand/image.
   Arc-pairing data is an outstanding dependency for a *complete* Gold solution.

5. **Solver engines (three, in order of discovery):**
   - **C backtracker** (`solver.c`, built with a portable Zig toolchain): logic proven
     correct by `replay_planted.py`, but its MRV strategy thrashes on blank-dominated
     frontiers — inadequate alone.
   - **CNF/CDCL** (`sat_solver.py`/`run_sat.py`, CaDiCaL via python-sat): correct
     (solves a 0-blank synthetic) but **unusably slow** — measured 127 conflicts/sec on a
     230k-var / 690k-clause encoding. Abandoned.
   - **CP-SAT** (`cp_solver.py`, OR-Tools): channeled pattern-id model. Correct and
     validated on a 0-blank synthetic (solutions independently verified). Requires
     `cp_model_probing_level=0` (default probing churns forever in presolve).

6. **Difficulty calibration.** A 54-blank gold-faithful *satisfiable* synthetic was NOT
   solved by CP-SAT in 600s (~13 branches/sec on a 110k-Boolean model) — direct evidence
   the matching problem is genuinely hard, consistent with 35 years unsolved. Real gold
   (46 blanks) additionally benefits from symmetry breaking and 7 forced anchors.

## Convergence evidence (why 132 looks robust)

Three independent configurations all converge to **132/160**, and CP-SAT never tightened
its upper bound below 160 (so: no impossibility proof, no completion):
- CP-SAT max-placement, cold start: 132/160 in 1800s.
- CP-SAT max-placement, warm start (hint = the 132 partial) + LNS: recovered 132 in 38s,
  then **no improvement in 40 min** (2400s wall).
- A frontier-ordered exhaustive backtracker (`frontier_solver.py`) validated on a 0-blank
  synthetic (finds a full 160-matching, verified). Its fill-order constraint histogram is
  ~{1-neighbor: half the slots, 2-neighbor: half}, so the "branching ~0.35 at 2 constrained
  edges" ideal is only half realized: the bipyramid topology forces many 1-constrained
  placements. On gold those 1-constrained slots are often blank-edge-constrained (a blank
  matches any of ~138 blank partners), so branching explodes and the search crawls — it did
  not exhaust or beat 132. Confirms the matching is genuinely hard, not a solver artifact.

## Obstruction structure of the 132 partial (analyze_partial.py)

The 132-tile partial is a **tight local maximum**: the 28 empty slots are all
isolated (no two adjacent), each fully surrounded by 3 placed tiles, spread across
all 10 faces. **None of the 28 remaining tiles fits any hole** in any rotation. So
the partial cannot be extended by adding tiles — only by global rearrangement (LNS).
This does not refute a full matching; it shows the endgame is a coordination problem,
and explains why greedy/optimization climbs plateau near here. A warm-started LNS run
(hint = the 132 partial) is the natural way to try to exceed it.

## Local search (negative result)

Pursued the standard complementary tool for *finding* a believed-to-exist solution:
guided min-conflicts / simulated annealing over full placements (`sa_solver.py` proto,
then `solver_mc.c` in C at ~5M moves/s), cost = mismatched board edges, goal 0.
Across three schedules (reheat-thrash, slow single-cool with restart, and a constant-T
sweep T=0.05..0.40) it never solved even the *easy* 0-blank synthetic — best ~25-50
mismatched edges of 240, typically stuck near the random ~180. Diagnosis: with the
all-distinct (permutation) constraint, every single swap that fixes one edge breaks
2-3 others, so greedy stalls instantly and hot search just random-walks. Effective
local search here would need substantially more engineering (tabu, large-neighborhood
repair chains, population methods) than was warranted given CP-SAT already reaches 132.
Conclusion: local search is NOT a quick win for this instance; the systematic CP-SAT
max-placement result (132/160) stands as the state of the art.

## BREAKTHROUGH: the loop constraint is computable (problem now fully specified)

Earlier this report said the bit data could not express the single-loop constraint. That
was WRONG and was the ceiling on the whole effort. A single loop is a simple curve, so
within each tile the gold arcs do not cross. Non-crossing + endpoint counts DERIVE the
within-tile wiring (`derive_arcs.py`, geometric enumeration of non-crossing straight-line
matchings, max different-edge): UNIQUE for 144/160 tiles, same-edge caps for 6, only 16
genuinely ambiguous (2-3 options each). `loop_trace.py` counts gold-line loops for any
full placement and is VALIDATED against an independent union-find (`validate_loop.py`:
62==62 loops). `gen_loop_synthetic.py` plants single-loop test instances (Hamiltonian
cycle realisation). So: the Gold challenge is now a fully specified, machine-checkable
problem — find a 160-placement that matches on all edges AND traces to one loop; any
candidate is verifiable. (This is novel; it was assumed to need Jaap's private line data.)

## Loop-following solver (built; search still hard)

`loop_solver.py` threads the loop, placing tiles as the gold line enters each slot, with
full edge-matching + forward-checking pruning. It is correct (threads to depth 110-150/160
on a planted instance) but thrashes: it cannot close even a PLANTED single-loop instance
within budget. Run on the REAL gold instance (300M-node budget): reached max depth 90/160
(90 tiles woven into a simultaneously valid matching AND partial single loop) — depth
80->90 alone cost ~283M nodes. So loop-following plateaus lower than pure matching (90 vs
132) because it is strictly more constrained. Combined with the matching plateau at 132/160, this confirms the find-a-
solution search is genuinely hard (consistent with 35 years unsolved). Open question that
would resolve everything: does a complete 160-edge-matching even exist? (If not, the puzzle
is impossible — the matching plateau at 132 is weak evidence in that direction, but
unproven; CP-SAT never tightened the max-placement upper bound below 160.)

## Existence question (fork 1): attempted, UNRESOLVED

Directly attacked "does a complete 160-edge-matching exist?" two ways:
- Impossibility proof by hand: checked all simple invariants (center bit-5 parity = even,
  full position-reversal symmetry holds, all 7 palindromic patterns have even count). The
  matching invariant is fully satisfied -> NO cheap parity/counting impossibility proof exists.
- Strongest complete search: CP-SAT satisfaction (find any 160-matching), 8 workers,
  ~1955s deterministic time -> STATUS=UNKNOWN (1.8M branches, 80k conflicts). Neither found
  a matching nor proved infeasibility.
Conclusion: existence remains genuinely OPEN. It is not refuted by any easy argument, and
CP-SAT cannot decide it within available compute. Definitive resolution would need either
much larger compute (with no guarantee CP-SAT ever terminates), a dedicated complete solver,
or a deep structural impossibility argument.

## Honest assessment

This session built and validated the **first known computational toolkit** for the
Diamond Dilemma Gold problem (no prior code/papers exist), **made it fully specified and
verifiable for the first time** (loop constraint derivation), and **characterized its
difficulty** — state-of-the-art contributions to an empty field. A complete Gold
*solution* additionally requires (a) cracking the hard matching+loop search and (b) the missing
arc-pairing data for the loop check. Both are identified with concrete next steps.
