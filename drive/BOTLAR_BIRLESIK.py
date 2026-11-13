# 16 TRADING BOTU - BIRLESTIRILMIS KOD ANALIZI

# Bu dosya 16 botun ana sinyal, config ve risk kodlarini icerir.

# Gorev: Tum botlari analiz et, hatalari bul, SUPER BOT insa et.

================================================================================


################################################################################
# BOT: 01_V20_FULL
################################################################################


# --- 01_V20_FULL/phoenix/signal.py (bulunamadi) ---


# --- 01_V20_FULL/phoenix/config.py ---

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from dataclasses import dataclass, field
from typing import Mapping


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, "") else float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw in (None, "") else int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Validated PHOENIX runtime configuration. Secrets are never stored here."""
    reference_equity: float = 1000.0
    entry_margin_usd: float = 50.0
    leverage: int = 10
    max_loss_usd: float = 20.0
    fee_bps_per_side: float = 5.5
    slippage_bps_reserve: float = 3.0
    maker_timeout_sec: int = 45
    requote_bps: float = 1.0
    tp_r: float = 1.0  # İYİLEŞTİRME: yakın kâr hedefi (2.2 ulaşılmıyordu)
    max_hold_bars: int = 96
    min_score: float = 0.30
    max_spread_bps: float = 12.0
    min_quote_volume_usd: float = 1_000_000.0
    stale_book_sec: float = 3.0
    universe_refresh_sec: int = 300
    max_reserved_margin_pct: float = 0.95
    correlation_window: int = 96
    correlation_limit: float = 0.85
    risk_per_trade_usd: float = 20.0
    daily_loss_limit_usd: float = 100.0
    weekly_loss_limit_usd: float = 250.0
    max_drawdown_pct: float = 0.20
    max_open_positions: int = 20
    funding_scale: float = 0.0005
    oi_change_scale: float = 100.0
    oi_lookback_sec: int = 300
    state_path: str = "state.json"
    journal_path: str = "trades.jsonl"
    strategy_weights: dict[str, float] = field(default_factory=lambda: {
        "trend": .35, "htf": .20, "oi": .15, "book": .15, "funding": .05, "liquidation": .10
    })

    def __post_init__(self):
        weights = dict(self.strategy_weights)
        if not weights or any(float(v) < 0 for v in weights.values()) or sum(float(v) for v in weights.values()) <= 0:
            raise ValueError("strategy_weights must contain non-negative weights with a positive total")
        object.__setattr__(self, "strategy_weights", weights)
        if self.reference_equity <= 0:
            raise ValueError("reference_equity must be > 0")
        if self.entry_margin_usd <= 0 or self.max_loss_usd <= 0 or self.risk_per_trade_usd <= 0:
            raise ValueError("margin/risk limits must be > 0")
        if not 1 <= self.leverage <= 125:
            raise ValueError("leverage must be between 1 and 125")
        if self.fee_bps_per_side < 0 or self.slippage_bps_reserve < 0:
            raise ValueError("fee/slippage cannot be negative")
        if self.maker_timeout_sec <= 0 or self.requote_bps < 0:
            raise ValueError("maker timeout must be > 0 and requote_bps >= 0")
        if not 0 < self.max_reserved_margin_pct <= 1:
            raise ValueError("max_reserved_margin_pct must be in (0, 1]")
        if not 0 < self.correlation_limit <= 1:
            raise ValueError("correlation_limit must be in (0, 1]")
        if self.correlation_window < 3:
            raise ValueError("correlation_window must be >= 3")
        if not 0 < self.max_drawdown_pct <= 1:
            raise ValueError("max_drawdown_pct must be in (0, 1]")
        if self.daily_loss_limit_usd <= 0 or self.weekly_loss_limit_usd <= 0:
            raise ValueError("loss limits must be > 0")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be >= 1")
        if not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be in [0, 1]")
        if self.max_spread_bps <= 0 or self.min_quote_volume_usd <= 0:
            raise ValueError("spread and volume limits must be > 0")
        if self.stale_book_sec <= 0 or self.universe_refresh_sec <= 0:
            raise ValueError("stale_book_sec and universe_refresh_sec must be > 0")
        if self.tp_r <= 0 or self.max_hold_bars < 1:
            raise ValueError("tp_r must be > 0 and max_hold_bars >= 1")
        if self.funding_scale <= 0:
            raise ValueError("funding_scale must be > 0")
        if self.oi_change_scale <= 0 or self.oi_lookback_sec <= 0:
            raise ValueError("oi_change_scale and oi_lookback_sec must be > 0")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """Load every non-secret runtime parameter from environment variables."""
        e = os.environ if env is None else env
        weights = {
            "trend": float(e.get("PHOENIX_WEIGHT_TREND", .35)),
            "htf": float(e.get("PHOENIX_WEIGHT_HTF", .20)),
            "oi": float(e.get("PHOENIX_WEIGHT_OI", .15)),
            "book": float(e.get("PHOENIX_WEIGHT_BOOK", .15)),
            "funding": float(e.get("PHOENIX_WEIGHT_FUNDING", .05)),
            "liquidation": float(e.get("PHOENIX_WEIGHT_LIQUIDATION", .10)),
        }
        def f(n, d): return d if e.get(n) in (None, "") else float(e[n])
        def i(n, d): return d if e.get(n) in (None, "") else int(e[n])
        return cls(
            reference_equity=f("PHOENIX_REFERENCE_EQUITY",1000), entry_margin_usd=f("PHOENIX_ENTRY_MARGIN_USD",50),
            leverage=i("PHOENIX_LEVERAGE",10), max_loss_usd=f("PHOENIX_MAX_LOSS_USD",20),
            fee_bps_per_side=f("PHOENIX_FEE_BPS_PER_SIDE",5.5), slippage_bps_reserve=f("PHOENIX_SLIPPAGE_BPS_RESERVE",3),
            maker_timeout_sec=i("PHOENIX_MAKER_TIMEOUT_SEC",45), requote_bps=f("PHOENIX_REQUOTE_BPS",1),
            tp_r=f("PHOENIX_TP_R",1.0), max_hold_bars=i("PHOENIX_MAX_HOLD_BARS",96), min_score=f("PHOENIX_MIN_SCORE",.30),
            max_spread_bps=f("PHOENIX_MAX_SPREAD_BPS",12), min_quote_volume_usd=f("PHOENIX_MIN_QUOTE_VOLUME_USD",1_000_000),
            stale_book_sec=f("PHOENIX_STALE_BOOK_SEC",3), universe_refresh_sec=i("PHOENIX_UNIVERSE_REFRESH_SEC",300),
            max_reserved_margin_pct=f("PHOENIX_MAX_RESERVED_MARGIN_PCT",.95), correlation_window=i("PHOENIX_CORRELATION_WINDOW",96),
            correlation_limit=f("PHOENIX_CORRELATION_LIMIT",.85), risk_per_trade_usd=f("PHOENIX_RISK_PER_TRADE_USD",20),
            daily_loss_limit_usd=f("PHOENIX_DAILY_LOSS_LIMIT_USD",100), weekly_loss_limit_usd=f("PHOENIX_WEEKLY_LOSS_LIMIT_USD",250),
            max_drawdown_pct=f("PHOENIX_MAX_DRAWDOWN_PCT",.20), max_open_positions=i("PHOENIX_MAX_OPEN_POSITIONS",20),
            funding_scale=f("PHOENIX_FUNDING_SCALE",.0005), oi_change_scale=f("PHOENIX_OI_CHANGE_SCALE",100.0),
            oi_lookback_sec=i("PHOENIX_OI_LOOKBACK_SEC",300), state_path=e.get("PHOENIX_STATE_PATH","state.json"),
            journal_path=e.get("PHOENIX_JOURNAL_PATH","trades.jsonl"), strategy_weights=weights,
        )


# --- 01_V20_FULL/phoenix/risk.py ---

from dataclasses import dataclass
from .models import Position


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg

    def target_notional(self):
        return self.cfg.entry_margin_usd * self.cfg.leverage

    def required_margin(self, notional):
        if self.cfg.leverage <= 0:
            return float("inf")
        return notional / self.cfg.leverage

    def estimated_entry_fee(self, notional):
        return abs(notional) * self.cfg.fee_bps_per_side / 10000

    def stop_price(self, entry, side, qty_contracts, contract_size=1.0, entry_fee=0):
        budget = max(0.0, self.cfg.max_loss_usd - max(0.0, entry_fee))
        # qty_contracts is exchange contract quantity; contract_size converts
        # contracts into base-asset exposure for correct USD loss budgeting.
        cost_factor = 1.0 + (self.cfg.fee_bps_per_side + self.cfg.slippage_bps_reserve) / 10000
        denom = abs(qty_contracts) * max(float(contract_size or 0.0), 0.0) * cost_factor
        distance = budget / denom if denom else 0.0
        return max(0.0, entry - distance) if side == "LONG" else entry + distance

    def used_margin(self, positions, pending_reserved=0):
        return sum(
            (p.reserved_margin if p.reserved_margin > 0 else p.margin)
            for p in positions if p.status == "OPEN"
        ) + max(0.0, pending_reserved)

    def available_margin(self, equity, positions, pending_reserved=0):
        cap = max(0.0, equity) * self.cfg.max_reserved_margin_pct
        return max(0.0, cap - self.used_margin(positions, pending_reserved))

    def can_enter(
        self,
        equity,
        positions,
        pending_reserved,
        notional,
        daily_loss=0.0,
        weekly_loss=0.0,
        peak_equity=None,
    ):
        if equity <= 0:
            return RiskDecision(False, "non_positive_equity")
        if daily_loss <= -self.cfg.daily_loss_limit_usd:
            return RiskDecision(False, "daily_loss_kill_switch")
        if weekly_loss <= -self.cfg.weekly_loss_limit_usd:
            return RiskDecision(False, "weekly_loss_kill_switch")
        if peak_equity is not None and peak_equity > 0:
            drawdown = (peak_equity - equity) / peak_equity
            if drawdown >= self.cfg.max_drawdown_pct:
                return RiskDecision(False, "max_drawdown_kill_switch")

        need = self.required_margin(notional)
        opens = [p for p in positions if p.status == "OPEN"]
        cap = equity * self.cfg.max_reserved_margin_pct
        used = self.used_margin(opens, pending_reserved)
        if len(opens) >= self.cfg.max_open_positions:
            return RiskDecision(False, "max_open_positions")
        if need <= 0 or notional <= 0:
            return RiskDecision(False, "invalid_margin")
        if used + need > cap + 1e-9:
            return RiskDecision(False, f"reserved_margin_cap:{used + need:.2f}>{cap:.2f}")
        return RiskDecision(True)


################################################################################
# BOT: 02_V20_FIXED
################################################################################


# --- 02_V20_FIXED/phoenix/signal.py (bulunamadi) ---


# --- 02_V20_FIXED/phoenix/config.py ---

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from dataclasses import dataclass, field
from typing import Mapping


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, "") else float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw in (None, "") else int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Validated PHOENIX runtime configuration. Secrets are never stored here."""
    reference_equity: float = 1000.0
    entry_margin_usd: float = 50.0
    leverage: int = 10
    max_loss_usd: float = 20.0
    fee_bps_per_side: float = 5.5
    slippage_bps_reserve: float = 3.0
    maker_timeout_sec: int = 45
    requote_bps: float = 1.0
    tp_r: float = 1.0  # İYİLEŞTİRME: yakın kâr hedefi (2.2 ulaşılmıyordu)
    max_hold_bars: int = 96
    min_score: float = 0.30
    max_spread_bps: float = 12.0
    min_quote_volume_usd: float = 1_000_000.0
    stale_book_sec: float = 3.0
    universe_refresh_sec: int = 300
    max_reserved_margin_pct: float = 0.95
    correlation_window: int = 96
    correlation_limit: float = 0.85
    risk_per_trade_usd: float = 20.0
    daily_loss_limit_usd: float = 100.0
    weekly_loss_limit_usd: float = 250.0
    max_drawdown_pct: float = 0.20
    max_open_positions: int = 20
    funding_scale: float = 0.0005
    oi_change_scale: float = 100.0
    oi_lookback_sec: int = 300
    state_path: str = "state.json"
    journal_path: str = "trades.jsonl"
    strategy_weights: dict[str, float] = field(default_factory=lambda: {
        "trend": .35, "htf": .20, "oi": .15, "book": .15, "funding": .05, "liquidation": .10
    })

    def __post_init__(self):
        weights = dict(self.strategy_weights)
        if not weights or any(float(v) < 0 for v in weights.values()) or sum(float(v) for v in weights.values()) <= 0:
            raise ValueError("strategy_weights must contain non-negative weights with a positive total")
        object.__setattr__(self, "strategy_weights", weights)
        if self.reference_equity <= 0:
            raise ValueError("reference_equity must be > 0")
        if self.entry_margin_usd <= 0 or self.max_loss_usd <= 0 or self.risk_per_trade_usd <= 0:
            raise ValueError("margin/risk limits must be > 0")
        if not 1 <= self.leverage <= 125:
            raise ValueError("leverage must be between 1 and 125")
        if self.fee_bps_per_side < 0 or self.slippage_bps_reserve < 0:
            raise ValueError("fee/slippage cannot be negative")
        if self.maker_timeout_sec <= 0 or self.requote_bps < 0:
            raise ValueError("maker timeout must be > 0 and requote_bps >= 0")
        if not 0 < self.max_reserved_margin_pct <= 1:
            raise ValueError("max_reserved_margin_pct must be in (0, 1]")
        if not 0 < self.correlation_limit <= 1:
            raise ValueError("correlation_limit must be in (0, 1]")
        if self.correlation_window < 3:
            raise ValueError("correlation_window must be >= 3")
        if not 0 < self.max_drawdown_pct <= 1:
            raise ValueError("max_drawdown_pct must be in (0, 1]")
        if self.daily_loss_limit_usd <= 0 or self.weekly_loss_limit_usd <= 0:
            raise ValueError("loss limits must be > 0")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be >= 1")
        if not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be in [0, 1]")
        if self.max_spread_bps <= 0 or self.min_quote_volume_usd <= 0:
            raise ValueError("spread and volume limits must be > 0")
        if self.stale_book_sec <= 0 or self.universe_refresh_sec <= 0:
            raise ValueError("stale_book_sec and universe_refresh_sec must be > 0")
        if self.tp_r <= 0 or self.max_hold_bars < 1:
            raise ValueError("tp_r must be > 0 and max_hold_bars >= 1")
        if self.funding_scale <= 0:
            raise ValueError("funding_scale must be > 0")
        if self.oi_change_scale <= 0 or self.oi_lookback_sec <= 0:
            raise ValueError("oi_change_scale and oi_lookback_sec must be > 0")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """Load every non-secret runtime parameter from environment variables."""
        e = os.environ if env is None else env
        weights = {
            "trend": float(e.get("PHOENIX_WEIGHT_TREND", .35)),
            "htf": float(e.get("PHOENIX_WEIGHT_HTF", .20)),
            "oi": float(e.get("PHOENIX_WEIGHT_OI", .15)),
            "book": float(e.get("PHOENIX_WEIGHT_BOOK", .15)),
            "funding": float(e.get("PHOENIX_WEIGHT_FUNDING", .05)),
            "liquidation": float(e.get("PHOENIX_WEIGHT_LIQUIDATION", .10)),
        }
        def f(n, d): return d if e.get(n) in (None, "") else float(e[n])
        def i(n, d): return d if e.get(n) in (None, "") else int(e[n])
        return cls(
            reference_equity=f("PHOENIX_REFERENCE_EQUITY",1000), entry_margin_usd=f("PHOENIX_ENTRY_MARGIN_USD",50),
            leverage=i("PHOENIX_LEVERAGE",10), max_loss_usd=f("PHOENIX_MAX_LOSS_USD",20),
            fee_bps_per_side=f("PHOENIX_FEE_BPS_PER_SIDE",5.5), slippage_bps_reserve=f("PHOENIX_SLIPPAGE_BPS_RESERVE",3),
            maker_timeout_sec=i("PHOENIX_MAKER_TIMEOUT_SEC",45), requote_bps=f("PHOENIX_REQUOTE_BPS",1),
            tp_r=f("PHOENIX_TP_R",1.0), max_hold_bars=i("PHOENIX_MAX_HOLD_BARS",96), min_score=f("PHOENIX_MIN_SCORE",.30),
            max_spread_bps=f("PHOENIX_MAX_SPREAD_BPS",12), min_quote_volume_usd=f("PHOENIX_MIN_QUOTE_VOLUME_USD",1_000_000),
            stale_book_sec=f("PHOENIX_STALE_BOOK_SEC",3), universe_refresh_sec=i("PHOENIX_UNIVERSE_REFRESH_SEC",300),
            max_reserved_margin_pct=f("PHOENIX_MAX_RESERVED_MARGIN_PCT",.95), correlation_window=i("PHOENIX_CORRELATION_WINDOW",96),
            correlation_limit=f("PHOENIX_CORRELATION_LIMIT",.85), risk_per_trade_usd=f("PHOENIX_RISK_PER_TRADE_USD",20),
            daily_loss_limit_usd=f("PHOENIX_DAILY_LOSS_LIMIT_USD",100), weekly_loss_limit_usd=f("PHOENIX_WEEKLY_LOSS_LIMIT_USD",250),
            max_drawdown_pct=f("PHOENIX_MAX_DRAWDOWN_PCT",.20), max_open_positions=i("PHOENIX_MAX_OPEN_POSITIONS",20),
            funding_scale=f("PHOENIX_FUNDING_SCALE",.0005), oi_change_scale=f("PHOENIX_OI_CHANGE_SCALE",100.0),
            oi_lookback_sec=i("PHOENIX_OI_LOOKBACK_SEC",300), state_path=e.get("PHOENIX_STATE_PATH","state.json"),
            journal_path=e.get("PHOENIX_JOURNAL_PATH","trades.jsonl"), strategy_weights=weights,
        )


################################################################################
# BOT: 03_V22_7
################################################################################


# --- 03_V22_7/phoenix/signal.py (bulunamadi) ---


