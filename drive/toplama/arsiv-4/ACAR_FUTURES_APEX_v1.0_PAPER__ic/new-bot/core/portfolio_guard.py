"""Portfolio-level risk helpers. Correlation is a veto, never a signal."""
from __future__ import annotations
from math import sqrt
from typing import Mapping, Sequence


def returns(closes: Sequence[float]) -> list[float]:
    if len(closes) < 3:
        return []
    out=[]
    for a,b in zip(closes[:-1], closes[1:]):
        if a <= 0 or b <= 0:
            return []
        out.append(b/a-1.0)
    return out


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    x,y=returns(a),returns(b)
    n=min(len(x),len(y))
    if n < 20:
        return None
    x,y=x[-n:],y[-n:]
    mx,my=sum(x)/n,sum(y)/n
    vx=sum((v-mx)**2 for v in x)
    vy=sum((v-my)**2 for v in y)
    if vx <= 0 or vy <= 0:
        return None
    return sum((u-mx)*(v-my) for u,v in zip(x,y))/sqrt(vx*vy)


class PortfolioRiskGuard:
    def __init__(self, max_positions: int = 4, max_same_side: int = 3,
                 correlation_limit: float = 0.85):
        if max_positions < 1 or max_same_side < 1:
            raise ValueError("position limits must be positive")
        if not 0 < correlation_limit <= 1:
            raise ValueError("correlation_limit must be in (0, 1]")
        self.max_positions=max_positions
        self.max_same_side=max_same_side
        self.correlation_limit=correlation_limit

    def approve(self, symbol: str, side: str, open_positions: Mapping[str,str],
                histories: Mapping[str,Sequence[float]] | None = None) -> tuple[bool,str]:
        if symbol in open_positions:
            return False,"SYMBOL_ALREADY_OPEN"
        if len(open_positions) >= self.max_positions:
            return False,"PORTFOLIO_POSITION_CAP"
        same=sum(1 for value in open_positions.values() if value == side)
        if same >= self.max_same_side:
            return False,"SAME_SIDE_EXPOSURE_CAP"
        histories=histories or {}
        candidate=histories.get(symbol)
        if candidate:
            for other in open_positions:
                peer=histories.get(other)
                if peer:
                    corr=correlation(candidate,peer)
                    if corr is not None and corr >= self.correlation_limit:
                        return False,f"HIGH_CORRELATION:{other}:{corr:.3f}"
        return True,"OK"
