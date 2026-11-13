⚠️ ARA CHECKPOINT — planlı Shadow closeout değildir.

# Shadow Lab — eşleştirilmiş paper varyant raporu

> Ana strateji değiştirilmedi. Giriş varyantları aynı baseline kapanışını eşler; `net-exit` kendi çıkışını bağımsız çalıştırır. Gerçek emir yoktur. Tek oturum otomatik canlı kural değildir ve zararsızlık garanti edilmez.

| Varyant | Kabul / ret | Kapanan | K / Z | Brüt | Ücret | Funding | Net | PF | İlk 2 / net | Açık |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 11 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | 0.0% | 0 |
| net-exit | 11 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 11 |
| flow-confidence | 0 / 11 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| volatility-gate | 11 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 11 |
| range-confirmation | 11 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 11 |
| technical-harmony | 8 / 3 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 8 |
| portfolio-guard | 11 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 11 |
| pdf-confluence | 7 / 4 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 7 |

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
- 1 × kapsama 3.9sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-13.8)
- 1 × işlem sayısı 2<5; kapsama 12.1sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-17.6)
- 1 × kapsama 15.9sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-24.7)
- 1 × kapsama 16.1sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-14.5)
- 1 × işlem sayısı 4<5; kapsama 20.1sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-22.9)
- 1 × işlem sayısı 2<5; kapsama 38.2sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-22.1)
- 1 × kapsama 46.8sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-14.4)
- 1 × kapsama 38.3sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-18.7)
- 1 × işlem sayısı 4<5; kapsama 51.7sn<60.0sn; emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-19.3)
- 1 × işlem sayısı 3<5; emir defteri yok; defter yaşı 14.7sn>10.0sn; güven ayarlı karar=yok:skor yetersiz (-23.0)
- 1 × emir defteri yok; güven ayarlı karar=yok:skor yetersiz (-20.2)

### technical-harmony
- 3 × karşıt teknik bileşen 2>1

### pdf-confluence
- 4 × PDF v2 aile oyu/veri yetersiz

## Çıkış modülleri

### net-exit

Kapanış mutabakatı: **EKSİK**.
Ayrıntılı karar, MFE/MAE, stop, maliyet ve işlem kayıtları eşlik eden JSON dosyasındadır.
