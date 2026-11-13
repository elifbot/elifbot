"""Executor ve Shadow Lab tarafından paylaşılan saf çıkış kuralları."""
from __future__ import annotations


def trailing_floor(risk, pos) -> float:
    """Aktif modda gerçek net başabaş, aksi halde eski brüt giriş tabanı."""
    if getattr(pos, "net_breakeven_enabled", False):
        return float(risk.net_breakeven_price(pos))
    return float(pos.entry)


def apply_supertrend_trailing(pos, price: float, info: dict | None, risk) -> bool:
    """Supertrend stopunu yalnız kâr ve geçerli başabaş tabanı yönünde sıkılaştır."""
    if not info or risk.profit_pct(pos, price) <= 0:
        return False
    direction = 1 if pos.side == "LONG" else -1
    try:
        trend_direction = int(info.get("direction", 0))
        value = float(info.get("value", 0.0))
    except (TypeError, ValueError, AttributeError):
        return False
    if trend_direction != direction or value <= 0:
        return False
    old_stop = float(pos.stop)
    floor = trailing_floor(risk, pos)
    if pos.side == "LONG":
        candidate = max(old_stop, value)
        if candidate < floor:
            return False
        pos.stop = candidate
    else:
        candidate = min(old_stop, value)
        if candidate > floor:
            return False
        pos.stop = candidate
    return pos.stop != old_stop


def runner_exit_reason(pos, price: float, pnl_pct: float, snap: dict, cfg: dict) -> str | None:
    """Kâr koşusunda LONG satış / SHORT alış baskısı çıkışını doğrula."""
    if not cfg.get("kosan_kar", False) or price <= 0:
        return None
    min_profit = float(cfg.get("orderflow_min_kar_yuzde", 0.5))
    if pnl_pct < min_profit:
        return None
    peak = float(pos.peak or pos.entry)
    if peak <= 0:
        return None
    direction = 1.0 if pos.side == "LONG" else -1.0
    pullback_pct = (
        (peak - price) / peak * 100.0
        if pos.side == "LONG"
        else (price - peak) / peak * 100.0
    )
    min_pullback = float(cfg.get("orderflow_min_geri_cekilme_yuzde", 0.05))
    if pullback_pct < min_pullback:
        return None

    def number(key: str, default: float = 0.0) -> float:
        try:
            return float(snap.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    buy = number("absorption_buy_usdt", number("buy_usdt"))
    sell = number("absorption_sell_usdt", number("sell_usdt"))
    cvd = number("cvd_60s", number("cvd_slope"))
    aggressive = sell if pos.side == "LONG" else buy
    other = buy if pos.side == "LONG" else sell
    ratio = float(cfg.get("orderflow_orani", 1.5))
    min_usdt = float(cfg.get("orderflow_min_usdt", 1000.0))
    pressure = aggressive >= min_usdt and aggressive >= other * ratio
    pressure_name = "SATIŞ" if pos.side == "LONG" else "ALIŞ"
    absorption = str(snap.get("absorption", "YOK")).upper()
    pressure_absorbed = "SATIS_EMILIMI" if pos.side == "LONG" else "ALIS_EMILIMI"
    if absorption == pressure_absorbed:
        return None

    divergence = str(snap.get("cvd_divergence", "YOK")).upper()
    expected_divergence = "BEARISH" if pos.side == "LONG" else "BULLISH"
    if pressure and cvd * direction < 0:
        suffix = (
            f" + {expected_divergence} divergence"
            if divergence == expected_divergence
            else ""
        )
        return (
            f"{pos.side} {pressure_name} BASKISI + CVD dönüşü{suffix} "
            f"(${aggressive:,.0f}, zirve/dip %{pullback_pct:.2f})"
        )
    return None
