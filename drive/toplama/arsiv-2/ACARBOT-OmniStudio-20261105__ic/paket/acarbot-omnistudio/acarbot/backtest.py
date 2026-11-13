"""Gerçek 5dk kapanmış mumlarla geriye dönük PAPER simülasyonu ve A/B katman testi.

NEDEN
  Maildeki paketin tek "kanıtı" 1.800 SENTETİK parite kontrolüydü (JS ile Python
  aynı sonucu veriyor mu). Bu, stratejinin para kazanıp kazanmadığını söylemez.
  Burada gerçek Binance/OKX/Gate mumları üzerinde, her sinyal için sonraki
  mumlarda stop/hedef/funding/maliyet simüle edilir (PAPER, emir yok).

KATMANLAR (her biri tek tek açılıp kapatılır)
  A temel          : taker 5bps + 2bps kayma + gerçek makas, funding YOK
  B +gerçek maliyet: + ölçülen funding oranı (8 saatlik dilim, tutma süresine oranlı)
  C +konsey        : OmniStudio 20 denetçili kural konseyi (ölçülmüş akış/MTF/genişlik)
  D +portföy riski : 8 açık pozisyon, pazar başına 4, aynı yön 6, günlük %3 kesici,
                     gerçek lot adımı/marj, 1R başabaş + takip
  E +funding kaçışı: funding anından 3 dk önce kapat (maildeki V10 davranışı)

DÜRÜSTLÜK
  · Bar içinde hem stop hem hedef görülürse STOP varsayılır (kötümser).
  · Giriş, sinyalden SONRAKİ mumun açılışıdır (geriye dönük veri sızıntısı yok).
  · Funding oranı geçmiş anlık görüntüdür; gelecekteki oranlar değişebilir.
  · 25 saatlik pencere kârlılık kanıtı değildir; yalnız katmanların etkisini
    AYNI örneklemde karşılaştırır.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from omnistudio.ai.council import AICouncil
from omnistudio.core.types import Candle, Side, Signal
from omnistudio.strategy.indicators import atr, choppiness

from . import marketdata as md
from .contracts import Instrument
from .flow import breadth, mtf_alignment, roundtrip_cost_bps
from .strategy import decide

D = Decimal


@dataclass
class Layer:
    name: str
    label: str
    real_costs: bool = False
    council: bool = False
    portfolio_risk: bool = False
    funding_avoidance: bool = False


LAYERS = [
    Layer("A", "Temel (maildeki gibi)"),
    Layer("B", "A + gerçek funding", real_costs=True),
    Layer("C", "B + konsey (ölçülmüş bağlam)", real_costs=True, council=True),
    Layer("D", "C + portföy riski & 1R koruma", real_costs=True, council=True,
          portfolio_risk=True),
    Layer("E", "D + funding kaçışı", real_costs=True, council=True,
          portfolio_risk=True, funding_avoidance=True),
]


@dataclass
class SimTrade:
    symbol: str
    market: str
    side: str
    entry_ms: int
    exit_ms: int
    entry: float
    exit: float
    stop: float
    target: float
    reason: str
    gross: float
    fees: float
    funding: float
    net: float
    r_multiple: float
    hold_bars: int


@dataclass
class SimState:
    equity: float
    start: float
    open_positions: list[dict] = field(default_factory=list)
    trades: list[SimTrade] = field(default_factory=list)
    peak: float = 0.0
    max_dd: float = 0.0
    breaker: bool = False
    consecutive_losses: int = 0
    day_start_equity: float = 0.0
    rejects: Counter = field(default_factory=Counter)


def simulate_symbol(inst: Instrument, candles: list[Candle], strategy: str,
                    layer: Layer, state: SimState, spread_bps: float,
                    funding_rate: float | None, funding_interval_h: float,
                    funding_next_ms: int | None, cfg: dict,
                    council: AICouncil | None, breadth_ratio: float,
                    stats: Counter) -> None:
    """Tek sembolün kararlarını sırayla simüle eder (portföy durumu paylaşılır)."""
    closed = sorted([c for c in candles if c.closed], key=lambda c: c.open_ms)
    if len(closed) < 250:
        stats["skip_short_history"] += 1
        return
    face = float(inst.face)
    i = 249
    while i < len(closed) - 1:
        bar = closed[i]
        close_now = bar.open_ms + md.INTERVAL_MS + 1000
        dec = decide(closed[:i + 1], close_now, strategy)
        stats[f"decide_{dec.reason}"] += 1
        if not dec.side:
            i += 1
            continue
        window = closed[:i + 1]
        atr_v = atr(window) or 0.0
        if atr_v <= 0:
            state.rejects["ATR_MISSING"] += 1
            i += 1
            continue
        spread = spread_bps
        cost = roundtrip_cost_bps(spread, funding_rate=(funding_rate if layer.real_costs else None),
                                  funding_interval_h=funding_interval_h)
        expected_move = (atr_v / bar.close) * 10_000 * 0.35
        # --- konsey katmanı ---
        if layer.council and council is not None:
            mtf = mtf_alignment(window, dec.side.value, close_now)
            metrics = {
                "entry_side": dec.side.value, "spread_bps": spread,
                "roundtrip_cost_bps": cost["total"],
                "expected_move_bps": expected_move,
                "atr_pct": atr_v / bar.close * 100,
                "choppiness": choppiness(window) or 50.0,
                "funding_rate": funding_rate or 0.0,
                "minutes_to_funding": ((funding_next_ms - close_now) / 60_000
                                       if funding_next_ms else 999.0),
                "extension_atr": abs(bar.close - sum(c.close for c in window[-20:]) / 20) / atr_v,
                "mtf_aligned": bool(mtf["aligned"]) if mtf["available"] else True,
                "breadth_ratio": breadth_ratio,
                # akış: geçmiş tick arşivi yok → ölçülmedi, nötr DEĞİL, uyarı
                "flow_score": 0.0,
            }
            sig = Signal(exchange=inst.market, symbol=inst.symbol, side=dec.side,
                         price=bar.close, ts_ms=close_now, ret_pct=0.0,
                         rvol=dec.volume_ratio, volume_usd=bar.quote_volume,
                         window_ms=md.INTERVAL_MS, ctx_vratio3=dec.volume_ratio,
                         signal_id=f"bt-{inst.key}-{bar.open_ms}", tag="backtest")
            # ağ/konsey asenkronizmi yok: kural turu senkron ve deterministik
            ctx = council.build_context(sig, metrics)
            verdict = council.quant_only(ctx)
            stats["council_calls"] += 1
            if not verdict.approved:
                stats["council_reject"] += 1
                i += 1
                continue
            stats["council_approve"] += 1
        # --- portföy kapıları ---
        if layer.portfolio_risk:
            if state.breaker:
                state.rejects["BREAKER"] += 1
                i += 1
                continue
            if len(state.open_positions) >= cfg["max_positions"]:
                state.rejects["MAX_POSITIONS"] += 1
                i += 1
                continue
            if any(p["symbol"] == inst.symbol and p["market"] == inst.market
                   for p in state.open_positions):
                state.rejects["ALREADY_OPEN"] += 1
                i += 1
                continue
            if sum(1 for p in state.open_positions if p["market"] == inst.market) >= cfg["max_per_market"]:
                state.rejects["MAX_PER_MARKET"] += 1
                i += 1
                continue
            if sum(1 for p in state.open_positions if p["side"] == dec.side.value) >= cfg["max_same_side"]:
                state.rejects["MAX_SAME_SIDE"] += 1
                i += 1
                continue
        # --- giriş: SONRAKİ mum açılışı ---
        entry_bar = closed[i + 1]
        sign = 1 if dec.side is Side.LONG else -1
        slip = cfg["slippage_bps"] / 10_000
        entry = entry_bar.open * (1 + sign * (slip + spread / 2 / 10_000))
        stop_dist = atr_v * cfg["atr_stop_mult"]
        stop = entry - sign * stop_dist
        target = entry + sign * stop_dist * cfg["tp_over_stop"]
        if layer.portfolio_risk:
            risk_amount = state.equity * cfg["risk_per_trade_pct"] / 100
            notional = min(risk_amount / (stop_dist / entry), cfg["max_notional"])
            if notional < cfg["min_notional"]:
                state.rejects["NOTIONAL_TOO_SMALL"] += 1
                i += 1
                continue
        else:
            notional = cfg["fixed_notional"]
        qty = notional / (face * entry)
        # borsa lot adımı
        step = float(inst.lot_step)
        if step > 0:
            qty = int(qty / step) * step
        if qty <= 0 or qty < float(inst.min_qty):
            state.rejects["QTY_BELOW_MIN"] += 1
            i += 1
            continue
        # geçmiş funding takvimi: borsanın bildirdiği sonraki andan geriye,
        # aynı oran varsayımıyla (etiketli tahmin)
        sched = None
        if funding_next_ms:
            step = int((funding_interval_h or 8.0) * 3600_000)
            if step > 0:
                first = funding_next_ms
                while first - step > closed[0].open_ms:
                    first -= step
                sched = first
        notional = qty * face * entry
        fee_rate = cfg["taker_fee_bps"] / 10_000
        entry_fee = notional * fee_rate
        pos = {"symbol": inst.symbol, "market": inst.market, "side": dec.side.value,
               "qty": qty, "face": face, "entry": entry, "stop": stop,
               "target": target, "notional": notional, "fee": entry_fee,
               "funding": 0.0, "opened_ms": entry_bar.open_ms,
               "risk_dist": stop_dist, "breakeven": False,
               "funding_next": sched, "rate": funding_rate or 0.0,
               "interval_h": funding_interval_h, "cost_bps": cost["total"]}
        if layer.portfolio_risk:
            state.open_positions.append(pos)
        # --- ileri yürüyüş ---
        exit_price = None
        exit_reason = ""
        exit_bar = i + 1
        funding_paid = 0.0
        for j in range(i + 1, min(len(closed), i + 1 + cfg["max_hold_bars"])):
            b = closed[j]
            # funding olayları
            if layer.real_costs and pos["funding_next"]:
                while pos["funding_next"] and b.open_ms >= pos["funding_next"]:
                    value = notional * (b.open / entry)
                    funding_paid += -sign * value * (funding_rate or 0.0)
                    interval_ms = int((funding_interval_h or 8.0) * 3600_000) or 28_800_000
                    pos["funding_next"] += interval_ms
            if layer.funding_avoidance and pos["funding_next"] and \
                    b.open_ms >= pos["funding_next"] - 180_000:
                exit_price, exit_reason, exit_bar = b.open, "FUNDING_AVOIDANCE", j
                break
            hit_stop = (b.low <= pos["stop"]) if sign > 0 else (b.high >= pos["stop"])
            hit_tp = (b.high >= pos["target"]) if sign > 0 else (b.low <= pos["target"])
            if hit_stop:            # kötümser: ikisi de görülürse STOP
                exit_price, exit_reason, exit_bar = pos["stop"], "STOP_LOSS", j
                break
            if hit_tp:
                exit_price, exit_reason, exit_bar = pos["target"], "TAKE_PROFIT", j
                break
            # 1R başabaş + takip (yalnız portföy katmanında)
            if layer.portfolio_risk:
                fav = (b.close - entry) * sign
                if fav >= pos["risk_dist"]:
                    be = entry * (1 + sign * (2 * fee_rate + 2 * slip))
                    trail = b.close - sign * pos["risk_dist"]
                    pos["stop"] = max(pos["stop"], be, trail) if sign > 0 else min(pos["stop"], be, trail)
                    pos["breakeven"] = True
        if exit_price is None:
            exit_price = closed[min(len(closed) - 1, i + cfg["max_hold_bars"])].close
            exit_reason = "MAX_HOLD"
            exit_bar = min(len(closed) - 1, i + cfg["max_hold_bars"])
        exit_eff = exit_price * (1 - sign * slip)
        gross = sign * qty * face * (exit_eff - entry)
        exit_fee = notional * fee_rate * (exit_eff / entry)
        fees = entry_fee + exit_fee
        net = gross - fees - funding_paid
        risk_value = stop_dist * qty * face
        state.equity += net
        state.peak = max(state.peak, state.equity)
        state.max_dd = max(state.max_dd, state.peak - state.equity)
        if net > 0:
            state.consecutive_losses = 0
        else:
            state.consecutive_losses += 1
        if layer.portfolio_risk:
            state.open_positions = [p for p in state.open_positions
                                    if not (p["symbol"] == inst.symbol)]
            if state.consecutive_losses >= cfg["max_consecutive_losses"]:
                state.breaker = True
            if state.equity <= state.start * (1 - cfg["daily_loss_limit_pct"] / 100):
                state.breaker = True
        state.trades.append(SimTrade(
            symbol=inst.symbol, market=inst.market, side=dec.side.value,
            entry_ms=entry_bar.open_ms, exit_ms=closed[exit_bar].open_ms,
            entry=round(entry, 8), exit=round(exit_eff, 8),
            stop=round(pos["stop"], 8), target=round(pos["target"], 8),
            reason=exit_reason, gross=round(gross, 6), fees=round(fees, 6),
            funding=round(funding_paid, 6), net=round(net, 6),
            r_multiple=round(net / risk_value, 4) if risk_value > 0 else 0.0,
            hold_bars=exit_bar - (i + 1)))
        i = max(exit_bar, i + 1)


def summary(state: SimState, layer: Layer, seconds: float) -> dict[str, Any]:
    t = state.trades
    wins = [x for x in t if x.net > 0]
    losses = [x for x in t if x.net < 0]
    gw = sum(x.net for x in wins)
    gl = abs(sum(x.net for x in losses))
    return {
        "layer": layer.name, "label": layer.label,
        "trades": len(t),
        "win_rate_pct": round(len(wins) / len(t) * 100, 2) if t else 0.0,
        "net": round(sum(x.net for x in t), 4),
        "profit_factor": round(gw / gl, 3) if gl > 0 else None,
        "avg_r": round(sum(x.r_multiple for x in t) / len(t), 3) if t else 0.0,
        "fees": round(sum(x.fees for x in t), 4),
        "funding": round(sum(x.funding for x in t), 4),
        "max_dd": round(state.max_dd, 4),
        "equity_start": round(state.start, 2),
        "equity_end": round(state.equity, 2),
        "exit_breakdown": dict(Counter(x.reason for x in t)),
        "per_market": dict(Counter(x.market for x in t)),
        "rejects": dict(state.rejects.most_common(12)),
    }


async def run(out: Path, symbols: int, per_market: int, strategy: str,
              cfg: dict) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    session = await md.MarketSession.create(concurrency=16)
    result: dict[str, Any] = {"strategy": strategy, "config": cfg}
    try:
        from .engine import discover, warmup
        items, coverage = await discover(session, per_market)
        books = await warmup(session, items, lambda row: None, symbols)
        by_key = {i.key: i for i in items}
        # gerçek makas anlık görüntüsü + funding
        spreads: dict[str, float] = {}
        for market in sorted({i.market for i in items if i.executable}):
            try:
                q = await session.quotes(market)
                for sym, quote in q.items():
                    spreads[f"{market}:{sym}"] = quote.spread_bps
            except Exception:
                pass
        breadth_all = breadth(books, md.now_ms())
        # sadece mumu olan, PAPER uygun enstrümanlar
        targets = [(by_key[k], v) for k, v in books.items()
                   if k in by_key and by_key[k].executable and len(v) >= 250]
        targets.sort(key=lambda kv: -kv[1][-1].quote_volume)
        targets = targets[:symbols]
        funding: dict[str, Any] = {}
        for inst, _ in targets[:120]:
            d = await session.funding(inst.market, inst.symbol)
            if d:
                funding[inst.key] = d
        council = AICouncil()
        layer_results = []
        for layer in LAYERS:
            state = SimState(equity=cfg["equity_start"], start=cfg["equity_start"],
                             peak=cfg["equity_start"])
            stats: Counter = Counter()
            for inst, candles in targets:
                f = funding.get(inst.key) or {}
                simulate_symbol(
                    inst, candles, strategy, layer, state,
                    spread_bps=spreads.get(f"{inst.market}:{inst.symbol}", 1.0),
                    funding_rate=f.get("rate"),
                    funding_interval_h=f.get("interval_h") or 8.0,
                    funding_next_ms=f.get("next_ms"),
                    cfg=cfg, council=council,
                    breadth_ratio=float(breadth_all.get("ratio") or 0.5),
                    stats=stats)
            s = summary(state, layer, time.monotonic() - t0)
            s["decide_reasons"] = {k[7:]: v for k, v in stats.items()
                                   if k.startswith("decide_")}
            s["council"] = {"calls": stats.get("council_calls", 0),
                            "approve": stats.get("council_approve", 0),
                            "reject": stats.get("council_reject", 0)}
            layer_results.append(s)
            print(f"  [{layer.name}] {layer.label}: işlem {s['trades']}, "
                  f"net {s['net']:+.3f}, PF {s['profit_factor']}, "
                  f"kazanma %{s['win_rate_pct']}", flush=True)
        best = max(layer_results, key=lambda s: s["net"])
        result.update({
            "status": "COMPLETED",
            "symbols_tested": len(targets),
            "markets": dict(Counter(i.market for i, _ in targets)),
            "breadth": breadth_all,
            "council_mode": council.mode,
            "layers": layer_results,
            "best_layer_by_net": {"layer": best["layer"], "net": best["net"]},
            "bars_per_symbol": min(len(c) for _, c in targets) if targets else 0,
            "window_hours": round(min(len(c) for _, c in targets) * 5 / 60, 1) if targets else 0,
            "elapsed_sec": round(time.monotonic() - t0, 1),
            "real_orders": 0,
            "limits": [
                "Geçmiş 5dk mum penceresi ~25 saat; kârlılık kanıtı değildir.",
                "Bar içi stop/hedef çakışmasında STOP varsayıldı (kötümser).",
                "Akış (CVD) geçmişi arşivlenmediği için konsey akış boyutunu "
                "nötr bıraktı; bu katman akış katkısını ölçmez.",
                "Funding oranı ölçüm anındaki anlık değerdir; geçmiş oranlar "
                "farklı olabilir.",
                "Gerçek emir, kısmi dolum, kuyruk önceliği ve likidasyon motoru yok.",
            ],
        })
    except Exception as e:
        result.update({"status": "FAILED", "error": f"{type(e).__name__}: {e}"})
    finally:
        await session.close()
    (out / "GERIYE_DONUK.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", type=int, default=200)
    ap.add_argument("--per-market", type=int, default=400)
    ap.add_argument("--strategy", default="trend")
    a = ap.parse_args()
    cfg = {
        "equity_start": 1000.0, "fixed_notional": 200.0,
        "taker_fee_bps": 5.0, "slippage_bps": 2.0,
        "atr_stop_mult": 2.5, "tp_over_stop": 2.0, "max_hold_bars": 24,
        "risk_per_trade_pct": 0.35, "max_notional": 300.0, "min_notional": 10.0,
        "max_positions": 8, "max_per_market": 4, "max_same_side": 6,
        "daily_loss_limit_pct": 3.0, "max_consecutive_losses": 5,
    }
    r = asyncio.run(run(Path(a.out), a.symbols, a.per_market, a.strategy, cfg))
    print(json.dumps({k: v for k, v in r.items() if k != "layers"}, ensure_ascii=False)[:600])
    raise SystemExit(0 if r["status"] == "COMPLETED" else 1)


if __name__ == "__main__":
    main()
