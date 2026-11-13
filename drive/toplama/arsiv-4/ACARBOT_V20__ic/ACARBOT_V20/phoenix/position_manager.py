from time import time
from .models import Position,Trade
class PositionManager:
    def __init__(self,cfg): self.cfg=cfg
    def check(self,p,mark,bars_held=None):
        p.update_extremes(mark); p.bars_held=p.bars_held+1 if bars_held is None else bars_held
        if (p.side=='LONG' and mark<=p.stop) or (p.side=='SHORT' and mark>=p.stop): return 'STOP',p.net_pnl(mark,self.cfg.fee_bps_per_side,self.cfg.slippage_bps_reserve)
        net=p.net_pnl(mark,self.cfg.fee_bps_per_side,self.cfg.slippage_bps_reserve)
        if net<=-self.cfg.max_loss_usd:return 'HARD_LOSS',net
        if (p.side=='LONG' and mark>=p.target) or (p.side=='SHORT' and mark<=p.target):return 'TARGET',net
        if p.bars_held>=self.cfg.max_hold_bars:return 'TIME',net
        return None,net
    def close(self,p,mark,reason,now=None):
        now=now or time(); gross=p.gross_pnl(mark); ef=p.estimated_exit_fee(mark,self.cfg.fee_bps_per_side); slip=abs(mark*p.qty*p.contract_size)*self.cfg.slippage_bps_reserve/10000; net=gross-p.entry_fee-p.funding_paid-ef-slip
        adverse=(p.entry-p.lowest)*p.qty*p.contract_size if p.side=='LONG' else (p.highest-p.entry)*p.qty*p.contract_size; favorable=(p.highest-p.entry)*p.qty*p.contract_size if p.side=='LONG' else (p.entry-p.lowest)*p.qty*p.contract_size
        return Trade(p.id,p.exchange,p.symbol,p.side,p.entry,mark,p.qty,gross,net,p.entry_fee+ef,p.funding_paid,reason,p.opened_at,now,-max(0,adverse),max(0,favorable))
