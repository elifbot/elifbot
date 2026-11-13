# ACARBOT Doğrulama Raporu — 5.2-final

**Üretim:** 2026-11-07T22:43:51+00:00
**Veri:** okx · 6 sembol · 90 gün · 155520 adet 5m bar
**1m alt çözünürlük:** targeted · 1310 bar · 5 sembol
**Profil:** apex · işlem başı TABAN net risk 25.0 USDT

## 1m kapsamı (iki geçişli)

- Geçiş sayısı: **2** · hedeflenen aralık: 14 · istek: 21
- Kazanılan 1m bar: **1310** · boş aralık: 0 · hata: 0

| Geçiş | Gerçek 1m bar | Sentetik bar | Kapsama |
|---|---|---|---|
| 1 | 0 | 234 | %0.0 |
| 2 | 235 | 18 | %92.9 |

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
| birincil (karma yol (gerçek 1m %92.9)) | real_1m | -80.4766 | 14 | 28.6% | 0.0749 | 80.4766 | 99.9% |
| sentetik ALT sınır (kötümser) (sentetik yol (1m YOK)) | adverse_first | -80.2827 | 14 | 28.6% | 0.0715 | 80.2827 | 99.9% |
| sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK)) | favorable_first | -80.5094 | 14 | 28.6% | 0.0435 | 80.5094 | 100.0% |
| maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %75.6) · MALİYETSİZ) | real_1m | -80.5242 | 16 | 37.5% | 0.0899 | 80.5242 | 99.8% |

## İyimserlik farkı (maliyetlerin etkisi)

- Maliyetli net: **-80.4766** USDT · 14 işlem
- Maliyetsiz net: **-80.5242** USDT · 16 işlem
- **Fark: -0.0476 USDT** (maliyetsiz koşu bu kadar iyimser)

## Sentetik sınır aralığı (mum içi belirsizlik)

- Kötümser (ALT): **-80.2827** USDT · 14 işlem
- İyimser (ÜST): **-80.5094** USDT · 14 işlem
- **Genişlik: 0.2267 USDT** — mum içi sıra bilinmediğinde sonuç bu aralıkta belirsizdir.

## Dinamik risk ölçekleme (v5.2)

- **birincil (karma yol (gerçek 1m %92.9))**: 1031 bütçe · ort ölçek 0.006 · min ölçek 0.000 · maliyet kapısı reddi 90 · bağlayan: {'cost': 1, 'drawdown': 1029, 'recovery': 1}
- **sentetik ALT sınır (kötümser) (sentetik yol (1m YOK))**: 1031 bütçe · ort ölçek 0.005 · min ölçek 0.000 · maliyet kapısı reddi 90 · bağlayan: {'cost': 1, 'drawdown': 1029, 'recovery': 1}
- **sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK))**: 1031 bütçe · ort ölçek 0.005 · min ölçek 0.000 · maliyet kapısı reddi 90 · bağlayan: {'cost': 1, 'drawdown': 1030}
- **maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %75.6) · MALİYETSİZ)**: 1120 bütçe · ort ölçek 0.006 · min ölçek 0.000 · maliyet kapısı reddi 0 · bağlayan: {'drawdown': 1119, 'recovery': 1}

## Risk denetimi (gerçekleşen / hedef kayıp)

- **birincil (karma yol (gerçek 1m %92.9))**: 10 zararlı işlem · ort 0.971x · maks 1.346x · aşım 1/10 (eşik 1.3x) · maks stop aşımı 0.775x
- **sentetik ALT sınır (kötümser) (sentetik yol (1m YOK))**: 10 zararlı işlem · ort 0.971x · maks 1.346x · aşım 1/10 (eşik 1.3x) · maks stop aşımı 0.775x
- **sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK))**: 10 zararlı işlem · ort 0.971x · maks 1.346x · aşım 1/10 (eşik 1.3x) · maks stop aşımı 0.775x
- **maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %75.6) · MALİYETSİZ)**: 10 zararlı işlem · ort 0.969x · maks 1.346x · aşım 1/10 (eşik 1.3x) · maks stop aşımı 8.386x

## Rejim kırılımı

### birincil (karma yol (gerçek 1m %92.9))

| Rejim | İşlem | Net PnL | Kazanma |
|---|---|---|---|
| TREND_DOWN | 5 | -61.0774 | 20.0% |
| TREND_UP | 5 | -11.4000 | 20.0% |
| STRONG_TREND_DOWN | 2 | -7.1008 | 50.0% |
| STRONG_TREND_UP | 1 | -1.1827 | 0.0% |
| UNCERTAIN | 1 | 0.2844 | 100.0% |

### sentetik ALT sınır (kötümser) (sentetik yol (1m YOK))

