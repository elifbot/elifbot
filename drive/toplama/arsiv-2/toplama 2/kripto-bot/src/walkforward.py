"""Walk-Forward optimizasyon — botun parametrelerini piyasaya göre yeniler.

Klasik backtest geçmişe "ezber" yapar (overfit). Walk-forward bunun yerine:
  1) EĞİTİM penceresinde (örn. 1200 mum) tüm parametre kombinasyonlarını dener
  2) TEST penceresinde (örn. 400 mum) her birini doğrular
  3) Pencereyi KAYDIRIP tekrarlar (piyasa rejimi değişimlerini yakalar)
  4) Tüm pencerelerde ortalama en iyi skoru alan parametreyi seçer

Optimize edilenler: indikatör ağırlıkları (w_ind/w_flow/w_news),
giriş eşikleri (long_th/short_th) ve çıkış eşiği (exit_th).

Skor (amaç fonksiyonu) = test_getirisi − 0.5 × max_düşüş
(yüksek getiri + düşük düşüş = sağlam parametre)

Kullanım:
    python -m src.walkforward veri.csv
    python -m src.walkforward veri.csv --train 1200 --test 400 --step 400 --stride 3
    python -m src.walkforward veri.csv --fast        (hızlı ön tarama)

CSV: timestamp,open,high,low,close,volume (başlıklı)
Çıktı: params_best.json → config.yaml'da optimizasyon.otomatik_params: true
       yapılırsa bot bir dahaki açılışta bu parametreleri yükler.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from .indicators import indicator_score
from .risk import Position, RiskManager
from .strategy import Strategy

DEFAULT_PARAMS = {"w_ind": 0.50, "w_flow": 0.30, "w_news": 0.20,
                  "long_th": 55.0, "short_th": -55.0, "exit_th": 15.0}


def param_grid(fast: bool = False) -> list[dict]:
    weights = [(0.50, 0.30, 0.20), (0.60, 0.25, 0.15)] if fast else [
        (0.50, 0.30, 0.20), (0.60, 0.25, 0.15),
        (0.40, 0.40, 0.20), (0.55, 0.30, 0.15)]
    long_ths = [50.0, 60.0] if fast else [45.0, 55.0, 65.0]
    exit_ths = [15.0] if fast else [10.0, 15.0, 20.0]
    grid = []
    for wi, wf, wn in weights:
        for lt in long_ths:
            for et in exit_ths:
                grid.append({"w_ind": wi, "w_flow": wf, "w_news": wn,
                             "long_th": lt, "short_th": -lt, "exit_th": et})
    return grid


def flow_proxy(df: pd.DataFrame) -> pd.Series:
    """Mum verisinden para-akışı vekili: gövde yönü × hacim (z-skorlanmış)."""
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    pressure = (((df["close"] - df["open"]) / rng).fillna(0) * df["volume"])
    num = pressure.rolling(10, min_periods=10).sum()
    den = pressure.abs().rolling(50, min_periods=50).mean() * 10
    z = (num / den.replace(0, np.nan)).fillna(0)
    return (z * 40).clip(-100, 100)


def precompute_scores(df: pd.DataFrame) -> np.ndarray:
    n = len(df)
    scores = np.zeros(n)
    for i in range(60, n):
        scores[i] = indicator_score(df.iloc[:i + 1])["score"]
        if i % 500 == 0:
            print(f"  ... indikatör ön-hesap {i}/{n}", flush=True)
    return scores


def simulate(df: pd.DataFrame, scores: np.ndarray, flow: pd.Series,
             params: dict, start: int, end: int, stride: int = 3) -> dict:
    """[start, end) aralığında stratejiyi koşturur."""
    risk = RiskManager()
    st = Strategy(params["w_ind"], params["w_flow"], params["w_news"],
                  params["long_th"], params["short_th"], params["exit_th"])
    pos: Position | None = None
    trades: list[float] = []
    equity, peak, maxdd = 1.0, 1.0, 0.0

    def _settle(pnl: float):
        nonlocal equity, peak, maxdd
        trades.append(pnl)
        equity *= (1 + pnl / 100)
        peak = max(peak, equity)
        maxdd = max(maxdd, (peak - equity) / peak * 100)

    for i in range(max(start, 60), min(end, len(df))):
        price = float(df["close"].iloc[i])
        decide = ((i - start) % stride == 0)
        if pos is not None:
            res = risk.update(pos, price)
            if res["action"] == "close":
                _settle(res["pnl_pct"])
                pos = None
                continue
            if decide:
                fw = float(flow.iloc[i])
                dec = st.combine(scores[i], fw, 0.0)
                ex = st.exit_decision(pos.side, dec, fw, False,
                                      risk.profit_pct(pos, price))
                if ex["action"] == "close":
                    _settle(risk.profit_pct(pos, price))
                    pos = None
        elif decide:
            fw = float(flow.iloc[i])
            dec = st.combine(scores[i], fw, 0.0)
            d = st.entry_decision(dec, False, False)
            if d["action"] in ("LONG", "SHORT"):
                pos = Position("WF", d["action"], price, 1.0,
                               risk.initial_stop(d["action"], price))

    ret = (equity - 1) * 100
    wins = [t for t in trades if t >= 0]
    obj = (ret - 0.5 * maxdd) if len(trades) >= 3 else float("-inf")
    return {"return_pct": round(ret, 2), "maxdd_pct": round(maxdd, 2),
            "trades": len(trades),
            "winrate": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
            "objective": round(obj, 2) if obj != float("-inf") else None}


def run_walkforward(csv_path: str, train: int = 1200, test: int = 400,
                    step: int = 400, stride: int = 3,
                    out: str = "params_best.json",
                    fast: bool = False) -> dict:
    df = pd.read_csv(csv_path)
    n = len(df)
    if n < 260:
        raise ValueError(f"Yetersiz veri: {n} mum (en az ~260 gerekir)")
    # Küçük veriye otomatik uyarla
    if 60 + train + test > n:
        scale = (n - 60) / (train + test)
        train, test = max(100, int(train * scale)), max(50, int(test * scale))
        step = min(step, test)
        print(f"ℹ️ Veri kısa ({n} mum) → train={train}, test={test}, step={step}")

    print(f"📥 {n} mum yüklendi. İndikatörler ön-hesaplanıyor...")
    scores = precompute_scores(df)
    flow = flow_proxy(df)
    combos = param_grid(fast)
    print(f"🔍 {len(combos)} kombinasyon × kayan pencereler test ediliyor...")

    starts = list(range(60, n - train - test + 1, step)) or [60]
    if starts == [60] and 60 + train + test > n:
        train = n - 60 - test
    totals = {i: [] for i in range(len(combos))}
    base_totals: list[float] = []

    for w, s in enumerate(starts):
        tr0, tr1, te1 = s, s + train, s + train + test
        # Eğitim: en iyi kombinasyonu seç
        scored = []
        for ci, p in enumerate(combos):
            r = simulate(df, scores, flow, p, tr0, tr1, stride)
            scored.append((r["objective"] if r["objective"] is not None
                           else float("-inf"), ci))
        scored.sort(reverse=True)
        # Test: ilk 3 adayı + varsayılanı doğrula
        for _, ci in scored[:3]:
            r = simulate(df, scores, flow, combos[ci], tr1, te1, stride)
            if r["objective"] is not None:
                totals[ci].append(r["objective"])
        rb = simulate(df, scores, flow, DEFAULT_PARAMS, tr1, te1, stride)
        if rb["objective"] is not None:
            base_totals.append(rb["objective"])
        print(f"  pencere {w + 1}/{len(starts)}: train[{tr0}:{tr1}] "
              f"test[{tr1}:{te1}] → aday {[combos[c] for _, c in scored[:3]][0]}",
              flush=True)

    avg = {ci: (sum(v) / len(v) if v else float("-inf"))
           for ci, v in totals.items()}
    best_ci = max(avg, key=avg.get)
    best = dict(combos[best_ci])
    base_avg = sum(base_totals) / len(base_totals) if base_totals else None

    # Hiçbir aday doğrulanamazsa varsayılanı koru
    if avg[best_ci] == float("-inf"):
        print("⚠️ Hiçbir kombinasyon testlerde doğrulanamadı, varsayılan korunuyor.")
        best = dict(DEFAULT_PARAMS)

    result = {**best, "meta": {
        "pencereler": len(starts), "train": train, "test": test,
        "test_skoru": round(avg.get(best_ci, 0), 2)
        if avg.get(best_ci, float("-inf")) != float("-inf") else None,
        "varsayilan_test_skoru": round(base_avg, 2) if base_avg is not None else None,
        "veri": csv_path}}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 55)
    print(f"🏆 EN İYİ PARAMETRE → {out}")
    print(f"   ağırlıklar: ind %{best['w_ind']*100:.0f} / "
          f"akış %{best['w_flow']*100:.0f} / haber %{best['w_news']*100:.0f}")
    print(f"   eşikler: LONG ≥ {best['long_th']}, SHORT ≤ {best['short_th']}, "
          f"çıkış {best['exit_th']}")
    print(f"   test skoru: {result['meta']['test_skoru']} "
          f"(varsayılan: {result['meta']['varsayilan_test_skoru']})")
    print("   Botun kullanması için config.yaml → optimizasyon.otomatik_params: true")
    print("=" * 55)
    return result


def main():
    ap = argparse.ArgumentParser(description="Walk-Forward optimizasyon")
    ap.add_argument("csv", help="OHLCV csv dosyası")
    ap.add_argument("--train", type=int, default=1200)
    ap.add_argument("--test", type=int, default=400)
    ap.add_argument("--step", type=int, default=400)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--out", default="params_best.json")
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    run_walkforward(a.csv, a.train, a.test, a.step, a.stride, a.out, a.fast)


if __name__ == "__main__":
    main()
