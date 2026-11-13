# Shadow Lab — bot-kapanış ve eşleştirilmiş pozisyon incelemesi

> Manuel/süre-sonu kapanışlar performans kohortundan ayrıldı. Eşleştirme aynı `position_id` ile yapılır. Tek run canlı kural veya zararsızlık garantisi değildir.

Baseline kapanış kapsaması: **20/20** | işaretli rekonstrüksiyon: 0 | durum: **TAM**.

## 1. Botun kapattığı işlemlerde performans

| Varyant | İşlem | K/Z | Net | PF | Medyan net | Max DD | İlk 2/net | Trailing maliyet zararı |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 20 | 13/7 | +31.89 | 4.23 | +1.95 | +7.21 | 41.2% | 1 / -0.46 |
| net-exit | 19 | 13/6 | +32.04 | 4.40 | +2.28 | +7.21 | 40.8% | 0 / +0.00 |
| flow-confidence | 0 | 0/0 | +0.00 | ∞ | +0.00 | +0.00 | — | 0 / +0.00 |
| volatility-gate | 18 | 13/5 | +32.96 | 4.74 | +2.34 | +7.21 | 39.8% | 0 / +0.00 |
| range-confirmation | 18 | 12/6 | +31.54 | 4.35 | +2.34 | +7.21 | 41.6% | 0 / +0.00 |
| technical-harmony | 14 | 9/5 | +23.28 | 3.85 | +1.95 | +5.96 | 56.4% | 0 / +0.00 |
| portfolio-guard | 20 | 13/7 | +31.89 | 4.23 | +1.95 | +7.21 | 41.2% | 1 / -0.46 |
| pdf-confluence | 16 | 10/6 | +24.94 | 3.65 | +1.95 | +7.21 | 52.6% | 0 / +0.00 |

## 2. Aynı baseline-bot pozisyonları üzerindeki etki

`Toplam fark`, reddedilen işlemlerin yokluğunu ve kabul edilenlerdeki çıkış farkını birlikte içerir. `Çıkış farkı` yalnız iki tarafta da kapanışı olan aynı pozisyonlardır.

| Varyant | Korunan / elenen | Kaçırılan kazanan | Toplam fark | Çıkış farkı | İyileşen / kötüleşen / aynı |
|---|---:|---:|---:|---:|---:|
| net-exit | 20 / 0 | 0.0% | +0.16 | +0.16 | 12 / 4 / 4 |
| flow-confidence | 0 / 20 | 100.0% | -31.89 | +0.00 | 0 / 0 / 0 |
| volatility-gate | 18 / 2 | 0.0% | +1.07 | +0.00 | 0 / 0 / 18 |
| range-confirmation | 18 / 2 | 7.7% | -0.35 | +0.00 | 0 / 0 / 18 |
| technical-harmony | 14 / 6 | 30.8% | -8.61 | +0.00 | 0 / 0 / 14 |
| portfolio-guard | 20 / 0 | 0.0% | +0.00 | +0.00 | 0 / 0 / 20 |
| pdf-confluence | 16 / 4 | 23.1% | -6.95 | +0.00 | 0 / 0 / 16 |

## 3. Net Exit çıkış dağılımı

- **FLASH CRASH SİGORTASI:** 12 işlem | K/Z 6/6 | net +1.99
- **KÂR KOŞUSU — ORDER-FLOW DÖNÜŞÜ:** 7 işlem | K/Z 7/0 | net +30.05

