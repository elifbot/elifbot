⚠️ ARA CHECKPOINT — planlı Shadow closeout değildir.

# Shadow Lab — eşleştirilmiş paper varyant raporu

> Ana strateji değiştirilmedi. Giriş varyantları aynı baseline kapanışını eşler; `net-exit` kendi çıkışını bağımsız çalıştırır. Gerçek emir yoktur. Tek oturum otomatik canlı kural değildir ve zararsızlık garanti edilmez.

| Varyant | Kabul / ret | Kapanan | K / Z | Brüt | Ücret | Funding | Net | PF | İlk 2 / net | Açık |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 20 / 0 | 20 | 13 / 7 | +41.84 | +9.98 | +0.03 | +31.89 | 4.23 | 41.2% | 0 |
| net-exit | 20 / 0 | 19 | 13 / 6 | +41.48 | +9.48 | +0.03 | +32.04 | 4.40 | 40.8% | 1 |
| flow-confidence | 0 / 20 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| volatility-gate | 18 / 2 | 18 | 13 / 5 | +41.93 | +8.98 | +0.01 | +32.96 | 4.74 | 39.8% | 0 |
| range-confirmation | 18 / 2 | 18 | 12 / 6 | +40.49 | +8.98 | +0.03 | +31.54 | 4.35 | 41.6% | 0 |
| technical-harmony | 14 / 6 | 14 | 9 / 5 | +30.24 | +6.98 | +0.03 | +23.28 | 3.85 | 56.4% | 0 |
| portfolio-guard | 20 / 0 | 20 | 13 / 7 | +41.84 | +9.98 | +0.03 | +31.89 | 4.23 | 41.2% | 0 |
| pdf-confluence | 16 / 4 | 16 | 10 / 6 | +32.89 | +7.98 | +0.03 | +24.94 | 3.65 | 52.6% | 0 |

## Kalite ve risk karşılaştırması

Drawdown yalnız kapanan işlemlerin realized-equity eğrisindendir. Elenen/kaçırılan kazanan, giriş varyantının reddettiği baseline işlemidir; net-exit için bu filtre metrikleri uygulanmaz.

| Varyant | Medyan net | Max DD | Korunan / elenen | Kaçırılan kazanan | Trailing maliyet zararı |
|---|---:|---:|---:|---:|---:|
| BASELINE | +1.95 | +7.21 | 20 / 0 | 0.0% | 1 / -0.46 |
| net-exit | +2.28 | +7.21 | 20 / 0 | 0.0% | 0 / +0.00 |
| flow-confidence | +0.00 | +0.00 | 0 / 20 | 100.0% | 0 / +0.00 |
| volatility-gate | +2.34 | +7.21 | 18 / 2 | 0.0% | 0 / +0.00 |
| range-confirmation | +2.34 | +7.21 | 18 / 2 | 7.7% | 0 / +0.00 |
| technical-harmony | +1.95 | +5.96 | 14 / 6 | 30.8% | 0 / +0.00 |
| portfolio-guard | +1.95 | +7.21 | 20 / 0 | 0.0% | 1 / -0.46 |
| pdf-confluence | +1.95 | +7.21 | 16 / 4 | 23.1% | 0 / +0.00 |

## Ret nedenleri

### flow-confidence
- 5 × emir defteri yok
- 1 × işlem sayısı 4<5; kapsama 10.3sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-15.9)
- 1 × kapsama 28.5sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-4.4)
- 1 × kapsama 28.2sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-10.3)
- 1 × işlem sayısı 3<5; kapsama 20.5sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-22.5)
- 1 × işlem sayısı 2<5; kapsama 38.4sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-17.9)
- 1 × emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-28.4)
- 1 × emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-20.6)
- 1 × emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-32.7)
- 1 × emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-22.9)
- 1 × işlem sayısı 4<5; emir defteri yok; defter yaşı 12.6sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-11.4)
- 1 × emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-27.3)
- 1 × emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-39.8)
- 1 × emir defteri yok; defter yaşı 15.6sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-38.9)
- 1 × emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-34.2)
- 1 × emir defteri yok; defter yaşı 30.8sn>10.0sn

### volatility-gate
- 2 × volatilite/maliyet hareket alanı yetersiz

### range-confirmation
- 2 × RANGE rejiminde yalnız para-akışı tetikli giriş

### technical-harmony
- 4 × karşıt teknik bileşen 2>1
- 2 × karşıt teknik bileşen 3>1

### pdf-confluence
- 4 × PDF v2 aile oyu/veri yetersiz

## Çıkış modülleri

### net-exit
- FLASH CRASH SİGORTASI: 12 işlem, net +1.99, K/Z 6/6
- KÂR KOŞUSU — ORDER-FLOW DÖNÜŞÜ: 7 işlem, net +30.05, K/Z 7/0

Kapanış mutabakatı: **EKSİK**.
Ayrıntılı karar, MFE/MAE, stop, maliyet ve işlem kayıtları eşlik eden JSON dosyasındadır.
