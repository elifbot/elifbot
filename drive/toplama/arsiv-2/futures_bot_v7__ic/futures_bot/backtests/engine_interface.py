"""
Phase D — backtest motoru arayüzü.

Bu modül yalnızca ARAYÜZ tanımlar; gerçek bir backtest motoru bu teslimatta
YOKTUR. Uygulama, ayrı bir ajanda (backtest & istatistik) ele alınmalıdır.
Lookahead koruması sözleşme gereğidir: motor mumları TEK TEK beslemeli ve
stratejiye yalnızca geçmiş satırlar verilmelidir.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field

import pandas as pd


class LookaheadError(RuntimeError):
    """Motor, stratejiye gelecekteki veriyi sızdırdığında fırlatılır."""


@dataclass
class BacktestConfig:
    """Backtest yapılandırması (parametre dondurma bilgisi ile)."""

    timeframe: str = "1m"
    fee_rate: float = 0.0005
    starting_balance: float = 1_000.0
    leverage: float = 5.0
    params_frozen: bool = True
    frozen_at: str | None = None
    notes: list[str] = field(default_factory=list)


class BacktestEngine(abc.ABC):
    """
    Backtest motoru sözleşmesi.

    Uygulayıcılar:
      * feed(): her çağrıda TEK bir mum ekler,
      * step(): stratejiyi yalnızca o ana kadarki veriyle çalıştırır,
      * sonuçları reports/pnl_report ile aynı metriklerle üretir.
    """

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self._history: list[dict] = []

    @property
    def history(self) -> pd.DataFrame:
        return pd.DataFrame(self._history)

    def feed(self, candle: dict) -> None:
        """Yeni (kapanmış) mumu motora ekler."""
        required = ("open_time", "open", "high", "low", "close", "volume")
        missing = [c for c in required if c not in candle]
        if missing:
            raise ValueError(f"eksik mum alanı: {missing}")
        self._history.append(dict(candle))

    def _assert_no_lookahead(self, window: pd.DataFrame, decision_ts: int) -> None:
        """Karar anından sonraki hiçbir mum pencereye girmemeli."""
        if window.empty:
            return
        if int(window["open_time"].max()) > decision_ts:
            raise LookaheadError("pencereye gelecekteki mum sızdı")

    @abc.abstractmethod
    def step(self) -> None:
        """Tek bir mum üzerinde ilerler."""

    @abc.abstractmethod
    def results(self) -> dict:
        """Metrikleri sözlük olarak döndürür."""


class WalkForwardPlan:
    """
    Walk-forward doğrulama planı (uygulama Phase D'de yapılacak).

    Kural: her pencere için parametreler pencere BAŞLAMADAN dondurulur.
    """

    def __init__(self, train_bars: int, test_bars: int) -> None:
        if train_bars < 1 or test_bars < 1:
            raise ValueError("pencere boyutları pozitif olmalı")
        self.train_bars = int(train_bars)
        self.test_bars = int(test_bars)

    def windows(self, total_bars: int) -> list[tuple[int, int, int, int]]:
        """(train_start, train_end, test_start, test_end) listesi."""
        out: list[tuple[int, int, int, int]] = []
        start = 0
        while start + self.train_bars + self.test_bars <= total_bars:
            ts, te = start, start + self.train_bars
            ss, se = te, te + self.test_bars
            out.append((ts, te, ss, se))
            start += self.test_bars
        return out
