"""PAPER broker: runs signals through the SAME gates the live path uses.

    SIGNAL -> SIZING -> RISK -> CORRELATION -> PAPER ACCEPT / REJECT

Every rejection carries (stage, reason) so "passed 0.30 but why no trade?" is answered
directly from the report. Open paper positions are marked every cycle and closed by
STOP / HARD_LOSS / TARGET / TIME using the production PositionManager.

Fill model (deliberately conservative and simple):
* entry fills at ``signal.entry`` with the configured fee; maker queue risk is NOT modelled
* STOP exits at the worse of (stop, mark); TARGET exits at target; HARD_LOSS/TIME at mark
* marks are cycle-granular, so intra-cycle wicks are invisible (documented limitation)
"""
from __future__ import annotations
import datetime
import json
import os
import time
from dataclasses import asdict
from uuid import uuid4

from .models import Position
from .portfolio import PortfolioRisk
from .position_manager import PositionManager
from .risk import RiskManager
from .sizing import fit_order, meta_from_dict, MarketMeta
from .state import StateStore

BAR_SECONDS = 15 * 60


def _day(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")


def _week(ts: float) -> str:
    y, w, _ = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


class PaperBroker:
    def __init__(self, cfg, equity=1000.0, state_path=None, journal_path=None, resume=False, clock=time.time):
        self.cfg = cfg
        self.risk = RiskManager(cfg)
        self.portfolio = PortfolioRisk(cfg.correlation_limit, cfg.correlation_window,
                                       cfg.correlation_min_samples, cfg.correlation_same_direction_only)
        self.pm = PositionManager(cfg)
        self.clock = clock
        self.equity0 = float(equity)
        self.positions: dict[str, Position] = {}
        self.realized_by_day: dict[str, float] = {}
        self.realized_by_week: dict[str, float] = {}
        self.realized_total = 0.0
        self.peak_equity = self.equity0
        self.closed = []
        self.stats = {"accepted": 0, "rejected": 0, "closed": 0, "wins": 0, "losses": 0}
        self.state = StateStore(state_path) if state_path else None
        self.journal_path = journal_path
        if resume and self.state:
            self._load()
        elif self.state:
            self._save()

    # ---- accounting ---------------------------------------------------------
    def open_positions(self):
        return [p for p in self.positions.values() if p.status == "OPEN"]

    def has_open(self, exchange, symbol):
        return any(p.exchange == exchange and p.symbol == symbol for p in self.open_positions())

    def unrealized(self, marks=None):
        total = 0.0
        for p in self.open_positions():
            mark = (marks or {}).get((p.exchange, p.symbol), p.entry)
            # net_pnl already deducts the entry fee, funding, estimated exit fee and slippage
            total += p.net_pnl(mark, self.cfg.fee_bps_per_side, self.cfg.slippage_bps_reserve)
        return total

    def equity(self, marks=None):
        return self.equity0 + self.realized_total + self.unrealized(marks)

    def daily_loss(self, now=None):
        return min(0.0, self.realized_by_day.get(_day(now or self.clock()), 0.0))

    def weekly_loss(self, now=None):
        return min(0.0, self.realized_by_week.get(_week(now or self.clock()), 0.0))

    # ---- submission ---------------------------------------------------------
    def submit(self, signal, returns=None, meta=None, marks=None):
        """Return dict(status, stage, reason, ...). Never raises for business rejections."""
        now = self.clock()
        key = f"{signal.exchange}:{signal.symbol}:{signal.side}"
        # DEDUPE: one open paper position per exchange:symbol
        for p in self.open_positions():
            if p.exchange == signal.exchange and p.symbol == signal.symbol:
                return self._reject("RISK", "already_open_symbol", key)
        # SIZING (precision/min amount/min notional; same code path as live)
        if isinstance(meta, dict):
            meta = meta_from_dict(meta)
        fitted = signal
        sizing_reason = "ok"
        if meta is not None:
            fitted, sizing_reason, info = fit_order(signal, meta, self.risk, self.cfg)
            if fitted is None:
                return self._reject("SIZING", sizing_reason, key, info=info)
        # RISK
        eq = self.equity(marks)
        self.peak_equity = max(self.peak_equity, eq)
        decision = self.risk.can_enter(eq, self.open_positions(), 0.0, fitted.notional,
                                       daily_loss=self.daily_loss(now), weekly_loss=self.weekly_loss(now),
                                       peak_equity=self.peak_equity)
        if not decision.allowed:
            reason = decision.reason.split(":", 1)[0]
            return self._reject("RISK", reason, key, detail=decision.reason)
        # CORRELATION
        if returns:
            r = self.portfolio.evaluate(fitted.symbol, returns, self.open_positions(), candidate_side=fitted.side)
            if r["blocked"]:
                return self._reject("CORRELATION", "correlation_limit", key,
                                    detail=f"{r['symbol']} corr={r['corr']:.3f} eff={r['effective']:.3f}")
        # ACCEPT
        entry_fee = self.risk.estimated_entry_fee(fitted.notional)
        pid = str(uuid4())
        pos = Position(pid, fitted.exchange, fitted.symbol, fitted.side, fitted.entry, fitted.qty, fitted.notional,
                       fitted.margin, fitted.stop, fitted.target, now, entry_fee=entry_fee,
                       contract_size=fitted.contract_size)
        self.positions[pid] = pos
        self.stats["accepted"] += 1
        self._journal({"event": "OPEN", "ts": now, "id": pid, "exchange": pos.exchange, "symbol": pos.symbol,
                       "side": pos.side, "entry": pos.entry, "qty": pos.qty, "notional": pos.notional,
                       "stop": pos.stop, "target": pos.target, "score": fitted.score, "sizing": sizing_reason})
        self._save()
        return {"status": "ACCEPTED", "stage": "PAPER", "reason": "accepted", "id": pid,
                "sizing": sizing_reason, "key": key}

    def _reject(self, stage, reason, key, detail="", info=None):
        self.stats["rejected"] += 1
        out = {"status": "REJECTED", "stage": stage, "reason": reason, "detail": detail, "key": key}
        if info:
            out["info"] = info
        return out

    # ---- position management ------------------------------------------------
    def update(self, marks, now=None):
        """marks: {(exchange, symbol): last_price}. Returns list of closed trade dicts."""
        now = now or self.clock()
        closed = []
        for pid, p in list(self.positions.items()):
            if p.status != "OPEN":
                continue
            mark = marks.get((p.exchange, p.symbol))
            if mark is None or mark <= 0:
                continue
            bars = int((now - p.opened_at) / BAR_SECONDS)
            reason, _net = self.pm.check(p, mark, bars)
            if not reason:
                continue
            if reason == "STOP":
                exit_price = min(mark, p.stop) if p.side == "LONG" else max(mark, p.stop)
            elif reason == "TARGET":
                exit_price = p.target
            else:
                exit_price = mark
            trade = self.pm.close(p, exit_price, reason, now)
            p.status = "CLOSED"
            day, week = _day(now), _week(now)
            self.realized_by_day[day] = self.realized_by_day.get(day, 0.0) + trade.net_pnl
            self.realized_by_week[week] = self.realized_by_week.get(week, 0.0) + trade.net_pnl
            self.realized_total += trade.net_pnl
            self.stats["closed"] += 1
            self.stats["wins" if trade.net_pnl > 0 else "losses"] += 1
            rec = asdict(trade)
            rec["event"] = "CLOSE"
            self._journal(rec)
            self.closed.append(rec)
            closed.append(rec)
        if closed:
            self._save()
        return closed

    # ---- persistence ----------------------------------------------------------
    def summary(self, marks=None):
        eq = self.equity(marks)
        return {
            "equity_start": self.equity0, "equity_now": round(eq, 4),
            "realized_total": round(self.realized_total, 4),
            "open_positions": len(self.open_positions()),
            "accepted": self.stats["accepted"], "closed": self.stats["closed"],
            "wins": self.stats["wins"], "losses": self.stats["losses"],
            "daily_loss": round(self.daily_loss(), 4), "peak_equity": round(self.peak_equity, 4),
        }

    def _journal(self, obj):
        if not self.journal_path:
            return
        with open(self.journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")

    def _save(self):
        if not self.state:
            return
        self.state.save({
            "equity0": self.equity0, "realized_total": self.realized_total, "peak_equity": self.peak_equity,
            "realized_by_day": self.realized_by_day, "realized_by_week": self.realized_by_week,
            "stats": self.stats, "positions": {k: p.to_dict() for k, p in self.positions.items() if p.status == "OPEN"},
        })

    def _load(self):
        st = self.state.load()
        if not st.get("equity0"):
            return
        self.equity0 = float(st.get("equity0", self.equity0))
        self.realized_total = float(st.get("realized_total", 0.0))
        self.peak_equity = float(st.get("peak_equity", self.equity0))
        self.realized_by_day = dict(st.get("realized_by_day", {}))
        self.realized_by_week = dict(st.get("realized_by_week", {}))
        self.stats.update(st.get("stats", {}))
        self.positions = {k: Position.from_dict(v) for k, v in st.get("positions", {}).items()}
