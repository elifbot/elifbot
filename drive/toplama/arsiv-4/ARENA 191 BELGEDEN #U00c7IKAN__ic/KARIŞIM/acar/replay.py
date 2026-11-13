"""Yeni tek-varlık, tek-pozisyon, ağ ve gerçek emir yeteneği olmayan PAPER motoru."""
from dataclasses import dataclass,asdict
from datetime import datetime, timezone
from math import isfinite
from .data import validate_bars
from .analytics import trade_metrics

@dataclass(frozen=True)
class Config:
    interval: int=60
    initial_cash: float=10000.0
    risk_fraction: float=0.005
    max_notional: float=1000.0
    stop_atr: float=1.5
    target_atr: float=3.0
    fee_bps: float=5.0
    spread_bps: float=4.0  # toplam spread; her tarafta yarısı
    slippage_bps: float=2.0
    min_edge_cost_ratio: float=1.15  # 0 = kapalı
    daily_loss_fraction: float=0.02
    cooldown_bars: int=3
    max_hold_bars: int=30
    breakeven_at_r: float=0.0  # 0 = kapalı; bir sonraki mumdan itibaren
    trailing_atr: float=0.0    # 0 = kapalı; bir sonraki mumdan itibaren
    def validate(self):
        for k,v in asdict(self).items():
            try: valid=isinstance(v,(float,int)) and not isinstance(v,bool) and isfinite(v)
            except OverflowError: valid=False
            if not valid: raise ValueError(f'geçersiz ayar: {k}')
        if not isinstance(self.interval,int) or self.interval<=0: raise ValueError('interval')
        if not isinstance(self.cooldown_bars,int) or self.cooldown_bars<0: raise ValueError('cooldown')
        if not isinstance(self.max_hold_bars,int) or self.max_hold_bars<1: raise ValueError('max_hold')
        if self.initial_cash<=0 or self.max_notional<=0 or self.stop_atr<=0 or self.target_atr<=0: raise ValueError('pozitif ayar gerekli')
        if not (0<self.risk_fraction<=0.1 and 0<self.daily_loss_fraction<=1): raise ValueError('risk sınırı')
        if self.breakeven_at_r<0 or self.trailing_atr<0 or self.min_edge_cost_ratio<0: raise ValueError('çıkış ayarları')
        if not (0<=self.fee_bps<=1000 and 0<=self.spread_bps<=1000 and 0<=self.slippage_bps<=1000): raise ValueError('maliyet aralığı')

@dataclass
class Position:
    side: str
    entry_time: int
    entry: float
    qty: float
    stop: float
    target: float
    entry_fee: float
    signal_time: int
    entry_atr: float
    initial_risk: float
    hold: int=0

