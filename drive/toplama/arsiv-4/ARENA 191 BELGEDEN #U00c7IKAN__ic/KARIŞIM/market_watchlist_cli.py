#!/usr/bin/env python3
"""Produce an OKX worker config from a fresh universe snapshot, without trading."""
import argparse,json,sys,time
from pathlib import Path
from acar.market_watchlist import make_watchlist

def main(argv=None):
 p=argparse.ArgumentParser(description='Taze market raporundan 1–4 OKX simgesi için PAPER ayarı üret; PAPER başlatmaz')
 p.add_argument('--report',required=True);p.add_argument('--out',required=True)
 p.add_argument('--target-notional',required=True);p.add_argument('--leverage',required=True);p.add_argument('--min-notional',required=True)
 p.add_argument('--count',type=int,default=4);p.add_argument('--poll-seconds',type=int,default=10)
 a=p.parse_args(argv)
 try:
  source=Path(a.report);dest=Path(a.out)
  if source.resolve()==dest.resolve():raise ValueError('input and output identical')
  if source.stat().st_size>10_000_000:raise ValueError('report too large')
  report=json.loads(source.read_text(encoding='utf-8'))
  config,summary=make_watchlist(report,now_ms=time.time_ns()//1_000_000,target_notional=a.target_notional,leverage=a.leverage,min_notional=a.min_notional,count=a.count,poll_seconds=a.poll_seconds)
  with dest.open('x',encoding='utf-8') as f:json.dump(config,f,ensure_ascii=False,indent=2);f.write('\n')
  print(json.dumps(summary,ensure_ascii=False));return 0
 except (OSError,ValueError,TypeError) as e:
  print('İzleme listesi oluşturulmadı: '+str(e),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
