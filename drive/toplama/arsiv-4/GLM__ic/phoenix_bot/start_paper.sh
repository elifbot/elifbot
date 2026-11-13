#!/usr/bin/env bash
# Phoenix Bot v2 — paralel paper test başlatıcı (Linux/Mac)
# Üç zaman dilimi + anahtarsız sinyal tarayıcı aynı anda çalışır.
cd "$(dirname "$0")"
python main.py trade --timeframe 15m &
python main.py trade --timeframe 30m &
python main.py trade --timeframe 1h &
python main.py scan --watch &
wait