| Sembol | Baseline çıkış | Shadow çıkış | Baseline net | Shadow net | Fark |
|---|---|---|---:|---:|---:|
| PIXEL/USDT SHORT | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($1,544, zirve/dip %0.12) | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($1,450, zirve/dip %0.14) | +3.37 | +2.76 | -0.61 |
| AMZN/USDT SHORT | TRAILING STOP | SÜRELİ PAPER ÖLÇÜMÜ SONU — SHADOW | -0.46 | +0.01 | +0.47 |
| APE/USDT SHORT | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($3,343, zirve/dip %0.08) | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($3,043, zirve/dip %0.08) | +3.84 | +4.23 | +0.39 |
| WLD/USDT SHORT | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($130,119, zirve/dip %1.18) | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($175,198, zirve/dip %1.18) | +3.21 | +3.42 | +0.22 |
| CELR/USDT SHORT | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($1,025, zirve/dip %0.08) | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($1,025, zirve/dip %0.12) | +8.27 | +8.06 | -0.20 |
| BONK/USDT SHORT | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($1,046, zirve/dip %0.20) | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($1,040, zirve/dip %0.20) | +4.44 | +4.28 | -0.16 |
| CHILLGUY/USDT SHORT | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($1,502, zirve/dip %0.07) | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($1,496, zirve/dip %0.07) | +4.86 | +5.01 | +0.16 |
| ACE/USDT SHORT | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($1,332, zirve/dip %0.06) | KÂR KOŞUSU: SHORT ALIŞ BASKISI + CVD dönüşü ($1,332, zirve/dip %0.06) | +2.38 | +2.28 | -0.11 |
| US500/USDT SHORT | FLASH CRASH SİGORTASI | FLASH CRASH SİGORTASI | -0.61 | -0.61 | +0.00 |
| SATS/USDT SHORT | FLASH CRASH SİGORTASI | FLASH CRASH SİGORTASI | +2.29 | +2.29 | +0.00 |
| 1000SATS/USDT SHORT | FLASH CRASH SİGORTASI | FLASH CRASH SİGORTASI | -1.50 | -1.50 | +0.00 |
| PIPPIN/USDT SHORT | FLASH CRASH SİGORTASI | FLASH CRASH SİGORTASI | +2.76 | +2.76 | +0.00 |
| SUI/USDT SHORT | FLASH CRASH SİGORTASI | FLASH CRASH SİGORTASI | -2.32 | -2.32 | +0.00 |
| TURBO/USDT SHORT | FLASH CRASH SİGORTASI | FLASH CRASH SİGORTASI | +2.90 | +2.90 | +0.00 |
| SOL/USDT SHORT | FLASH CRASH SİGORTASI | FLASH CRASH SİGORTASI | +1.03 | +1.03 | +0.00 |
| ETH/USDT SHORT | FLASH CRASH SİGORTASI | FLASH CRASH SİGORTASI | -1.25 | -1.25 | +0.00 |

## 4. Borsa ve rejim dağılımı

- **BASELINE** — Borsa: binance: 11 / +20.25, okx: 9 / +11.64. Rejim: BREAKOUT: 3 / -0.50, RANGE: 2 / +0.35, TREND: 15 / +32.03.
- **net-exit** — Borsa: binance: 10 / +20.34, okx: 9 / +11.70. Rejim: BREAKOUT: 3 / -0.50, RANGE: 1 / +0.81, TREND: 15 / +31.72.
- **flow-confidence** — Borsa: veri yok. Rejim: veri yok.
- **volatility-gate** — Borsa: binance: 10 / +20.71, okx: 8 / +12.25. Rejim: BREAKOUT: 2 / +0.11, RANGE: 1 / +0.81, TREND: 15 / +32.03.
- **range-confirmation** — Borsa: binance: 10 / +20.71, okx: 8 / +10.83. Rejim: BREAKOUT: 3 / -0.50, TREND: 15 / +32.03.
- **technical-harmony** — Borsa: binance: 8 / +18.12, okx: 6 / +5.17. Rejim: BREAKOUT: 3 / -0.50, TREND: 11 / +23.78.
- **portfolio-guard** — Borsa: binance: 11 / +20.25, okx: 9 / +11.64. Rejim: BREAKOUT: 3 / -0.50, RANGE: 2 / +0.35, TREND: 15 / +32.03.
- **pdf-confluence** — Borsa: binance: 9 / +16.87, okx: 7 / +8.07. Rejim: BREAKOUT: 3 / -0.50, TREND: 13 / +25.44.

## 5. Reddedilen adayların baseline sonuçları