# --- 03_V22_7/phoenix/config.py ---

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from dataclasses import dataclass, field
from typing import Mapping


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, "") else float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw in (None, "") else int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Validated PHOENIX runtime configuration. Secrets are never stored here.

    V22.6-FINAL entry semantics (fixes the V22.0.5 stop/liquidation contradiction):
      entry_mode="margin"   (DEFAULT) PHOENIX_ENTRY_MARGIN_USD (50) x leverage (10) = 500 USD notional.
                            The -$20 stop is then a ~4% price move - INSIDE the ~10% isolated
                            liquidation distance, so the stop is real and reachable.
      entry_mode="notional" PHOENIX_ENTRY_NOTIONAL_USD directly (e.g. 50). The -$20 stop would be a
                            ~40% move: physics caps the stop at liquidation_buffer_fraction/leverage
                            (0.70/10 = 7%) so the modeled per-position loss is ~-$3.9, not -$20.
    """
    reference_equity: float = 1000.0
    # USER RULES (V22.6-FINAL): 1000 USD | 50 USD margin entry | 10x | -20 USD stop | unlimited count.
    entry_mode: str = "margin"
    entry_margin_usd: float = 50.0          # input in margin mode (V22.0.5 derived this; now authoritative)
    entry_notional_usd: float = 0.0         # 0 = derived; set directly only with entry_mode="notional"
    leverage: int = 10
    max_loss_usd: float = 20.0
    # Stop-distance cap relative to leverage. Only binds when the dollar stop would sit beyond it
    # (margin mode 4% < 7%: never binds; notional mode 40% -> capped to 7%). Heuristic, not a
    # liquidation-price guarantee.
    liquidation_buffer_fraction: float = 0.70
    fee_bps_per_side: float = 5.5
    slippage_bps_reserve: float = 3.0
    maker_timeout_sec: int = 45
    requote_bps: float = 1.0
    tp_r: float = 1.0  # İYİLEŞTİRME: yakın kâr hedefi (2.2 ulaşılmıyordu)
    max_hold_bars: int = 96
    min_score: float = 0.30
    max_spread_bps: float = 12.0
    min_quote_volume_usd: float = 1_000_000.0
    stale_book_sec: float = 3.0
    universe_refresh_sec: int = 300
    max_reserved_margin_pct: float = 1.0
    correlation_window: int = 96
    correlation_limit: float = 0.85
    risk_per_trade_usd: float = 20.0
    # Portfolio kill-switches are OFF by default (user rule: bot keeps trading 24/7, no daily/weekly loss stop).
    # daily/weekly: 0 = disabled. max_drawdown_pct: 1.0 = disabled. Set positive values to re-enable.
    daily_loss_limit_usd: float = 0.0
    weekly_loss_limit_usd: float = 0.0
    max_drawdown_pct: float = 1.0
    # 0 means no arbitrary position-count cap; margin/equity and risk gates remain active.
    max_open_positions: int = 0
    funding_scale: float = 0.0005
    # --- V20 strategy gate (shadow-counted even when off) ---
    require_alignment: bool = False
    alignment_min: float = 0.10
    # --- V20 correlation gate ---
    correlation_min_samples: int = 30
    correlation_same_direction_only: bool = True
    atr_stop_multiplier: float = 0.0   # 0 = ATR never touches the stop: stop is the fixed -max_loss_usd rule
    # Take profit is decided by indicators: a position is closed when the signed score in its
    # direction drops below tp_exit_score AND its net profit clears the R-based floor.
    tp_mode: str = "indicator"
    tp_exit_score: float = 0.10
    tp_min_net_usd: float = 0.0        # absolute net floor (kept for compat; see tp_min_net_effective)
    # V22.6: R-based profit floors. The old tp_min_net_usd=0.10 cut winners at +$0.10 while losers
    # lost ~-$4..-$20 (payoff ~1:40 -> mathematically unprofitable). tp_min_r=0.5 demands at least
    # 0.5 x risk ($10 at -$20 risk) before a score-fade exit may fire.
    tp_min_r: float = 0.5
    breakeven_r: float = 0.5           # move stop to entry+costs once net >= breakeven_r x risk (0 = off)
    trail_arm_r: float = 1.0           # arm the trailing stop once peak net >= trail_arm_r x risk (0 = off)
    trail_giveback_r: float = 0.5      # trail locks peak_net - trail_giveback_r x risk
    exit_eval_budget_sec: int = 40
    paper_stop_fill: str = "worse"  # conservative: worse of stop and observed mark
    # --- V22.6 signal-quality upgrades (all env-tunable, architecture unchanged) ---
    oi_price_agreement: bool = True    # sign OI flow with 15m price direction (OI up+price up = new longs)
    conflict_penalty: float = 0.70     # multiply score when 15m trend and 1h/4h disagree (0 disables, 1 = off)
    rsi_gate: bool = True              # graded entry penalty; extreme levels still block
    rsi_block_high: float = 80.0       # hard block LONG at/above this
    rsi_block_low: float = 20.0        # hard block SHORT at/below this
    rsi_soft_high: float = 70.0        # start LONG penalty
    rsi_soft_low: float = 30.0         # start SHORT penalty
    rsi_penalty_high: float = 75.0     # stronger LONG penalty
    rsi_penalty_low: float = 25.0      # stronger SHORT penalty
    paper_funding_accrual: bool = True # accrue funding every 8h held in PAPER (honest cost model)
    live_indicator_tp: bool = True     # bot-managed indicator TP + stop amendment in LIVE
    # --- V20 maker execution ---
    max_requotes: int = 2
    max_chase_bps: float = 10.0
    auto_bump_max_factor: float = 1.0
    okx_td_mode: str = "cross"
    okx_pos_mode: str = "net"
    binance_pos_mode: str = "oneway"
    paper_state_path: str = "paper_state.json"
    paper_journal_path: str = "paper_trades.jsonl"
    oi_change_scale: float = 100.0
    oi_lookback_sec: int = 300
    oi_persistence_sec: int = 1800
    book_history_sec: int = 60
    book_min_samples: int = 3
    signal_confirmation_samples: int = 2
    signal_confirmation_window_sec: int = 90
    strict_liquidation_guard: bool = False
    state_path: str = "state.json"
    journal_path: str = "trades.jsonl"
    strategy_weights: dict[str, float] = field(default_factory=lambda: {
        "trend": .35, "htf_1h": .15, "htf_4h": .10, "oi": .15, "book": .15, "funding": .05, "liquidation": .05
    })

    @property
    def entry_margin_effective(self) -> float:
        """Margin actually reserved per position."""
        return self.entry_notional_usd / self.leverage

    @property
    def entry_margin_usd_effective(self) -> float:
        return self.entry_margin_usd if self.entry_mode == "margin" else self.entry_notional_usd / self.leverage

    @property
    def stop_distance_pct_estimate(self) -> float:
        """Approx. price distance of the -max_loss_usd stop, as a fraction of entry (before fees)."""
        return self.max_loss_usd / self.entry_notional_usd if self.entry_notional_usd > 0 else 0.0

    @property
    def stop_leverage_cap_pct(self) -> float:
        """Leverage-relative stop-distance cap (fraction of entry)."""
        return self.liquidation_buffer_fraction / self.leverage

    @property
    def stop_beyond_liquidation(self) -> bool:
        """True when the modeled stop sits at/after the leverage-relative cap (~0.8/leverage)."""
        return self.stop_distance_pct_estimate >= 0.8 / self.leverage

    @property
    def tp_min_net_effective(self) -> float:
        """Net profit a position must reach before the indicator exit may fire."""
        return max(float(self.tp_min_net_usd), float(self.tp_min_r) * self.max_loss_usd)

    def __post_init__(self):
        if self.entry_mode not in {"margin", "notional"}:
            raise ValueError("entry_mode must be 'margin' or 'notional'")
        weights = dict(self.strategy_weights)
        if not weights or any(float(v) < 0 for v in weights.values()) or sum(float(v) for v in weights.values()) <= 0:
            raise ValueError("strategy_weights must contain non-negative weights with a positive total")
        object.__setattr__(self, "strategy_weights", weights)
        if self.reference_equity <= 0:
            raise ValueError("reference_equity must be > 0")
        if self.entry_margin_usd < 0 or self.entry_notional_usd < 0 or self.max_loss_usd <= 0 or self.risk_per_trade_usd <= 0:
            raise ValueError("margin/risk limits must be > 0")
        if self.entry_mode == "margin":
            if self.entry_margin_usd <= 0:
                raise ValueError("entry_margin_usd must be > 0 in margin mode")
            object.__setattr__(self, "entry_notional_usd", self.entry_margin_usd * self.leverage)
        else:
            if self.entry_notional_usd <= 0:
                raise ValueError("entry_notional_usd must be > 0 in notional mode")
            object.__setattr__(self, "entry_margin_usd", self.entry_notional_usd / self.leverage)
        if not 1 <= self.leverage <= 125:
            raise ValueError("leverage must be between 1 and 125")
        if self.fee_bps_per_side < 0 or self.slippage_bps_reserve < 0:
            raise ValueError("fee/slippage cannot be negative")
        if self.maker_timeout_sec <= 0 or self.requote_bps < 0:
            raise ValueError("maker timeout must be > 0 and requote_bps >= 0")
        if not 0 < self.max_reserved_margin_pct <= 1:
            raise ValueError("max_reserved_margin_pct must be in (0, 1]")
        if not 0 < self.correlation_limit <= 1:
            raise ValueError("correlation_limit must be in (0, 1]")
        if self.correlation_window < 3:
            raise ValueError("correlation_window must be >= 3")
        if not 0 < self.max_drawdown_pct <= 1:
            raise ValueError("max_drawdown_pct must be in (0, 1] (1.0 = disabled)")
        if self.daily_loss_limit_usd < 0 or self.weekly_loss_limit_usd < 0:
            raise ValueError("loss limits must be >= 0 (0 = disabled)")
        if self.max_open_positions < 0:
            raise ValueError("max_open_positions must be >= 0 (0 = unlimited)")
        if self.paper_stop_fill not in {"stop", "worse"}:
            raise ValueError("paper_stop_fill must be stop or worse")
        if self.atr_stop_multiplier < 0:
            raise ValueError("atr_stop_multiplier must be >= 0 (0 = off)")
        if self.tp_mode not in {"indicator", "fixed_rr"}:
            raise ValueError("tp_mode must be indicator or fixed_rr")
        if not 0 <= self.tp_exit_score <= 1 or self.tp_min_net_usd < 0 or self.exit_eval_budget_sec < 1:
            raise ValueError("tp_exit_score must be in [0, 1], tp_min_net_usd >= 0, exit_eval_budget_sec >= 1")
        if not 0 <= self.tp_min_r <= 10 or not 0 <= self.breakeven_r <= 10 or not 0 <= self.trail_arm_r <= 10:
            raise ValueError("tp_min_r/breakeven_r/trail_arm_r must be in [0, 10]")
        if not 0 < self.trail_giveback_r <= 10:
            raise ValueError("trail_giveback_r must be in (0, 10]")
        if self.oi_persistence_sec < self.oi_lookback_sec:
            raise ValueError("oi_persistence_sec must be >= oi_lookback_sec")
        if self.book_history_sec <= 0 or self.book_min_samples < 1 or self.signal_confirmation_samples < 1 or self.signal_confirmation_window_sec <= 0:
            raise ValueError("book/confirmation persistence settings are invalid")
        if not 0 <= self.conflict_penalty <= 1:
            raise ValueError("conflict_penalty must be in [0, 1] (1 = off, 0 = max penalty)")
        if not 0 <= self.rsi_block_low < self.rsi_block_high <= 100:
            raise ValueError("rsi thresholds must satisfy 0 <= rsi_block_low < rsi_block_high <= 100")
        # Surface the stop/liquidation relationship loudly (never silently):
        # margin mode: -$20 on $500 = 4% -> inside the 7% cap, stop is REAL.
        # notional mode: capped to the leverage-relative distance; max_loss_usd is then a ceiling, not the trigger.
        if self.strict_liquidation_guard and self.stop_distance_pct_estimate >= 0.8 / self.leverage \
                and self.stop_distance_pct_estimate > self.stop_leverage_cap_pct:
            raise ValueError("max_loss_usd is too large for this notional/leverage: the stop would sit at or beyond liquidation")
        if not (0 <= self.rsi_block_low <= self.rsi_penalty_low <= self.rsi_soft_low <= self.rsi_soft_high <= self.rsi_penalty_high <= self.rsi_block_high <= 100):
            raise ValueError("RSI soft/penalty thresholds must be ordered")
        if not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be in [0, 1]")
        if self.max_spread_bps <= 0 or self.min_quote_volume_usd <= 0:
            raise ValueError("spread and volume limits must be > 0")
        if self.stale_book_sec <= 0 or self.universe_refresh_sec <= 0:
            raise ValueError("stale_book_sec and universe_refresh_sec must be > 0")
        if self.tp_r <= 0 or self.max_hold_bars < 1:
            raise ValueError("tp_r must be > 0 and max_hold_bars >= 1")
        if self.funding_scale <= 0:
            raise ValueError("funding_scale must be > 0")
        if not 0 <= self.alignment_min <= 1:
            raise ValueError("alignment_min must be in [0, 1]")
        if self.correlation_min_samples < 3:
            raise ValueError("correlation_min_samples must be >= 3")
        if self.max_requotes < 0 or self.max_chase_bps < 0 or self.auto_bump_max_factor < 0:
            raise ValueError("max_requotes/max_chase_bps/auto_bump_max_factor cannot be negative")
        if self.okx_pos_mode not in {"net", "long_short"}:
            raise ValueError("okx_pos_mode must be 'net' or 'long_short'")
        if self.binance_pos_mode not in {"oneway", "hedge"}:
            raise ValueError("binance_pos_mode must be 'oneway' or 'hedge'")
        if self.okx_td_mode not in {"cross", "isolated"}:
            raise ValueError("okx_td_mode must be 'cross' or 'isolated'")
        if self.oi_change_scale <= 0 or self.oi_lookback_sec <= 0:
            raise ValueError("oi_change_scale and oi_lookback_sec must be > 0")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """Load every non-secret runtime parameter from environment variables."""
        e = os.environ if env is None else env
        weights = {
            "trend": float(e.get("PHOENIX_WEIGHT_TREND", .35)),
            "htf": float(e.get("PHOENIX_WEIGHT_HTF", .20)),
            "oi": float(e.get("PHOENIX_WEIGHT_OI", .15)),
            "book": float(e.get("PHOENIX_WEIGHT_BOOK", .15)),
            "funding": float(e.get("PHOENIX_WEIGHT_FUNDING", .05)),
            "liquidation": float(e.get("PHOENIX_WEIGHT_LIQUIDATION", .10)),
        }
        mode = str(e.get("PHOENIX_ENTRY_MODE", "margin") or "margin").strip().lower()
        margin_raw = e.get("PHOENIX_ENTRY_MARGIN_USD")
        notional_raw = e.get("PHOENIX_ENTRY_NOTIONAL_USD")
        if mode == "margin":
            if notional_raw not in (None, ""):
                raise ValueError(
                    "PHOENIX_ENTRY_NOTIONAL_USD is set but PHOENIX_ENTRY_MODE=margin (default). "
                    "Remove PHOENIX_ENTRY_NOTIONAL_USD, or set PHOENIX_ENTRY_MODE=notional to size entries by notional.")
            margin = 50.0 if margin_raw in (None, "") else float(margin_raw)
            notional = 0.0
        else:
            if margin_raw not in (None, ""):
                raise ValueError(
                    "PHOENIX_ENTRY_MARGIN_USD is set but PHOENIX_ENTRY_MODE=notional. "
                    "Remove PHOENIX_ENTRY_MARGIN_USD, or set PHOENIX_ENTRY_MODE=margin (default) to size entries by margin.")
            notional = 50.0 if notional_raw in (None, "") else float(notional_raw)
            margin = 0.0

        def f(n, d): return d if e.get(n) in (None, "") else float(e[n])
        def i(n, d): return d if e.get(n) in (None, "") else int(e[n])
        def b(n, d): return d if e.get(n) in (None, "") else str(e[n]).strip().lower() in {"1", "true", "yes", "on"}
        return cls(
            reference_equity=f("PHOENIX_REFERENCE_EQUITY",1000),
            entry_mode=mode, entry_margin_usd=margin, entry_notional_usd=notional,
            leverage=i("PHOENIX_LEVERAGE",10), max_loss_usd=f("PHOENIX_MAX_LOSS_USD",20),
            liquidation_buffer_fraction=f("PHOENIX_LIQUIDATION_BUFFER_FRACTION",0.70),
            fee_bps_per_side=f("PHOENIX_FEE_BPS_PER_SIDE",5.5), slippage_bps_reserve=f("PHOENIX_SLIPPAGE_BPS_RESERVE",3),
            maker_timeout_sec=i("PHOENIX_MAKER_TIMEOUT_SEC",45), requote_bps=f("PHOENIX_REQUOTE_BPS",1),
            tp_r=f("PHOENIX_TP_R",1.0), max_hold_bars=i("PHOENIX_MAX_HOLD_BARS",96), min_score=f("PHOENIX_MIN_SCORE",.30),
            max_spread_bps=f("PHOENIX_MAX_SPREAD_BPS",12), min_quote_volume_usd=f("PHOENIX_MIN_QUOTE_VOLUME_USD",1_000_000),
            stale_book_sec=f("PHOENIX_STALE_BOOK_SEC",3), universe_refresh_sec=i("PHOENIX_UNIVERSE_REFRESH_SEC",300),
            max_reserved_margin_pct=f("PHOENIX_MAX_RESERVED_MARGIN_PCT",1.0), correlation_window=i("PHOENIX_CORRELATION_WINDOW",96),
            correlation_limit=f("PHOENIX_CORRELATION_LIMIT",.85), risk_per_trade_usd=f("PHOENIX_RISK_PER_TRADE_USD",20),
            daily_loss_limit_usd=f("PHOENIX_DAILY_LOSS_LIMIT_USD",0), weekly_loss_limit_usd=f("PHOENIX_WEEKLY_LOSS_LIMIT_USD",0),
            max_drawdown_pct=f("PHOENIX_MAX_DRAWDOWN_PCT",1.0), max_open_positions=i("PHOENIX_MAX_OPEN_POSITIONS",0),
            funding_scale=f("PHOENIX_FUNDING_SCALE",.0005), oi_change_scale=f("PHOENIX_OI_CHANGE_SCALE",100.0),
            oi_lookback_sec=i("PHOENIX_OI_LOOKBACK_SEC",300), oi_persistence_sec=i("PHOENIX_OI_PERSISTENCE_SEC",1800),
            book_history_sec=i("PHOENIX_BOOK_HISTORY_SEC",60), book_min_samples=i("PHOENIX_BOOK_MIN_SAMPLES",3),
            signal_confirmation_samples=i("PHOENIX_SIGNAL_CONFIRMATION_SAMPLES",2), signal_confirmation_window_sec=i("PHOENIX_SIGNAL_CONFIRMATION_WINDOW_SEC",90), strict_liquidation_guard=b("PHOENIX_STRICT_LIQUIDATION_GUARD",False), state_path=e.get("PHOENIX_STATE_PATH","state.json"),
            journal_path=e.get("PHOENIX_JOURNAL_PATH","trades.jsonl"), strategy_weights=weights,

################################################################################
# BOT: 04_V23
################################################################################


# --- 04_V23/acarbot/signal.py (bulunamadi) ---


# --- 04_V23/acarbot/config.py ---

"""Ayarlar. Kullanıcının SABİT kuralları varsayılandır: 1000$ kasa, işlem başına 50$ teminat, 10x, maker giriş, sınırsız işlem."""
from __future__ import annotations
import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    # --- sabit kurallar ---
    equity_usd: float = 1000.0          # kasa
    margin_usd: float = 50.0            # işlem başına teminat
    leverage: int = 10                  # sabit kaldıraç
    margin_mode: str = "isolated"       # isolated: bir pozisyonun kaybı kendi teminatıyla sınırlı
    max_positions: int = 0              # 0 = sınırsız (tek sınır serbest teminat)
    entry_post_only: bool = False       # İYİLEŞTİRME: market emir (maker dolmuyordu — KGEN PENDING kaldı)
    # --- borsalar ---
    exchanges: tuple = ("binance", "okx")
    binance_public_www: str = "auto"    # auto | 1 | 0  (fapi 451 dönerse www.binance.com public rotası)
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    # --- risk ---
    fee_reserve_frac: float = 0.03      # kasadan komisyon/funding için ayrılan pay
    one_position_per_coin: bool = True  # aynı coin iki borsada birden açılmaz
    daily_loss_limit_usd: float = 150.0
    weekly_loss_limit_usd: float = 300.0
    max_drawdown_usd: float = 400.0     # kalıcı durdurma (elle kaldırılır)
    liq_mmr_assumed: float = 0.025      # bakım teminatı varsayımı (stop tasfiyeden önce kalsın diye)
    liq_safety: float = 0.90
    # --- strateji ---
    strategy: str = "pump_short"
    vs_min: float = 30.0                # son 1 saat hacmi / önceki 7 günün saatlik ortalaması
    r1_min: float = 0.05                # son 1 saat getirisi
    liq_min_usd: float = 2_000_000.0    # önceki 7 günün günlük ortalama hacmi
    min_age_hours: int = 336            # en az 14 günlük geçmiş
    stop_frac: float = 0.065
    tp_frac: float = 0.0                # 0 = kâr-al yok, süre çıkışı
    max_hold_sec: int = 86_400
    entry_ttl_sec: int = 3_600
    cooldown_sec: int = 86_400
    # --- çalışma ---
    mode: str = "paper"                 # paper | live
    scan_interval_sec: int = 300
    manage_interval_sec: int = 20
    max_candidates_per_scan: int = 12
    state_dir: str = "calisma"
    cert_dir: str = "sertifikalar"
    # paper dolum modeli (araştırmayla aynı)
    paper_through: float = 0.0005
    paper_stop_slip: float = 0.002
    paper_exit_slip: float = 0.0005
    # canlı kilitler
    confirm_live: str = ""              # "EVET" olmalı
    accept_unvalidated: str = ""        # sertifikasız stratejiyle canlı için: "RISKI_KABUL_EDIYORUM"
    # API
    binance_key: str = field(default="", repr=False)
    binance_secret: str = field(default="", repr=False)
    okx_key: str = field(default="", repr=False)
    okx_secret: str = field(default="", repr=False)
    okx_passphrase: str = field(default="", repr=False)
    binance_demo: bool = False
    okx_demo: bool = False

    @property
    def notional_usd(self) -> float:
        return self.margin_usd * self.leverage

    @property
    def max_slots(self) -> int:
        usable = self.equity_usd * (1.0 - self.fee_reserve_frac)
        n = int(usable // self.margin_usd)
        return min(n, self.max_positions) if self.max_positions > 0 else n

    def validate(self) -> list[str]:
        e = []
        if self.margin_usd <= 0 or self.equity_usd <= 0: e.append("kasa ve teminat pozitif olmalı")
        if self.leverage < 1: e.append("kaldıraç >= 1 olmalı")
        if self.margin_mode not in ("isolated", "cross"): e.append("margin_mode isolated|cross olmalı")
        if self.mode not in ("paper", "live"): e.append("mode paper|live olmalı")
        if not (0 < self.stop_frac < 1): e.append("stop_frac (0,1) aralığında olmalı")
        if self.margin_mode == "isolated" and self.stop_frac > self.max_safe_stop():
            e.append(f"stop %{self.stop_frac*100:.1f} izole {self.leverage}x tasfiye mesafesine fazla yakın (güvenli üst sınır %{self.max_safe_stop()*100:.2f})")
        if not self.exchanges: e.append("en az bir borsa gerekli")
        return e

    def max_safe_stop(self) -> float:
        return max(0.0, (1.0 / self.leverage - self.liq_mmr_assumed) * self.liq_safety)


_ENV_PREFIX = "ACARBOT_"


def load_settings(env_file: str = ".env", **overrides) -> Settings:
    _load_dotenv(env_file)
    vals = {}
    for f in fields(Settings):
        raw = os.environ.get(_ENV_PREFIX + f.name.upper())
        if raw is None or raw == "":
            continue
        t = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "str")
        if t == "bool": vals[f.name] = raw.strip().lower() in ("1", "true", "yes", "evet")
        elif t == "int": vals[f.name] = int(float(raw))
        elif t == "float": vals[f.name] = float(raw)
        elif t == "tuple": vals[f.name] = tuple(x.strip().lower() for x in raw.split(",") if x.strip())
        else: vals[f.name] = raw
    vals.update({k: v for k, v in overrides.items() if v is not None})
    s = replace(Settings(), **vals)
    errs = s.validate()
    if errs:
        raise ValueError("Ayar hatası: " + "; ".join(errs))
    return s


# --- 04_V23/acarbot/engine.py ---

"""Ana döngü: tara -> aday -> özellik -> strateji -> risk -> maker emir -> yönet -> kaydet.
Teknik arıza (veri alınamıyor, borsa hatası) durumunda yeni işlem AÇILMAZ, mevcut durum korunur ve sonraki döngü beklenir."""
from __future__ import annotations
import logging, time, uuid
from collections import deque
from typing import Optional
from .config import Settings
from .exchanges.base import Broker, MarketData
from .features import compute_features
from .journal import Journal
from .models import Instrument, Position, Signal
from .risk import RiskManager
from .rules import contracts_for_notional
from .strategies.base import Strategy

log = logging.getLogger("acarbot.engine")
SNAP_KEEP_SEC = 4200


class Engine:
    def __init__(self, cfg: Settings, feeds: dict[str, MarketData], broker: Broker, journal: Journal, strategy: Strategy, risk: Optional[RiskManager] = None, now=time.time):
        self.cfg = cfg; self.feeds = feeds; self.broker = broker; self.journal = journal; self.strategy = strategy; self.now = now
        self.risk = risk or RiskManager(cfg, now)
        self.positions: list[Position] = []
        self.snap: dict[str, dict[str, deque]] = {name: {} for name in feeds}      # borsa -> sembol -> (ts, last)
        self.inst: dict[str, dict[str, Instrument]] = {}
        self.stats = dict(tarama=0, aday=0, sinyal=0, emir=0, red=0, veri_hatasi=0)
        pos, extra = journal.load_state()
        self.positions = [p for p in pos if p.status in ("PENDING", "OPEN")]
        if extra.get("risk"): self.risk.load(extra["risk"])
        if self.positions: journal.event("durum_yuklendi", acik=len(self.positions))

    # ------------------------------------------------------------------ yardımcılar
    def _instruments(self, name: str) -> dict[str, Instrument]:
        if name not in self.inst: self.inst[name] = self.feeds[name].instruments()
        return self.inst[name]

    def _pnl_windows(self) -> tuple[float, float, float]:
        t = self.now(); day0 = t - (t % 86400); week0 = day0 - 6 * 86400
        return self.journal.realized(day0), self.journal.realized(week0), self.journal.realized(0.0)

    def _r1h_estimate(self, name: str, sym: str, last: float, t: float) -> Optional[float]:
        dq = self.snap[name].setdefault(sym, deque())
        dq.append((t, last))
        while dq and t - dq[0][0] > SNAP_KEEP_SEC: dq.popleft()
        ref = None
        for ts, px in dq:                                  # ~1 saat önceki (55-70 dk) en eski kayıt
            if 3300 <= t - ts <= 4200: ref = px; break
        return (last / ref - 1.0) if ref else None

    def save(self) -> None:
        self.journal.save_state(self.positions, dict(risk=self.risk.to_dict(), stats=self.stats))

    # ------------------------------------------------------------------ tarama
    def scan(self) -> list[Signal]:
        t = self.now(); signals: list[Signal] = []; self.stats["tarama"] += 1
        today, week, total = self._pnl_windows()
        for name, feed in self.feeds.items():
            try:
                inst = self._instruments(name); tk = feed.tickers()
            except Exception as e:
                self.stats["veri_hatasi"] += 1; self.journal.event("veri_hatasi", borsa=name, hata=str(e)[:200]); log.warning("%s veri alınamadı: %s", name, e)
                continue
            cands = []
            for sym, x in tk.items():
                if sym not in inst: continue
                r1 = self._r1h_estimate(name, sym, x["last"], t)
                if self.strategy.prefilter(r1, x.get("pct_24h"), x.get("quote_vol_24h", 0.0)):
                    cands.append((r1 if r1 is not None else (x.get("pct_24h") or 0.0), sym))
            cands.sort(reverse=True)
            for score, sym in cands[: self.cfg.max_candidates_per_scan]:
                i = inst[sym]; self.stats["aday"] += 1
                probe = Signal(name, sym, i.base, -1, 0.0, self.cfg.stop_frac, 0.0, 0, 0, "on_kontrol")
                ok, why = self.risk.can_open(probe, self.positions, today, week, total)
                if not ok:
                    self.journal.event("aday_red", borsa=name, sembol=sym, neden=why); continue
                try:
                    now_ms = int(self.now() * 1000)
                    f = compute_features(feed.ohlcv(sym, "5m", 30), feed.ohlcv(sym, "1h", 400), now_ms)
                except Exception as e:
                    self.stats["veri_hatasi"] += 1; self.journal.event("veri_hatasi", borsa=name, sembol=sym, hata=str(e)[:200]); continue
                if f is None:
                    self.journal.event("aday_red", borsa=name, sembol=sym, neden="ozellik_hesaplanamadi"); continue
                if i.listed_ms: f.age_hours = (now_ms - i.listed_ms) / 3_600_000.0     # OKX en fazla 300 saatlik mum verir; yas listeleme tarihinden
                if now_ms - (f.bar_ts + 300_000) > 660_000:          # son tamamlanan mum >2 bar eski: veri akisi kopmus/bayat
                    self.journal.event("aday_red", borsa=name, sembol=sym, neden="veri_bayat"); continue
                sig, why = self.strategy.evaluate(i, f)
                self.journal.event("aday", borsa=name, sembol=sym, sonuc=why, vs=round(f.vs, 2), r1h=round(f.r1h, 4), liq=round(f.liq_usd))
                if sig is None: continue
                self.stats["sinyal"] += 1; signals.append(sig)
                self._try_open(sig, i, today, week, total)
        self.save()
        return signals

    def _try_open(self, sig: Signal, inst: Instrument, today: float, week: float, total: float) -> Optional[Position]:
        ok, why = self.risk.can_open(sig, self.positions, today, week, total)
        if not ok:
            self.stats["red"] += 1; self.journal.event("sinyal_red", borsa=sig.exchange, sembol=sig.symbol, neden=why); return None
        qty = contracts_for_notional(self.cfg.notional_usd, sig.limit_price, inst)
        if qty <= 0:
            self.stats["red"] += 1; self.journal.event("sinyal_red", borsa=sig.exchange, sembol=sig.symbol, neden="min_emir_boyutu"); return None
        t = self.now()
        pos = Position(id=uuid.uuid4().hex[:12], exchange=sig.exchange, symbol=sig.symbol, base=sig.base, side=sig.side, qty=qty, contract_size=inst.contract_size,
                       limit_price=sig.limit_price, stop_frac=sig.stop_frac, tp_frac=sig.tp_frac, created_ts=t, expire_ts=t + sig.ttl_sec,
                       max_hold_sec=sig.max_hold_sec, reason=sig.reason, features=dict(sig.features))
        ok, why = self.broker.open_entry(pos, inst)
        if not ok:
            self.stats["red"] += 1; self.journal.event("emir_red", borsa=sig.exchange, sembol=sig.symbol, neden=why); return None
        self.positions.append(pos); self.stats["emir"] += 1
        self.journal.event("emir", id=pos.id, borsa=pos.exchange, sembol=pos.symbol, yon=pos.side, miktar=pos.qty, limit=pos.limit_price, stop=pos.stop_price, neden=pos.reason)
        log.info("EMİR %s %s %s limit=%.6g stop=%.6g (%s)", pos.exchange, pos.symbol, "LONG" if pos.side > 0 else "SHORT", pos.limit_price, pos.stop_price, pos.reason)
        return pos

    # ------------------------------------------------------------------ yönetim
    def manage(self) -> None:
        t = self.now(); changed = False
        for pos in list(self.positions):
            before = pos.status
            try:
                self.broker.manage(pos, self._instruments(pos.exchange)[pos.symbol], t)
            except Exception as e:                                  # teknik arıza: bekle
                self.stats["veri_hatasi"] += 1; self.journal.event("teknik_ariza", id=pos.id, hata=str(e)[:200]); continue
            if pos.status == before: continue
            changed = True
            if pos.status == "OPEN":
                self.journal.event("giris", id=pos.id, fiyat=pos.entry_price); log.info("GİRİŞ %s %s @ %.6g", pos.exchange, pos.symbol, pos.entry_price)
            elif pos.status == "CLOSED":
                self._on_closed(pos)
            elif pos.status == "CANCELLED":
                self.risk.on_entry_expired(pos); self.positions.remove(pos); self.journal.event("emir_iptal", id=pos.id, neden=pos.exit_reason)
        if changed:
            today, week, total = self._pnl_windows(); self.risk.update_limits(today, week, total)
            if self.risk.halted: self.journal.event("DURDURULDU", neden=self.risk.halt_reason); log.error("BOT DURDURULDU: %s", self.risk.halt_reason)
            self.save()

    def _on_closed(self, pos: Position) -> None:
        self.journal.record_closed(pos); self.risk.on_closed(pos)
        if pos in self.positions: self.positions.remove(pos)
        self.journal.event("cikis", id=pos.id, neden=pos.exit_reason, fiyat=pos.exit_price, pnl=round(pos.pnl_usd, 4))
        log.info("ÇIKIŞ %s %s %s @ %.6g net=%.2f$", pos.exchange, pos.symbol, pos.exit_reason, pos.exit_price, pos.pnl_usd)

    def flatten_all(self, reason: str = "KULLANICI") -> None:
        t = self.now()
        for pos in list(self.positions):
            self.broker.flatten(pos, self._instruments(pos.exchange)[pos.symbol], t, reason)
            if pos.status == "CLOSED": self._on_closed(pos)
            elif pos.status == "CANCELLED": self.positions.remove(pos)
        self.save()

    # ------------------------------------------------------------------ döngü
    def run(self, duration_sec: Optional[float] = None, sleep=time.sleep) -> None:
        start = self.now(); next_scan = 0.0; next_manage = 0.0
        self.journal.event("basladi", mod=self.cfg.mode, strateji=self.strategy.name, borsalar=list(self.feeds))
        while duration_sec is None or self.now() - start < duration_sec:
            t = self.now()
            if t >= next_manage:
                self.manage(); next_manage = t + self.cfg.manage_interval_sec
            if t >= next_scan:
                self.scan()
                iv = self.cfg.scan_interval_sec
                next_scan = (int(self.now()) // iv + 1) * iv + 8          # 5dk mum kapanışından 8 sn sonra
            sleep(1.0)
        self.save(); self.journal.event("durdu")

    def summary(self) -> dict:
        tr = self.journal.closed_trades(); pnl = [x["pnl_usd"] for x in tr]
        wins = [x for x in pnl if x > 0]; losses = [x for x in pnl if x <= 0]
        return dict(mod=self.cfg.mode, strateji=self.strategy.name, tarama=self.stats["tarama"], aday=self.stats["aday"], sinyal=self.stats["sinyal"],
                    emir=self.stats["emir"], red=self.stats["red"], veri_hatasi=self.stats["veri_hatasi"], acik=len(self.positions), kapanan=len(tr),
                    net_usd=round(sum(pnl), 4), kazanan=len(wins), kaybeden=len(losses),
                    profit_factor=(round(sum(wins) / -sum(losses), 3) if losses and sum(losses) < 0 else None),
                    komisyon_usd=round(sum(x["fees_usd"] for x in tr), 4), durduruldu=self.risk.halted)


################################################################################
# BOT: 05_V24_ZERO
################################################################################


# --- 05_V24_ZERO/live_feeder.py ---

"""V24_ZERO canlı besleyici: Binance+OKX futures tam verisiyle 15dk sinyal testi.
CSV-only motoru gerçek piyasayla besler; emir yok, paper sinyal kaydı tutar.
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared_data import (SYMBOLS, fetch_binance_15m, fetch_okx_15m,
                         fetch_binance_derivatives, fetch_okx_derivatives,
                         derivatives_for_v24)
