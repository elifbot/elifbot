⚠️ ARA CHECKPOINT — planlı Shadow closeout değildir.

# Shadow Lab — eşleştirilmiş paper varyant raporu

> Ana strateji değiştirilmedi. Giriş varyantları aynı baseline kapanışını eşler; `net-exit` kendi çıkışını bağımsız çalıştırır. Gerçek emir yoktur. Tek oturum otomatik canlı kural değildir ve zararsızlık garanti edilmez.

| Varyant | Kabul / ret | Kapanan | K / Z | Brüt | Ücret | Funding | Net | PF | İlk 2 / net | Açık |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 9 / 0 | 9 | 2 / 7 | +0.10 | +3.15 | +0.00 | -3.05 | 0.26 | 0.0% | 0 |
| net-exit | 9 / 0 | 9 | 2 / 7 | +0.10 | +3.15 | +0.00 | -3.05 | 0.26 | — | 0 |
| flow-confidence | 0 / 9 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| volatility-gate | 9 / 0 | 9 | 2 / 7 | +0.10 | +3.15 | +0.00 | -3.05 | 0.26 | — | 0 |
| range-confirmation | 9 / 0 | 9 | 2 / 7 | +0.10 | +3.15 | +0.00 | -3.05 | 0.26 | — | 0 |
| technical-harmony | 8 / 1 | 8 | 1 / 7 | -0.53 | +2.80 | +0.00 | -3.33 | 0.19 | — | 0 |
| portfolio-guard | 9 / 0 | 9 | 2 / 7 | +0.10 | +3.15 | +0.00 | -3.05 | 0.26 | — | 0 |

## Kalite ve risk karşılaştırması

Drawdown yalnız kapanan işlemlerin realized-equity eğrisindendir. Elenen/kaçırılan kazanan, giriş varyantının reddettiği baseline işlemidir; net-exit için bu filtre metrikleri uygulanmaz.

| Varyant | Medyan net | Max DD | Korunan / elenen | Kaçırılan kazanan | Trailing maliyet zararı |
|---|---:|---:|---:|---:|---:|
| BASELINE | -0.13 | +3.60 | 9 / 0 | 0.0% | 0 / +0.00 |
| net-exit | -0.13 | +3.60 | 9 / 0 | 0.0% | 0 / +0.00 |
| flow-confidence | +0.00 | +0.00 | 0 / 9 | 100.0% | 0 / +0.00 |
| volatility-gate | -0.13 | +3.60 | 9 / 0 | 0.0% | 0 / +0.00 |
| range-confirmation | -0.13 | +3.60 | 9 / 0 | 0.0% | 0 / +0.00 |
| technical-harmony | -0.22 | +3.88 | 8 / 1 | 50.0% | 0 / +0.00 |
| portfolio-guard | -0.13 | +3.60 | 9 / 0 | 0.0% | 0 / +0.00 |

## Ret nedenleri

### flow-confidence
- 1 × işlem sayısı 3<5; kapsama 9.6sn<60.0sn; güven ayarlı karar=yok:skor yetersiz (-15.4)
- 1 × işlem sayısı 4<5; kapsama 18.0sn<60.0sn; güven ayarlı karar=yok:skor yetersiz (-22.2)
- 1 × defter yaşı 26.6sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-9.9)
- 1 × defter yaşı 30.0sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-23.4)
- 1 × güven ayarlı karar=yok:skor yetersiz (-23.3)
- 1 × defter yaşı 36.2sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-10.8)
- 1 × güven ayarlı karar=yok:skor yetersiz (-19.6)
- 1 × güven ayarlı karar=yok:skor yetersiz (-33.5)
- 1 × güven ayarlı karar=yok:skor yetersiz (-21.2)

### technical-harmony
- 1 × karşıt teknik bileşen 4>1

## Çıkış modülleri

### net-exit
- FLASH CRASH SİGORTASI: 9 işlem, net -3.05, K/Z 2/7

Kapanış mutabakatı: **TAMAM**.
Ayrıntılı karar, MFE/MAE, stop, maliyet ve işlem kayıtları eşlik eden JSON dosyasındadır.
