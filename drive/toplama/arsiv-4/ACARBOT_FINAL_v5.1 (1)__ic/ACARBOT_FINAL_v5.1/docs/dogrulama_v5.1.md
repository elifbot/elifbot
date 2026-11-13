# ACARBOT Doğrulama Raporu — 5.1-final

**Üretim:** 2026-11-07T19:19:05+00:00
**Veri:** okx · 6 sembol · 90 gün · 155520 adet 5m bar
**1m alt çözünürlük:** 3 gün · 25920 bar
**Profil:** apex · işlem başı hedef net risk 25.0 USDT

## Maliyet modeli

Maliyet modeli: ÖLÇÜLMÜŞ · 6 sembol ölçüldü · binance: spread 1.50bps, kayma 2.00bps, çıkış kayması 3.00bps, gecikme 250ms | okx: spread 0.99bps, kayma 3.00bps, çıkış kayması 4.00bps, gecikme 350ms

## Koşular

| Koşu | Yol kaynağı | Net PnL | İşlem | Kazanma | PF | Maks DD | MC kayıp olasılığı |
|---|---|---|---|---|---|---|---|
| birincil (1m yol + maliyet) | adverse_first | -87.1110 | 5 | 20.0% | 0.0075 | 87.1110 | 99.6% |

## Risk denetimi (gerçekleşen / hedef kayıp)

- **birincil (1m yol + maliyet)**: 4 zararlı işlem · ort 1.099x · maks 1.346x · aşım 1/4 (eşik 1.3x) · maks stop aşımı 0.775x

## Rejim kırılımı

### birincil (1m yol + maliyet)

| Rejim | İşlem | Net PnL | Kazanma |
|---|---|---|---|
| TREND_DOWN | 2 | -59.1063 | 0.0% |
| STRONG_TREND_DOWN | 2 | -26.8220 | 50.0% |
| STRONG_TREND_UP | 1 | -1.1827 | 0.0% |

## Walk-forward

- **birincil (1m yol + maliyet)**: 0/[{'index': 1, 'start_ts': 1786301400000, 'end_ts': 1787597400000, 'net_pnl': -89.4523, 'trades': 5, 'win_rate': 0.2, 'max_dd_pct': 8.9452, 'profitable': False}, {'index': 2, 'start_ts': 1787597400000, 'end_ts': 1788893400000, 'net_pnl': -23.3584, 'trades': 15, 'win_rate': 0.5333, 'max_dd_pct': 8.9524, 'profitable': False}, {'index': 3, 'start_ts': 1788893400000, 'end_ts': 1790189400000, 'net_pnl': -45.6862, 'trades': 13, 'win_rate': 0.4615, 'max_dd_pct': 9.7321, 'profitable': False}, {'index': 4, 'start_ts': 1790189400000, 'end_ts': 1791485400000, 'net_pnl': -80.3102, 'trades': 4, 'win_rate': 0.25, 'max_dd_pct': 8.9374, 'profitable': False}, {'index': 5, 'start_ts': 1791485400000, 'end_ts': 1792781400000, 'net_pnl': -102.1114, 'trades': 17, 'win_rate': 0.5294, 'max_dd_pct': 10.2111, 'profitable': False}, {'index': 6, 'start_ts': 1792781400000, 'end_ts': 1794077400001, 'net_pnl': -92.7194, 'trades': 7, 'win_rate': 0.4286, 'max_dd_pct': 9.2778, 'profitable': False}] pencere kârlı · toplam -433.6379 USDT

## Red sayaçları

- **birincil (1m yol + maliyet)**: dusuk_hacim=126652, fade_kosulu_yok=12728, guclu_trend_fade_kapali=5704, fake_breakout_or_suspect=3624, rejim_uyumsuz=2480, yukselen_bicak=1323, dusen_bicak=1207, PORTFOLIO_DRAWDOWN_PROTECTION=1117

## Hüküm

🔴 **KENAR KANITLANMADI — örneklem yetersiz.** Birincil koşuda 5 işlem var; istatistiksel hüküm için en az 200 gerekir. Daha uzun veri veya daha çok sembol ile tekrar koşun. Bu sonuçla gerçek paraya ölçekleme YAPILMAMALIDIR.
