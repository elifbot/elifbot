# Shadow Lab — bot-kapanış ve eşleştirilmiş pozisyon incelemesi

> Manuel/süre-sonu kapanışlar performans kohortundan ayrıldı. Eşleştirme aynı `position_id` ile yapılır. Tek run canlı kural veya zararsızlık garantisi değildir.

Baseline kapanış kapsaması: **0/0** | işaretli rekonstrüksiyon: 0 | durum: **TAM**.

## 1. Botun kapattığı işlemlerde performans

| Varyant | İşlem | K/Z | Net | PF | Medyan net | Max DD | İlk 2/net | Trailing maliyet zararı |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 0 | 0/0 | +0.00 | ∞ | +0.00 | +0.00 | — | 0 / +0.00 |
| net-exit | 0 | 0/0 | +0.00 | ∞ | +0.00 | +0.00 | — | 0 / +0.00 |
| flow-confidence | 0 | 0/0 | +0.00 | ∞ | +0.00 | +0.00 | — | 0 / +0.00 |
| volatility-gate | 0 | 0/0 | +0.00 | ∞ | +0.00 | +0.00 | — | 0 / +0.00 |
| range-confirmation | 0 | 0/0 | +0.00 | ∞ | +0.00 | +0.00 | — | 0 / +0.00 |
| technical-harmony | 0 | 0/0 | +0.00 | ∞ | +0.00 | +0.00 | — | 0 / +0.00 |
| portfolio-guard | 0 | 0/0 | +0.00 | ∞ | +0.00 | +0.00 | — | 0 / +0.00 |
| pdf-confluence | 0 | 0/0 | +0.00 | ∞ | +0.00 | +0.00 | — | 0 / +0.00 |

## 2. Aynı baseline-bot pozisyonları üzerindeki etki

`Toplam fark`, reddedilen işlemlerin yokluğunu ve kabul edilenlerdeki çıkış farkını birlikte içerir. `Çıkış farkı` yalnız iki tarafta da kapanışı olan aynı pozisyonlardır.

| Varyant | Korunan / elenen | Kaçırılan kazanan | Toplam fark | Çıkış farkı | İyileşen / kötüleşen / aynı |
|---|---:|---:|---:|---:|---:|
| net-exit | 0 / 0 | — | +0.00 | +0.00 | 0 / 0 / 0 |
| flow-confidence | 0 / 0 | — | +0.00 | +0.00 | 0 / 0 / 0 |
| volatility-gate | 0 / 0 | — | +0.00 | +0.00 | 0 / 0 / 0 |
| range-confirmation | 0 / 0 | — | +0.00 | +0.00 | 0 / 0 / 0 |
| technical-harmony | 0 / 0 | — | +0.00 | +0.00 | 0 / 0 / 0 |
| portfolio-guard | 0 / 0 | — | +0.00 | +0.00 | 0 / 0 / 0 |
| pdf-confluence | 0 / 0 | — | +0.00 | +0.00 | 0 / 0 / 0 |

## 3. Net Exit çıkış dağılımı


## 4. Borsa ve rejim dağılımı

- **BASELINE** — Borsa: veri yok. Rejim: veri yok.
- **net-exit** — Borsa: veri yok. Rejim: veri yok.
- **flow-confidence** — Borsa: veri yok. Rejim: veri yok.
- **volatility-gate** — Borsa: veri yok. Rejim: veri yok.
- **range-confirmation** — Borsa: veri yok. Rejim: veri yok.
- **technical-harmony** — Borsa: veri yok. Rejim: veri yok.
- **portfolio-guard** — Borsa: veri yok. Rejim: veri yok.
- **pdf-confluence** — Borsa: veri yok. Rejim: veri yok.

## 5. Reddedilen adayların baseline sonuçları

Bot-kapanış kohortuna denk gelen reddedilen aday yok.

## 6. Ayrı tutulan manuel/erken kapanışlar

- Baseline: 0 | net-exit: 0 | flow-confidence: 0 | volatility-gate: 0 | range-confirmation: 0 | technical-harmony: 0 | portfolio-guard: 0 | pdf-confluence: 0
Bu kohortta çıkış performansı değerlendirilmez; giriş kanıtı ayrı `cohort-report.md` içindedir.

