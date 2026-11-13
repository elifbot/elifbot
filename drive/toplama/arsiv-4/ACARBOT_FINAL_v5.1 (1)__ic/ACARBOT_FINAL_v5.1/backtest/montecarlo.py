"""ACARBOT v2.0 — Monte Carlo simülasyonu (şartname madde 7).

"Botun yalnızca iyi bir geçmiş dönem yakalayıp yakalamadığını anlamamızı
sağlar": kapanan işlemlerin PnL dizisi bootstrap ile yeniden örneklenir;
binlerce alternatif gelecek için nihai PnL, MaxDD ve kayıp olasılığı
dağılımı üretilir.

Yöntem:
  - iid bootstrap (varsayılan): işlemler bağımsız örneklenir.
  - blok bootstrap (block_size > 1): ardışık işlem bağımlılığını korur
    (trend takip sistemlerinde ardışıklık gerçekçidir).
Çıktı: yüzde bileşenleri (p5/p25/p50/p75/p95), kayıp olasılığı,
ruin olasılığı (final <= ruin_threshold), MaxDD dağılımı.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class MonteCarloResult:
    simulations: int
    final_pnl_p5: float
    final_pnl_p25: float
    final_pnl_p50: float
    final_pnl_p75: float
    final_pnl_p95: float
    max_dd_p50_pct: float
    max_dd_p95_pct: float
    prob_loss: float                 # final < 0 olasılığı
    prob_ruin: float                 # final <= ruin_threshold olasılığı
    trade_count: int

    def as_dict(self) -> dict:
        return {
            "simulations": self.simulations,
            "final_pnl_p5": round(self.final_pnl_p5, 4),
            "final_pnl_p25": round(self.final_pnl_p25, 4),
            "final_pnl_p50": round(self.final_pnl_p50, 4),
            "final_pnl_p75": round(self.final_pnl_p75, 4),
            "final_pnl_p95": round(self.final_pnl_p95, 4),
            "max_dd_p50_pct": round(self.max_dd_p50_pct, 3),
            "max_dd_p95_pct": round(self.max_dd_p95_pct, 3),
            "prob_loss": round(self.prob_loss, 4),
            "prob_ruin": round(self.prob_ruin, 4),
            "trade_count": self.trade_count,
        }

    def summary_text(self) -> str:
        return (
            f"MONTE CARLO ({self.simulations} simülasyon, {self.trade_count} işlem)\n"
            f"Final PnL p5/p50/p95: {self.final_pnl_p5:+.2f} / "
            f"{self.final_pnl_p50:+.2f} / {self.final_pnl_p95:+.2f} USDT\n"
            f"MaxDD p50/p95: %{self.max_dd_p50_pct:.1f} / %{self.max_dd_p95_pct:.1f}\n"
            f"Zarar olasılığı: %{self.prob_loss*100:.1f} | "
            f"Ruin olasılığı: %{self.prob_ruin*100:.1f}"
        )


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, int(round(p * (len(sorted_values) - 1)))))
    return sorted_values[index]


def monte_carlo(
    trade_pnls: list[float],
    initial_balance: float = 1_000.0,
    simulations: int = 2_000,
    block_size: int = 1,
    ruin_drawdown_pct: float = 15.0,
    seed: int = 42,
) -> MonteCarloResult:
    """Kapanan işlem PnL'lerinden Monte Carlo dağılımı üretir.

    ruin_drawdown_pct: başlangıç bakiyesine göre kayıp eşiği (varsayılan
    v2.0 equity eşiği ile tutarlı: -%15).
    """
    if simulations < 1:
        raise ValueError("simülasyon sayısı >= 1 olmalı")
    if block_size < 1:
        raise ValueError("blok boyutu >= 1 olmalı")
    if not trade_pnls:
        return MonteCarloResult(
            simulations=0, final_pnl_p5=0.0, final_pnl_p25=0.0,
            final_pnl_p50=0.0, final_pnl_p75=0.0, final_pnl_p95=0.0,
            max_dd_p50_pct=0.0, max_dd_p95_pct=0.0,
            prob_loss=0.0, prob_ruin=0.0, trade_count=0,
        )
    rng = random.Random(seed)
    ruin_threshold = -abs(initial_balance) * ruin_drawdown_pct / 100.0
    finals: list[float] = []
    max_dds: list[float] = []
    losses = 0
    ruins = 0
    n = len(trade_pnls)
    for _ in range(simulations):
        equity = initial_balance
        peak = initial_balance
        max_dd = 0.0
        i = 0
        while i < n:
            if block_size == 1:
                chunk = [trade_pnls[rng.randrange(n)]]
            else:
                start = rng.randrange(n)
                chunk = [trade_pnls[(start + k) % n] for k in range(block_size)]
            for pnl in chunk:
                equity += pnl
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)
            i += len(chunk)
        final = equity - initial_balance
        finals.append(final)
        max_dds.append(max_dd / peak * 100.0 if peak > 0 else 0.0)
        if final < 0:
            losses += 1
        if equity <= initial_balance + ruin_threshold:
            ruins += 1
    finals.sort()
    max_dds.sort()
    return MonteCarloResult(
        simulations=simulations,
        final_pnl_p5=_percentile(finals, 0.05),
        final_pnl_p25=_percentile(finals, 0.25),
        final_pnl_p50=_percentile(finals, 0.50),
        final_pnl_p75=_percentile(finals, 0.75),
        final_pnl_p95=_percentile(finals, 0.95),
        max_dd_p50_pct=_percentile(max_dds, 0.50),
        max_dd_p95_pct=_percentile(max_dds, 0.95),
        prob_loss=losses / simulations,
        prob_ruin=ruins / simulations,
        trade_count=n,
    )
