# ACARBOT FINAL v5.0 — Değişiklik Günlüğü (7 Kasım 2026)

**Taban:** v4.0 (483 test) · **Port kaynağı:** v1.10 (315 test) · **Sonuç:** **549/549 passed**

v5.0, birbirinden kopmuş iki geliştirme hattını birleştirir:
- **A hattı** (v2.0→v4.0): uzmanlar, rejim, MTF, order flow, confluence, DCA, ajanlar, Monte Carlo, canlı emir katmanı
- **B hattı** (v1.0→v1.10): tam pazar taraması, RVOL birim doğruluğu, hedef net risk, dinamik teminat, stop fiyat ızgarası, dolum anı teminat kilidi

Ayrıntılı analiz: **`ANALIZ_v5.0_DETAYLI.md`**

---

## 1. `app/__init__.py`
- `__version__ = "5.0-final"`

## 2. `core/config.py`
| Alan | Eski | Yeni | Anlamı |
|---|---|---|---|
| `account.max_notional_per_position` | 500.0 | **0.0** | Nominal tavan KAPALI |
| `account.margin_per_position` | 50.0 | **0.0** | Teminat DİNAMİK (nominal/kaldıraç) |
| `signal.spike_min_baseline_notional_per_second` | — | **5.0** | Likidite tabanı (USDT/sn) |
| `signal.rvol_log_interval_seconds` | — | **60.0** | Sembol başına log aralığı |
| `exit.stop_tick_max_widen_ratio` | — | **1.5** | Izgara genişleme tavanı |

## 3. `core/risk.py`
- **Hedef-net-risk boyutlaması:** `notional = 25 / (effective_stop_fraction + cost_rate)`
- **Dinamik teminat:** `margin = notional / leverage`
- **Fiyat ızgarası:** `plan(..., tick_size=...)` — stop ızgaraya DIŞA yuvarlanır (LONG `floor`, SHORT `ceil`), pozisyon gerçek mesafeden boyutlanır
- **Kaba ızgara koruması:** `snapped > raw * 1.5` → `ValueError("STOP_IZGARA_KABA")`, işlem açılmaz
- `raw_stop_distance_fraction` alanı — çift yuvarlamayı önler
- `funding_buffer_rate()` / `estimated_funding_buffer(notional=...)`
- **Funding çift sayımı düzeltildi:** `net_risk = notional*(effective_frac + cost_rate) + funding_buffer`
- `check_portfolio(..., reserved_margin=...)` — bekleyen emir rezervasyonu düşülür
- **Fail-closed doğrulamalar:** `max_loss_per_position<=0`, `max_notional_per_position<0`, `leverage<=0`, `margin_per_position<0` → `ValueError`
- Docstring güncellendi (eski "2-3 USDT net risk" ifadesi kaldırıldı)

## 4. `core/spike.py`
- `SpikeEvent.illiquid` + `SpikeEvent.baseline_notional_per_second`
- `SpikeDetector(min_baseline_notional_per_second=..., cooldown_seconds=...)`
- **Sıra:** önce likidite, sonra birim doğrulaması → `illiquid` ve `suspect` artık ayrı
- `_last_spike` **pencere bazlı cooldown** (eski: yalnız aynı saniye tekilleştirme → 3 sn pencere toplamı mükerrer sayılıyordu)

## 5. `exec/paper.py`
- `reserved_margin(exclude_order_id)` / `free_margin(exclude_order_id)`
- **`_margin_lock_blocks`** — her tick'te dolum anı teminat kontrolü; yetmezse emir iptal + `TEMİNAT_KILIDI` kaydı + `margin_lock_cancels` sayacı
- **`_align_plan_to_grid`** — planı gerçek dolum fiyatına ve ızgaraya oturtur, pozisyonu yeniden boyutlar; `grid_realign_count` sayacı
- `place_entry`: miktar `plan.notional / limit_price` (nominal sabit kalır)
- `bind_plan` artık ızgara hizalı plan bağlar
- `_open_position_from_order`: dinamik teminat, **dolan orana göre ölçeklenen net risk**, nominalle ölçeklenen funding tamponu
- `OPEN` kaydına `notional` eklendi; `margin` dinamik
- `ORDER_NEW` kaydına `notional`, `margin`, `net_risk`, `grid_aligned` eklendi
- İptal edilen emirler pending listesinden temizleniyor

