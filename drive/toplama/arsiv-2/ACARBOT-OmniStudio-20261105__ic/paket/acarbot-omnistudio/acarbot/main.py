"""Çalıştır: python -m acarbot.main --duration 600"""
import argparse, asyncio
from datetime import datetime, timezone
from pathlib import Path
from .runner import run
from .strategy import STRATEGIES

def main():
    p=argparse.ArgumentParser(description='ACARBOT, yalnız PAPER')
    p.add_argument('--duration',type=float,default=600)
    p.add_argument('--symbols',type=int,default=20)
    p.add_argument('--strategy',choices=STRATEGIES,default='trend')
    p.add_argument('--out',default='')
    a=p.parse_args()
    out=Path(a.out) if a.out else Path('runs')/('acarbot-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    result=asyncio.run(run(out,a.duration,a.symbols,a.strategy))
    raise SystemExit(0 if result['status']=='COMPLETED' else 1)
if __name__=='__main__': main()
