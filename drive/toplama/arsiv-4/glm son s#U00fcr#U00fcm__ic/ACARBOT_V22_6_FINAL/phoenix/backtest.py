from dataclasses import dataclass
from .strategy import Strategy
from .risk import RiskManager


@dataclass
class Bar:
    ts: float
    open: float
    high: float
    low: float
    close: float
    signal: float = 0.0
    contract_size: float = 1.0


@dataclass
class BacktestResult:
    trades: int
    wins: int
    losses: int
    net_pnl: float
    max_drawdown: float
    expectancy: float


class Backtester:
    def __init__(self, cfg=None):
        from .config import Config
        self.cfg = cfg or Config()
        self.strategy = Strategy(self.cfg)
        self.risk = RiskManager(self.cfg)

    def run(self, bars):
        equity = self.cfg.reference_equity
        peak = equity
        dd = 0.0
        pnl = []
        i = 0
        while i < len(bars):
            b = bars[i]
            if abs(b.signal) < self.cfg.min_score or b.close <= 0 or b.contract_size <= 0:
                i += 1
                continue
            # Signal is known only at bar close -> fill at the NEXT bar's open (no phantom fill at the signal close).
            if i + 1 >= len(bars) or bars[i + 1].open <= 0:
                i += 1
                continue
            entry = bars[i + 1].open
            fill_idx = i + 1
            notional = self.cfg.entry_notional_usd
            qty = notional / (entry * b.contract_size)
            entry_fee = self.risk.estimated_entry_fee(notional)
            side = "LONG" if b.signal > 0 else "SHORT"
            stop = self.risk.stop_price(entry, side, qty, b.contract_size, entry_fee)
            dist = abs(entry - stop)
            target = entry + dist * self.cfg.tp_r if side == "LONG" else entry - dist * self.cfg.tp_r
            outcome = None
            exit_price = entry
            window = bars[fill_idx : fill_idx + self.cfg.max_hold_bars]
            for j, x in enumerate(window, fill_idx):
                hit_stop = (x.low <= stop) if side == "LONG" else (x.high >= stop)
                hit_target = (x.high >= target) if side == "LONG" else (x.low <= target)
                # Conservative same-bar rule: stop wins when both are touched.
                if hit_stop:
                    exit_price, outcome = stop, "STOP"
                    break
                if hit_target:
                    exit_price, outcome = target, "TARGET"
                    break
            if outcome is None:
                if not window:
                    i += 1
                    continue
                j = fill_idx + len(window) - 1
                exit_price, outcome = window[-1].close, "TIME"

            exit_notional = abs(exit_price * qty * b.contract_size)
            gross = (exit_price - entry) * qty * b.contract_size * (1 if side == "LONG" else -1)
            exit_fee = exit_notional * self.cfg.fee_bps_per_side / 10000
            slip = exit_notional * self.cfg.slippage_bps_reserve / 10000
            net = gross - entry_fee - exit_fee - slip
            equity += net
            pnl.append(net)
            peak = max(peak, equity)
            dd = max(dd, peak - equity)
            i = j + 1

        wins = sum(x > 0 for x in pnl)
        losses = sum(x < 0 for x in pnl)
        return BacktestResult(
            len(pnl), wins, losses, sum(pnl), dd, sum(pnl) / len(pnl) if pnl else 0.0
        )

    def run_snapshots(self, snapshots, bars_by_symbol):
        grouped = {}
        for s in snapshots:
            grouped.setdefault(s.market.symbol, []).append(s)
        results = []
        for symbol, ss in grouped.items():
            bars = bars_by_symbol[symbol]
            signals = {s.ts: self.strategy.evaluate(s) for s in ss}
            converted = []
            for b in bars:
                sig = signals.get(b.ts)
                score = 0.0
                if sig:
                    score = sig.score * (1 if sig.side == "LONG" else -1)
                converted.append(Bar(b.ts, b.open, b.high, b.low, b.close, score, b.contract_size))
            results.append(self.run(converted))
        return results