from acarbot.features import build_snapshot
from acarbot.strategy import ZeroStrategy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=900)
    ap.add_argument("--poll", type=int, default=60)
    ap.add_argument("--out", default="feeder_15min.jsonl")
    a = ap.parse_args()
    strat = ZeroStrategy()
    prev_oi = {}
    end = time.time() + a.duration
    tur = 0
    with open(a.out, "w", encoding="utf-8") as f:
        while time.time() < end:
            tur += 1
            for base in SYMBOLS:
                for ex, fetch_df, fetch_d in (
                    ("binance", fetch_binance_15m, fetch_binance_derivatives),
                    ("okx", fetch_okx_15m, fetch_okx_derivatives),
                ):
                    try:
                        df = fetch_df(base)
                        deriv = fetch_d(base)
                        key = (ex, base)
                        d24 = derivatives_for_v24(deriv, prev_oi.get(key))
                        if "oi" in deriv:
                            prev_oi[key] = deriv["oi"]
                        feat = build_snapshot(df, d24)
                        sig = strat.evaluate(feat)
                        rec = {"tur": tur, "exchange": ex, "symbol": base,
                               "signal": None if sig is None else
                               {"side": sig.side, "score": sig.score,
                                "confidence": sig.confidence, "reason": sig.reason},
                               "features": {k: round(float(v), 6) for k, v in feat.items()
                                            if isinstance(v, (int, float))}}
                    except Exception as e:
                        rec = {"tur": tur, "exchange": ex, "symbol": base,
                               "error": f"{type(e).__name__}: {e}"}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                    print(json.dumps(rec, ensure_ascii=False), flush=True)
            left = end - time.time()
            if left > 0:
                time.sleep(min(a.poll, left))
    print(f"BİTTİ tur={tur} kayıt={a.out}", flush=True)


if __name__ == "__main__":
    main()


################################################################################
# BOT: 06_V25_ALL_IN
################################################################################


# --- 06_V25_ALL_IN/live_feeder.py ---

"""V25_ALL_IN canlı besleyici: Binance+OKX futures tam verisiyle 15dk sinyal testi."""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared_data import (SYMBOLS, fetch_binance_15m, fetch_okx_15m,
                         fetch_binance_derivatives, fetch_okx_derivatives,
                         derivatives_for_v25)
from acarbot.features import build_snapshot
from acarbot.strategy import AllInStrategy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=900)
    ap.add_argument("--poll", type=int, default=60)
    ap.add_argument("--out", default="feeder_15min.jsonl")
    a = ap.parse_args()
    strat = AllInStrategy()
    end = time.time() + a.duration
    tur = 0
    with open(a.out, "w", encoding="utf-8") as f:
        while time.time() < end:
            tur += 1
            for base in SYMBOLS:
                for ex, fetch_df, fetch_d in (
                    ("binance", fetch_binance_15m, fetch_binance_derivatives),
                    ("okx", fetch_okx_15m, fetch_okx_derivatives),
                ):
                    try:
                        df = fetch_df(base)
                        deriv = fetch_d(base)
                        feat = build_snapshot(df, derivatives_for_v25(deriv))
                        sig = strat.decide(feat)
                        rec = {"tur": tur, "exchange": ex, "symbol": base,
                               "signal": {"side": sig.side, "score": round(sig.score, 3),
                                          "confidence": round(sig.confidence, 3),
                                          "reasons": sig.reasons, "blocked": sig.blocked},
                               "n_features": len(feat)}
                    except Exception as e:
                        rec = {"tur": tur, "exchange": ex, "symbol": base,
                               "error": f"{type(e).__name__}: {e}"}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                    print(json.dumps(rec, ensure_ascii=False), flush=True)
            left = end - time.time()
            if left > 0:
                time.sleep(min(a.poll, left))
    print(f"BİTTİ tur={tur} kayıt={a.out}", flush=True)


if __name__ == "__main__":
    main()


################################################################################
# BOT: 07_V27_SUPER
################################################################################


# --- 07_V27_SUPER/live_feeder.py ---

"""V27_SUPER canlı besleyici: Binance+OKX futures 15m verisiyle 15dk sinyal testi.
V27 OHLCV motorudur; türev veriler loglanır ama motora uydurulmaz (tasarım gereği).
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared_data import (SYMBOLS, fetch_binance_15m, fetch_okx_15m,
                         fetch_binance_derivatives, fetch_okx_derivatives)
from acarbot.core import SignalEngine, Config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=900)
    ap.add_argument("--poll", type=int, default=60)
    ap.add_argument("--out", default="feeder_15min.jsonl")
    a = ap.parse_args()
    eng = SignalEngine(Config())
    end = time.time() + a.duration
    tur = 0
    with open(a.out, "w", encoding="utf-8") as f:
        while time.time() < end:
            tur += 1
            for base in SYMBOLS:
                for ex, fetch_df, fetch_d in (
                    ("binance", fetch_binance_15m, fetch_binance_derivatives),
                    ("okx", fetch_okx_15m, fetch_okx_derivatives),
                ):
                    try:
                        df = fetch_df(base)
                        deriv = fetch_d(base)
                        sig = eng.evaluate(df)
                        # Debug: sinyal yoksa hangi kapı engelledi? (skor/destek/rejim)
                        dbg = {}
                        if sig is None:
                            try:
                                from acarbot.core import features as _feat
                                import numpy as np
                                x = _feat(df, eng.c).iloc[-1]
                                dbg = {"adx": round(float(x.adx), 1), "rsi": round(float(x.rsi_wilder), 1),
                                       "natr": round(float(x.natr), 4), "range": round(float(x.range), 4),
                                       "close": round(float(x.close), 4)}
                            except Exception:
                                pass
                        rec = {"tur": tur, "exchange": ex, "symbol": base,
                               "signal": None if sig is None else
                               {"side": sig.side, "score": round(sig.score, 1),
                                "confidence": round(sig.confidence, 3),
                                "reason": sig.reason, "regime": sig.regime},
                               "debug": dbg,
                               "derivatives": {k: round(float(v), 8) for k, v in deriv.items()}}
                    except Exception as e:
                        rec = {"tur": tur, "exchange": ex, "symbol": base,
                               "error": f"{type(e).__name__}: {e}"}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                    print(json.dumps(rec, ensure_ascii=False), flush=True)
            left = end - time.time()
            if left > 0:
                time.sleep(min(a.poll, left))
    print(f"BİTTİ tur={tur} kayıt={a.out}", flush=True)


if __name__ == "__main__":
    main()


################################################################################
# BOT: 08_V28_SINGLE
################################################################################


# --- 08_V28_SINGLE/ACARBOT_V28.py ---

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ACARBOT V28 FUSION — 6 botun en iyi parcalarindan insa edildi
==============================================================
Kaynak botlar ve alinan parcalar:
  V23          -> paper motoru, risk kurallari, Binance 451 -> www yedek rotasi, kayit disiplini
  V24_ZERO     -> 15m/1h/4h coklu zaman dilimi teyidi, puanlama + cooldown fikri
  V25_ALL_IN   -> genis indikator ailesi (trend/momentum/volatilite/hacim)
  V26_FUSION   -> grup bazli skor (korelasyon azaltma), RSI Wilder, soft veto
  V27_SUPER    -> veto zinciri disiplini (yetersiz teyit = sinyal yok)
  ZERO         -> veri kalitesi kapisi + 2 tarama teyidi (kusurlari giderildi:
                  borsa hatasi yalitimi, OKX hacim olcumu duzeltmesi)

SABIT KURALLAR: 1000$ kasa - islem basina 50$ teminat - sabit 10x - maker
(post-only) giris - sinirsiz islem (tek sinir serbest teminat) - Binance + OKX.
MOD: sinyal + paper. Canli emir YOK (kanit kapisi: hicbir strateji henuz
dokunulmamis donemde kar kanitlamadi; once paper yarisi).

Komutlar:
  python ACARBOT_V28.py ozet
  python ACARBOT_V28.py tara                 tek tarama, skorlu sinyal listesi
  python ACARBOT_V28.py paper --sure 900     15 dk paper (varsayilan sure 900)
  python ACARBOT_V28.py durum                acik paper pozisyonlar + ozet
  python ACARBOT_V28.py yaris                setup bazinda paper performansi
"""
import argparse, json, math, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------- SABIT KURALLAR ----------
KASA, TEMINAT, KALDIRAC = 1000.0, 50.0, 10
NOMINAL = TEMINAT * KALDIRAC
MAKER_FEE, TAKER_FEE = 0.0002, 0.0005
GUNLUK_ZARAR_LIMIT, MAX_DD = 150.0, 400.0
SKOR_ESIK = 70
DIZIN = Path("v28_kayit")

def http_json(url, timeout=20):
    r = urllib.request.Request(url, headers={"User-Agent": "ACARBOT-V28/1.0"})
    with urllib.request.urlopen(r, timeout=timeout) as x:
        return json.loads(x.read().decode())

def iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------- BORSALAR (sadece public veri; hata yalitimi: biri cokerse digeri devam) ----------
class Binance:
    AD, KOK = "binance", "https://www.binance.com/fapi/v1"
    def tikler(self):
        return [dict(sembol=t["symbol"], son=float(t["lastPrice"]), deg24=float(t["priceChangePercent"]) / 100,
                     hacim24=float(t["quoteVolume"]))
                for t in http_json(f"{self.KOK}/ticker/24hr")
                if t["symbol"].endswith("USDT") and not any(x in t["symbol"] for x in ("UPUSDT", "DOWNUSDT", "BULL", "BEAR"))]
    def mum(self, s, aralik, limit):
        h = http_json(f"{self.KOK}/klines?symbol={s}&interval={aralik}&limit={limit}")
        return [dict(o=float(x[1]), h=float(x[2]), l=float(x[3]), c=float(x[4]), qv=float(x[7])) for x in h]
    def funding(self):
        return {x["symbol"]: float(x["lastFundingRate"]) for x in http_json(f"{self.KOK}/premiumIndex")}

class Okx:
    AD, KOK = "okx", "https://www.okx.com/api/v5"
    def tikler(self):
        cikti = []
        for t in http_json(f"{self.KOK}/market/tickers?instType=SWAP")["data"]:
            if not t["instId"].endswith("-USDT-SWAP"): continue
            son, acik = float(t["last"]), float(t["open24h"])
            # OKX hacmi: volCcy24h (USDT degeri) — ZERO'daki olcum uyumsuzlugu burada duzgun birimle alinir
            cikti.append(dict(sembol=t["instId"], son=son, deg24=(son / acik - 1) if acik else 0.0,
                              hacim24=float(t["volCcy24h"])))
        return cikti
    def mum(self, s, aralik, limit):
        h = http_json(f"{self.KOK}/market/candles?instId={s}&bar={aralik}&limit={limit}")["data"]
        return [dict(o=float(x[1]), h=float(x[2]), l=float(x[3]), c=float(x[4]), qv=float(x[5]) * float(x[4]))
                for x in reversed(h)]
    def funding(self, s):
        try:
            d = http_json(f"{self.KOK}/public/funding-rate?instId={s}")["data"]
            return float(d[0]["fundingRate"]) if d else None
        except Exception:
            return None

BORSALAR = {"binance": Binance, "okx": Okx}

# ---------- INDIKATORLER (V25/V26 ailesi, sade ve hizli) ----------
def ema(d, n):
    if len(d) < n: return None
    k, e = 2 / (n + 1), sum(d[:n]) / n
    for x in d[n:]: e = x * k + e * (1 - k)
    return e

def rsi_wilder(kapanis, n=14):
    if len(kapanis) < n + 2: return None
    kaz, kay = [], []
    for i in range(1, len(kapanis)):
        f = kapanis[i] - kapanis[i - 1]; kaz.append(max(f, 0)); kay.append(max(-f, 0))
    ak, ay = sum(kaz[:n]) / n, sum(kay[:n]) / n
    for i in range(n, len(kaz)):
        ak = (ak * (n - 1) + kaz[i]) / n; ay = (ay * (n - 1) + kay[i]) / n
    return 100.0 if ay == 0 else 100 - 100 / (1 + ak / ay)

def atr(mumlar, n=14):
    if len(mumlar) < n + 1: return None
    trler = [max(m["h"] - m["l"], abs(m["h"] - mumlar[i - 1]["c"]), abs(m["l"] - mumlar[i - 1]["c"]))
             for i, m in enumerate(mumlar) if i > 0]
    a = sum(trler[:n]) / n
    for t in trler[n:]: a = (a * (n - 1) + t) / n
    return a

def macd_hist(kapanis):
    def seri(d, n):
        k, e, out = 2 / (n + 1), d[0], []
        for x in d: e = x * k + e * (1 - k); out.append(e)
        return out
    if len(kapanis) < 40: return None
    hizli, yavas = seri(kapanis, 12), seri(kapanis, 26)
    fark = [a - b for a, b in zip(hizli, yavas)]
    sinyal = seri(fark, 9)
    return fark[-1] - sinyal[-1]

# ---------- OZELLIK + SKOR (V26 grup skorlamasi; V27 veto disiplini) ----------
def ozellikler(m15, m1h, m4h, funding):
    if len(m15) < 60 or len(m1h) < 60 or len(m4h) < 30: return None
    c15 = [m["c"] for m in m15[:-1]]; c1 = [m["c"] for m in m1h[:-1]]; c4 = [m["c"] for m in m4h[:-1]]
    qv1 = [m["qv"] for m in m1h[:-1]]
    son, onceki = qv1[-1], qv1[-169:-1] if len(qv1) >= 169 else qv1[:-1]
    ort = sum(onceki) / len(onceki) if onceki else 0
    return dict(
        son=m15[-1]["c"], r1h=c1[-1] / c1[-2] - 1, r15=c15[-1] / c15[-2] - 1,
        vs=son / ort if ort > 0 else 0, lik=ort * 24,
        trend1h=(ema(c1, 20) or 0) > (ema(c1, 50) or 1e18), trend4h=(ema(c4, 20) or 0) > (ema(c4, 50) or 1e18),
        rsi15=rsi_wilder(c15), rsi1h=rsi_wilder(c1), macd=macd_hist(c1),
        atr_oran=(atr(m1h) or 0) / c1[-1] if c1[-1] else 0,
        donch_ust=max(m["h"] for m in m1h[-21:-1]), donch_alt=min(m["l"] for m in m1h[-21:-1]),
        funding=funding)

def skorla(f):
    """Uc kurulum degerlendirilir; grup tavanlari tekrar sayimi engeller. Donus: [(skor, yon, kurulum, sebepler)]"""
    adaylar = []
    # --- LONG trend/momentum (V24+V25) ---
    puan, sebepler = 0, []
    if f["trend4h"]: puan += 15; sebepler.append("4h trend yukari")
    if f["trend1h"]: puan += 10; sebepler.append("1h trend yukari")
    if f["rsi1h"] and 50 <= f["rsi1h"] <= 70: puan += 12; sebepler.append(f"RSI1h {f['rsi1h']:.0f} saglikli bolge")
    if f["macd"] and f["macd"] > 0: puan += 10; sebepler.append("MACD pozitif")
    if f["son"] > f["donch_ust"]: puan += 15; sebepler.append("Donchian kirilimi")
    if f["vs"] >= 5: puan += min(13, f["vs"]); sebepler.append(f"hacim {f['vs']:.0f}x")
    if puan: adaylar.append((puan, +1, "trend_long", sebepler))
    # --- SHORT pump-fade (guclendirilmis pump_short; arsivin en guclu adayi) ---
    if f["vs"] >= 30 and f["r1h"] >= 0.05 and f["lik"] >= 2_000_000:
        puan = 55 + min(25, (f["vs"] - 30) / 4 + (f["r1h"] - 0.05) * 200)
        sebepler = [f"pump-fade: hacim {f['vs']:.0f}x, 1s +{f['r1h']*100:.1f}%"]
        if f["rsi1h"] and f["rsi1h"] > 75: puan += 8; sebepler.append(f"RSI1h {f['rsi1h']:.0f} asiri alim")
        if f["funding"] is not None and f["funding"] < -0.001: puan -= 15; sebepler.append("funding ters (short kalabalik)")
        adaylar.append((puan, -1, "pump_fade_short", sebepler))
    # --- LONG dip-bounce (ZERO/V27 teyit disipliniyle) ---
    if f["r1h"] <= -0.05 and f["vs"] >= 5 and f["lik"] >= 2_000_000 and f["trend4h"]:
        puan = 45 + min(20, (-f["r1h"] - 0.05) * 200 + f["vs"] / 2)
        adaylar.append((puan, +1, "dip_long", [f"dususte hacim {f['vs']:.0f}x, 1s {f['r1h']*100:.1f}%, 4h trend hala yukari"]))
    # --- funding teyidi (butun kurulumlara +/-) ---
    fr = f["funding"]
    duzeltilmis = []
    for puan, yon, kurulum, sebepler in adaylar:
        if fr is not None and abs(fr) >= 0.0005:
            if (fr > 0) == (yon < 0): puan += 6; sebepler = sebepler + ["funding teyidi +"]
            else: puan -= 6; sebepler = sebepler + ["funding karsi -"]
        duzeltilmis.append((round(puan), yon, kurulum, sebepler))
    return sorted(duzeltilmis, reverse=True)

# ---------- TARAMA ----------
def tara(borsa_adi, aday_sayisi=25, funding_haritasi=None):
    api = BORSALAR[borsa_adi]()
    tikler = [t for t in api.tikler() if t["hacim24"] >= 1_000_000]
    tikler.sort(key=lambda t: t["hacim24"] * (0.2 + abs(t["deg24"])), reverse=True)
    if funding_haritasi is None and borsa_adi == "binance":
        try: funding_haritasi = api.funding()
        except Exception: funding_haritasi = {}
    cikti, hatalar = [], 0
    for tik in tikler[:aday_sayisi]:
        try:
            m15 = api.mum(tik["sembol"], "15m", 120)
            m1h = api.mum(tik["sembol"], "1h", 220)
            m4h = api.mum(tik["sembol"], "4h", 80)
            fr = (funding_haritasi or {}).get(tik["sembol"]) if borsa_adi == "binance" else api.funding(tik["sembol"])
        except Exception:
            hatalar += 1; continue
        f = ozellikler(m15, m1h, m4h, fr)
        if not f: continue
        for puan, yon, kurulum, sebepler in skorla(f):
            if puan >= SKOR_ESIK:
                stop_oran = min(0.065, max(0.03, 1.8 * f["atr_oran"]))
                giris = f["son"]
                cikti.append(dict(zaman=iso(), borsa=borsa_adi, sembol=tik["sembol"],
                                  yon="LONG" if yon > 0 else "SHORT", kurulum=kurulum, skor=puan,
                                  sebepler=sebepler, maker_limit=round(giris, 8),
                                  stop_fiyat=round(giris * (1 - stop_oran) if yon > 0 else giris * (1 + stop_oran), 8),
                                  stop_oran=round(stop_oran, 4),
                                  teminat=TEMINAT, kaldirac=KALDIRAC, nominal=NOMINAL,
                                  ozellikler=dict(vs=round(f["vs"], 1), r1h=round(f["r1h"], 4),
                                                  lik=round(f["lik"]), rsi1h=round(f["rsi1h"], 1) if f["rsi1h"] else None,
                                                  funding=fr)))
    return sorted(cikti, key=lambda s: -s["skor"]), hatalar

# ---------- PAPER MOTORU (V23 disiplini + ZERO 2-teyit) ----------
class Paper:
    def __init__(self):
        DIZIN.mkdir(exist_ok=True)
        self.durum_yol, self.gunluk_yol = DIZIN / "durum.json", DIZIN / "olaylar.jsonl"
        d = json.loads(self.durum_yol.read_text(encoding="utf-8")) if self.durum_yol.exists() else {}
        self.pozisyonlar = d.get("pozisyonlar", [])
        self.teyit_bekleyen = d.get("teyit", {})
        self.gerceklesen = d.get("gerceklesen", 0.0)
        self.tepe = d.get("tepe", 0.0)
        self.bekleyen_emirler = d.get("emirler", [])
        self.kapanan_say = d.get("kapanan", 0)
    def kaydet(self):
        self.durum_yol.write_text(json.dumps(dict(pozisyonlar=self.pozisyonlar, teyit=self.teyit_bekleyen,
            gerceklesen=self.gerceklesen, tepe=self.tepe, emirler=self.bekleyen_emirler,
            kapanan=self.kapanan_say), ensure_ascii=False, indent=1), encoding="utf-8")
    def olay(self, o):
        with open(self.gunluk_yol, "a", encoding="utf-8") as f:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    def acik_mi(self, sembol_baz):
        return any(p["baz"] == sembol_baz for p in self.pozisyonlar) or \
               any(e["baz"] == sembol_baz for e in self.bekleyen_emirler)
    def teyit_et_ve_emir(self, sinyal):
        """2 tarama teyidi: ayni kurulum+yön iki ardışık taramada görülmeden emir yok (ZERO fikri)."""
        anahtar = f"{sinyal['sembol']}|{sinyal['yon']}|{sinyal['kurulum']}"
        baz = sinyal["sembol"].replace("-USDT-SWAP", "").replace("USDT", "")
        if self.acik_mi(baz): return "zaten_acik"
        if anahtar not in self.teyit_bekleyen:
            self.teyit_bekleyen[anahtar] = sinyal; return "teyit_bekliyor"
        self.bekleyen_emirler.append(dict(sinyal, baz=baz, durum="EMIR", olusma=time.time()))
        del self.teyit_bekleyen[anahtar]
        self.olay(dict(olay="EMIR", **sinyal)); return "emir_verildi"
    def yonet(self, fiyatlar):
        simdi = time.time()
        for e in list(self.bekleyen_emirler):
            f = fiyatlar.get(e["sembol"])
            if f is None: continue
            doldu = (f <= e["maker_limit"]) if e["yon"] == "LONG" else (f >= e["maker_limit"])
            if doldu:
                self.pozisyonlar.append(dict(e, giris=e["maker_limit"], giris_zaman=simdi, durum="ACIK"))
                self.bekleyen_emirler.remove(e); self.olay(dict(olay="DOLUM", sembol=e["sembol"], yon=e["yon"], giris=e["maker_limit"]))
            elif simdi - e["olusma"] > 3600:
                self.bekleyen_emirler.remove(e); self.olay(dict(olay="EMIR_IPTAL", sembol=e["sembol"]))
        for p in list(self.pozisyonlar):
            f = fiyatlar.get(p["sembol"])
            if f is None: continue
            yon = 1 if p["yon"] == "LONG" else -1
            sebep = None
            if (yon > 0 and f <= p["stop_fiyat"]) or (yon < 0 and f >= p["stop_fiyat"]): sebep = "STOP"
            elif simdi - p["giris_zaman"] > 24 * 3600: sebep = "SURE"
            if sebep:
                pnl = yon * (f / p["giris"] - 1) * NOMINAL - NOMINAL * (MAKER_FEE + TAKER_FEE)
                self.gerceklesen += pnl; self.kapanan_say += 1
                self.tepe = max(self.tepe, self.gerceklesen)
                self.pozisyonlar.remove(p)
                self.olay(dict(olay="KAPANIS", sembol=p["sembol"], yon=p["yon"], kurulum=p["kurulum"],
                               cikis=f, pnl=round(pnl, 2), sebep=sebep))
    def ozet(self):
        return dict(acik_pozisyon=len(self.pozisyonlar), bekleyen_emir=len(self.bekleyen_emirler),
                    teyit_bekleyen=len(self.teyit_bekleyen), kapanan=self.kapanan_say,
                    gerceklesen_pnl=round(self.gerceklesen, 2),
                    kalici_durdurma=(self.tepe - self.gerceklesen) >= MAX_DD)

def fiyat_haritasi():
    harita = {}
    for ad, sinif in BORSALAR.items():
        try:
            for t in sinif().tikler(): harita[t["sembol"]] = t["son"]
        except Exception as e:
            print(f"[{ad}] fiyat alinamadi (yalitimli hata): {e}", file=sys.stderr)
    return harita

# ---------- KOMUTLAR ----------
def ozet_yazdir():
    print("ACARBOT V28 FUSION — 6 botun fuzyonu (V23+V24+V25+V26+V27+ZERO)")
    print(f"Sabit kurallar: kasa {KASA:.0f}$ | teminat {TEMINAT:.0f}$/islem | {KALDIRAC}x | maker giris | sinirsiz islem")
    print(f"Skor esigi: {SKOR_ESIK}/100 + 2 tarama teyidi | Stop: ATR tabanli %3-6.5 | Gunluk zarar limiti {GUNLUK_ZARAR_LIMIT:.0f}$")
    print("Mod: SINYAL + PAPER (canli emir yok — kanit kapisi)")
    print("Kurulumlar: trend_long (V24/V25) | pump_fade_short (V23 adayi, guclendirilmis) | dip_long (ZERO teyitli)")

def main(argv=None):
    ap = argparse.ArgumentParser(prog="ACARBOT_V28")
    ap.add_argument("komut", choices=["ozet", "tara", "paper", "durum", "yaris"])
    ap.add_argument("--sure", type=int, default=900)
    ap.add_argument("--aday", type=int, default=25)
    ap.add_argument("--dongu", type=int, default=60, help="paper tarama araligi (sn)")
    a = ap.parse_args(argv)
    if a.komut == "ozet": ozet_yazdir(); return 0
    if a.komut == "durum":
        print(json.dumps(Paper().ozet(), ensure_ascii=False, indent=1)); return 0
    if a.komut == "yaris":
        if not (DIZIN / "olaylar.jsonl").exists(): print("Kayit yok; once paper calistirin."); return 0
        from collections import defaultdict
        ist = defaultdict(lambda: [0, 0.0])
        for s in (DIZIN / "olaylar.jsonl").read_text(encoding="utf-8").splitlines():
            o = json.loads(s)
            if o.get("olay") == "KAPANIS": ist[o["kurulum"]][0] += 1; ist[o["kurulum"]][1] += o["pnl"]

################################################################################
# BOT: 09_V28_FINAL
################################################################################


# --- 09_V28_FINAL/acarbot/signal.py ---

"""ANSAMBL SİNYAL MOTORU — V26/V27 grup yaklaşımı + ZERO dersleri.
Gruplar [-1,1] normalize edilir; gruplar arası EŞİT ağırlık kullanılır (V26: indikatör sayısı yanlılığı yok).
- trend: EMA dizilimi + ADX/DMI rejimi (+ supertrend)
- momentum: Wilder RSI (varsayılan) + MACD histogram + ROC + stokastik
- breakout: Donchian/BB/VWAP kırılımı + hacim onayı (V27)
- volume_flow: hacim şoku + CMF + MFI + OBV eğimi (V26)
- derivatives / microstructure: YALNIZ kolonlar gerçekten verilmişse (uydurma yok, V26/V27)
Rejim (ADX) ağırlıkları değiştirir (V27). RSI aşırılığı sert veto DEĞİL yumuşak cezadır (V26).
STOP: ATR×2.2, [0.012, 0.045] kelepçe (V24) + izole tasfiye güvenliği (V23).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .config import Settings
from .features import feature_frame

EPS = 1e-12


@dataclass
class EnsembleResult:
    side: int                       # 1 / -1 / 0 (FLAT)
    score: float                    # grup ortalaması [-1,1]
    confidence: float               # [0,1]
    stop_frac: float
    regime: str                     # trend | range
    reason: str
    groups: dict = field(default_factory=dict)
    blocked: str = ""               # sinyal üretilmediyse gerekçe


def _last(x) -> float:
    try:
        v = float(x.iloc[-1])
    except Exception:
        return float("nan")
    return v


def _at(x, idx: int) -> float:
    """Satır idx'teki değer (backtest O(n): dilim yok, nedensel göstergelerde eşdeğerdir)."""
    try:
        v = float(x.iloc[idx])
    except Exception:
        return float("nan")
    return v


def _clip01(x: float) -> float:
    if not np.isfinite(x): return 0.0
    return float(max(-1.0, min(1.0, x)))


