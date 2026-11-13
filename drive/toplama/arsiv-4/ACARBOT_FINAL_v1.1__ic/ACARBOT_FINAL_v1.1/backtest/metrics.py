"""Backtest metrik paketi (Y1-D, Y2-6).

Raporlanan ölçümler:
  Net PnL, işlem sayısı, kazanma oranı, Profit Factor, Max Drawdown
  (USDT + %), Sharpe, ortalama kazanç/kayıp, beklenen değer (USDT + R),
  ardışık kayıp sayısı, ücret/kayma/funding ayrıştırması, motor/sembol/
  yön kırılımı.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from statistics import mean, stdev


@dataclass
class MetricBlock:
    net_pnl: float = 0.0
    trade_count: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_usdt: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_per_trade: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy_usdt: float = 0.0
    expectancy_r: float = 0.0
    max_consecutive_losses: int = 0
    total_fees: float = 0.0
    total_funding: float = 0.0
    total_slippage: float = 0.0
    avg_r_multiple: float = 0.0
    by_engine: dict[str, dict] = field(default_factory=dict)
    by_symbol: dict[str, dict] = field(default_factory=dict)
    by_side: dict[str, dict] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "net_pnl": round(self.net_pnl, 4),
            "trade_count": self.trade_count,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "max_drawdown_usdt": round(self.max_drawdown_usdt, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "sharpe_per_trade": round(self.sharpe_per_trade, 4),
            "avg_win": round(self.avg_win, 4),
            "avg_loss": round(self.avg_loss, 4),
            "expectancy_usdt": round(self.expectancy_usdt, 4),
            "expectancy_r": round(self.expectancy_r, 4),
            "max_consecutive_losses": self.max_consecutive_losses,
            "total_fees": round(self.total_fees, 4),
            "total_funding": round(self.total_funding, 4),
            "total_slippage": round(self.total_slippage, 4),
            "avg_r_multiple": round(self.avg_r_multiple, 4),
            "by_engine": self.by_engine,
            "by_symbol": self.by_symbol,
            "by_side": self.by_side,
        }


def _group_stats(closes: list[dict]) -> dict:
    pnls = [float(t.get("pnl", 0.0)) for t in closes]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    rs = [
        float(t.get("r_multiple", 0.0)) for t in closes
        if isinstance(t.get("r_multiple"), (int, float))
    ]
    return {
        "trades": len(closes),
        "net_pnl": round(sum(pnls), 4),
        "win_rate": round(len(wins) / len(closes), 4) if closes else 0.0,
        "profit_factor": (
            round(gross_win / gross_loss, 4) if gross_loss > 0
            else float("inf") if gross_win > 0 else 0.0
        ),
        "avg_r": round(mean(rs), 4) if rs else 0.0,
    }


def compute_metrics(
    trades: list[dict],
    initial_balance: float,
    final_balance: float | None = None,
    equity_curve: list[float] | None = None,
) -> MetricBlock:
    """Kapanış kayıtlarından tüm metrikleri hesaplar.

    Beklenti: işlem başı ortalama net PnL. Sharpe: işlem getirilerinin
    (PnL / başlangıç bakiyesi) ortalamasının standart sapmaya oranı —
    yıllıklandırma yok, karşılaştırma için ham bilgi oranı.
    Max DD: equity eğrisi yoksa işlem sırasına göre kümülatif PnL'den.
    """
    closes = [t for t in trades if t.get("type") == "CLOSE"]
    block = MetricBlock()
    if final_balance is None:
        final_balance = initial_balance + sum(
            float(t.get("pnl", 0.0)) for t in closes
        )
    block.net_pnl = final_balance - initial_balance
    block.trade_count = len(closes)
    if not closes:
        return block

    pnls = [float(t.get("pnl", 0.0)) for t in closes]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    block.win_rate = len(wins) / len(closes)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        block.profit_factor = gross_win / gross_loss
    elif gross_win > 0:
        block.profit_factor = float("inf")
    block.avg_win = mean(wins) if wins else 0.0
    block.avg_loss = mean(losses) if losses else 0.0
    block.expectancy_usdt = mean(pnls)

    r_values = [
        float(t["r_multiple"]) for t in closes
        if isinstance(t.get("r_multiple"), (int, float))
        and t.get("r_multiple") is not None
    ]
    if r_values:
        block.expectancy_r = mean(r_values)
        block.avg_r_multiple = mean(r_values)

    # Sharpe (işlem başı bilgi oranı)
    base = max(initial_balance, 1e-9)
    returns = [p / base for p in pnls]
    if len(returns) > 1 and stdev(returns) > 0:
        block.sharpe_per_trade = mean(returns) / stdev(returns)

    # Ardışık kayıp
    streak = 0
    worst_streak = 0
    for p in pnls:
        if p <= 0:
            streak += 1
            worst_streak = max(worst_streak, streak)
        else:
            streak = 0
    block.max_consecutive_losses = worst_streak

    # Maliyet ayrıştırması
    block.total_fees = sum(
        float(t.get("entry_fee", 0.0)) + float(t.get("fee", 0.0))
        for t in closes
    )
    block.total_funding = sum(
        float(t.get("funding_paid", 0.0)) for t in closes
    )
    block.total_slippage = sum(
        float(t.get("slippage", 0.0)) for t in closes
    )

    # Max Drawdown
    curve = equity_curve
    if not curve:
        curve = [initial_balance]
        running = initial_balance
        for p in pnls:
            running += p
            curve.append(running)
    peak = curve[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    for value in curve:
        peak = max(peak, value)
        dd = peak - value
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / peak * 100.0) if peak > 0 else 0.0
    block.max_drawdown_usdt = max_dd
    block.max_drawdown_pct = max_dd_pct

    # Kırılımlar
    for key, attr in (("motor", "by_engine"), ("symbol", "by_symbol"),
                      ("side", "by_side")):
        groups: dict[str, list[dict]] = {}
        for t in closes:
            groups.setdefault(str(t.get(key, "?")), []).append(t)
        setattr(block, attr, {k: _group_stats(v) for k, v in groups.items()})
    return block


def format_metrics_report(block: MetricBlock, title: str = "BACKTEST") -> str:
    """Telegram/terminal için okunur rapor."""
    lines = [
        f"== {title} ==",
        f"Net PnL: {block.net_pnl:+.2f} USDT",
        f"İşlem: {block.trade_count} | Kazanma: %{block.win_rate*100:.1f}",
        f"Profit Factor: {block.profit_factor:.2f} | Sharpe: {block.sharpe_per_trade:.2f}",
        f"Max DD: {block.max_drawdown_usdt:.2f} USDT (%{block.max_drawdown_pct:.1f})",
        f"Beklenen değer: {block.expectancy_usdt:+.3f} USDT ({block.expectancy_r:+.2f}R)",
        f"Ort. kazanç/kayıp: {block.avg_win:+.2f} / {block.avg_loss:+.2f}",
        f"Ardışık kayıp: {block.max_consecutive_losses}",
        f"Ücret: {block.total_fees:.2f} | Funding: {block.total_funding:.2f} | Kayma: {block.total_slippage:.2f}",
    ]
    if block.by_engine:
        lines.append("-- Motorlar --")
        for engine, stats in block.by_engine.items():
            lines.append(
                f"{engine}: {stats['trades']} işlem, "
                f"net {stats['net_pnl']:+.2f}, PF {stats['profit_factor']}"
            )
    return "\n".join(lines)
