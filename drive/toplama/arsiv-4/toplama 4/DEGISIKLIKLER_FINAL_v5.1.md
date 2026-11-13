# ACARBOT FINAL v5.1 — Değişiklik Günlüğü (7 Kasım 2026)

**Taban:** v5.0 (549 test) · **Sonuç:** **601 passed + 1 koşullu** · `__version__ = "5.1-final"`

v5.1 yeni sinyal eklemez. **Kanıt kalitesini** düzeltir. v5.0 incelemesinde
tespit edilen altı boşluk kapatıldı.

---

## 1. Mum içi yol modeli — `backtest/intrabar.py` (YENİ)

**Sorun:** 5 dakikalık mumda stop ile TP aynı barda görülürse sıra bilinmez.
Eski motor "önce stop" diyor ama çıkış fiyatı olarak **mumun ucunu**
kullanıyordu. Stop 75.475 iken mum ucu 75.810 olan barda kayıp 25 yerine
40 USDT çıkıyordu. Bunun gerçek gap mi yoksa model kötümserliği mi olduğu
5m veriyle **ayırt edilemiyordu**.

**Çözüm:**
- `IntrabarPath` — 1m mumlar varsa 5m barın içindeki **gerçek sıra** ile
  yürünür. Stop, tetiklendiği ilk 1m barda ve o barın çok daha dar ucundan
  kapanır.
- 1m yoksa OHLC'den deterministik sentetik yol; `adverse_first` (kötümser)
  ve `favorable_first` (iyimser) ile **alt/üst sınır** koşulur. Tek sayı
  yerine aralık raporlanır.
- Kapsama denetimi: eksik kapsama (`partial_coverage_bars`) veya kaba barla
  çelişen uçlar (`inconsistent_bars`) → sentetiğe düşer ve SAYILIR.
- `overshoot_ratio()` — çıkışın stop seviyesini stop mesafesinin kaç katı
  aştığını ölçer.
- `manage_position_candle(..., intrabar=True)` — alt mumlar bar sayacını
  şişirmez (yoksa zaman bazlı çıkış 5 kat erken tetiklenirdi).

**Regresyon testi:** aynı 5m barda 1m yol ile kayıp, kaba mum ucuna göre
**%20'den fazla daha küçük** (`test_real_1m_reduces_emergency_stop_loss`).

## 2. Gerçek maliyet modeli — `backtest/costs.py` (YENİ)

**Sorun:** v3.0–v5.0 backtest'lerinde `spread = uygulanmadi`,
`slippage_bps = 0`, `latency_ms = 0`. Sonuçlar yapısal olarak iyimserdi.

**Çözüm:**
- `CostModel` — borsa ve sembol başına spread / giriş kayması /
  **çıkış kayması** / gecikme. Çıkış bacağına kayma uygulanması yenidir.
- Üç kaynak: **ölçülmüş** (`tools/measure_costs.py`) → **muhafazakâr
  varsayım** (açıkça "ölçülmedi" etiketli) → **kapalı** (yalnızca bilinçli
  `CostModel.disabled()`, rapor iyimserlik bayrağı taşır).
- **Maliyetler artık VARSAYILAN AÇIK.** Eski "maliyetsiz" davranışı
  isteyen testler açıkça `CostModel.disabled()` kullanır.
- `tools/measure_costs.py` (YENİ) — canlı emir defterinden örnek alır:
  spread = (ask1−bid1)/orta, kayma = hedef nominali süpürmenin VWAP
  sapması, gecikme = REST gidiş-dönüş süresi.

**Gerçek ölçüm (7 Kasım 2026, OKX, 3.000 USDT nominal, 4 örnek/sembol):**

