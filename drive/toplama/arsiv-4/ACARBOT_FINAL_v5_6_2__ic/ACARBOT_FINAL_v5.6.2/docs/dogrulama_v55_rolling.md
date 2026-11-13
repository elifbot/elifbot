# ACARBOT Doğrulama Raporu — 5.5-final

**Üretim:** 2026-11-08T10:53:38+00:00
**Veri:** okx · 6 sembol · 90 gün · 155520 adet 5m bar
**1m alt çözünürlük:** targeted · 11385 bar · 6 sembol
**Profil:** apex · işlem başı TABAN net risk 25.0 USDT

## 1m kapsamı (iki geçişli)

- Geçiş sayısı: **1** · hedeflenen aralık: 0 · istek: 0
- Kazanılan 1m bar: **0** · boş aralık: 0 · hata: 0

| Geçiş | Gerçek 1m bar | Sentetik bar | Kapsama |
|---|---|---|---|
| 1 | 257 | 88 | %74.5 |

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
| birincil (karma yol (gerçek 1m %74.5)) | real_1m | -101.0655 | 20 | 25.0% | 0.0636 | 101.0655 | 100.0% |

## Dinamik risk ölçekleme (v5.2)

- **birincil (karma yol (gerçek 1m %74.5))**: 38 bütçe · ort ölçek 0.288 · min ölçek 0.105 · maliyet kapısı reddi 1079 · bağlayan: {'cost': 3, 'drawdown': 17, 'none': 2, 'recovery': 16}

## Risk denetimi (gerçekleşen / hedef kayıp)

- **birincil (karma yol (gerçek 1m %74.5))**: 15 zararlı işlem · ort 0.957x · maks 1.346x · aşım 1/15 (eşik 1.3x) · maks stop aşımı 0.775x

## Rejim kırılımı

### birincil (karma yol (gerçek 1m %74.5))

| Rejim | İşlem | Net PnL | Kazanma |
|---|---|---|---|
| TREND_UP | 8 | -25.9705 | 12.5% |
| TREND_DOWN | 6 | -66.3474 | 33.3% |
| STRONG_TREND_UP | 2 | -1.7379 | 0.0% |
| STRONG_TREND_DOWN | 2 | -7.1008 | 50.0% |
| UNCERTAIN | 2 | 0.0911 | 50.0% |

## Walk-forward

- **birincil (karma yol (gerçek 1m %74.5))**: koşulmadı
## Red sayaçları

- **birincil (karma yol (gerçek 1m %74.5))**: dusuk_hacim=126422, fade_kosulu_yok=12693, guclu_trend_fade_kapali=5690, fake_breakout_or_suspect=3623, rejim_uyumsuz=2476, yukselen_bicak=1322, dusen_bicak=1207, OLCEK_TABAN_ALTINDA=989

## Hüküm

**Kod:** `INSUFFICIENT_SAMPLE` · **Önem:** red

🔴 **KENAR KANITLANMADI — örneklem yetersiz**

- Toplam kanıt 20 işlem (birincil 20 + walk-forward 0); istatistiksel hüküm için en az 200 gerekir.
- Walk-forward: 0/0 pencere kârlı, toplam 0.00 USDT.
- Daha uzun veri veya daha çok sembol ile tekrar koşun. Bu sonuçla gerçek paraya ölçekleme YAPILMAMALIDIR.
