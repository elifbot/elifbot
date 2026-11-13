#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=.
if [[ ! -f .env ]]; then cp .env.example .env; fi
mkdir -p reports
python -m phoenix.live --paper --require-mainnet-data --duration 1800 --poll 15 --max-cycle-sec 180 --report reports/v22_paper_30min.json --score-log reports/v22_paper_30min_scores.jsonl
python tools/read_report.py reports/v22_paper_30min.json