| Sembol | Spread (bps) | Giriş kayması (bps) | Çıkış kayması (bps) | Gecikme (ms) |
|---|---|---|---|---|
| BTC-USDT-SWAP | 0,01 | 0,0066 | 0,0066 | 200 |
| ETH-USDT-SWAP | 0,04 | 0,0224 | 0,0224 | 191 |
| SOL-USDT-SWAP | 1,12 | 0,5576 | 0,5576 | 150 |
| XRP-USDT-SWAP | 0,86 | 2,7908 | 1,9976 | 148 |
| **DOGE-USDT-SWAP** | 1,39 | **21,8745** | **23,9115** | 150 |
| **ADA-USDT-SWAP** | 5,50 | **14,2751** | **14,4538** | 148 |

DOGE ve ADA'da 3.000 USDT'lik emir **%0,14–0,24** kayma yaratıyor. Bu,
25 USDT hedef net riskin tek başına işlem maliyetine yakın olduğu anlamına
gelir — maliyetleri sıfır sayan hiçbir backtest bu gerçeği gösteremez.

## 3. Çok sembollü doğrulama koşucusu — `tools/validate_strategy.py` (YENİ)

Tek komutla:
1. 90+ gün, çok sembollü 5m mum indirir (önbellekli, tekrar indirmez)
2. Mum içi yol için 1m alt çözünürlük indirir
3. Maliyet modelini yükler
4. Backtest'i **maliyet açık** koşar
5. Walk-forward + Monte Carlo + rejim kırılımı
6. Gerçekleşen/hedef kayıp denetimi
7. Maliyetsiz karşılaştırma koşusu (iyimserlik farkını gösterir)
8. Hepsini **tek JSON + tek Markdown** rapora yazar
9. **Hüküm** üretir: örneklem yetersiz / kenar yok / kenar var ama risk
   sapıyor / kenar adayı

`tools/download_history.py`'ye `interval` parametresi eklendi (1m için).

```bash
python3 -m tools.measure_costs --out docs/maliyet_olcum.json
python3 -m tools.validate_strategy --days 90 --fine-days 3 \
    --costs docs/maliyet_olcum.json --out docs/dogrulama_v5.1.json
```

## 4. Sürüm regresyon kapısı — `backtest/regression_gate.py` (YENİ)

**Sorun:** v5.0 paketindeki `docs/backtest_gercek_veri.json` v3.0/v4.0'tan
kalmaydı ve v5.0 ile yeniden üretilmemişti. Belge eski sayıları yeni
sürümün kanıtı gibi sunuyordu.

**Çözüm:** `docs/backtest_referans.json` bir kanıt parmak izi taşır ve
kapı şunları zorunlu kılar:
1. **Referans sürümü = paket sürümü** → bayat sonuç KIRMIZI
2. **Maliyetler açık** → iyimser backtest KIRMIZI
3. **Deterministik fixture yeniden üretilebiliyor** → motor davranışı
   değiştiyse KIRMIZI (veri parmak izi + metrikler + red sayaçları)
4. Veri kümesi çok sembollü ve uzun (≥3 sembol / ≥90 gün)

Fixture ağ gerektirmez; CI'da çevrimdışı yeniden koşulur.
`tools/make_reference.py` (YENİ) referansı üretir.
**CI'ya `regression-gate` işi eklendi** — sürüm atlanıp kanıt
güncellenmezse pipeline kırılır.

## 5. Tick/lot doğrulaması — `infra/tick_verify.py` (YENİ)

**Sorun:** Binance vadeli `exchangeInfo` bu bölgeden 451 döndüğü için
tickSize **spot aynadan** okunuyor. Spot tick vadeli sözleşmeyle aynı
olmak zorunda değil; farklıysa stop ızgarası hizalama yanlış ızgaraya
göre çalışır.

**İki katmanlı çözüm:**
- `TickVerifier` — vadeli kaynakları dener (fapi, fapi1/2/3):
  - **uyuşma** → sembol işlem görür
  - **UYUŞMAZLIK** → sembol **işlem dışı** (politikadan bağımsız)
  - **erişilemiyor** → `--tick-policy warn|strict` (varsayılan `warn`)
