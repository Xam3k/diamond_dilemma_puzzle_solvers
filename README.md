# Diamond Dilemma — solvers, records, and negative results

An attempt on the **gold challenge of the Diamond Dilemma** (Alan Fraser-Dackers,
G J Hayter Ltd, 1988): place 160 triangular tiles on a pentagonal bipyramid
(10 faces × 16 slots, 240 internal edges) so that the gold lines crossing every
edge match **and form one single closed loop**. A prize puzzle from 1988 —
to our knowledge **never solved by anyone**. It still isn't. This repository
documents how far we got, how, and everything that didn't work, so the next
attempt can start where we stopped.

## Results

| Category | Best known | File | Visualization |
|---|---|---|---|
| **A** — most tiles placed with *every* touching edge matched | **142 / 160** (186/240 edges, zero mismatches) | `rr_best.txt` | `record_A_142.svg` |
| **B** — most matched edges with *all 160* tiles placed (Eternity-II-style score) | **208 / 240** | `edges_208_checkpoint.txt` | `record_B_208.svg` |
| Full gold solution (160 tiles + single loop) | **open** | — | — |

Open `records_view.html` for both boards with commentary. Every score is
re-verifiable in one command: `python score_board.py <board.txt>`.

Supporting measurements worth knowing before you start:
- The fully-pruned exhaustive search tree is **T ≈ 3×10¹⁶ nodes** (Knuth-probe
  estimate, validated to 4% on truncated trees) — ~320 core-years at our
  3M nodes/s/core. Exhaustion is an institutional-compute project, not a
  desktop one.
- Category A's 142 sits in a basin where **all 18 holes are provably dead**
  (no remaining tile fits any hole); it survived 120 perturbation kicks and a
  102-slot coordinated CP-SAT re-solve.
- Category B's 208 survived ~1,600 provably-optimal 52–64-tile
  rearrangements, cross-basin path-relinking, and ten degrade-reclimb
  restarts.

## Why you can trust the data

The tile digitisation and matching conventions were validated **end-to-end
against ground truth**: using the same pipeline, we solved the puzzle's three
published side-challenges (silver / red / blue, white lines) and reproduced
Jaap Scherphuis's published solution counts **exactly** (2 / 1 / 1), with every
solution forming the required single white loop. The ~15 digitisation errors
found along the way were located by CP-SAT min-edit fitting against known
solutions and corrected after human re-verification of the physical tiles.

## The two documents to read

- **[SOLVERS.md](SOLVERS.md)** — code-level tour of every solver: the
  exhaustive DFS engine (`solver3.c`) with its seven pruning layers, CP-SAT
  oracle sidecar, crash-resilient work decomposition, and tree-size
  estimator; and the high-score optimizers (`ruin_recreate.py`,
  `rr_edges.py`, `tabu_solver.c`, `cp_maxsat.py`).
- **[NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md)** — everything we tried that
  failed, the exact measurement that killed each idea, whether the rejection
  still holds, and the shelf of untried ideas. **Read this before re-trying
  anything** — and re-run our measurements before trusting them on your
  hardware.

## Quick start

```sh
# score any board file (both categories, independent verifier)
python score_board.py rr_best.txt

# render a board on the unfolded bipyramid net
python gen_viz.py rr_best.txt my_board.svg

# improve the Category-B record (CP-SAT large-neighbourhood search)
python rr_edges.py edges_208_checkpoint.txt 3600 15

# improve the Category-A record (ruin-and-recreate with kicks)
python ruin_recreate.py rr_best.txt 3600 8

# exhaustive engine (compile with zig or gcc; see SOLVERS.md §1 for env flags)
zig cc -O3 -o solver3.exe solver3.c
FORCED_PAIRS=1 NEIGHBOR_FC=1 ROOT_UNIT=14 ./solver3.exe instance_gold.txt 0 0
```

Python deps: `ortools` (CP-SAT). C engine: any C99 compiler; `solver3_linux`
is a prebuilt znver4 ELF.

## Repository map

| | |
|---|---|
| Data (verified) | `diamonddilemma.txt` (gold, Jaap's), `tiles.json`, `geometry.json`, `arcs.json`/`arcs_flat.txt`, `whites.txt`, `white_arcs.json`, `verify_*.txt` (human verification sheets) |
| Exhaustive engine | `solver3.c`, `oracle_sidecar.py`, `run_hybrid.py`, `frontier_ledger.py`, `ledger_run.py` |
| High-score solvers | `rr_edges.py` (B champion), `ruin_recreate.py` (A champion), `tabu_solver.c`, `cp_maxsat.py`, `kick_cycle.sh` |
| Verification & analysis | `score_board.py`, `analyze_partial.py`, `check_verified.py`, `check_white_full.py`, `loop_trace.py`, white-challenge solvers `cp_white_*.py`, min-edit fitters `*_edit.py` |
| Visualization | `gen_viz.py`, `render_records.py`, `records_view.html`, `solutions_view.html` (silver/red/blue gallery) |
| Records & artifacts | `rr_best.txt`, `edges_208_checkpoint.txt`, `est_result.txt` (tree-size estimate), `frontier_ledger.txt` (banked exhaustive coverage) |

## Acknowledgments

**[Jaap Scherphuis](https://www.jaapsch.net/puzzles/)** made this project
possible: the gold tile data, the puzzle's history, and the published
silver/red/blue solutions we validated our entire pipeline against all come
from his puzzle pages. Thank you, Jaap.

The heuristic playbook owes a debt to the **Eternity II** solver community,
whose public write-ups shaped the supply/demand pruning, the tabu baseline,
and the expectation that matched-edge scores climb with solver quality —
which they did here too, until they didn't (see NEGATIVE_RESULTS.md §5).

## Status

Actively concluded (2026). The gold challenge remains open: 142/160 perfect,
208/240 with mismatches, full solution unknown — possibly waiting for a
structural insight, possibly for ~320 core-years, possibly for you.
