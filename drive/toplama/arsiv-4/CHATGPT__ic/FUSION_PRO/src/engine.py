import asyncio, time
import pandas as pd
from .mtf import consensus
from .strategy import analyze
from .risk import plan
from .paper_broker import PaperBroker
from .universe import UniverseScanner

class FusionEngine:
    def __init__(self, client, cfg, store=None, exchange='binance', instrument_map=None):
        self.client=client; self.cfg=cfg; self.store=store; self.exchange=exchange
        self.broker=PaperBroker(cfg); self.prev_oi={}; self.last_trade={}; self.instrument_map=instrument_map or {}
        self.session_peak=self.broker.cash; self.day_start=self.broker.cash; self.week_start=self.broker.cash
        self._last_day=None; self._last_week=None

    def _refresh_periods(self):
        import datetime as dt
        now=dt.datetime.utcnow(); day=now.date(); week=now.date()-dt.timedelta(days=now.weekday())
        if self._last_day != day:
            self._last_day=day; self.day_start=self.broker.equity({p['symbol']:p['entry'] for p in self.broker.positions.values()})
        if self._last_week != week:
            self._last_week=week; self.week_start=self.broker.equity({p['symbol']:p['entry'] for p in self.broker.positions.values()})

    def _risk_halted(self,equity):
        self._refresh_periods(); day_dd=(self.day_start-equity)/max(self.day_start,1)*100; week_dd=(self.week_start-equity)/max(self.week_start,1)*100
        return day_dd>=self.cfg['risk']['max_daily_loss_pct'] or week_dd>=self.cfg['risk']['max_weekly_loss_pct']

    async def scan(self,symbol):
        candles,snap=await self.client.snapshot(symbol,self.cfg['market']['interval'],self.cfg['market']['warmup'])
        htf_rows=await asyncio.gather(*[self.client.klines(symbol,tf,220) for tf in self.cfg['market']['htf']])
        htf_bias=consensus([pd.DataFrame(r) for r in htf_rows if len(r)>=205]) if all(len(r)>=205 for r in htf_rows) else 'NEUTRAL'
        if len(candles)<210:return {'symbol':symbol,'exchange':self.exchange,'status':'warmup','vetoes':['insufficient_candles']}
        snap['data_age_sec']=max(0,(int(time.time()*1000)-candles[-1]['ts'])/1000); snap['oi_prev']=self.prev_oi.get(symbol,snap['oi']); self.prev_oi[symbol]=snap['oi']
        df=pd.DataFrame(candles); a=analyze(df,snap,self.cfg,htf_bias=htf_bias); a['htf_bias']=htf_bias; a['symbol']=symbol; a['exchange']=self.exchange; a['ts']=int(time.time()*1000)
        self.store and self.store.log('decision',a)
        prices={p['symbol']:snap['price'] for p in self.broker.positions.values()}; eq=self.broker.equity(prices)
        if self._risk_halted(eq): a['vetoes'].append('portfolio_kill_switch')
        for pid,p in list(self.broker.positions.items()):
            if p['symbol']!=symbol: continue
            if self.cfg['trading'].get('dynamic_tp',True) and a['side']==p['side'] and a.get('target'): p['target']=float(a['target'])
            closed=self.broker.mark(pid,snap['price'])
            if closed:self.store and self.store.log('paper_close',closed)
        last=self.last_trade.get(symbol,0); cooldown=self.cfg['risk'].get('cooldown_min',0)
        if cooldown and time.time()-last<cooldown*60: a['vetoes'].append('cooldown')
        if a['side']!='FLAT' and not a['vetoes']:
            inst=self.instrument_map.get(symbol)
            p,why=plan(a,eq,self.cfg,len(self.broker.positions),sum(x['side']==a['side'] for x in self.broker.positions.values()),inst)
            if p:
                pos=self.broker.open(a,p); self.last_trade[symbol]=time.time(); self.store and self.store.log('paper_open',pos); a['action']='OPEN'; a['position']=pos
            else:a['action']='RISK_BLOCK:'+why
        else:a['action']='NO_TRADE'
        return a

    async def scan_many(self,symbols,concurrency=8):
        sem=asyncio.Semaphore(concurrency)
        async def one(s):
            async with sem:
                try:return await self.scan(s)
                except Exception as e:return {'symbol':s,'exchange':self.exchange,'action':'ERROR','error':str(e)}
        return await asyncio.gather(*[one(s) for s in symbols])

    @staticmethod
    def scan_line(a):
        return f"{a.get('exchange','')}:{a.get('symbol')} {a.get('action','')} side={a.get('side')} quality={a.get('quality_score')} score={a.get('score')} edge={a.get('edge_bps')} regime={a.get('regime')} vetoes={','.join(a.get('vetoes',[]))}"
