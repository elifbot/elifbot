#!/usr/bin/env bash
# ACARBOT FINAL v1.8 — 15 dakikalık süreli paper testi (OKX, APEX, TREND)
# İşlem başı 25 USDT hedef net risk + dinamik teminat.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m app.main --mode paper --paper --exchange okx --profile apex --motors trend \
  --symbols BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP,XRP-USDT-SWAP,DOGE-USDT-SWAP,BNB-USDT-SWAP \
  --balance 1000 --duration-minutes 15 \
  --state test15_state.sqlite3 --report-file session_report_15min.json
