"""v5.2 — KAPI ATIF ANALİZİ: "bu kapı bizi kârdan etti mi?"

SORU
----
Canlı testte 13 giriş maliyet kapısıyla reddedildi. Hacim kapısı barların
%85'ini reddediyor. Emirlerin %83'ü dolmadan süresi doluyor. Bu kapılar
bizi KÂRDAN mı etti, yoksa ZARARDAN mı kurtardı?

YÖNTEM
------
İki farklı kapı sınıfı var ve AYNI yöntemle ölçülemezler:

  A) SİNYALİ OLUŞMUŞ adayın reddi (maliyet kapısı, drawdown koruması,
     şok testi, hız limiti...). Yön ve stop belli → karşı-olgusal
     simülasyon yapılabilir: "bu işlemi açsaydık ne olurdu?"

  B) SİNYAL HİÇ OLUŞMADI (dusuk_hacim, fake_breakout, trend_onayi_yok).
     Yön yok → karşı-olgusal tanımsız. Tek dürüst yöntem ABLASYON:
     eşiği gevşetip aynı veride yeniden koşmak.

Bu araç A'yı yapar. Her aday, portföy durumundan BAĞIMSIZ olarak gerçek
çıkış kuralları (stop / TP1 / trailing / zaman stopu / acil net stop) ve
ÖLÇÜLMÜŞ maliyetlerle simüle edilir. Böylece kapı etkisi, drawdown
korumasının yol-bağımlılığından ayrılarak ölçülür.

KULLANIM
--------
    python3 -m tools.gate_attribution --days 90 --out docs/kapi_atif.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from backtest.costs import CostModel
from backtest.engine import BacktestEngine
from core.risk import RiskManager
from exec.paper import PaperBroker
from infra.market_data.models import Candle
from tools.validate_strategy import (
    COARSE_MS,
    DEFAULT_SYMBOLS,
    _load_or_fetch,
    _profile_config,
    json_safe,
)

logger = logging.getLogger("gate_attribution")

# Karşı-olgusal simülasyon ufku: TREND zaman stopu 24 saat. Daha uzun
# tutmak hiçbir işlemin sonucunu değiştirmez (zaman stopu zaten keser).
MAX_FORWARD_BARS = 288 + 12


def _load_cached_or_fetch(
    exchange: str, key: str, bars: int, data_dir: Path, pause: float,
) -> list[Candle]:
    """Önbellekte DAHA UZUN bir dosya varsa onu kullan (yeniden indirme yok).

    validate_strategy dosya adını bar sayısıyla kuruyor; 4 günlük bir
    analiz için 90 günlük önbellek yeniden indirilmemeli.
    """
    from tools.validate_strategy import _read_csv

    raw = key.split(":", 1)[-1]          # önbellek adında borsa öneki YOK
    safe = raw.replace("-", "").upper()
    best: list[Candle] = []
    for path in sorted(data_dir.glob(f"{safe}_5m_*.csv")):
        try:
            n = int(path.stem.rsplit("_", 1)[-1])
        except ValueError:
            continue
        if n >= bars:
            rows = _read_csv(path)
            if len(rows) > len(best):
                best = rows
    if best:
        logger.info("[%s] önbellek: %d bar (istenen %d)", key, len(best), bars)
        return best
    return _load_or_fetch(exchange, raw, bars, "5m", data_dir, pause)


def _simulate_candidate(
    cand: dict,
    forward: list[Candle],
    config,
    costs: CostModel | None,
    risk_usdt: float,
    immediate_fill: bool = True,
) -> dict | None:
    """Bir adayı portföyden bağımsız olarak sonuna kadar simüle et.

    immediate_fill=True → giriş anında dolar (kapı sorusunu dolum
    sorusundan ayırır). False → gerçek maker yolu; dolmazsa sonuç yok.
    """
    symbol = cand["symbol"]
    side = cand["side"]
    entry_ref = float(cand["entry_ref"])
    stop_fraction = float(cand["stop_fraction"])
    if entry_ref <= 0 or not 0 < stop_fraction < 1 or not forward:
        return None

    broker = PaperBroker(config, 1_000.0)
    risk = RiskManager(config)
    broker.risk_manager_ref = risk
    if costs is not None:
        maker, taker = costs.fee_rates(symbol)
        broker.set_symbol_costs(
            symbol,
            maker_fee_rate=maker,
            taker_fee_rate=taker,
            stop_slippage_rate=costs.exit_slippage_bps(symbol) / 10_000.0,
            extra_slippage_rate=(costs.spread_bps(symbol) / 2.0) / 10_000.0,
        )
    try:
        plan = risk.plan(
            entry_ref, stop_fraction, side, motor=cand.get("motor", "trend"),
            risk_budget=risk_usdt,
        )
    except ValueError:
        return None

    t0 = int(cand["ts_ms"])
    if immediate_fill:
        # Girişi doğrudan aç: kapı sorusunu dolum belirsizliğinden ayır.
        order = broker.place_entry(
            symbol, plan, now_ms=t0, baseline_per_second=1e12,
        )
        broker.bind_plan(order, plan, cand.get("motor", "trend"))
        aligned = broker._plan_for_order.get(order.id, plan)
        # Maker beklemeden doldur (fiyatı limitin ötesine iterek).
        fill_price = (
            aligned.entry * 0.999 if side == "LONG" else aligned.entry * 1.001
        )
        broker.process_entry_tick(symbol, fill_price, 1e12, t0)
        if symbol not in broker.portfolio.positions:
            return {"outcome": "DOLMADI", "net_pnl": 0.0}
    else:
        order = broker.place_entry(
            symbol, plan, now_ms=t0, baseline_per_second=1e12,
        )
        broker.bind_plan(order, plan, cand.get("motor", "trend"))

    closed: dict | None = None
    bars = 0
    for candle in forward[:MAX_FORWARD_BARS]:
        now = int(candle.timestamp) + COARSE_MS
        if not immediate_fill and symbol not in broker.portfolio.positions:
            broker.process_entry_tick(
                symbol, candle.close, max(candle.volume, 1.0), now,
            )
            if symbol not in broker.portfolio.positions:
                bars += 1
                continue
        events = broker.manage_position_candle(
            symbol, candle, now, intrabar=False,
        )
        for ev in events:
            if ev.get("type") == "CLOSE":
                closed = ev
                break
        bars += 1
        if closed is not None:
            break

    if closed is None:
        pos = broker.portfolio.positions.get(symbol)
        if pos is None:
            return {"outcome": "DOLMADI", "net_pnl": 0.0}
        last = forward[min(bars, len(forward) - 1)]
        ev = broker.close_position_market(
            symbol, last.close, "analiz_ufku", int(last.timestamp) + COARSE_MS,
        )
        closed = ev or {}
        outcome = "UFUK_KAPANDI"
    else:
        outcome = str(closed.get("reason", "?"))

    net = float(closed.get("pnl", 0.0) or 0.0)
    target = float(closed.get("target_net_risk", risk_usdt) or risk_usdt)
    return {
        "outcome": outcome,
        "net_pnl": round(net, 4),
        "r_multiple": round(net / target, 4) if target > 0 else 0.0,
        "hold_ms": int(closed.get("hold_ms", 0) or 0),
        "target_net_risk": round(target, 4),
    }


def _agg(rows: list[dict]) -> dict:
    scored = [r for r in rows if r.get("sim") and r["sim"]["outcome"] != "DOLMADI"]
    pnls = [r["sim"]["net_pnl"] for r in scored]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = round(sum(pnls), 4)
    return {
        "aday": len(rows),
        "simule_edilen": len(scored),
        "dolmayan": len(rows) - len(scored),
        "hipotetik_net_usdt": total,
        "kazanan": len(wins),
        "kaybeden": len(losses),
        "kazanma_orani": round(len(wins) / len(scored), 4) if scored else 0.0,
        "ort_kazanc": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "ort_kayip": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "en_iyi": round(max(pnls), 4) if pnls else 0.0,
        "en_kotu": round(min(pnls), 4) if pnls else 0.0,
        "hukum": (
            "KAPI BIZI KÂRDAN ETTI" if total > 0
            else "KAPI BIZI ZARARDAN KURTARDI" if total < 0
            else "ETKISIZ"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exchange", default="okx")
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--profile", default="apex")
    ap.add_argument("--balance", type=float, default=1_000.0)
    ap.add_argument("--costs", default="docs/maliyet_olcum_v5.2.json")
    ap.add_argument("--data-dir", default="data/validation")
    ap.add_argument("--risk-usdt", type=float, default=25.0,
                    help="Karşı-olgusal simülasyonda sabit net risk")
    ap.add_argument("--max-candidates", type=int, default=0,
                    help="0 = sınırsız")
    ap.add_argument("--pause", type=float, default=0.15)
    ap.add_argument("--out", default="docs/kapi_atif.json")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    keys = [f"{args.exchange}:{s.strip()}" for s in args.symbols.split(",") if s.strip()]
    bars = args.days * 24 * 12

    candles: dict[str, list[Candle]] = {}
    for key in keys:
        rows = _load_cached_or_fetch(
            args.exchange, key, bars, data_dir, args.pause,
        )
        if rows:
            candles[key] = rows[-bars:] if len(rows) > bars else rows
    if not candles:
        logger.error("Veri yok")
        return 1

    config = _profile_config(args.profile, None)
    costs = CostModel.load(args.costs) if args.costs else None

    logger.info("TEMEL KOŞU: kapı izleme açık, %d sembol", len(candles))
    engine = BacktestEngine(config, initial_balance=args.balance)
    engine.gate_probe = []
    result = engine.run(candles, cost_model=costs)
    probe = list(engine.gate_probe)
    logger.info("Aday sayısı: %d | açılan: %d", len(probe), len(result.trades))

    by_reason: dict[str, list[dict]] = {}
    for rec in probe:
        by_reason.setdefault(rec["reason"] or "BILINMIYOR", []).append(rec)
    logger.info("Kapı dağılımı: %s",
                {k: len(v) for k, v in sorted(by_reason.items())})

    # Karşı-olgusal simülasyon
    index = {k: {int(c.timestamp): i for i, c in enumerate(v)}
             for k, v in candles.items()}
    if args.max_candidates:
        for k in by_reason:
            by_reason[k] = by_reason[k][: args.max_candidates]

    simulated: dict[str, list[dict]] = {}
    for reason, rows in by_reason.items():
        out_rows = []
        for cand in rows:
            series = candles[cand["symbol"]]
            pos = index[cand["symbol"]].get(int(cand["ts_ms"]))
            if pos is None:
                continue
            forward = series[pos + 1:]
            sim = _simulate_candidate(
                cand, forward, config, costs, args.risk_usdt,
            )
            out_rows.append({**cand, "sim": sim})
        simulated[reason] = out_rows
        logger.info("  %s: %d aday simüle edildi", reason, len(out_rows))

    summary = {reason: _agg(rows) for reason, rows in simulated.items()}
    report = {
        "surum": __import__("app").__version__,
        "veri": {
            "borsa": args.exchange, "sembol": len(candles),
            "gun": args.days, "bar": sum(len(v) for v in candles.values()),
        },
        "yontem": (
            "Sinyali oluşmuş her aday, portföyden bağımsız olarak gerçek "
            "çıkış kuralları ve ölçülmüş maliyetlerle simüle edildi. "
            "Giriş anında dolduruldu (kapı sorusu dolum sorusundan ayrıldı). "
            f"Sabit net risk {args.risk_usdt} USDT."
        ),
        "temel_kosu": {
            "net_pnl": round(result.net_pnl, 4),
            "islem": result.trade_count,
            "redler": dict(sorted(
                result.rejection_counts.items(), key=lambda kv: -kv[1],
            )),
        },
        "kapi_atfi": summary,
        "ornekler": {
            reason: [
                {k: v for k, v in r.items() if k != "score"}
                for r in rows[:5]
            ]
            for reason, rows in simulated.items()
        },
        "acik_sinir": (
            "Bu analiz SİNYALİ OLUŞMUŞ adayları kapsar. dusuk_hacim gibi "
            "sinyal öncesi filtreler burada YOK — onlar için ablasyon gerekir "
            "(eşiği gevşetip yeniden koşmak). Ayrıca portföy etkileşimi "
            "(drawdown koruması, teminat) model dışı bırakıldı."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(json_safe(report), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    logger.info("Yazıldı: %s", out)
    print("\n=== KAPI ATFI ===")
    for reason, s in sorted(
        summary.items(), key=lambda kv: -abs(kv[1]["hipotetik_net_usdt"]),
    ):
        print(f"{reason:32s} aday={s['aday']:5d} "
              f"net={s['hipotetik_net_usdt']:10.2f} "
              f"kazanma=%{s['kazanma_orani']*100:5.1f}  {s['hukum']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
