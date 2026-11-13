from dataclasses import dataclass, field, asdict

@dataclass(frozen=True)
class Market:
    exchange: str
    symbol: str
    base: str
    quote: str
    settle: str
    contract_type: str
    contract_size: float = 1.0
    active: bool = True
    tick_size: float = 0.0
    lot_size: float = 0.0
    min_amount: float = 0.0
    min_cost: float = 0.0
    info: dict = field(default_factory=dict, compare=False, hash=False)

@dataclass
class Snapshot:
    market: Market
    ts: float
    price: float
    bid: float
    ask: float
    spread_bps: float
    quote_volume_24h: float
    funding: float = 0.0
    oi: float = 0.0
    oi_change: float = 0.0
    book_imbalance: float = 0.0
    liquidation_pressure: float = 0.0
    regime_score: float = 0.0
    htf_score: float = 0.0
    stale_book: bool = False
    oi_available: bool = True
    funding_available: bool = True
    liquidation_available: bool = False
    data_quality: float = 1.0
    atr_pct: float = 0.0
    # --- V22.6 signal-quality inputs (defaults keep old constructions valid) ---
    rsi_14: float = 0.0                 # 15m RSI(14); 0 = unavailable
    rsi_available: bool = False
    price_chg_pct: float = 0.0          # signed 30-min % price change; 0 = unknown (OI agreement falls back)

@dataclass
class Signal:
    exchange: str
    symbol: str
    side: str
    score: float
    entry: float
    stop: float
    target: float
    notional: float
    margin: float
    created_at: float
    qty: float = 0.0
    reasons: list[str] = field(default_factory=list)
    contract_size: float = 1.0
    atr_pct: float = 0.0
    funding_rate: float = 0.0           # funding at signal time; used for paper funding accrual

@dataclass
class Position:
    id: str
    exchange: str
    symbol: str
    side: str
    entry: float
    qty: float
    notional: float
    margin: float
    stop: float
    target: float
    opened_at: float
    entry_fee: float = 0.0
    funding_paid: float = 0.0
    status: str = 'OPEN'
    highest: float = 0.0
    lowest: float = 0.0
    bars_held: int = 0
    reserved_margin: float = 0.0
    contract_size: float = 1.0
    # --- V22.6 exit engine state (defaults keep old paper_state.json files loadable) ---
    funding_at_open: float = 0.0        # |funding rate| at open; paper accrues notional x rate per 8h held
    peak_net: float = 0.0               # best net PnL seen while the position was open
    be_armed: bool = False              # breakeven stop armed (net >= breakeven_r x risk)
    trail_armed: bool = False           # trailing stop armed (peak net >= trail_arm_r x risk)

    def __post_init__(self):
        self.reserved_margin = self.reserved_margin or self.margin
        self.highest = self.highest or self.entry
        self.lowest = self.lowest or self.entry

    def gross_pnl(self, mark):
        return (mark - self.entry) * self.qty * self.contract_size * (1 if self.side == 'LONG' else -1)

    def estimated_exit_fee(self, mark, fee_bps):
        return abs(mark * self.qty * self.contract_size) * fee_bps / 10000

    def net_pnl(self, mark, fee_bps, slippage_bps=0):
        return (self.gross_pnl(mark) - self.entry_fee - self.funding_paid
                - self.estimated_exit_fee(mark, fee_bps)
                - abs(mark * self.qty * self.contract_size) * slippage_bps / 10000)

    def update_extremes(self, mark):
        self.highest = max(self.highest, mark)
        self.lowest = min(self.lowest, mark)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

@dataclass
class Trade:
    position_id: str
    exchange: str
    symbol: str
    side: str
    entry: float
    exit: float
    qty: float
    gross_pnl: float
    net_pnl: float
    fees: float
    funding: float
    reason: str
    opened_at: float
    closed_at: float
    mae: float
    mfe: float