class PaperEngine:
    def __init__(self, config, strategy):
        config.validate(); self.cfg=config; self.strategy=strategy
    def run(self,bars):
        c=self.cfg; validate_bars(bars,c.interval)
        cash=c.initial_cash; p=None; pending=None; trades=[]; events=[]; curve=[]
        cooldown_until=0; day=None; day_start=cash; halted=False
        # Alış daha pahalı, satış daha ucuz; fiyat etkisi toplam yarım spread + kayma.
        slip=(c.spread_bps/2+c.slippage_bps)/10000; fee=c.fee_bps/10000
        def price(raw, buying): return raw*(1+slip if buying else 1-slip)
        def close_position(pos, raw, ts, reason):
            nonlocal cash,cooldown_until
            exit_price=price(raw,pos.side=='short')
            exit_fee=exit_price*pos.qty*fee
            gross=(exit_price-pos.entry)*pos.qty*(1 if pos.side=='long' else -1)
            cash+=gross-exit_fee
            trades.append({'side':pos.side,'signal_time':pos.signal_time,'entry_time':pos.entry_time,'exit_time':ts,'entry':pos.entry,'exit':exit_price,'qty':pos.qty,'gross_pnl':gross,'entry_fee':pos.entry_fee,'exit_fee':exit_fee,'net_pnl':gross-pos.entry_fee-exit_fee,'reason':reason})
        for i,b in enumerate(bars):
            d=datetime.fromtimestamp(b.timestamp,tz=timezone.utc).date().isoformat()
            if d!=day:
                day=d; day_start=cash+((b.open-p.entry)*p.qty*(1 if p.side=='long' else -1) if p else 0); halted=False
            # Önceki mum sinyali ancak bu mumun açılışında dolabilir.
            if pending is not None:
                s,signal_ts=pending; pending=None
                if p or halted or i<cooldown_until or cash<=0:
                    events.append({'time':b.timestamp,'type':'ENTRY_BLOCKED','reason':'position/halt/cooldown/cash'})
                else:
                    fill=price(b.open,s.side=='long'); distance=s.atr*c.stop_atr
                    if not isfinite(distance) or distance<=0 or s.side not in ('long','short'):
                        events.append({'time':b.timestamp,'type':'ENTRY_BLOCKED','reason':'invalid signal'})
                    else:
                        sign=1 if s.side=='long' else -1
                        stop=fill-sign*distance; target=fill+sign*s.atr*c.target_atr
                        if stop<=0 or target<=0:
                            events.append({'time':b.timestamp,'type':'ENTRY_BLOCKED','reason':'invalid stop/target'})
                        elif c.min_edge_cost_ratio and (
                            abs(target-fill) < c.min_edge_cost_ratio * (
                                abs(fill-b.open) + abs(price(target,s.side=='short')-target)
                                + fee*(fill+price(target,s.side=='short')))):
                            events.append({'time':b.timestamp,'type':'ENTRY_BLOCKED','reason':'EDGE_BELOW_COST'})
                        else:
                            # Stop kayması ve iki tahmini komisyonu boyuta dahil et.
                            estimated_exit=price(stop,s.side=='short')
                            unit_risk=abs(fill-estimated_exit)+fee*(fill+estimated_exit)
                            qty=min(cash*c.risk_fraction/unit_risk,c.max_notional/fill, (cash/(fill*fee) if fee else float('inf')))
                            if qty>0 and isfinite(qty):
                                entry_fee=fill*qty*fee; cash-=entry_fee
                                p=Position(s.side,b.timestamp,fill,qty,stop,target,entry_fee,signal_ts,s.atr,distance)
                                events.append({'time':b.timestamp,'type':'PAPER_ENTRY','side':s.side,'qty':qty,'signal_time':signal_ts})
            if p:
                p.hold+=1
                if p.side=='long':
                    stop_hit=b.low<=p.stop; target_hit=b.high>=p.target
                    stop_raw=min(b.open,p.stop)
                else:
                    stop_hit=b.high>=p.stop; target_hit=b.low<=p.target
                    stop_raw=max(b.open,p.stop)
                reason=None; raw=None
                # Aynı mumda ikisi gerçekleşmişse stop daha kötü kabul edilir.
                if stop_hit: reason='STOP'; raw=stop_raw
                elif target_hit: reason='TARGET'; raw=p.target
                elif p.hold>=c.max_hold_bars: reason='MAX_HOLD'; raw=b.close
                if reason:
                    close_position(p,raw,b.timestamp+c.interval,reason); p=None; cooldown_until=i+1+c.cooldown_bars
                elif p:
                    # Kapanışta güncelle; bu mumun geçmişinde bu yeni stopu kullanma.
                    sign=1 if p.side=='long' else -1
                    favorable=sign*(b.close-p.entry)
                    proposed=p.stop
                    if c.breakeven_at_r and favorable>=c.breakeven_at_r*p.initial_risk:
                        proposed=max(proposed,p.entry) if sign==1 else min(proposed,p.entry)
                    if c.trailing_atr and favorable>0:
                        candidate=b.close-sign*c.trailing_atr*p.entry_atr
                        proposed=max(proposed,candidate) if sign==1 else min(proposed,candidate)
                    if proposed!=p.stop:
                        events.append({'time':b.timestamp+c.interval,'type':'STOP_UPDATE','old':p.stop,'new':proposed})
                        p.stop=proposed
            equity=cash+((b.close-p.entry)*p.qty*(1 if p.side=='long' else -1) if p else 0)
            if not halted and equity<=day_start*(1-c.daily_loss_fraction):
                halted=True; events.append({'time':b.timestamp+c.interval,'type':'DAILY_HALT','equity':equity})
            curve.append({'time':b.timestamp+c.interval,'equity':equity})
            # Sinyal en erken bir sonraki mumda kullanılabilir; son mumda emir oluşturulmaz.
            if i<len(bars)-1 and p is None and not halted and i+1>=cooldown_until and cash>0:
                s=self.strategy(bars[:i+1])
                if s is not None:
                    pending=(s,b.timestamp+c.interval); events.append({'time':b.timestamp+c.interval,'type':'SIGNAL','side':s.side,'votes':s.votes})
        if p is not None:
            close_position(p,bars[-1].close,bars[-1].timestamp+c.interval,'END_OF_DATA')
            curve[-1]['equity']=cash
        peak=c.initial_cash; max_dd=0
        for e in curve:
            peak=max(peak,e['equity']); max_dd=max(max_dd,(peak-e['equity'])/peak)
        return {'mode':'PAPER_OFFLINE','config':asdict(c),'starting_cash':c.initial_cash,'ending_cash':cash,'net_pnl':cash-c.initial_cash,'trade_count':len(trades),'max_drawdown_fraction':max_dd,'trade_metrics':trade_metrics(trades),'trades':trades,'events':events,'equity_curve':curve,'limitations':['Tek sembol; funding, likidasyon, kısmi dolum ve piyasa derinliği modellenmez.','Geçmiş test sonucu gelecek performans garantisi değildir.','Borsa kuralları, lot adımı ve minimum tutar uygulanmaz.','Stop kayması sabit varsayılır; boşluklar ve gerçek kayıp riski daha büyük olabilir.']}
