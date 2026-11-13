#!/usr/bin/env bash
# 10 min READ_ONLY, then 10 min PAPER. Read the funnel after each step.
set -e
export PYTHONPATH=.
mkdir -p reports
echo "===== STEP 1/2: READ_ONLY (10 min) ====="
python -m phoenix.live --require-mainnet-data --duration 600 --poll 15 --max-cycle-sec 240 --report reports/readonly_10min.json --score-log reports/scores_readonly.jsonl
python tools/read_report.py reports/readonly_10min.json
echo; echo "===== STEP 2/2: PAPER (10 min) ====="
python -m phoenix.live --paper --require-mainnet-data --duration 600 --poll 15 --max-cycle-sec 240 --report reports/paper_10min.json --score-log reports/scores_paper.jsonl
python tools/read_report.py reports/paper_10min.json
