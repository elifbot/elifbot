"""Olay Güdümlü (Event-Driven) Backtest Motoru + Gelecek Sızıntısı Denetimi + OOS Doğrulama.

Olay Zinciri:
  MarketEvent → SignalEvent → OrderEvent → FillEvent
  - İntrabar likidasyon, stop, kısmi TP1/TP2 ve Supertrend iz süren stop simülasyonu
  - Gerçekçi komisyon, kayma (slippage bps) ve zaman-ağırlıklı 8s funding maliyeti
  - Sabit 50 USDT marj / 10x / 40 USDT stop modeli ile birebir aynı yürütme kuralları
"""
from __future__ import annotations

import sys
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .indicators import Indicators, indicator_score
from .ml_predictor import MLPredictor
from .risk import Position, RiskManager
from .strategy import Strategy

DEFAULT_TRADE_PLAN = {
    "aktif": True,
    "atr_stop_katsayi": 1.5,
    "swing_mum": 20,
    "swing_atr_buffer": 0.20,
    "max_stop_yuzde": 12.0,
    "tp1_r": 1.0,
    "tp2_r": 2.0,
    "tp1_kapatma_orani": 0.50,
}


@dataclass
class MarketEvent:
    bar_idx: int
    ts: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SignalEvent:
    bar_idx: int
    symbol: str
    action: str
    score: float
    price: float
    reason: str


@dataclass
class OrderEvent:
    bar_idx: int
    symbol: str
    order_action: str  # OPEN | ADD | CLOSE
    side: str          # LONG | SHORT
    qty: float
    margin_usdt: float
    leverage: int
    price_ref: float
    reason: str
    trade_plan: dict | None = None


@dataclass
class FillEvent:
    bar_idx: int
    symbol: str
    order_action: str
    side: str
    qty: float
    fill_price: float
    fee_usdt: float
    slippage_abs: float
    margin_usdt: float
    leverage: int
    reason: str
    trade_plan: dict | None = None


def verify_no_lookahead_bias(df: pd.DataFrame, check_bar: int = 100) -> bool:
    """`check_bar` sonrasındaki mumlar tamamen değiştirildiğinde o bardaki skorun değişmediğini doğrular."""
    if df is None or len(df) < 75:
        return True
    idx = max(62, min(int(check_bar), len(df) - 5))
    s_orig = indicator_score(df.iloc[: idx + 1])["score"]
    tampered = df.copy()
    tampered.iloc[idx + 1 :, tampered.columns.get_loc("close")] *= 5.0
    tampered.iloc[idx + 1 :, tampered.columns.get_loc("high")] *= 5.0
    s_tamp = indicator_score(tampered.iloc[: idx + 1])["score"]
    return abs(float(s_orig) - float(s_tamp)) < 1e-9


