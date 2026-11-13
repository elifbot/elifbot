#!/usr/bin/env bash
# KRIPTO-BOT v7.8 — tek komut kurulum (Ubuntu 22.04/24.04, Debian 12)
# Kullanim: sudo bash deploy/kur.sh /tmp/KRIPTO-BOT-v7.8-MAIL-PAKETI.zip
set -euo pipefail

ZIP="${1:-}"
HEDEF="/opt/kripto-bot"
KULLANICI="kriptobot"

[ -f "$ZIP" ] || { echo "Kullanim: sudo bash deploy/kur.sh <ZIP-yolu>"; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "Root olarak calistirin (sudo)."; exit 1; }

echo "==> 1/7 Sistem paketleri"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip unzip curl >/dev/null

echo "==> 2/7 Servis kullanicisi: $KULLANICI"
id -u "$KULLANICI" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$KULLANICI"

echo "==> 3/7 Proje dosyalari -> $HEDEF"
mkdir -p "$HEDEF"
TMPD="$(mktemp -d)"
unzip -q "$ZIP" -d "$TMPD"
SRC="$(find "$TMPD" -maxdepth 2 -type d -name 'kripto-bot-v7*' | head -1)"
[ -n "$SRC" ] || { echo "ZIP icinde kripto-bot-v7.x klasoru bulunamadi"; exit 1; }
rm -rf "$HEDEF/kripto-bot-v7.8"
cp -r "$SRC" "$HEDEF/kripto-bot-v7.8"
mkdir -p "$HEDEF/deploy" && cp -r "$(dirname "$0")"/. "$HEDEF/deploy/" 2>/dev/null || true

echo "==> 4/7 Python ortami"
python3 -m venv "$HEDEF/.venv"
"$HEDEF/.venv/bin/pip" install -q -U pip
"$HEDEF/.venv/bin/pip" install -q -r "$HEDEF/kripto-bot-v7.8/requirements.txt"

echo "==> 5/7 .env"
ENV_DOSYA="$HEDEF/kripto-bot-v7.8/.env"
if [ ! -f "$ENV_DOSYA" ]; then
  cp "$HEDEF/kripto-bot-v7.8/.env.ornek" "$ENV_DOSYA"
  TOKEN="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
  sed -i "s|^DASHBOARD_TOKEN=.*|DASHBOARD_TOKEN=${TOKEN}|" "$ENV_DOSYA"
  echo "    .env olusturuldu (MODE=paper). DASHBOARD_TOKEN: ${TOKEN}"
else
  echo "    .env zaten var, dokunulmadi."
fi

chown -R "$KULLANICI:$KULLANICI" "$HEDEF"
chmod 600 "$ENV_DOSYA"

echo "==> 6/7 Dogrulama testleri (paper, cevrimdisi)"
sudo -u "$KULLANICI" "$HEDEF/.venv/bin/python" -m pytest -q "$HEDEF/kripto-bot-v7.8/tests" || \
  echo "    UYARI: testler gecmedi, loglari inceleyin."

echo "==> 7/7 systemd servisleri"
cp "$HEDEF/kripto-bot-v7.8/deploy/kripto-bot.service" /etc/systemd/system/ 2>/dev/null || \
  cp "$(dirname "$0")/kripto-bot.service" /etc/systemd/system/
cp "$HEDEF/kripto-bot-v7.8/deploy/kripto-panel.service" /etc/systemd/system/ 2>/dev/null || \
  cp "$(dirname "$0")/kripto-panel.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now kripto-bot.service
systemctl enable --now kripto-panel.service

IPADDR="$(hostname -I | awk '{print $1}')"
cat <<EOF

✅ Kurulum tamam.
   Panel      : http://${IPADDR}:8501
   Saglik     : http://${IPADDR}:8502/health
   Metrikler  : http://${IPADDR}:8502/metrics
   Log        : journalctl -u kripto-bot -f
   .env       : $ENV_DOSYA  (MODE=paper ile basladi)
   Testnet    : .env icinde MODE=testnet + API anahtarlari, sonra: systemctl restart kripto-bot
   Canli      : MODE=live + LIVE_TRADING_CONFIRM=YES_I_RISK_REAL_MONEY

   Firewall onerisi:
     ufw allow 22/tcp
     ufw allow from <kendi-IP> to any port 8501,8502 proto tcp
     ufw enable
EOF
