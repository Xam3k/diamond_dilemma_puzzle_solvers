#!/bin/sh
# kick_cycle.sh -- endless degrade-reclimb lottery on the B-metric record.
# Each cycle: kick the 208 record board (random pair-swaps), re-climb with
# LNS for a bounded window, keep any board that BEATS the record (rr_edges
# only overwrites RE_OUT on improvement over its own start, so we give each
# cycle a fresh output file and compare afterwards).
cd /c/Users/xavie/coding/diamond-dilemma || exit 1
CYCLE=0
while true; do
  CYCLE=$((CYCLE+1))
  SEED=$((100 + CYCLE))
  python3 - "$SEED" <<'EOF'
import json, random, sys
rng = random.Random(int(sys.argv[1]))
cur = {}
for tok in open("edges_208_checkpoint.txt").read().split():
    s,t,r = map(int, tok.split(":")); cur[s]=(t,r)
slots = list(cur.keys())
for _ in range(rng.choice([5, 8, 12])):
    a, b = rng.sample(slots, 2)
    (ta,_),(tb,_) = cur[a], cur[b]
    cur[a]=(tb,rng.randrange(3)); cur[b]=(ta,rng.randrange(3))
open("kick_cycle_start.txt","w").write(" ".join(f"{s}:{cur[s][0]}:{cur[s][1]}" for s in sorted(cur))+"\n")
EOF
  RE_SEED=$SEED RE_MAXF=36 RE_WORKERS=6 RE_OUT=kick_cycle_best.txt \
    RE_A_OUT=rr_bestA_from_kick.txt \
    python rr_edges.py kick_cycle_start.txt 5400 15 > kick_cycle_run.log 2>&1
  BEST=$(python score_board.py kick_cycle_best.txt 2>/dev/null | grep -oE "edges matched *: [0-9]+" | grep -oE "[0-9]+$")
  echo "cycle $CYCLE seed $SEED -> best ${BEST:-none}" >> kick_cycle_history.log
  if [ -n "$BEST" ] && [ "$BEST" -gt 208 ]; then
    cp kick_cycle_best.txt "edges_record_${BEST}.txt"
    echo "*** NEW RECORD $BEST/240 (cycle $CYCLE) -> edges_record_${BEST}.txt ***" >> kick_cycle_history.log
  fi
done
