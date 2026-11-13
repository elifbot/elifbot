from __future__ import annotations

from sentez.models import Bar, Config, Signal

H = 3_600_000


def bar(i: int, o: float, h: float, l: float, c: float, step: int = 60_000, v: float = 100.0) -> Bar:
    return Bar(i * step, o, h, l, c, v)


def flat(i: int, px: float = 100.0, step: int = 60_000) -> Bar:
    return bar(i, px, px + 0.3, px - 0.3, px, step)


def zero_cost_cfg(**kw) -> Config:
    base = dict(taker_bps=0.0, slip_bps=0.0, spread_bps=0.0, funding_bps_8h=0.0, min_edge_ratio=0.0,
                max_notional=100_000.0, bar_ms=60_000, cooldown_bars=0, max_hold_bars=50)
    base.update(kw)
    return Config(**base).validate()


class FakeSource:
    """Önceden belirlenmiş sinyaller: {(sym, ts): Signal}; 'always' ise her zaman damgasında."""

    def __init__(self, sigs=None, always=None, breadth=None):
        self.sigs, self.always, self._breadth = sigs or {}, always, breadth

    def signal(self, sym, ts):
        s = self.sigs.get((sym, ts))
        if s is None and self.always is not None:
            a = self.always
            s = Signal(a.side, a.score, a.votes, a.atr, a.price, ts)
        return (s, "SIGNAL") if s else (None, "THRESHOLD")

    def breadth(self, ts):
        return self._breadth


def long_sig(ts=0, price=100.0, atr=1.0, score=5, side=1) -> Signal:
    return Signal(side, score if side > 0 else -score, {"ema": side}, atr, price, ts)
