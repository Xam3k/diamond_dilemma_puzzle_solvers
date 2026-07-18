#!/bin/bash
# Round 2: targeted + path-relinking + cross-basin, all via CP-SAT exact repair.
cd /c/Users/xavie/coding/diamond-dilemma
WALL=${1:-5400}
# 1 & 2: TARGETED bottom-pyramid repair (bottleneck = B faces) from the 142 record
RR_OUT=r2_bot.txt   RR_SEED=11 RR_WORKERS=2 RR_BIG=0.5 RR_FOCUS=B0,B1,B2,B3,B4 python ruin_recreate.py rr_best.txt $WALL 50 > r2_bot.log 2>&1 &
RR_OUT=r2_bot2.txt  RR_SEED=12 RR_WORKERS=2 RR_BIG=0.6 RR_FOCUS=B2,B3,B4         python ruin_recreate.py rr_best.txt $WALL 50 > r2_bot2.log 2>&1 &
# 3: PATH RELINKING - start from clique basin (140), guided toward the 142 record
RR_OUT=r2_relink.txt RR_SEED=21 RR_WORKERS=2 RR_BIG=0.1 RR_GUIDE=rr_best.txt      python ruin_recreate.py hyb_clique.txt $WALL 45 > r2_relink.log 2>&1 &
# 4: CROSS-BASIN continue - clique seed, big general repair, fresh stream
RR_OUT=r2_cross.txt  RR_SEED=31 RR_WORKERS=2 RR_BIG=0.3                            python ruin_recreate.py hyb_clique.txt $WALL 45 > r2_cross.log 2>&1 &
wait
echo "round 2 done"
