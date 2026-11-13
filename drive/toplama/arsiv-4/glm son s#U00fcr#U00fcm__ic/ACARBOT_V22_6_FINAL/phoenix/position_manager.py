from time import time
from .models import Position,Trade
class PositionManager:
    """V22.6 exit engine.

    Problem fixed: V22.5 cut winners at +$0.10 (tp_min_net_usd) while losers ran to the stop.
    On $500 notional with a -$20 stop the payoff was ~1:40: no win-rate makes that profitable.

    The engine now trades like the user's rule set intends:
      * STOP: the fixed dollar rule (-max_loss_usd; -$20 at default margin mode) - unchanged.
      * BREAKEVEN: once net >= breakeven_r x risk ($10 default), the stop moves to entry + costs.
        From there the position cannot turn into a loser.
      * TRAIL: once peak net >= trail_arm_r x risk ($20 default), the stop trails at
        peak_net - trail_giveback_r x risk - winners are allowed to run, locked profit decays
        by at most trail_giveback_r x risk.
      * INDICATOR_TP: only for positions whose net >= tp_min_net_effective (0.5R = $10 default).
    The stop only ever TIGHTENS: the user's -$20 floor is never widened.
    """
    def __init__(self,cfg): self.cfg=cfg

    def _costs(self,p,mark):
        """Entry fee + funding + estimated exit fee + slippage reserve at ``mark``."""
        exit_fee=abs(mark*p.qty*p.contract_size)*self.cfg.fee_bps_per_side/10000
        slip=abs(mark*p.qty*p.contract_size)*self.cfg.slippage_bps_reserve/10000
        return p.entry_fee+p.funding_paid+exit_fee+slip

    def _tighten_stop(self,p,mark):
        """Breakeven + trailing stop logic. Only tightens; returns 'BE'/'TRAIL' when the stop moved."""
        exposure=abs(p.qty)*max(float(p.contract_size or 0.0),0.0)
        if exposure<=0 or p.entry<=0: return None
        risk=self.cfg.max_loss_usd
        net=p.net_pnl(mark,self.cfg.fee_bps_per_side,self.cfg.slippage_bps_reserve)
        p.peak_net=max(p.peak_net,net)
        moved=None
        sgn=1.0 if p.side=='LONG' else -1.0
        # total dollar costs approximated at entry (exit fee/slippage scale with price; close enough)
        costs_dollars=self._costs(p,p.entry)
        if self.cfg.breakeven_r>0 and not p.be_armed and net>=self.cfg.breakeven_r*risk:
            p.be_armed=True
            be=p.entry+sgn*costs_dollars/exposure
            if (sgn>0 and be>p.stop) or (sgn<0 and be<p.stop):
                p.stop=be; moved='BE'
        if self.cfg.trail_arm_r>0 and p.peak_net>=self.cfg.trail_arm_r*risk:
            p.trail_armed=True
        if p.trail_armed:
            lock=max(0.0,p.peak_net)-self.cfg.trail_giveback_r*risk
            trail=p.entry+sgn*(lock+costs_dollars)/exposure
            if (sgn>0 and trail>p.stop) or (sgn<0 and trail<p.stop):
                p.stop=trail; moved='TRAIL' if moved is None else 'BE+TRAIL'
        return moved

    def check(self,p,mark,bars_held=None):
        p.update_extremes(mark); p.bars_held=p.bars_held+1 if bars_held is None else bars_held
        self._tighten_stop(p,mark)
        if (p.side=='LONG' and mark<=p.stop) or (p.side=='SHORT' and mark>=p.stop): return 'STOP',p.net_pnl(mark,self.cfg.fee_bps_per_side,self.cfg.slippage_bps_reserve)
        net=p.net_pnl(mark,self.cfg.fee_bps_per_side,self.cfg.slippage_bps_reserve)
        if net<=-self.cfg.max_loss_usd:return 'HARD_LOSS',net
        if p.target>0 and ((p.side=='LONG' and mark>=p.target) or (p.side=='SHORT' and mark<=p.target)):return 'TARGET',net
        if p.bars_held>=self.cfg.max_hold_bars:return 'TIME',net
        return None,net
    def indicator_exit(self,p,mark,signed_score):
        """Indicator take profit: close a position once the score in its direction fades AND the
        net profit clears the R-based floor (tp_min_net_effective, default 0.5R = $10)."""
        if self.cfg.tp_mode!='indicator': return None
        net=p.net_pnl(mark,self.cfg.fee_bps_per_side,self.cfg.slippage_bps_reserve)
        directional=signed_score if p.side=='LONG' else -signed_score
        if net>=self.cfg.tp_min_net_effective and directional<self.cfg.tp_exit_score: return 'INDICATOR_TP'
        return None
    def close(self,p,mark,reason,now=None):
        now=now or time(); gross=p.gross_pnl(mark); ef=p.estimated_exit_fee(mark,self.cfg.fee_bps_per_side); slip=abs(mark*p.qty*p.contract_size)*self.cfg.slippage_bps_reserve/10000; net=gross-p.entry_fee-p.funding_paid-ef-slip
        adverse=(p.entry-p.lowest)*p.qty*p.contract_size if p.side=='LONG' else (p.highest-p.entry)*p.qty*p.contract_size; favorable=(p.highest-p.entry)*p.qty*p.contract_size if p.side=='LONG' else (p.entry-p.lowest)*p.qty*p.contract_size
        return Trade(p.id,p.exchange,p.symbol,p.side,p.entry,mark,p.qty,gross,net,p.entry_fee+ef,p.funding_paid,reason,p.opened_at,now,-max(0,adverse),max(0,favorable))