class EnsembleEngine:
    def __init__(self, cfg: Settings):
        self.cfg = cfg

    # ------------------------------------------------------------------ grup puanları
    def _group_trend(self, f: pd.DataFrame, idx: int = -1) -> float:
        e20, e50, e200 = _at(f.ema_20, idx), _at(f.ema_50, idx), _at(f.ema_200, idx)
        if not (np.isfinite(e20) and np.isfinite(e50) and np.isfinite(e200)): return 0.0
        t = 0.4 * np.sign(e20 - e50) + 0.3 * np.sign(e50 - e200)
        adx, pdi, mdi = _at(f.adx, idx), _at(f.plus_di, idx), _at(f.minus_di, idx)
        if np.isfinite(adx) and adx >= self.cfg.adx_min:
            t += 0.3 * np.sign(pdi - mdi)
        return _clip01(t / 1.0)

    def _group_momentum(self, f: pd.DataFrame, idx: int = -1) -> float:
        if self.cfg.rsi_mode == "wilder":
            rsi = _at(f.rsi_wilder, idx)
        elif self.cfg.rsi_mode == "sma":
            rsi = _at(f.rsi_sma, idx)
        else:
            rsi = 50.0
        mom = 0.45 * _clip01((rsi - 50.0) / 20.0) if np.isfinite(rsi) else 0.0
        mh = _at(f.macd_hist, idx)
        mom += 0.25 * (np.sign(mh) if np.isfinite(mh) else 0.0)
        roc = _at(f.roc_12, idx)
        mom += 0.15 * _clip01(roc / 5.0) if np.isfinite(roc) else 0.0
        sk = _at(f.stoch_k, idx)
        mom += 0.15 * _clip01((sk - 50.0) / 30.0) if np.isfinite(sk) else 0.0
        return _clip01(mom)

    def _group_breakout(self, f: pd.DataFrame, idx: int = -1) -> float:
        c, dcu, dcl = _at(f.close, idx), _at(f.dc_up, idx), _at(f.dc_low, idx)
        bbu, bbl, vw, vr = _at(f.bb_up, idx), _at(f.bb_low, idx), _at(f.vwap, idx), _at(f.vol_ratio, idx)
        if not np.isfinite(c): return 0.0
        parts = []
        if np.isfinite(dcu) and dcu > 0: parts.append(_clip01((c / dcu - 1.0) / 0.01))
        if np.isfinite(dcl) and dcl > 0: parts.append(_clip01((c / dcl - 1.0) / 0.01))
        if np.isfinite(bbu) and bbu > 0: parts.append(_clip01((c / bbu - 1.0) / 0.01))
        if np.isfinite(bbl) and bbl > 0: parts.append(_clip01((c / bbl - 1.0) / 0.01))
        if np.isfinite(vw) and vw > 0: parts.append(_clip01((c / vw - 1.0) / 0.01))
        if not parts: return 0.0
        s = float(np.mean(parts))
        # hacim onayı: vol_ratio < 1.0 ise kırılım güvenilirliği düşer (V27 breakout+volume dersi)
        if np.isfinite(vr) and vr < 1.0:
            s *= 0.7
        return _clip01(s)

    def _group_volume_flow(self, f: pd.DataFrame, idx: int = -1) -> float:
        vz, cmfv, mfi = _at(f.vol_z, idx), _at(f.cmf, idx), _at(f.mfi, idx)
        vf = 0.45 * _clip01(vz / 3.0) if np.isfinite(vz) else 0.0
        vf += 0.25 * _clip01(cmfv * 4.0) if np.isfinite(cmfv) else 0.0
        vf += 0.20 * _clip01((mfi - 50.0) / 25.0) if np.isfinite(mfi) else 0.0
        obv = f.obv
        if idx >= 5 or (idx == -1 and len(obv) >= 6):
            o_now, o_then = _at(obv, idx), _at(obv, idx - 5 if idx != -1 else -6)
            vf += 0.10 * (np.sign(o_now - o_then) if np.isfinite(o_now) and np.isfinite(o_then) else 0.0)
        return _clip01(vf)

    def _group_fade(self, f: pd.DataFrame, idx: int = -1) -> float:
        """FADE TERSİNE ÇEVİRME (yeni): pump sonrası fade -> SHORT, dump sonrası bounce -> LONG.

        KGEN örneği: 0.082 -> 0.103 (pump +%9.73) -> 0.090 (fade -%12.7).
        V23 doğru SHORT sinyalini verdi ama maker emir dolmadı.
        V28 yanlış LONG'a girdi (tepe).
        Bu grup: güçlü pump + momentum dönüşü = fade başlangıcı -> ters yön sinyali.
        """
        try:
            c = _at(f.close, idx)
            # Son 4 bar (1 saat) getirisi: pump/dump tespiti
            c_4ago = _at(f.close, idx - 4 if idx != -1 else -5)
            if not (np.isfinite(c) and np.isfinite(c_4ago) and c_4ago > 0):
                return 0.0
            ret_1h = c / c_4ago - 1.0
            # Momentum dönüşü: macd_hist işareti veya stoch dönüşü
            mh = _at(f.macd_hist, idx) if "macd_hist" in f.columns else 0.0
            mh_prev = _at(f.macd_hist, idx - 2 if idx != -1 else -3) if "macd_hist" in f.columns else 0.0
            fade = 0.0
            # Pump sonrası fade: ret_1h güçlü pozitif ama momentum düşüyor
            if ret_1h >= 0.04 and np.isfinite(mh) and np.isfinite(mh_prev) and mh < mh_prev:
                fade = -min(1.0, (ret_1h - 0.04) * 10 + 0.3)  # SHORT sinyali
            # Dump sonrası bounce: ret_1h güçlü negatif ama momentum yükseliyor
            elif ret_1h <= -0.04 and np.isfinite(mh) and np.isfinite(mh_prev) and mh > mh_prev:
                fade = min(1.0, (-ret_1h - 0.04) * 10 + 0.3)  # LONG sinyali
            return _clip01(fade)
        except Exception:
            return 0.0

    def _group_derivatives(self, f: pd.DataFrame, idx: int = -1) -> float:
        """Yalnız sağlanan kolonlar. funding: pozitif funding long için maliyet -> ters işaret (V26)."""
        der, norm = 0.0, 0.0
        for col, w in (("oi_delta_pct", 0.35), ("oi_z", 0.15), ("funding", -0.15),
                       ("basis_pct", 0.15), ("liquidation_delta", 0.20)):
            if col in f.columns:
                x = _at(f[col], idx)
                if np.isfinite(x):
                    der += w * _clip01(x)
                    norm += abs(w)
        return _clip01(der / norm) if norm > 0 else 0.0

    def _group_microstructure(self, f: pd.DataFrame, idx: int = -1) -> float:
        micro, norm = 0.0, 0.0
        for col, w in (("cvd_slope", 0.45), ("taker_imbalance", 0.25), ("orderbook_imbalance", 0.30)):
            if col in f.columns:
                x = _at(f[col], idx)
                if np.isfinite(x):
                    micro += w * _clip01(x)
                    norm += abs(w)
        if "spread_bps" in f.columns:
            sp = _at(f["spread_bps"], idx)
            if np.isfinite(sp) and sp > 15 and norm > 0:
                micro *= 0.6     # geniş spread: mikroyapı güvenilirliği düşer (ZERO spread kapısı)
        return _clip01(micro / norm) if norm > 0 else 0.0

    # ------------------------------------------------------------------ değerlendirme
    def evaluate(self, df: pd.DataFrame, htf: Optional[dict] = None) -> EnsembleResult:
        """df: HAM OHLCV (taban zaman dilimi). htf: {'1h': ohlcv_df, ...} (opsiyonel onay, V26)."""
        f = feature_frame(df)
        return self._evaluate_frame(f, htf)

    def _evaluate_frame(self, f: pd.DataFrame, htf: Optional[dict] = None, idx: int = -1) -> EnsembleResult:
        """f: feature_frame çıktısı. idx: değerlendirilecek satır (backtest'te i; nedensel göstergeler
        nedeniyle f.iloc[:i+1] dilimiyle birebir eşdeğerdir ama O(1)'dir)."""
        cfg = self.cfg
        n_avail = len(f) if idx == -1 else idx + 1
        if n_avail < 260:
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "veri_yetersiz")
        c, natr, rng = _at(f.close, idx), _at(f.natr, idx), _at(f.range_frac, idx)
        if not np.isfinite(c) or c <= 0:
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "fiyat_gecersiz")
        atrv = _at(f.atr, idx)
        if not np.isfinite(atrv) or atrv <= 0:
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "atr_yok")
        # volatilite sağduyu kapısı (V27): aşırı sakin/pahalı piyasa sinyal üretmez
        if not (cfg.min_natr <= natr <= cfg.max_natr) or (np.isfinite(rng) and rng > 0.18):
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "volatilite_kapisi")

        groups = {
            "trend": self._group_trend(f, idx),
            "momentum": self._group_momentum(f, idx),
            "breakout": self._group_breakout(f, idx),
            "volume_flow": self._group_volume_flow(f, idx),
        }
        # FADE TERSİNE ÇEVİRME: pump/dump sonrası dönüş -> ters yön.
        # Güçlü fade sinyali varsa skoru ters yöne çevir (V23 pump_short mantığı).
        fade = self._group_fade(f, idx)
        if abs(fade) >= 0.3:
            groups["fade"] = fade
        deriv = self._group_derivatives(f, idx)
        micro = self._group_microstructure(f, idx)
        core = list(groups.values())
        score = float(np.mean(core))                     # çekirdek gruplar eşit ağırlıkta
        coverage = 0.0
        if deriv != 0.0:
            groups["derivatives"] = deriv
            core.append(deriv)
            coverage += 0.5
        if micro != 0.0:
            groups["microstructure"] = micro
            core.append(micro)
            coverage += 0.5
        score = float(np.mean(core))

        # HTF onayı: taban 0.8 + onay 0.2 (V26), onay = EMA20/50 yönü ortalaması
        htf_note = ""
        if htf:
            hs = []
            for tf, hf in htf.items():   # htf değerleri HAZIR feature frame olabilir (backtest) veya ham OHLCV
                try:
                    hf2 = hf if ("ema_20" in getattr(hf, "columns", [])) else feature_frame(hf)
                    h20, h50 = _last(hf2.ema_20), _last(hf2.ema_50)   # HTF: son bar onayı
                    if np.isfinite(h20) and np.isfinite(h50):
                        hs.append(np.sign(h20 - h50))
                        htf_note = f"+htf({','.join(htf.keys())})"
                except Exception:
                    continue
            if hs:
                score = 0.8 * score + 0.2 * float(np.mean(hs))

        # çatışma cezası (ZERO ders 3): trend ile momentum güçlü ve ters yönlüyse puan düşer
        conflict = groups["trend"] * groups["momentum"] < 0 and abs(groups["trend"]) > 0.2 and abs(groups["momentum"]) > 0.2
        if conflict:
            score *= cfg.conflict_penalty

        # RSI yumuşak cezası (V26; sert veto kaldırıldı)
        rsi = _at(f.rsi_wilder if cfg.rsi_mode == "wilder" else f.rsi_sma, idx) if cfg.rsi_mode != "off" else 50.0
        rsi_note = ""
        if np.isfinite(rsi):
            if score > 0 and rsi > cfg.rsi_soft_zone:
                score -= cfg.rsi_soft_penalty
                rsi_note = f"-rsi{rsi:.0f}"
            elif score < 0 and rsi < 100 - cfg.rsi_soft_zone:
                score += cfg.rsi_soft_penalty
                rsi_note = f"+rsi{rsi:.0f}"
        # İYİLEŞTİRME: pump-tepe filtresi — aşırı alım/satımda ters yön engelle
        rsi_blocked = ""
        if np.isfinite(rsi):
            if score > 0 and rsi > cfg.rsi_long_block:
                rsi_blocked = f"rsi_asiri_alim({rsi:.0f})"
            elif score < 0 and rsi < cfg.rsi_short_block:
                rsi_blocked = f"rsi_asiri_satim({rsi:.0f})"

        adx = _at(f.adx, idx)
        regime = "trend" if (np.isfinite(adx) and adx >= cfg.adx_min) else "range"

        # destek: aynı yönde anlamlı katkı veren grup sayısı (V27 'support' dersi)
        side = 1 if score > 0 else (-1 if score < 0 else 0)
        support = sum(1 for g in core if g * side > 0 and abs(g) >= 0.15) if side != 0 else 0
        agreement = abs(float(np.mean(np.sign(core)))) if core else 0.0
        confidence = float(np.clip(0.45 + 0.35 * agreement + 0.20 * coverage, 0.0, 1.0))

        stop_frac = self._stop_frac(atrv, c)
        reason = (f"trend={groups['trend']:+.2f} mom={groups['momentum']:+.2f} brk={groups['breakout']:+.2f} "
                  f"flow={groups['volume_flow']:+.2f} adx={adx:.0f} rsi={rsi:.0f} {regime}{htf_note}{rsi_note}")
        blocked = ""
        if abs(score) < cfg.min_score:
            blocked = "skor_esik_alti"
        elif support < cfg.min_support:
            blocked = f"grup_destegi_yetersiz({support})"
        elif confidence < cfg.min_confidence:
            blocked = "guven_dusuk"
        # İYİLEŞTİRME: momentum/flow teyidi — trend tek başına yetmez.
        # Kayıp analizi: AGT (flow=0.00), KGEN (mom=+0.10) bu kapıda elenirdi.
        elif groups["momentum"] * side < cfg.min_momentum:
            blocked = "momentum_teyitsiz"
        elif groups["volume_flow"] * side < cfg.min_flow:
            blocked = "flow_teyitsiz"
        # İYİLEŞTİRME: pump-tepe filtresi — RSI aşırı bölgede ters yön engelle
        elif rsi_blocked:
            blocked = rsi_blocked
        if blocked:
            side = 0
        return EnsembleResult(side, float(score), confidence, stop_frac, regime, reason, groups, blocked)

    def _stop_frac(self, atrv: float, price: float) -> float:
        """ATR'ye uyarlanan stop, sıkı kelepçeli (V24) ve tasfiyeye güvenli (V23)."""
        natr = atrv / (price + EPS)
        stop = self.cfg.stop_atr_mult * natr
        stop = max(self.cfg.stop_min_frac, min(self.cfg.stop_max_frac, stop))
        safe = self.cfg.max_safe_stop()
        return min(stop, safe)

    # ------------------------------------------------------------------ Signal üretimi (canlı tarama için)

# --- 09_V28_FINAL/acarbot/config.py ---

"""ACARBOT V28 FINAL — ayarlar.
Kullanıcının SABİT kuralları varsayılandır: 1000$ kasa, işlem başına 50$ teminat, sabit 10x,
maker (post-only) giriş, izole marj. Diğer tüm parametreler .env ile değiştirilebilir (ACARBOT_ öneki).
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    # --- sabit kurallar (kullanıcı) ---
    equity_usd: float = 1000.0
    margin_usd: float = 50.0
    leverage: int = 10
    margin_mode: str = "isolated"
    max_positions: int = 0              # 0 = slot hesabına göre (serbest teminat)
    entry_post_only: bool = True
    # --- borsalar ---
    exchanges: tuple = ("binance", "okx")
    binance_public_www: str = "auto"
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    # --- risk (V23) ---
    fee_reserve_frac: float = 0.03
    one_position_per_coin: bool = True
    daily_loss_limit_usd: float = 150.0
    weekly_loss_limit_usd: float = 300.0
    max_drawdown_usd: float = 400.0
    liq_mmr_assumed: float = 0.025
    liq_safety: float = 0.90
    max_stop_risk_usd: float = 50.0     # ZERO ders 9: tek işlemde modellenen risk üst sınırı (uyarı + red)
    # --- strateji / sinyal ---
    strategy: str = "ensemble"
    timeframe: str = "15m"              # ansambl taban zaman dilimi
    htf_frames: tuple = ("1h", "4h")    # onay zaman dilimleri (V24/V26 dersi)
    rsi_mode: str = "wilder"            # wilder | sma | off  (V26 araştırma kararı)
    min_score: float = 0.22             # grup ortalaması eşiği [-1,1]
    min_confidence: float = 0.60
    min_support: int = 2                # aynı yönde |g|>=0.15 olan grup sayısı (V27 desteği)
    # İYİLEŞTİRME (1s test analizi): trend-tek başına girişleri engelle.
    # AGT/KGEN LONG kayıpları: trend=+1.00 ama momentum +0.10/+0.23, flow 0.00/+0.27 idi.
    # Momentum ve flow sinyal yönünde minimum güç göstermeli.
    min_momentum: float = 0.20          # momentum grubu sinyal yönünde >= bu olmalı
    min_flow: float = 0.10              # volume_flow grubu sinyal yönünde >= bu olmalı
    adx_min: float = 18.0               # rejim: >= adx_min -> trend
    conflict_penalty: float = 0.85      # trend ile momentum ters yönlüyse (ZERO ders 3)
    rsi_soft_zone: float = 82.0         # yumuşak ceza eşiği (V26; sert veto KALDIRILDI)
    # İYİLEŞTİRME: pump-tepe filtresi — RSI > 70 ise LONG engelle (KGEN RSI 75 idi, tepeden girdi)
    rsi_long_block: float = 70.0        # LONG için RSI üst sınırı
    rsi_short_block: float = 30.0       # SHORT için RSI alt sınırı
    rsi_soft_penalty: float = 0.08
    max_natr: float = 0.12              # volatilite sağduyu kapısı (V27)
    min_natr: float = 0.001
    # --- stop / çıkış ---
    stop_atr_mult: float = 2.2
    stop_min_frac: float = 0.012        # V24 dersi: sıkılı aralık
    stop_max_frac: float = 0.045
    tp_frac: float = 0.0                # 0 = kâr-al yok (ZERO ders 1: erken TP beklentiyi bozar)
    max_hold_sec: int = 86_400          # 24 saat süre çıkışı (V23)
    entry_ttl_sec: int = 3_600
    cooldown_sec: int = 86_400
    # --- pozisyon yönetimi (ZERO) ---
    be_arm_r: float = 0.5               # +0.5R'de başabaş kolu
    trail_arm_r: float = 1.0            # +1R'de trailing kollar
    trail_giveback_r: float = 0.5
    # --- onay kapısı (ZERO ders 10) ---
    confirm_count: int = 2              # ardışık aynı yönlü sinyal gerekir (1 = kapalı)
    # --- pump_short legacy parametreleri (sertifikayla aynı: gate.CERT_PARAM_MAP buna bakar) ---
    vs_min: float = 30.0
    r1_min: float = 0.05
    liq_min_usd: float = 2_000_000.0
    min_age_hours: int = 336
    stop_frac: float = 0.065            # yalnız pump_short kullanır; ansambl stopu ATR'den gelir
    # --- çalışma ---
    mode: str = "paper"                 # paper | live
    scan_interval_sec: int = 300
    manage_interval_sec: int = 20
    max_candidates_per_scan: int = 12
    state_dir: str = "calisma"
    cert_dir: str = "sertifikalar"
    # paper dolum modeli (V23, araştırmayla aynı)
    paper_through: float = 0.0005
    paper_stop_slip: float = 0.002
    paper_exit_slip: float = 0.0005
    # canlı kilitleri (V23 + ZERO ikinci onay)
    confirm_live: str = ""              # "EVET" olmalı
    accept_unvalidated: str = ""        # sertifikasız canlı: "RISKI_KABUL_EDIYORUM"
    live_confirm: str = ""              # ikinci onay: "I_UNDERSTAND"
    # API
    binance_key: str = field(default="", repr=False)
    binance_secret: str = field(default="", repr=False)
    okx_key: str = field(default="", repr=False)
    okx_secret: str = field(default="", repr=False)
    okx_passphrase: str = field(default="", repr=False)
    binance_demo: bool = False
    okx_demo: bool = False

    @property
    def notional_usd(self) -> float:
        return self.margin_usd * self.leverage

    def validate(self) -> list[str]:
        e = []
        if self.margin_usd <= 0 or self.equity_usd <= 0: e.append("kasa ve teminat pozitif olmalı")
        if self.leverage < 1: e.append("kaldıraç >= 1 olmalı")
        if self.margin_mode not in ("isolated", "cross"): e.append("margin_mode isolated|cross olmalı")
        if self.mode not in ("paper", "live"): e.append("mode paper|live olmalı")
        if not (0 < self.stop_min_frac <= self.stop_max_frac < 0.1): e.append("stop_min_frac <= stop_max_frac < 0.1 olmalı")
        if self.margin_mode == "isolated" and self.stop_max_frac > self.max_safe_stop():
            e.append(f"stop_max_frac %{self.stop_max_frac*100:.1f} izole {self.leverage}x tasfiye mesafesine fazla yakın (üst sınır %{self.max_safe_stop()*100:.2f})")
        if self.rsi_mode not in ("wilder", "sma", "off"): e.append("rsi_mode wilder|sma|off olmalı")
        if not self.exchanges: e.append("en az bir borsa gerekli")
        if self.confirm_count < 1: e.append("confirm_count >= 1 olmalı")
        if self.strategy == "pump_short" and self.stop_frac > self.max_safe_stop():
            e.append(f"pump_short stop %{self.stop_frac*100:.1f} tasfiye mesafesine fazla yakın")
        return e

    def max_safe_stop(self) -> float:
        return max(0.0, (1.0 / self.leverage - self.liq_mmr_assumed) * self.liq_safety)


_ENV_PREFIX = "ACARBOT_"


def load_settings(env_file: str = ".env", **overrides) -> Settings:
    _load_dotenv(env_file)
    vals = {}
    for f in fields(Settings):
        raw = os.environ.get(_ENV_PREFIX + f.name.upper())
        if raw is None or raw == "":
            continue
        t = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "str")
        if t == "bool": vals[f.name] = raw.strip().lower() in ("1", "true", "yes", "evet")
        elif t == "int": vals[f.name] = int(float(raw))
        elif t == "float": vals[f.name] = float(raw)
        elif t == "tuple": vals[f.name] = tuple(x.strip() for x in raw.split(",") if x.strip())
        else: vals[f.name] = raw
    vals.update({k: v for k, v in overrides.items() if v is not None})
    s = replace(Settings(), **vals)
    errs = s.validate()
    if errs:
        raise ValueError("Ayar hatası: " + "; ".join(errs))
    return s


# --- 09_V28_FINAL/acarbot/engine.py ---

"""Ana döngü — V23 omurgası + ZERO onay kapısı.
tara -> aday -> özellik -> strateji -> [onay kapısı] -> risk -> maker emir -> yönet -> kaydet.
Teknik arıza (veri alınamıyor, borsa hatası) durumunda yeni işlem AÇILMAZ, mevcut durum korunur.
Onay kapısı (ZERO ders 10): aynı coin için son N (confirm_count) değerlendirmenin hepsi aynı yönde
ve eşik üzerinde olmalı; tek mum spike'ları emre dönüşmez."""
from __future__ import annotations
import logging, time, uuid
from collections import deque
from typing import Optional
from .config import Settings
from .base import Broker, MarketData
from .strategies import Strategy
from .journal import Journal
from .models import Instrument, Position, Signal
from .risk import RiskManager
from .rules import contracts_for_notional

log = logging.getLogger("acarbot.engine")
SNAP_KEEP_SEC = 4200


