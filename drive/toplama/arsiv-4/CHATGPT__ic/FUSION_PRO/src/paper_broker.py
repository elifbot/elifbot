import time, uuid

class PaperBroker:
    """Cross-margin style paper broker with fixed $50 margin tranches, 10x notional,
    maker-first entries, dynamic TP, partial profit and trailing runner."""
    def __init__(self,cfg):
        self.cash=float(cfg['paper']['initial_cash']); self.cfg=cfg; self.positions={}; self.closed=[]
    def _fill(self,price,side,maker=False):
        if maker:return price
        slip=self.cfg['execution']['slippage_bps_side']/10000
        return price*(1+slip if side=='BUY' else 1-slip)
    def open(self,signal,plan):
        side=signal['side']; fill=self._fill(signal['entry'],'BUY' if side=='LONG' else 'SELL',maker=True)
        pid=f"{signal['symbol']}-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}"
        p={'id':pid,'symbol':signal['symbol'],'side':side,'qty':plan['qty'],'entry':fill,'stop':plan.get('stop',signal['stop']),'target':plan.get('target',signal['target']),
           'opened_ts':int(time.time()*1000),'risk_cash':plan['risk_cash'],'margin':plan['margin'],'notional':plan['notional'],'leverage':plan['leverage'],'best':fill,'tp1':False,
           'atr':signal.get('atr',abs(fill-signal['stop'])/self.cfg['risk'].get('atr_stop_mult',1.6)),'tp1_fraction':self.cfg['execution'].get('tp1_fraction',0.35)}
        self.positions[pid]=p; return p
    def mark(self,pid,price):
        p=self.positions.get(pid)
        if not p:return None
        p['best']=max(p['best'],price) if p['side']=='LONG' else min(p['best'],price)
        r=(price-p['entry']) if p['side']=='LONG' else (p['entry']-price)
        risk=abs(p['entry']-p['stop'])
        if r>=risk*self.cfg['execution'].get('tp1_r',1.0) and not p['tp1']:
            frac=min(max(p['tp1_fraction'],0),0.9); partial_qty=p['qty']*frac
            if partial_qty>0:
                exitp=self._fill(price,'SELL' if p['side']=='LONG' else 'BUY'); gross=(exitp-p['entry'])*partial_qty if p['side']=='LONG' else (p['entry']-exitp)*partial_qty
                fee=(p['notional']*frac)*self.cfg['execution'].get('fee_bps_roundtrip',8)/10000
                self.cash += gross-fee; p['qty']-=partial_qty; p['notional']=p['qty']*p['entry']; p['tp1']=True
                p['partial_realized']=p.get('partial_realized',0)+gross-fee; p['stop']=p['entry']
        if p['tp1']:
            trail_mult=self.cfg['execution'].get('trail_atr_mult',2.2)
            if p['side']=='LONG': p['stop']=max(p['stop'],p['best']-trail_mult*p['atr'])
            else: p['stop']=min(p['stop'],p['best']+trail_mult*p['atr'])
        max_hold=self.cfg['risk'].get('max_hold_min',240)*60
        if time.time()-p['opened_ts']/1000>=max_hold:return self.close(pid,price,'max_hold')
        if p['side']=='LONG' and price>=p['target']:return self.close(pid,price,'target')
        if p['side']=='SHORT' and price<=p['target']:return self.close(pid,price,'target')
        if p['side']=='LONG' and price<=p['stop']:return self.close(pid,price,'stop')
        if p['side']=='SHORT' and price>=p['stop']:return self.close(pid,price,'stop')
    def close(self,pid,price,reason):
        p=self.positions.pop(pid); exitp=self._fill(price,'SELL' if p['side']=='LONG' else 'BUY')
        gross=(exitp-p['entry'])*p['qty'] if p['side']=='LONG' else (p['entry']-exitp)*p['qty']
        fee=(p['qty']*p['entry'])*self.cfg['execution'].get('fee_bps_roundtrip',8)/10000
        net=gross-fee+p.get('partial_realized',0); self.cash+=gross-fee
        rec={**p,'exit':exitp,'gross':gross,'fee':fee,'net':net,'reason':reason,'closed_ts':int(time.time()*1000)}
        self.closed.append(rec); return rec
    def equity(self,prices):
        eq=self.cash
        for p in self.positions.values():
            px=prices.get(p['symbol'],p['entry']); eq += (px-p['entry'])*p['qty'] if p['side']=='LONG' else (p['entry']-px)*p['qty']
        return eq
