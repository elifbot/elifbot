"""Tek sembollü, yalnızca simülasyon yapan canlı PAPER karar motoru.
İşlem fiyatları halka açık en iyi alış/satıştan türetilen varsayımlardır.
"""
import copy,datetime,math
from dataclasses import asdict
from .strategy import Confluence,Breakout
from .market_safety import funding_gate
from .portfolio import evaluate_portfolio, Limits

INITIAL=1000.0
RISK=0.005
NOTIONAL_CAP=250.0
FEE=0.0005
SLIP=0.0002
MAX_SPREAD_BPS=8.0
FUNDING_NO_ENTRY_SEC=600
FUNDING_EXIT_SEC=180
MAX_HOLD_SEC=1800

def initial_state(now):
 return {'version':1,'started_at':now,'cash':INITIAL,'initial_cash':INITIAL,'last_bar':None,'position':None,'trade_count':0,'halt':False,'halt_reason':'','daily_halt':False,'day':None,'day_equity':INITIAL,'last_closed_at':None,'signals':{},'last_quote_time':None,'last_settlement':None,'funding_unaccounted':False,'last_fault':'','processed_bars':0}

def unrealized(p,q):
 if not p or not q:return 0.0
 px=q['bid'] if p['side']=='long' else q['ask']
 return (px-p['entry'])*p['qty']*(1 if p['side']=='long' else -1)

