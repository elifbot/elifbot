# ACARBOT V22

CCXT destekli USDT-settled Futures borsaları için sinyal, risk ve paper işlem çekirdeği.
V20 altyapısı korunarak V21 paper/portföy geliştirmeleri ve 30 dakikalık V21 test bulguları (K1–K8) işlendi.
Python paketi adı `phoenix` olarak kaldı (komutlar değişmedi): `python -m phoenix.live ...`

> Bu paket kârlılık iddiası taşımaz. Yazılım doğruluğu ≠ strateji kârlılığı. Canlıya geçmeden önce OOS/walk-forward gerekir.

## Modlar (kaza ile değişmez)

| Mod | Nasıl | Ne yapar |
|---|---|---|
| READ_ONLY | varsayılan | Veri çeker, skorlar, rapor yazar. Hiçbir şey simüle etmez/göndermez |
| PAPER | `--paper` | `SIZING → RISK → CORRELATION → PAPER ACCEPT/REJECT`; her red `(aşama, neden)` ile raporlanır |
| LIVE | `--live` + `PHOENIX_CONFIRM_LIVE=YES` + API anahtarları | Gerçek emir. `--live` ve `--paper` birlikte kullanılamaz |

## Kurulum

```bash
python -m pip install -r requirements.txt
cp .env.example .env     # READ_ONLY/PAPER için anahtar gerekmez
```

## İlk kabul testi: 30 dk gerçek piyasa verisiyle PAPER

```bash
./run_v22_30min_paper_test.sh     # Linux/macOS
RUN_V22_30MIN_PAPER_TEST.bat      # Windows
```

Rapor: `python tools/read_report.py reports/v22_paper_30min.json`
Zinciri nasıl okuyacağın: `docs/V22_TEST_PLAN.md`.

## Portföy ve borsa ayarları

- `PHOENIX_EXCHANGES=binance,okx,bybit` gibi virgülle ayrılmış CCXT borsa kimlikleri kullanılabilir.
- PAPER/READ_ONLY tüm seçili borsaları tek bir 1.000 $ sanal portföyde birleştirir.
- `PHOENIX_MAX_OPEN_POSITIONS=0` sabit pozisyon adedi sınırı olmadığını belirtir; marj, kullanılabilir kasa, ücret, günlük/haftalık zarar ve tema limitleri geçerlidir.
- Aynı dayanak varlığa farklı borsalarda ikinci açık PAPER pozisyonu açılmaz.
- Çoklu borsada LIVE emirleri global canlı bakiye/marj koordinasyonu tamamlanana kadar kilitlidir.
- Gerçek piyasa verisi testi `--require-mainnet-data` ile sandbox/demo açıksa başlamaz.

## Hızlı komutlar

```bash
python -m phoenix.live --duration 600 --poll 15 --max-cycle-sec 240 --report reports/readonly.json --score-log reports/scores.jsonl
python -m phoenix.live --paper --duration 600 --poll 15 --max-cycle-sec 240 --report reports/paper.json
python tools/calibrate_from_scores.py reports/scores.jsonl     # eşik başına geçen aday sayısı (çevrimdışı)
python -m phoenix.live --clear-halt                            # kill switch kilidini elle kaldır
```

## Test

```bash
PYTHONPATH=. pytest -q
python -m compileall -q phoenix tests tools
```

Ayrıntılar: `docs/V22_BUILD_REPORT.md` (ne değişti, neyin test EDİLEMEDİĞİ dahil), `docs/OPERATIONS.md`, `CHANGELOG.md`.


### V22.0.3 sizing and V22.0.2 position-count behavior
Each entry targets $50 notional exposure (approximately $5 initial margin at 10x, before fees). Set with `PHOENIX_ENTRY_NOTIONAL_USD=50`. The bot has no arbitrary global or theme position-count cap by default. Each fresh, eligible signal may open a position while shared portfolio collateral and risk checks permit it. `PHOENIX_MAX_OPEN_POSITIONS=0` means unlimited global count; no theme-count setting is used (legacy `PHOENIX_MAX_POSITIONS_PER_THEME` is ignored). This does **not** mean unlimited leverage or borrowing: available margin, equity, daily/weekly loss, drawdown and correlation checks remain active. The same underlying is not opened simultaneously on multiple exchanges, and duplicate open orders are rejected. Paper stop fills default to conservative `PHOENIX_PAPER_STOP_FILL=worse`.


## V22.0.4 risk rule
`PHOENIX_MAX_LOSS_USD=20` is a per-position net-loss ceiling. The stop is also tightened by `PHOENIX_LIQUIDATION_BUFFER_FRACTION=0.70` to at most 70% of the theoretical 1/leverage adverse move (7% at 10x). This is a conservative heuristic, not an exchange-specific liquidation-price guarantee.  The stop is calculated from final rounded quantity and estimated fees/slippage; ATR does not tighten it. This is not a guaranteed maximum realized loss: gaps, execution slippage, funding, exchange liquidation and market outages can exceed the estimate. The configured 50 USD notional and 10x leverage remain unchanged; position count remains uncapped by a fixed count, subject to collateral and risk gates.