class Engine:
    def __init__(self, cfg: Settings, feeds: dict[str, MarketData], broker: Broker, journal: Journal,
                 strategy: Strategy, risk: Optional[RiskManager] = None, now=time.time):
        self.cfg = cfg
        self.feeds = feeds
        self.broker = broker
        self.journal = journal
        self.strategy = strategy
        self.now = now
        self.risk = risk or RiskManager(cfg, now)
        self.positions: list[Position] = []
        self.snap: dict[str, dict[str, deque]] = {name: {} for name in feeds}
        self.inst: dict[str, dict[str, Instrument]] = {}
        self.sig_hist: dict[str, deque] = {}     # base -> son confirm_count sinyal (ZERO onayı)
        self.stats = dict(tarama=0, aday=0, sinyal=0, onaylandi=0, emir=0, red=0, veri_hatasi=0, onay_bekleyen=0)
        pos, extra = journal.load_state()
        self.positions = [p for p in pos if p.status in ("PENDING", "OPEN")]
        if extra.get("risk"): self.risk.load(extra["risk"])
        if self.positions: journal.event("durum_yuklendi", acik=len(self.positions))

    # ------------------------------------------------------------------ yardımcılar
    def _instruments(self, name: str) -> dict[str, Instrument]:
        if name not in self.inst: self.inst[name] = self.feeds[name].instruments()
        return self.inst[name]

    def _pnl_windows(self) -> tuple[float, float, float]:
        t = self.now()
        day0 = t - (t % 86400)
        week0 = day0 - 6 * 86400
        return self.journal.realized(day0), self.journal.realized(week0), self.journal.realized(0.0)

    def _r1h_estimate(self, name: str, sym: str, last: float, t: float) -> Optional[float]:
        dq = self.snap[name].setdefault(sym, deque())
        dq.append((t, last))
        while dq and t - dq[0][0] > SNAP_KEEP_SEC: dq.popleft()
        ref = None
        for ts, px in dq:
            if 3300 <= t - ts <= 4200: ref = px; break
        return (last / ref - 1.0) if ref else None

    def save(self) -> None:
        self.journal.save_state(self.positions, dict(risk=self.risk.to_dict(), stats=self.stats))

    def _confirmed(self, sig: Signal) -> bool:
        """ZERO ders 10: confirm_count ardışık aynı yönlü sinyal. confirm_count=1 -> her zaman doğru."""
        n = max(1, self.cfg.confirm_count)
        h = self.sig_hist.setdefault(sig.base, deque(maxlen=n))
        if h and h[-1][0] != sig.side:
            h.clear()
        h.append((sig.side, sig.score))
        return len(h) >= n

    # ------------------------------------------------------------------ tarama
    def scan(self) -> list[Signal]:
        t = self.now()
        signals: list[Signal] = []
        self.stats["tarama"] += 1
        today, week, total = self._pnl_windows()
        now_ms = int(t * 1000)
        for name, feed in self.feeds.items():
            try:
                inst = self._instruments(name)
                tk = feed.tickers()
            except Exception as e:
                self.stats["veri_hatasi"] += 1
                self.journal.event("veri_hatasi", borsa=name, hata=str(e)[:200])
                log.warning("%s veri alınamadı: %s", name, e)
                continue
            cands = []
            for sym, x in tk.items():
                if sym not in inst: continue
                r1 = self._r1h_estimate(name, sym, x["last"], t)
                if self.strategy.prefilter(r1, x.get("pct_24h"), x.get("quote_vol_24h", 0.0)):
                    cands.append((abs(r1) if r1 is not None else abs(x.get("pct_24h") or 0.0), sym))
            cands.sort(reverse=True)
            for score, sym in cands[: self.cfg.max_candidates_per_scan]:
                i = inst[sym]
                self.stats["aday"] += 1
                probe = Signal(name, sym, i.base, -1, 0.0, self.cfg.stop_min_frac, 0.0, 0, 0, "on_kontrol")
                ok, why = self.risk.can_open(probe, self.positions, today, week, total)
                if not ok:
                    self.journal.event("aday_red", borsa=name, sembol=sym, neden=why)
                    continue
                try:
                    sig, why = self.strategy.evaluate(i, self.feeds, now_ms)
                except Exception as e:
                    self.stats["veri_hatasi"] += 1
                    self.journal.event("veri_hatasi", borsa=name, sembol=sym, hata=str(e)[:200])
                    continue
                if sig is None:
                    self.journal.event("aday", borsa=name, sembol=sym, sonuc=why)
                    continue
                self.stats["sinyal"] += 1
                self.journal.event("aday", borsa=name, sembol=sym, sonuc="sinyal", skor=round(sig.score, 3),
                                   yon="LONG" if sig.side > 0 else "SHORT", gerekce=sig.reason)
                if not self._confirmed(sig):
                    self.stats["onay_bekleyen"] += 1
                    self.journal.event("onay_bekleniyor", borsa=name, sembol=sym,
                                       yon="LONG" if sig.side > 0 else "SHORT")
                    continue
                self.stats["onaylandi"] += 1
                signals.append(sig)
                self._try_open(sig, i, today, week, total)
        self.save()
        return signals

    def _try_open(self, sig: Signal, inst: Instrument, today: float, week: float, total: float) -> Optional[Position]:
        ok, why = self.risk.can_open(sig, self.positions, today, week, total)
        if not ok:
            self.stats["red"] += 1
            self.journal.event("sinyal_red", borsa=sig.exchange, sembol=sig.symbol, neden=why)
            return None
        qty = contracts_for_notional(self.cfg.notional_usd, sig.limit_price, inst)
        if qty <= 0:
            self.stats["red"] += 1
            self.journal.event("sinyal_red", borsa=sig.exchange, sembol=sig.symbol, neden="min_emir_boyutu")
            return None
        t = self.now()
        pos = Position(id=uuid.uuid4().hex[:12], exchange=sig.exchange, symbol=sig.symbol, base=sig.base,
                       side=sig.side, qty=qty, contract_size=inst.contract_size, limit_price=sig.limit_price,
                       stop_frac=sig.stop_frac, tp_frac=sig.tp_frac, created_ts=t, expire_ts=t + sig.ttl_sec,
                       max_hold_sec=sig.max_hold_sec, reason=sig.reason, features=dict(sig.features))
        ok, why = self.broker.open_entry(pos, inst)
        if not ok:
            self.stats["red"] += 1
            self.journal.event("emir_red", borsa=sig.exchange, sembol=sig.symbol, neden=why)
            return None
        self.positions.append(pos)
        self.stats["emir"] += 1
        self.journal.event("emir", id=pos.id, borsa=pos.exchange, sembol=pos.symbol, yon=pos.side, miktar=pos.qty,
                           limit=pos.limit_price, stop=pos.stop_price, skor=round(sig.score, 3), neden=pos.reason)
        log.info("EMİR %s %s %s limit=%.6g stop=%.6g (%s)", pos.exchange, pos.symbol,
                 "LONG" if pos.side > 0 else "SHORT", pos.limit_price, pos.stop_price, pos.reason)
        return pos

    # ------------------------------------------------------------------ yönetim
    def manage(self) -> None:
        t = self.now()
        changed = False
        for pos in list(self.positions):
            before = pos.status
            try:
                self.broker.manage(pos, self._instruments(pos.exchange)[pos.symbol], t)
            except Exception as e:
                self.stats["veri_hatasi"] += 1
                self.journal.event("teknik_ariza", id=pos.id, hata=str(e)[:200])
                continue
            if pos.status == before: continue
            changed = True
            if pos.status == "OPEN":
                self.journal.event("giris", id=pos.id, fiyat=pos.entry_price)
                log.info("GİRİŞ %s %s @ %.6g", pos.exchange, pos.symbol, pos.entry_price)
            elif pos.status == "CLOSED":
                self._on_closed(pos)
            elif pos.status == "CANCELLED":
                self.risk.on_entry_expired(pos)
                self.positions.remove(pos)
                self.journal.event("emir_iptal", id=pos.id, neden=pos.exit_reason)
        if changed:
            today, week, total = self._pnl_windows()
            self.risk.update_limits(today, week, total)
            if self.risk.halted:
                self.journal.event("DURDURULDU", neden=self.risk.halt_reason)
                log.error("BOT DURDURULDU: %s", self.risk.halt_reason)
            self.save()

    def _on_closed(self, pos: Position) -> None:
        self.journal.record_closed(pos)
        self.risk.on_closed(pos)
        if pos in self.positions: self.positions.remove(pos)
        self.journal.event("cikis", id=pos.id, neden=pos.exit_reason, fiyat=pos.exit_price,
                           pnl=round(pos.pnl_usd, 4), be=pos.be_armed, trail=pos.trail_armed)
        log.info("ÇIKIŞ %s %s %s @ %.6g net=%.2f$", pos.exchange, pos.symbol, pos.exit_reason, pos.exit_price, pos.pnl_usd)

    def flatten_all(self, reason: str = "KULLANICI") -> None:
        t = self.now()
        for pos in list(self.positions):
            self.broker.flatten(pos, self._instruments(pos.exchange)[pos.symbol], t, reason)
            if pos.status == "CLOSED": self._on_closed(pos)
            elif pos.status == "CANCELLED": self.positions.remove(pos)
        self.save()

    # ------------------------------------------------------------------ döngü
    def run(self, duration_sec: Optional[float] = None, sleep=time.sleep) -> None:
        start = self.now()
        next_scan = 0.0
        next_manage = 0.0
        self.journal.event("basladi", mod=self.cfg.mode, strateji=self.strategy.name,
                           borsalar=list(self.feeds), onay=self.cfg.confirm_count)
        while duration_sec is None or self.now() - start < duration_sec:
            t = self.now()
            if t >= next_manage:
                self.manage()
                next_manage = t + self.cfg.manage_interval_sec
            if t >= next_scan:
                self.scan()
                iv = self.cfg.scan_interval_sec
                next_scan = (int(self.now()) // iv + 1) * iv + 8   # mum kapanışından 8 sn sonra
            sleep(1.0)
        self.save()
        self.journal.event("durdu")

    def summary(self) -> dict:
        tr = self.journal.closed_trades()
        pnl = [x["pnl_usd"] for x in tr]
        wins = [x for x in pnl if x > 0]
        losses = [x for x in pnl if x <= 0]
        return dict(mod=self.cfg.mode, strateji=self.strategy.name, tarama=self.stats["tarama"],
                    aday=self.stats["aday"], sinyal=self.stats["sinyal"], onaylandi=self.stats["onaylandi"],
                    emir=self.stats["emir"],
                    red=self.stats["red"], veri_hatasi=self.stats["veri_hatasi"],
                    onay_bekleyen=self.stats["onay_bekleyen"], acik=len(self.positions), kapanan=len(tr),
                    net_usd=round(sum(pnl), 4), kazanan=len(wins), kaybeden=len(losses),
                    profit_factor=(round(sum(wins) / -sum(losses), 3) if losses and sum(losses) < 0 else None),
                    komisyon_usd=round(sum(x["fees_usd"] for x in tr), 4), durduruldu=self.risk.halted)


################################################################################
# BOT: 10_V28_1
################################################################################


# --- 10_V28_1/acarbot/signal.py ---

"""ANSAMBL SİNYAL MOTORU — V26/V27 grup yaklaşımı + ZERO dersleri.
Gruplar [-1,1] normalize edilir; gruplar arası EŞİT ağırlık kullanılır (V26: indikatör sayısı yanlılığı yok).
- trend: EMA dizilimi + ADX/DMI rejimi (+ supertrend)
- momentum: Wilder RSI (varsayılan) + MACD histogram + ROC + stokastik
- breakout: Donchian/BB/VWAP kırılımı + hacim onayı (V27)
- volume_flow: hacim şoku + CMF + MFI + OBV eğimi (V26)
- derivatives / microstructure: YALNIZ kolonlar gerçekten verilmişse (uydurma yok, V26/V27)
Rejim (ADX) ağırlıkları değiştirir (V27). RSI aşırılığı sert veto DEĞİL yumuşak cezadır (V26).
STOP: ATR×2.2, [0.012, 0.045] kelepçe (V24) + izole tasfiye güvenliği (V23).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .config import Settings
from .features import feature_frame

EPS = 1e-12


@dataclass
class EnsembleResult:
    side: int                       # 1 / -1 / 0 (FLAT)
    score: float                    # grup ortalaması [-1,1]
    confidence: float               # [0,1]
    stop_frac: float
    regime: str                     # trend | range
    reason: str
    groups: dict = field(default_factory=dict)
    blocked: str = ""               # sinyal üretilmediyse gerekçe


def _last(x) -> float:
    try:
        v = float(x.iloc[-1])
    except Exception:
        return float("nan")
    return v


def _at(x, idx: int) -> float:
    """Satır idx'teki değer (backtest O(n): dilim yok, nedensel göstergelerde eşdeğerdir)."""
    try:
        v = float(x.iloc[idx])
    except Exception:
        return float("nan")
    return v


def _clip01(x: float) -> float:
    if not np.isfinite(x): return 0.0
    return float(max(-1.0, min(1.0, x)))


class EnsembleEngine:
    def __init__(self, cfg: Settings):
        self.cfg = cfg

    # ------------------------------------------------------------------ grup puanları
    def _group_trend(self, f: pd.DataFrame, idx: int = -1) -> float:
        e20, e50, e200 = _at(f.ema_20, idx), _at(f.ema_50, idx), _at(f.ema_200, idx)
        if not (np.isfinite(e20) and np.isfinite(e50) and np.isfinite(e200)): return 0.0
        t = 0.4 * np.sign(e20 - e50) + 0.3 * np.sign(e50 - e200)
        adx, pdi, mdi = _at(f.adx, idx), _at(f.plus_di, idx), _at(f.minus_di, idx)
        if np.isfinite(adx) and adx >= self.cfg.adx_min:
            t += 0.3 * np.sign(pdi - mdi)
        return _clip01(t / 1.0)

    def _group_momentum(self, f: pd.DataFrame, idx: int = -1) -> float:
        if self.cfg.rsi_mode == "wilder":
            rsi = _at(f.rsi_wilder, idx)
        elif self.cfg.rsi_mode == "sma":
            rsi = _at(f.rsi_sma, idx)
        else:
            rsi = 50.0
        mom = 0.45 * _clip01((rsi - 50.0) / 20.0) if np.isfinite(rsi) else 0.0
        mh = _at(f.macd_hist, idx)
        mom += 0.25 * (np.sign(mh) if np.isfinite(mh) else 0.0)
        roc = _at(f.roc_12, idx)
        mom += 0.15 * _clip01(roc / 5.0) if np.isfinite(roc) else 0.0
        sk = _at(f.stoch_k, idx)
        mom += 0.15 * _clip01((sk - 50.0) / 30.0) if np.isfinite(sk) else 0.0
        return _clip01(mom)

    def _group_breakout(self, f: pd.DataFrame, idx: int = -1) -> float:
        c, dcu, dcl = _at(f.close, idx), _at(f.dc_up, idx), _at(f.dc_low, idx)
        bbu, bbl, vw, vr = _at(f.bb_up, idx), _at(f.bb_low, idx), _at(f.vwap, idx), _at(f.vol_ratio, idx)
        if not np.isfinite(c): return 0.0
        parts = []
        if np.isfinite(dcu) and dcu > 0: parts.append(_clip01((c / dcu - 1.0) / 0.01))
        if np.isfinite(dcl) and dcl > 0: parts.append(_clip01((c / dcl - 1.0) / 0.01))
        if np.isfinite(bbu) and bbu > 0: parts.append(_clip01((c / bbu - 1.0) / 0.01))
        if np.isfinite(bbl) and bbl > 0: parts.append(_clip01((c / bbl - 1.0) / 0.01))
        if np.isfinite(vw) and vw > 0: parts.append(_clip01((c / vw - 1.0) / 0.01))
        if not parts: return 0.0
        s = float(np.mean(parts))
        # hacim onayı: vol_ratio < 1.0 ise kırılım güvenilirliği düşer (V27 breakout+volume dersi)
        if np.isfinite(vr) and vr < 1.0:
            s *= 0.7
        return _clip01(s)

    def _group_volume_flow(self, f: pd.DataFrame, idx: int = -1) -> float:
        vz, cmfv, mfi = _at(f.vol_z, idx), _at(f.cmf, idx), _at(f.mfi, idx)
        vf = 0.45 * _clip01(vz / 3.0) if np.isfinite(vz) else 0.0
        vf += 0.25 * _clip01(cmfv * 4.0) if np.isfinite(cmfv) else 0.0
        vf += 0.20 * _clip01((mfi - 50.0) / 25.0) if np.isfinite(mfi) else 0.0
        obv = f.obv
        if idx >= 5 or (idx == -1 and len(obv) >= 6):
            o_now, o_then = _at(obv, idx), _at(obv, idx - 5 if idx != -1 else -6)
            vf += 0.10 * (np.sign(o_now - o_then) if np.isfinite(o_now) and np.isfinite(o_then) else 0.0)
        return _clip01(vf)

    def _group_fade(self, f: pd.DataFrame, idx: int = -1) -> float:
        """FADE TERSİNE ÇEVİRME (yeni): pump sonrası fade -> SHORT, dump sonrası bounce -> LONG.

        KGEN örneği: 0.082 -> 0.103 (pump +%9.73) -> 0.090 (fade -%12.7).
        V23 doğru SHORT sinyalini verdi ama maker emir dolmadı.
        V28 yanlış LONG'a girdi (tepe).
        Bu grup: güçlü pump + momentum dönüşü = fade başlangıcı -> ters yön sinyali.
        """
        try:
            c = _at(f.close, idx)
            # Son 4 bar (1 saat) getirisi: pump/dump tespiti
            c_4ago = _at(f.close, idx - 4 if idx != -1 else -5)
            if not (np.isfinite(c) and np.isfinite(c_4ago) and c_4ago > 0):
                return 0.0
            ret_1h = c / c_4ago - 1.0
            # Momentum dönüşü: macd_hist işareti veya stoch dönüşü
            mh = _at(f.macd_hist, idx) if "macd_hist" in f.columns else 0.0
            mh_prev = _at(f.macd_hist, idx - 2 if idx != -1 else -3) if "macd_hist" in f.columns else 0.0
            fade = 0.0
            # Pump sonrası fade: ret_1h güçlü pozitif ama momentum düşüyor
            if ret_1h >= 0.04 and np.isfinite(mh) and np.isfinite(mh_prev) and mh < mh_prev:
                fade = -min(1.0, (ret_1h - 0.04) * 10 + 0.3)  # SHORT sinyali
            # Dump sonrası bounce: ret_1h güçlü negatif ama momentum yükseliyor
            elif ret_1h <= -0.04 and np.isfinite(mh) and np.isfinite(mh_prev) and mh > mh_prev:
                fade = min(1.0, (-ret_1h - 0.04) * 10 + 0.3)  # LONG sinyali
            return _clip01(fade)
        except Exception:
            return 0.0

    def _group_derivatives(self, f: pd.DataFrame, idx: int = -1) -> float:
        """Yalnız sağlanan kolonlar. funding: pozitif funding long için maliyet -> ters işaret (V26)."""
        der, norm = 0.0, 0.0
        for col, w in (("oi_delta_pct", 0.35), ("oi_z", 0.15), ("funding", -0.15),
                       ("basis_pct", 0.15), ("liquidation_delta", 0.20)):
            if col in f.columns:
                x = _at(f[col], idx)
                if np.isfinite(x):
                    der += w * _clip01(x)
                    norm += abs(w)
        return _clip01(der / norm) if norm > 0 else 0.0

    def _group_microstructure(self, f: pd.DataFrame, idx: int = -1) -> float:
        micro, norm = 0.0, 0.0
        for col, w in (("cvd_slope", 0.45), ("taker_imbalance", 0.25), ("orderbook_imbalance", 0.30)):
            if col in f.columns:
                x = _at(f[col], idx)
                if np.isfinite(x):
                    micro += w * _clip01(x)
                    norm += abs(w)
        if "spread_bps" in f.columns:
            sp = _at(f["spread_bps"], idx)
            if np.isfinite(sp) and sp > 15 and norm > 0:
                micro *= 0.6     # geniş spread: mikroyapı güvenilirliği düşer (ZERO spread kapısı)
        return _clip01(micro / norm) if norm > 0 else 0.0

    # ------------------------------------------------------------------ değerlendirme
    def evaluate(self, df: pd.DataFrame, htf: Optional[dict] = None) -> EnsembleResult:
        """df: HAM OHLCV (taban zaman dilimi). htf: {'1h': ohlcv_df, ...} (opsiyonel onay, V26)."""
        f = feature_frame(df)
        return self._evaluate_frame(f, htf)

    def _evaluate_frame(self, f: pd.DataFrame, htf: Optional[dict] = None, idx: int = -1) -> EnsembleResult:
        """f: feature_frame çıktısı. idx: değerlendirilecek satır (backtest'te i; nedensel göstergeler
        nedeniyle f.iloc[:i+1] dilimiyle birebir eşdeğerdir ama O(1)'dir)."""
        cfg = self.cfg
        n_avail = len(f) if idx == -1 else idx + 1
        if n_avail < 260:
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "veri_yetersiz")
        c, natr, rng = _at(f.close, idx), _at(f.natr, idx), _at(f.range_frac, idx)
        if not np.isfinite(c) or c <= 0:
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "fiyat_gecersiz")
        atrv = _at(f.atr, idx)
        if not np.isfinite(atrv) or atrv <= 0:
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "atr_yok")
        # volatilite sağduyu kapısı (V27): aşırı sakin/pahalı piyasa sinyal üretmez
        if not (cfg.min_natr <= natr <= cfg.max_natr) or (np.isfinite(rng) and rng > 0.18):
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "volatilite_kapisi")

        groups = {
            "trend": self._group_trend(f, idx),
            "momentum": self._group_momentum(f, idx),
            "breakout": self._group_breakout(f, idx),
            "volume_flow": self._group_volume_flow(f, idx),
        }
        # FADE TERSİNE ÇEVİRME: pump/dump sonrası dönüş -> ters yön.
        # Güçlü fade sinyali varsa skoru ters yöne çevir (V23 pump_short mantığı).
        fade = self._group_fade(f, idx)
        if abs(fade) >= 0.3:
            groups["fade"] = fade
        deriv = self._group_derivatives(f, idx)
        micro = self._group_microstructure(f, idx)
        core = list(groups.values())
        score = float(np.mean(core))                     # çekirdek gruplar eşit ağırlıkta
        coverage = 0.0
        if deriv != 0.0:
            groups["derivatives"] = deriv
            core.append(deriv)
            coverage += 0.5
        if micro != 0.0:
            groups["microstructure"] = micro
            core.append(micro)
            coverage += 0.5
        score = float(np.mean(core))

        # HTF onayı: taban 0.8 + onay 0.2 (V26), onay = EMA20/50 yönü ortalaması
        htf_note = ""
        if htf:
            hs = []
            for tf, hf in htf.items():   # htf değerleri HAZIR feature frame olabilir (backtest) veya ham OHLCV
                try:
                    hf2 = hf if ("ema_20" in getattr(hf, "columns", [])) else feature_frame(hf)
                    h20, h50 = _last(hf2.ema_20), _last(hf2.ema_50)   # HTF: son bar onayı
                    if np.isfinite(h20) and np.isfinite(h50):
                        hs.append(np.sign(h20 - h50))
                        htf_note = f"+htf({','.join(htf.keys())})"
                except Exception:
                    continue
            if hs:
                score = 0.8 * score + 0.2 * float(np.mean(hs))

        # çatışma cezası (ZERO ders 3): trend ile momentum güçlü ve ters yönlüyse puan düşer
        conflict = groups["trend"] * groups["momentum"] < 0 and abs(groups["trend"]) > 0.2 and abs(groups["momentum"]) > 0.2
        if conflict:
            score *= cfg.conflict_penalty

        # RSI yumuşak cezası (V26; sert veto kaldırıldı)
        rsi = _at(f.rsi_wilder if cfg.rsi_mode == "wilder" else f.rsi_sma, idx) if cfg.rsi_mode != "off" else 50.0
        rsi_note = ""
        if np.isfinite(rsi):
            if score > 0 and rsi > cfg.rsi_soft_zone:
                score -= cfg.rsi_soft_penalty
                rsi_note = f"-rsi{rsi:.0f}"
            elif score < 0 and rsi < 100 - cfg.rsi_soft_zone:
                score += cfg.rsi_soft_penalty
                rsi_note = f"+rsi{rsi:.0f}"
        # İYİLEŞTİRME: pump-tepe filtresi — aşırı alım/satımda ters yön engelle
        rsi_blocked = ""
        if np.isfinite(rsi):
            if score > 0 and rsi > cfg.rsi_long_block:
                rsi_blocked = f"rsi_asiri_alim({rsi:.0f})"
            elif score < 0 and rsi < cfg.rsi_short_block:
                rsi_blocked = f"rsi_asiri_satim({rsi:.0f})"

        adx = _at(f.adx, idx)
        regime = "trend" if (np.isfinite(adx) and adx >= cfg.adx_min) else "range"

        # destek: aynı yönde anlamlı katkı veren grup sayısı (V27 'support' dersi)
        side = 1 if score > 0 else (-1 if score < 0 else 0)
        support = sum(1 for g in core if g * side > 0 and abs(g) >= 0.15) if side != 0 else 0
        agreement = abs(float(np.mean(np.sign(core)))) if core else 0.0
        confidence = float(np.clip(0.45 + 0.35 * agreement + 0.20 * coverage, 0.0, 1.0))

        stop_frac = self._stop_frac(atrv, c)
        reason = (f"trend={groups['trend']:+.2f} mom={groups['momentum']:+.2f} brk={groups['breakout']:+.2f} "
                  f"flow={groups['volume_flow']:+.2f} adx={adx:.0f} rsi={rsi:.0f} {regime}{htf_note}{rsi_note}")
        blocked = ""
        if abs(score) < cfg.min_score:
            blocked = "skor_esik_alti"
        elif support < cfg.min_support:
            blocked = f"grup_destegi_yetersiz({support})"
        elif confidence < cfg.min_confidence:
            blocked = "guven_dusuk"
        # İYİLEŞTİRME: momentum/flow teyidi — trend tek başına yetmez.
        # Kayıp analizi: AGT (flow=0.00), KGEN (mom=+0.10) bu kapıda elenirdi.
        elif groups["momentum"] * side < cfg.min_momentum:
            blocked = "momentum_teyitsiz"
        elif groups["volume_flow"] * side < cfg.min_flow:
            blocked = "flow_teyitsiz"
        # İYİLEŞTİRME: pump-tepe filtresi — RSI aşırı bölgede ters yön engelle
        elif rsi_blocked:
            blocked = rsi_blocked
        if blocked:
            side = 0
        return EnsembleResult(side, float(score), confidence, stop_frac, regime, reason, groups, blocked)

    def _stop_frac(self, atrv: float, price: float) -> float:
        """ATR'ye uyarlanan stop, sıkı kelepçeli (V24) ve tasfiyeye güvenli (V23)."""
        natr = atrv / (price + EPS)
        stop = self.cfg.stop_atr_mult * natr
        stop = max(self.cfg.stop_min_frac, min(self.cfg.stop_max_frac, stop))
        safe = self.cfg.max_safe_stop()
        return min(stop, safe)

    # ------------------------------------------------------------------ Signal üretimi (canlı tarama için)

# --- 10_V28_1/acarbot/config.py ---

"""ACARBOT V28 FINAL — ayarlar.
Kullanıcının SABİT kuralları varsayılandır: 1000$ kasa, işlem başına 50$ teminat, sabit 10x,
maker (post-only) giriş, izole marj. Diğer tüm parametreler .env ile değiştirilebilir (ACARBOT_ öneki).
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    # --- sabit kurallar (kullanıcı) ---
    equity_usd: float = 1000.0
    margin_usd: float = 50.0
    leverage: int = 10
    margin_mode: str = "isolated"
    max_positions: int = 0              # 0 = slot hesabına göre (serbest teminat)
    entry_post_only: bool = True
    # --- borsalar ---
    exchanges: tuple = ("binance", "okx")
    binance_public_www: str = "auto"
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    # --- risk (V23) ---
    fee_reserve_frac: float = 0.03
    one_position_per_coin: bool = True
    daily_loss_limit_usd: float = 150.0
    weekly_loss_limit_usd: float = 300.0
    max_drawdown_usd: float = 400.0
    liq_mmr_assumed: float = 0.025
    liq_safety: float = 0.90
    max_stop_risk_usd: float = 50.0     # ZERO ders 9: tek işlemde modellenen risk üst sınırı (uyarı + red)
    # --- strateji / sinyal ---
    strategy: str = "ensemble"
    timeframe: str = "15m"              # ansambl taban zaman dilimi
    htf_frames: tuple = ("1h", "4h")    # onay zaman dilimleri (V24/V26 dersi)
    rsi_mode: str = "wilder"            # wilder | sma | off  (V26 araştırma kararı)
    min_score: float = 0.22             # grup ortalaması eşiği [-1,1]
    min_confidence: float = 0.60
    min_support: int = 2                # aynı yönde |g|>=0.15 olan grup sayısı (V27 desteği)
    # İYİLEŞTİRME (1s test analizi): trend-tek başına girişleri engelle.
    # AGT/KGEN LONG kayıpları: trend=+1.00 ama momentum +0.10/+0.23, flow 0.00/+0.27 idi.
    # Momentum ve flow sinyal yönünde minimum güç göstermeli.
    min_momentum: float = 0.20          # momentum grubu sinyal yönünde >= bu olmalı
    min_flow: float = 0.10              # volume_flow grubu sinyal yönünde >= bu olmalı
    adx_min: float = 18.0               # rejim: >= adx_min -> trend
    conflict_penalty: float = 0.85      # trend ile momentum ters yönlüyse (ZERO ders 3)
    rsi_soft_zone: float = 82.0         # yumuşak ceza eşiği (V26; sert veto KALDIRILDI)
    # İYİLEŞTİRME: pump-tepe filtresi — RSI > 70 ise LONG engelle (KGEN RSI 75 idi, tepeden girdi)
    rsi_long_block: float = 70.0        # LONG için RSI üst sınırı
    rsi_short_block: float = 30.0       # SHORT için RSI alt sınırı
    rsi_soft_penalty: float = 0.08
    max_natr: float = 0.12              # volatilite sağduyu kapısı (V27)
    min_natr: float = 0.001
    # --- stop / çıkış ---
    stop_atr_mult: float = 2.2
    stop_min_frac: float = 0.012        # V24 dersi: sıkılı aralık
    stop_max_frac: float = 0.045
    tp_frac: float = 0.0                # 0 = kâr-al yok (ZERO ders 1: erken TP beklentiyi bozar)
    max_hold_sec: int = 86_400          # 24 saat süre çıkışı (V23)
    entry_ttl_sec: int = 3_600
    cooldown_sec: int = 86_400
    # --- pozisyon yönetimi (ZERO) ---
    be_arm_r: float = 0.5               # +0.5R'de başabaş kolu
    trail_arm_r: float = 1.0            # +1R'de trailing kollar
    trail_giveback_r: float = 0.5
    # --- onay kapısı (ZERO ders 10) ---
    confirm_count: int = 2              # ardışık aynı yönlü sinyal gerekir (1 = kapalı)
    # --- pump_short legacy parametreleri (sertifikayla aynı: gate.CERT_PARAM_MAP buna bakar) ---
    vs_min: float = 30.0
    r1_min: float = 0.05
    liq_min_usd: float = 2_000_000.0
    min_age_hours: int = 336
    stop_frac: float = 0.065            # yalnız pump_short kullanır; ansambl stopu ATR'den gelir
    # --- çalışma ---
    mode: str = "paper"                 # paper | live
    scan_interval_sec: int = 300
    manage_interval_sec: int = 20
    max_candidates_per_scan: int = 12
    state_dir: str = "calisma"
    cert_dir: str = "sertifikalar"
    # paper dolum modeli (V23, araştırmayla aynı)
    paper_through: float = 0.0005
    paper_stop_slip: float = 0.002
    paper_exit_slip: float = 0.0005
    # canlı kilitleri (V23 + ZERO ikinci onay)
    confirm_live: str = ""              # "EVET" olmalı
    accept_unvalidated: str = ""        # sertifikasız canlı: "RISKI_KABUL_EDIYORUM"
    live_confirm: str = ""              # ikinci onay: "I_UNDERSTAND"
    # API
    binance_key: str = field(default="", repr=False)
    binance_secret: str = field(default="", repr=False)
    okx_key: str = field(default="", repr=False)
    okx_secret: str = field(default="", repr=False)
    okx_passphrase: str = field(default="", repr=False)
    binance_demo: bool = False
    okx_demo: bool = False

    @property
    def notional_usd(self) -> float:
        return self.margin_usd * self.leverage

    def validate(self) -> list[str]:
        e = []
        if self.margin_usd <= 0 or self.equity_usd <= 0: e.append("kasa ve teminat pozitif olmalı")
        if self.leverage < 1: e.append("kaldıraç >= 1 olmalı")
        if self.margin_mode not in ("isolated", "cross"): e.append("margin_mode isolated|cross olmalı")
        if self.mode not in ("paper", "live"): e.append("mode paper|live olmalı")
        if not (0 < self.stop_min_frac <= self.stop_max_frac < 0.1): e.append("stop_min_frac <= stop_max_frac < 0.1 olmalı")
        if self.margin_mode == "isolated" and self.stop_max_frac > self.max_safe_stop():
            e.append(f"stop_max_frac %{self.stop_max_frac*100:.1f} izole {self.leverage}x tasfiye mesafesine fazla yakın (üst sınır %{self.max_safe_stop()*100:.2f})")
        if self.rsi_mode not in ("wilder", "sma", "off"): e.append("rsi_mode wilder|sma|off olmalı")
        if not self.exchanges: e.append("en az bir borsa gerekli")
        if self.confirm_count < 1: e.append("confirm_count >= 1 olmalı")
        if self.strategy == "pump_short" and self.stop_frac > self.max_safe_stop():
            e.append(f"pump_short stop %{self.stop_frac*100:.1f} tasfiye mesafesine fazla yakın")
        return e

    def max_safe_stop(self) -> float:
        return max(0.0, (1.0 / self.leverage - self.liq_mmr_assumed) * self.liq_safety)


_ENV_PREFIX = "ACARBOT_"


def load_settings(env_file: str = ".env", **overrides) -> Settings:
    _load_dotenv(env_file)
    vals = {}
    for f in fields(Settings):
        raw = os.environ.get(_ENV_PREFIX + f.name.upper())
        if raw is None or raw == "":
            continue
        t = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "str")
        if t == "bool": vals[f.name] = raw.strip().lower() in ("1", "true", "yes", "evet")
        elif t == "int": vals[f.name] = int(float(raw))
        elif t == "float": vals[f.name] = float(raw)
        elif t == "tuple": vals[f.name] = tuple(x.strip() for x in raw.split(",") if x.strip())
        else: vals[f.name] = raw
    vals.update({k: v for k, v in overrides.items() if v is not None})
    s = replace(Settings(), **vals)
    errs = s.validate()
    if errs:
        raise ValueError("Ayar hatası: " + "; ".join(errs))
    return s


################################################################################
# BOT: 11_V29
################################################################################


# --- 11_V29/acarbot/signal.py (bulunamadi) ---


# --- 11_V29/acarbot/config.py ---

"""Tek dogruluk kaynagi: sabit kurallar. Hicbir modul bu sayilari kendi basina yeniden tanimlamaz."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, asdict, field


