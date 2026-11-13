"""En iyi alış/satış + varsayımsal kayma üzerinden sanal taker defteri.
Emir göndermez. Derinlik ve gerçek dolum garantisi yoktur.
"""
from dataclasses import dataclass, asdict
from omnistudio.core.types import Side, Quote
from omnistudio.risk.manager import RiskManager, RiskConfig

@dataclass
class Trade:
    symbol: str
    side: str
    qty: float
    entry: float
    stop: float
    target: float
    entry_fee: float
    opened_ms: int
    exit: float = 0
    exit_fee: float = 0
    closed_ms: int = 0
    reason: str = ''
    net: float = 0
    initial_risk_distance: float = 0
    breakeven: bool = False

class Ledger:
    def __init__(self, equity=1000, fee_bps=5.5, slip_bps=2):
        self.risk=RiskManager(RiskConfig(equity_start=equity, max_open_positions=5,
            max_position_notional=250, max_gross_exposure=1000, atr_stop_mult=2.5,
            atr_tp_mult=5, risk_per_trade_pct=.35, daily_loss_limit_pct=3))
        self.fee=fee_bps/10000; self.slip=slip_bps/10000
        self.positions={}; self.closed=[]; self.marks={}
    def open(self,q: Quote,side: Side,atr: float,ts: int):
        if q.symbol in self.positions or len(self.positions)>=5: return None
        if self.risk.state.breaker_tripped: return None
        px=(q.ask if side is Side.LONG else q.bid)*(1+self.slip*side.sign)
        plan=self.risk.plan(side,px,atr)
        if not plan: return None
        exposure=sum(p.qty*p.entry for p in self.positions.values())
        if exposure+plan.notional>self.risk.cfg.max_gross_exposure: return None
        p=Trade(q.symbol,side.value,plan.qty,px,plan.stop_price,plan.take_profit_price,px*plan.qty*self.fee,ts,initial_risk_distance=plan.stop_distance)
        self.positions[q.symbol]=p
        return p
    def close(self,q: Quote,reason: str,ts: int):
        p=self.positions.pop(q.symbol); side=Side(p.side)
        p.exit=(q.bid if side is Side.LONG else q.ask)*(1-self.slip*side.sign)
        p.exit_fee=p.exit*p.qty*self.fee; p.closed_ms=ts; p.reason=reason
        p.net=(p.exit-p.entry)*p.qty*side.sign-p.entry_fee-p.exit_fee
        self.closed.append(p); self.risk.state.record_close(p.net,p.entry_fee+p.exit_fee)
        return p
    def on_quote(self,q: Quote,ts:int):
        self.marks[q.symbol]=q.mid
        unreal=sum((self.marks.get(p.symbol,p.entry)-p.entry)*p.qty*Side(p.side).sign for p in self.positions.values())
        if self.risk.state.equity+unreal <= self.risk.cfg.equity_start*(1-self.risk.cfg.daily_loss_limit_pct/100):
            self.risk.state.breaker_tripped=True
            self.risk.state.breaker_reason='DAILY_LOSS_LIMIT'
        p=self.positions.get(q.symbol)
        if not p:return None
        side=Side(p.side); executable=q.bid if side is Side.LONG else q.ask
        if (executable-p.stop)*side.sign <= 0: return self.close(q,'STOP_LOSS',ts)
        if (executable-p.target)*side.sign >= 0: return self.close(q,'TAKE_PROFIT',ts)
        # Örnekteki 1R başabaş + 1R takip; stop asla geriye taşınmaz.
        if (executable-p.entry)*side.sign >= p.initial_risk_distance:
            be=p.entry*(1+side.sign*(self.fee*2+self.slip*2))
            trailing=executable-side.sign*p.initial_risk_distance
            p.stop=max(p.stop,be,trailing) if side is Side.LONG else min(p.stop,be,trailing)
            p.breakeven=True
        return None
    def summary(self):
        return {'open':[asdict(p) for p in self.positions.values()], 'closed':[asdict(p) for p in self.closed],
                'closed_trades':len(self.closed),'realized_net':sum(p.net for p in self.closed),
                'equity_realized':self.risk.state.equity, 'fees_on_closed':self.risk.state.fees_paid}
