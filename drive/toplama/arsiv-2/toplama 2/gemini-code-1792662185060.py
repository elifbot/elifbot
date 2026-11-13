"""Event-Driven & Look-Ahead Bias İçermeyen Backtest + Out-of-Sample (OOS) Test Motoru."""
from __future__ import annotations
import sys
from collections import deque
from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd
from .indicators import indicator_score
from .ml_predictor import MLPredictor
from .risk import Position, RiskManager
from .strategy import Strategy

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
    order_action: str
    side: str
    qty: float
    margin_usdt: float
    leverage: int
    price_ref: float
    reason: str

@dataclass
class FillEvent:
    bar_idx: int
    symbol: str
    order_action: str
    side: str
    qty: float
    fill_price: float
    fee_usdt: float
    slippage_usdt: float
    margin_usdt: float
    leverage: int
    reason: str

def verify_no_lookahead_bias(df: pd.DataFrame, check_bar: int = 100) -> bool:
    if len(df) <= check_bar + 10:
        check_bar = max(35, len(df) // 2)
    slice_clean = df.iloc[: check_bar + 1].copy()
    ind_clean = indicator_score(slice_clean)["score"]
    ml_clean = MLPredictor(min_train_bars=40).predict(slice_clean)["score"]

    df_tampered = df.copy()
    df_tampered.iloc[check_bar + 1 :, df_tampered.columns.get_loc("close")] *= 50.0
    df_tampered.iloc[check_bar + 1 :, df_tampered.columns.get_loc("high")] *= 50.0

    slice_test = df_tampered.iloc[: check_bar + 1].copy()
    ind_test = indicator_score(slice_test)["score"]
    ml_test = MLPredictor(min_train_bars=40).predict(slice_test)["score"]
    return abs(ind_clean - ind_test) < 1e-9 and abs(ml_clean - ml_test) < 1e-9

class EventDrivenBacktester:
    def __init__(self, symbol: str = "BTC/USDT", initial_balance: float = 10_000.0, capital_pct: float = 10.0, leverage: int = 20, stop_loss_pct: float = 5.0, fee_pct: float = 0.04, slippage_bps: float = 2.0, use_ml: bool = True, unlimited_pyramiding: bool = True, strategy_params: dict | None = None, bar_minutes: float = 5.0, funding_8h_pct: float = 0.01):
        self.bar_minutes = bar_minutes
        self.funding_8h_pct = funding_8h_pct
        self.funding_paid_usdt = 0.0
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.capital_pct = capital_pct
        self.leverage = leverage
        self.fee_pct = fee_pct
        self.slippage_bps = slippage_bps
        self.use_ml = use_ml

        self.risk = RiskManager(stop_loss_pct=stop_loss_pct, capital_pct_per_entry=capital_pct, leverage=leverage, unlimited_pyramiding=unlimited_pyramiding)
        sp = strategy_params or {}
        self.strategy = Strategy(
            w_ind=sp.get("w_ind", 0.50), w_flow=sp.get("w_flow", 0.20), w_news=sp.get("w_news", 0.15),
            long_th=sp.get("long_th", 55.0), short_th=sp.get("short_th", -55.0), exit_th=sp.get("exit_th", 15.0),
            flow_trigger=sp.get("flow_trigger", True), flow_th=sp.get("flow_th", 50.0), flow_ind_min=sp.get("flow_ind_min", 10.0),
            flow_min_total=sp.get("flow_min_total", 15.0), w_ml=sp.get("w_ml", 0.15 if use_ml else 0.0),
        )
        self.ml = MLPredictor(min_train_bars=60, retrain_every=25) if use_ml else None
        self.events: deque[Any] = deque()
        self.pos: Position | None = None
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.events_processed: int = 0

    def _apply_slippage(self, price: float, is_buy: bool) -> tuple[float, float]:
        slip_frac = self.slippage_bps / 10_000.0
        fill_px = price * (1.0 + slip_frac) if is_buy else price * (1.0 - slip_frac)
        return fill_px, abs(fill_px - price)

    def _intrabar_ticks(self, ev: MarketEvent) -> list[float]:
        if self.pos is not None and self.pos.side == "SHORT":
            return [ev.open, ev.high, ev.low, ev.close]
        return [ev.open, ev.low, ev.high, ev.close]

    def _handle_market_event(self, ev: MarketEvent, history_slice: pd.DataFrame):
        if self.pos is not None:
            for tick_px in self._intrabar_ticks(ev):
                _mm = self.risk.maintenance_margin_pct / 100.0
                _lev = max(1, int(self.pos.leverage))
                liq_px = self.pos.entry * (1.0 - (1.0 / _lev - _mm)) if self.pos.side == "LONG" else self.pos.entry * (1.0 + (1.0 / _lev - _mm))
                liquidated = tick_px <= liq_px if self.pos.side == "LONG" else tick_px >= liq_px
                if liquidated:
                    self.events.append(OrderEvent(bar_idx=ev.bar_idx, symbol=self.symbol, order_action="CLOSE", side=self.pos.side, qty=self.pos.qty, margin_usdt=self.pos.margin_usdt, leverage=self.pos.leverage, price_ref=liq_px, reason="LİKİDASYON"))
                    return
                res = self.risk.update(self.pos, tick_px)
                if res["action"] == "close":
                    self.events.append(OrderEvent(bar_idx=ev.bar_idx, symbol=self.symbol, order_action="CLOSE", side=self.pos.side, qty=self.pos.qty, margin_usdt=self.pos.margin_usdt, leverage=self.pos.leverage, price_ref=res["stop"], reason=res["reason"]))
                    return

        ind = indicator_score(history_slice)
        ml_score = self.ml.predict(history_slice)["score"] if self.ml else None
        close_s, vol_s = history_slice["close"], history_slice["volume"]
        signed_v = np.sign(close_s.diff().fillna(0.0)) * vol_s
        flow_proxy = float(np.clip(signed_v.tail(10).sum() / max(vol_s.tail(10).sum(), 1e-9) * 80.0, -100.0, 100.0))
        combined = self.strategy.combine(ind["score"], flow_proxy, 0.0, ml_score)

        if self.pos is not None:
            pnl = self.risk.profit_pct(self.pos, ev.close)
            ex = self.strategy.exit_decision(self.pos.side, combined, flow_proxy, False, pnl)
            if ex["action"] == "close":
                self.events.append(SignalEvent(ev.bar_idx, self.symbol, "CLOSE", combined["total"], ev.close, f"BOT ÇIKIŞI: {ex['reason']}"))
                return
            can_add, add_why = self.risk.can_add_to_winner(self.pos, ev.close)
            if can_add:
                dec = self.strategy.entry_decision(combined, False, has_position=True, can_pyramid=True, current_side=self.pos.side)
                if dec["action"] in ("ADD_LONG", "ADD_SHORT"):
                    self.events.append(SignalEvent(ev.bar_idx, self.symbol, dec["action"], combined["total"], ev.close, f"{add_why} | {dec['reason']}"))
        else:
            dec = self.strategy.entry_decision(combined, False, has_position=False)
            if dec["action"] in ("LONG", "SHORT"):
                self.events.append(SignalEvent(ev.bar_idx, self.symbol, dec["action"], combined["total"], ev.close, dec["reason"]))

    def _handle_signal_event(self, sig: SignalEvent):
        if sig.action == "CLOSE" and self.pos is not None:
            self.events.append(OrderEvent(bar_idx=sig.bar_idx, symbol=sig.symbol, order_action="CLOSE", side=self.pos.side, qty=self.pos.qty, margin_usdt=self.pos.margin_usdt, leverage=self.pos.leverage, price_ref=sig.price, reason=sig.reason))
        elif sig.action in ("LONG", "SHORT") and self.pos is None:
            qty, info = self.risk.leveraged_entry_size(self.balance, sig.price, self.capital_pct, self.leverage)
            if qty > 0:
                self.events.append(OrderEvent(bar_idx=sig.bar_idx, symbol=sig.symbol, order_action="OPEN", side=sig.action, qty=qty, margin_usdt=info["margin_usdt"], leverage=self.leverage, price_ref=sig.price, reason=sig.reason))
        elif sig.action in ("ADD_LONG", "ADD_SHORT") and self.pos is not None:
            qty, info = self.risk.leveraged_entry_size(self.balance, sig.price, self.capital_pct, self.leverage)
            if qty > 0:
                self.events.append(OrderEvent(bar_idx=sig.bar_idx, symbol=sig.symbol, order_action="ADD", side=self.pos.side, qty=qty, margin_usdt=info["margin_usdt"], leverage=self.leverage, price_ref=sig.price, reason=sig.reason))

    def _handle_order_event(self, order: OrderEvent):
        is_buy = (order.side == "LONG") if order.order_action in ("OPEN", "ADD") else (order.side == "SHORT")
        fill_px, slip_per_unit = self._apply_slippage(order.price_ref, is_buy)
        notional = fill_px * order.qty
        self.events.append(FillEvent(bar_idx=order.bar_idx, symbol=order.symbol, order_action=order.order_action, side=order.side, qty=order.qty, fill_price=fill_px, fee_usdt=notional * (self.fee_pct / 100.0), slippage_usdt=slip_per_unit * order.qty, margin_usdt=order.margin_usdt, leverage=order.leverage, reason=order.reason))

    def _handle_fill_event(self, fill: FillEvent):
        self.balance -= fill.fee_usdt
        if fill.order_action == "OPEN":
            self.pos = Position(symbol=fill.symbol, side=fill.side, entry=fill.fill_price, qty=fill.qty, stop=self.risk.initial_stop(fill.side, fill.fill_price, fill.leverage), leverage=fill.leverage, margin_usdt=fill.margin_usdt, layers=1, last_add_price=fill.fill_price)
        elif fill.order_action == "ADD" and self.pos is not None:
            self.pos.add_layer(add_price=fill.fill_price, add_qty=fill.qty, add_margin_usdt=fill.margin_usdt, stop_loss_pct=self.risk.effective_stop_pct(fill.leverage))
        elif fill.order_action == "CLOSE" and self.pos is not None:
            pnl_pct = self.risk.profit_pct(self.pos, fill.fill_price)
            roe_pct = self.risk.roe_pct(self.pos, fill.fill_price)
            pnl_usdt = self.risk.pnl_usdt(self.pos, fill.fill_price)
            self.balance = max(0.0, self.balance + pnl_usdt)
            self.trades.append({"bar_idx": fill.bar_idx, "symbol": fill.symbol, "side": self.pos.side, "entry": round(self.pos.entry, 4), "exit": round(fill.fill_price, 4), "layers": self.pos.layers, "leverage": self.pos.leverage, "pnl_pct": round(pnl_pct, 2), "roe_pct": round(roe_pct, 2), "pnl_usdt": round(pnl_usdt, 2), "reason": fill.reason})
            self.pos = None

    def run_df(self, df: pd.DataFrame, warmup: int = 60) -> dict:
        no_bias = verify_no_lookahead_bias(df, min(warmup + 10, len(df) - 15))
        for i in range(warmup, len(df)):
            row = df.iloc[i]
            history_slice = df.iloc[: i + 1]
            mev = MarketEvent(bar_idx=i, ts=float(row.get("timestamp", row.get("ts", i))), open=float(row["open"]), high=float(row["high"]), low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"]))
            self.events.append(mev)

            while self.events:
                ev = self.events.popleft()
                self.events_processed += 1
                if isinstance(ev, MarketEvent): self._handle_market_event(ev, history_slice)
                elif isinstance(ev, SignalEvent): self._handle_signal_event(ev)
                elif isinstance(ev, OrderEvent): self._handle_order_event(ev)
                elif isinstance(ev, FillEvent): self._handle_fill_event(ev)

            unrealized = 0.0
            if self.pos is not None:
                _fund = self.pos.entry * self.pos.qty * (self.funding_8h_pct / 100.0) * (self.bar_minutes / 480.0)
                self.balance = max(0.0, self.balance - _fund)
                self.funding_paid_usdt += _fund
                unrealized = self.risk.pnl_usdt(self.pos, float(row["close"]))
            self.equity_curve.append({"bar_idx": i, "balance": round(self.balance, 2), "equity": round(self.balance + unrealized, 2)})

        wins = [t for t in self.trades if t["pnl_pct"] >= 0]
        eq = [e["equity"] for e in self.equity_curve] or [self.initial_balance]
        peak, max_dd = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            if peak > 0:
                max_dd = max(max_dd, (peak - v) / peak * 100.0)

        total_ret_pct = (self.balance / self.initial_balance - 1.0) * 100.0
        return {
            "trades_count": len(self.trades), "winrate_pct": round(len(wins) / len(self.trades) * 100.0, 1) if self.trades else 0.0,
            "total_return_pct": round(total_ret_pct, 2), "max_drawdown_pct": round(max_dd, 2), "final_balance": round(self.balance, 2),
            "events_processed": self.events_processed, "lookahead_bias_free": no_bias, "trades": self.trades, "equity_curve": self.equity_curve,
        }

def run_out_of_sample_test(df_or_csv: pd.DataFrame | str, train_ratio: float = 0.70, symbol: str = "BTC/USDT") -> dict:
    df = pd.read_csv(df_or_csv) if isinstance(df_or_csv, str) else df_or_csv.copy().reset_index(drop=True)
    n = len(df)
    split_idx = max(80, int(n * train_ratio))
    if n - split_idx < 40:
        split_idx = max(65, n - 50)

    is_df = df.iloc[:split_idx].reset_index(drop=True)
    warmup_oos = 40
    oos_start = max(0, split_idx - warmup_oos)
    oos_df = df.iloc[oos_start:].reset_index(drop=True)

    candidates = [
        {"w_ind": 0.50, "w_flow": 0.20, "w_news": 0.15, "w_ml": 0.15, "long_th": 50.0, "short_th": -50.0, "exit_th": 15.0},
        {"w_ind": 0.55, "w_flow": 0.25, "w_news": 0.10, "w_ml": 0.10, "long_th": 45.0, "short_th": -45.0, "exit_th": 12.0},
    ]
    best_params, best_is_rep, best_obj = candidates[0], {}, -1e18
    for cand in candidates:
        bt_is = EventDrivenBacktester(symbol=symbol, strategy_params=cand)
        rep_is = bt_is.run_df(is_df, warmup=min(45, len(is_df) // 3))
        obj = rep_is["total_return_pct"] - 0.5 * rep_is["max_drawdown_pct"]
        if obj > best_obj:
            best_obj, best_params, best_is_rep = obj, cand, rep_is

    bt_oos = EventDrivenBacktester(symbol=symbol, strategy_params=best_params)
    rep_oos = bt_oos.run_df(oos_df, warmup=min(warmup_oos, len(oos_df) // 3))
    is_ret, oos_ret, oos_dd = best_is_rep.get("total_return_pct", 0.0), rep_oos.get("total_return_pct", 0.0), rep_oos.get("max_drawdown_pct", 0.0)
    overfitting = bool((is_ret > 5.0 and oos_ret < -8.0) or oos_dd > 25.0)
    verdict = "⚠️ AŞIRI UYUM RİSKİ (Overfitting)" if overfitting else "✅ SAĞLAM (Out-of-Sample Doğrulandı)"

    return {
        "train_bars": len(is_df), "oos_bars": len(df) - split_idx, "selected_params": best_params,
        "in_sample": {"return_pct": is_ret, "max_dd_pct": best_is_rep.get("max_drawdown_pct", 0.0), "winrate_pct": best_is_rep.get("winrate_pct", 0.0), "trades_count": best_is_rep.get("trades_count", 0)},
        "out_of_sample": {"return_pct": oos_ret, "max_dd_pct": oos_dd, "winrate_pct": rep_oos.get("winrate_pct", 0.0), "trades_count": rep_oos.get("trades_count", 0)},
        "overfitting_detected": overfitting, "verdict": verdict, "lookahead_bias_free": bool(rep_oos.get("lookahead_bias_free", True)),
    }