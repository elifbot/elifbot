"""Kayan Pencere (Walk-Forward) Parametre Optimizasyonu.

Eğitim penceresinde en iyi parametre adaylarını seçer, takip eden hiç görülmemiş
test pencerelerinde (out-of-sample) doğrulayarak `params_best.json` çıktısı üretir.

Kullanım:
    python -m src.walkforward veri.csv
    python -m src.walkforward veri.csv --train 1200 --test 400 --step 400 --stride 3
    python -m src.walkforward veri.csv --fast        (hızlı ön tarama)
    python -m src.walkforward veri.csv --legacy-indicators  (eski skorla A/B)

CSV: timestamp,open,high,low,close,volume (başlıklı)
Çıktı: params_best.json → config.yaml'da optimizasyon.otomatik_params: true
"""
from __future__ import annotations

import argparse
import itertools
import json

import numpy as np
import pandas as pd

from .indicators import indicator_score
from .risk import Position, RiskManager
from .strategy import Strategy

DEFAULT_PARAMS = {
    "w_ind": 0.45,
    "w_flow": 0.35,
    "w_news": 0.20,
    "long_th": 50.0,
    "short_th": -50.0,
    "exit_th": 15.0,
}


def param_grid(fast: bool = False) -> list[dict]:
    if fast:
        w_inds = [0.40, 0.55]
        w_flows = [0.25, 0.40]
        long_ths = [45.0, 55.0]
        exit_ths = [15.0]
    else:
        w_inds = [0.35, 0.45, 0.55]
        w_flows = [0.25, 0.35, 0.45]
        long_ths = [40.0, 50.0, 60.0]
        exit_ths = [12.0, 18.0]
    combos = []
    for wi, wf, lth, eth in itertools.product(w_inds, w_flows, long_ths, exit_ths):
        wn = round(max(0.05, 1.0 - wi - wf), 2)
        combos.append(
            {
                "w_ind": wi,
                "w_flow": wf,
                "w_news": wn,
                "long_th": lth,
                "short_th": -lth,
                "exit_th": eth,
            }
        )
    return combos


def flow_proxy(df: pd.DataFrame) -> pd.Series:
    """OHLCV hacim ve mum yönünden yaklaşık para akışı vekili (-100..+100)."""
    close = df["close"].astype(float)
    open_ = df["open"].astype(float)
    vol = df["volume"].astype(float)
    signed = np.where(close >= open_, vol, -vol)
    s = pd.Series(signed, index=df.index)
    mean = s.rolling(30, min_periods=5).mean()
    std = s.rolling(30, min_periods=5).std().replace(0, np.nan)
    z = ((s - mean) / std).fillna(0.0)
    return (z * 40).clip(-100, 100)


def precompute_analysis(
    df: pd.DataFrame, regime_aware: bool = True
) -> tuple[np.ndarray, list[dict]]:
    n = len(df)
    scores = np.zeros(n)
    contexts: list[dict] = [{} for _ in range(n)]
    for i in range(60, n):
        result = indicator_score(df.iloc[: i + 1], regime_aware=regime_aware)
        scores[i] = result["score"]
        contexts[i] = result.get("snapshot", {})
        if i % 500 == 0:
            print(f"  ... indikatör ön-hesap {i}/{n}", flush=True)
    return scores, contexts


def precompute_scores(df: pd.DataFrame, regime_aware: bool = True) -> np.ndarray:
    """Geriye uyumlu yalnızca-skor arayüzü."""
    return precompute_analysis(df, regime_aware=regime_aware)[0]


def simulate(
    df: pd.DataFrame,
    scores: np.ndarray,
    flow: pd.Series,
    params: dict,
    start: int,
    end: int,
    stride: int = 3,
    contexts: list[dict] | None = None,
) -> dict:
    """[start, end) aralığında stratejiyi koşturur."""
    risk = RiskManager()
    st = Strategy(
        params["w_ind"],
        params["w_flow"],
        params["w_news"],
        params["long_th"],
        params["short_th"],
        params["exit_th"],
        True,
        w_ml=0.0,
    )
    pos: Position | None = None
    trades_pnl: list[float] = []
    equity = 1.0
    peak = 1.0
    max_dd = 0.0

    def _settle(pnl_pct: float):
        nonlocal equity, peak, max_dd
        net_pct = pnl_pct - 0.10  # komisyon + kayma payı
        trades_pnl.append(net_pct)
        equity *= max(0.01, 1.0 + net_pct / 100.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100.0)

    for i in range(max(60, start), min(len(df), end)):
        price = float(df["close"].iloc[i])
        decide = ((i - start) % stride == 0)
        if pos is not None:
            previous = contexts[i - 1] if contexts is not None and i > 0 else {}
            if previous.get("regime_aware", False):
                st_dir = int(previous.get("supertrend_direction", 0) or 0)
                st_stop = float(previous.get("supertrend", 0.0) or 0.0)
                pos_dir = 1 if pos.side == "LONG" else -1
                if st_dir == pos_dir and st_stop > 0 and risk.profit_pct(pos, price) > 0:
                    if pos.side == "LONG":
                        pos.stop = max(pos.stop, st_stop)
                    else:
                        pos.stop = min(pos.stop, st_stop)
            res = risk.update(pos, price)
            if res["action"] == "close":
                _settle(res["pnl_pct"])
                pos = None
                continue
            if decide:
                fw = float(flow.iloc[i])
                dec = st.combine(
                    scores[i],
                    fw,
                    0.0,
                    market_context=contexts[i] if contexts is not None else None,
                )
                ex = st.exit_decision(
                    pos.side, dec, fw, False, risk.profit_pct(pos, price)
                )
                if ex["action"] == "close":
                    _settle(risk.profit_pct(pos, price))
                    pos = None
        elif decide:
            fw = float(flow.iloc[i])
            dec = st.combine(
                scores[i],
                fw,
                0.0,
                market_context=contexts[i] if contexts is not None else None,
            )
            d = st.entry_decision(dec, False, False)
            if d["action"] in ("LONG", "SHORT"):
                pos = Position(
                    "WF",
                    d["action"],
                    price,
                    1.0,
                    risk.initial_stop(d["action"], price),
                )

    ret_pct = (equity - 1.0) * 100.0
    objective = (ret_pct - 0.5 * max_dd) if len(trades_pnl) >= 2 else None
    return {
        "trades": len(trades_pnl),
        "return_pct": round(ret_pct, 2),
        "max_dd_pct": round(max_dd, 2),
        "objective": objective,
    }