@dataclass(frozen=True)
class Rules:
    # --- kullanicinin sabit kurallari ---
    equity: float = 1000.0
    margin: float = 50.0            # islem basina teminat
    leverage: int = 10              # sabit
    max_loss_usd: float = 20.0      # stop dolarken ucret+kayma DAHIL azami kayip
    # --- maliyet modeli ---
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    stop_slip: float = 0.0005       # stop-market kaymasi (fiyat orani)
    maintenance_margin: float = 0.005
    # --- cikis motoru (V22.6'dan; yalniz SIKILASTIRIR) ---
    be_usd: float = 10.0            # net +10$ -> stop maliyet-basi basabasa
    trail_arm_usd: float = 20.0     # net +20$ -> takip eden stop
    trail_giveback_usd: float = 10.0
    max_hold_sec: int = 24 * 3600
    # --- giris ---
    maker_offset: float = 0.0002    # limit, son fiyatin pasif tarafinda
    order_ttl_sec: int = 900
    confirm_scans: int = 2          # ardisik tarama teyidi
    confirm_ttl_sec: int = 300
    cooldown_after_stop_sec: int = 4 * 3600
    # --- risk ---
    daily_loss_limit: float = 150.0
    max_drawdown: float = 300.0     # kapi kriteriyle ayni: kasanin %30'u
    reserve_margin_frac: float = 0.05   # serbest teminatin %5'i hep bos kalir
    max_open_risk_frac: float = 0.30    # tum acik pozisyonlarin stop-kaybi toplami <= kasanin %30'u (0 = kapali)
    # --- sinyal ---
    score_threshold: int = 70
    rsi_mode: str = "rma"           # rma | sma | off  (arastirma notu: RMA = TradingView tanimi)
    rsi_extreme: float = 90.0       # yalniz asiri uc: sert veto
    rsi_soft: float = 80.0          # asiri-uzama: puan cezasi
    adx_min: float = 20.0
    adx_strong: float = 25.0
    chase_atr: float = 2.5          # EMA20'den > 2.5 ATR uzakta kovalama cezasi
    min_liquidity_usd: float = 2_000_000.0
    min_stop_frac: float = 0.012
    atr_stop_mult: float = 1.5
    enabled_setups: tuple = ("trend_breakout", "trend_pullback")
    # KANIT YOK: V23 kanit kapisinda dokunulmamis 2026 testini gecemeyen aileler varsayilan KAPALI
    # ("pump_fade_short", "dip_long" icin enabled_setups'a elle eklenmeli)

    @property
    def notional(self) -> float:
        return self.margin * self.leverage

    @property
    def fee_roundtrip_usd(self) -> float:
        return self.notional * (self.maker_fee + self.taker_fee)

    @property
    def liquidation_dist(self) -> float:
        return 1.0 / self.leverage - self.maintenance_margin

    @property
    def max_stop_frac(self) -> float:
        """Stop dolarsa ucret+kayma dahil toplam kayip max_loss_usd'yi gecmesin."""
        budget = self.max_loss_usd - self.fee_roundtrip_usd - self.notional * self.stop_slip
        return budget / self.notional

    def validate(self) -> None:
        errs = []
        if self.leverage < 1 or self.margin <= 0 or self.equity <= 0:
            # temel sayilar gecersizse turetilmis degerler (bolme) hesaplanmadan hemen reddet
            raise ValueError("Gecersiz kural seti: equity/margin/leverage pozitif olmali")
        if self.max_stop_frac <= self.min_stop_frac:
            errs.append("max_loss_usd ucretlerden sonra min_stop_frac'e yetmiyor")
        if self.max_stop_frac * 1.5 > self.liquidation_dist:
            errs.append("stop tasfiye mesafesine cok yakin/ustunde: stop gercek olmaz")
        if self.rsi_mode not in ("rma", "sma", "off"):
            errs.append("rsi_mode rma|sma|off olmali")
        if self.margin * 1.0 > self.equity:
            errs.append("tek teminat kasayi asiyor")
        if self.trail_arm_usd <= self.be_usd:
            errs.append("trail_arm_usd > be_usd olmali")
        if errs:
            raise ValueError("Gecersiz kural seti: " + "; ".join(errs))

    def fingerprint(self) -> str:
        """Sertifika/parametre eslesmesi icin deterministik parmak izi."""
        d = asdict(self)
        d["enabled_setups"] = sorted(d["enabled_setups"])
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


DEFAULT = Rules()
DEFAULT.validate()


################################################################################
# BOT: 12_ZERO
################################################################################


# --- 12_ZERO/main.py ---

import argparse,time,json,os
from acarbot.core.config import Config
from acarbot.core.signal import SignalEngine
from acarbot.core.risk import RiskManager
from acarbot.core.portfolio import PaperPortfolio
from acarbot.data.exchange import ExchangeData

def log(x):
 os.makedirs('logs',exist_ok=True)
 with open('logs/events.jsonl','a',encoding='utf8') as f:f.write(json.dumps(x,ensure_ascii=False,default=str)+'\n')
 print(json.dumps(x,ensure_ascii=False,default=str))

def main():
 p=argparse.ArgumentParser(); p.add_argument('--paper',action='store_true'); p.add_argument('--live',action='store_true'); p.add_argument('--duration',type=int,default=3600); p.add_argument('--symbols',nargs='*'); a=p.parse_args()
 cfg=Config(mode='live' if a.live else 'paper'); cfg.validate()
 sigeng=SignalEngine(cfg); risk=RiskManager(cfg); book=PaperPortfolio(cfg)
 # Hata yalıtımı: tek borsa çökerse bot düşmez, çalışanla devam eder
 feeds=[]
 for x in cfg.exchanges:
  try:
   f=ExchangeData(x,cfg)
   if getattr(f,'available',True): feeds.append(f); log({'event':'FEED_OK','exchange':x})
   else: log({'event':'FEED_UNAVAILABLE','exchange':x,'error':getattr(f,'error',None)})
  except Exception as e: log({'event':'FEED_INIT_ERROR','exchange':x,'error':f'{type(e).__name__}: {e}'})
 if not feeds: log({'event':'FATAL','error':'hiçbir borsa bağlanamadı'}); return
 end=time.time()+a.duration
 while time.time()<end:
  for feed in feeds:
   syms=a.symbols or feed.universe(cfg.scan_limit)
   for sym in syms[:cfg.detail_limit]:
    try:
     s=feed.snapshot(sym); sig,reason,details=sigeng.evaluate(s); log({'ts':s.ts,'exchange':s.exchange,'symbol':s.symbol,'signal':bool(sig),'reason':reason,'score':details.get('score') if details else None})
     if sig:
      ok,why=risk.can_open(book.balance,list(book.positions.values()),sig); log({'event':'risk','symbol':sig.symbol,'side':sig.side,'ok':ok,'why':why})
      if ok:
       if cfg.mode=='paper': book.open(sig); log({'event':'OPEN','symbol':sig.symbol,'side':sig.side,'entry':sig.entry,'notional':sig.notional})
       else: raise RuntimeError('Live execution adapter bu ilk ZERO paketinde bilinçli olarak kilitli; önce paper doğrulaması yapılmalı.')
     book.mark(s.price,s.ts)
    except Exception as e: log({'event':'ERROR','exchange':feed.name,'symbol':sym,'error':f'{type(e).__name__}: {e}'})
  time.sleep(cfg.poll_seconds)
 print('BALANCE',book.balance,'OPEN',len(book.positions),'CLOSED',len(book.closed))

if __name__=='__main__':main()


# --- 12_ZERO/acarbot/core/config.py ---

from dataclasses import dataclass
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv yoksa .env okunmaz, varsayılanlar kullanılır

@dataclass(frozen=True)
class Config:
    mode: str = os.getenv('MODE','paper').lower()
    exchanges: tuple[str,...] = tuple(x.strip() for x in os.getenv('EXCHANGES','binance,okx').split(',') if x.strip())
    start_balance: float = float(os.getenv('START_BALANCE','1000'))
    entry_margin: float = float(os.getenv('ENTRY_MARGIN','50'))
    leverage: float = float(os.getenv('LEVERAGE','10'))
    max_open: int = int(os.getenv('MAX_OPEN','20'))
    scan_limit: int = int(os.getenv('SCAN_LIMIT','80'))
    detail_limit: int = int(os.getenv('DETAIL_LIMIT','30'))
    poll_seconds: int = int(os.getenv('POLL_SECONDS','60'))
    min_score: float = 0.58
    conflict_penalty: float = 0.70
    confirm_count: int = 2
    rsi_long_block: float = 78.0
    rsi_short_block: float = 22.0
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    max_spread_bps: float = 8.0
    min_quote_volume: float = 2_000_000.0
    max_data_age_sec: int = 150
    stop_risk_usd: float = 20.0
    breakeven_r: float = 0.5
    trail_arm_r: float = 1.0
    trail_giveback_r: float = 0.5
    time_exit_hours: int = 24
    same_underlying_lock: bool = True
    paper_slippage_bps: float = 2.0

    @property
    def notional(self):
        return self.entry_margin * self.leverage

    def validate(self):
        if self.mode not in ('paper','live'): raise ValueError('MODE paper veya live olmalı')
        if self.entry_margin <= 0 or self.leverage <= 0: raise ValueError('margin/leverage pozitif olmalı')
        if self.mode == 'live' and os.getenv('LIVE_CONFIRM') != 'I_UNDERSTAND':
            raise ValueError('Live için LIVE_CONFIRM=I_UNDERSTAND gerekli')


################################################################################
# BOT: 13_TOPLAMA_SINGLE
################################################################################


# --- 13_TOPLAMA_SINGLE/ACARBOT_TEK_DOSYA.py ---

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ACARBOT V23 — TEK DOSYA SÜRÜMÜ
==============================
Toplama 1-4 arşivlerindeki tüm çalışmaların temizlenip tekilleştirilmiş hâlinden
üretilen ACARBOT V23 botunun tek dosyalık sürümü. Özet veriler ve aday strateji
sertifikası dosyanın içine gömülüdür (GOMULU_OZET / GOMULU_SERTIFIKALAR).

SABİT KURALLAR: 1000$ kasa - işlem başına 50$ teminat - sabit 10x - maker
(post-only) giriş - sınırsız işlem - Binance USDT-M + OKX USDT-swap.

ÖNEMLİ: Aday strateji pump_short, kanıt kapısından KALDI. Canlı mod kilitlidir;
bu dosya paper (simülasyon) amaçlıdır. Ayrıntı: `ozet` ve `kapi` komutları.

Kurulum : pip install "ccxt>=4.5"
Kullanım: python ACARBOT_TEK_DOSYA.py ozet|kapi|tara|paper|durum|canli
"""
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from dataclasses import dataclass, field, asdict
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Iterable
from typing import Optional
from typing import Optional, Sequence
import argparse, json, logging, sys
import json
import json, os, sqlite3, time
import logging
import logging, time, uuid
import math
import os
import re, time, logging
import time

__version__ = "23.0.0-tekdosya"


# ======================================================================
# GÖMÜLÜ VERİLER (özet + sertifika)
# ======================================================================
GOMULU_OZET = {'proje': 'ACARBOT V23 — tek dosya sürümü (Toplama 1-4 arşivinin temizlenmiş hâlinden üretilmiştir)', 'sabit_kurallar': {'kasa_usd': 1000, 'islem_basina_teminat_usd': 50, 'kaldirac': '10x sabit', 'emir_tipi': 'maker / post-only giriş', 'islem_siniri': 'sınırsız (tek sınır serbest teminat)', 'borsalar': ['Binance USDT-M', 'OKX USDT-swap']}, 'arsiv_hukmu': "En güncel hat Toplama 4 içindeki ACARBOT_FINAL -> V20 -> V22.6-FINAL hattıdır. Eski sürümlerin kendi raporları da (v5.5/v5.6) 'KENAR YOK' sonucuna varmıştı: walk-forward 0/3 kârlı pencere, Monte Carlo kayıp olasılığı %98,9. Tüm eski paper koşularında toplam yalnızca 72 kapanan işlem vardı.", 'arastirma_hukmu': '2022-2026, delist dahil 920 sembol, 182,6 milyon 5 dakikalık bar üzerinde ~10 strateji ailesi test edildi; hiçbiri dokunulmamış dönemde sağlam pozitif beklenti vermedi. Ham fiyat etkileri gerçek olsa da 10x + uygulanabilir stop altında stop, ortalamaya dönüşü öldürüyor.', 'aday_strateji_pump_short': {'kural': 'hacim şoku >=30x, son 1 saat getirisi >=+%5, likidite >=2M$/gün, yaş >=14 gün; SHORT, stop %6,5, 24 saat süre çıkışı', 'tasarim_2022_2025': {'n': 3061, 'net_usd': 7696.58, 'ort_islem_usd': 2.51, 'winrate': 0.4417, 'pf': 1.1377, 'gun_kumeli_t': 2.5723, 'max_dd_usd': 1146.75}, 'dokunulmamis_2026': {'n': 1655, 'net_usd': 32.77, 'ort_islem_usd': 0.02, 'pf': 1.0009, 't': 0.0148, 'max_dd_usd': 1881.98}, 'sertifika_karari': 'KALDI', 'basarisiz_kriterler': ['2026 PF >= 1,15', '2026 t >= 2,0', 'azami düşüş <= 300$'], 'sonuc': 'Canlı işlem KİLİTLİ; bot yalnızca paper modda çalışır.'}, 'paper_boru_hatti_testi_25dk': {'tarama': 6, 'aday': 144, 'emir': 19, 'dolum': 10, 'iptal': 8, 'kapanan_islem': 8, 'kazanan': 2, 'kaybeden': 6, 'net_usd': -14.34, 'komisyon_usd': 2.51, 'pf': 0.577, 'veri_hatasi': 0, 'not': 'Boru hattı doğrulamasıdır, strateji kârlılık kanıtı değildir.'}, 'dogrulama': '51 birim/entegrasyon testi geçiyor (orijinal çok dosyalı projede).', 'kullanim': ['python ACARBOT_TEK_DOSYA.py ozet', 'python ACARBOT_TEK_DOSYA.py kapi', 'python ACARBOT_TEK_DOSYA.py tara', 'python ACARBOT_TEK_DOSYA.py paper --sure 3600 --dizin veri/paper1', 'python ACARBOT_TEK_DOSYA.py durum --dizin veri/paper1', 'python ACARBOT_TEK_DOSYA.py canli  (sertifika KALDI olduğu için kilitli)']}

GOMULU_SERTIFIKALAR = {'pump_short': {'strateji': 'pump_short', 'surum': 1, 'parametreler': {'vs_min': 30.0, 'r1_min': 0.05, 'liq_min': 2000000.0, 'stop': 0.065, 'hold_bars': 288, 'ttl_bars': 12, 'cooldown_bars': 288}, 'uretim_utc': '2026-11-11T17:54:40Z', 'veri': 'Binance USDT-M 5dk, 2022-01..2026-10, delist dahil 695 kripto sembol', 'protokol': 'tasarim 2022-2025, son test 2026 (dokunulmamis)', 'kriterler': {'oos_min_trades': 300, 'oos_min_pf': 1.15, 'oos_min_t': 2.0, 'min_positive_years': 4, 'last_year_positive': True, 'max_dd_frac_of_equity': 0.3, 'stress_min_pf': 1.0}, 'tasarim_2022_2025': {'n': 3061, 'net': 7696.581, 'avg': 2.5144, 'wr': 0.4417, 'pf': 1.1377, 'aw': 47.0407, 'al': -32.7106, 'dd': 1146.7475, 'sharpe': 1.2924, 't': 2.5723, 'days': 1447}, 'son_test_2026': {'n': 1655, 'net': 32.7731, 'avg': 0.0198, 'wr': 0.368, 'pf': 1.0009, 'aw': 57.7914, 'al': -33.6158, 'dd': 1881.9764, 'sharpe': 0.0162, 't': 0.0148, 'days': 304}, 'bes_yil': {'n': 4716, 'net': 7729.3541, 'avg': 1.639, 'wr': 0.4158, 'pf': 1.0849, 'aw': 50.3794, 'al': -33.0543, 'dd': 1881.9764, 'sharpe': 0.9486, 't': 2.0766, 'days': 1750}, 'stres_bes_yil': {'n': 4677, 'net': 1576.3404, 'avg': 0.337, 'wr': 0.4103, 'pf': 1.0167, 'aw': 50.1451, 'al': -34.3191, 'dd': 3607.5742, 'sharpe': 0.1926, 't': 0.4216, 'days': 1750}, 'stres_2026': {'n': 1644, 'net': -2451.465, 'avg': -1.4912, 'wr': 0.3619, 'pf': 0.933, 'aw': 57.3547, 'al': -34.8689, 'dd': 3080.8102, 'sharpe': -1.2068, 't': -1.0996, 'days': 304}, 'yillar': {'2022': {'n': 306, 'net': 2684.5054, 'avg': 8.7729, 'wr': 0.5425, 'pf': 1.5775, 'aw': 44.1754, 'al': -33.2043, 'dd': 546.2092, 'sharpe': 2.8151, 't': 2.7488, 'days': 349}, '2023': {'n': 465, 'net': 1324.1192, 'avg': 2.8476, 'wr': 0.4925, 'pf': 1.1753, 'aw': 38.7669, 'al': -32.0064, 'dd': 443.9907, 'sharpe': 1.3992, 't': 1.3954, 'days': 364}, '2024': {'n': 599, 'net': -427.1511, 'avg': -0.7131, 'wr': 0.4524, 'pf': 0.959, 'aw': 36.9058, 'al': -31.7946, 'dd': 1146.7475, 'sharpe': -0.4067, 't': -0.4067, 'days': 366}, '2025': {'n': 1691, 'net': 4115.1076, 'avg': 2.4335, 'wr': 0.4057, 'pf': 1.1237, 'aw': 54.4997, 'al': -33.1062, 'dd': 948.9905, 'sharpe': 1.6841, 't': 1.6818, 'days': 365}, '2026': {'n': 1655, 'net': 32.7731, 'avg': 0.0198, 'wr': 0.368, 'pf': 1.0009, 'aw': 57.7914, 'al': -33.6158, 'dd': 1881.9764, 'sharpe': 0.0162, 't': 0.0148, 'days': 304}}, 'kontroller': {'oos_islem_sayisi': {'gecti': True, 'deger': 1655}, 'oos_profit_factor': {'gecti': False, 'deger': 1.0009}, 'oos_t_istatistigi': {'gecti': False, 'deger': 0.0148}, 'pozitif_yil_sayisi': {'gecti': True, 'deger': 4}, 'son_yil_pozitif': {'gecti': True, 'deger': 32.7731}, 'maks_dusus_kasa_orani': {'gecti': False, 'deger': 1881.9764}, 'maliyet_stresi_pf': {'gecti': True, 'deger': 1.0167}}, 'karar': 'KALDI'}}

# ======================================================================
# MODÜL: acarbot/config.py
# ======================================================================
"""Ayarlar. Kullanıcının SABİT kuralları varsayılandır: 1000$ kasa, işlem başına 50$ teminat, 10x, maker giriş, sınırsız işlem."""


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    # --- sabit kurallar ---
    equity_usd: float = 1000.0          # kasa
    margin_usd: float = 50.0            # işlem başına teminat
    leverage: int = 10                  # sabit kaldıraç
    margin_mode: str = "isolated"       # isolated: bir pozisyonun kaybı kendi teminatıyla sınırlı
    max_positions: int = 0              # 0 = sınırsız (tek sınır serbest teminat)
    entry_post_only: bool = False        # maker
    # --- borsalar ---
    exchanges: tuple = ("binance", "okx")
    binance_public_www: str = "auto"    # auto | 1 | 0  (fapi 451 dönerse www.binance.com public rotası)
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    # --- risk ---
    fee_reserve_frac: float = 0.03      # kasadan komisyon/funding için ayrılan pay
    one_position_per_coin: bool = True  # aynı coin iki borsada birden açılmaz
    daily_loss_limit_usd: float = 150.0
    weekly_loss_limit_usd: float = 300.0
    max_drawdown_usd: float = 400.0     # kalıcı durdurma (elle kaldırılır)
    liq_mmr_assumed: float = 0.025      # bakım teminatı varsayımı (stop tasfiyeden önce kalsın diye)
    liq_safety: float = 0.90
    # --- strateji ---
    strategy: str = "pump_short"
    vs_min: float = 30.0                # son 1 saat hacmi / önceki 7 günün saatlik ortalaması
    r1_min: float = 0.05                # son 1 saat getirisi
    liq_min_usd: float = 2_000_000.0    # önceki 7 günün günlük ortalama hacmi
    min_age_hours: int = 336            # en az 14 günlük geçmiş
    stop_frac: float = 0.065
    tp_frac: float = 0.0                # 0 = kâr-al yok, süre çıkışı
    max_hold_sec: int = 86_400
    entry_ttl_sec: int = 3_600
    cooldown_sec: int = 86_400
    # --- çalışma ---
    mode: str = "paper"                 # paper | live
    scan_interval_sec: int = 300
    manage_interval_sec: int = 20
    max_candidates_per_scan: int = 12
    state_dir: str = "calisma"
    cert_dir: str = "sertifikalar"
    # paper dolum modeli (araştırmayla aynı)
    paper_through: float = 0.0005
    paper_stop_slip: float = 0.002
    paper_exit_slip: float = 0.0005
    # canlı kilitler
    confirm_live: str = ""              # "EVET" olmalı
    accept_unvalidated: str = ""        # sertifikasız stratejiyle canlı için: "RISKI_KABUL_EDIYORUM"
    # API
    binance_key: str = field(default="", repr=False)
    binance_secret: str = field(default="", repr=False)
    okx_key: str = field(default="", repr=False)
    okx_secret: str = field(default="", repr=False)
    okx_passphrase: str = field(default="", repr=False)
    binance_demo: bool = False
    okx_demo: bool = False

    @property
    def notional_usd(self) -> float:
        return self.margin_usd * self.leverage

    @property
    def max_slots(self) -> int:
        usable = self.equity_usd * (1.0 - self.fee_reserve_frac)
        n = int(usable // self.margin_usd)
        return min(n, self.max_positions) if self.max_positions > 0 else n

    def validate(self) -> list[str]:
        e = []
        if self.margin_usd <= 0 or self.equity_usd <= 0: e.append("kasa ve teminat pozitif olmalı")
        if self.leverage < 1: e.append("kaldıraç >= 1 olmalı")
        if self.margin_mode not in ("isolated", "cross"): e.append("margin_mode isolated|cross olmalı")
        if self.mode not in ("paper", "live"): e.append("mode paper|live olmalı")
        if not (0 < self.stop_frac < 1): e.append("stop_frac (0,1) aralığında olmalı")
        if self.margin_mode == "isolated" and self.stop_frac > self.max_safe_stop():
            e.append(f"stop %{self.stop_frac*100:.1f} izole {self.leverage}x tasfiye mesafesine fazla yakın (güvenli üst sınır %{self.max_safe_stop()*100:.2f})")
        if not self.exchanges: e.append("en az bir borsa gerekli")
        return e

    def max_safe_stop(self) -> float:
        return max(0.0, (1.0 / self.leverage - self.liq_mmr_assumed) * self.liq_safety)


_ENV_PREFIX = "ACARBOT_"


def load_settings(env_file: str = ".env", **overrides) -> Settings:
    _load_dotenv(env_file)
    vals = {}
    for f in fields(Settings):
        raw = os.environ.get(_ENV_PREFIX + f.name.upper())
        if raw is None or raw == "":
            continue
        t = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "str")
        if t == "bool": vals[f.name] = raw.strip().lower() in ("1", "true", "yes", "evet")
        elif t == "int": vals[f.name] = int(float(raw))
        elif t == "float": vals[f.name] = float(raw)
        elif t == "tuple": vals[f.name] = tuple(x.strip().lower() for x in raw.split(",") if x.strip())
        else: vals[f.name] = raw
    vals.update({k: v for k, v in overrides.items() if v is not None})
    s = replace(Settings(), **vals)
    errs = s.validate()
    if errs:
        raise ValueError("Ayar hatası: " + "; ".join(errs))
    return s


# ======================================================================
# MODÜL: acarbot/models.py
# ======================================================================
LONG, SHORT = 1, -1


@dataclass(frozen=True)
class Instrument:
    exchange: str
    symbol: str                 # ccxt birleşik sembol, ör. BTC/USDT:USDT
    base: str                   # ör. BTC (1000PEPE -> PEPE olarak normalize edilir)
    contract_size: float = 1.0  # 1 kontrat = kaç coin
    amount_step: float = 0.0    # miktar adımı (kontrat cinsinden)
    min_amount: float = 0.0
    min_cost: float = 0.0
    price_tick: float = 0.0
    listed_ms: int = 0          # borsada listelenme ani (ms); 0 = bilinmiyor


@dataclass
class Features:
    r1h: float          # son 1 saat getirisi (tamamlanmış 5dk barlar)
    vs: float           # hacim şoku: son 1s hacim / önceki 7g saatlik ortalama
    liq_usd: float      # önceki 7 günün günlük ortalama hacmi
    age_hours: float
    last_close: float
    bar_ts: int         # son tamamlanmış 5dk barın açılış zamanı (ms)


@dataclass
class Signal:
    exchange: str
    symbol: str
    base: str
    side: int
    limit_price: float
    stop_frac: float
    tp_frac: float
    ttl_sec: int
    max_hold_sec: int
    reason: str
    features: dict = field(default_factory=dict)


@dataclass
class Position:
    id: str
    exchange: str
    symbol: str
    base: str
    side: int
    qty: float                 # kontrat adedi
    contract_size: float
    limit_price: float
    stop_frac: float
    tp_frac: float
    created_ts: float
    expire_ts: float           # giriş emri son geçerlilik
    max_hold_sec: int
    status: str = "PENDING"    # PENDING -> OPEN -> CLOSED | CANCELLED
    entry_order_id: Optional[str] = None
    stop_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    entry_price: float = 0.0
    entry_ts: float = 0.0
    exit_price: float = 0.0
    exit_ts: float = 0.0
    exit_reason: str = ""
    fees_usd: float = 0.0
    funding_usd: float = 0.0
    pnl_usd: float = 0.0       # net (komisyon + funding dahil)
    last_check_ms: int = 0     # paper: son işlenen mum zamanı
    reason: str = ""
    features: dict = field(default_factory=dict)

    @property
    def notional(self) -> float:
        px = self.entry_price or self.limit_price
        return self.qty * self.contract_size * px

    @property
    def stop_price(self) -> float:
        px = self.entry_price or self.limit_price
        return px * (1.0 - self.side * self.stop_frac)

    @property
    def tp_price(self) -> float:
        if self.tp_frac <= 0: return 0.0
        px = self.entry_price or self.limit_price
        return px * (1.0 + self.side * self.tp_frac)

    def to_dict(self) -> dict:
        return asdict(self)


# ======================================================================
# MODÜL: acarbot/rules.py
# ======================================================================
"""Sabit kural matematiği (saf fonksiyonlar): miktar, stop, tasfiye güvenliği, net PnL."""


def floor_step(x: float, step: float) -> float:
    if step <= 0: return x
    return math.floor(x / step + 1e-9) * step


def round_tick(price: float, tick: float, side: int, passive: bool = True) -> float:
    """Fiyatı tick'e yuvarlar. passive=True: emri DAHA PASİF yapar (alış aşağı, satış yukarı) -> post-only reddi azalır."""
    if tick <= 0: return price
    n = price / tick
    if (side > 0) == passive: return math.floor(n + 1e-9) * tick     # alış & pasif -> aşağı ; satış & agresif -> aşağı
    return math.ceil(n - 1e-9) * tick


