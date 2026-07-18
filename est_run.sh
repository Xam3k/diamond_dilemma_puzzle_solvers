#!/bin/sh
# est_run.sh -- production Knuth tree-size estimate for all 48 root units.
# Engine flags mirror the sweep (FORCED_PAIRS=1; oracle NOT modelled, so the
# result upper-bounds the hybrid engine's node count). Single process,
# sequential units (one core), safe to run beside the sweep.
cd /c/Users/xavie/coding/diamond-dilemma || exit 1
FORCED_PAIRS=1 ESTIMATE=${1:-500000} ESTIMATE_SEED=${2:-1} \
    ./solver3_est.exe instance_gold.txt 0 0 2>&1 \
    | grep -E "EST unit|EST GRAND|ESTIMATE ON|FORCED_PAIRS" > est_result.txt
echo "EST_ALLDONE" >> est_result.txt
