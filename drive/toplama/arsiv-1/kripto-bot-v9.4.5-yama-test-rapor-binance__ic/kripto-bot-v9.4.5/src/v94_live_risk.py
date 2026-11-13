"""Live risk adapter sharing exactly the adaptive stop formula with replay."""
from .risk import RiskManager
from .adaptive_policy import AdaptivePolicy


class V94RiskManager(RiskManager):
    policy=AdaptivePolicy()
    def update(self,pos,price):
        pnl=self.profit_pct(pos,price);usd=self.pnl_usdt(pos,price)
        # Existing protective stop has priority. A jump cannot be turned into a profitable historical fill.
        hit=price<=pos.stop if pos.side=='LONG' else price>=pos.stop
        if hit:return {'action':'close','reason':self.close_stop_reason(pos),'pnl_pct':pnl,'roe_pct':self.roe_pct(pos,price),'pnl_usdt':usd,'stop':pos.stop}
        pos.mfe_usdt=max(pos.mfe_usdt,usd);pos.mae_usdt=min(pos.mae_usdt,usd)
        pos.peak=max(pos.peak,price) if pos.side=='LONG' else min(pos.peak,price)
        atr=pos.entry*float(pos.atr_pct)/100
        fees=float(pos.entry_fee_usdt)+pos.entry*pos.qty*max(0,pos.exit_fee_pct)/100
        try:
            pos.stop=self.policy.ratchet(side=pos.side,entry=pos.entry,qty=pos.qty,atr=atr,mfe_usdt=pos.mfe_usdt,
                old_stop=pos.stop,mark=price,fees_usdt=fees)
        except ValueError:
            pass # Existing protective stop remains; invalid state never widens it.
        pos.locked_profit=pos.stop>pos.entry if pos.side=='LONG' else pos.stop<pos.entry
        return {'action':'hold','stop':pos.stop,'pnl_pct':pnl,'roe_pct':self.roe_pct(pos,price),'pnl_usdt':usd,
                'locked':pos.locked_profit,'mfe_usdt':pos.mfe_usdt,'mae_usdt':pos.mae_usdt}
