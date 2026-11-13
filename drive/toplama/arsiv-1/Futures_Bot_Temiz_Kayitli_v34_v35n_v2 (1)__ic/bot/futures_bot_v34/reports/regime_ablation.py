"""Tek işlem bazında gölge karşılaştırma; portföy karşı-olgusunu simüle etmez."""
from __future__ import annotations
import argparse,json,math
from scanner.regime_shadow import GATES


def analyze(rows):
    byid={}; duplicates=[]; volume_count=0
    for row in rows:
        typ=row.get('kind')
        if typ=='volume_shadow':volume_count+=1;continue
        if typ not in ('entry','features','close'):continue
        try:key=(row['exchange'],row['symbol'],row['side'],int(row['opened_at']))
        except (KeyError,ValueError,TypeError):raise ValueError('bozuk olay kimliği')
        d=byid.setdefault(key,{})
        if typ in d:duplicates.append((key,typ))
        else:d[typ]=row
    if duplicates:raise ValueError('yinelenen kayıt kimliği; güvenilir eşleme yapılamaz')
    result={'entry_count':sum('entry' in x for x in byid.values()),
            'close_count':sum('close' in x for x in byid.values()),
            'incomplete_count':sum(not all(k in x for k in ('entry','features','close')) for x in byid.values()),
            'volume_observations':volume_count,'gates':{},
            'warning':'Retrospektif; portföy limitleri/kaçırılan diğer işlemler/funding belirsizliği modellenmedi. Nedensel kâr kanıtı değildir.'}
    for gate in GATES:
        groups={'pass':[],'block':[],'unknown':[]}
        for d in byid.values():
            if not ('entry' in d and 'close' in d):continue
            try: pnl=float(d['close']['realized_pnl'])
            except (KeyError,TypeError,ValueError):continue
            if not math.isfinite(pnl):continue
            v=d.get('features',{}).get('gates',{}).get(gate)
            group='block' if v is True else 'pass' if v is False else 'unknown'
            groups[group].append(pnl)
        result['gates'][gate]={k:{'count':len(v),'pnl_sum':sum(v),'pnl_mean':sum(v)/len(v) if v else None} for k,v in groups.items()}
    return result


def main():
    ap=argparse.ArgumentParser(description='Retrospektif gölge karşılaştırma')
    ap.add_argument('input', help='indikator_shadow.jsonl')
    ap.add_argument('--output', help='JSON sonuç dosyası')
    args=ap.parse_args()
    with open(args.input,encoding='utf-8') as f:rows=[json.loads(x) for x in f if x.strip()]
    text=json.dumps(analyze(rows),ensure_ascii=False,indent=2,allow_nan=False)
    if args.output:
        with open(args.output,'w',encoding='utf-8') as f:f.write(text+'\n')
    else:print(text)
if __name__=='__main__':main()
