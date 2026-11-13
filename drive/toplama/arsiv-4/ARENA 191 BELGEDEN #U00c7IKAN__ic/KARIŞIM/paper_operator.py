#!/usr/bin/env python3
"""Explicit operator actions for the local simulation; no network or real orders."""
import argparse,json,sqlite3,sys,time,uuid
from acar.unified_simulator import UnifiedSimulator
from acar.worker_lock import WorkerLock

def main(argv=None):
 p=argparse.ArgumentParser(description='Yerel PAPER defteri için açık operatör işlemleri; ağ ve gerçek emir yok')
 sub=p.add_subparsers(dest='action',required=True)
 f=sub.add_parser('funding',help='Operatörün doğruladığı gerçekleşmiş funding girdisi')
 f.add_argument('--db',required=True);f.add_argument('--symbol',required=True);f.add_argument('--settlement-ts',required=True,type=int)
 f.add_argument('--finalized-at',required=True,type=int);f.add_argument('--rate',required=True);f.add_argument('--mark-price',required=True)
 f.add_argument('--next-funding',required=True,type=int);f.add_argument('--confirm-manual-funding',action='store_true')
 u=sub.add_parser('unlock',help='Güvenlik şartları sağlanırsa giriş kilidini operatör isteğiyle kaldır')
 u.add_argument('--db',required=True);u.add_argument('--confirm-unlock',action='store_true')
 a=p.parse_args(argv)
 if a.action=='funding' and not a.confirm_manual_funding:
  print('İşlem yapılmadı: doğrulanmış settlement için --confirm-manual-funding gerekir.',file=sys.stderr);return 2
 if a.action=='unlock' and not a.confirm_unlock:
  print('İşlem yapılmadı: --confirm-unlock gerekir.',file=sys.stderr);return 2
 try:
  with WorkerLock(a.db):
   sim=UnifiedSimulator(a.db);now=int(time.time());cid='operator:'+uuid.uuid4().hex
   if a.action=='funding':
    result=sim.settle_funding(cid,symbol=a.symbol,settlement_ts=a.settlement_ts,finalized_at=a.finalized_at,rate=a.rate,mark_price=a.mark_price,next_funding=a.next_funding,now=now)
    result={'result':result,'warning':'Operatör girdisi; kaynak ve gerçekleşmiş fiyat bu program tarafından doğrulanmaz.'}
   else:result=sim.clear_entry_lock(cid,now)
   print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0
 except (ValueError,TypeError,OSError,sqlite3.Error) as e:
  print('Operatör işlemi uygulanmadı: '+str(e),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
