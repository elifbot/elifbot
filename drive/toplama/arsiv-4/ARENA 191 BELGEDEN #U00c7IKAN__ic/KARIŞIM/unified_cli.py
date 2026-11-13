#!/usr/bin/env python3
"""Ağsız, yeni SQLite defterinde çalışan çoklu-piyasa simülasyon CLI'si."""
import argparse,json,sys,sqlite3,os
from pathlib import Path
from acar.data import Bar
from acar.depth_research import MarketRules
from acar.unified_simulator import UnifiedSimulator
from acar.unified_bot import OfflineUnifiedBot
from acar.omnistudio_contract import build_omni_status
from acar.risk_report import risk_report
from acar.telegram_delivery import notification_status,deliver_telegram,resolve_delivery

def event_execute(sim,record):
    if not isinstance(record,dict):raise ValueError('event must be an object')
    kind=record.get('type');eid=record.get('id');data=record.get('data')
    if not isinstance(data,dict):raise ValueError('data must be an object')
    if kind=='candles':
        d=dict(data);d['rules']=MarketRules(**d['rules']);d['bars']=[Bar(**bar) for bar in d['bars']]
        if d.get('correlation_histories') is not None:d['correlation_histories']={k:[Bar(**bar) for bar in bars] for k,bars in d['correlation_histories'].items()}
        return OfflineUnifiedBot(sim).on_candles(eid,**d)
    if kind=='book':
        d=dict(data);d['rules']=MarketRules(**d['rules']);return OfflineUnifiedBot(sim).on_book(eid,**d)
    if kind=='add':
        d=dict(data);d['rules']=MarketRules(**d['rules']);return sim.add_position(eid,**d)
    if kind=='exit_config':return sim.configure_exit(eid,**data)
    if kind=='funding':return sim.settle_funding(eid,**data)
    if kind=='unlock':return sim.clear_entry_lock(eid,**data)
    if kind=='lock':return sim.lock_entries(eid,**data)
    raise ValueError('unsupported event type')

def main(argv=None):
    p=argparse.ArgumentParser(description='Offline birleşik simülatör: ağ erişimi ve gerçek emir yok')
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--db',required=True);init.add_argument('--cash',default='1000')
    status=sub.add_parser('status');status.add_argument('--db',required=True);status.add_argument('--format',choices=('full','omni','risk'),default='full');status.add_argument('--as-of',type=int)
    run=sub.add_parser('run');run.add_argument('--db',required=True);run.add_argument('--events',required=True);run.add_argument('--out',required=True)
    telegram=sub.add_parser('telegram');telegram.add_argument('--db',required=True);telegram.add_argument('--seq',type=int,required=True);telegram.add_argument('--send',action='store_true');telegram.add_argument('--attempt')
    resolve=sub.add_parser('telegram-resolve');resolve.add_argument('--db',required=True);resolve.add_argument('--seq',type=int,required=True);resolve.add_argument('--decision',choices=('CONFIRMED_SENT','RETRY_APPROVED'),required=True)
    a=p.parse_args(argv)
    try:
        if a.command=='init':
            bot=UnifiedSimulator.create(a.db,a.cash);print(json.dumps(bot.snapshot(),ensure_ascii=False));return 0
        if a.command=='status':
            if a.as_of is not None and a.format!='risk':raise ValueError('--as-of only supported for risk format')
            view=UnifiedSimulator(a.db).snapshot()
            if a.format=='omni':view=build_omni_status(view)
            elif a.format=='risk':view=risk_report(view,a.as_of)
            print(json.dumps(view,ensure_ascii=False));return 0
        if a.command=='telegram':
            if a.send:
                if not a.attempt:raise ValueError('--attempt required with --send')
                value=deliver_telegram(a.db,a.seq,token=os.environ.get('ACAR_TELEGRAM_TOKEN',''),chat_id=os.environ.get('ACAR_TELEGRAM_CHAT_ID',''),attempt_id=a.attempt)
            else:value=notification_status(a.db,a.seq)
            print(json.dumps(value,ensure_ascii=False));return 0
        if a.command=='telegram-resolve':
            print(json.dumps(resolve_delivery(a.db,a.seq,a.decision),ensure_ascii=False));return 0
        db=Path(a.db).resolve();source=Path(a.events).resolve();out=Path(a.out).resolve()
        if len({db,source,out})<3:raise ValueError('db, events and output must be different files')
        sim=UnifiedSimulator(db)
        with source.open('r',encoding='utf-8') as f,out.open('x',encoding='utf-8') as dest:
            for line_no,line in enumerate(f,1):
                if not line.strip():continue
                if len(line)>4_000_000:raise ValueError(f'line {line_no} too large')
                try:
                    obj=json.loads(line);result=event_execute(sim,obj)
                except (ValueError,TypeError,KeyError) as e:raise ValueError(f'line {line_no}: {e}') from e
                dest.write(json.dumps({'line':line_no,'id':obj['id'],'result':result},ensure_ascii=False,allow_nan=False)+'\n');dest.flush()
        print('Çevrimdışı olaylar işlendi. Çıktı: '+str(out));return 0
    except (ValueError,OSError,TypeError,KeyError,sqlite3.Error) as e:
        print('Durduruldu: '+str(e),file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