class EventDrivenBacktester:
    def __init__(
        self,
        symbol: str = "BTC/USDT",
        initial_balance: float = 10_000.0,
        capital_pct: float = 10.0,
        leverage: int = 20,
        stop_loss_pct: float = 5.0,
        stop_model: str = "fiyat_yuzde",
        margin_stop_fraction: float = 0.80,
        margin_stop_liq_buffer: float = 0.85,
        fixed_margin_usdt: float | None = None,
        runner_exit: bool = False,
        fee_pct: float = 0.04,
        slippage_bps: float = 2.0,
        use_ml: bool = True,
        unlimited_pyramiding: bool = True,
        strategy_params: dict | None = None,
        bar_minutes: float = 5.0,
        funding_8h_pct: float = 0.01,
        trade_plan_cfg: dict | None = None,
    ):
        self.bar_minutes = float(bar_minutes)
        self.funding_8h_pct = float(funding_8h_pct)
        self.funding_paid_usdt: float = 0.0
        self.symbol = symbol
        self.initial_balance = float(initial_balance)
        self.balance = float(initial_balance)
        self.capital_pct = float(capital_pct)
        self.leverage = int(leverage)
        self.fixed_margin_usdt = fixed_margin_usdt
        self.runner_exit = bool(runner_exit)
        self.fee_pct = float(fee_pct)
        self.slippage_bps = float(slippage_bps)
        self.use_ml = bool(use_ml)
        self.trade_plan_cfg = dict(trade_plan_cfg or {})
        self.trade_plan_enabled = bool(self.trade_plan_cfg.get("aktif", False))
        self._last_atr = 0.0
        self._swing_low: float | None = None
        self._swing_high: float | None = None
        self._trade_plan: dict | None = None

        self.risk = RiskManager(
            stop_loss_pct=stop_loss_pct,
            stop_model=stop_model,
            margin_stop_fraction=margin_stop_fraction,
            margin_stop_liq_buffer=margin_stop_liq_buffer,
            capital_pct_per_entry=capital_pct,
            leverage=leverage,
            unlimited_pyramiding=(
                False if fixed_margin_usdt is not None else unlimited_pyramiding
            ),
            max_layers=1 if fixed_margin_usdt is not None else 6,
        )
        sp = strategy_params or {}
        self.supertrend_trailing = bool(sp.get("supertrend_trailing", True))
        self._supertrend: tuple[int, float] | None = None
        self.strategy = Strategy(
            w_ind=sp.get("w_ind", 0.50),
            w_flow=sp.get("w_flow", 0.20),
            w_news=sp.get("w_news", 0.15),
            long_th=sp.get("long_th", 45.0),
            short_th=sp.get("short_th", -45.0),
            exit_th=sp.get("exit_th", 15.0),
            allow_short=sp.get("allow_short", True),
            flow_trigger=sp.get("flow_trigger", True),
            flow_th=sp.get("flow_th", 50.0),
            flow_ind_min=sp.get("flow_ind_min", 10.0),
            flow_min_total=sp.get("flow_min_total", 15.0),
            w_ml=sp.get("w_ml", 0.15 if use_ml else 0.0),
            runner_exit=self.runner_exit,
        )
        self.ml = MLPredictor(min_train_bars=60, retrain_every=25) if use_ml else None

        self.events: deque[Any] = deque()
        self.pos: Position | None = None
        self._position_fees_usdt = 0.0
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.events_processed: int = 0

    def _apply_slippage(self, price: float, is_buy: bool) -> tuple[float, float]:
        slip_frac = self.slippage_bps / 10_000.0
        fill_px = price * (1.0 + slip_frac) if is_buy else price * (1.0 - slip_frac)
        return fill_px, abs(fill_px - price)

    def _prepare_atr_plan(self, side: str, price: float) -> dict | None:
        if not self.trade_plan_enabled:
            return None
        return self.risk.atr_structure_plan(
            side,
            price,
            self._last_atr,
            self.leverage,
            swing_low=self._swing_low,
            swing_high=self._swing_high,
            atr_mult=float(self.trade_plan_cfg.get("atr_stop_katsayi", 1.5)),
            structure_buffer_atr=float(self.trade_plan_cfg.get("swing_atr_buffer", 0.2)),
            max_stop_pct=float(self.trade_plan_cfg.get("max_stop_yuzde", 12.0)),
        )

    def _make_r_plan(
        self, side: str, entry: float, stop: float, source: str, atr: float
    ) -> dict | None:
        risk_distance = abs(entry - stop)
        if risk_distance <= 0 or entry <= 0 or stop <= 0:
            return None
        direction = 1.0 if side == "LONG" else -1.0
        return {
            "source": source,
            "initial_stop": stop,
            "initial_risk": risk_distance,
            "atr": atr,
            "tp1": entry
            + direction * risk_distance * float(self.trade_plan_cfg.get("tp1_r", 1.0)),
            "tp2": entry
            + direction * risk_distance * float(self.trade_plan_cfg.get("tp2_r", 2.0)),
            "tp1_fraction": float(self.trade_plan_cfg.get("tp1_kapatma_orani", 0.5)),
            "tp1_hit": False,
        }

    def _intrabar_ticks(self, ev: MarketEvent) -> list[float]:
        if self.pos is not None and self.pos.side == "SHORT":
            return [ev.open, ev.high, ev.low, ev.close]
        return [ev.open, ev.low, ev.high, ev.close]

    def _handle_market_event(self, ev: MarketEvent, history_slice: pd.DataFrame):
        # İntrabar stop takibinde yalnızca ÖNCEKİ kapalı mumun Supertrend'i
        # kullanılır. Mevcut mumun değeri bir sonraki bar için saklanır.
        previous_supertrend = self._supertrend
        ind = indicator_score(history_slice)
        snap = ind.get("snapshot", {})
        st_value = float(snap.get("supertrend", 0.0) or 0.0)
        self._supertrend = (
            (int(snap.get("supertrend_direction", 1)), st_value)
            if np.isfinite(st_value) and st_value > 0
            else None
        )
        if self.trade_plan_enabled:
            atr_series = Indicators.atr(
                history_slice["high"], history_slice["low"], history_slice["close"], 14
            )
            atr_value = float(atr_series.iloc[-1])
            self._last_atr = atr_value if np.isfinite(atr_value) and atr_value > 0 else 0.0
            structure = history_slice.tail(int(self.trade_plan_cfg.get("swing_mum", 20)))
            self._swing_low = float(structure["low"].min())
            self._swing_high = float(structure["high"].max())

        if self.pos is not None:
            for tick_px in self._intrabar_ticks(ev):
                # Likidasyon kontrolü (gerçek borsada stop'tan önce vurabilir)
                liq_drop = 100.0 / max(1, self.pos.leverage) * 0.92
                adverse = (
                    (self.pos.entry - tick_px) / self.pos.entry * 100.0
                    if self.pos.side == "LONG"
                    else (tick_px - self.pos.entry) / self.pos.entry * 100.0
                )
                if adverse >= liq_drop:
                    self.events.append(
                        OrderEvent(
                            bar_idx=ev.bar_idx,
                            symbol=self.symbol,
                            order_action="CLOSE",
                            side=self.pos.side,
                            qty=self.pos.qty,
                            margin_usdt=self.pos.margin_usdt,
                            leverage=self.pos.leverage,
                            price_ref=tick_px,
                            reason="LİKİDASYON KORUMASI",
                        )
                    )
                    return
                plan = self._trade_plan
                if plan:
                    tp2_hit = (
                        self.pos.side == "LONG" and tick_px >= plan["tp2"]
                    ) or (
                        self.pos.side == "SHORT" and tick_px <= plan["tp2"]
                    )
                    if tp2_hit:
                        self.events.append(
                            OrderEvent(
                                bar_idx=ev.bar_idx,
                                symbol=self.symbol,
                                order_action="CLOSE",
                                side=self.pos.side,
                                qty=self.pos.qty,
                                margin_usdt=self.pos.margin_usdt,
                                leverage=self.pos.leverage,
                                price_ref=plan["tp2"],
                                reason=f"{plan['source']} TP2 (2R)",
                            )
                        )
                        return
                    tp1_hit = (
                        self.pos.side == "LONG" and tick_px >= plan["tp1"]
                    ) or (
                        self.pos.side == "SHORT" and tick_px <= plan["tp1"]
                    )
                    if not plan.get("tp1_hit") and tp1_hit:
                        if self.pos.side == "LONG":
                            self.pos.stop = max(self.pos.stop, self.pos.entry)
                        else:
                            self.pos.stop = min(self.pos.stop, self.pos.entry)
                        plan["tp1_hit"] = True
                        self.events.append(
                            OrderEvent(
                                bar_idx=ev.bar_idx,
                                symbol=self.symbol,
                                order_action="CLOSE",
                                side=self.pos.side,
                                qty=self.pos.qty * float(plan.get("tp1_fraction", 0.5)),
                                margin_usdt=self.pos.margin_usdt
                                * float(plan.get("tp1_fraction", 0.5)),
                                leverage=self.pos.leverage,
                                price_ref=plan["tp1"],
                                reason=f"{plan['source']} TP1 (1R) başabaş",
                            )
                        )
                        return
                if self.supertrend_trailing and previous_supertrend:
                    st_dir, st_stop = previous_supertrend
                    pos_dir = 1 if self.pos.side == "LONG" else -1
                    if st_dir == pos_dir and self.risk.profit_pct(self.pos, tick_px) > 0:
                        if self.pos.side == "LONG":
                            self.pos.stop = max(self.pos.stop, st_stop)
                        else:
                            self.pos.stop = min(self.pos.stop, st_stop)
                res = self.risk.update(self.pos, tick_px)
                if res["action"] == "close":
                    self.events.append(
                        OrderEvent(
                            bar_idx=ev.bar_idx,
                            symbol=self.symbol,
                            order_action="CLOSE",
                            side=self.pos.side,
                            qty=self.pos.qty,
                            margin_usdt=self.pos.margin_usdt,
                            leverage=self.pos.leverage,
                            price_ref=self.pos.stop,
                            reason=res["reason"],
                        )
                    )
                    return

        ml_score = self.ml.predict(history_slice)["score"] if self.ml else None
        close_s = history_slice["close"]
        vol_s = history_slice["volume"]
        vol_std = float(vol_s.tail(30).std() or 1.0)
        vol_z = (float(vol_s.iloc[-1]) - float(vol_s.tail(30).mean())) / (vol_std or 1.0)
        sign_dir = 1.0 if float(close_s.iloc[-1]) >= float(close_s.iloc[-2]) else -1.0
        flow_proxy = float(
            np.clip(
                sign_dir * min(abs(vol_z), 3.0) * 33.0,
                -100.0,
                100.0,
            )
        )
        combined = self.strategy.combine(
            ind["score"],
            flow_proxy,
            0.0,
            ml_score,
            market_context={**ind.get("snapshot", {}), "cvd_slope": 0.0},
        )

        if self.pos is not None:
            pnl = self.risk.profit_pct(self.pos, ev.close)
            ex_dec = self.strategy.exit_decision(
                self.pos.side, combined, flow_proxy, False, pnl
            )
            if ex_dec["action"] == "close":
                self.events.append(
                    SignalEvent(
                        bar_idx=ev.bar_idx,
                        symbol=self.symbol,
                        action="EXIT",
                        score=combined["total"],
                        price=ev.close,
                        reason=ex_dec["reason"],
                    )
                )
                return

            can_add, _ = self.risk.can_add_to_winner(self.pos, ev.close)
            if self._trade_plan and self._trade_plan.get("tp1_hit"):
                can_add = False
            if can_add:
                dec = self.strategy.entry_decision(
                    combined,
                    False,
                    has_position=True,
                    can_pyramid=True,
                    current_side=self.pos.side,
                )
                if dec["action"] in ("ADD_LONG", "ADD_SHORT"):
                    self.events.append(
                        SignalEvent(
                            bar_idx=ev.bar_idx,
                            symbol=self.symbol,
                            action=dec["action"],
                            score=combined["total"],
                            price=ev.close,
                            reason=dec["reason"],
                        )
                    )
        else:
            dec = self.strategy.entry_decision(combined, False, has_position=False)
            if dec["action"] in ("LONG", "SHORT"):
                self.events.append(
                    SignalEvent(
                        bar_idx=ev.bar_idx,
                        symbol=self.symbol,
                        action=dec["action"],
                        score=combined["total"],
                        price=ev.close,
                        reason=dec["reason"],
                    )
                )

    def _handle_signal_event(self, sig: SignalEvent):
        if sig.action == "EXIT" and self.pos is not None:
            self.events.append(
                OrderEvent(
                    bar_idx=sig.bar_idx,
                    symbol=self.symbol,
                    order_action="CLOSE",
                    side=self.pos.side,
                    qty=self.pos.qty,
                    margin_usdt=self.pos.margin_usdt,
                    leverage=self.pos.leverage,
                    price_ref=sig.price,
                    reason=sig.reason,
                )
            )
        elif sig.action in ("LONG", "SHORT") and self.pos is None:
            prepared = self._prepare_atr_plan(sig.action, sig.price)
            if self.trade_plan_enabled and not prepared.get("accepted"):
                return
            if prepared:
                leverage = int(prepared["leverage"])
                qty = self.risk.position_size(self.balance, sig.price, prepared["stop"])
                info = {"margin_usdt": qty * sig.price / max(1, leverage)}
            elif self.fixed_margin_usdt is not None:
                leverage = self.leverage
                if self.balance < self.fixed_margin_usdt:
                    return
                qty = self.fixed_margin_usdt * leverage / sig.price
                info = {"margin_usdt": self.fixed_margin_usdt}
            else:
                leverage = self.leverage
                qty, info = self.risk.leveraged_entry_size(
                    self.balance, sig.price, self.capital_pct, leverage
                )
            if qty > 0:
                self.events.append(
                    OrderEvent(
                        bar_idx=sig.bar_idx,
                        symbol=self.symbol,
                        order_action="OPEN",
                        side=sig.action,
                        qty=qty,
                        margin_usdt=info["margin_usdt"],
                        leverage=leverage,
                        price_ref=sig.price,
                        reason=sig.reason,
                        trade_plan=prepared,
                    )
                )
        elif sig.action in ("ADD_LONG", "ADD_SHORT") and self.pos is not None:
            if self.fixed_margin_usdt is not None:
                return
            prepared = self._prepare_atr_plan(self.pos.side, sig.price)
            if self.trade_plan_enabled and not prepared.get("accepted"):
                return
            if prepared:
                leverage = int(prepared["leverage"])
                qty = self.risk.position_size(self.balance, sig.price, prepared["stop"])
                info = {"margin_usdt": qty * sig.price / max(1, leverage)}
            else:
                leverage = self.leverage
                qty, info = self.risk.leveraged_entry_size(
                    self.balance, sig.price, self.capital_pct, leverage
                )
            margin_ok, _ = self.risk.margin_cap_ok(
                self.pos.margin_usdt, info["margin_usdt"], self.balance
            )
            if qty > 0 and margin_ok:
                self.events.append(
                    OrderEvent(
                        bar_idx=sig.bar_idx,
                        symbol=self.symbol,
                        order_action="ADD",
                        side=self.pos.side,
                        qty=qty,
                        margin_usdt=info["margin_usdt"],
                        leverage=leverage,
                        price_ref=sig.price,
                        reason=sig.reason,
                        trade_plan=prepared,
                    )
                )

    def _handle_order_event(self, order: OrderEvent):
        if order.order_action in ("OPEN", "ADD"):
            is_buy = order.side == "LONG"
        else:
            is_buy = order.side == "SHORT"
        fill_px, slip_abs = self._apply_slippage(order.price_ref, is_buy)
        fee_usdt = order.qty * fill_px * (self.fee_pct / 100.0)
        self.events.append(
            FillEvent(
                bar_idx=order.bar_idx,
                symbol=order.symbol,
                order_action=order.order_action,
                side=order.side,
                qty=order.qty,
                fill_price=fill_px,
                fee_usdt=fee_usdt,
                slippage_abs=slip_abs,
                margin_usdt=order.margin_usdt,
                leverage=order.leverage,
                reason=order.reason,
                trade_plan=order.trade_plan,
            )
        )

    def _handle_fill_event(self, fill: FillEvent):
        self.balance -= fill.fee_usdt
        if fill.order_action in ("OPEN", "ADD"):
            self._position_fees_usdt += fill.fee_usdt
        if fill.order_action == "OPEN":
            if fill.trade_plan:
                direction = 1.0 if fill.side == "LONG" else -1.0
                stop = fill.fill_price - direction * float(fill.trade_plan["risk_distance"])
            else:
                stop = self.risk.initial_stop(fill.side, fill.fill_price, fill.leverage)
            self.pos = Position(
                symbol=fill.symbol,
                side=fill.side,
                entry=fill.fill_price,
                qty=fill.qty,
                stop=stop,
                leverage=fill.leverage,
                margin_usdt=fill.margin_usdt,
                layers=1,
                last_add_price=fill.fill_price,
            )
            self._trade_plan = (
                self._make_r_plan(
                    fill.side,
                    fill.fill_price,
                    stop,
                    str(fill.trade_plan.get("source") or "ATR"),
                    float(fill.trade_plan.get("atr") or 0.0),
                )
                if fill.trade_plan
                else None
            )
        elif fill.order_action == "ADD" and self.pos is not None:
            self.pos.add_layer(
                add_price=fill.fill_price,
                add_qty=fill.qty,
                add_margin_usdt=fill.margin_usdt,
                stop_loss_pct=self.risk.effective_stop_pct(fill.leverage),
            )
            if self._trade_plan is not None:
                self._trade_plan = self._make_r_plan(
                    self.pos.side,
                    self.pos.entry,
                    self.pos.stop,
                    str((fill.trade_plan or {}).get("source") or "ATR"),
                    float((fill.trade_plan or {}).get("atr") or 0.0),
                )
        elif fill.order_action == "CLOSE" and self.pos is not None:
            pnl_pct = self.risk.profit_pct(self.pos, fill.fill_price)
            roe_pct = self.risk.roe_pct(self.pos, fill.fill_price)
            original_qty = self.pos.qty
            closed_qty = min(original_qty, max(0.0, float(fill.qty)))
            if closed_qty <= 0:
                return
            direction = 1.0 if self.pos.side == "LONG" else -1.0
            gross_pnl_usdt = direction * (fill.fill_price - self.pos.entry) * closed_qty
            closed_fraction = closed_qty / original_qty
            allocated_entry_fees = self._position_fees_usdt * closed_fraction
            total_fees_usdt = allocated_entry_fees + fill.fee_usdt
            net_pnl_usdt = gross_pnl_usdt - total_fees_usdt
            self.balance = max(0.0, self.balance + gross_pnl_usdt)
            fully_closed = closed_qty >= original_qty - max(original_qty * 1e-9, 1e-12)
            self.trades.append(
                {
                    "bar_idx": fill.bar_idx,
                    "symbol": fill.symbol,
                    "side": self.pos.side,
                    "entry": round(self.pos.entry, 4),
                    "exit": round(fill.fill_price, 4),
                    "qty": closed_qty,
                    "partial": not fully_closed,
                    "layers": self.pos.layers,
                    "leverage": self.pos.leverage,
                    "pnl_pct": round(pnl_pct, 2),
                    "roe_pct": round(roe_pct, 2),
                    "pnl_usdt": round(net_pnl_usdt, 2),
                    "gross_pnl_usdt": round(gross_pnl_usdt, 2),
                    "fees_usdt": round(total_fees_usdt, 2),
                    "reason": fill.reason,
                }
            )
            if fully_closed:
                self.pos = None
                self._trade_plan = None
                self._position_fees_usdt = 0.0
            else:
                self.pos.qty = original_qty - closed_qty
                self.pos.margin_usdt *= self.pos.qty / original_qty
                self._position_fees_usdt -= allocated_entry_fees

    def run_df(self, df: pd.DataFrame, warmup: int = 60) -> dict:
        no_bias = verify_no_lookahead_bias(df, min(warmup + 10, len(df) - 15))
        n = len(df)
        start = max(2, int(warmup))
        for i in range(start, n):
            row = df.iloc[i]
            ts_val = float(row["ts"]) if "ts" in df.columns else float(i)
            ev = MarketEvent(
                bar_idx=i,
                ts=ts_val,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
            )
            self.events.append(ev)
            history_slice = df.iloc[: i + 1]
            while self.events:
                cur = self.events.popleft()
                self.events_processed += 1
                if isinstance(cur, MarketEvent):
                    self._handle_market_event(cur, history_slice)
                elif isinstance(cur, SignalEvent):
                    self._handle_signal_event(cur)
                elif isinstance(cur, OrderEvent):
                    self._handle_order_event(cur)
                elif isinstance(cur, FillEvent):
                    self._handle_fill_event(cur)

            unrealized = 0.0
            if self.pos is not None:
                _fund = (
                    self.pos.qty
                    * float(row["close"])
                    * (self.funding_8h_pct / 100.0)
                    * (self.bar_minutes / 480.0)
                )
                funding_charge = min(self.balance, _fund)
                self.balance -= funding_charge
                self.funding_paid_usdt += funding_charge
                unrealized = self.risk.pnl_usdt(self.pos, float(row["close"]))
            self.equity_curve.append(
                {
                    "bar_idx": i,
                    "balance": round(self.balance, 2),
                    "equity": round(self.balance + unrealized, 2),
                }
            )

        wins = [t for t in self.trades if t["pnl_usdt"] >= 0]
        eq = [e["equity"] for e in self.equity_curve] or [self.initial_balance]
        peak = eq[0]
        max_dd = 0.0
        for v in eq:
            peak = max(peak, v)
            if peak > 0:
                max_dd = max(max_dd, (peak - v) / peak * 100.0)

        final_equity = eq[-1]
        total_ret_pct = (final_equity / self.initial_balance - 1.0) * 100.0
        return {
            "trades_count": len(self.trades),
            "winrate_pct": round(len(wins) / len(self.trades) * 100.0, 1)
            if self.trades
            else 0.0,
            "total_return_pct": round(total_ret_pct, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "final_balance": round(self.balance, 2),
            "final_equity": round(final_equity, 2),
            "funding_paid_usdt": round(self.funding_paid_usdt, 4),
            "execution_model": (
                f"sabit_{self.fixed_margin_usdt:g}_USDT_{self.leverage}x"
                if self.fixed_margin_usdt is not None
                else f"serbest_marj_x{self.leverage}"
            ),
            "stop_model": self.risk.stop_model,
            "runner_exit": self.runner_exit,
            "orderflow_exit_simulated": False,
            "events_processed": self.events_processed,
            "lookahead_bias_free": no_bias,
            "trades": self.trades,
            "equity_curve": self.equity_curve,
        }


def run_out_of_sample_test(
    df_or_csv: pd.DataFrame | str,
    train_ratio: float = 0.70,
    symbol: str = "BTC/USDT",
    trade_plan_cfg: dict | None = None,
    fixed_margin_usdt: float | None = 50.0,
    leverage: int = 10,
    stop_model: str = "marj",
    runner_exit: bool = True,
) -> dict:
    """Verinin ilk %70'inde (In-Sample) en iyi parametreleri seçip ML'i eğitir;
    hiç görmediği son %30 veride (Out-of-Sample) dondurulmuş parametrelerle test eder."""
    if trade_plan_cfg is None:
        trade_plan_cfg = {"aktif": False}
    df = (
        pd.read_csv(df_or_csv)
        if isinstance(df_or_csv, str)
        else df_or_csv.reset_index(drop=True)
    )
    split = max(70, int(len(df) * train_ratio))
    split = min(split, max(70, len(df) - 35))
    is_df = df.iloc[:split].reset_index(drop=True)
    warmup_oos = min(60, split // 2)
    oos_df = df.iloc[max(0, split - warmup_oos) :].reset_index(drop=True)

    candidates = [
        {"long_th": 40.0, "short_th": -40.0, "w_ind": 0.45, "w_flow": 0.25, "w_news": 0.15},
        {"long_th": 50.0, "short_th": -50.0, "w_ind": 0.50, "w_flow": 0.20, "w_news": 0.15},
        {"long_th": 55.0, "short_th": -55.0, "w_ind": 0.40, "w_flow": 0.30, "w_news": 0.15},
    ]
    best_params = candidates[0]
    best_is_rep: dict = {}
    best_obj = -1e18

    for cand in candidates:
        bt_is = EventDrivenBacktester(
            symbol=symbol,
            strategy_params=cand,
            trade_plan_cfg=trade_plan_cfg,
            fixed_margin_usdt=fixed_margin_usdt,
            leverage=leverage,
            stop_model=stop_model,
            runner_exit=runner_exit,
        )
        rep_is = bt_is.run_df(is_df, warmup=min(45, len(is_df) // 3))
        obj = rep_is["total_return_pct"] - 0.5 * rep_is["max_drawdown_pct"]
        if obj > best_obj:
            best_obj = obj
            best_params = cand
            best_is_rep = rep_is

    # Seçilen parametreyi DONDUR ve hiç görülmemiş Out-of-Sample verisinde test et
    bt_oos = EventDrivenBacktester(
        symbol=symbol,
        strategy_params=best_params,
        trade_plan_cfg=trade_plan_cfg,
        fixed_margin_usdt=fixed_margin_usdt,
        leverage=leverage,
        stop_model=stop_model,
        runner_exit=runner_exit,
    )
    rep_oos = bt_oos.run_df(oos_df, warmup=min(warmup_oos, len(oos_df) // 3))

    is_ret = best_is_rep.get("total_return_pct", 0.0)
    oos_ret = rep_oos.get("total_return_pct", 0.0)
    oos_dd = rep_oos.get("max_drawdown_pct", 0.0)
    verdict = (
        "SAĞLAM (Overfit Yok)"
        if (oos_ret >= -5.0 and oos_dd < 35.0)
        else "DİKKAT (OOS Düşüşü)"
    )
    return {
        "train_bars": len(is_df),
        "oos_bars": len(df) - split,
        "selected_params": best_params,
        "in_sample_return_pct": is_ret,
        "oos_return_pct": oos_ret,
        "oos_max_drawdown_pct": oos_dd,
        "oos_trades": rep_oos.get("trades_count", 0),
        "verdict": verdict,
        "in_sample_report": best_is_rep,
        "oos_report": rep_oos,
    }


def run(
    csv_path: str,
    symbol: str = "BTC/USDT",
    run_oos: bool = True,
    trade_plan_cfg: dict | None = None,
    fixed_margin_usdt: float | None = 50.0,
    leverage: int = 10,
    stop_model: str = "marj",
    runner_exit: bool = True,
) -> dict:
    if trade_plan_cfg is None:
        trade_plan_cfg = {"aktif": False}
    df = pd.read_csv(csv_path)
    bt = EventDrivenBacktester(
        symbol=symbol,
        trade_plan_cfg=trade_plan_cfg,
        fixed_margin_usdt=fixed_margin_usdt,
        leverage=leverage,
        stop_model=stop_model,
        runner_exit=runner_exit,
    )
    rep = bt.run_df(df)
    print(f"Olay (Event) sayısı : {rep['events_processed']}")
    print(f"İşlem sayısı        : {rep['trades_count']}")
    print(f"Kazanma oranı       : %{rep['winrate_pct']:.1f}")
    print(f"Toplam getiri       : %{rep['total_return_pct']:+.2f}")
    print(f"Maks. Drawdown      : %{rep['max_drawdown_pct']:.2f}")
    if rep["runner_exit"] and not rep["orderflow_exit_simulated"]:
        print(
            "Order-flow çıkışı   : SİMÜLE EDİLMEDİ — "
            "OHLCV geçmiş tick/CVD verisi içermez; yalnız stop/trailing çıkışları çalışır."
        )
    if run_oos and len(df) >= 120:
        oos = run_out_of_sample_test(
            df,
            symbol=symbol,
            trade_plan_cfg=trade_plan_cfg,
            fixed_margin_usdt=fixed_margin_usdt,
            leverage=leverage,
            stop_model=stop_model,
            runner_exit=runner_exit,
        )
        rep["oos_report"] = oos
        print(
            f"OOS Test Sonucu     : {oos['verdict']} "
            f"(IS %{oos['in_sample_return_pct']:+.2f} / OOS %{oos['oos_return_pct']:+.2f})"
        )
    return rep


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım: python -m src.backtest veri.csv [--legacy-risk | --atr-risk]")
        sys.exit(1)
    kwargs = {}
    if "--legacy-risk" in sys.argv:
        kwargs = {
            "fixed_margin_usdt": None,
            "leverage": 20,
            "stop_model": "fiyat_yuzde",
            "runner_exit": False,
            "trade_plan_cfg": {"aktif": False},
        }
    elif "--atr-risk" in sys.argv:
        kwargs = {
            "fixed_margin_usdt": None,
            "leverage": 20,
            "stop_model": "fiyat_yuzde",
            "runner_exit": False,
            "trade_plan_cfg": dict(DEFAULT_TRADE_PLAN),
        }
    run(sys.argv[1], **kwargs)
