#!/usr/bin/env bash
# Runner token'ını gizli okur; hiçbir dosyaya veya komut geçmişine yazmaz.
set -euo pipefail

REPO_URL="https://github.com/omeracar56/kripto-bot"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
STATUS_FILE="$HOME/exchange-preflight.txt"

if [[ ! -x "$RUNNER_DIR/config.sh" ]]; then
    echo "Runner paketi hazır değil; önce: bash .devcontainer/prepare-runner.sh"
    exit 1
fi
if ! grep -q '^RESULT: PASS$' "$STATUS_FILE" 2>/dev/null; then
    echo "İki-borsa ön-kontrolü başarısız veya eksik; runner yapılandırılmadı."
    exit 1
fi

cd "$RUNNER_DIR"
if [[ ! -f .runner ]]; then
    token=""
    trap 'unset token' EXIT
    read -r -s -p "GitHub runner registration token (gizli): " token
    echo
    if [[ -z "$token" ]]; then
        echo "Token boş olamaz."
        exit 1
    fi
    ./config.sh \
        --unattended \
        --replace \
        --url "$REPO_URL" \
        --token "$token" \
        --name "binance-futures-runner" \
        --labels "binance-futures" \
        --work "_work"
    unset token
    trap - EXIT
fi

sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
cat <<'EOF'

Runner yapılandırıldı. GitHub → Settings → Actions → Runners sayfasında
binance-futures-runner = Idle görünmelidir. Artık 120 dakikalık iş başlatılabilir.
EOF
