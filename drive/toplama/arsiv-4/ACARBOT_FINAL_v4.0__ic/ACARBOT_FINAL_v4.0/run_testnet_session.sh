#!/usr/bin/env bash
# ACARBOT v4.0 — 24/48 saatlik testnet oturum başlatıcı (madde 24).
#
# Kullanım:
#   chmod +x run_testnet_session.sh
#   BINANCE_TESTNET_API_KEY=... BINANCE_TESTNET_API_SECRET=... \
#       ./run_testnet_session.sh 1440            # 24 saat
#   ./run_testnet_session.sh 2880 okx            # 48 saat, OKX demo
#
# Süreç nohup ile arka planda çalışır; çıkmak için oturumu kapatabilirsiniz.
# Rapor: session_24h.json / session_48h.json  |  Log: paper_<dk>.log
set -euo pipefail

MINUTES="${1:-1440}"
EXCHANGE="${2:-binance}"
PROFILE_FLAG="${PROFILE:---motors trend}"
REPORT="session_${MINUTES}h.json"
LOG="paper_${MINUTES}.log"

if [ "$EXCHANGE" = "okx" ]; then
  : "${OKX_DEMO_API_KEY:?OKX_DEMO_API_KEY gerekli}"
  : "${OKX_DEMO_API_SECRET:?OKX_DEMO_API_SECRET gerekli}"
  : "${OKX_API_PASSPHRASE:?OKX_API_PASSPHRASE gerekli}"
else
  : "${BINANCE_TESTNET_API_KEY:?BINANCE_TESTNET_API_KEY gerekli}"
  : "${BINANCE_TESTNET_API_SECRET:?BINANCE_TESTNET_API_SECRET gerekli}"
fi

python3 -m pytest tests/ -q

nohup python3 -m app.main --mode paper --paper \
  --live-testnet --live-exchange "$EXCHANGE" \
  --scan-all $PROFILE_FLAG \
  --live-entry-style post_only_market_fallback \
  --duration-minutes "$MINUTES" \
  --report-file "$REPORT" > "$LOG" 2>&1 &

PID=$!
echo "$PID" > "paper_${MINUTES}.pid"
echo "Oturum başladı: PID=$PID süre=${MINUTES}dk borsa=$EXCHANGE"
echo "İzleme:  tail -f $LOG"
echo "Durdurma: kill \$(cat paper_${MINUTES}.pid)"
echo "Acil durum: python3 -m app.main --emergency-flatten --live-testnet --live-exchange $EXCHANGE"