### flow-confidence

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| ACE/USDT SHORT | işlem sayısı 4<5; kapsama 10.3sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-15.9) | +2.38 | +3.09 | -0.18 | 0.1536732 | +0.50 / -0.00 |
| AMZN/USDT SHORT | kapsama 28.5sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-4.4) | -0.46 | +0.09 | +0.00 | 248.82982 | +0.50 / +0.00 |
| APE/USDT SHORT | kapsama 28.2sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-10.3) | +3.84 | +5.13 | -0.39 | 0.136836 | +0.50 / -0.00 |
| BONK/USDT SHORT | işlem sayısı 3<5; kapsama 20.5sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-22.5) | +4.44 | +5.76 | -0.66 | 3.0348393e-06 | +0.50 / +0.00 |
| CELR/USDT SHORT | işlem sayısı 2<5; kapsama 38.4sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-17.9) | +8.27 | +9.17 | -0.41 | 0.0026514 | +0.50 / +0.00 |
| CHILLGUY/USDT SHORT | emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-28.4) | +4.86 | +5.88 | -0.60 | 0.01038528 | +0.50 / -0.00 |
| PIPPIN/USDT SHORT | emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-20.6) | +2.76 | +4.88 | -0.33 | 0.015322674 | +0.50 / +0.00 |
| PIXEL/USDT SHORT | emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-32.7) | +3.37 | +3.97 | -0.71 | 0.00530496 | +0.50 / -0.00 |
| SATS/USDT SHORT | emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-22.9) | +2.29 | +5.07 | -0.30 | 1.0019676e-08 | +0.50 / +0.00 |
| SHAZ/USDT SHORT | işlem sayısı 4<5; emir defteri yok; defter yaşı 12.6sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-11.4) | +0.81 | +2.41 | -0.66 | 22.801229 | +0.50 / -0.00 |
| TURBO/USDT SHORT | emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-27.3) | +2.90 | +4.98 | -0.43 | 0.00082104935 | +0.50 / +0.00 |
| US500/USDT SHORT | emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-39.8) | -0.61 | +0.30 | -0.14 | 8242.452 | +0.50 / +0.02 |
| SOL/USDT SHORT | emir defteri yok | +1.03 | +2.76 | -0.35 | 109.5552 | +0.50 / +0.00 |
| WLD/USDT SHORT | emir defteri yok | +3.21 | +9.70 | -1.85 | 0.496044 | +0.50 / +0.00 |
| ETH/USDT SHORT | emir defteri yok | -1.25 | +0.88 | -0.85 | 2522.4588 | +0.50 / +0.00 |
| SUI/USDT SHORT | emir defteri yok | -2.32 | +1.98 | -2.03 | 0.984204 | +0.50 / +0.00 |
| 1000SATS/USDT SHORT | emir defteri yok; defter yaşı 15.6sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-38.9) | -1.50 | +1.00 | -1.51 | 1.07568e-05 | +0.50 / +0.00 |
| 2Z/USDT SHORT | emir defteri yok | +1.61 | +3.17 | -0.53 | 0.0306936 | +0.50 / +0.00 |
| BITO/USDT SHORT | emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-34.2) | -1.90 | +0.00 | -1.40 | 11.556 | +0.50 / +0.00 |
| CSOPSAMSUNG2L/USDT SHORT | emir defteri yok; defter yaşı 30.8sn>10.0sn | -1.85 | +0.00 | -1.35 | 6.38064 | +0.50 / +0.00 |

### volatility-gate

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| AMZN/USDT SHORT | volatilite/maliyet hareket alanı yetersiz | -0.46 | +0.09 | +0.00 | 248.82982 | +0.50 / +0.00 |
| US500/USDT SHORT | volatilite/maliyet hareket alanı yetersiz | -0.61 | +0.30 | -0.14 | 8242.452 | +0.50 / +0.02 |

### range-confirmation

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| AMZN/USDT SHORT | RANGE rejiminde yalnız para-akışı tetikli giriş | -0.46 | +0.09 | +0.00 | 248.82982 | +0.50 / +0.00 |
| SHAZ/USDT SHORT | RANGE rejiminde yalnız para-akışı tetikli giriş | +0.81 | +2.41 | -0.66 | 22.801229 | +0.50 / -0.00 |

### technical-harmony

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| AMZN/USDT SHORT | karşıt teknik bileşen 3>1 | -0.46 | +0.09 | +0.00 | 248.82982 | +0.50 / +0.00 |
| APE/USDT SHORT | karşıt teknik bileşen 2>1 | +3.84 | +5.13 | -0.39 | 0.136836 | +0.50 / -0.00 |
| PIPPIN/USDT SHORT | karşıt teknik bileşen 2>1 | +2.76 | +4.88 | -0.33 | 0.015322674 | +0.50 / +0.00 |
| SHAZ/USDT SHORT | karşıt teknik bileşen 3>1 | +0.81 | +2.41 | -0.66 | 22.801229 | +0.50 / -0.00 |
| TURBO/USDT SHORT | karşıt teknik bileşen 2>1 | +2.90 | +4.98 | -0.43 | 0.00082104935 | +0.50 / +0.00 |
| ETH/USDT SHORT | karşıt teknik bileşen 2>1 | -1.25 | +0.88 | -0.85 | 2522.4588 | +0.50 / +0.00 |

### pdf-confluence

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| AMZN/USDT SHORT | PDF v2 aile oyu/veri yetersiz | -0.46 | +0.09 | +0.00 | 248.82982 | +0.50 / +0.00 |
| APE/USDT SHORT | PDF v2 aile oyu/veri yetersiz | +3.84 | +5.13 | -0.39 | 0.136836 | +0.50 / -0.00 |
| PIPPIN/USDT SHORT | PDF v2 aile oyu/veri yetersiz | +2.76 | +4.88 | -0.33 | 0.015322674 | +0.50 / +0.00 |
| SHAZ/USDT SHORT | PDF v2 aile oyu/veri yetersiz | +0.81 | +2.41 | -0.66 | 22.801229 | +0.50 / -0.00 |


## 6. Ayrı tutulan manuel/erken kapanışlar

- Baseline: 0 | net-exit: 1 | flow-confidence: 0 | volatility-gate: 0 | range-confirmation: 0 | technical-harmony: 0 | portfolio-guard: 0 | pdf-confluence: 0
Bu kohortta çıkış performansı değerlendirilmez; giriş kanıtı ayrı `cohort-report.md` içindedir.

