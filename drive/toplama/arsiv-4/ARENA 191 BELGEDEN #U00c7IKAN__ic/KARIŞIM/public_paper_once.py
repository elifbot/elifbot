#!/usr/bin/env python3
"""Explicit opt-in, one-shot OKX public-data PAPER command; no real orders."""
import argparse,json,sys,sqlite3
from acar.unified_simulator import UnifiedSimulator
from acar.public_paper_once import public_paper_once
from acar.worker_lock import WorkerLock

def main():
    p=argparse.ArgumentParser(description='Tek tur halka açık veri kullanan PAPER; gerçek emir yok. Yalnız açık onayla kullanın.')
    p.add_argument('--db',required=True);p.add_argument('--symbol',required=True);p.add_argument('--quantity',required=True)
    p.add_argument('--leverage',required=True);p.add_argument('--min-notional',required=True)
    p.add_argument('--confirm-public-paper',action='store_true')
    a=p.parse_args()
    if not a.confirm_public_paper:
        print('Ağ veya PAPER başlatılmadı; açık --confirm-public-paper gereklidir.',file=sys.stderr);return 2
    try:
        with WorkerLock(a.db):
            sim=UnifiedSimulator(a.db)
            result=public_paper_once(sim,symbol=a.symbol,quantity=a.quantity,leverage=a.leverage,min_notional=a.min_notional)
            print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0 if result.get('action')!='DATA_ERROR' else 2
    except (ValueError,OSError,sqlite3.Error) as e:print('Durduruldu: '+str(e),file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