| Rejim | İşlem | Net PnL | Kazanma |
|---|---|---|---|
| TREND_DOWN | 5 | -61.5219 | 20.0% |
| TREND_UP | 5 | -10.7616 | 20.0% |
| STRONG_TREND_DOWN | 2 | -7.1008 | 50.0% |
| STRONG_TREND_UP | 1 | -1.1827 | 0.0% |
| UNCERTAIN | 1 | 0.2844 | 100.0% |

### sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK))

| Rejim | İşlem | Net PnL | Kazanma |
|---|---|---|---|
| TREND_DOWN | 5 | -63.3623 | 20.0% |
| TREND_UP | 5 | -9.1480 | 20.0% |
| STRONG_TREND_DOWN | 2 | -7.1008 | 50.0% |
| STRONG_TREND_UP | 1 | -1.1827 | 0.0% |
| UNCERTAIN | 1 | 0.2844 | 100.0% |

### maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %75.6) · MALİYETSİZ)

| Rejim | İşlem | Net PnL | Kazanma |
|---|---|---|---|
| TREND_UP | 7 | -12.5224 | 28.6% |
| TREND_DOWN | 5 | -60.0046 | 40.0% |
| STRONG_TREND_DOWN | 2 | -7.1070 | 50.0% |
| STRONG_TREND_UP | 1 | -1.1813 | 0.0% |
| UNCERTAIN | 1 | 0.2910 | 100.0% |

## Walk-forward

- **birincil (karma yol (gerçek 1m %92.9))**: 0/6 pencere kârlı · 242 işlem · toplam -390.6141 USDT · en kötü pencere -81.2242 USDT

| Pencere | İşlem | Net PnL | Kazanma | Maks DD | Kârlı |
|---|---|---|---|---|---|
| 1 | 14 | -80.4766 | 28.6% | 8.05% | ❌ |
| 2 | 58 | -39.2963 | 46.6% | 8.01% | ❌ |
| 3 | 101 | -76.4027 | 49.5% | 8.08% | ❌ |
| 4 | 4 | -69.8761 | 25.0% | 7.90% | ❌ |
| 5 | 36 | -81.2242 | 41.7% | 8.12% | ❌ |
| 6 | 29 | -43.3381 | 48.3% | 8.07% | ❌ |

- **sentetik ALT sınır (kötümser) (sentetik yol (1m YOK))**: koşulmadı
- **sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK))**: koşulmadı
- **maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %75.6) · MALİYETSİZ)**: koşulmadı
## Red sayaçları

- **birincil (karma yol (gerçek 1m %92.9))**: dusuk_hacim=126458, fade_kosulu_yok=12703, guclu_trend_fade_kapali=5696, fake_breakout_or_suspect=3624, rejim_uyumsuz=2476, yukselen_bicak=1323, dusen_bicak=1207, PORTFOLIO_DRAWDOWN_PROTECTION=1012
- **sentetik ALT sınır (kötümser) (sentetik yol (1m YOK))**: dusuk_hacim=126476, fade_kosulu_yok=12703, guclu_trend_fade_kapali=5697, fake_breakout_or_suspect=3624, rejim_uyumsuz=2476, yukselen_bicak=1323, dusen_bicak=1207, PORTFOLIO_DRAWDOWN_PROTECTION=1012
- **sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK))**: dusuk_hacim=126491, fade_kosulu_yok=12703, guclu_trend_fade_kapali=5699, fake_breakout_or_suspect=3624, rejim_uyumsuz=2476, yukselen_bicak=1323, dusen_bicak=1207, PORTFOLIO_DRAWDOWN_PROTECTION=1012
- **maliyetsiz karşılaştırma (İYİMSER) (karma yol (gerçek 1m %75.6) · MALİYETSİZ)**: dusuk_hacim=126415, fade_kosulu_yok=12697, guclu_trend_fade_kapali=5692, fake_breakout_or_suspect=3621, rejim_uyumsuz=2472, yukselen_bicak=1323, dusen_bicak=1207, PORTFOLIO_DRAWDOWN_PROTECTION=1099

## Hüküm

**Kod:** `NO_EDGE` · **Önem:** red

🔴 **KENAR YOK — walk-forward tüm pencerelerde zararlı**

- Walk-forward: 242 işlem, 0/6 pencere kârlı, toplam -390.61 USDT.
- En kötü pencere -81.22 USDT. Hiçbir alt dönemde kâr yok — tek dönemlik şans açıklaması geçersiz.
- Birincil koşu: 14 işlem, net -80.48 USDT, Monte Carlo kayıp olasılığı %99.9.
- Birincil koşunun örneklemi KESİLMİŞ: 1012 giriş drawdown korumasıyla reddedildi (açılan işlem başına 72.3 red). Az işlem bir belirsizlik değil, kaybın sonucu.
- Ayrıca 1 işlemde gerçekleşen kayıp hedefin 1.3 katını aştı (maks 1.346x).
- Gerçek paraya ölçekleme YAPILMAMALIDIR. `max_loss_per_position` 2,5–5 USDT'de tutulmalı.
