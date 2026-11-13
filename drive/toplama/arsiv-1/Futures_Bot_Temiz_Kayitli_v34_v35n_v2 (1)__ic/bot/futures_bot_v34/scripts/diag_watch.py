#!/usr/bin/env python3
"""
scripts/diag_watch.py — Tur bazında gösterge tanılama kaydı.

Neden: "Bot neden işlem açmadı?" sorusunun cevabı log'da yok; çünkü sadece
açılan/kapanan pozisyonlar yazılıyor. Bu betik, canlı paper oturumunun yanında
çalışıp her turda GÖSTERGE DEĞERLERİNİ ve her adayın HANGİ KOŞULDA takıldığını
CSV'ye yazar. Sonra `scripts/postmortem.py` bu dosyayı analiz eder.

Kullanım:
    python scripts/diag_watch.py --minutes 55 --out logs/diagnostics.csv

Yalnızca public OKX uç noktaları kullanılır; kimlik bilgisi yoktur.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import config  # noqa: E402
from data.okx_swap_feed import OkxSwapFeed  # noqa: E402
from indicators.core import add_core_indicators  # noqa: E402
from indicators.volume import bb_keltner_squeeze, volume_zscore  # noqa: E402

FIELDS = [
    "ts_utc", "symbol", "close", "ema_ribbon", "ema_200_nan",
    "adx", "adx_ok", "macd_hist", "macd_ok", "supertrend_dir", "st_ok",
    "rsi", "bb_pos", "vwap_diff_pct",
    "squeeze_on", "volume_z", "vol_ok", "mom3",
    "trend_signal", "meanrev_signal", "squeeze_signal", "blocker",
]


def ribbon_dir(row, cols) -> str:
    vals = [row[c] for c in cols]
    if any(pd.isna(v) for v in vals):
        return "NAN"
    if all(a > b for a, b in zip(vals, vals[1:])):
        return "BULL"
    if all(a < b for a, b in zip(vals, vals[1:])):
        return "BEAR"
    return "MIXED"


def diagnose(symbol: str, df: pd.DataFrame) -> dict:
    """Tek sembol için gösterge tanılaması üretir."""
    ind = add_core_indicators(df)
    ind = pd.concat([ind, bb_keltner_squeeze(ind)], axis=1)
    ind["volume_z"] = volume_zscore(ind)
    last = ind.iloc[-1]

    cols = [f"ema_{p}" for p in config.EMA_PERIODS]
    rib = ribbon_dir(last, cols)

    adx_v = float(last["adx"]) if pd.notna(last["adx"]) else None
    hist_v = float(last["macd_hist"]) if pd.notna(last["macd_hist"]) else None
    st_v = float(last["st_trend"]) if pd.notna(last["st_trend"]) else None
    rsi_v = float(last["rsi"]) if pd.notna(last["rsi"]) else None
    close_v = float(last["close"])
    vz = float(last["volume_z"]) if pd.notna(last["volume_z"]) else None
    squeeze = bool(last["squeeze_on"]) if pd.notna(last["squeeze_on"]) else False

    bb_u = float(last["bb_upper"]) if pd.notna(last["bb_upper"]) else None
    bb_l = float(last["bb_lower"]) if pd.notna(last["bb_lower"]) else None
    bb_pos = "ABOVE" if (bb_u and close_v > bb_u) else "BELOW" if (bb_l and close_v < bb_l) else "INSIDE"

    from indicators.volume import session_vwap

    vwap = session_vwap(ind)
    vwap_v = float(vwap.iloc[-1]) if pd.notna(vwap.iloc[-1]) else None
    vwap_diff = ((close_v - vwap_v) / vwap_v * 100) if vwap_v else None

    mom3 = None
    if len(ind) > 3:
        prev = float(ind["close"].iloc[-4])
        mom3 = (close_v - prev) / prev * 100

    adx_ok = adx_v is not None and adx_v >= config.ADX_TREND_THRESHOLD
    macd_ok = hist_v is not None
    st_ok = st_v is not None

    # --- aday A: hangi koşul bloke ediyor? ---
    if rib == "NAN":
        blocker = "A:EMA200_warmup"
    elif rib == "MIXED":
        blocker = "A:ribbon_karisik"
    elif not adx_ok:
        blocker = "A:ADX<esik"
    elif rib == "BULL" and not (hist_v and hist_v > 0):
        blocker = "A:MACD_yon"
    elif rib == "BEAR" and not (hist_v and hist_v < 0):
        blocker = "A:MACD_yon"
    elif rib == "BULL" and st_v is not None and close_v <= st_v:
        blocker = "A:Supertrend_yon"
    elif rib == "BEAR" and st_v is not None and close_v >= st_v:
        blocker = "A:Supertrend_yon"
    elif rb_ok(rib, close_v, st_v, hist_v, adx_ok):
        blocker = "A:Hazir"
    else:
        blocker = "A:diger"

    trend_sig = "LONG" if blocker == "A:Hazir" and rib == "BULL" else (
        "SHORT" if blocker == "A:Hazir" and rib == "BEAR" else "HOLD")

    # --- aday B (ortalamaya dönüş) ---
    meanrev = "HOLD"
    if rsi_v is not None and vwap_v is not None:
        if rsi_v <= config.RSI_OVERSOLD and bb_pos == "BELOW" and close_v < vwap_v:
            meanrev = "LONG"
        elif rsi_v >= config.RSI_OVERBOUGHT and bb_pos == "ABOVE" and close_v > vwap_v:
            meanrev = "SHORT"

    # --- aday C (sıkışma kırılımı) ---
    squeeze_sig = "HOLD"
    if vz is not None and squeeze and mom3 is not None:
        if vz >= config.VOLUME_ZSCORE_THRESHOLD and mom3 > 0:
            squeeze_sig = "LONG"
        elif vz >= config.VOLUME_ZSCORE_THRESHOLD and mom3 < 0:
            squeeze_sig = "SHORT"

    return {
        "ts_utc": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "close": round(close_v, 6),
        "ema_ribbon": rib,
        "ema_200_nan": int(last["ema_200"] != last["ema_200"]),
        "adx": None if adx_v is None else round(adx_v, 2),
        "adx_ok": int(adx_ok),
        "macd_hist": None if hist_v is None else round(hist_v, 6),
        "macd_ok": int(macd_ok),
        "supertrend_dir": None if st_v is None else int(st_v),
        "st_ok": int(st_ok),
        "rsi": None if rsi_v is None else round(rsi_v, 2),
        "bb_pos": bb_pos,
        "vwap_diff_pct": None if vwap_diff is None else round(vwap_diff, 4),
        "squeeze_on": int(squeeze),
        "volume_z": None if vz is None else round(vz, 3),
        "vol_ok": int(vz is not None and vz >= config.VOLUME_ZSCORE_THRESHOLD),
        "mom3": None if mom3 is None else round(mom3, 4),
        "trend_signal": trend_sig,
        "meanrev_signal": meanrev,
        "squeeze_signal": squeeze_sig,
        "blocker": blocker,
    }


def rb_ok(rib, close_v, st_v, hist_v, adx_ok) -> bool:
    """Aday A'nın dört koşulu birlikte sağlanıyor mu?"""
    if rib == "BULL":
        return adx_ok and hist_v is not None and hist_v > 0 and st_v is not None and close_v > st_v
    if rib == "BEAR":
        return adx_ok and hist_v is not None and hist_v < 0 and st_v is not None and close_v < st_v
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=55)
    ap.add_argument("--out", default="logs/diagnostics.csv")
    ap.add_argument("--poll", type=int, default=config.POLL_INTERVAL_SEC)
    ap.add_argument("--symbols", default="BTC-USDT-SWAP,ETH-USDT-SWAP")
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    new_file = not os.path.exists(args.out)

    feed = OkxSwapFeed()
    try:
        inst = feed.fetch_instruments()
    except Exception as exc:
        print(f"HATA: enstrüman listesi alınamadı: {exc}", file=sys.stderr)
        return 1

    deadline = time.time() + args.minutes * 60
    fh = open(args.out, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=FIELDS)
    if new_file:
        writer.writeheader()

    print(f"tanılama başladı: {args.minutes} dk, semboller={symbols}, çıktı={args.out}")
    try:
        while time.time() < deadline:
            for sym in symbols:
                meta = inst.get(sym)
                if not meta:
                    continue
                try:
                    df = feed.fetch_candles(
                        sym, config.TIMEFRAME, config.CANDLE_LIMIT, ct_val=meta["ct_val"]
                    )
                except Exception as exc:
                    print(f"[{sym}] veri hatası: {exc}", file=sys.stderr)
                    continue
                row = diagnose(sym, df)
                writer.writerow(row)
                print(f"{row['ts_utc']} | {sym} | {row['close']} | {row['blocker']} "
                      f"| A={row['trend_signal']} B={row['meanrev_signal']} C={row['squeeze_signal']}")
            fh.flush()
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("durduruldu")
    finally:
        fh.close()
        feed.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
