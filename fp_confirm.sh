#!/bin/bash
cd /c/Users/xavie/coding/diamond-dilemma
for seed in 8 9; do
  rm -rf oracle_dir; pkill -f oracle_sidecar 2>/dev/null
  FORCED_PAIRS=0 timeout 700 python run_hybrid.py instance_gold.txt 0 $seed 4000000 600 >/dev/null 2>&1
  cp hybrid_solver.log fpc_off_$seed.log
  rm -rf oracle_dir; pkill -f oracle_sidecar 2>/dev/null
  FORCED_PAIRS=1 timeout 700 python run_hybrid.py instance_gold.txt 0 $seed 4000000 600 >/dev/null 2>&1
  cp hybrid_solver.log fpc_on_$seed.log
done
for seed in 8 9; do
  echo "seed $seed OFF: $(grep -aoE 'pfx=[0-9.]+' fpc_off_$seed.log | tail -1)" >> fp_confirm_result.txt
  echo "seed $seed ON : $(grep -aoE 'pfx=[0-9.]+' fpc_on_$seed.log | tail -1)" >> fp_confirm_result.txt
done
echo ALLDONE >> fp_confirm_result.txt
