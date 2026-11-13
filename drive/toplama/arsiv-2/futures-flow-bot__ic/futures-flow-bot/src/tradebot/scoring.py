"""Giris ve cikis puanlama. Esikler config'ten gelir; veriyle ayarlanmalidir."""
from __future__ import annotations

from .config import EntryCfg, ExitCfg, ScannerCfg
from .features import Features
from .models import Side


def score_entry(f: Features, e: EntryCfg, sc: ScannerCfg) -> tuple[Side, int, list[str]] | None:
    """5 kriter: delta*, hacim*, fiyat degisimi, MACD ivmesi, RSI bolgesi (*zorunlu)."""
    if f.flow_usd < sc.min_flow_usd:
        return None
    best = None
    for side in (Side.LONG, Side.SHORT):
        s = side.sign
        if not (s * f.delta_ratio >= e.delta_min and f.vol_ratio >= e.vol_ratio_min):
            continue
        hits = [f"delta {f.delta_ratio:+.2f}", f"hacim x{f.vol_ratio:.1f}"]
        if s * f.change_pct >= e.change_min_pct:
            hits.append(f"fiyat {f.change_pct:+.2f}%/60s")
        if s * f.macd_hist > 0 and s * (f.macd_hist - f.macd_hist_prev) > 0:
            hits.append("MACD ivme")
        lo, hi = ((e.rsi_long_min, e.rsi_long_max) if side is Side.LONG
                  else (e.rsi_short_min, e.rsi_short_max))
        if lo <= f.rsi <= hi:
            hits.append(f"RSI {f.rsi:.0f}")
        if len(hits) >= e.threshold and (best is None or len(hits) > best[1]):
            best = (side, len(hits), hits)
    return best


def score_exit(side: Side, f: Features, x: ExitCfg) -> tuple[int, list[str]]:
    """Para girisi durdu mu? 5 kriter."""
    s = side.sign
    hits = []
    if s * f.delta_ratio <= x.delta_flip:
        hits.append(f"akis durdu/dondu (delta {f.delta_ratio:+.2f})")
    if f.vol_ratio < x.vol_ratio_fade:
        hits.append(f"hacim soldu (x{f.vol_ratio:.1f})")
    if side is Side.LONG and f.rsi_prev >= x.rsi_overbought and f.rsi < f.rsi_prev:
        hits.append("RSI asiri alimdan dondu")
    if side is Side.SHORT and f.rsi_prev <= x.rsi_oversold and f.rsi > f.rsi_prev:
        hits.append("RSI asiri satimdan dondu")
    if s * (f.macd_hist - f.macd_hist_prev) < 0:
        hits.append("MACD zayifliyor")
    if s * f.change_pct <= -x.adverse_change_pct:
        hits.append(f"fiyat ters yone ({f.change_pct:+.2f}%)")
    return len(hits), hits
