"""Pre-order sizing: precision, exchange minimums and automatic bump-or-skip.

The same function runs in PAPER and LIVE so a paper "SIZING" rejection predicts exactly
what the live executor would have refused (min amount / min notional / zero after rounding).
"""
from __future__ import annotations
import math
from dataclasses import replace, dataclass
from .models import Signal


@dataclass(frozen=True)
class MarketMeta:
    min_amount: float = 0.0
    min_cost: float = 0.0
    amount_step: float = 0.0
    price_tick: float = 0.0
    contract_size: float = 1.0


def meta_from_dict(d) -> MarketMeta:
    d = d or {}
    return MarketMeta(float(d.get("min_amount") or 0), float(d.get("min_cost") or 0),
                      float(d.get("amount_step") or 0), float(d.get("price_tick") or 0),
                      float(d.get("contract_size") or 1.0))


def _round_down(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step + 1e-9) * step


def _round_up(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.ceil(x / step - 1e-9) * step


def _clean(x: float, step: float) -> float:
    """Remove float noise like 0.30000000000000004 relative to the step grid."""
    if step <= 0:
        return x
    decimals = max(0, min(12, int(round(-math.log10(step))) + 1)) if step < 1 else 6
    return round(x, decimals)


def fit_order(signal: Signal, meta: MarketMeta, risk, cfg):
    """Return (fitted_signal | None, reason, info).

    reason is 'ok', 'auto_bumped' or a rejection code:
    'zero_qty_after_rounding', 'below_min_amount', 'below_min_notional', 'invalid_stop'.
    The stop is recomputed whenever quantity changes so the dollar loss budget is preserved.
    """
    cs = meta.contract_size or signal.contract_size or 1.0
    price = signal.entry
    if price <= 0 or signal.qty <= 0:
        return None, "zero_qty_after_rounding", {"qty": signal.qty}
    step = meta.amount_step
    qty = _clean(_round_down(signal.qty, step), step)
    min_qty = max(meta.min_amount or 0.0, (meta.min_cost / (price * cs)) if meta.min_cost else 0.0)
    info = {"requested_qty": signal.qty, "rounded_qty": qty, "min_qty_needed": min_qty,
            "min_amount": meta.min_amount, "min_cost": meta.min_cost}
    bumped = False
    if qty <= 0 or (min_qty and qty + 1e-12 < min_qty):
        need = _clean(_round_up(max(min_qty, step), step), step)
        new_notional = need * price * cs
        factor = cfg.auto_bump_max_factor
        if factor > 0 and new_notional <= signal.notional * factor + 1e-9:
            qty, bumped = need, True
            info["bumped_to_qty"] = need
        else:
            if qty <= 0:
                reason = "zero_qty_after_rounding"
            elif meta.min_amount and qty + 1e-12 < meta.min_amount:
                reason = "below_min_amount"
            else:
                reason = "below_min_notional"
            info["needed_notional"] = new_notional
            return None, reason, info
    notional = qty * price * cs
    margin = notional / cfg.leverage
    entry_fee = risk.estimated_entry_fee(notional)
    # Always rebuild the protective stop from the final exchange-rounded quantity.
    # Never trust an upstream ATR stop: the configured per-position USD loss cap
    # is authoritative. Preserve the signal's reward multiple when possible.
    reward_distance = abs(float(signal.target or 0.0) - price)
    stop = risk.stop_price(price, signal.side, qty, cs, entry_fee)
    # Keep the strategy's ATR-based target distance independent from the
    # per-position hard-loss stop.
    target = price + reward_distance if signal.side == "LONG" else price - reward_distance
    if stop <= 0 or (signal.side == "LONG" and not stop < price) or (signal.side == "SHORT" and not stop > price):
        return None, "invalid_stop", info
    fitted = replace(signal, qty=qty, notional=notional, margin=margin, stop=stop, target=target,
                     contract_size=cs, reasons=list(signal.reasons) + (["auto_bumped"] if bumped else []))
    return fitted, ("auto_bumped" if bumped else "ok"), info
