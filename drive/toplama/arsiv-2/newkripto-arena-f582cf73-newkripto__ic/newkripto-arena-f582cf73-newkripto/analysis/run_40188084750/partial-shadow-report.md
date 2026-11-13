⚠️ ARA CHECKPOINT — planlı Shadow closeout değildir.

# Shadow Lab — eşleştirilmiş paper varyant raporu

> Ana strateji değiştirilmedi. Giriş varyantları aynı baseline kapanışını eşler; `net-exit` kendi çıkışını bağımsız çalıştırır. Gerçek emir yoktur. Tek oturum otomatik canlı kural değildir ve zararsızlık garanti edilmez.

| Varyant | Kabul / ret | Kapanan | K / Z | Brüt | Ücret | Funding | Net | PF | İlk 2 / net | Açık |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 13 / 0 | 8 | 2 / 6 | -7.84 | +3.87 | -0.01 | -11.71 | 0.51 | 0.0% | 0 |
| net-exit | 13 / 0 | 4 | 2 / 2 | +4.78 | +1.85 | -0.01 | +2.91 | 3.69 | 137.1% | 9 |
| flow-confidence | 13 / 0 | 8 | 2 / 6 | -7.84 | +3.87 | -0.01 | -11.71 | 0.51 | — | 5 |
| volatility-gate | 13 / 0 | 8 | 2 / 6 | -7.84 | +3.87 | -0.01 | -11.71 | 0.51 | — | 5 |
| range-confirmation | 9 / 4 | 7 | 2 / 5 | +3.24 | +3.36 | -0.01 | -0.14 | 0.99 | — | 2 |
| technical-harmony | 3 / 10 | 2 | 2 / 0 | +12.82 | +0.86 | +0.00 | +11.97 | ∞ | 100.0% | 1 |
| portfolio-guard | 13 / 0 | 8 | 2 / 6 | -7.84 | +3.87 | -0.01 | -11.71 | 0.51 | — | 5 |
| pdf-confluence | 6 / 7 | 5 | 2 / 3 | +10.47 | +2.36 | -0.01 | +8.10 | 3.10 | 147.7% | 1 |
| pdf-v3-confluence | 9 / 4 | 6 | 2 / 4 | +3.24 | +2.86 | +0.00 | +0.38 | 1.03 | 3169.3% | 3 |

## Kalite ve risk karşılaştırması

Drawdown yalnız kapanan işlemlerin realized-equity eğrisindendir. Elenen/kaçırılan kazanan, giriş varyantının reddettiği baseline işlemidir; net-exit için bu filtre metrikleri uygulanmaz.

| Varyant | Medyan net | Max DD | Korunan / elenen | Kaçırılan kazanan | Trailing maliyet zararı |
|---|---:|---:|---:|---:|---:|
| BASELINE | -1.48 | +17.26 | 8 / 0 | 0.0% | 0 / +0.00 |
| net-exit | +0.12 | +0.57 | 8 / 0 | 0.0% | 0 / +0.00 |
| flow-confidence | -1.48 | +17.26 | 8 / 0 | 0.0% | 0 / +0.00 |
| volatility-gate | -1.48 | +17.26 | 8 / 0 | 0.0% | 0 / +0.00 |
| range-confirmation | -0.57 | +5.85 | 7 / 1 | 0.0% | 0 / +0.00 |
| technical-harmony | +5.98 | +0.00 | 2 / 6 | 0.0% | 0 / +0.00 |
| portfolio-guard | -1.48 | +17.26 | 8 / 0 | 0.0% | 0 / +0.00 |
| pdf-confluence | -0.51 | +3.30 | 5 / 3 | 0.0% | 0 / +0.00 |
| pdf-v3-confluence | -1.48 | +5.85 | 6 / 2 | 0.0% | 0 / +0.00 |

## Ret nedenleri

### range-confirmation
- 4 × RANGE rejiminde yalnız para-akışı tetikli giriş

### technical-harmony
- 6 × karşıt teknik bileşen 2>1
- 4 × karşıt teknik bileşen 3>1

### pdf-confluence
- 7 × PDF v2 aile oyu/veri yetersiz

### pdf-v3-confluence
- 4 × PDF v3 + türev istihbarat uyumu yetersiz

## Çıkış modülleri

### net-exit
- KÂR KOŞUSU — ORDER-FLOW DÖNÜŞÜ: 1 işlem, net +3.24, K/Z 1/0
- SÜRELİ PAPER ÖLÇÜMÜ SONU: 3 işlem, net -0.33, K/Z 1/2

Kapanış mutabakatı: **EKSİK**.
Ayrıntılı karar, MFE/MAE, stop, maliyet ve işlem kayıtları eşlik eden JSON dosyasındadır.
