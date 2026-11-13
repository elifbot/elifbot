# PHOENIX FINAL — Backtest

- semboller: BTC/USDT:USDT, ETH/USDT:USDT, SOL/USDT:USDT
- tf: 15m
- aralık: 2026-10-09 15:30:00+00:00 → 2026-11-09 21:00:00+00:00
- risk_işlem: %0.5
- motor: kötümser (stop-once, ücret+kayma+funding)

## Metrikler

| metrik | değer |
|---|---|
| n | 71 |
| kazanma_orani_pct | 42.3 |
| net_pnl | -118.2 |
| net_getiri_pct | -1.18 |
| ort_R | -0.361 |
| profit_factor | 0.47 |
| ort_kazanc | 3.47 |
| ort_kayip | -5.42 |
| max_dd_pct | 1.18 |
| toplam_ucret | 67.11 |
| toplam_funding | -1.57 |
| long_n | 71 |
| short_n | 0 |
| kucuk_orneklem | False |

## Katkı analizi (en iyi/kötü)

| kategori | bilgi |
|---|---|
| ci:STOP | {'n': 33, 'pnl': -212.83} |
| ci:BREAKEVEN | {'n': 22, 'pnl': 2.44} |
| ci:TIME | {'n': 4, 'pnl': 10.31} |
| ci:TRAIL | {'n': 3, 'pnl': 4.26} |
| ci:TARGET | {'n': 9, 'pnl': 77.63} |
| sym:SOL/USDT:USDT | {'pnl': -55.25} |
| sym:BTC/USDT:USDT | {'pnl': -40.32} |
| sym:ETH/USDT:USDT | {'pnl': -22.63} |
| yön:long | {'pnl': -118.2} |
| oy:ema+ | {'pnl': -148.06} |
| oy:boll+ | {'pnl': -125.93} |
| oy:vwap+ | {'pnl': -124.28} |
| oy:supertrend+ | {'pnl': -118.2} |
| oy:adx+ | {'pnl': -99.77} |
| oy:rsi+ | {'pnl': -72.44} |

## Devre kesici tetikleri

| neden | sayı |
|---|---|
| CONSEC_LOSSES | 4 |

## Motor istatistikleri

```
{'CLOSED_BREAKEVEN': 22, 'CLOSED_STOP': 33, 'CLOSED_TARGET': 9, 'CLOSED_TIME': 4, 'CLOSED_TRAIL': 3, 'EVAL_SIGNAL': 380, 'EVAL_THRESHOLD': 7816, 'OPENED': 71, 'REJECT_LOSS_PAUSE': 10, 'REJECT_MAX_SAME_SIDE': 29, 'SIGNALS': 100, 'SKIP_COOLDOWN': 355, 'VETO_CHOP': 24, 'VETO_EDGE_BELOW_COST': 47, 'VETO_HACIM_YOK': 71, 'VETO_HTF_CELISKI': 93, 'VETO_REJIM_ZAYIF': 35}
```

> Backtest geçmiş performanstır; gelecek getirinin garantisi DEĞİLDİR.
