# ACARBOT Doğrulama Raporu — 5.4-final

**Üretim:** 2026-11-08T09:43:06+00:00
**Veri:** okx · 6 sembol · 90 gün · 155520 adet 5m bar
**1m alt çözünürlük:** targeted · 11385 bar · 6 sembol
**Profil:** apex · işlem başı TABAN net risk 25.0 USDT

## 1m kapsamı (iki geçişli)

- Geçiş sayısı: **1** · hedeflenen aralık: 899 · istek: 0
- Kazanılan 1m bar: **0** · boş aralık: 0 · hata: 0

| Geçiş | Gerçek 1m bar | Sentetik bar | Kapsama |
|---|---|---|---|
| 1 | 225 | 22 | %91.1 |

## Maliyet modeli

Maliyet modeli: 10 sembol ölçüldü · ölçüm anı 2026-11-07T21:58:04+00:00 · binance: VARSAYIM (ÖLÇÜLMEDİ) spread 1.50bps, kayma 2.00bps, çıkış 3.00bps, gecikme 250ms | okx: 10 sembol ÖLÇÜLDÜ (sembol bazlı değerler kullanılır); ölçülmeyenler için VARSAYIM spread 1.13bps, kayma 23.56bps, çıkış 25.63bps, gecikme 350ms · VERİ KÜMESİ KAPSAMASI 6/6 (%100)

**Veri kümesi kapsamasi:** 6/6 sembol ölçülmüş (%100).

| Borsa | Kaynak | Ölçülen sembol | Varsayılan kayma |
|---|---|---|---|
| binance | **VARSAYIM — ÖLÇÜLMEDİ** | 0 | 2.00 bps |
| okx | ÖLÇÜLDÜ (sembol bazlı) | 10 | 23.56 bps |

**Ölçüm tabanı:** 24 örnek/sembol · 4 tur · pencere 148 sn · değerlendirme: **adequate**

## Koşular

| Koşu | Yol kaynağı | Net PnL | İşlem | Kazanma | PF | Maks DD | MC kayıp olasılığı |
|---|---|---|---|---|---|---|---|
| birincil (karma yol (gerçek 1m %91.1)) | real_1m | -80.5192 | 12 | 33.3% | 0.0781 | 80.5192 | 99.7% |
| sentetik ALT sınır (kötümser) (sentetik yol (1m YOK)) | adverse_first | 0.0000 | 0 | 0.0% | 0.0000 | 0.0000 | 0.0% |
| sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK)) | favorable_first | 0.0000 | 0 | 0.0% | 0.0000 | 0.0000 | 0.0% |
| maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %86.2) · MALİYETSİZ) | real_1m | -80.5361 | 13 | 38.5% | 0.0864 | 80.5361 | 99.7% |

## İyimserlik farkı (maliyetlerin etkisi)

- Maliyetli net: **-80.5192** USDT · 12 işlem
- Maliyetsiz net: **-80.5361** USDT · 13 işlem
- **Fark: -0.0169 USDT** (maliyetsiz koşu bu kadar iyimser)

## Sentetik sınır aralığı (mum içi belirsizlik)

- Kötümser (ALT): **0.0000** USDT · 0 işlem
- İyimser (ÜST): **0.0000** USDT · 0 işlem
- **Genişlik: 0.0000 USDT** — mum içi sıra bilinmediğinde sonuç bu aralıkta belirsizdir.

> 🟡 Aralık sıfırı KAPSIYOR: tek bir sayı ile kârlılık iddia edilemez. Gerçek 1m kapsaması artırılmalı.

## Dinamik risk ölçekleme (v5.2)

- **birincil (karma yol (gerçek 1m %91.1))**: 19 bütçe · ort ölçek 0.337 · min ölçek 0.174 · maliyet kapısı reddi 1103 · bağlayan: {'drawdown': 17, 'none': 2}
- **sentetik ALT sınır (kötümser) (sentetik yol (1m YOK))**: 994 bütçe · ort ölçek 0.893 · min ölçek 0.105 · maliyet kapısı reddi 133 · bağlayan: {'cost': 220, 'none': 774}
- **sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK))**: 994 bütçe · ort ölçek 0.893 · min ölçek 0.105 · maliyet kapısı reddi 133 · bağlayan: {'cost': 220, 'none': 774}
- **maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %86.2) · MALİYETSİZ)**: 22 bütçe · ort ölçek 0.330 · min ölçek 0.181 · maliyet kapısı reddi 1099 · bağlayan: {'drawdown': 20, 'none': 2}

## Risk denetimi (gerçekleşen / hedef kayıp)

