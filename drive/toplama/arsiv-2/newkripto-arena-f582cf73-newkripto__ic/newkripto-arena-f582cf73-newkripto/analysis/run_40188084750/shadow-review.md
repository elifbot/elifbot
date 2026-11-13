# Shadow Lab — bot-kapanış ve eşleştirilmiş pozisyon incelemesi

> Manuel/süre-sonu kapanışlar performans kohortundan ayrıldı. Eşleştirme aynı `position_id` ile yapılır. Tek run canlı kural veya zararsızlık garantisi değildir.

Baseline kapanış kapsaması: **13/13** | işaretli rekonstrüksiyon: 0 | durum: **TAM**.

## 1. Botun kapattığı işlemlerde performans

| Varyant | İşlem | K/Z | Net | PF | Medyan net | Max DD | İlk 2/net | Trailing maliyet zararı |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 5 | 1/4 | -11.39 | 0.50 | -2.78 | +16.75 | — | 0 / +0.00 |
| net-exit | 1 | 1/0 | +3.24 | ∞ | +3.24 | +0.00 | 100.0% | 0 / +0.00 |
| flow-confidence | 5 | 1/4 | -11.39 | 0.50 | -2.78 | +16.75 | — | 0 / +0.00 |
| volatility-gate | 5 | 1/4 | -11.39 | 0.50 | -2.78 | +16.75 | — | 0 / +0.00 |
| range-confirmation | 4 | 1/3 | +0.19 | 1.02 | -2.59 | +5.85 | 4588.0% | 0 / +0.00 |
| technical-harmony | 1 | 1/0 | +11.21 | ∞ | +11.21 | +0.00 | 100.0% | 0 / +0.00 |
| portfolio-guard | 5 | 1/4 | -11.39 | 0.50 | -2.78 | +16.75 | — | 0 / +0.00 |
| pdf-confluence | 2 | 1/1 | +8.43 | 4.03 | +4.21 | +2.78 | 100.0% | 0 / +0.00 |
| pdf-v3-confluence | 4 | 1/3 | +0.19 | 1.02 | -2.59 | +5.85 | 4588.0% | 0 / +0.00 |

## 2. Aynı baseline-bot pozisyonları üzerindeki etki

`Toplam fark`, reddedilen işlemlerin yokluğunu ve kabul edilenlerdeki çıkış farkını birlikte içerir. `Çıkış farkı` yalnız iki tarafta da kapanışı olan aynı pozisyonlardır.

| Varyant | Korunan / elenen | Kaçırılan kazanan | Toplam fark | Çıkış farkı | İyileşen / kötüleşen / aynı |
|---|---:|---:|---:|---:|---:|
| net-exit | 5 / 0 | 0.0% | +13.77 | +13.77 | 4 / 1 / 0 |
| flow-confidence | 5 / 0 | 0.0% | +0.00 | +0.00 | 0 / 0 / 5 |
| volatility-gate | 5 / 0 | 0.0% | +0.00 | +0.00 | 0 / 0 / 5 |
| range-confirmation | 4 / 1 | 0.0% | +11.58 | +0.00 | 0 / 0 / 4 |
| technical-harmony | 1 / 4 | 0.0% | +22.60 | +0.00 | 0 / 0 / 1 |
| portfolio-guard | 5 / 0 | 0.0% | +0.00 | +0.00 | 0 / 0 / 5 |
| pdf-confluence | 2 / 3 | 0.0% | +19.82 | +0.00 | 0 / 0 / 2 |
| pdf-v3-confluence | 4 / 1 | 0.0% | +11.58 | +0.00 | 0 / 0 / 4 |

## 3. Net Exit çıkış dağılımı

- **KÂR KOŞUSU — ORDER-FLOW DÖNÜŞÜ:** 1 işlem | K/Z 1/0 | net +3.24

