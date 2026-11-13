from dataclasses import dataclass, asdict

@dataclass
class Candle:
    ts:int; open:float; high:float; low:float; close:float; volume:float; trades:int=0; taker_buy_volume:float=0.0

@dataclass
class MarketSnapshot:
    symbol:str; price:float; bid:float; ask:float; spread_bps:float
    funding:float; open_interest:float; oi_change_pct:float
    depth_imbalance:float; taker_imbalance:float; data_age_sec:float; ts:int

@dataclass
class Signal:
    symbol:str; side:str; score:float; edge_bps:float; regime:str; entry:float; stop:float; target:float
    reasons:list; vetoes:list; confidence:float; ts:int
    def to_dict(self): return asdict(self)

@dataclass
class Position:
    symbol:str; side:str; qty:float; entry:float; stop:float; target:float; opened_ts:int
    initial_risk:float; leverage:int; tp1_done:bool=False; best_price:float=0.0
