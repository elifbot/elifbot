⚠️ ARA CHECKPOINT — planlı Shadow closeout değildir.

# Shadow Lab — eşleştirilmiş paper varyant raporu

> Ana strateji değiştirilmedi. Giriş varyantları aynı baseline kapanışını eşler; `net-exit` kendi çıkışını bağımsız çalıştırır. Gerçek emir yoktur. Tek oturum otomatik canlı kural değildir ve zararsızlık garanti edilmez.

| Varyant | Kabul / ret | Kapanan | K / Z | Brüt | Ücret | Funding | Net | PF | İlk 2 / net | Açık |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 0 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | 0.0% | 0 |
| net-exit | 0 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| flow-confidence | 0 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| volatility-gate | 0 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| range-confirmation | 0 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| technical-harmony | 0 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| portfolio-guard | 0 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |
| pdf-confluence | 0 / 0 | 0 | 0 / 0 | +0.00 | +0.00 | +0.00 | +0.00 | ∞ | — | 0 |

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

## Çıkış modülleri

### net-exit

Kapanış mutabakatı: **TAMAM**.
Ayrıntılı karar, MFE/MAE, stop, maliyet ve işlem kayıtları eşlik eden JSON dosyasındadır.