## 6. `app/executor.py`
- `tick_sizes` sözlüğü; `risk.plan(..., tick_size=...)`, `ValueError` → `RİSK ENGELİ` logu
- `check_portfolio(..., reserved_margin=broker.reserved_margin())`
- **Maker açlığı düzeltmesi:** `tick_volume = base_delta` (eski: `spike is not None` koşullu → hacim patlaması olmayan piyasada emirler dolmuyordu)
- **`_log_volume_filter`** — `LİKİDİTE DÜŞÜK` (INFO) / `RVOL ŞÜPHELİ` (WARNING), sembol başına 60 sn'de tek satır, bastırılan tekrarlar sayılır
- `rvol_suspect_count`, `low_liquidity_count` sayaçları

## 7. `app/main.py`
- **tickSize keşfi ek HTTP olmadan:** `--scan-all`'ın `Market` nesnelerinden alınır (v1.10'daki ayrı `symbol_universe` portuna gerek kalmadı)
- Boş evren → fail-closed `return 1`
- Afiş: `HACİM FİLTRESİ v5.0`, `BOYUTLAMA v5.0`, `STOP KORUMASI v5.0`, borsa başına `FİYAT IZGARASI`
- Oturum raporu: **`volume_filter`** ve **`target_risk_audit`** blokları (`net_risks` listesiyle her pozisyonun 25 USDT taşıdığı denetlenebilir)
- Rapor bloğunda savunmacı `getattr` zinciri (sahte executor'larla uyum)

## 8. Test paketi (549)

| Küme | Adet |
|---|---|
| v4.0 tabanı (uyarlanmış) | 483 |
| `test_target_risk_25.py` + `test_rvol_liquidity.py` + `test_stop_tick_and_margin_lock.py` (v1.10'dan) | 51 |
| **`test_v5_merge.py`** (yeni, birleşim kesişimi) | **15** |

`tests/helpers.py`: `apex_config()` ve `legacy_capped_config()` fabrikaları eklendi.

**Uyarlanan v4.0 testleri (22):** 500 nominal tavanı varsayanlar yeni davranışa çekildi; akış testleri `apex_config()` kullanıyor; çıkış nedeni kümesi `{stop_loss, position_loss_stop}` (25 USDT boyutlamasında acil stop klasik stopla çakışıyor); float karşılaştırmaları `pytest.approx`.

## 9. Canlı duman testi (7 Kasım 2026, 13:19 UTC)

```
FİYAT IZGARASI [binance]: 518 · [okx]: 528 → toplam 1046 feed
ACARBOT v5.0-final | PAPER | bakiye=1000.00 | maks pozisyon=SINIRSIZ
0 traceback · 0 CRITICAL · LİKİDİTE DÜŞÜK / RVOL ŞÜPHELİ ayrı ve kısıtlı
```

## 10. ⚠️ Dürüst uyarı — sinyal kenarı doğrulanmadı

v3.0/v4.0'ın gerçek veri backtest'i **zarar ediyor**: net **−6,6794 USDT**, 8 işlem, PF **0,31**, ort. kazanç +0,75 / ort. kayıp −2,42, Monte Carlo kayıp olasılığı **%92,3**. Paketlerdeki +29,09 / PF 2,80 sonucu **sentetik demo** (`docs/backtest_ornek.json`, tüm sürümlerde aynı dosya).

**v5.0 risk hassasiyetini düzeltir, kâr eden sinyal üretmez.** 25 USDT'ye ölçeklemeden önce §8.1'deki önerileri uygulayın.

## 11. Kapsam dışı (bilinçli)
- Gerçek/testnet emri bu oturumda gönderilmedi; **paper-only** doğrulandı
- Tarayıcı/araştırma ajanı, OKX likidasyon verisi (v4.0'dan beri kapsam dışı)
- Tam pazar modunda MTF REST / OI sorguları kapalı (rate limiti)
