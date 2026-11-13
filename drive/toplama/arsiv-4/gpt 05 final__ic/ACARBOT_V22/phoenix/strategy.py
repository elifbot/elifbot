from .config import Config
from .models import Snapshot, Signal
from .risk import RiskManager


class Strategy:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.risk = RiskManager(cfg)

    def evaluate_details(self, s: Snapshot):
        if not s.market.active:
            return None, "inactive_market", None
        if s.stale_book:
            return None, "stale_book", None
        if s.quote_volume_24h < self.cfg.min_quote_volume_usd:
            return None, "low_volume", None
        if s.spread_bps > self.cfg.max_spread_bps:
            return None, "wide_spread", None
        if not s.oi_available:
            return None, "oi_unavailable", None
        if not s.funding_available:
            return None, "funding_unavailable", None

        trend = max(-1, min(1, float(s.regime_score)))
        htf = max(-1, min(1, float(s.htf_score)))
        book = max(-1, min(1, float(s.book_imbalance)))
        # OI change is already signed. Do not erase its direction with abs().
        oi_direction = max(-1, min(1, float(s.oi_change)))
        funding = max(-1, min(1, -float(s.funding) / self.cfg.funding_scale if self.cfg.funding_scale else 0))
        w = self.cfg.strategy_weights
        parts = [
            (w.get("trend", 0), trend),
            (w.get("htf", 0), htf),
            (w.get("oi", 0), oi_direction),
            (w.get("book", 0), book),
            (w.get("funding", 0), funding),
        ]
        if s.liquidation_available:
            parts.append((w.get("liquidation", 0), max(-1, min(1, float(s.liquidation_pressure)))))
        weight_total = sum(weight for weight, _ in parts)
        score = sum(weight * value for weight, value in parts) / weight_total if weight_total else 0.0
        # Alignment: higher-timeframe and 15m trend must agree in sign and clear a floor.
        # Always computed (shadow-counted by the runner); only enforced if cfg.require_alignment.
        floor = self.cfg.alignment_min
        aligned = (trend * htf > 0) and abs(trend) >= floor and abs(htf) >= floor
        details = {
            "aligned": aligned, "trend": trend, "htf": htf, "oi": oi_direction, "book": book,
            "funding": funding, "liquidation": float(s.liquidation_pressure) if s.liquidation_available else None,
            "weight_total": weight_total, "score": score,
        }
        if abs(score) < self.cfg.min_score:
            return None, "below_min_score", details
        if self.cfg.require_alignment and not aligned:
            return None, "alignment_failed", details
        side = "LONG" if score > 0 else "SHORT"
        entry = s.ask if side == "LONG" else s.bid
        notional = self.risk.target_notional()
        if entry <= 0:
            return None, "invalid_entry", details
        contract_size = max(float(s.market.contract_size or 0.0), 0.0)
        qty = notional / (entry * contract_size) if contract_size > 0 else notional / entry
        entry_fee = self.risk.estimated_entry_fee(notional)
        # Protective stop follows the per-position USD loss budget. Take-profit
        # remains volatility/ATR based and is deliberately independent of that stop.
        stop = self.risk.stop_price(entry, side, qty, contract_size, entry_fee)
        stop_dist = abs(entry - stop)
        atr_pct = float(getattr(s, "atr_pct", 0.0) or 0.0)
        target_dist = entry * atr_pct * self.cfg.atr_stop_multiplier * self.cfg.tp_r if atr_pct > 0 else stop_dist * self.cfg.tp_r
        target = entry + target_dist if side == "LONG" else entry - target_dist
        sig = Signal(s.market.exchange, s.market.symbol, side, abs(score), entry, stop, target, notional,
                     self.risk.required_margin(notional), s.ts, qty,
                     [f'trend={trend:.2f}', f'htf={htf:.2f}', f'oi={oi_direction:.2f}',
                      f'book={book:.2f}', f'fund={s.funding:.6f}',
                      f'liq={s.liquidation_pressure:.2f}' if s.liquidation_available else 'liq=NA'],
                     contract_size, s.atr_pct)
        return sig, "signal", details

    def evaluate(self, s: Snapshot):
        sig, _, _ = self.evaluate_details(s)
        return sig
