import math
from collections import Counter


class PortfolioRisk:
    """Pairwise correlation gate.

    V20 rules
    ---------
    * Minimum sample size (``min_samples``): too-short series produce meaningless
      correlations, so the gate is SKIPPED (and counted) instead of firing on noise.
    * Direction-aware: two positions only add concentration when their *P&L* moves
      together. effective = corr * (+1 if same side else -1). LONG A + SHORT B with
      corr +0.9 is a hedge (allowed); LONG A + SHORT B with corr -0.9 is stacked risk
      (blocked). When sides are unknown the raw signed correlation is used.
    * Only ``effective >= limit`` blocks (no abs()) when ``same_direction_only`` is on.
    """

    def __init__(self, correlation_limit=.85, correlation_window=96, min_samples=3, same_direction_only=True):
        self.limit = correlation_limit
        self.window = correlation_window
        self.min_samples = max(3, int(min_samples))
        self.same_direction_only = same_direction_only
        self.stats = Counter()

    @staticmethod
    def _keys(symbol):
        s = str(symbol).upper()
        return (s, s.split(":", 1)[0], s.split("/", 1)[0])

    def _series(self, returns, symbol):
        for key in self._keys(symbol):
            if key in returns and returns[key]:
                return list(returns[key])[-self.window:]
        return None

    @staticmethod
    def _pearson(a, b):
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        va = sum((x - ma) ** 2 for x in a)
        vb = sum((y - mb) ** 2 for y in b)
        if va == 0 or vb == 0:
            return None
        return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)

    def evaluate(self, candidate_symbol, returns, positions, candidate_side=None):
        """Return dict(blocked, symbol, corr, effective, samples, skipped_reason)."""
        out = {"blocked": False, "symbol": "", "corr": 0.0, "effective": 0.0, "samples": 0, "skipped_reason": ""}
        candidate = self._series(returns or {}, candidate_symbol)
        if not candidate:
            out["skipped_reason"] = "no_candidate_series"
            self.stats["skipped_no_series"] += 1
            return out
        if len(candidate) < self.min_samples:
            out["skipped_reason"] = "insufficient_samples"
            out["samples"] = len(candidate)
            self.stats["skipped_insufficient_samples"] += 1
            return out
        compared = 0
        for p in positions:
            if getattr(p, "status", "OPEN") != "OPEN":
                continue
            if self._keys(p.symbol)[0] == self._keys(candidate_symbol)[0]:
                continue
            other = self._series(returns, p.symbol)
            if not other:
                continue
            n = min(len(candidate), len(other), self.window)
            if n < self.min_samples:
                self.stats["skipped_insufficient_samples"] += 1
                continue
            c = self._pearson(candidate[-n:], other[-n:])
            if c is None:
                continue
            compared += 1
            p_side = getattr(p, "side", None)
            if self.same_direction_only and candidate_side and p_side:
                effective = c if str(candidate_side).upper() == str(p_side).upper() else -c
            elif self.same_direction_only:
                effective = c
            else:
                effective = abs(c)
            if effective >= self.limit:
                self.stats["blocked"] += 1
                out.update(blocked=True, symbol=p.symbol, corr=c, effective=effective, samples=n)
                return out
            out["samples"] = max(out["samples"], n)
        self.stats["passed" if compared else "skipped_no_peers"] += 1
        if not compared:
            out["skipped_reason"] = "no_comparable_positions"
        return out

    def correlated(self, candidate_symbol, returns, positions, candidate_side=None):
        r = self.evaluate(candidate_symbol, returns, positions, candidate_side)
        if r["blocked"]:
            return True, r["symbol"], r["corr"]
        return False, "", 0.0
