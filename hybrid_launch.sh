#!/bin/bash
# Hybrid: 4 parallel ruin-recreate instances (2 CP-SAT workers each = 8 cores),
# seeded from DIVERSE basins + large face-sized exact repair. WALL seconds each.
cd /c/Users/xavie/coding/diamond-dilemma
WALL=${1:-5400}
# 1: champion basin, big-neighborhood escape attempts
RR_OUT=hyb_champ.txt  RR_SEED=101 RR_WORKERS=2 RR_BIG=0.25 python ruin_recreate.py rr_best.txt        $WALL 40 > hyb_champ.log 2>&1 &
# 2: clique basin (97 tiles, only 2 slots shared with champion) - different peak?
RR_OUT=hyb_clique.txt RR_SEED=202 RR_WORKERS=2 RR_BIG=0.15 python ruin_recreate.py clique_best.txt    $WALL 40 > hyb_clique.log 2>&1 &
# 3: solver2 basin (69 tiles, 0 slots shared) - totally different region
RR_OUT=hyb_s2.txt     RR_SEED=303 RR_WORKERS=2 RR_BIG=0.15 python ruin_recreate.py best2_partial.txt  $WALL 40 > hyb_s2.log 2>&1 &
# 4: champion basin, small aggressive neighborhoods, different seed
RR_OUT=hyb_champ2.txt RR_SEED=404 RR_WORKERS=2 RR_BIG=0.0  python ruin_recreate.py rr_best.txt        $WALL 30 > hyb_champ2.log 2>&1 &
wait
echo "hybrid portfolio done"
