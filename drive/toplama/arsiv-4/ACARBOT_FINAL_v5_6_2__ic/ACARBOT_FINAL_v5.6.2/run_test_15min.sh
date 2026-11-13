#!/usr/bin/env bash
# ACARBOT v5.6.2 — 15 dakikalık süreli paper testi (OKX, kasa1000 profili)
set -euo pipefail
cd "$(dirname "$0")"
python3 -m app.main --mode paper --paper --exchange okx --profile kasa1000 \
  --symbols BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP,XRP-USDT-SWAP,DOGE-USDT-SWAP,BNB-USDT-SWAP \
  --balance 1000 --duration-minutes 15 \
  --state test15_state.sqlite3 --report-file session_report_15min.json
