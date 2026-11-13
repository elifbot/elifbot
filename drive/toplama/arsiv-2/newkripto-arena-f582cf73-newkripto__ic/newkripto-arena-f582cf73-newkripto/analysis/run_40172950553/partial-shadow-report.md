⚠️ ARA CHECKPOINT — planlı Shadow closeout değildir.

# Shadow Lab — eşleştirilmiş paper varyant raporu

> Ana strateji değiştirilmedi. Giriş varyantları aynı baseline kapanışını eşler; `net-exit` kendi çıkışını bağımsız çalıştırır. Gerçek emir yoktur. Tek oturum otomatik canlı kural değildir ve zararsızlık garanti edilmez.

| Varyant | Kabul / ret | Kapanan | K / Z | Brüt | Ücret | Funding | Net | PF | İlk 2 / net | Açık |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 10 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | 0.0% | 0 |
| net-exit | 10 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 10 |
| flow-confidence | 0 / 10 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| volatility-gate | 8 / 2 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 8 |
| range-confirmation | 9 / 1 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 9 |
| technical-harmony | 6 / 4 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 6 |
| portfolio-guard | 10 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 10 |
| pdf-confluence | 8 / 2 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 8 |

## Kalite ve risk karşılaştırması

Drawdown yalnız kapanan işlemlerin realized-equity eğrisindendir. Elenen/kaçırılan kazanan, giriş varyantının reddettiği baseline işlemidir; net-exit için bu filtre metrikleri uygulanmaz.

| Varyant | Medyan net | Max DD | Korunan / elenen | Kaçırılan kazanan | Trailing maliyet zararı |
|---|---:|---:|---:|---:|---:|
| BASELINE | +0.00 | +0.00 | 0 / 0 | 0.0% | 0 / +0.00 |
| net-exit | +0.00 | +0.00 | 0 / 0 | — | 0 / +0.00 |
| flow-confidence | +0.00 | +0.00 | 0 / 0 | — | 0 / +0.00 |
| volatility-gate | +0.00 | +0.00 | 0 / 0 | — | 0 / +0.00 |
| range-confirmation | +0.00 | +0.00 | 0 / 0 | — | 0 / +0.00 |
| technical-harmony | +0.00 | +0.00 | 0 / 0 | — | 0 / +0.00 |
| portfolio-guard | +0.00 | +0.00 | 0 / 0 | — | 0 / +0.00 |
| pdf-confluence | +0.00 | +0.00 | 0 / 0 | — | 0 / +0.00 |

## Ret nedenleri

### flow-confidence
- 1 × işlem sayısı 2<5; kapsama 13.1sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-20.9)
- 1 × kapsama 32.0sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-19.1)
- 1 × işlem sayısı 2<5; kapsama 26.8sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-15.8)
- 1 × işlem sayısı 2<5; kapsama 41.3sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-22.6)
- 1 × işlem sayısı 3<5; kapsama 32.8sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (+18.1)
- 1 × emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-21.7)
- 1 × işlem sayısı 1<5; emir defteri yok; defter yaşı 34.4sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (+10.9)
- 1 × işlem sayısı 3<5; emir defteri yok; defter yaşı 14.9sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-14.5)
- 1 × işlem sayısı 2<5; emir defteri yok; defter yaşı yok>10.0sn; güven ayarlı karar=yok:skor yetersiz (+11.2)
- 1 × emir defteri yok; defter yaşı 20.1sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-26.2)

### volatility-gate
- 2 × volatilite/maliyet hareket alanı yetersiz

### range-confirmation
- 1 × RANGE rejiminde yalnız para-akışı tetikli giriş

### technical-harmony
- 4 × karşıt teknik bileşen 2>1

### pdf-confluence
- 2 × PDF v2 aile oyu/veri yetersiz

## Çıkış modülleri

### net-exit

Kapanış mutabakatı: **EKSİK**.
Ayrıntılı karar, MFE/MAE, stop, maliyet ve işlem kayıtları eşlik eden JSON dosyasındadır.
