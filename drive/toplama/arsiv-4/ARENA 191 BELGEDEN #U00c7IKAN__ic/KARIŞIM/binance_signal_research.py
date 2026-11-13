#!/usr/bin/env python3
"""One-symbol Binance public candle analysis, no database, no orders or PAPER."""
import argparse,json,sys,time
from acar.binance_public_data import BinancePublicDetails
from acar.confluence10 import confluence_snapshot

def evaluate(client,symbol,clock_ms=None):
 clock_ms=clock_ms or (lambda:time.time_ns()//1_000_000)
 bars=client.complete_history(symbol,now_ms=clock_ms());now=clock_ms()//1000
 close=bars[-1].timestamp+60
 if close>now or now-close>30:raise ValueError('closed candle stale or future')
 result=confluence_snapshot(bars)
 return {'venue':'BINANCE','symbol':symbol,'mode':'PUBLIC_RESEARCH_ONLY_NO_PAPER','closed_bars':len(bars),'as_of_s':now,'latest_bar_close_s':close,'research':result,
         'warning':'Single snapshot, not a trade recommendation, no orders. No funding, book or account risk approval.'}

def main(argv=None):
 p=argparse.ArgumentParser(description='Binance kapalı mumları üzerinde araştırma; PAPER başlatmaz')
 p.add_argument('--symbol',required=True);p.add_argument('--binance-host',choices=('fapi','www'),default='fapi');a=p.parse_args(argv)
 try:
  client=BinancePublicDetails(binance_host=a.binance_host);result=evaluate(client,a.symbol)
  print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0 if result['research'].get('ready') else 1
 except (ValueError,TypeError,OSError) as e:
  print(json.dumps({'status':'DATA_UNAVAILABLE','reason':type(e).__name__},ensure_ascii=False),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
