import math


class PortfolioRisk:
    def __init__(self, correlation_limit=.85, correlation_window=96):
        self.limit = correlation_limit
        self.window = correlation_window

    @staticmethod
    def _keys(symbol):
        s = str(symbol).upper()
        return (s, s.split(":", 1)[0], s.split("/", 1)[0])

    def _series(self, returns, symbol):
        for key in self._keys(symbol):
            if key in returns and returns[key]:
                return list(returns[key])[-self.window:]
        return None

    def correlated(self, candidate_symbol, returns, positions):
        candidate = self._series(returns, candidate_symbol)
        if not candidate or len(candidate) < 3:
            return False, '', 0.0
        for p in positions:
            if self._keys(p.symbol)[0] == self._keys(candidate_symbol)[0]:
                continue
            other = self._series(returns, p.symbol)
            if not other:
                continue
            n = min(len(candidate), len(other), self.window)
            a, b = candidate[-n:], other[-n:]
            if len(a) < 3:
                continue
            ma, mb = sum(a)/len(a), sum(b)/len(b)
            va = sum((x-ma)**2 for x in a); vb = sum((y-mb)**2 for y in b)
            if va == 0 or vb == 0:
                continue
            c = sum((x-ma)*(y-mb) for x,y in zip(a,b)) / math.sqrt(va*vb)
            if abs(c) >= self.limit:
                return True, p.symbol, c
        return False, '', 0.0
