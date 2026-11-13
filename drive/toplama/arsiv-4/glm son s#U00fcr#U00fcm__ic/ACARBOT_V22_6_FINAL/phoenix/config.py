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
    tp_r: float = 2.2
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
    rsi_gate: bool = True              # block entries into overextended moves
    rsi_block_high: float = 78.0       # no LONG when 15m RSI(14) >= this
    rsi_block_low: float = 22.0        # no SHORT when 15m RSI(14) <= this
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
    strict_liquidation_guard: bool = False
    state_path: str = "state.json"
    journal_path: str = "trades.jsonl"
    strategy_weights: dict[str, float] = field(default_factory=lambda: {
        "trend": .35, "htf": .20, "oi": .15, "book": .15, "funding": .05, "liquidation": .10
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
            tp_r=f("PHOENIX_TP_R",2.2), max_hold_bars=i("PHOENIX_MAX_HOLD_BARS",96), min_score=f("PHOENIX_MIN_SCORE",.30),
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
            tp_exit_score=f("PHOENIX_TP_EXIT_SCORE",0.10), tp_min_net_usd=f("PHOENIX_TP_MIN_NET_USD",0.0),
            tp_min_r=f("PHOENIX_TP_MIN_R",0.5), breakeven_r=f("PHOENIX_BREAKEVEN_R",0.5),
            trail_arm_r=f("PHOENIX_TRAIL_ARM_R",1.0), trail_giveback_r=f("PHOENIX_TRAIL_GIVEBACK_R",0.5),
            oi_price_agreement=b("PHOENIX_OI_PRICE_AGREEMENT",True),
            conflict_penalty=f("PHOENIX_CONFLICT_PENALTY",0.70),
            rsi_gate=b("PHOENIX_RSI_GATE",True),
            rsi_block_high=f("PHOENIX_RSI_BLOCK_HIGH",78.0), rsi_block_low=f("PHOENIX_RSI_BLOCK_LOW",22.0),
            paper_funding_accrual=b("PHOENIX_PAPER_FUNDING_ACCRUAL",True),
            live_indicator_tp=b("PHOENIX_LIVE_INDICATOR_TP",True),
            exit_eval_budget_sec=i("PHOENIX_EXIT_EVAL_BUDGET_SEC",40),
            paper_stop_fill=str(e.get("PHOENIX_PAPER_STOP_FILL","worse") or "worse").strip().lower(),
            max_requotes=i("PHOENIX_MAX_REQUOTES",2), max_chase_bps=f("PHOENIX_MAX_CHASE_BPS",10),
            auto_bump_max_factor=f("PHOENIX_AUTO_BUMP_MAX_FACTOR",1.0),
            okx_td_mode=e.get("PHOENIX_OKX_TD_MODE","cross"), okx_pos_mode=e.get("PHOENIX_OKX_POS_MODE","net"),
            binance_pos_mode=e.get("PHOENIX_BINANCE_POS_MODE","oneway"),
            paper_state_path=e.get("PHOENIX_PAPER_STATE_PATH","paper_state.json"),
            paper_journal_path=e.get("PHOENIX_PAPER_JOURNAL_PATH","paper_trades.jsonl"),
        )
