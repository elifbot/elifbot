#!/usr/bin/env bash
# GitHub Codespaces içinde resmî Futures erişimini doğrular ve runner'ı hazırlar.
set -euo pipefail

RUNNER_VERSION="2.338.0"
RUNNER_SHA256="af4b794c1bc41d73d40535e3fe092a39f9679cd8d965954c2aca25a05ca41d32"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
STATUS_FILE="$HOME/exchange-preflight.txt"

probe() {
    local url="$1"
    local output="$2"
    local code
    code=$(curl -sS -L --max-time 30 -o "$output" -w '%{http_code}' "$url" 2>/dev/null) || code="000"
    printf '%s' "$code"
}

echo "== Binance + OKX Futures erişim kontrolü =="
binance_status=$(probe \
    "https://fapi.binance.com/fapi/v1/exchangeInfo" \
    "/tmp/binance-futures-exchange-info.json")
okx_status=$(probe \
    "https://www.okx.com/api/v5/public/instruments?instType=SWAP" \
    "/tmp/okx-swap-instruments.json")

if [[ "$binance_status" == "200" && "$okx_status" == "200" ]]; then
    result="PASS"
else
    result="FAIL"
fi

{
    echo "Codespace: ${CODESPACE_NAME:-unknown}"
    echo "Binance Futures HTTP: $binance_status"
    echo "OKX Swap HTTP: $okx_status"
    echo "RESULT: $result"
} | tee "$STATUS_FILE"

if [[ "$result" != "PASS" ]]; then
    cat <<'EOF'

Bu Codespace bölgesinde iki-borsa erişimi yok. Runner yapılandırılmadı.
Bu Codespace'i silip farklı bir bölge ile yeniden oluşturun; 451 sonucunu
proxy/VPN ile aşmaya çalışmayın. Ayrıntı: ~/exchange-preflight.txt
EOF
    exit 0
fi

mkdir -p "$RUNNER_DIR"
if [[ ! -x "$RUNNER_DIR/config.sh" ]]; then
    archive="/tmp/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
    url="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
    echo "== GitHub Actions Runner v${RUNNER_VERSION} indiriliyor =="
    curl -fL --retry 3 --connect-timeout 20 "$url" -o "$archive"
    echo "${RUNNER_SHA256}  ${archive}" | sha256sum -c -
    tar -xzf "$archive" -C "$RUNNER_DIR"
    rm -f "$archive"
fi

cat <<'EOF'

Hazırlık tamamlandı. Repository kök dizininde şu komutu çalıştırın:
  bash .devcontainer/configure-runner.sh

Script geçici runner token'ını gizli olarak soracak; token komut satırına,
sohbete veya herhangi bir dosyaya yazılmayacak.
EOF
