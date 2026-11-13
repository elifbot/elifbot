"""Offline one-to-one association of source dispatch records; never deduplicates decisions."""
import argparse,json
from collections import defaultdict,Counter


def match(records, window_ms, start_ms=None, end_ms=None):
    grouped=defaultdict(lambda:{'v4':[],'v78':[]});seen=set();total=Counter()
    for r in records:
        if r.get('stage')!='candidate_dispatch_attempt' or not r.get('ready'):continue
        observed=r.get('observed_ts_ms')
        if start_ms is not None and (observed is None or int(observed)<start_ms):continue
        if end_ms is not None and (observed is None or int(observed)>end_ms):continue
        src=r.get('source');id=r.get('id')
        if src not in ('v4','v78') or not isinstance(id,str) or id in seen:continue
        seen.add(id);key=(r['exchange'],r['symbol'],r['side'])
        grouped[key][src].append((int(r['signal_ts_ms']),id));total[src]+=1
    pairs=[];unmatched=[]
    for key,items in sorted(grouped.items()):
        a=items['v4'];b=items['v78']
        if len(a)*len(b)>2_000_000:raise ValueError(f'matching too many combinations: {key}')
        candidates=sorted((abs(t-u),t,u,i,j) for t,i in a for u,j in b if abs(t-u)<=window_ms)
        used_v4=set();used_v78=set()
        for delta,t,u,i,j in candidates:
            if i in used_v4 or j in used_v78:continue
            used_v4.add(i);used_v78.add(j)
            pairs.append({'exchange':key[0],'symbol':key[1],'side':key[2],'v4_id':i,'v78_id':j,'v4_ts_ms':t,'v78_ts_ms':u,'abs_delta_ms':delta})
        unmatched.extend(i for t,i in a if i not in used_v4)
        unmatched.extend(j for t,j in b if j not in used_v78)
    return {'window_ms':window_ms,'method':'minimum time distance greedy one-to-one within exchange,symbol,side; tie: timestamps,ids',
            'eligible_counts':dict(total),'paired_count':len(pairs),'pairs':pairs,'unmatched_ids':unmatched,
            'note':'Possible temporal association only; not proof of same opportunity or duplicate orders.'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('audit');ap.add_argument('output');ap.add_argument('--start-ms',type=int);ap.add_argument('--end-ms',type=int);args=ap.parse_args()
    with open(args.audit,encoding='utf-8') as f:records=[json.loads(line) for line in f if line.strip()]
    result={'observed_local_start_ms':args.start_ms,'observed_local_end_ms':args.end_ms,'narrow_5sec':match(records,5_000,args.start_ms,args.end_ms),'broad_5min':match(records,300_000,args.start_ms,args.end_ms)}
    with open(args.output,'w',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
if __name__=='__main__':main()
