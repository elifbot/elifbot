#!/usr/bin/env bash
# ACARBOT - maildeki/drive'daki paketleri yeni GitHub reposuna tasima betigi
#
# Kullanim:
#   bash kur_yeni_repo.sh BOT1.zip BOT2.zip APEX_HYBRID.zip [hedef_klasor]
#
# Ornek:
#   bash kur_yeni_repo.sh ~/Downloads/ACARBOT56_v3.1_Tum_Futures_Bot.zip \
#                         ~/Downloads/ACARBOT_OMEGA_v1.0_Kurumsal_Motor.zip \
#                         ~/Downloads/ACARBOT_APEX_HYBRID_v2.zip
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "Kullanim: bash kur_yeni_repo.sh BOT1.zip BOT2.zip APEX_HYBRID.zip [hedef_klasor]"
  exit 1
fi

BOT1="$1"
BOT2="$2"
APEKS="$3"
HEDEF="${4:-acarbot56_yeni}"

for dosya in "$BOT1" "$BOT2" "$APEKS"; do
  if [ ! -f "$dosya" ]; then
    echo "HATA: dosya yok -> $dosya"
    exit 1
  fi
done

command -v unzip >/dev/null 2>&1 || { echo "HATA: unzip kurulu degil"; exit 1; }
command -v git   >/dev/null 2>&1 || { echo "HATA: git kurulu degil";   exit 1; }

rm -rf "$HEDEF"
mkdir -p "$HEDEF"

echo "== 1/6  BOT 1 aciliyor (turbo_engine)"
unzip -q -o "$BOT1" -d "$HEDEF"

echo "== 2/6  BOT 2 aciliyor (omega)"
unzip -q -o "$BOT2" -d "$HEDEF"

echo "== 3/6  BOT 3 + BOT 4 aciliyor (APEX / HYBRID v2)"
unzip -q -o "$APEKS" -d "$HEDEF"

echo "== 4/6  .gitignore yaziliyor"
cat > "$HEDEF/.gitignore" <<'GITIGNORE'
__pycache__/
*.py[cod]
.venv/
venv/
.env
.env.*
*.key
*.pem
*secret*
*token*
toplama*/
*.sqlite3
*.db
durum*.json
*_durum.json
*.jsonl
GITIGNORE

echo "== 5/6  API anahtari / sizinti taramasi"
SIZINTI=$(grep -rIl --exclude-dir=.git --exclude-dir=__pycache__ \
  -E "(api[_-]?key|secret|passphrase)[\"']?[[:space:]]*[:=][[:space:]]*[\"'][A-Za-z0-9/+]{16,}" \
  "$HEDEF" 2>/dev/null || true)

if [ -n "$SIZINTI" ]; then
  echo ""
  echo "!!! DUR: su dosyalarda API anahtari gibi gorunen degerler var:"
  echo "$SIZINTI"
  echo ""
  echo "Once bunlari temizle (sil veya bosalt), sonra betigi tekrar kos."
  exit 2
fi
echo "    temiz"

echo "== 6/6  git deposu kuruluyor"
cd "$HEDEF"
if [ -d .git ]; then rm -rf .git; fi
git init -q
git checkout -q -b main 2>/dev/null || true
git add -A
git -c user.name="acarbot56" -c user.email="acarbot56@gmail.com" \
    commit -qm "ACARBOT: BOT1 TURBO + BOT2 OMEGA + BOT3 HYBRID v2 + BOT4 APEX"

echo ""
echo "--- repo icerigi ---"
for f in turbo_engine.py akilli_filtre.py omega_bot.py cekirdek.py apex_bot.py hybrid_bot.py test_4bot.py; do
  if [ -f "$f" ]; then echo "  OK   $f"; else echo "  YOK  $f"; fi
done
if [ -d acarbot_omega ]; then echo "  OK   acarbot_omega/"; else echo "  YOK  acarbot_omega/"; fi
echo ""
echo "commit: $(git rev-parse --short HEAD)"
echo "takip edilen dosya: $(git ls-files | wc -l | tr -d ' ')"
echo ""
echo "--- GitHub'a gonder ---"
echo "A) gh kurulu ve girisli ise (en kolay):"
echo "   gh repo create acarbot56 --private --source=. --remote=origin --push"
echo ""
echo "B) elle:"
echo "   git remote add origin https://github.com/KULLANICI/acarbot56.git"
echo "   git push -u origin main"
echo ""
echo "Not: push sirasinda sifre sorulursa GitHub sifresi DEGIL, Personal Access Token kullan."
