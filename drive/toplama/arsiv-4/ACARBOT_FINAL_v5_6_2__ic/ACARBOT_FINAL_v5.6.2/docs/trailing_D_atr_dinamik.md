# ACARBOT Doğrulama Raporu — 5.6-final

**Üretim:** 2026-11-08T15:52:08+00:00
**Veri:** okx · 6 sembol · 90 gün · 155520 adet 5m bar
**1m alt çözünürlük:** targeted · 11385 bar · 6 sembol
**Profil:** kasa1000 · işlem başı TABAN net risk 25.0 USDT

## 1m kapsamı (iki geçişli)

- Geçiş sayısı: **1** · hedeflenen aralık: 897 · istek: 0
- Kazanılan 1m bar: **0** · boş aralık: 0 · hata: 0

| Geçiş | Gerçek 1m bar | Sentetik bar | Kapsama |
|---|---|---|---|
| 1 | 240 | 181 | %57.0 |

## Maliyet modeli

Maliyet modeli: MUHAFAZAKÂR VARSAYIM (ölçülmedi) · binance: VARSAYIM (ÖLÇÜLMEDİ) spread 1.50bps, kayma 2.00bps, çıkış 3.00bps, gecikme 250ms | okx: VARSAYIM (ÖLÇÜLMEDİ) spread 2.50bps, kayma 3.00bps, çıkış 4.00bps, gecikme 350ms · VERİ KÜMESİ KAPSAMASI 0/6 (%0) · ÖLÇÜLMEYEN: okx:ADA-USDT-SWAP, okx:BTC-USDT-SWAP, okx:DOGE-USDT-SWAP, okx:ETH-USDT-SWAP, okx:SOL-USDT-SWAP, okx:XRP-USDT-SWAP

**Veri kümesi kapsamasi:** 0/6 sembol ölçülmüş (%0).

> 🟡 Ölçülmeyen semboller borsa VARSAYIMI ile koştu: okx:ADA-USDT-SWAP, okx:BTC-USDT-SWAP, okx:DOGE-USDT-SWAP, okx:ETH-USDT-SWAP, okx:SOL-USDT-SWAP, okx:XRP-USDT-SWAP

| Borsa | Kaynak | Ölçülen sembol | Varsayılan kayma |
|---|---|---|---|
| binance | **VARSAYIM — ÖLÇÜLMEDİ** | 0 | 2.00 bps |
| okx | **VARSAYIM — ÖLÇÜLMEDİ** | 0 | 3.00 bps |

## Koşular

| Koşu | Yol kaynağı | Net PnL | İşlem | Kazanma | PF | Maks DD | MC kayıp olasılığı |
|---|---|---|---|---|---|---|---|
| birincil (karma yol (gerçek 1m %57.0)) | real_1m | -13.4564 | 20 | 45.0% | 0.3104 | 15.0042 | 98.2% |

## Dinamik risk ölçekleme (v5.2)

- **birincil (karma yol (gerçek 1m %57.0))**: 48 bütçe · ort ölçek 0.356 · min ölçek 0.250 · maliyet kapısı reddi 1062 · bağlayan: {'none': 2, 'recovery': 46}

## Risk denetimi (gerçekleşen / hedef kayıp)

- **birincil (karma yol (gerçek 1m %57.0))**: 11 zararlı işlem · ort 0.916x · maks 0.933x · aşım 0/11 (eşik 1.3x) · maks stop aşımı 0.524x

## Rejim kırılımı

### birincil (karma yol (gerçek 1m %57.0))

| Rejim | İşlem | Net PnL | Kazanma |
|---|---|---|---|
| TREND_DOWN | 9 | -2.9364 | 44.4% |
| TREND_UP | 5 | -8.4294 | 20.0% |
| STRONG_TREND_DOWN | 3 | -1.2567 | 66.7% |
| STRONG_TREND_UP | 2 | -1.1185 | 50.0% |
| UNCERTAIN | 1 | 0.2847 | 100.0% |

## Walk-forward

- **birincil (karma yol (gerçek 1m %57.0))**: koşulmadı
## Red sayaçları

- **birincil (karma yol (gerçek 1m %57.0))**: dusuk_hacim=126389, fade_kosulu_yok=12688, guclu_trend_fade_kapali=5679, fake_breakout_or_suspect=3618, rejim_uyumsuz=2478, yukselen_bicak=1323, dusen_bicak=1205, OLCEK_TABAN_ALTINDA=1062

## Hüküm

**Kod:** `INSUFFICIENT_SAMPLE` · **Önem:** red

🔴 **KENAR KANITLANMADI — örneklem yetersiz**

- Toplam kanıt 20 işlem (birincil 20 + walk-forward 0); istatistiksel hüküm için en az 200 gerekir.
- Walk-forward: 0/0 pencere kârlı, toplam 0.00 USDT.
- Daha uzun veri veya daha çok sembol ile tekrar koşun. Bu sonuçla gerçek paraya ölçekleme YAPILMAMALIDIR.
