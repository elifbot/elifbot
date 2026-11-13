"""5m OHLC counterfactual; never submits orders; does NOT simulate v37 execution."""
import asyncio, csv, json, math, time, statistics, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import aiohttp

ROOT=Path('/home/user/v7_paper_test')
OUT=Path('/home/user/analiz_raporu/vwap_cvd')
S=60_000

def iso_ms(s): return int(datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1000)
def simulation(row, bars, now_ms):
    event=int(row['ts_ms']);start=(event//S+1)*S
    if start+5*S>now_ms-2000: return None,'5m_not_closed'
    by_ts={b[0]:b for b in bars}; candles=[by_ts.get(start+i*S) for i in range(5)]
    if any(c is None for c in candles): return None,'missing_candles'
    direction=1 if row['v7_fade_direction']=='LONG' else -1
    slip=.0005; fee=.0005
    entry=candles[0][1]*(1+direction*slip)
    tp=entry*(1+direction*.008); sl=entry*(1-direction*.005)
    for b in candles:
        ts,o,h,l,c=b
        if direction==1:
            stop_hit=l<=sl; tp_hit=h>=tp; gap=o<=sl
        else:
            stop_hit=h>=sl; tp_hit=l<=tp; gap=o>=sl
        if stop_hit:
            exit_raw=o if gap else sl; reason='sl';end=ts+S;break
        if tp_hit:
            exit_raw=tp;reason='tp';end=ts+S;break
    else:
        exit_raw=candles[-1][4];reason='timeout';end=start+5*S
    exit_fill=exit_raw*(1-direction*slip)
    gross=100*direction*(exit_fill-entry)/entry
    fees=100*fee*(1+exit_fill/entry)
    return {'entry_ts':start,'end_bar_ts':end,'entry':entry,'exit':exit_fill,
            'gross_pct':gross,'fee_pct':fees,'net_pct':gross-fees,'reason':reason},None

async def main():
    records=[json.loads(x) for x in (ROOT/'logs/v7_karsilastirma.jsonl').read_text().splitlines()]
    events=list(csv.DictReader((ROOT/'logs/ws_olay.csv').open(encoding='utf8')))
    enrich=list(csv.DictReader((ROOT/'logs/ws_sinyal_zenginlestirme.csv').open(encoding='utf8')))
    for e in events:e['ms']=iso_ms(e['ts_utc'].replace(' ','T')+'+00:00')
    for e in enrich:e['ms']=iso_ms(e['ts_utc'])
    enrich_matched=0; enrich_unmatched=[]
    for r in records:
        if not r['dispatched_to_v37_guards']:
            r['cvd_status']='not_measured';r['other_reasons']='';continue
        hits=[e for e in events if e['exchange']==r['exchange'] and e['symbol']==r['symbol'] and e['ms']==r['ts_ms']]
        if len(hits)!=1:
            r['cvd_status']='event_unmatched';enrich_unmatched.append([r['symbol'],r['ts_ms'],'event',len(hits)]);continue
        e=hits[0]
        hits=[z for z in enrich if z['exchange']==r['exchange'] and z['symbol']==r['symbol'] and 0<=z['ms']-e['ms']<=15_000]
        if len(hits)!=1:
            r['cvd_status']='enrich_unmatched';enrich_unmatched.append([r['symbol'],r['ts_ms'],'enrich',len(hits)]);continue
        z=hits[0];enrich_matched+=1
        reasons=[x for x in z['reasons'].split(';') if x]
        r['cvd_status']='opposes' if 'cvd_opposes_entry' in reasons else ('other_flow_veto' if any(x.startswith(('orderflow_','cvd_','taker_')) for x in reasons) else 'pass')
        r['other_reasons']=';'.join(x for x in reasons if not x.startswith(('orderflow_','cvd_','taker_')))
        r['signal_accepted']=z['accepted'];r['decision_ts']=z['ms'];r['all_reasons']=z['reasons']

    keys=sorted({(r['exchange'],r['symbol']) for r in records})
    start=min(r['ts_ms'] for r in records)//S*S
    if '--offline' in sys.argv:
        stored=json.loads((OUT/'kapanmis_mumlar.json').read_text())
        now=iso_ms(stored['captured_utc']);data=stored['bars'];errors=stored['errors']
    else:
        now=int(time.time()*1000)
        sem=asyncio.Semaphore(4); data={}; errors={}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as sess:
            async def fetch(ex,sym):
                async with sem:
                    if ex=='binance':
                        url='https://www.binance.com/fapi/v1/klines'; params={'symbol':sym,'interval':'1m','startTime':start,'endTime':now,'limit':100}
                    else:
                        url='https://www.okx.com/api/v5/market/history-candles'; params={'instId':sym,'bar':'1m','limit':100}
                    try:
                        async with sess.get(url,params=params) as res:
                            res.raise_for_status(); raw=await res.json()
                        if ex=='okx':
                            if raw.get('code')!='0': raise ValueError('OKX code '+str(raw.get('code')))
                            raw=raw['data']
                        out=[]
                        for b in raw:
                            ts=int(b[0]);v=[float(z) for z in b[1:5]]
                            if ts+S>now-2000 or (ex=='okx' and (len(b)<9 or str(b[8])!='1')):continue
                            if not all(math.isfinite(x) and x>0 for x in v):continue
                            out.append([ts,*v])
                        data[ex+'|'+sym]=sorted(out)
                    except Exception as err:errors[ex+'|'+sym]=type(err).__name__+': '+str(err)[:160]
            await asyncio.gather(*(fetch(*key) for key in keys))
    results=[];excluded=Counter()
    for r in records:
        rr,err=simulation(r,data.get(r['exchange']+'|'+r['symbol'],[]),now)
        if err:excluded[err]+=1
        results.append({**r,'simulation':rr,'exclusion':err})
    (OUT/'kapanmis_mumlar.json').write_text(json.dumps({'captured_utc':datetime.fromtimestamp(now/1000,timezone.utc).isoformat(),'sources':['https://www.binance.com/fapi/v1/klines','https://www.okx.com/api/v5/market/history-candles'],'bars':data,'errors':errors},ensure_ascii=False))
    (OUT/'olay_sonuclari.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in results))
    def summary(name,cond):
        allr=[r for r in results if cond(r)];valid=[r for r in allr if r['simulation'] is not None]
        vals=[r['simulation']['net_pct'] for r in valid]
        return {'group':name,'recorded':len(allr),'replay_n':len(valid),'excluded':len(allr)-len(valid),'symbols':len({(r['exchange'],r['symbol']) for r in valid}),
                'average_net_pct':sum(vals)/len(vals) if vals else None,'median_net_pct':statistics.median(vals) if vals else None,
                'positive':sum(v>0 for v in vals),'positive_pct':100*sum(v>0 for v in vals)/len(vals) if vals else None,
                'exit_reasons':dict(Counter(r['simulation']['reason'] for r in valid))}
    groups=[summary('all',lambda r:True),summary('vwap_rejected',lambda r:r['indicator_reason']=='indikator_vwap_yon'),
      summary('indicators_passed',lambda r:r['v7_direction_indicator_pass']),
      summary('cvd_opposes',lambda r:r['cvd_status']=='opposes'),summary('cvd_opposes_only',lambda r:r['cvd_status']=='opposes' and not r['other_reasons']),
      summary('cvd_opposes_other_veto',lambda r:r['cvd_status']=='opposes' and bool(r['other_reasons'])),
      summary('cvd_pass',lambda r:r['cvd_status']=='pass'), summary('cvd_not_measured',lambda r:r['cvd_status']=='not_measured')]
    obj={'now_utc':datetime.fromtimestamp(now/1000,timezone.utc).isoformat(),'candidates':len(records),'symbols':len(keys),'enrichment_matched':enrich_matched,'enrichment_unmatched':enrich_unmatched,'fetch_errors':errors,'excluded':dict(excluded),'method':{'entry':'next 1m candle open after signal','horizon':'5 fully closed 1m bars','tp_pct':.8,'sl_pct':.5,'slippage_pct_per_side':.05,'taker_fee_pct_per_side':.05,'both_hit':'stop first','no_funding':True},'groups':groups}
    (OUT/'ozet.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2))
    print(json.dumps(obj,ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