| Sembol | Baseline çıkış | Shadow çıkış | Baseline net | Shadow net | Fark |
|---|---|---|---:|---:|---:|
| AVNT/USDT SHORT | ERKEN TREND BOZULMA ÇIKIŞI (28dk, %-1.86): Supertrend ters kırıldı + karşı akış (+41) | SÜRELİ PAPER ÖLÇÜMÜ SONU — SHADOW | -11.58 | -0.72 | +10.86 |
| RLS/USDT LONG | KÂR KOŞUSU: LONG SATIŞ BASKISI + CVD dönüşü ($2,420, zirve/dip %0.26) | KÂR KOŞUSU: LONG SATIŞ BASKISI + CVD dönüşü ($2,420, zirve/dip %0.26) | +11.21 | +3.24 | -7.97 |
| ALCH/USDT SHORT | ERKEN TREND BOZULMA ÇIKIŞI (21dk, %-1.08): birleşik skor ters yöne döndü (+17.3) | SÜRELİ PAPER ÖLÇÜMÜ SONU — SHADOW | -5.85 | +0.05 | +5.90 |
| SYN/USDT SHORT | ERKEN TREND BOZULMA ÇIKIŞI (36dk, %-0.40): rehin marj kurtarma — karşı ALIŞ baskısı ($555) | SÜRELİ PAPER ÖLÇÜMÜ SONU — SHADOW | -2.39 | +0.14 | +2.53 |
| ID/USDT SHORT | ERKEN TREND BOZULMA ÇIKIŞI (29dk, %-0.46): rehin marj kurtarma — karşı ALIŞ baskısı ($570) | SÜRELİ PAPER ÖLÇÜMÜ SONU — SHADOW | -2.78 | -0.34 | +2.45 |

## 4. Borsa ve rejim dağılımı

- **BASELINE** — Borsa: binance: 3 / -11.02, okx: 2 / -0.36. Rejim: RANGE: 1 / -11.58, TREND: 4 / +0.19.
- **net-exit** — Borsa: okx: 1 / +3.24. Rejim: TREND: 1 / +3.24.
- **flow-confidence** — Borsa: binance: 3 / -11.02, okx: 2 / -0.36. Rejim: RANGE: 1 / -11.58, TREND: 4 / +0.19.
- **volatility-gate** — Borsa: binance: 3 / -11.02, okx: 2 / -0.36. Rejim: RANGE: 1 / -11.58, TREND: 4 / +0.19.
- **range-confirmation** — Borsa: binance: 3 / -11.02, okx: 1 / +11.21. Rejim: TREND: 4 / +0.19.
- **technical-harmony** — Borsa: okx: 1 / +11.21. Rejim: TREND: 1 / +11.21.
- **portfolio-guard** — Borsa: binance: 3 / -11.02, okx: 2 / -0.36. Rejim: RANGE: 1 / -11.58, TREND: 4 / +0.19.
- **pdf-confluence** — Borsa: binance: 1 / -2.78, okx: 1 / +11.21. Rejim: TREND: 2 / +8.43.
- **pdf-v3-confluence** — Borsa: binance: 3 / -11.02, okx: 1 / +11.21. Rejim: TREND: 4 / +0.19.

## 5. Reddedilen adayların baseline sonuçları

### range-confirmation

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| AVNT/USDT SHORT | RANGE rejiminde yalnız para-akışı tetikli giriş | -11.58 | +0.00 | -11.07 | 0.1219536 | +0.51 / +0.00 |

### technical-harmony

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| ALCH/USDT SHORT | karşıt teknik bileşen 2>1 | -5.85 | +1.10 | -8.64 | 0.0393336 | +0.50 / +0.00 |
| AVNT/USDT SHORT | karşıt teknik bileşen 2>1 | -11.58 | +0.00 | -11.07 | 0.1219536 | +0.51 / +0.00 |
| ID/USDT SHORT | karşıt teknik bileşen 3>1 | -2.78 | +0.49 | -3.42 | 0.0331128 | +0.50 / +0.00 |
| SYN/USDT SHORT | karşıt teknik bileşen 2>1 | -2.39 | +2.66 | -2.43 | 0.160218 | +0.50 / +0.00 |

### pdf-confluence

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| ALCH/USDT SHORT | PDF v2 aile oyu/veri yetersiz | -5.85 | +1.10 | -8.64 | 0.0393336 | +0.50 / +0.00 |
| AVNT/USDT SHORT | PDF v2 aile oyu/veri yetersiz | -11.58 | +0.00 | -11.07 | 0.1219536 | +0.51 / +0.00 |
| SYN/USDT SHORT | PDF v2 aile oyu/veri yetersiz | -2.39 | +2.66 | -2.43 | 0.160218 | +0.50 / +0.00 |

### pdf-v3-confluence

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| AVNT/USDT SHORT | PDF v3 + türev istihbarat uyumu yetersiz | -11.58 | +0.00 | -11.07 | 0.1219536 | +0.51 / +0.00 |


## 6. Ayrı tutulan manuel/erken kapanışlar

- Baseline: 8 | net-exit: 12 | flow-confidence: 8 | volatility-gate: 8 | range-confirmation: 5 | technical-harmony: 2 | portfolio-guard: 8 | pdf-confluence: 4 | pdf-v3-confluence: 5
Bu kohortta çıkış performansı değerlendirilmez; giriş kanıtı ayrı `cohort-report.md` içindedir.

