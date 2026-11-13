# ACARBOT FINAL v1.3 — Değişiklik Günlüğü (7 Kasım 2026)

Kullanıcı isteği: "Bir işlem görmek için gevşetilmiş eşikleri deneyelim."

## Yeni: sinyal eşikleri CLI'dan ayarlanabilir
Kod varsayılanları DEĞİŞMEDİ; bayrak verilmezse eski davranış birebir korunur.

| Bayrak | Varsayılan | Açıklama |
|---|---|---|
| `--min-rvol X` | 1.5 | 5m mum RVOL giriş eşiği (düşük = daha çok sinyal) |
| `--fade-impulse X` | 0.35 | FADE 10dk impuls eşiği (%) |
| `--spike-multiplier X` | 3.0 | canlı hacim patlaması çarpanı (>1 olmalı) |

- Paper ve backtest modlarında da geçerli; profillerle (apex/guarded) birleşir.
- Başlangıç afişinde aktif eşikler loglanır.
- Oturum JSON raporuna `signal_thresholds` alanı eklendi.
- Doğrulama: pozitif değerler zorunlu (spike çarpanı >1).

## Test durumu
**214/214 test geçti** (208 v1.2 + 6 yeni sinyal CLI testi).

## Karşılaştırmalı 15 dk test (bu sürümle)
Gevşetilmiş ayar: `--min-rvol 1.2 --fade-impulse 0.25 --spike-multiplier 2.5`
+ 12 sembol × 2 borsa (24 feed), APEX profili. Sonuç raporu ayrı dosyada.

## Not
Eşik gevşetmek işlem sayısını artırır ama sinyal kalitesini bir miktar
düşürür; uzun oturum + walk-forward ile karşılaştırma önerilir.
Paket PAPER ONLY'dir.
