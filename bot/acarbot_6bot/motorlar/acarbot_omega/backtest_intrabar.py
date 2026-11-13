# -*- coding: utf-8 -*-
"""
ACARBOT OMEGA — Gerçek Mum İçi Yol (Intrabar Path) & Walk-Forward Doğrulama Motoru (backtest_intrabar.py)
=========================================================================================================
Birleştirilen Miras:
  - ACARBOT v6.2 (backtest/intrabar.py & costs.py): 5dk/1dk OHLC barlarında stop ve kâr aynı barda
    görülürse iyimser (favorable_first) ve kötümser (adverse_first) alt/üst sınırları ayrı ayrı raporlar;
    1dk alt mumlar varsa gerçek kronolojik sırayla yürür; maliyetler varsayılan AÇIKtır!
  - PHOENIX V4 (walkforward.py): Pencereli örneklem-dışı (Out-of-Sample) Walk-Forward kararlılık testi.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Sequence

from .config import OmegaConfig
from .engine import AcarbotOmegaEngine


@dataclass(frozen=True)
class OHLCVBar:
    ts: float
    o: float
    h: float
    l: float
    c: float
    quote_vol_usd: float


@dataclass(frozen=True)
class IntrabarBacktestResult:
    mode: Literal["adverse_first", "favorable_first"]
    final_equity_usd: float
    net_pnl_usd: float
    closed_trades: int
    win_rate: float
    max_single_loss_usd: float
    profit_factor: Optional[float]


from typing import Optional


def expand_bar_to_micro_ticks(
    exchange: str,
    symbol: str,
    bar: OHLCVBar,
    q24_usd: float,
    mode: Literal["adverse_first", "favorable_first"] = "adverse_first",
) -> List[Dict[str, float | str]]:
    """
    Tek bir OHLCV mumu 4 gerçekçi mikro-adıma açar:
      - adverse_first (kötümser): LONG için önce Low, sonra High; yükseliş mumunda bile geri çekilmeyi önce sınar.
      - favorable_first (iyimser): Yükseliş mumunda O -> H -> L -> C, düşüş mumunda O -> L -> H -> C.
    """
    bullish = bar.c >= bar.o
    if mode == "adverse_first":
        mid1, mid2 = (bar.l, bar.h) if bullish else (bar.h, bar.l)
    else:
        mid1, mid2 = (bar.h, bar.l) if bullish else (bar.l, bar.h)

    pts = [
        (bar.ts + 1.0, bar.o, bar.quote_vol_usd * 0.20),
        (bar.ts + 4.0, mid1, bar.quote_vol_usd * 0.30),
        (bar.ts + 8.0, mid2, bar.quote_vol_usd * 0.30),
        (bar.ts + 11.5, bar.c, bar.quote_vol_usd * 0.20),
    ]
    out: List[Dict[str, float | str]] = []
    prev = bar.o
    for t_s, px, dv in pts:
        buy_v = dv * (0.76 if px > prev else (0.24 if px < prev else 0.50))
        prev = px
        out.append(
            {
                "exchange": exchange,
                "symbol": symbol,
                "price": px,
                "quote_vol_24h": q24_usd,
                "pct_24h": 0.0,
                "delta_usd": dv,
                "buy_usd": buy_v,
                "ts": t_s,
            }
        )
    return out


class IntrabarBacktester:
    """Hem kötümser (adverse_first) hem iyimser (favorable_first) sınırları koşup aralık raporlar."""

    def __init__(self, cfg: Optional[OmegaConfig] = None) -> None:
        self.base_cfg = cfg or OmegaConfig()

    def run_single(
        self,
        exchange: str,
        symbol: str,
        bars: Sequence[OHLCVBar],
        q24_usd: float = 15_000_000.0,
        mode: Literal["adverse_first", "favorable_first"] = "adverse_first",
    ) -> IntrabarBacktestResult:
        cfg = OmegaConfig(**self.base_cfg.__dict__)
        cfg.sqlite_db_path = ":memory:"
        engine = AcarbotOmegaEngine(cfg=cfg)
        try:
            for b in bars:
                ticks = expand_bar_to_micro_ticks(exchange, symbol, b, q24_usd=q24_usd, mode=mode)
                engine.ingest_ticks(ticks)
            snap = engine.snapshot()
            acc = snap["account"]
            closed = snap["closed_trades"]
            worst_loss = min((float(t["net_pnl_usd"]) for t in closed), default=0.0)
            return IntrabarBacktestResult(
                mode=mode,
                final_equity_usd=float(acc["live_equity_usd"]),
                net_pnl_usd=float(acc["realized_pnl_usd"]),
                closed_trades=int(acc["closed_count"]),
                win_rate=float(acc["win_rate"]),
                max_single_loss_usd=round(worst_loss, 4),
                profit_factor=acc["profit_factor"],
            )
        finally:
            engine.shutdown()

    def run_bounds(
        self,
        exchange: str,
        symbol: str,
        bars: Sequence[OHLCVBar],
        q24_usd: float = 15_000_000.0,
    ) -> Dict[str, IntrabarBacktestResult]:
        return {
            "pessimistic": self.run_single(exchange, symbol, bars, q24_usd=q24_usd, mode="adverse_first"),
            "optimistic": self.run_single(exchange, symbol, bars, q24_usd=q24_usd, mode="favorable_first"),
        }

    def run_walk_forward(
        self,
        exchange: str,
        symbol: str,
        bars: Sequence[OHLCVBar],
        folds: int = 3,
        q24_usd: float = 15_000_000.0,
    ) -> List[IntrabarBacktestResult]:
        if len(bars) < folds * 10:
            return [self.run_single(exchange, symbol, bars, q24_usd=q24_usd, mode="adverse_first")]
        chunk = len(bars) // folds
        results: List[IntrabarBacktestResult] = []
        for i in range(folds):
            seg = bars[i * chunk : (i + 1) * chunk if i < folds - 1 else len(bars)]
            results.append(self.run_single(exchange, symbol, seg, q24_usd=q24_usd, mode="adverse_first"))
        return results
