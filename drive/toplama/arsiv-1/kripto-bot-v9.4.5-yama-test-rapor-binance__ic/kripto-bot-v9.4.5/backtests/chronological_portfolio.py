"""Timestamp-synchronized, single-wallet multi-asset 5m replay.

All decisions at t close are filled at t+1 open. Exits at later intrabar lows
cannot finance entries at the earlier open. Prior stops are tested before
new intrabar MFE is used. New ratchets apply only to the following bar.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import asdict
import numpy as np
from portfolio.paper_futures import PaperPortfolio
from src.v94_core import V94DecisionCore, features, market_context
from src.adaptive_policy import AdaptivePolicy
from .execution import ExecutionModel


class ChronologicalPortfolioEngine:
    def __init__(self,frames,*,policy=None,disabled=None,legacy=False,slippage_bps=3.,fee_rate=.00035,delay_bars=1, funding_events=None):
        self.frames={s:f.sort_values('open_time').reset_index(drop=True) for s,f in sorted(frames.items())}
        self.policy=policy or AdaptivePolicy();self.core=V94DecisionCore(self.policy,disabled)
        self.legacy=legacy;self.disabled=disabled
        self.execution=ExecutionModel(fixed_slippage_bps=slippage_bps)
        self.fee_rate=fee_rate;self.delay_bars=max(1,int(delay_bars))
        self.wallet=PaperPortfolio(1000.,fee_rate=fee_rate,max_open_positions=1000,
            max_same_direction=None,max_utilisation=.98,daily_loss_limit_pct=.25,max_leverage=10)
        self.indices={s:{int(t):i for i,t in enumerate(f.open_time)} for s,f in self.frames.items()}
        self.feature_cache={};self.rejections=Counter();self.pending={};self.cooldown={};self.meta={}
        self.equity_curve=[];self.stop_history=[];self.signal_count=0;self._day=None
        self.funding_events=funding_events or {}
        self.legacy_strategies={}
        if legacy:
            from strategies.v93_flow_strategy import CausalMarketPanel,V93CanonicalFlowStrategy
            panel=CausalMarketPanel(self.frames)
            self.legacy_strategies={s:V93CanonicalFlowStrategy(symbol=s,market_panel=panel) for s in self.frames}

    def get_features(self,s,i):
        key=(s,i)
        if key not in self.feature_cache:self.feature_cache[key]=features(self.frames[s].iloc[max(0,i-599):i+1])
        return self.feature_cache[key]

    def close(self,s,raw,ts,reason):
        p=self.wallet.positions.get(('BACKTEST',s))
        if p is None:return
        self.wallet.close_position('BACKTEST',s,self.execution.execution_price(raw,p.side,is_entry=False),now_ms=ts,reason=reason)
        self.cooldown[s]=ts+self.policy.cooldown_bars*300000
        self.meta.pop(s,None)

    def run(self,start_ts,end_ts):
        times=sorted(set.intersection(*(set(x) for x in self.indices.values())))
        times=[t for t in times if start_ts<=t<end_ts]
        for ts in times:
            rows={s:self.frames[s].iloc[self.indices[s][ts]] for s in self.frames}
            for s,row in rows.items():
                if ('BACKTEST',s) in self.wallet.positions:
                    self.wallet.mark_price('BACKTEST',s,float(row.open),ts)
            day=ts//86400000
            if day!=self._day:
                self.wallet.day_start_balance=self.wallet.equity
                self.wallet.blocked_new_positions=False
                self._day=day
            # Settlement is charged to positions held before this exact timestamp, using
            # the open mark, never the future close. New entries at settlement pay no retroactive funding.
            for s, events in self.funding_events.items():
                p=self.wallet.positions.get(('BACKTEST',s))
                if p is None:continue
                for event in events:
                    event_ts=event['fundingTime']
                    if event_ts==ts and event_ts>p.opened_at and event_ts not in p.funding_event_ts:
                        amount=p.qty_base*float(rows[s].open)*event['fundingRate']*(1 if p.side=='LONG' else -1)
                        self.wallet.balance-=amount;p.funding_fee+=amount
                        p.funding_event_ts.append(event_ts);p.funding_label='historical funding applied, open-mark approximation'
            # Phase 1: known open quotes, prior stop gaps and precommitted exit instructions.
            for s,row in rows.items():
                p=self.wallet.positions.get(('BACKTEST',s))
                if p is not None:
                    self.wallet.mark_price('BACKTEST',s,float(row.open),ts)
                    gap=float(row.open)<=p.stop_price if p.side=='LONG' else float(row.open)>=p.stop_price
                    if gap:self.close(s,float(row.open),ts,'STOP_GAP')
            due=[(s,p) for s,p in self.pending.items() if p['execute_ts']<=ts]
            for s,pending in due:
                if pending['kind']=='EXIT':self.close(s,float(rows[s].open),ts,pending['reason'])
            # Phase 2: committed next-open entries, using only money available at this open.
            for s,pending in sorted(due,key=lambda x:(-x[1].get('strength',0),x[0])):
                self.pending.pop(s,None)
                if pending['kind']!='ENTRY' or ('BACKTEST',s) in self.wallet.positions:continue
                side=pending['side'];raw=float(rows[s].open);atr=pending['atr']
                if abs(raw-pending['signal_close'])>self.policy.max_entry_drift_atr*atr:
                    self.rejections['NEXT_OPEN_DRIFT']+=1;continue
                fill=self.execution.execution_price(raw,side,is_entry=True)
                try:stop=self.policy.initial_stop(side,fill,atr) if not self.legacy else fill*(.92 if side=='LONG' else 1.08)
                except ValueError:self.rejections['ENTRY_RISK_CAP']+=1;continue
                qty=500/fill;candidate_risk=abs(fill-stop)*qty
                eq=self.wallet.equity
                current_risk=sum(max(0,(p.entry_price-p.stop_price) if p.side=='LONG' else (p.stop_price-p.entry_price))*p.qty_base for p in self.wallet.positions.values())
                directional=sum(max(0,(p.entry_price-p.stop_price) if p.side=='LONG' else (p.stop_price-p.entry_price))*p.qty_base for p in self.wallet.positions.values() if p.side==side)
                # Apply the same aggregate budget to legacy comparisons; cap legacy risk at emergency stop.
                if not self.legacy and (current_risk+candidate_risk>eq*self.policy.total_risk_fraction or directional+candidate_risk>eq*self.policy.directional_risk_fraction):
                    self.rejections['AGGREGATE_RISK_BUDGET']+=1;continue
                result=self.wallet.open_position('BACKTEST',s,side,fill,50.,leverage=10.,step_size=.000001,now_ms=ts,stop_price=stop)
                if result.ok:self.meta[s]={'atr':atr,'initial_risk':candidate_risk,'signal_ts':pending['signal_ts']}
                else:self.rejections['WALLET_'+result.reason]+=1
            # Phase 3: price ranges are observed only after open allocations are final.
            for s,row in rows.items():
                p=self.wallet.positions.get(('BACKTEST',s))
                if p is None:continue
                touched=float(row.low)<=p.stop_price if p.side=='LONG' else float(row.high)>=p.stop_price
                if touched:
                    reason='PROFIT_LOCK_STOP' if p.unrealised_pnl(p.stop_price)>0 else 'TACTICAL_STOP' if not self.legacy else 'EMERGENCY_STOP'
                    self.close(s,p.stop_price,ts+300000,reason);continue
                favorable=float(row.high) if p.side=='LONG' else float(row.low)
                p.mfe_usdt=max(p.mfe_usdt,p.unrealised_pnl(favorable))
                self.wallet.mark_price('BACKTEST',s,float(row.close),ts+300000)
            prefixes={s:self.frames[s].iloc[max(0,self.indices[s][ts]-599):self.indices[s][ts]+1] for s in self.frames}
            ctx=market_context(prefixes,ts)
            # Phase 4: close-time decisions and next-bar stop changes.
            for s,row in rows.items():
                i=self.indices[s][ts]
                if i<119:continue
                f=self.get_features(s,i);p=self.wallet.positions.get(('BACKTEST',s))
                if p is not None:
                    if self.legacy:
                        dec=self.legacy_strategies[s].evaluate_exit(prefixes[s],p,price=float(row.close),now_ms=ts+300000,fee_rate=self.fee_rate)
                    else:dec=self.core.exit_decision(f,p.side,(ts+300000-p.opened_at)/1000,p.unrealised_pnl(float(row.close)),self.meta[s]['initial_risk'])
                    if dec.get('should_exit') and s not in self.pending:
                        self.pending[s]={'kind':'EXIT','execute_ts':ts+self.delay_bars*300000,'reason':dec.get('exit_kind','FLOW_EXIT')}
                    old=p.stop_price
                    if self.legacy:
                        if p.mfe_usdt>=1.55:
                            keep=.8 if p.mfe_usdt>=8 else .72 if p.mfe_usdt>=4.5 else .65
                            locked=p.mfe_usdt*keep if p.mfe_usdt>=2.2 else max(.55,p.notional*self.fee_rate*2+.25)
                            cand=p.entry_price+(1 if p.side=='LONG' else -1)*locked/p.qty_base
                            cand=min(cand,float(row.close)*.9992) if p.side=='LONG' else max(cand,float(row.close)*1.0008)
                            p.stop_price=max(old,cand) if p.side=='LONG' else min(old,cand)
                    elif self.disabled!='ADAPTIVE_EXIT':
                        p.stop_price=self.policy.ratchet(side=p.side,entry=p.entry_price,qty=p.qty_base,atr=self.meta[s]['atr'],mfe_usdt=p.mfe_usdt,old_stop=old,mark=float(row.close),fees_usdt=p.notional*self.fee_rate*2)
                    self.stop_history.append({'symbol':s,'known_after':ts+300000,'old':old,'new':p.stop_price})
                    continue
                if s in self.pending or ts+300000<self.cooldown.get(s,0):continue
                if self.legacy:
                    res=self.legacy_strategies[s].evaluate(prefixes[s]);decision={'side':res.signal,'reason':res.regime}
                else:decision=self.core.decide(f,ctx)
                if decision['side'] not in ('LONG','SHORT'):
                    self.rejections[decision['reason']]+=1;continue
                self.signal_count+=1
                self.pending[s]={'kind':'ENTRY','side':decision['side'],'execute_ts':ts+self.delay_bars*300000,
                    'atr':f.atr,'strength':abs(f.flow_score),'signal_close':float(row.close),'signal_ts':ts+300000}
            self.equity_curve.append({'ts':ts+300000,'equity':self.wallet.equity,'open':len(self.wallet.positions)})
        remaining=len(self.wallet.positions)
        for _,s in list(self.wallet.positions):self.close(s,float(self.frames[s].iloc[self.indices[s][times[-1]]].close),times[-1]+300000,'TEST_END_MARK_TO_MARKET')
        trades=[asdict(t) for t in self.wallet.closed_trades]
        pnl=np.array([t['realized_pnl'] for t in trades]);curve=np.array([1000.]+[x['equity'] for x in self.equity_curve]+[self.wallet.balance])
        return {'engine':'shared_wallet_next_open','legacy':self.legacy,'disabled':self.disabled,
            'starting_equity':1000.,'ending_equity':self.wallet.balance,'net_pnl':self.wallet.balance-1000,
            'trade_net_sum':float(pnl.sum()),'trades':trades,'trade_count':len(trades),
            'gross_pnl':sum(t['gross_pnl'] for t in trades),'fees':sum(t['entry_fee']+t['exit_fee'] for t in trades),
            'funding_cost':sum(t['funding_fee'] for t in trades),'funding_label':'historical events applied at settlement using 5m open mark' if self.funding_events else 'EXCLUDED_UNAVAILABLE',
            'win_rate_pct':float((pnl>0).mean()*100) if len(pnl) else 0.,
            'profit_factor':float(pnl[pnl>0].sum()/max(-pnl[pnl<0].sum(),1e-12)) if len(pnl) else None,
            'max_equity_drawdown_usdt':float((np.maximum.accumulate(curve)-curve).max()),
            'rejections':dict(self.rejections),'signals':self.signal_count,'cancelled_terminal_pending':len(self.pending),
            'terminal_marked_positions':remaining,'equity_curve':self.equity_curve,
            'limitations':['Stops modeled from OHLC, adverse-first ordering when ambiguous.','Funding uses 5m open mark, not exchange settlement mark. Non-aligned funding timestamps are not modeled.','Fees and slippage fixed, no historical maker queue.','Legacy arm uses old entry/exit but new clock and shared wallet; not an exact rerun of v9.3.']}
