from .config import Config
from .models import Snapshot, Signal
from .risk import RiskManager


class Strategy:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.risk = RiskManager(cfg)

    def _components(self, s: Snapshot):
        """Weighted score and its components. No entry gates: also used to judge open positions.

        V22.6 signal-quality upgrades (architecture unchanged):
        * OI x price agreement: rising OI with rising price = new longs (+), rising OI with falling
          price = new shorts (-); falling OI means positions are CLOSING (weak signal -> magnitude
          halved, sign follows price). Without a price direction (price_chg_pct == 0) the raw signed
          OI change is used, exactly like V22.5.
        * Conflict penalty: when the 15m trend and the 1h/4h trend disagree in sign, the final score
          is multiplied by cfg.conflict_penalty (default 0.70) - chasing a countertrend move needs a
          much stronger reading.
        """
        trend = max(-1, min(1, float(s.regime_score)))
        htf = max(-1, min(1, float(s.htf_score)))
        book = max(-1, min(1, float(s.book_imbalance)))
        raw_oi = max(-1, min(1, float(s.oi_change)))
        if self.cfg.oi_price_agreement:
            direction = 0.0
            chg = float(getattr(s, "price_chg_pct", 0.0) or 0.0)
            if chg > 0:
                direction = 1.0
            elif chg < 0:
                direction = -1.0
            if raw_oi == 0 or direction == 0:
                oi_direction = raw_oi                      # no price context yet: legacy behaviour
            elif raw_oi > 0:
                oi_direction = raw_oi * direction          # open interest building WITH/AGAINST price
            else:
                oi_direction = -raw_oi * direction * 0.5   # OI unwinding: weak, follow price
        else:
            oi_direction = raw_oi
        oi_direction = max(-1, min(1, oi_direction))
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
        raw_score = sum(weight * value for weight, value in parts) / weight_total if weight_total else 0.0
        conflict = (trend * htf) < 0
        score = raw_score * self.cfg.conflict_penalty if (conflict and self.cfg.conflict_penalty < 1) else raw_score
        # Alignment: higher-timeframe and 15m trend must agree in sign and clear a floor.
        # Always computed (shadow-counted by the runner); only enforced if cfg.require_alignment.
        floor = self.cfg.alignment_min
        aligned = (trend * htf > 0) and abs(trend) >= floor and abs(htf) >= floor
        details = {
            "aligned": aligned, "conflict": conflict, "trend": trend, "htf": htf,
            "oi": oi_direction, "raw_oi": raw_oi, "book": book, "funding": funding,
            "liquidation": float(s.liquidation_pressure) if s.liquidation_available else None,
            "weight_total": weight_total, "score_raw": raw_score, "score": score,
        }
        return score, details

    def score_only(self, s: Snapshot):
        """Details (incl. signed score) without entry gates, for indicator exits of open positions."""
        return self._components(s)[1]

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

        score, details = self._components(s)
        if abs(score) < self.cfg.min_score:
            return None, "below_min_score", details
        if self.cfg.require_alignment and not details["aligned"]:
            return None, "alignment_failed", details
        side = "LONG" if score > 0 else "SHORT"
        # V22.6 RSI overextension gate: do not chase a move that is already exhausted.
        # Exits are unaffected (score_only never applies this).
        if self.cfg.rsi_gate and bool(getattr(s, "rsi_available", False)):
            rsi = float(getattr(s, "rsi_14", 0.0) or 0.0)
            if rsi > 0:
                if side == "LONG" and rsi >= self.cfg.rsi_block_high:
                    return None, "rsi_overextended", details
                if side == "SHORT" and rsi <= self.cfg.rsi_block_low:
                    return None, "rsi_overextended", details
        entry = s.ask if side == "LONG" else s.bid
        notional = self.risk.target_notional()
        if entry <= 0:
            return None, "invalid_entry", details
        contract_size = max(float(s.market.contract_size or 0.0), 0.0)
        qty = notional / (entry * contract_size) if contract_size > 0 else notional / entry
        entry_fee = self.risk.estimated_entry_fee(notional)
        stop = self.risk.stop_price(entry, side, qty, contract_size, entry_fee, getattr(s, "atr_pct", 0.0))
        dist = abs(entry - stop)
        if self.cfg.tp_mode == "indicator":
            target = 0.0          # no fixed target: indicators decide the take profit
        else:
            target = entry + dist * self.cfg.tp_r if side == "LONG" else entry - dist * self.cfg.tp_r
        sig = Signal(s.market.exchange, s.market.symbol, side, abs(score), entry, stop, target, notional,
                     self.risk.required_margin(notional), s.ts, qty,
                     [f'trend={details["trend"]:.2f}', f'htf={details["htf"]:.2f}', f'oi={details["oi"]:.2f}',
                      f'book={details["book"]:.2f}', f'fund={s.funding:.6f}',
                      f'liq={s.liquidation_pressure:.2f}' if s.liquidation_available else 'liq=NA'],
                     contract_size, s.atr_pct, float(s.funding))
        return sig, "signal", details

    def evaluate(self, s: Snapshot):
        sig, _, _ = self.evaluate_details(s)
        return sig
