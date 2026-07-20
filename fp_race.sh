#!/bin/bash
cd "$(dirname "$0")"
rm -rf oracle_dir; pkill -f oracle_sidecar 2>/dev/null
FORCED_PAIRS=0 timeout 700 python run_hybrid.py instance_gold.txt 0 5 4000000 600 >/dev/null 2>&1
cp hybrid_solver.log fp_off.log
rm -rf oracle_dir; pkill -f oracle_sidecar 2>/dev/null
FORCED_PAIRS=1 timeout 700 python run_hybrid.py instance_gold.txt 0 5 4000000 600 >/dev/null 2>&1
cp hybrid_solver.log fp_on.log
echo "OFF: $(grep -aoE 'pfx=[0-9.]+' fp_off.log | tail -1)" > fp_race_result.txt
echo "ON : $(grep -aoE 'pfx=[0-9.]+' fp_on.log | tail -1)" >> fp_race_result.txt
grep -aoE "fp_rejections=[0-9]+" fp_on.log | tail -1 >> fp_race_result.txt
# then: ledger unit-0 probe with best-so-far (FP on if it won is decided later; use FP=0 baseline hybrid)
rm -rf oracle_dir; pkill -f oracle_sidecar 2>/dev/null
ROOT_UNIT=0 timeout 2000 python run_hybrid.py instance_gold.txt 0 1 4000000 1800 >/dev/null 2>&1
grep -aE "UNIT 0 (EXHAUSTED|INCOMPLETE)" hybrid_solver.log >> fp_race_result.txt
echo ALLDONE >> fp_race_result.txt
