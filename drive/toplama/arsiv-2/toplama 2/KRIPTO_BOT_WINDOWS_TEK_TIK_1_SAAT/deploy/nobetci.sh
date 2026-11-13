#!/usr/bin/env bash
# Basit nobetci: /health + surec + veritabani tazeligi kontrolu, sorun varsa Telegram'a alarm.
# Cron: */5 * * * * /opt/kripto-bot/deploy/nobetci.sh
set -uo pipefail
ENV_DOSYA="${ENV_DOSYA:-/opt/kripto-bot/kripto-bot-v7.8/.env}"
HEALTH="${HEALTH:-http://127.0.0.1:8502/health}"
DB="${DB:-/opt/kripto-bot/kripto-bot-v7.8/bot_state.db}"
DURUM_DOSYA="/tmp/kriptobot_son_durum"
DB_ESIK_SN=900          # DB 15 dakikadir yazilmiyorsa sorun
HEALTH_ESIK_SN=600      # health "healthy:false" bu sureden uzun surerse sorun

[ -f "$ENV_DOSYA" ] && set -a && . "$ENV_DOSYA" && set +a

CEVAP="$(curl -s --max-time 10 "$HEALTH" || true)"
DURUM="OK"; NEDEN=""

# 1) Surec ayakta mi?
if ! systemctl is-active --quiet kripto-bot 2>/dev/null; then
  DURUM="SORUN"; NEDEN="kripto-bot servisi aktif degil"
fi

# 2) Veritabani tazeligi (en guvenilir sinyal: bot tick'lerde DB'ye yazar)
if [ -z "$NEDEN" ] && [ -f "$DB" ]; then
  YAS=$(( $(date +%s) - $(stat -c %Y "$DB") ))
  if [ "$YAS" -gt "$DB_ESIK_SN" ]; then
    DURUM="SORUN"; NEDEN="DB ${YAS}sn'dir yazilmiyor"
  fi
fi

# 3) Health bayragi (heartbeat bayatligi tek basina alarm sebebi degil;
#    v7.8'de heartbeat meta'si bazi kosullarda gecikmeli guncelleniyor)
if echo "$CEVAP" | grep -q '"healthy": *false'; then
  if [ -z "$NEDEN" ]; then DURUM="IZLE"; NEDEN="health healthy:false (DB yazimi taze, izlemede)"; fi
fi
if echo "$CEVAP" | grep -q '"circuit_breaker": *{[^}]*"tripped": *true'; then
  DURUM="SORUN"; NEDEN="devre kesici (circuit breaker) atti"
fi

# Yalnizca durum degistiginde mesaj at (spam yok)
ONCEKI="$(cat "$DURUM_DOSYA" 2>/dev/null || echo BILINMIYOR)"
if [ "$DURUM" != "$ONCEKI" ] && [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
  curl -s --max-time 10 -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=🤖 KRIPTO-BOT nobetci: ${DURUM} | $(date '+%Y-%m-%d %H:%M') | ${NEDEN:-saglikli} | ${CEVAP:0:200}" \
    >/dev/null
fi
echo "$DURUM" > "$DURUM_DOSYA"

case "$DURUM" in
  SORUN) echo "[$(date '+%F %T')] SORUN: $NEDEN | $CEVAP"; exit 1 ;;
  IZLE)  echo "[$(date '+%F %T')] IZLE: $NEDEN"; exit 0 ;;
  *)     exit 0 ;;
esac
