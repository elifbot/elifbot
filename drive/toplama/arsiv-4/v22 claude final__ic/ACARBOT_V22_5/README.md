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
### Strateji kuralları (V22.0.5, değiştirmeyin)

| Kural | Değer |
|---|---|
| Kasa | 1000 USD |
| İşlem girişi | **50 USD NOMİNAL, 10x kaldıraç → ~5 USD teminat** (`PHOENIX_ENTRY_NOTIONAL_USD=50`, `PHOENIX_LEVERAGE=10`). `PHOENIX_ENTRY_MARGIN_USD` artık reddedilir (500 USD pozisyona yol açıyordu) |
| Zarar-kes | **−20 USD** sabit (ücret + slipaj dahil; 50 USD nominalde ≈ %40 fiyat hareketi — **izole 10x tasfiye mesafesinin (~%10) ötesinde**, bkz. docs/V22_5_BUILD_REPORT.md). ATR stopa karışmaz (`PHOENIX_ATR_STOP_MULTIPLIER=0`) |
| Kâr al | **İndikatörler belirler** (`PHOENIX_TP_MODE=indicator`): pozisyon net kârdayken (≥ `PHOENIX_TP_MIN_NET_USD`) yöndeki skor `PHOENIX_TP_EXIT_SCORE` altına düşünce kapanır. Sabit hedef yok |
| Pozisyon sayısı | Sınırsız (`PHOENIX_MAX_OPEN_POSITIONS=0`); tek sınır teminat: 1000 USD / ~5 USD ≈ 195–198 eşzamanlı pozisyon (test edildi: 196) |

Kâr alma kuralı yalnızca kârdaki pozisyonları kapatır; zarardaki pozisyonu indikatör erken kesmez, onu −20 USD stop (veya süre çıkışı) kapatır. Skor her cycle başında açık pozisyonlar için ayrıca hesaplanır (`PHOENIX_EXIT_EVAL_BUDGET_SEC`). `PHOENIX_TP_MODE=fixed_rr` eski sabit R hedefini geri getirir. **LIVE modda indikatörlü kâr al henüz yoktur** (borsada TP emri olmadığı için): `--live` bu modda başlamaz.

Pozisyon sayısı için ayrı bir global/tema limiti yoktur. Her taze, uygun sinyal teminat ve risk kapıları izin verdiği sürece pozisyon açar. Bu sınırsız kaldıraç veya borç anlamına gelmez: kullanılabilir marj, özsermaye ve korelasyon kapıları aktiftir. Günlük/haftalık zarar ve drawdown durdurucuları varsayılan KAPALIDIR (0 / 1.0); istenirse env ile açılır. Aynı dayanak iki borsada birden açılmaz. Paper stop dolumu varsayılan olarak muhafazakârdır (`PHOENIX_PAPER_STOP_FILL=worse`: stop ile anlık fiyatın kötüsü).