def run_walkforward(
    csv_path: str,
    train: int = 1200,
    test: int = 400,
    step: int = 400,
    stride: int = 3,
    out: str = "params_best.json",
    fast: bool = False,
    regime_aware: bool = True,
) -> dict:
    df = pd.read_csv(csv_path)
    n = len(df)
    if n < 260:
        raise ValueError(f"Walk-forward için en az 260 mum gerekli (mevcut: {n})")
    if n < train + test + 60:
        train = max(120, int((n - 60) * 0.65))
        test = max(60, n - 60 - train)
        step = max(40, test)
        print(f"ℹ️ Veri kısa ({n} mum) → train={train}, test={test}, step={step}")

    print(f"📥 {n} mum yüklendi. İndikatörler ön-hesaplanıyor...")
    scores, contexts = precompute_analysis(df, regime_aware=regime_aware)
    flow = flow_proxy(df)
    combos = param_grid(fast)
    print(f"🔍 {len(combos)} kombinasyon × kayan pencereler test ediliyor...")

    starts = list(range(60, max(61, n - train - test + 1), step))
    totals: dict[int, list[float]] = {ci: [] for ci in range(len(combos))}
    base_totals: list[float] = []

    for w, tr0 in enumerate(starts):
        tr1 = tr0 + train
        te1 = min(n, tr1 + test)
        scored = []
        for ci, p in enumerate(combos):
            r = simulate(df, scores, flow, p, tr0, tr1, stride, contexts)
            scored.append(
                (r["objective"] if r["objective"] is not None else float("-inf"), ci)
            )
        scored.sort(reverse=True)
        for _, ci in scored[:3]:
            r = simulate(df, scores, flow, combos[ci], tr1, te1, stride, contexts)
            if r["objective"] is not None:
                totals[ci].append(r["objective"])
        rb = simulate(df, scores, flow, DEFAULT_PARAMS, tr1, te1, stride, contexts)
        if rb["objective"] is not None:
            base_totals.append(rb["objective"])
        print(
            f"  pencere {w + 1}/{len(starts)}: train[{tr0}:{tr1}] test[{tr1}:{te1}] tamamlandı",
            flush=True,
        )

    avg = {
        ci: (sum(vals) / len(vals) if vals else float("-inf"))
        for ci, vals in totals.items()
    }
    best_ci = max(avg, key=avg.get)
    best_params = combos[best_ci] if avg[best_ci] != float("-inf") else dict(DEFAULT_PARAMS)
    base_avg = sum(base_totals) / len(base_totals) if base_totals else None

    result = {
        **best_params,
        "meta": {
            "pencere_sayisi": len(starts),
            "test_skoru": round(avg.get(best_ci, 0), 2)
            if avg.get(best_ci, float("-inf")) != float("-inf")
            else None,
            "varsayilan_test_skoru": round(base_avg, 2) if base_avg is not None else None,
            "veri": csv_path,
            "indikator_modu": "rejim" if regime_aware else "legacy",
        },
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ En iyi walk-forward parametreleri kaydedildi: {out}")
    return result


def main():
    ap = argparse.ArgumentParser(description="Walk-Forward Parametre Optimizasyonu")
    ap.add_argument("csv", help="OHLCV CSV dosya yolu")
    ap.add_argument("--train", type=int, default=1200)
    ap.add_argument("--test", type=int, default=400)
    ap.add_argument("--step", type=int, default=400)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--out", default="params_best.json")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument(
        "--legacy-indicators",
        action="store_true",
        help="Rejim bazlı model yerine eski toplam indikatör skorunu kullan (A/B).",
    )
    a = ap.parse_args()
    run_walkforward(
        a.csv,
        a.train,
        a.test,
        a.step,
        a.stride,
        a.out,
        a.fast,
        regime_aware=not a.legacy_indicators,
    )


if __name__ == "__main__":
    main()