def process(state,bars,q,f,now):
 """Yeni state ve olaylar döndürür. Girdi state mutasyona uğramaz."""
 s=copy.deepcopy(state);events=[];trades=[]
 def event(kind,detail):events.append({'time':now,'type':kind,'detail':detail})
 def close(reason):
  p=s['position'];side=p['side'];raw=q['bid'] if side=='long' else q['ask']
  px=raw*(1-SLIP if side=='long' else 1+SLIP);fee=px*p['qty']*FEE
  gross=(px-p['entry'])*p['qty']*(1 if side=='long' else -1)
  net=gross-fee-p['entry_fee'];s['cash']+=gross-fee
  uncertain=bool(s.get('monitoring_uncertain') or s.get('funding_unaccounted') or s.get('halt_reason') in ('KOTASYON_KESINTISI','KACIRILMIS_MUM','BAYAT_MUM'))
  t={'execution_uncertain':uncertain,'entry_time':p['entry_time'],'exit_time':now,'side':side,'entry':p['entry'],'exit':px,'qty':p['qty'],'gross':gross,'fees':p['entry_fee']+fee,'net':net,'reason':reason}
  trades.append(t);s['trade_count']+=1;s['position']=None;s['last_closed_at']=now;event('PAPER_CLOSE',reason)
 latest=bars[-1] if bars else None
 if s['position'] and s.get('halt_reason') in ('KOTASYON_KESINTISI','KACIRILMIS_MUM','BAYAT_MUM'):
  s['monitoring_uncertain']=True
 q_valid=(q is not None and all(isinstance(q.get(k),(int,float)) and math.isfinite(q[k]) for k in ('bid','ask','time','spread_bps')) and 0<q['bid']<=q['ask'] and -5<=now-q['time']<=20)
 if not q_valid:q=None
 if s['last_bar'] is not None and (latest is None or now-(latest.timestamp+60)>90):
  if not s['halt']: event('DATA_HALT','Kapanmış mum verisi eksik veya bayat.')
  s['halt']=True;s['halt_reason']='BAYAT_MUM'
  if s['position']:s['monitoring_uncertain']=True
 if s['position'] and s['last_quote_time'] is not None and now-s['last_quote_time']>30:
  if not s['halt']:event('DATA_HALT','Pozisyon izlenirken kotasyon kesintisi yaşandı.')
  s['halt']=True;s['halt_reason']='KOTASYON_KESINTISI';s['monitoring_uncertain']=True
 if q_valid:s['last_quote_time']=q['time']
 # Settlement'i kaçırdıysa sıfır funding varsayılmaz; sonuç güvenilir değil, giriş kilitlenir.
 if s['position'] and s.get('last_settlement') and now>=s['last_settlement']:
  if not s['funding_unaccounted']:event('FUNDING_UNKNOWN','Uzlaşma geçildi; funding muhasebesi yok, giriş kilitlendi.')
  s['funding_unaccounted']=True;s['halt']=True;s['halt_reason']='FUNDING_MUHASEBESI_EKSIK'
 if f is not None:
  try:valid_funding=funding_gate('long',f['rate'],f['settlement'],f['observed'],now)['reason'] in ('FUNDING_OK','FUNDING_ADVERSE')
  except (KeyError,TypeError):valid_funding=False
  if not valid_funding:f=None
  else:s['last_settlement']=f['settlement']
 # Kotasyon varsa mevcut pozisyon her döngüde izlenir; bu, sürekli borsa stopu değildir.
 if s['position'] and q_valid:
  p=s['position'];mark=q['bid'] if p['side']=='long' else q['ask']
  if (p['side']=='long' and mark<=p['stop']) or (p['side']=='short' and mark>=p['stop']):close('STOP')
  elif (p['side']=='long' and mark>=p['target']) or (p['side']=='short' and mark<=p['target']):close('HEDEF')
  elif f is None:close('FUNDING_BILINMIYOR')
  elif 0<=f['settlement']-now<=FUNDING_EXIT_SEC:close('FUNDING_ONCESI')
  elif now-p['entry_time']>=MAX_HOLD_SEC:close('MAX_SURE')
 # UTC günlük zarar kapısı özsermaye üzerinden, yalnız gözlemlenen kotasyonlarda.
 day=datetime.datetime.fromtimestamp(now,datetime.timezone.utc).date().isoformat()
 eq=s['cash']+unrealized(s['position'],q)
 if (q_valid or not s['position']) and s['day']!=day:s['day']=day;s['day_equity']=eq;s['daily_halt']=False
 if q_valid and eq<=s['day_equity']*.98 and not s['daily_halt']:
  s['daily_halt']=True;event('DAILY_HALT','Günlük özsermaye kaybı %2 eşiğine ulaştı.')
 if latest is None:return s,events,trades
 if s['last_bar'] is None:
  if now-(latest.timestamp+60)>90 or latest.timestamp+60>now+5:
   s['last_fault']='BAYAT_BASLANGIC_VERISI';return s,events,trades
  s['last_bar']=latest.timestamp;event('WARMUP',f'{len(bars)} kapanmış mum; geçmişte sanal işlem açılmadı.')
  return s,events,trades
 if latest.timestamp<s['last_bar']:
  s['halt']=True;s['halt_reason']='MUM_ZAMANI_GERI';event('DATA_HALT',s['halt_reason']);return s,events,trades
 if latest.timestamp==s['last_bar']:return s,events,trades
 if latest.timestamp-s['last_bar']!=60:
  s['halt']=True;s['halt_reason']='KACIRILMIS_MUM';s['monitoring_uncertain']=bool(s.get('monitoring_uncertain') or s['position']);event('DATA_HALT','En az bir mum kaçırıldı; yeni girişler kilitli.');s['last_bar']=latest.timestamp;return s,events,trades
 s['last_bar']=latest.timestamp;s['processed_bars']+=1
 if now-(latest.timestamp+60)>90 or latest.timestamp+60>now+5:
  s['halt']=True;s['halt_reason']='BAYAT_MUM';event('DATA_HALT',s['halt_reason']);return s,events,trades
 ca=Confluence()(bars);br=Breakout()(bars)
 s['signals']={'confluence':ca.side if ca else 'hold','breakout':br.side if br else 'hold','bar_close':latest.timestamp+60}
 event('BAR',f"Confluence: {s['signals']['confluence']}; kırılım: {s['signals']['breakout']}")
 if s['halt'] or s['daily_halt'] or s['position'] or not ca or not br or ca.side!=br.side:return s,events,trades
 if s['last_closed_at'] and now-s['last_closed_at']<300:event('BLOCK','COOLDOWN');return s,events,trades
 if not q_valid:event('BLOCK','KOTASYON_BILINMIYOR');return s,events,trades
 if q['spread_bps']>MAX_SPREAD_BPS:event('BLOCK','YUKSEK_SPREAD');return s,events,trades
 if f is None:event('BLOCK','FUNDING_BILINMIYOR');return s,events,trades
 fg=funding_gate(ca.side,f['rate'],f['settlement'],f['observed'],now,window=FUNDING_NO_ENTRY_SEC)
 if not fg['allowed'] or f['settlement']-now<FUNDING_NO_ENTRY_SEC:event('BLOCK',fg['reason'] if not fg['allowed'] else 'FUNDING_YAKIN');return s,events,trades
 side=ca.side;raw=q['ask'] if side=='long' else q['bid'];entry=raw*(1+SLIP if side=='long' else 1-SLIP)
 distance=ca.atr*1.5;sign=1 if side=='long' else -1;stop=entry-sign*distance;target=entry+sign*ca.atr*3
 if not all(math.isfinite(x) and x>0 for x in (entry,distance,stop,target)):event('BLOCK','GECERSIZ_RISK');return s,events,trades
 # İki taraflı ücret, spread ve kayma tahmini hareket/maliyet kapısı.
 mid=(q['bid']+q['ask'])/2;unit_cost=(q['ask']-q['bid'])+2*mid*(SLIP+FEE)
 if abs(target-entry)<1.15*unit_cost:event('BLOCK','EDGE_BELOW_COST');return s,events,trades
 estimated_loss=distance+entry*(2*FEE+SLIP);qty=min(max(s['cash'],0)*RISK/estimated_loss,NOTIONAL_CAP/entry)
 if qty<=0 or not math.isfinite(qty):event('BLOCK','YETERSIZ_BAKIYE');return s,events,trades
 # Aynı altyapı çoklu varlık denetimini destekler; burada tek pozisyon sınırı korunur.
 cap=Limits(per_trade_fraction=RISK,total_risk_fraction=.02,directional_risk_fraction=.01,gross_notional=NOTIONAL_CAP,per_position_notional=NOTIONAL_CAP,max_positions=1,max_per_asset=1,fee_rate=FEE,slippage_rate=SLIP)
 verdict=evaluate_portfolio(s['cash'],[],{'side':side,'asset':'BTC','entry':entry,'stop':stop,'qty':qty,'mark':entry},cap)
 if not verdict['allowed']:event('BLOCK','PORTFOY_'+verdict['reason']);return s,events,trades
 entry_fee=entry*qty*FEE;s['cash']-=entry_fee
 s['position']={'side':side,'entry':entry,'qty':qty,'entry_time':now,'entry_fee':entry_fee,'stop':stop,'target':target,'signal_bar':latest.timestamp}
 event('PAPER_OPEN',f'{side.upper()} sanal pozisyon; stratejiler uyumlu.')
 return s,events,trades
