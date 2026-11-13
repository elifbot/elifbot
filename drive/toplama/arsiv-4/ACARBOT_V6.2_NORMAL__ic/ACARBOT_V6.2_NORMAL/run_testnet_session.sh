#!/usr/bin/env bash
# ACARBOT v5.6.2 — 24/48 saatlik testnet oturum başlatıcı (madde 24).
#
# Kullanım:
#   chmod +x run_testnet_session.sh
#   BINANCE_TESTNET_API_KEY=... BINANCE_TESTNET_API_SECRET=... \
#       ./run_testnet_session.sh 1440            # 24 saat
#   ./run_testnet_session.sh 2880 okx            # 48 saat, OKX demo
#
# Süreç nohup ile arka planda çalışır; çıkmak için oturumu kapatabilirsiniz.
# Rapor: session_<dk>dk.json (örn. session_1440dk.json)  |  Log: paper_<dk>.log
# Profil: varsayılan kasa1000; geçersiz kılmak için:
#   PROFILE="--profile apex" ./run_testnet_session.sh 1440
set -euo pipefail

MINUTES="${1:-1440}"
EXCHANGE="${2:-binance}"
# Varsayılan: kasa1000 profili (25 USDT zarar tavanı) + TREND motoru.
# Windows karşılığı (run_testnet_session.bat) ile aynı rapor adı düzeni:
PROFILE_FLAG="${PROFILE:---profile kasa1000 --motors trend}"
REPORT="session_${MINUTES}dk.json"
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
