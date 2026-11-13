"""Offline illustration: old v7.8 calculations on generated trades/candles."""
import json, math, time
from scanner.v78_flow_adapter import closed_5m, legacy_flow_snapshot
from scanner.v78_indicators import indicator_score
from scanner.v78_strategy import Strategy
now=int(time.time()*1000);last=(now//300000-1)*300000
out=[]
for direction in (1,-1):
 events=[(now-39000+i*1000,100. if direction>0 else 0.,0. if direction>0 else 100.,10000. if direction>0 else 0.,0. if direction>0 else 10000.) for i in range(40)]
 rows=[]
 for i in range(200):
  t=last-(199-i)*300000;o=100+direction*i*.03+math.sin(i*.6)*.05;c=o+direction*.05
  rows.append([t,o,max(o,c)+.06,min(o,c)-.06,c,3000 if i>195 else 1000])
 flow=legacy_flow_snapshot(events,now)
 ind=indicator_score(closed_5m('binance',rows,now),None,True,1.5)
 context={**ind.get('snapshot',{}),**ind,'cvd_slope':flow.get('cvd_slope',0.0),'cvd_divergence':flow.get('cvd_divergence','YOK'),'absorption':flow.get('absorption','YOK'),'oi_signal':flow.get('oi_signal','NOTR')}
 decision=Strategy(w_ind=.4,w_flow=.3,w_news=.15,w_ml=0,flow_trigger=True,flow_th=50,flow_ind_min=10,flow_min_total=15).combine(float(ind['score']),float(flow['score']),0.0,None,market_context=context)
 out.append(dict(synthetic_direction=direction,trade_count=40,candle_count=200,flow_score=flow['score'],technical_score=ind['score'],entry_allowed=ind['entry_allowed'],total=decision['total'],raw_signal=decision['raw_signal'],trigger=decision['trigger'],signal=decision['signal'],orderflow_veto=decision['orderflow_veto'],market_not_live=True))
print(json.dumps(out,indent=2,ensure_ascii=False))
