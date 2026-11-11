#!/bin/sh
# Runs batches 2..13 sequentially: run -> verify. Stops at the first failure (no auto-fix).
cd "$HOME/media-reorg" || exit 1
for n in 2 3 4 5 6 7 8 9 10 11 12 13; do
  echo "===== BATCH $n RUN $(date "+%F %T")"
  python3 reorgdb.py run --batch $n || { echo "STOPPED: batch $n run failed"; exit 1; }
  echo "===== BATCH $n VERIFY $(date "+%F %T")"
  python3 reorgdb.py verify --batch $n || { echo "STOPPED: batch $n verify failed"; exit 2; }
done
echo "ALL BATCHES DONE $(date "+%F %T")"