def contracts_for_notional(notional_usd: float, price: float, inst: Instrument) -> float:
    """Hedef nominal için kontrat adedi (aşağı yuvarlanır). Borsa minimumlarını karşılamıyorsa 0."""
    if price <= 0 or inst.contract_size <= 0: return 0.0
    q = floor_step(notional_usd / (price * inst.contract_size), inst.amount_step)
    if q <= 0 or q < inst.min_amount: return 0.0
    if inst.min_cost and q * inst.contract_size * price < inst.min_cost: return 0.0
    return q


def liquidation_distance(leverage: int, mmr: float) -> float:
    """İzole pozisyonda yaklaşık tasfiye mesafesi (fiyat kesri)."""
    return max(0.0, 1.0 / leverage - mmr)


def stop_price(entry: float, side: int, stop_frac: float) -> float:

################################################################################
# BOT: 14_GPT_V22
################################################################################


# --- 14_GPT_V22/phoenix/signal.py (bulunamadi) ---


# --- 14_GPT_V22/phoenix/config.py ---

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from dataclasses import dataclass, field
from typing import Mapping


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, "") else float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw in (None, "") else int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Validated PHOENIX runtime configuration. Secrets are never stored here."""
    reference_equity: float = 1000.0
    # Fixed order exposure (not margin). At 10x, $50 notional reserves about $5 margin.
    entry_notional_usd: float = 50.0
    leverage: int = 10
    max_loss_usd: float = 20.0
    # Stop distance is additionally capped to a conservative fraction of 1/leverage.
    # This is a pre-liquidation buffer heuristic, NOT an exchange liquidation-price guarantee.
    liquidation_buffer_fraction: float = 0.70
    fee_bps_per_side: float = 5.5
    slippage_bps_reserve: float = 3.0
    maker_timeout_sec: int = 45
    requote_bps: float = 1.0
    tp_r: float = 1.0  # İYİLEŞTİRME: yakın kâr hedefi (2.2 ulaşılmıyordu)
    max_hold_bars: int = 96
    # V20: 0.72 -> 0.30. score = sum(w*component)/sum(w) is a weighted AVERAGE of components
    # in [-1, 1]; 0.72 was unreachable (max measured |score| 0.66 over 1087 live candidates).
    min_score: float = 0.30
    max_spread_bps: float = 12.0
    min_quote_volume_usd: float = 1_000_000.0
    stale_book_sec: float = 3.0
    universe_refresh_sec: int = 300
    max_reserved_margin_pct: float = 1.0
    correlation_window: int = 96
    correlation_limit: float = 0.85
    risk_per_trade_usd: float = 20.0
    daily_loss_limit_usd: float = 100.0
    weekly_loss_limit_usd: float = 250.0
    max_drawdown_pct: float = 0.20
    # 0 means no arbitrary position-count cap; margin/equity and risk gates remain active.
    max_open_positions: int = 0
    funding_scale: float = 0.0005
    # --- V20 strategy gate (shadow-counted even when off) ---
    require_alignment: bool = False
    alignment_min: float = 0.10
    # --- V20 correlation gate ---
    correlation_min_samples: int = 30
    correlation_same_direction_only: bool = True
    atr_stop_multiplier: float = 2.0
    paper_stop_fill: str = "worse"  # conservative: worse of stop and observed mark
    # --- V20 maker execution ---
    max_requotes: int = 2
    max_chase_bps: float = 10.0
    auto_bump_max_factor: float = 1.0
    okx_td_mode: str = "cross"
    okx_pos_mode: str = "net"
    binance_pos_mode: str = "oneway"
    paper_state_path: str = "paper_state.json"
    paper_journal_path: str = "paper_trades.jsonl"
    oi_change_scale: float = 100.0
    oi_lookback_sec: int = 300
    state_path: str = "state.json"
    journal_path: str = "trades.jsonl"
    strategy_weights: dict[str, float] = field(default_factory=lambda: {
        "trend": .35, "htf": .20, "oi": .15, "book": .15, "funding": .05, "liquidation": .10
    })

    def __post_init__(self):
        weights = dict(self.strategy_weights)
        if not weights or any(float(v) < 0 for v in weights.values()) or sum(float(v) for v in weights.values()) <= 0:
            raise ValueError("strategy_weights must contain non-negative weights with a positive total")
        object.__setattr__(self, "strategy_weights", weights)
        if self.reference_equity <= 0:
            raise ValueError("reference_equity must be > 0")
        if self.entry_notional_usd <= 0 or self.max_loss_usd <= 0 or self.risk_per_trade_usd <= 0:
            raise ValueError("margin/risk limits must be > 0")
        if not 1 <= self.leverage <= 125:
            raise ValueError("leverage must be between 1 and 125")
        if not 0 < self.liquidation_buffer_fraction < 1:
            raise ValueError("liquidation_buffer_fraction must be in (0, 1)")
        if self.fee_bps_per_side < 0 or self.slippage_bps_reserve < 0:
            raise ValueError("fee/slippage cannot be negative")
        if self.maker_timeout_sec <= 0 or self.requote_bps < 0:
            raise ValueError("maker timeout must be > 0 and requote_bps >= 0")
        if not 0 < self.max_reserved_margin_pct <= 1:
            raise ValueError("max_reserved_margin_pct must be in (0, 1]")
        if not 0 < self.correlation_limit <= 1:
            raise ValueError("correlation_limit must be in (0, 1]")
        if self.correlation_window < 3:
            raise ValueError("correlation_window must be >= 3")
        if not 0 < self.max_drawdown_pct <= 1:
            raise ValueError("max_drawdown_pct must be in (0, 1]")
        if self.daily_loss_limit_usd <= 0 or self.weekly_loss_limit_usd <= 0:
            raise ValueError("loss limits must be > 0")
        if self.max_open_positions < 0:
            raise ValueError("max_open_positions must be >= 0 (0 = unlimited)")
        if self.paper_stop_fill not in {"stop", "worse"}:
            raise ValueError("paper_stop_fill must be stop or worse")
        if self.atr_stop_multiplier <= 0:
            raise ValueError("atr_stop_multiplier must be > 0")
        if not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be in [0, 1]")
        if self.max_spread_bps <= 0 or self.min_quote_volume_usd <= 0:
            raise ValueError("spread and volume limits must be > 0")
        if self.stale_book_sec <= 0 or self.universe_refresh_sec <= 0:
            raise ValueError("stale_book_sec and universe_refresh_sec must be > 0")
        if self.tp_r <= 0 or self.max_hold_bars < 1:
            raise ValueError("tp_r must be > 0 and max_hold_bars >= 1")
        if self.funding_scale <= 0:
            raise ValueError("funding_scale must be > 0")
        if not 0 <= self.alignment_min <= 1:
            raise ValueError("alignment_min must be in [0, 1]")
        if self.correlation_min_samples < 3:
            raise ValueError("correlation_min_samples must be >= 3")
        if self.max_requotes < 0 or self.max_chase_bps < 0 or self.auto_bump_max_factor < 0:
            raise ValueError("max_requotes/max_chase_bps/auto_bump_max_factor cannot be negative")
        if self.okx_pos_mode not in {"net", "long_short"}:
            raise ValueError("okx_pos_mode must be 'net' or 'long_short'")
        if self.binance_pos_mode not in {"oneway", "hedge"}:
            raise ValueError("binance_pos_mode must be 'oneway' or 'hedge'")
        if self.okx_td_mode != "cross":
            raise ValueError("cross margin is mandatory; isolated mode is not supported")
        if self.oi_change_scale <= 0 or self.oi_lookback_sec <= 0:
            raise ValueError("oi_change_scale and oi_lookback_sec must be > 0")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """Load every non-secret runtime parameter from environment variables."""
        e = os.environ if env is None else env
        weights = {
            "trend": float(e.get("PHOENIX_WEIGHT_TREND", .35)),
            "htf": float(e.get("PHOENIX_WEIGHT_HTF", .20)),
            "oi": float(e.get("PHOENIX_WEIGHT_OI", .15)),
            "book": float(e.get("PHOENIX_WEIGHT_BOOK", .15)),
            "funding": float(e.get("PHOENIX_WEIGHT_FUNDING", .05)),
            "liquidation": float(e.get("PHOENIX_WEIGHT_LIQUIDATION", .10)),
        }
        def f(n, d): return d if e.get(n) in (None, "") else float(e[n])
        def i(n, d): return d if e.get(n) in (None, "") else int(e[n])
        def b(n, d): return d if e.get(n) in (None, "") else str(e[n]).strip().lower() in {"1", "true", "yes", "on"}
        return cls(
            reference_equity=f("PHOENIX_REFERENCE_EQUITY",1000),
            # Position size is always USD notional. Legacy margin-named variables
            # are intentionally ignored to prevent accidental 10x exposure inflation.
            entry_notional_usd=f("PHOENIX_ENTRY_NOTIONAL_USD", 50),
            leverage=i("PHOENIX_LEVERAGE",10), max_loss_usd=f("PHOENIX_MAX_LOSS_USD",20),
            liquidation_buffer_fraction=f("PHOENIX_LIQUIDATION_BUFFER_FRACTION",.70),
            fee_bps_per_side=f("PHOENIX_FEE_BPS_PER_SIDE",5.5), slippage_bps_reserve=f("PHOENIX_SLIPPAGE_BPS_RESERVE",3),
            maker_timeout_sec=i("PHOENIX_MAKER_TIMEOUT_SEC",45), requote_bps=f("PHOENIX_REQUOTE_BPS",1),
            tp_r=f("PHOENIX_TP_R",1.0), max_hold_bars=i("PHOENIX_MAX_HOLD_BARS",96), min_score=f("PHOENIX_MIN_SCORE",.30),
            max_spread_bps=f("PHOENIX_MAX_SPREAD_BPS",12), min_quote_volume_usd=f("PHOENIX_MIN_QUOTE_VOLUME_USD",1_000_000),
            stale_book_sec=f("PHOENIX_STALE_BOOK_SEC",3), universe_refresh_sec=i("PHOENIX_UNIVERSE_REFRESH_SEC",300),
            max_reserved_margin_pct=f("PHOENIX_MAX_RESERVED_MARGIN_PCT",1.0), correlation_window=i("PHOENIX_CORRELATION_WINDOW",96),
            correlation_limit=f("PHOENIX_CORRELATION_LIMIT",.85), risk_per_trade_usd=f("PHOENIX_RISK_PER_TRADE_USD",20),
            daily_loss_limit_usd=f("PHOENIX_DAILY_LOSS_LIMIT_USD",100), weekly_loss_limit_usd=f("PHOENIX_WEEKLY_LOSS_LIMIT_USD",250),
            max_drawdown_pct=f("PHOENIX_MAX_DRAWDOWN_PCT",.20), max_open_positions=i("PHOENIX_MAX_OPEN_POSITIONS",0),
            funding_scale=f("PHOENIX_FUNDING_SCALE",.0005), oi_change_scale=f("PHOENIX_OI_CHANGE_SCALE",100.0),
            oi_lookback_sec=i("PHOENIX_OI_LOOKBACK_SEC",300), state_path=e.get("PHOENIX_STATE_PATH","state.json"),
            journal_path=e.get("PHOENIX_JOURNAL_PATH","trades.jsonl"), strategy_weights=weights,
            require_alignment=b("PHOENIX_REQUIRE_ALIGNMENT",False), alignment_min=f("PHOENIX_ALIGNMENT_MIN",.10),
            correlation_min_samples=i("PHOENIX_CORRELATION_MIN_SAMPLES",30),
            correlation_same_direction_only=b("PHOENIX_CORRELATION_SAME_DIRECTION_ONLY",True),
            atr_stop_multiplier=f("PHOENIX_ATR_STOP_MULTIPLIER",2.0),
            paper_stop_fill=str(e.get("PHOENIX_PAPER_STOP_FILL","worse") or "worse").strip().lower(),
            max_requotes=i("PHOENIX_MAX_REQUOTES",2), max_chase_bps=f("PHOENIX_MAX_CHASE_BPS",10),
            auto_bump_max_factor=f("PHOENIX_AUTO_BUMP_MAX_FACTOR",1.0),
            okx_td_mode="cross", okx_pos_mode=e.get("PHOENIX_OKX_POS_MODE","net"),
            binance_pos_mode=e.get("PHOENIX_BINANCE_POS_MODE","oneway"),
            paper_state_path=e.get("PHOENIX_PAPER_STATE_PATH","paper_state.json"),
            paper_journal_path=e.get("PHOENIX_PAPER_JOURNAL_PATH","paper_trades.jsonl"),
        )


################################################################################
# BOT: 15_V22_5_CLAUDE
################################################################################


# --- 15_V22_5_CLAUDE/phoenix/signal.py (bulunamadi) ---


# --- 15_V22_5_CLAUDE/phoenix/config.py ---

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from dataclasses import dataclass, field
from typing import Mapping


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, "") else float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw in (None, "") else int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Validated PHOENIX runtime configuration. Secrets are never stored here."""
    reference_equity: float = 1000.0
    # USER RULE (V22.0.5): every entry is a fixed $50 NOTIONAL position. At 10x that is ~$5 margin.
    # (V22.0.4 had $50 MARGIN x 10 = $500 notional, which broke this rule.)
    entry_notional_usd: float = 50.0
    leverage: int = 10
    # İYİLEŞTİRME (1s test analizi): max_loss_usd 20.0 -> 3.5.
    # Eski değer $50 notionalde %40 stop demekti — likidasyon mesafesi (~%8) ÖTESİNDEYDİ.
    # Canlıda stop dolmadan pozisyon likide olurdu. Yeni değer %7 stop (GPT_V22 ile aynı),
    # likidasyon mesafesi içinde kalır.
    max_loss_usd: float = 3.5
    fee_bps_per_side: float = 5.5
    slippage_bps_reserve: float = 3.0
    maker_timeout_sec: int = 45
    requote_bps: float = 1.0
    tp_r: float = 1.0  # İYİLEŞTİRME: yakın kâr hedefi (2.2 ulaşılmıyordu)
    max_hold_bars: int = 96
    # V20: 0.72 -> 0.30. score = sum(w*component)/sum(w) is a weighted AVERAGE of components
    # in [-1, 1]; 0.72 was unreachable (max measured |score| 0.66 over 1087 live candidates).
    min_score: float = 0.30
    max_spread_bps: float = 12.0
    min_quote_volume_usd: float = 1_000_000.0
    stale_book_sec: float = 3.0
    universe_refresh_sec: int = 300
    max_reserved_margin_pct: float = 1.0
    correlation_window: int = 96
    correlation_limit: float = 0.85
    risk_per_trade_usd: float = 20.0
    # Portfolio kill-switches are OFF by default (user rule: bot keeps trading 24/7, no daily/weekly loss stop).
    # daily/weekly: 0 = disabled. max_drawdown_pct: 1.0 = disabled. Set positive values to re-enable.
    daily_loss_limit_usd: float = 0.0
    weekly_loss_limit_usd: float = 0.0
    max_drawdown_pct: float = 1.0
    # 0 means no arbitrary position-count cap; margin/equity and risk gates remain active.
    max_open_positions: int = 0
    funding_scale: float = 0.0005
    # --- V20 strategy gate (shadow-counted even when off) ---
    require_alignment: bool = False
    alignment_min: float = 0.10
    # --- V20 correlation gate ---
    correlation_min_samples: int = 30
    correlation_same_direction_only: bool = True
    atr_stop_multiplier: float = 0.0   # 0 = ATR never touches the stop: stop is the fixed -max_loss_usd rule
    # Take profit is decided by indicators: while the position is net-profitable (>= tp_min_net_usd after
    # fees/slippage) it is closed when the signed score in the position direction drops below tp_exit_score.
    # tp_mode=fixed_rr restores the old fixed R-multiple target (tp_r).
    tp_mode: str = "indicator"
    tp_exit_score: float = 0.10
    tp_min_net_usd: float = 0.10   # 0.2% of the $50 notional (was 1.0 for $500)
    exit_eval_budget_sec: int = 40
    paper_stop_fill: str = "worse"  # conservative: worse of stop and observed mark
    # --- V20 maker execution ---
    max_requotes: int = 2
    max_chase_bps: float = 10.0
    auto_bump_max_factor: float = 1.0
    okx_td_mode: str = "cross"
    okx_pos_mode: str = "net"
    binance_pos_mode: str = "oneway"
    paper_state_path: str = "paper_state.json"
    paper_journal_path: str = "paper_trades.jsonl"
    oi_change_scale: float = 100.0
    oi_lookback_sec: int = 300
    strict_liquidation_guard: bool = False
    state_path: str = "state.json"
    journal_path: str = "trades.jsonl"
    strategy_weights: dict[str, float] = field(default_factory=lambda: {
        "trend": .35, "htf": .20, "oi": .15, "book": .15, "funding": .05, "liquidation": .10
    })

    @property
    def entry_margin_usd(self) -> float:
        """Derived: notional / leverage (50 / 10 = ~5 USD margin per position)."""
        return self.entry_notional_usd / self.leverage

    @property
    def stop_distance_pct_estimate(self) -> float:
        """Approx. price distance of the -max_loss_usd stop, as a fraction of entry (before fees)."""
        return self.max_loss_usd / self.entry_notional_usd

    @property
    def stop_beyond_liquidation(self) -> bool:
        """True when the modeled stop sits at/after the isolated-margin liquidation distance (~0.8/leverage)."""
        return self.stop_distance_pct_estimate >= 0.8 / self.leverage

    def __post_init__(self):
        weights = dict(self.strategy_weights)
        if not weights or any(float(v) < 0 for v in weights.values()) or sum(float(v) for v in weights.values()) <= 0:
            raise ValueError("strategy_weights must contain non-negative weights with a positive total")
        object.__setattr__(self, "strategy_weights", weights)
        if self.reference_equity <= 0:
            raise ValueError("reference_equity must be > 0")
        if self.entry_notional_usd <= 0 or self.max_loss_usd <= 0 or self.risk_per_trade_usd <= 0:
            raise ValueError("margin/risk limits must be > 0")
        if not 1 <= self.leverage <= 125:
            raise ValueError("leverage must be between 1 and 125")
        if self.fee_bps_per_side < 0 or self.slippage_bps_reserve < 0:
            raise ValueError("fee/slippage cannot be negative")
        if self.maker_timeout_sec <= 0 or self.requote_bps < 0:
            raise ValueError("maker timeout must be > 0 and requote_bps >= 0")
        if not 0 < self.max_reserved_margin_pct <= 1:
            raise ValueError("max_reserved_margin_pct must be in (0, 1]")
        if not 0 < self.correlation_limit <= 1:
            raise ValueError("correlation_limit must be in (0, 1]")
        if self.correlation_window < 3:
            raise ValueError("correlation_window must be >= 3")
        if not 0 < self.max_drawdown_pct <= 1:
            raise ValueError("max_drawdown_pct must be in (0, 1] (1.0 = disabled)")
        if self.daily_loss_limit_usd < 0 or self.weekly_loss_limit_usd < 0:
            raise ValueError("loss limits must be >= 0 (0 = disabled)")
        if self.max_open_positions < 0:
            raise ValueError("max_open_positions must be >= 0 (0 = unlimited)")
        if self.paper_stop_fill not in {"stop", "worse"}:
            raise ValueError("paper_stop_fill must be stop or worse")
        if self.atr_stop_multiplier < 0:
            raise ValueError("atr_stop_multiplier must be >= 0 (0 = off)")
        if self.tp_mode not in {"indicator", "fixed_rr"}:
            raise ValueError("tp_mode must be indicator or fixed_rr")
        if not 0 <= self.tp_exit_score <= 1 or self.tp_min_net_usd < 0 or self.exit_eval_budget_sec < 1:
            raise ValueError("tp_exit_score must be in [0, 1], tp_min_net_usd >= 0, exit_eval_budget_sec >= 1")
        # With $50 notional @10x a -$20 stop is ~40% away, i.e. beyond isolated liquidation (~10%).
        # Not an error (user rule) but surfaced loudly: stop_beyond_liquidation / report config_echo.
        # strict_liquidation_guard=True restores the old hard refusal.
        if self.strict_liquidation_guard and self.stop_beyond_liquidation:
            raise ValueError("max_loss_usd is too large for this notional/leverage: the stop would sit at or beyond liquidation")
        if not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be in [0, 1]")
        if self.max_spread_bps <= 0 or self.min_quote_volume_usd <= 0:
            raise ValueError("spread and volume limits must be > 0")
        if self.stale_book_sec <= 0 or self.universe_refresh_sec <= 0:
            raise ValueError("stale_book_sec and universe_refresh_sec must be > 0")
        if self.tp_r <= 0 or self.max_hold_bars < 1:
            raise ValueError("tp_r must be > 0 and max_hold_bars >= 1")
        if self.funding_scale <= 0:
            raise ValueError("funding_scale must be > 0")
        if not 0 <= self.alignment_min <= 1:
            raise ValueError("alignment_min must be in [0, 1]")
        if self.correlation_min_samples < 3:
            raise ValueError("correlation_min_samples must be >= 3")
        if self.max_requotes < 0 or self.max_chase_bps < 0 or self.auto_bump_max_factor < 0:
            raise ValueError("max_requotes/max_chase_bps/auto_bump_max_factor cannot be negative")
        if self.okx_pos_mode not in {"net", "long_short"}:
            raise ValueError("okx_pos_mode must be 'net' or 'long_short'")
        if self.binance_pos_mode not in {"oneway", "hedge"}:
            raise ValueError("binance_pos_mode must be 'oneway' or 'hedge'")
        if self.okx_td_mode not in {"cross", "isolated"}:
            raise ValueError("okx_td_mode must be 'cross' or 'isolated'")
        if self.oi_change_scale <= 0 or self.oi_lookback_sec <= 0:
            raise ValueError("oi_change_scale and oi_lookback_sec must be > 0")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """Load every non-secret runtime parameter from environment variables."""
        e = os.environ if env is None else env
        weights = {
            "trend": float(e.get("PHOENIX_WEIGHT_TREND", .35)),
            "htf": float(e.get("PHOENIX_WEIGHT_HTF", .20)),
            "oi": float(e.get("PHOENIX_WEIGHT_OI", .15)),
            "book": float(e.get("PHOENIX_WEIGHT_BOOK", .15)),
            "funding": float(e.get("PHOENIX_WEIGHT_FUNDING", .05)),
            "liquidation": float(e.get("PHOENIX_WEIGHT_LIQUIDATION", .10)),
        }
        if e.get("PHOENIX_ENTRY_MARGIN_USD") not in (None, ""):
            raise ValueError("PHOENIX_ENTRY_MARGIN_USD is no longer supported (it silently produced 500 USD positions): set PHOENIX_ENTRY_NOTIONAL_USD (50) and PHOENIX_LEVERAGE (10); margin = notional / leverage")
        def f(n, d): return d if e.get(n) in (None, "") else float(e[n])
        def i(n, d): return d if e.get(n) in (None, "") else int(e[n])
        def b(n, d): return d if e.get(n) in (None, "") else str(e[n]).strip().lower() in {"1", "true", "yes", "on"}
        return cls(
            reference_equity=f("PHOENIX_REFERENCE_EQUITY",1000),
            entry_notional_usd=f("PHOENIX_ENTRY_NOTIONAL_USD",50),
            leverage=i("PHOENIX_LEVERAGE",10), max_loss_usd=f("PHOENIX_MAX_LOSS_USD",3.5),
            fee_bps_per_side=f("PHOENIX_FEE_BPS_PER_SIDE",5.5), slippage_bps_reserve=f("PHOENIX_SLIPPAGE_BPS_RESERVE",3),
            maker_timeout_sec=i("PHOENIX_MAKER_TIMEOUT_SEC",45), requote_bps=f("PHOENIX_REQUOTE_BPS",1),
            tp_r=f("PHOENIX_TP_R",1.0), max_hold_bars=i("PHOENIX_MAX_HOLD_BARS",96), min_score=f("PHOENIX_MIN_SCORE",.30),
            max_spread_bps=f("PHOENIX_MAX_SPREAD_BPS",12), min_quote_volume_usd=f("PHOENIX_MIN_QUOTE_VOLUME_USD",1_000_000),
            stale_book_sec=f("PHOENIX_STALE_BOOK_SEC",3), universe_refresh_sec=i("PHOENIX_UNIVERSE_REFRESH_SEC",300),
            max_reserved_margin_pct=f("PHOENIX_MAX_RESERVED_MARGIN_PCT",1.0), correlation_window=i("PHOENIX_CORRELATION_WINDOW",96),
            correlation_limit=f("PHOENIX_CORRELATION_LIMIT",.85), risk_per_trade_usd=f("PHOENIX_RISK_PER_TRADE_USD",20),
            daily_loss_limit_usd=f("PHOENIX_DAILY_LOSS_LIMIT_USD",0), weekly_loss_limit_usd=f("PHOENIX_WEEKLY_LOSS_LIMIT_USD",0),
            max_drawdown_pct=f("PHOENIX_MAX_DRAWDOWN_PCT",1.0), max_open_positions=i("PHOENIX_MAX_OPEN_POSITIONS",0),
            funding_scale=f("PHOENIX_FUNDING_SCALE",.0005), oi_change_scale=f("PHOENIX_OI_CHANGE_SCALE",100.0),
            oi_lookback_sec=i("PHOENIX_OI_LOOKBACK_SEC",300), strict_liquidation_guard=b("PHOENIX_STRICT_LIQUIDATION_GUARD",False), state_path=e.get("PHOENIX_STATE_PATH","state.json"),
            journal_path=e.get("PHOENIX_JOURNAL_PATH","trades.jsonl"), strategy_weights=weights,
            require_alignment=b("PHOENIX_REQUIRE_ALIGNMENT",False), alignment_min=f("PHOENIX_ALIGNMENT_MIN",.10),
            correlation_min_samples=i("PHOENIX_CORRELATION_MIN_SAMPLES",30),
            correlation_same_direction_only=b("PHOENIX_CORRELATION_SAME_DIRECTION_ONLY",True),
            atr_stop_multiplier=f("PHOENIX_ATR_STOP_MULTIPLIER",0.0),
            tp_mode=str(e.get("PHOENIX_TP_MODE","indicator") or "indicator").strip().lower(),
            tp_exit_score=f("PHOENIX_TP_EXIT_SCORE",0.10), tp_min_net_usd=f("PHOENIX_TP_MIN_NET_USD",0.10),
            exit_eval_budget_sec=i("PHOENIX_EXIT_EVAL_BUDGET_SEC",40),
            paper_stop_fill=str(e.get("PHOENIX_PAPER_STOP_FILL","worse") or "worse").strip().lower(),
            max_requotes=i("PHOENIX_MAX_REQUOTES",2), max_chase_bps=f("PHOENIX_MAX_CHASE_BPS",10),
            auto_bump_max_factor=f("PHOENIX_AUTO_BUMP_MAX_FACTOR",1.0),
            okx_td_mode=e.get("PHOENIX_OKX_TD_MODE","cross"), okx_pos_mode=e.get("PHOENIX_OKX_POS_MODE","net"),
            binance_pos_mode=e.get("PHOENIX_BINANCE_POS_MODE","oneway"),
            paper_state_path=e.get("PHOENIX_PAPER_STATE_PATH","paper_state.json"),
            paper_journal_path=e.get("PHOENIX_PAPER_JOURNAL_PATH","paper_trades.jsonl"),
        )


