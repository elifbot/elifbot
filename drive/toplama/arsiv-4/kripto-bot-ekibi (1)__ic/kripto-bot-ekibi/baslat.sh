#!/usr/bin/env bash
# KriptoBot Panel başlatıcı (macOS / Linux)
cd "$(dirname "$0")"

echo "============================================"
echo "  KriptoBot Panel başlatılıyor..."
echo "  (Kapatmak için Ctrl+C)"
echo "============================================"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[HATA] Python 3 bulunamadı! python.org adresinden kurun."
  exit 1
fi

if [ ! -f ".kuruldu" ]; then
  echo "[KURULUM] Gerekli paketler kuruluyor... (ilk çalıştırmada bir kere)"
  python3 -m pip install --upgrade pip
  python3 -m pip install -r requirements.txt || { echo "[HATA] Kurulum başarısız"; exit 1; }
  echo OK > .kuruldu
fi

python3 panel.py
