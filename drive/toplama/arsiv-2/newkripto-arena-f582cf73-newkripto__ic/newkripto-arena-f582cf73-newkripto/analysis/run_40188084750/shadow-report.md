# Shadow Lab — eşleştirilmiş paper varyant raporu

> Ana strateji değiştirilmedi. Giriş varyantları aynı baseline kapanışını eşler; `net-exit` kendi çıkışını bağımsız çalıştırır. Gerçek emir yoktur. Tek oturum otomatik canlı kural değildir ve zararsızlık garanti edilmez.

| Varyant | Kabul / ret | Kapanan | K / Z | Brüt | Ücret | Funding | Net | PF | İlk 2 / net | Açık |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 13 / 0 | 13 | 6 / 7 | -2.40 | +6.36 | -0.01 | -8.77 | 0.63 | 0.0% | 0 |
| net-exit | 13 / 0 | 13 | 8 / 5 | +11.35 | +6.35 | -0.00 | +4.99 | 3.01 | 88.6% | 0 |
| flow-confidence | 13 / 0 | 13 | 6 / 7 | -2.40 | +6.36 | -0.01 | -8.77 | 0.63 | — | 0 |
| volatility-gate | 13 / 0 | 13 | 6 / 7 | -2.40 | +6.36 | -0.01 | -8.77 | 0.63 | — | 0 |
| range-confirmation | 9 / 4 | 9 | 4 / 5 | +6.12 | +4.36 | -0.01 | +1.75 | 1.14 | 696.1% | 0 |
| technical-harmony | 3 / 10 | 3 | 3 / 0 | +14.25 | +1.36 | +0.00 | +12.89 | ∞ | 94.2% | 0 |
| portfolio-guard | 13 / 0 | 13 | 6 / 7 | -2.40 | +6.36 | -0.01 | -8.77 | 0.63 | — | 0 |
| pdf-confluence | 6 / 7 | 6 | 3 / 3 | +11.90 | +2.86 | -0.01 | +9.03 | 3.34 | 134.5% | 0 |
| pdf-v3-confluence | 9 / 4 | 9 | 5 / 4 | +7.79 | +4.36 | +0.00 | +3.44 | 1.30 | 360.1% | 0 |

## Kalite ve risk karşılaştırması

Drawdown yalnız kapanan işlemlerin realized-equity eğrisindendir. Elenen/kaçırılan kazanan, giriş varyantının reddettiği baseline işlemidir; net-exit için bu filtre metrikleri uygulanmaz.

| Varyant | Medyan net | Max DD | Korunan / elenen | Kaçırılan kazanan | Trailing maliyet zararı |
|---|---:|---:|---:|---:|---:|
| BASELINE | -0.35 | +17.26 | 13 / 0 | 0.0% | 0 / +0.00 |
| net-exit | +0.14 | +1.06 | 13 / 0 | 0.0% | 0 / +0.00 |
| flow-confidence | -0.35 | +17.26 | 13 / 0 | 0.0% | 0 / +0.00 |
| volatility-gate | -0.35 | +17.26 | 13 / 0 | 0.0% | 0 / +0.00 |
| range-confirmation | -0.51 | +5.85 | 9 / 4 | 33.3% | 0 / +0.00 |
| technical-harmony | +0.93 | +0.00 | 3 / 10 | 50.0% | 0 / +0.00 |
| portfolio-guard | -0.35 | +17.26 | 13 / 0 | 0.0% | 0 / +0.00 |
| pdf-confluence | +0.12 | +3.30 | 6 / 7 | 50.0% | 0 / +0.00 |
| pdf-v3-confluence | +0.75 | +5.85 | 9 / 4 | 16.7% | 0 / +0.00 |

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
- SÜRELİ PAPER ÖLÇÜMÜ SONU: 8 işlem, net +2.61, K/Z 5/3
- SÜRELİ PAPER ÖLÇÜMÜ SONU — SHADOW: 4 işlem, net -0.86, K/Z 2/2

Kapanış mutabakatı: **TAMAM**.
Ayrıntılı karar, MFE/MAE, stop, maliyet ve işlem kayıtları eşlik eden JSON dosyasındadır.