################################################################################
# BOT: 16_V29_FUSION
################################################################################


# --- 16_V29_FUSION/acarbot/signal.py ---

"""ANSAMBL SİNYAL MOTORU — V26/V27 grup yaklaşımı + ZERO dersleri.
Gruplar [-1,1] normalize edilir; gruplar arası EŞİT ağırlık kullanılır (V26: indikatör sayısı yanlılığı yok).
- trend: EMA dizilimi + ADX/DMI rejimi (+ supertrend)
- momentum: Wilder RSI (varsayılan) + MACD histogram + ROC + stokastik
- breakout: Donchian/BB/VWAP kırılımı + hacim onayı (V27)
- volume_flow: hacim şoku + CMF + MFI + OBV eğimi (V26)
- derivatives / microstructure: YALNIZ kolonlar gerçekten verilmişse (uydurma yok, V26/V27)
Rejim (ADX) ağırlıkları değiştirir (V27). RSI aşırılığı sert veto DEĞİL yumuşak cezadır (V26).
STOP: ATR×2.2, [0.012, 0.045] kelepçe (V24) + izole tasfiye güvenliği (V23).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .config import Settings
from .features import feature_frame

EPS = 1e-12


@dataclass
class EnsembleResult:
    side: int                       # 1 / -1 / 0 (FLAT)
    score: float                    # grup ortalaması [-1,1]
    confidence: float               # [0,1]
    stop_frac: float
    regime: str                     # trend | range
    reason: str
    groups: dict = field(default_factory=dict)
    blocked: str = ""               # sinyal üretilmediyse gerekçe


def _last(x) -> float:
    try:
        v = float(x.iloc[-1])
    except Exception:
        return float("nan")
    return v


def _at(x, idx: int) -> float:
    """Satır idx'teki değer (backtest O(n): dilim yok, nedensel göstergelerde eşdeğerdir)."""
    try:
        v = float(x.iloc[idx])
    except Exception:
        return float("nan")
    return v


def _clip01(x: float) -> float:
    if not np.isfinite(x): return 0.0
    return float(max(-1.0, min(1.0, x)))


class EnsembleEngine:
    def __init__(self, cfg: Settings):
        self.cfg = cfg

    # ------------------------------------------------------------------ grup puanları
    def _group_trend(self, f: pd.DataFrame, idx: int = -1) -> float:
        e20, e50, e200 = _at(f.ema_20, idx), _at(f.ema_50, idx), _at(f.ema_200, idx)
        if not (np.isfinite(e20) and np.isfinite(e50) and np.isfinite(e200)): return 0.0
        t = 0.4 * np.sign(e20 - e50) + 0.3 * np.sign(e50 - e200)
        adx, pdi, mdi = _at(f.adx, idx), _at(f.plus_di, idx), _at(f.minus_di, idx)
        if np.isfinite(adx) and adx >= self.cfg.adx_min:
            t += 0.3 * np.sign(pdi - mdi)
        return _clip01(t / 1.0)

    def _group_momentum(self, f: pd.DataFrame, idx: int = -1) -> float:
        if self.cfg.rsi_mode == "wilder":
            rsi = _at(f.rsi_wilder, idx)
        elif self.cfg.rsi_mode == "sma":
            rsi = _at(f.rsi_sma, idx)
        else:
            rsi = 50.0
        mom = 0.45 * _clip01((rsi - 50.0) / 20.0) if np.isfinite(rsi) else 0.0
        mh = _at(f.macd_hist, idx)
        mom += 0.25 * (np.sign(mh) if np.isfinite(mh) else 0.0)
        roc = _at(f.roc_12, idx)
        mom += 0.15 * _clip01(roc / 5.0) if np.isfinite(roc) else 0.0
        sk = _at(f.stoch_k, idx)
        mom += 0.15 * _clip01((sk - 50.0) / 30.0) if np.isfinite(sk) else 0.0
        return _clip01(mom)

    def _group_breakout(self, f: pd.DataFrame, idx: int = -1) -> float:
        c, dcu, dcl = _at(f.close, idx), _at(f.dc_up, idx), _at(f.dc_low, idx)
        bbu, bbl, vw, vr = _at(f.bb_up, idx), _at(f.bb_low, idx), _at(f.vwap, idx), _at(f.vol_ratio, idx)
        if not np.isfinite(c): return 0.0
        parts = []
        if np.isfinite(dcu) and dcu > 0: parts.append(_clip01((c / dcu - 1.0) / 0.01))
        if np.isfinite(dcl) and dcl > 0: parts.append(_clip01((c / dcl - 1.0) / 0.01))
        if np.isfinite(bbu) and bbu > 0: parts.append(_clip01((c / bbu - 1.0) / 0.01))
        if np.isfinite(bbl) and bbl > 0: parts.append(_clip01((c / bbl - 1.0) / 0.01))
        if np.isfinite(vw) and vw > 0: parts.append(_clip01((c / vw - 1.0) / 0.01))
        if not parts: return 0.0
        s = float(np.mean(parts))
        # hacim onayı: vol_ratio < 1.0 ise kırılım güvenilirliği düşer (V27 breakout+volume dersi)
        if np.isfinite(vr) and vr < 1.0:
            s *= 0.7
        return _clip01(s)

    def _group_volume_flow(self, f: pd.DataFrame, idx: int = -1) -> float:
        vz, cmfv, mfi = _at(f.vol_z, idx), _at(f.cmf, idx), _at(f.mfi, idx)
        vf = 0.45 * _clip01(vz / 3.0) if np.isfinite(vz) else 0.0
        vf += 0.25 * _clip01(cmfv * 4.0) if np.isfinite(cmfv) else 0.0
        vf += 0.20 * _clip01((mfi - 50.0) / 25.0) if np.isfinite(mfi) else 0.0
        obv = f.obv
        if idx >= 5 or (idx == -1 and len(obv) >= 6):
            o_now, o_then = _at(obv, idx), _at(obv, idx - 5 if idx != -1 else -6)
            vf += 0.10 * (np.sign(o_now - o_then) if np.isfinite(o_now) and np.isfinite(o_then) else 0.0)
        return _clip01(vf)

    def _group_fade(self, f: pd.DataFrame, idx: int = -1) -> float:
        """FADE TERSİNE ÇEVİRME (yeni): pump sonrası fade -> SHORT, dump sonrası bounce -> LONG.

        KGEN örneği: 0.082 -> 0.103 (pump +%9.73) -> 0.090 (fade -%12.7).
        V23 doğru SHORT sinyalini verdi ama maker emir dolmadı.
        V28 yanlış LONG'a girdi (tepe).
        Bu grup: güçlü pump + momentum dönüşü = fade başlangıcı -> ters yön sinyali.
        """
        try:
            c = _at(f.close, idx)
            # Son 4 bar (1 saat) getirisi: pump/dump tespiti
            c_4ago = _at(f.close, idx - 4 if idx != -1 else -5)
            if not (np.isfinite(c) and np.isfinite(c_4ago) and c_4ago > 0):
                return 0.0
            ret_1h = c / c_4ago - 1.0
            # Momentum dönüşü: macd_hist işareti veya stoch dönüşü
            mh = _at(f.macd_hist, idx) if "macd_hist" in f.columns else 0.0
            mh_prev = _at(f.macd_hist, idx - 2 if idx != -1 else -3) if "macd_hist" in f.columns else 0.0
            fade = 0.0
            # Pump sonrası fade: ret_1h güçlü pozitif ama momentum düşüyor
            if ret_1h >= 0.04 and np.isfinite(mh) and np.isfinite(mh_prev) and mh < mh_prev:
                fade = -min(1.0, (ret_1h - 0.04) * 10 + 0.3)  # SHORT sinyali
            # Dump sonrası bounce: ret_1h güçlü negatif ama momentum yükseliyor
            elif ret_1h <= -0.04 and np.isfinite(mh) and np.isfinite(mh_prev) and mh > mh_prev:
                fade = min(1.0, (-ret_1h - 0.04) * 10 + 0.3)  # LONG sinyali
            return _clip01(fade)
        except Exception:
            return 0.0

    def _group_derivatives(self, f: pd.DataFrame, idx: int = -1) -> float:
        """Yalnız sağlanan kolonlar. funding: pozitif funding long için maliyet -> ters işaret (V26)."""
        der, norm = 0.0, 0.0
        for col, w in (("oi_delta_pct", 0.35), ("oi_z", 0.15), ("funding", -0.15),
                       ("basis_pct", 0.15), ("liquidation_delta", 0.20)):
            if col in f.columns:
                x = _at(f[col], idx)
                if np.isfinite(x):
                    der += w * _clip01(x)
                    norm += abs(w)
        return _clip01(der / norm) if norm > 0 else 0.0

    def _group_microstructure(self, f: pd.DataFrame, idx: int = -1) -> float:
        micro, norm = 0.0, 0.0
        for col, w in (("cvd_slope", 0.45), ("taker_imbalance", 0.25), ("orderbook_imbalance", 0.30)):
            if col in f.columns:
                x = _at(f[col], idx)
                if np.isfinite(x):
                    micro += w * _clip01(x)
                    norm += abs(w)
        if "spread_bps" in f.columns:
            sp = _at(f["spread_bps"], idx)
            if np.isfinite(sp) and sp > 15 and norm > 0:
                micro *= 0.6     # geniş spread: mikroyapı güvenilirliği düşer (ZERO spread kapısı)
        return _clip01(micro / norm) if norm > 0 else 0.0

    # ------------------------------------------------------------------ değerlendirme
    def evaluate(self, df: pd.DataFrame, htf: Optional[dict] = None) -> EnsembleResult:
        """df: HAM OHLCV (taban zaman dilimi). htf: {'1h': ohlcv_df, ...} (opsiyonel onay, V26)."""
        f = feature_frame(df)
        return self._evaluate_frame(f, htf)

    def _evaluate_frame(self, f: pd.DataFrame, htf: Optional[dict] = None, idx: int = -1) -> EnsembleResult:
        """f: feature_frame çıktısı. idx: değerlendirilecek satır (backtest'te i; nedensel göstergeler
        nedeniyle f.iloc[:i+1] dilimiyle birebir eşdeğerdir ama O(1)'dir)."""
        cfg = self.cfg
        n_avail = len(f) if idx == -1 else idx + 1
        if n_avail < 260:
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "veri_yetersiz")
        c, natr, rng = _at(f.close, idx), _at(f.natr, idx), _at(f.range_frac, idx)
        if not np.isfinite(c) or c <= 0:
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "fiyat_gecersiz")
        atrv = _at(f.atr, idx)
        if not np.isfinite(atrv) or atrv <= 0:
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "atr_yok")
        # volatilite sağduyu kapısı (V27): aşırı sakin/pahalı piyasa sinyal üretmez
        if not (cfg.min_natr <= natr <= cfg.max_natr) or (np.isfinite(rng) and rng > 0.18):
            return EnsembleResult(0, 0.0, 0.0, cfg.stop_min_frac, "range", "", {}, "volatilite_kapisi")

        groups = {
            "trend": self._group_trend(f, idx),
            "momentum": self._group_momentum(f, idx),
            "breakout": self._group_breakout(f, idx),
            "volume_flow": self._group_volume_flow(f, idx),
        }
        # FADE TERSİNE ÇEVİRME: pump/dump sonrası dönüş -> ters yön.
        # Güçlü fade sinyali varsa skoru ters yöne çevir (V23 pump_short mantığı).
        fade = self._group_fade(f, idx)
        if abs(fade) >= 0.3:
            groups["fade"] = fade
        deriv = self._group_derivatives(f, idx)
        micro = self._group_microstructure(f, idx)
        core = list(groups.values())
        score = float(np.mean(core))                     # çekirdek gruplar eşit ağırlıkta
        coverage = 0.0
        if deriv != 0.0:
            groups["derivatives"] = deriv
            core.append(deriv)
            coverage += 0.5
        if micro != 0.0:
            groups["microstructure"] = micro
            core.append(micro)
            coverage += 0.5
        score = float(np.mean(core))

        # HTF onayı: taban 0.8 + onay 0.2 (V26), onay = EMA20/50 yönü ortalaması
        htf_note = ""
        if htf:
            hs = []
            for tf, hf in htf.items():   # htf değerleri HAZIR feature frame olabilir (backtest) veya ham OHLCV
                try:
                    hf2 = hf if ("ema_20" in getattr(hf, "columns", [])) else feature_frame(hf)
                    h20, h50 = _last(hf2.ema_20), _last(hf2.ema_50)   # HTF: son bar onayı
                    if np.isfinite(h20) and np.isfinite(h50):
                        hs.append(np.sign(h20 - h50))
                        htf_note = f"+htf({','.join(htf.keys())})"
                except Exception:
                    continue
            if hs:
                score = 0.8 * score + 0.2 * float(np.mean(hs))

        # çatışma cezası (ZERO ders 3): trend ile momentum güçlü ve ters yönlüyse puan düşer
        conflict = groups["trend"] * groups["momentum"] < 0 and abs(groups["trend"]) > 0.2 and abs(groups["momentum"]) > 0.2
        if conflict:
            score *= cfg.conflict_penalty

        # RSI yumuşak cezası (V26; sert veto kaldırıldı)
        rsi = _at(f.rsi_wilder if cfg.rsi_mode == "wilder" else f.rsi_sma, idx) if cfg.rsi_mode != "off" else 50.0
        rsi_note = ""
        if np.isfinite(rsi):
            if score > 0 and rsi > cfg.rsi_soft_zone:
                score -= cfg.rsi_soft_penalty
                rsi_note = f"-rsi{rsi:.0f}"
            elif score < 0 and rsi < 100 - cfg.rsi_soft_zone:
                score += cfg.rsi_soft_penalty
                rsi_note = f"+rsi{rsi:.0f}"
        # İYİLEŞTİRME: pump-tepe filtresi — aşırı alım/satımda ters yön engelle
        rsi_blocked = ""
        if np.isfinite(rsi):
            if score > 0 and rsi > cfg.rsi_long_block:
                rsi_blocked = f"rsi_asiri_alim({rsi:.0f})"
            elif score < 0 and rsi < cfg.rsi_short_block:
                rsi_blocked = f"rsi_asiri_satim({rsi:.0f})"

        adx = _at(f.adx, idx)
        regime = "trend" if (np.isfinite(adx) and adx >= cfg.adx_min) else "range"

        # destek: aynı yönde anlamlı katkı veren grup sayısı (V27 'support' dersi)
        side = 1 if score > 0 else (-1 if score < 0 else 0)
        support = sum(1 for g in core if g * side > 0 and abs(g) >= 0.15) if side != 0 else 0
        agreement = abs(float(np.mean(np.sign(core)))) if core else 0.0
        confidence = float(np.clip(0.45 + 0.35 * agreement + 0.20 * coverage, 0.0, 1.0))

        stop_frac = self._stop_frac(atrv, c)
        reason = (f"trend={groups['trend']:+.2f} mom={groups['momentum']:+.2f} brk={groups['breakout']:+.2f} "
                  f"flow={groups['volume_flow']:+.2f} adx={adx:.0f} rsi={rsi:.0f} {regime}{htf_note}{rsi_note}")
        blocked = ""
        if abs(score) < cfg.min_score:
            blocked = "skor_esik_alti"
        elif support < cfg.min_support:
            blocked = f"grup_destegi_yetersiz({support})"
        elif confidence < cfg.min_confidence:
            blocked = "guven_dusuk"
        # İYİLEŞTİRME: momentum/flow teyidi — trend tek başına yetmez.
        # Kayıp analizi: AGT (flow=0.00), KGEN (mom=+0.10) bu kapıda elenirdi.
        elif groups["momentum"] * side < cfg.min_momentum:
            blocked = "momentum_teyitsiz"
        elif groups["volume_flow"] * side < cfg.min_flow:
            blocked = "flow_teyitsiz"
        # İYİLEŞTİRME: pump-tepe filtresi — RSI aşırı bölgede ters yön engelle
        elif rsi_blocked:
            blocked = rsi_blocked
        if blocked:
            side = 0
        return EnsembleResult(side, float(score), confidence, stop_frac, regime, reason, groups, blocked)

    def _stop_frac(self, atrv: float, price: float) -> float:
        """ATR'ye uyarlanan stop, sıkı kelepçeli (V24) ve tasfiyeye güvenli (V23)."""
        natr = atrv / (price + EPS)
        stop = self.cfg.stop_atr_mult * natr
        stop = max(self.cfg.stop_min_frac, min(self.cfg.stop_max_frac, stop))
        safe = self.cfg.max_safe_stop()
        return min(stop, safe)

    # ------------------------------------------------------------------ Signal üretimi (canlı tarama için)

# --- 16_V29_FUSION/acarbot/config.py ---

"""ACARBOT V28 FINAL — ayarlar.
Kullanıcının SABİT kuralları varsayılandır: 1000$ kasa, işlem başına 50$ teminat, sabit 10x,
maker (post-only) giriş, izole marj. Diğer tüm parametreler .env ile değiştirilebilir (ACARBOT_ öneki).
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    # --- sabit kurallar (kullanıcı) ---
    equity_usd: float = 1000.0
    margin_usd: float = 50.0
    leverage: int = 10
    margin_mode: str = "isolated"
    max_positions: int = 0              # 0 = slot hesabına göre (serbest teminat)
    entry_post_only: bool = True
    # --- borsalar ---
    exchanges: tuple = ("binance", "okx")
    binance_public_www: str = "auto"
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    # --- risk (V23) ---
    fee_reserve_frac: float = 0.03
    one_position_per_coin: bool = True
    daily_loss_limit_usd: float = 150.0
    weekly_loss_limit_usd: float = 300.0
    max_drawdown_usd: float = 400.0
    liq_mmr_assumed: float = 0.025
    liq_safety: float = 0.90
    max_stop_risk_usd: float = 50.0     # ZERO ders 9: tek işlemde modellenen risk üst sınırı (uyarı + red)
    # --- strateji / sinyal ---
    strategy: str = "ensemble"
    timeframe: str = "15m"              # ansambl taban zaman dilimi
    htf_frames: tuple = ("1h", "4h")    # onay zaman dilimleri (V24/V26 dersi)
    rsi_mode: str = "wilder"            # wilder | sma | off  (V26 araştırma kararı)
    min_score: float = 0.22             # grup ortalaması eşiği [-1,1]
    min_confidence: float = 0.60
    min_support: int = 2                # aynı yönde |g|>=0.15 olan grup sayısı (V27 desteği)
    # İYİLEŞTİRME (1s test analizi): trend-tek başına girişleri engelle.
    # AGT/KGEN LONG kayıpları: trend=+1.00 ama momentum +0.10/+0.23, flow 0.00/+0.27 idi.
    # Momentum ve flow sinyal yönünde minimum güç göstermeli.
    min_momentum: float = 0.20          # momentum grubu sinyal yönünde >= bu olmalı
    min_flow: float = 0.10              # volume_flow grubu sinyal yönünde >= bu olmalı
    adx_min: float = 18.0               # rejim: >= adx_min -> trend
    conflict_penalty: float = 0.85      # trend ile momentum ters yönlüyse (ZERO ders 3)
    rsi_soft_zone: float = 82.0         # yumuşak ceza eşiği (V26; sert veto KALDIRILDI)
    # İYİLEŞTİRME: pump-tepe filtresi — RSI > 70 ise LONG engelle (KGEN RSI 75 idi, tepeden girdi)
    rsi_long_block: float = 70.0        # LONG için RSI üst sınırı
    rsi_short_block: float = 30.0       # SHORT için RSI alt sınırı
    rsi_soft_penalty: float = 0.08
    max_natr: float = 0.12              # volatilite sağduyu kapısı (V27)
    min_natr: float = 0.001
    # --- stop / çıkış ---
    stop_atr_mult: float = 2.2
    stop_min_frac: float = 0.012        # V24 dersi: sıkılı aralık
    stop_max_frac: float = 0.045
    tp_frac: float = 0.0                # 0 = kâr-al yok (ZERO ders 1: erken TP beklentiyi bozar)
    max_hold_sec: int = 86_400          # 24 saat süre çıkışı (V23)
    entry_ttl_sec: int = 3_600
    cooldown_sec: int = 86_400
    # --- pozisyon yönetimi (ZERO) ---
    be_arm_r: float = 0.5               # +0.5R'de başabaş kolu
    trail_arm_r: float = 1.0            # +1R'de trailing kollar
    trail_giveback_r: float = 0.5
    # --- onay kapısı (ZERO ders 10) ---
    confirm_count: int = 2              # ardışık aynı yönlü sinyal gerekir (1 = kapalı)
    # --- pump_short legacy parametreleri (sertifikayla aynı: gate.CERT_PARAM_MAP buna bakar) ---
    vs_min: float = 30.0
    r1_min: float = 0.05
    liq_min_usd: float = 2_000_000.0
    min_age_hours: int = 336
    stop_frac: float = 0.065            # yalnız pump_short kullanır; ansambl stopu ATR'den gelir
    # --- çalışma ---
    mode: str = "paper"                 # paper | live
    scan_interval_sec: int = 300
    manage_interval_sec: int = 20
    max_candidates_per_scan: int = 12
    state_dir: str = "calisma"
    cert_dir: str = "sertifikalar"
    # paper dolum modeli (V23, araştırmayla aynı)
    paper_through: float = 0.0005
    paper_stop_slip: float = 0.002
    paper_exit_slip: float = 0.0005
    # canlı kilitleri (V23 + ZERO ikinci onay)
    confirm_live: str = ""              # "EVET" olmalı
    accept_unvalidated: str = ""        # sertifikasız canlı: "RISKI_KABUL_EDIYORUM"
    live_confirm: str = ""              # ikinci onay: "I_UNDERSTAND"
    # API
    binance_key: str = field(default="", repr=False)
    binance_secret: str = field(default="", repr=False)
    okx_key: str = field(default="", repr=False)
    okx_secret: str = field(default="", repr=False)
    okx_passphrase: str = field(default="", repr=False)
    binance_demo: bool = False
    okx_demo: bool = False

    @property
    def notional_usd(self) -> float:
        return self.margin_usd * self.leverage

    def validate(self) -> list[str]:
        e = []
        if self.margin_usd <= 0 or self.equity_usd <= 0: e.append("kasa ve teminat pozitif olmalı")
        if self.leverage < 1: e.append("kaldıraç >= 1 olmalı")
        if self.margin_mode not in ("isolated", "cross"): e.append("margin_mode isolated|cross olmalı")
        if self.mode not in ("paper", "live"): e.append("mode paper|live olmalı")
        if not (0 < self.stop_min_frac <= self.stop_max_frac < 0.1): e.append("stop_min_frac <= stop_max_frac < 0.1 olmalı")
        if self.margin_mode == "isolated" and self.stop_max_frac > self.max_safe_stop():
            e.append(f"stop_max_frac %{self.stop_max_frac*100:.1f} izole {self.leverage}x tasfiye mesafesine fazla yakın (üst sınır %{self.max_safe_stop()*100:.2f})")
        if self.rsi_mode not in ("wilder", "sma", "off"): e.append("rsi_mode wilder|sma|off olmalı")
        if not self.exchanges: e.append("en az bir borsa gerekli")
        if self.confirm_count < 1: e.append("confirm_count >= 1 olmalı")
        if self.strategy == "pump_short" and self.stop_frac > self.max_safe_stop():
            e.append(f"pump_short stop %{self.stop_frac*100:.1f} tasfiye mesafesine fazla yakın")
        return e

    def max_safe_stop(self) -> float:
        return max(0.0, (1.0 / self.leverage - self.liq_mmr_assumed) * self.liq_safety)


_ENV_PREFIX = "ACARBOT_"


def load_settings(env_file: str = ".env", **overrides) -> Settings:
    _load_dotenv(env_file)
    vals = {}
    for f in fields(Settings):
        raw = os.environ.get(_ENV_PREFIX + f.name.upper())
        if raw is None or raw == "":
            continue
        t = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "str")
        if t == "bool": vals[f.name] = raw.strip().lower() in ("1", "true", "yes", "evet")
        elif t == "int": vals[f.name] = int(float(raw))
        elif t == "float": vals[f.name] = float(raw)
        elif t == "tuple": vals[f.name] = tuple(x.strip() for x in raw.split(",") if x.strip())
        else: vals[f.name] = raw
    vals.update({k: v for k, v in overrides.items() if v is not None})
    s = replace(Settings(), **vals)
    errs = s.validate()
    if errs:
        raise ValueError("Ayar hatası: " + "; ".join(errs))
    return s
