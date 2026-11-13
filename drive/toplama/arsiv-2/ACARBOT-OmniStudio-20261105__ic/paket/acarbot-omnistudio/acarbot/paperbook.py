"""Çoklu borsa PAPER defteri — Decimal sözleşme matematiği, gerçek funding,
likidasyon mesafesi tahmini, korelasyon ve maruziyet limitleri.

MAİLDEKİ EKSİĞE KARŞILIK
  V10 defteri (`acarbot/ledger.py`) tek para birimi, tek borsa, float PnL ve
  "funding muhasebesi yok" diyordu. Burada:
    · PnL `ContractSpec.pnl` ile Decimal ve yerel settlement biriminde,
    · miktar borsanın lot adımına/mimimumuna yuvarlanır (uydurma yok),
    · funding, borsanın verdiği oranla ve GERÇEK funding anında deftere işlenir,
    · likidasyon mesafesi bakım marjı + kaldıraçtan TAHMİN edilir ve etiketlenir,
    · borsa/pazar bazında maruziyet ve aynı yön yoğunluğu sınırlanır.

SINIRLAR (dürüstçe)
  · Likidasyon fiyatı borsanın sözleşme kurallarına göre değişir; burada
    `1/lev` ve bakım marjı ile yaklaşık hesaplanır, GARANTİ DEĞİLDİR.
  · Fonlama oranı gelecekte değişebilir; önceden ödenen/alan tutar kesin değil.
  · Gerçek emir yolu yoktur; taker fiyatı + varsayımsal kayma kullanılır.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Any

from omnistudio.core.types import Quote, Side

from .contract_math import ContractSpec, D
from .contracts import Instrument


@dataclass
class PaperConfig:
    equity_start: Decimal = D("10000")
    risk_per_trade_pct: float = 0.35
    max_open_positions: int = 8
    max_positions_per_market: int = 4
    max_same_side: int = 6
    max_gross_exposure: Decimal = D("3000")     # settlement birimi (USDT)
    min_notional: Decimal = D("10")
    max_notional_per_trade: Decimal = D("400")
    atr_stop_mult: float = 2.5
    atr_tp_mult: float = 5.0
    breakeven_at_r: float = 1.0
    trail_at_r: float = 1.0
    max_hold_sec: float = 7_200
    daily_loss_limit_pct: float = 3.0
    max_consecutive_losses: int = 5
    taker_fee_bps: float = 5.0
    maker_fee_bps: float = 2.0
    slippage_bps: float = 2.0
    max_spread_bps: float = 8.0
    leverage_assumed: Decimal = D("3")          # likidasyon mesafesi için
    #: likidasyon mesafesi bundan yakınsa giriş reddedilir (yüzde)
    min_liquidation_distance_pct: float = 12.0


@dataclass
class Position:
    key: str
    market: str
    symbol: str
    settlement: str
    kind: str
    side: str
    qty: Decimal
    face: Decimal
    entry: Decimal
    stop: Decimal
    target: Decimal
    notional: Decimal            # settlement biriminde
    fee_paid: Decimal
    funding_paid: Decimal
    opened_ms: int
    signal_id: str
    strategy: str
    risk_distance: Decimal
    leverage: Decimal
    liq_price_estimate: Decimal | None
    breakeven: bool = False
    max_favorable: Decimal = D("0")
    entry_spread_bps: float = 0.0
    entry_cost_bps: float = 0.0
    marks: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class ClosedTrade:
    key: str
    market: str
    symbol: str
    side: str
    qty: str
    entry: str
    exit: str
    stop: str
    target: str
    gross: str
    fees: str
    funding: str
    net: str
    exit_reason: str
    opened_ms: int
    closed_ms: int
    hold_sec: float
    r_multiple: float
    equity_after: str
    leverage: str
    liq_price_estimate: str
    entry_cost_bps: float


class PaperBook:
    def __init__(self, cfg: PaperConfig | None = None):
        self.cfg = cfg or PaperConfig()
        self.equity = self.cfg.equity_start
        self.peak = self.equity
        self.max_dd = D("0")
        self.positions: dict[str, Position] = {}
        self.closed: list[ClosedTrade] = []
        self.realized = D("0")
        self.fees_total = D("0")
        self.funding_total = D("0")
        self.consecutive_losses = 0
        self.breaker = False
        self.breaker_reason = ""
        self.rejects: dict[str, int] = {}
        self.funding_events = 0

    # ---------------- risk ----------------
    def _reject(self, reason: str) -> None:
        self.rejects[reason] = self.rejects.get(reason, 0) + 1

    def exposure(self) -> Decimal:
        return sum((p.notional for p in self.positions.values()), D("0"))

    def market_count(self, market: str) -> int:
        return sum(1 for p in self.positions.values() if p.market == market)

    def same_side_count(self, side: Side) -> int:
        return sum(1 for p in self.positions.values() if p.side == side.value)

    def check_breaker(self) -> None:
        if self.breaker:
            return
        floor = self.cfg.equity_start * (1 - D(str(self.cfg.daily_loss_limit_pct)) / 100)
        if self.equity <= floor:
            self.breaker = True
            self.breaker_reason = "DAILY_LOSS_LIMIT"
        elif self.consecutive_losses >= self.cfg.max_consecutive_losses:
            self.breaker = True
            self.breaker_reason = "MAX_CONSECUTIVE_LOSSES"

    # ---------------- sizing ----------------
    def plan(self, inst: Instrument, quote: Quote, side: Side, atr_value: float
             ) -> dict[str, Any] | None:
        """Miktar, stop/hedef ve likidasyon mesafesini borsa kurallarıyla planla."""
        spec: ContractSpec = inst.spec()
        exec_px = D(str(quote.ask if side is Side.LONG else quote.bid))
        stop_dist = D(str(atr_value)) * D(str(self.cfg.atr_stop_mult))
        if stop_dist <= 0:
            self._reject("ATR_INVALID")
            return None
        risk_amount = (self.equity * D(str(self.cfg.risk_per_trade_pct)) / 100)
        # notional = risk / (stop_dist/px)  → fiyat birimi settlement ise geçerli
        risk_frac = stop_dist / exec_px
        notional = risk_amount / risk_frac
        notional = min(notional, self.cfg.max_notional_per_trade)

        # miktarı sözleşme kuralına çevir: linear'de qty = notional / (face*px)
        unit_value = spec.face * exec_px if spec.kind == "linear" else spec.face
        if unit_value <= 0:
            self._reject("CONTRACT_INVALID")
            return None
        # Efektif kaldıraç: defter kaldıracı ile borsanın izin verdiği üst sınırın
        # küçüğü. Bakım marjı oran olarak (ör. 0.003) beklenir; yüzde olarak
        # gelirse (ör. 5.0 = %5) 100'e bölünür — alan anlamı doğrulanır.
        lev = self.cfg.leverage_assumed
        if inst.max_leverage and inst.max_leverage > 0:
            lev = min(lev, inst.max_leverage)
        mmr = inst.maintenance_rate if inst.maintenance_rate else D("0.005")
        if mmr > D("1"):
            mmr = mmr / 100
        if mmr < 0 or mmr >= (D("1") / lev):
            mmr = D("0.005")
        liq_dist_pct = (D("1") / lev - mmr) * 100
        if float(liq_dist_pct) < self.cfg.min_liquidation_distance_pct:
            self._reject("LIQUIDATION_TOO_CLOSE")
            return None
        raw_qty = notional / unit_value
        try:
            qty = spec.qty(raw_qty)
        except ValueError:
            self._reject("QTY_BELOW_MINIMUM")
            return None
        if qty <= 0:
            self._reject("QTY_ZERO")
            return None
        notional = spec.value_in_settlement(qty, exec_px)
        if notional < self.cfg.min_notional:
            self._reject("NOTIONAL_TOO_SMALL")
            return None
        if inst.min_notional and notional < inst.min_notional:
            self._reject("EXCHANGE_MIN_NOTIONAL")
            return None
        if inst.max_qty and qty > inst.max_qty:
            self._reject("EXCHANGE_MAX_QTY")
            return None
        if inst.expires_ms and inst.expires_ms - quote.ts_ms < 24 * 3600 * 1000:
            self._reject("CONTRACT_EXPIRY_NEAR")
            return None

        sign = D("1") if side is Side.LONG else D("-1")
        stop = exec_px - sign * stop_dist
        target = exec_px + sign * stop_dist * D(str(self.cfg.atr_tp_mult / self.cfg.atr_stop_mult))
        if stop <= 0 or target <= 0:
            self._reject("STOP_INVALID")
            return None

        if float(liq_dist_pct) < self.cfg.min_liquidation_distance_pct:
            self._reject("LIQUIDATION_TOO_CLOSE")
            return None
        liq_price = exec_px * (1 - sign * D(str(liq_dist_pct)) / 100)
        fee = spec.fee(qty, exec_px, D(str(self.cfg.taker_fee_bps)) / 10000)
        return {"spec": spec, "qty": qty, "entry": exec_px, "notional": notional,
                "stop": stop, "target": target, "fee": fee, "leverage": lev,
                "liq_price": liq_price, "risk_distance": stop_dist,
                "liq_distance_pct": float(liq_dist_pct)}

    def open(self, inst: Instrument, quote: Quote, side: Side, atr_value: float,
             ts_ms: int, signal_id: str, strategy: str, cost_bps: float) -> Position | None:
        if signal_id and any(p.signal_id == signal_id for p in self.positions.values()):
            self._reject("DUPLICATE_SIGNAL")
            return None
        if self.breaker:
            self._reject("BREAKER_" + self.breaker_reason)
            return None
        if inst.key in self.positions:
            self._reject("ALREADY_OPEN")
            return None
        if len(self.positions) >= self.cfg.max_open_positions:
            self._reject("MAX_POSITIONS")
            return None
        if self.market_count(inst.market) >= self.cfg.max_positions_per_market:
            self._reject("MAX_POSITIONS_PER_MARKET")
            return None
        if self.same_side_count(side) >= self.cfg.max_same_side:
            self._reject("MAX_SAME_SIDE")
            return None
        planned = self.plan(inst, quote, side, atr_value)
        if not planned:
            return None
        if self.exposure() + planned["notional"] > self.cfg.max_gross_exposure:
            self._reject("MAX_GROSS_EXPOSURE")
            return None
        p = Position(
            key=inst.key, market=inst.market, symbol=inst.symbol,
            settlement=inst.settlement, kind=inst.kind, side=side.value,
            qty=planned["qty"], face=planned["spec"].face,
            entry=planned["entry"], stop=planned["stop"],
            target=planned["target"], notional=planned["notional"],
            fee_paid=planned["fee"], funding_paid=D("0"), opened_ms=ts_ms,
            signal_id=signal_id, strategy=strategy,
            risk_distance=planned["risk_distance"], leverage=planned["leverage"],
            liq_price_estimate=planned["liq_price"],
            entry_spread_bps=quote.spread_bps, entry_cost_bps=cost_bps,
        )
        self.positions[inst.key] = p
        return p

    # ---------------- mark / exit ----------------
    def mark_to_market(self, key: str, quote: Quote, ts_ms: int) -> Decimal:
        p = self.positions.get(key)
        if not p:
            return D("0")
        px = D(str(quote.bid if p.side == "LONG" else quote.ask))
        sign = D("1") if p.side == "LONG" else D("-1")
        # linear: değer = adet × face × fiyat; fiyat farkı → settlement farkı
        unreal = (px - p.entry) * sign * p.qty * p.face
        p.marks.append((ts_ms, str(px)))
        if len(p.marks) > 500:
            p.marks = p.marks[-500:]
        fav = (px - p.entry) * sign
        p.max_favorable = max(p.max_favorable, fav)
        return unreal

    def evaluate_exit(self, key: str, quote: Quote, now_ms: int) -> ClosedTrade | None:
        p = self.positions.get(key)
        if not p:
            return None
        sign = D("1") if p.side == "LONG" else D("-1")
        exec_px = D(str(quote.bid if p.side == "LONG" else quote.ask))
        # 1) stop / hedef
        if (exec_px - p.stop) * sign <= 0:
            return self.close(key, quote, now_ms, "STOP_LOSS")
        if (exec_px - p.target) * sign >= 0:
            return self.close(key, quote, now_ms, "TAKE_PROFIT")
        # 2) likidasyon tahmini aşıldıysa (gerçek likidasyon değil, uyarı)
        if p.liq_price_estimate is not None and (exec_px - p.liq_price_estimate) * sign <= 0:
            return self.close(key, quote, now_ms, "LIQUIDATION_ESTIMATE")
        # 3) 1R başabaş + takip
        if (exec_px - p.entry) * sign >= p.risk_distance * D(str(self.cfg.breakeven_at_r)):
            fee_pct = D(str(self.cfg.taker_fee_bps * 2 + self.cfg.slippage_bps * 2)) / 10000
            be = p.entry * (1 + sign * fee_pct)
            trail = exec_px - sign * p.risk_distance * D(str(self.cfg.trail_at_r))
            p.stop = max(p.stop, be, trail) if p.side == "LONG" else min(p.stop, be, trail)
            p.breakeven = True
        # 4) süre sınırı
        if (now_ms - p.opened_ms) / 1000 > self.cfg.max_hold_sec:
            return self.close(key, quote, now_ms, "MAX_HOLD")
        return None

    def close(self, key: str, quote: Quote, ts_ms: int, reason: str) -> ClosedTrade | None:
        p = self.positions.pop(key, None)
        if not p:
            return None
        exit_px = D(str(quote.bid if p.side == "LONG" else quote.ask))
        sign = D("1") if p.side == "LONG" else D("-1")
        slip = exit_px * D(str(self.cfg.slippage_bps)) / 10000
        exit_px_eff = exit_px - sign * slip
        gross = sign * p.qty * p.face * (exit_px_eff - p.entry)
        exit_fee = p.notional * D(str(self.cfg.taker_fee_bps)) / 10000 * (exit_px_eff / p.entry)
        fees = p.fee_paid + exit_fee
        net = gross - fees - p.funding_paid
        self.equity += net
        self.realized += net
        self.fees_total += fees
        self.funding_total += p.funding_paid
        self.peak = max(self.peak, self.equity)
        self.max_dd = max(self.max_dd, self.peak - self.equity)
        if net > 0:
            self.consecutive_losses = 0
        elif net < 0:
            self.consecutive_losses += 1
        risk_value = p.risk_distance * p.qty * p.face
        trade = ClosedTrade(
            key=key, market=p.market, symbol=p.symbol, side=p.side,
            qty=str(p.qty), entry=str(p.entry), exit=str(exit_px_eff),
            stop=str(p.stop), target=str(p.target), gross=str(gross),
            fees=str(fees), funding=str(p.funding_paid), net=str(net),
            exit_reason=reason, opened_ms=p.opened_ms, closed_ms=ts_ms,
            hold_sec=round((ts_ms - p.opened_ms) / 1000, 1),
            r_multiple=float(net / risk_value) if risk_value > 0 else 0.0,
            equity_after=str(self.equity), leverage=str(p.leverage),
            liq_price_estimate=str(p.liq_price_estimate or ""),
            entry_cost_bps=p.entry_cost_bps,
        )
        self.closed.append(trade)
        self.check_breaker()
        return trade

    # ---------------- funding ----------------
    def apply_funding(self, key: str, rate: float, mark_price: float) -> Decimal:
        """Borsanın bildirdiği oranla funding ödemesini/alanını deftere yaz."""
        p = self.positions.get(key)
        if not p or rate == 0:
            return D("0")
        value = p.notional * (D(str(mark_price)) / p.entry) if p.entry > 0 else p.notional
        delta = -D(str(1 if p.side == "LONG" else -1)) * value * D(str(rate))
        p.funding_paid += delta
        self.funding_total += delta
        self.equity += delta
        self.funding_events += 1
        return delta

    # ---------------- reporting ----------------
    def summary(self) -> dict[str, Any]:
        wins = [t for t in self.closed if float(t.net) > 0]
        losses = [t for t in self.closed if float(t.net) < 0]
        gross_win = sum((float(t.net) for t in wins), 0.0)
        gross_loss = abs(sum((float(t.net) for t in losses), 0.0))
        per_market: dict[str, dict[str, float]] = defaultdict(
            lambda: {"trades": 0, "net": 0.0, "wins": 0})
        for t in self.closed:
            d = per_market[t.market]
            d["trades"] += 1
            d["net"] = round(d["net"] + float(t.net), 8)
            if float(t.net) > 0:
                d["wins"] += 1
        unrealized = D("0")
        return {
            "equity_start": str(self.cfg.equity_start),
            "equity_now": str(self.equity.quantize(D("0.000001"))),
            "realized_net": str(self.realized.quantize(D("0.000001"))),
            "fees_paid": str(self.fees_total.quantize(D("0.000001"))),
            "funding_net": str(self.funding_total.quantize(D("0.000001"))),
            "funding_events": self.funding_events,
            "closed_trades": len(self.closed),
            "open_positions": len(self.positions),
            "win_rate_pct": round(len(wins) / len(self.closed) * 100, 2) if self.closed else 0.0,
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
            "avg_r": round(sum(t.r_multiple for t in self.closed) / len(self.closed), 3) if self.closed else 0.0,
            "max_drawdown": str(self.max_dd.quantize(D("0.000001"))),
            "breaker": self.breaker, "breaker_reason": self.breaker_reason,
            "rejects": dict(sorted(self.rejects.items(), key=lambda kv: -kv[1])),
            "per_market": {k: dict(v) for k, v in per_market.items()},
            "open": [{k: str(v) for k, v in asdict(p).items()
                      if k not in ("marks",)} for p in self.positions.values()],
        }
