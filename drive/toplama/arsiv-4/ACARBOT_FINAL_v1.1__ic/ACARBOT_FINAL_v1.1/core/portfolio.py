"""Paper hesap görünümü — funding, likidasyon ve R takibi ile genişletildi.

Position artık şunları bilir:
  - gerçekleştirilen funding ödemeleri (Yorum 1 C),
  - izole teminat likidasyon fiyatı (Yorum 1 C),
  - TP1 kısmi kâr alma durumu (Yorum 2 #3),
  - giriş anındaki net risk birimi R (Yorum 2 #4: maliyet-dâhil risk).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

from core.config import FundingConfig


@dataclass
class Position:
    symbol: str
    side: str                                  # "LONG" | "SHORT"
    entry: float
    quantity: float                            # hâlen açık miktar (TP1 ile azalır)
    initial_quantity: float
    margin: float
    stop_loss: float
    opened_at_ms: int
    entry_fee: float = 0.0
    motor: str = "fade"                        # "fade" | "trend"
    leverage: float = 10.0
    liquidation_price: float = 0.0
    funding_paid: float = 0.0                  # pozitif = ödeme, negatif = tahsilat
    take_profit: float | None = None           # TP1 seviyesi
    tp1_done: bool = False
    tp1_realized_pnl: float = 0.0              # TP1 kapatmasının net sonucu
    trailing_active: bool = False
    best_price: float | None = None
    initial_net_risk: float = 0.0              # R birimi (maliyetler dâhil)
    bars_held: int = 0
    last_candle_timestamp: int = 0
    funding_events: list[float] = field(default_factory=list)

    @property
    def direction(self) -> float:
        return 1.0 if self.side == "LONG" else -1.0

    def unrealized_pnl(self, mark_price: float) -> float:
        """Brüt gerçekleşmemiş kâr/zarar (ücretsiz)."""
        if not isfinite(mark_price) or mark_price <= 0:
            raise ValueError("mark fiyatı pozitif ve sonlu olmalı")
        return self.direction * (mark_price - self.entry) * self.quantity

    def estimated_exit_cost(self, mark_price: float, taker_fee: float,
                            slippage_rate: float) -> float:
        """Marktan çıkış için beklenen ücret + kayma (maliyet-dâhil zarar kontrolü)."""
        exit_price = (
            mark_price * (1.0 - slippage_rate)
            if self.side == "LONG"
            else mark_price * (1.0 + slippage_rate)
        )
        fee = exit_price * self.quantity * taker_fee
        slippage_cost = abs(exit_price - mark_price) * self.quantity
        return fee + slippage_cost

    def net_pnl(self, mark_price: float, taker_fee: float,
                slippage_rate: float) -> float:
        """TP1 kısmi sonucu, funding ve çıkış maliyetleri dâhil net PnL."""
        gross = self.unrealized_pnl(mark_price)
        exit_cost = self.estimated_exit_cost(mark_price, taker_fee, slippage_rate)
        return gross + self.tp1_realized_pnl - self.entry_fee - exit_cost - self.funding_paid

    def margin_used_fraction(self, mark_price: float) -> float:
        """Teminatın ne kadarının zararla tüketildiği (likidasyon uyarısı için)."""
        loss = max(0.0, -self.unrealized_pnl(mark_price))
        if self.margin <= 0:
            return 0.0
        return loss / self.margin


def compute_liquidation_price(
    entry: float,
    side: str,
    leverage: float,
    config: FundingConfig,
) -> float:
    """İzole teminat yaklaşık likidasyon fiyatı.

    LONG:  liq = entry * (1 - 1/lev + mmr + liq_fee)
    SHORT: liq = entry * (1 + 1/lev - mmr - liq_fee)

    10x kaldıraçta LONG için ≈ %9,7 ters yönlü hareket. Stop genelde çok
    önce tetiklenir ama model YİNE DE likidasyonu hesaplar ve izler
    (Yorum 1 C: "likidasyon fiyatı modellenmiyor" eleştirisi).
    """
    if entry <= 0 or leverage <= 0:
        raise ValueError("entry ve leverage pozitif olmalı")
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side LONG veya SHORT olmalı")
    one_over_lev = 1.0 / leverage
    buffer = config.maintenance_margin_rate + config.liquidation_fee_rate
    if side == "LONG":
        fraction = max(1.0 - one_over_lev + buffer, 1e-6)
        return entry * fraction
    fraction = min(1.0 + one_over_lev - buffer, 2.0 - 1e-6)
    return entry * fraction


def compute_funding_payment(
    notional_mark: float,
    funding_rate: float,
    side: str,
) -> float:
    """Funding ödemesi (pozitif = pozisyon sahibi öder).

    Binance kuralı: rate > 0 iken LONG öder, SHORT tahsil eder; tersi rate < 0.
    """
    if not isfinite(notional_mark) or notional_mark < 0:
        raise ValueError("nominal sonlu ve negatif olmalı")
    if not isfinite(funding_rate):
        raise ValueError("funding oranı sonlu olmalı")
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side LONG veya SHORT olmalı")
    sign = 1.0 if side == "LONG" else -1.0
    return notional_mark * funding_rate * sign


def next_funding_timestamp_ms(now_ms: int, interval_hours: float = 8.0) -> int:
    """Bir sonraki funding zamanını (UTC 00:00/08:00/16:00) ms cinsinden verir."""
    interval_ms = int(interval_hours * 3_600_000)
    if interval_ms <= 0:
        raise ValueError("funding aralığı pozitif olmalı")
    return ((now_ms // interval_ms) + 1) * interval_ms


class Portfolio:
    """Bakiye + açık pozisyonlar. Ücret ve funding nakit akışlarını taşır."""

    def __init__(self, initial_balance: float = 1_000.0) -> None:
        if not isfinite(initial_balance) or initial_balance <= 0:
            raise ValueError("başlangıç bakiyesi pozitif olmalı")
        self.initial_balance = float(initial_balance)
        self.balance = float(initial_balance)
        self.positions: dict[str, Position] = {}
        self.equity_peak: float = float(initial_balance)

    @property
    def used_margin(self) -> float:
        return sum(p.margin for p in self.positions.values())

    def free_balance(self) -> float:
        return self.balance - self.used_margin

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        total = 0.0
        for symbol, position in self.positions.items():
            price = prices.get(symbol, position.entry)
            total += position.unrealized_pnl(price)
        return total

    def equity(self, prices: dict[str, float] | None = None) -> float:
        value = self.balance + self.unrealized_pnl(prices or {})
        self.equity_peak = max(self.equity_peak, value)
        return value

    def drawdown_pct(self, prices: dict[str, float] | None = None) -> float:
        peak = self.equity_peak
        if peak <= 0:
            return 0.0
        current = self.equity(prices)
        return max(0.0, (peak - current) / peak * 100.0)

    def total_open_net_risk(self) -> float:
        return sum(p.initial_net_risk for p in self.positions.values())

    def total_notional(self, prices: dict[str, float] | None = None) -> float:
        prices = prices or {}
        return sum(
            p.quantity * prices.get(symbol, p.entry)
            for symbol, p in self.positions.items()
        )

    def directional_notional(self, prices: dict[str, float] | None = None) -> float:
        prices = prices or {}
        long_n = short_n = 0.0
        for symbol, p in self.positions.items():
            notional = p.quantity * prices.get(symbol, p.entry)
            if p.side == "LONG":
                long_n += notional
            else:
                short_n += notional
        return long_n - short_n

    def positions_in_group(self, group_of, group: str) -> int:
        return sum(
            1 for symbol in self.positions
            if group_of(symbol) == group
        )
