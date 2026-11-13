# Shadow Lab — bot-kapanış ve eşleştirilmiş pozisyon incelemesi

> Manuel/süre-sonu kapanışlar performans kohortundan ayrıldı. Eşleştirme aynı `position_id` ile yapılır. Tek run canlı kural veya zararsızlık garantisi değildir.

Baseline kapanış kapsaması: **9/9** | işaretli rekonstrüksiyon: 0 | durum: **TAM**.

## 1. Botun kapattığı işlemlerde performans

| Varyant | İşlem | K/Z | Net | PF | Medyan net | Max DD | İlk 2/net | Trailing maliyet zararı |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 9 | 2/7 | -3.05 | 0.26 | -0.13 | +3.60 | — | 0 / +0.00 |
| net-exit | 9 | 2/7 | -3.05 | 0.26 | -0.13 | +3.60 | — | 0 / +0.00 |
| flow-confidence | 0 | 0/0 | +0.00 | ∞ | +0.00 | +0.00 | — | 0 / +0.00 |
| volatility-gate | 9 | 2/7 | -3.05 | 0.26 | -0.13 | +3.60 | — | 0 / +0.00 |
| range-confirmation | 9 | 2/7 | -3.05 | 0.26 | -0.13 | +3.60 | — | 0 / +0.00 |
| technical-harmony | 8 | 1/7 | -3.33 | 0.19 | -0.22 | +3.88 | — | 0 / +0.00 |
| portfolio-guard | 9 | 2/7 | -3.05 | 0.26 | -0.13 | +3.60 | — | 0 / +0.00 |

## 2. Aynı baseline-bot pozisyonları üzerindeki etki

`Toplam fark`, reddedilen işlemlerin yokluğunu ve kabul edilenlerdeki çıkış farkını birlikte içerir. `Çıkış farkı` yalnız iki tarafta da kapanışı olan aynı pozisyonlardır.

| Varyant | Korunan / elenen | Kaçırılan kazanan | Toplam fark | Çıkış farkı | İyileşen / kötüleşen / aynı |
|---|---:|---:|---:|---:|---:|
| net-exit | 9 / 0 | 0.0% | +0.00 | +0.00 | 0 / 0 / 9 |
| flow-confidence | 0 / 9 | 100.0% | +3.05 | +0.00 | 0 / 0 / 0 |
| volatility-gate | 9 / 0 | 0.0% | +0.00 | +0.00 | 0 / 0 / 9 |
| range-confirmation | 9 / 0 | 0.0% | +0.00 | +0.00 | 0 / 0 / 9 |
| technical-harmony | 8 / 1 | 50.0% | -0.28 | +0.00 | 0 / 0 / 8 |
| portfolio-guard | 9 / 0 | 0.0% | +0.00 | +0.00 | 0 / 0 / 9 |

## 3. Net Exit çıkış dağılımı

- **FLASH CRASH SİGORTASI:** 9 işlem | K/Z 2/7 | net -3.05

## 4. Borsa ve rejim dağılımı

- **BASELINE** — Borsa: binance: 6 / -1.53, okx: 3 / -1.52. Rejim: TREND: 9 / -3.05.
- **net-exit** — Borsa: binance: 6 / -1.53, okx: 3 / -1.52. Rejim: TREND: 9 / -3.05.
- **flow-confidence** — Borsa: veri yok. Rejim: veri yok.
- **volatility-gate** — Borsa: binance: 6 / -1.53, okx: 3 / -1.52. Rejim: TREND: 9 / -3.05.
- **range-confirmation** — Borsa: binance: 6 / -1.53, okx: 3 / -1.52. Rejim: TREND: 9 / -3.05.
- **technical-harmony** — Borsa: binance: 5 / -1.81, okx: 3 / -1.52. Rejim: TREND: 8 / -3.33.
- **portfolio-guard** — Borsa: binance: 6 / -1.53, okx: 3 / -1.52. Rejim: TREND: 9 / -3.05.

## 5. Reddedilen adayların baseline sonuçları

### flow-confidence

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| AEON/USDT SHORT | işlem sayısı 3<5; kapsama 9.6sn<60.0sn; güven ayarlı karar=yok:skor yetersiz (-15.4) | -2.20 | +0.00 | -1.85 | 0.0350136 | +0.35 / +0.00 |
| ARPA/USDT SHORT | işlem sayısı 4<5; kapsama 18.0sn<60.0sn; güven ayarlı karar=yok:skor yetersiz (-22.2) | -0.30 | +0.15 | +0.00 | 0.0107298 | +0.35 / +0.00 |
| CYBER/USDT SHORT | defter yaşı 26.6sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-9.9) | +0.28 | +0.63 | +0.00 | 0.341172 | +0.35 / +0.00 |
| DYM/USDT SHORT | defter yaşı 30.0sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-23.4) | -0.07 | +0.28 | +0.00 | 0.0196344 | +0.35 / +0.00 |
| FLUX/USDT SHORT | güven ayarlı karar=yok:skor yetersiz (-23.3) | -0.96 | +0.00 | -0.61 | 0.0709776 | +0.35 / +0.00 |
| HK0992/USDT SHORT | defter yaşı 36.2sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-10.8) | -0.35 | +0.00 | -0.45 | 24.2028 | +0.35 / +0.00 |
| IONQ/USDT SHORT | güven ayarlı karar=yok:skor yetersiz (-19.6) | +0.78 | +1.13 | +0.00 | 33.588 | +0.35 / +0.00 |
| KOMA/USDT SHORT | güven ayarlı karar=yok:skor yetersiz (-33.5) | -0.13 | +0.22 | +0.00 | 0.01732104 | +0.35 / +0.00 |
| KSM/USDT SHORT | güven ayarlı karar=yok:skor yetersiz (-21.2) | -0.09 | +0.26 | +0.00 | 4.20984 | +0.35 / +0.00 |

### technical-harmony

| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |
|---|---|---:|---:|---:|---:|---:|
| CYBER/USDT SHORT | karşıt teknik bileşen 4>1 | +0.28 | +0.63 | +0.00 | 0.341172 | +0.35 / +0.00 |


## 6. Ayrı tutulan manuel/erken kapanışlar

- Baseline: 0 | net-exit: 0 | flow-confidence: 0 | volatility-gate: 0 | range-confirmation: 0 | technical-harmony: 0 | portfolio-guard: 0
Bu kohortta çıkış performansı değerlendirilmez; giriş kanıtı ayrı `cohort-report.md` içindedir.