- `GridObserver` — vadeli API hiç erişilemediğinde **tek gerçek kanıt**:
  borsadan gelen fiyat iddia edilen ızgaranın üzerinde mi? Eşik sayıda
  ihlalde (varsayılan 3) sembol işlem dışı kalır ve girişi engellenir.
  API'ye ihtiyaç duymaz.

**Dürüstlük notu:** bu ortamda vadeli uç noktaların hiçbiri yanıt vermiyor
(451 / boş 202). Binance sembolleri `unverified` kalır; rapor bunu açıkça
yazar. `unverified` ≠ "doğrulandı".

## 7. Oturum sonu risk denetimi — `audit_trade_risk()`

`exec/paper.py` CLOSE kaydına iki alan eklendi: **`target_net_risk`** ve
**`stop_loss`**. Bunlarla:
- Her kapanış için **gerçekleşen / hedef kayıp** oranı hesaplanır
- **1,3 katı aşan** işlemler işaretlenir ve log'a `RİSK AŞIMI` olarak düşer
- **Stop aşımı** (overshoot) ölçülür: çıkış, stop seviyesinin ne kadar
  ötesinde gerçekleşti
- Oturum raporunda `target_risk_audit.realized_vs_target` bloğu

Kullanıcının canlı örneği (−40,31 / 25 = **1,61R**) artık otomatik
yakalanıyor ve test ediliyor.

## 6. Paket hijyeni

| Bulgu | Düzeltme |
|---|---|
| README dizin ağacı v4.0, "483 test" | v5.1 ağacı, 601 test, yeni modüller eklendi |
| `requirements.txt` başlığı v3.0 | v5.1 |
| Analiz dokümanı `safety/` için "kill switch, deadman" diyordu | **Düzeltildi:** `safety/` = Telegram + haber koruması + sır maskeleme (19 satır). Kill switch `core/risk.py`, deadman `app/main.py` + `live/broker_clients.py`, acil düzleştirme `live/sync.py` |
| Analiz dokümanında kişisel e-posta adresi | Kaldırıldı |
| CI yalnızca kritik ruff + test | `F,E9,E711,E712,E722` taraması + **regression-gate** işi eklendi; 54 lint bulgusu temizlendi |
| Backtest fiyat ızgarasını uygulamıyordu | `engine.run(tick_sizes=...)` — artık backtest'te de ızgara hizalı |

## Test paketi (601 + 1 koşullu)

| Küme | Adet |
|---|---|
| v5.0 tabanı | 549 |
| **`test_v51_hardening.py`** (yeni) | **52** (+1 koşullu: referans dosyası yoksa atlanır) |

Yeni test sınıfları: `TestIntrabarPath` (9), `TestOvershoot` (4),
`TestIntrabarChangesOutcome` (1), `TestCostModel` (8),
`TestRegressionGate` (8), `TestTickVerification` (6), `TestGridObserver` (4),
`TestRiskAudit` (7), `TestValidationRunner` (6).

## Hâlâ AÇIK olan sınırlar (dürüst liste)

- **Gerçek testnet/demo oturumu yapılmadı.** `live/` katmanı yalnızca mock
  testlerle sınanmış.
- **Tam pazar modunda MTF ve order flow kapalı** (1046 sembolde REST rate
  limitlerine sığmaz). En güçlü iki uzman, en geniş modda devre dışı.
- **Ajanlar backtest'te etkisiz**, canlıda yalnızca gözlem üretir.
- **Binance vadeli tickSize doğrulanamıyor** (bölgesel 451). Canlı ızgara
  gözlemi tek ampirik kanıt.
- **1000 USDT bakiyede 25 USDT risk** ancak ~2 eşzamanlı pozisyona yeter.
- **Kârlılık iddiası yok.** v5.1 ölçüm altyapısı kurar; kenarın var olup
  olmadığını `docs/dogrulama_v5.1.json` raporundaki hüküm söyler.
