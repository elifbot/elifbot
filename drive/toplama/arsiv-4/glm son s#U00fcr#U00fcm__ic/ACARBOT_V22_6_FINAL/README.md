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


## Kural seti (V22.6-FINAL, düzeltilmiş ve tutarlı)

| Kural | Değer |
|---|---|
| Kasa | 1000 USD |
| İşlem girişi | **50 USD TEMİNAT x 10x = 500 USD nominal** (`PHOENIX_ENTRY_MODE=margin`, `PHOENIX_ENTRY_MARGIN_USD=50`, `PHOENIX_LEVERAGE=10`) |
| Zarar-kes | **-20 USD sabit** (ücret+slipaj dahil, ~%3.9 fiyat hareketi - izole 10x tasfiye mesafesinin (~%10) İÇİNDE, yani stop GERÇEKTİR). `entry_mode=notional` (eski $50 nominal) seçilirse stop mesafesi `0.70/leverage` (%7) ile sınırlanır |
| Kâr alma | İndikatör belirler ama **net kâr >= 0.5R ($10)** olmadan kapanmaz (`PHOENIX_TP_MIN_R`). +$10'da stop maliyet-başı başabaşa çekilir (`PHOENIX_BREAKEVEN_R`), +$20'de takip eden stop devreye girer (`PHOENIX_TRAIL_ARM_R`, geri verme 0.5R). Stop yalnız SIKILAŞIR, -$20 tabanı hiç genişlemez |
| Pozisyon sayısı | Sınırsız (`PHOENIX_MAX_OPEN_POSITIONS=0`); tek sınır teminat: 1000 / ~50.3 ≈ 19-20 eşzamanlı pozisyon |
| Sinyal kalitesi | OI x fiyat yönü uyumu, 15m/1h-4h çelişki cezası (x0.70), RSI(14) aşırı-uzama kapısı (LONG >= 78, SHORT <= 22 engellenir) |
| LIVE | `--live` + `PHOENIX_CONFIRM_LIVE=YES`; indikatör TP artık LIVE'da bot tarafından yönetilir (stop borsada taşınır, TP reduce-only market ile kapatılır) |

Mimari, modlar (READ_ONLY / PAPER / LIVE), kapılar (SIZING -> RISK -> CORRELATION) ve CLI degismedi.
Detayli analiz ve V22.5 karsilastirmasi: `docs/V22_6_FINAL_BUILD_REPORT.md`.

