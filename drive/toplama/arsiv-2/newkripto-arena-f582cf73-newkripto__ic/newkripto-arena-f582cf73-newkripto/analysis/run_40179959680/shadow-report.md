# Shadow Lab — eşleştirilmiş paper varyant raporu

> Ana strateji değiştirilmedi. Giriş varyantları aynı baseline kapanışını eşler; `net-exit` kendi çıkışını bağımsız çalıştırır. Gerçek emir yoktur. Tek oturum otomatik canlı kural değildir ve zararsızlık garanti edilmez.

| Varyant | Kabul / ret | Kapanan | K / Z | Brüt | Ücret | Funding | Net | PF | İlk 2 / net | Açık |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 11 / 0 | 11 | 0 / 11 | -29.56 | +5.51 | +0.01 | -35.06 | 0.00 | 0.0% | 0 |
| net-exit | 11 / 0 | 11 | 0 / 11 | -29.56 | +5.51 | +0.01 | -35.06 | 0.00 | — | 0 |
| flow-confidence | 0 / 11 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| volatility-gate | 11 / 0 | 11 | 0 / 11 | -29.56 | +5.51 | +0.01 | -35.06 | 0.00 | — | 0 |
| range-confirmation | 11 / 0 | 11 | 0 / 11 | -29.56 | +5.51 | +0.01 | -35.06 | 0.00 | — | 0 |
| technical-harmony | 11 / 0 | 11 | 0 / 11 | -29.56 | +5.51 | +0.01 | -35.06 | 0.00 | — | 0 |
| portfolio-guard | 11 / 0 | 11 | 0 / 11 | -29.56 | +5.51 | +0.01 | -35.06 | 0.00 | — | 0 |
| pdf-confluence | 11 / 0 | 11 | 0 / 11 | -29.56 | +5.51 | +0.01 | -35.06 | 0.00 | — | 0 |
| pdf-v3-confluence | 11 / 0 | 11 | 0 / 11 | -29.56 | +5.51 | +0.01 | -35.06 | 0.00 | — | 0 |

## Kalite ve risk karşılaştırması

Drawdown yalnız kapanan işlemlerin realized-equity eğrisindendir. Elenen/kaçırılan kazanan, giriş varyantının reddettiği baseline işlemidir; net-exit için bu filtre metrikleri uygulanmaz.

| Varyant | Medyan net | Max DD | Korunan / elenen | Kaçırılan kazanan | Trailing maliyet zararı |
|---|---:|---:|---:|---:|---:|
| BASELINE | -3.08 | +35.06 | 11 / 0 | 0.0% | 0 / +0.00 |
| net-exit | -3.08 | +35.06 | 11 / 0 | — | 0 / +0.00 |
| flow-confidence | +0.00 | +0.00 | 0 / 11 | — | 0 / +0.00 |
| volatility-gate | -3.08 | +35.06 | 11 / 0 | — | 0 / +0.00 |
| range-confirmation | -3.08 | +35.06 | 11 / 0 | — | 0 / +0.00 |
| technical-harmony | -3.08 | +35.06 | 11 / 0 | — | 0 / +0.00 |
| portfolio-guard | -3.08 | +35.06 | 11 / 0 | — | 0 / +0.00 |
| pdf-confluence | -3.08 | +35.06 | 11 / 0 | — | 0 / +0.00 |
| pdf-v3-confluence | -3.08 | +35.06 | 11 / 0 | — | 0 / +0.00 |

## Ret nedenleri

### flow-confidence
- 1 × kapsama 7.2sn<60.0sn; güven ayarlı karar=yok:skor yetersiz (-30.0)
- 1 × kapsama 12.2sn<60.0sn; emir defteri yok; defter yaşı yok>10.0sn; güven ayarlı karar=yok:skor yetersiz (-22.0)
- 1 × kapsama 27.0sn<60.0sn; güven ayarlı karar=yok:skor yetersiz (-30.0)
- 1 × kapsama 27.4sn<60.0sn; defter yaşı 11.8sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-23.4)
- 1 × kapsama 32.1sn<60.0sn; defter yaşı 15.7sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-23.8)
- 1 × kapsama 48.4sn<60.0sn; güven ayarlı karar=yok:skor yetersiz (-26.1)
- 1 × kapsama 57.9sn<60.0sn; defter yaşı 14.2sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-31.1)
- 1 × kapsama 54.7sn<60.0sn; güven ayarlı karar=yok:skor yetersiz (-24.7)
- 1 × güven ayarlı karar=yok:skor yetersiz (-30.4)
- 1 × güven ayarlı karar=yok:skor yetersiz (-23.3)
- 1 × güven ayarlı karar=yok:skor yetersiz (-30.6)

## Çıkış modülleri

### net-exit
- SÜRELİ PAPER ÖLÇÜMÜ SONU: 11 işlem, net -35.06, K/Z 0/11

Kapanış mutabakatı: **TAMAM**.
Ayrıntılı karar, MFE/MAE, stop, maliyet ve işlem kayıtları eşlik eden JSON dosyasındadır.
