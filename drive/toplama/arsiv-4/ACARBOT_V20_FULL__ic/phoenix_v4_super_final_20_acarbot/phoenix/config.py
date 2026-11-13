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
    tp_r: float = 2.2
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
            tp_r=f("PHOENIX_TP_R",2.2), max_hold_bars=i("PHOENIX_MAX_HOLD_BARS",96), min_score=f("PHOENIX_MIN_SCORE",.30),
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
