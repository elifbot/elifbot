# ACARBOT FINAL v1.4 — Değişiklik Günlüğü (7 Kasım 2026)

Kullanıcı isteği: "FADE kapat, diğerlerini ön plana çıkar, öyle test et."

## Yeni: motor seçimi (`--motors`)
| Bayrak | Aktif motorlar |
|---|---|
| `--motors both` | FADE + TREND (varsayılan, eski davranış) |
| `--motors trend` | **yalnız TREND** (FADE kapalı) |
| `--motors fade` | yalnız FADE |

- Kapalı motor hiç DEĞERLENDİRİLMEZ (testle kilitli); canlı ve backtest
  katmanlarında aynı kural.
- TREND'in kalite filtreleri korunur: EMA20/50 + MACD onayı, geri çekilme
  girişi, rejim filtresi (RANGE'de trend girişi yok), sahte kırılım, hacim.
- Afişte ve JSON raporunda aktif motorlar görünür.

## Backtest karşılaştırması (son 3,5 gün, 12 sembol, gerçek veri, APEX)
| Konfigürasyon | İşlem | Net PnL | PF | Kazanma | Max DD |
|---|---|---|---|---|---|
| Her iki motor, varsayılan eşik | 65 | -6,29 | 0.94 | %47,7 | %4,5 |
| Her iki motor, gevşetilmiş | 135 | -50,97 | 0.74 | %47,4 | %5,8 |
| **TREND-only, gevşetilmiş** | 39 | **+25,71** | 1.55 | %59,0 | %2,8 |
| **TREND-only, varsayılan** | 32 | **+37,11** | **2.20** | **%62,5** | **%2,5** |

**Sonuç:** FADE kapatılınca strateji bu örneklemde kâra geçti. En iyi
kombinasyon: TREND-only + VARSAYILAN eşikler (RVOL 1.5 / spike 3.0).
FADE'in çıkardığı gürültü işlemleri hem kendi zararını hem de aynı sembolde
TREND'in önünü kesmesini engellemiş oldu.

## Test durumu
**224/224 test geçti** (214 v1.3 + 10 motor seçimi testi).

## Notlar
- 3,5 günlük örneklem küçüktür; kârlılık kanıtı değildir. Uzun walk-forward
  ve farklı rejimlerde doğrulama önerilir.
- Paket PAPER ONLY'dir; gerçek emir göndermez.