- **birincil (karma yol (gerçek 1m %91.1))**: 8 zararlı işlem · ort 0.983x · maks 1.346x · aşım 1/8 (eşik 1.3x) · maks stop aşımı 0.775x
- **sentetik ALT sınır (kötümser) (sentetik yol (1m YOK))**: 0 zararlı işlem · ort 0.000x · maks 0.000x · aşım 0/0 (eşik 1.3x) · maks stop aşımı 0.000x
- **sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK))**: 0 zararlı işlem · ort 0.000x · maks 0.000x · aşım 0/0 (eşik 1.3x) · maks stop aşımı 0.000x
- **maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %86.2) · MALİYETSİZ)**: 8 zararlı işlem · ort 0.983x · maks 1.346x · aşım 1/8 (eşik 1.3x) · maks stop aşımı 8.386x

## Rejim kırılımı

### birincil (karma yol (gerçek 1m %91.1))

| Rejim | İşlem | Net PnL | Kazanma |
|---|---|---|---|
| TREND_UP | 5 | -17.5471 | 20.0% |
| TREND_DOWN | 3 | -54.9730 | 33.3% |
| STRONG_TREND_DOWN | 2 | -7.1008 | 50.0% |
| STRONG_TREND_UP | 1 | -1.1827 | 0.0% |
| UNCERTAIN | 1 | 0.2844 | 100.0% |

### maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %86.2) · MALİYETSİZ)

| Rejim | İşlem | Net PnL | Kazanma |
|---|---|---|---|
| TREND_UP | 6 | -17.8030 | 33.3% |
| TREND_DOWN | 3 | -54.7359 | 33.3% |
| STRONG_TREND_DOWN | 2 | -7.1070 | 50.0% |
| STRONG_TREND_UP | 1 | -1.1813 | 0.0% |
| UNCERTAIN | 1 | 0.2910 | 100.0% |

## Walk-forward

- **birincil (karma yol (gerçek 1m %91.1))**: 0/6 pencere kârlı · 104 işlem · toplam -301.6891 USDT · en kötü pencere -80.5192 USDT

| Pencere | İşlem | Net PnL | Kazanma | Maks DD | Kârlı |
|---|---|---|---|---|---|
| 1 | 12 | -80.5192 | 33.3% | 8.05% | ❌ |
| 2 | 34 | -12.9595 | 52.9% | 7.40% | ❌ |
| 3 | 16 | -30.4648 | 75.0% | 8.01% | ❌ |
| 4 | 8 | -72.2134 | 25.0% | 7.49% | ❌ |
| 5 | 11 | -76.7337 | 36.4% | 8.28% | ❌ |
| 6 | 23 | -28.7984 | 52.2% | 6.66% | ❌ |

- **sentetik ALT sınır (kötümser) (sentetik yol (1m YOK))**: koşulmadı
- **sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK))**: koşulmadı
- **maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %86.2) · MALİYETSİZ)**: koşulmadı
## Red sayaçları

- **birincil (karma yol (gerçek 1m %91.1))**: dusuk_hacim=126489, fade_kosulu_yok=12706, guclu_trend_fade_kapali=5696, fake_breakout_or_suspect=3624, rejim_uyumsuz=2476, yukselen_bicak=1323, dusen_bicak=1207, OLCEK_TABAN_ALTINDA=1013
- **sentetik ALT sınır (kötümser) (sentetik yol (1m YOK))**: dusuk_hacim=126692, fade_kosulu_yok=12729, guclu_trend_fade_kapali=5704, fake_breakout_or_suspect=3624, rejim_uyumsuz=2480, yukselen_bicak=1323, dusen_bicak=1207, limit_bekliyor=994
- **sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK))**: dusuk_hacim=126692, fade_kosulu_yok=12729, guclu_trend_fade_kapali=5704, fake_breakout_or_suspect=3624, rejim_uyumsuz=2480, yukselen_bicak=1323, dusen_bicak=1207, limit_bekliyor=994
- **maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %86.2) · MALİYETSİZ)**: dusuk_hacim=126475, fade_kosulu_yok=12706, guclu_trend_fade_kapali=5693, fake_breakout_or_suspect=3623, rejim_uyumsuz=2476, yukselen_bicak=1323, dusen_bicak=1207, OLCEK_TABAN_ALTINDA=1099

## Hüküm

**Kod:** `NO_EDGE` · **Önem:** red

🔴 **KENAR YOK — walk-forward tüm pencerelerde zararlı**

- Walk-forward: 104 işlem, 0/6 pencere kârlı, toplam -301.69 USDT.
- En kötü pencere -80.52 USDT. Hiçbir alt dönemde kâr yok — tek dönemlik şans açıklaması geçersiz.
- Birincil koşu: 12 işlem, net -80.52 USDT, Monte Carlo kayıp olasılığı %99.7.
- Ayrıca 1 işlemde gerçekleşen kayıp hedefin 1.3 katını aştı (maks 1.346x).
- Gerçek paraya ölçekleme YAPILMAMALIDIR. `max_loss_per_position` 2,5–5 USDT'de tutulmalı.
