#!/usr/bin/env python3
"""One-shot public market-data snapshot; never starts the paper engine."""
import argparse,json,sys
from pathlib import Path
from acar.market_universe import scan

def main(argv=None):
 p=argparse.ArgumentParser(description='OKX ve Binance public USDT sürekli vadeli kontrat keşfi; emir veya PAPER yok')
 p.add_argument('--out',required=True,help='Yeni JSON dosyası (varsa üzerine yazılmaz)')
 p.add_argument('--venues',choices=('okx','both'),default='okx',help='Varsayılan yalnız OKX; Binance sonraki aşamada açıkça both ile seçilir')
 p.add_argument('--binance-host',choices=('fapi','www'),default='fapi',help='www yalnız açık seçilen, eski belgede geçen public uyumluluk yolu; otomatik fallback yok')
 a=p.parse_args(argv);path=Path(a.out)
 # Reserve output before network request to prevent accidental overwrite.
 try:
  with path.open('x',encoding='utf-8') as f:
   venues=('OKX',) if a.venues=='okx' else ('OKX','BINANCE')
   result=scan(binance_host=a.binance_host,venues=venues);json.dump(result,f,ensure_ascii=False,allow_nan=False,indent=2);f.write('\n')
 except (ValueError,OSError) as e:
  print('Tarama durduruldu: '+type(e).__name__,file=sys.stderr);return 2
 print(json.dumps({'mode':result['mode'],'captured_at_ms':result['captured_at_ms'],'counts':result['counts'],'endpoints':result['endpoints'],'output':str(path)},ensure_ascii=False))
 return 0 if result['counts']['total_contracts'] else 1
if __name__=='__main__':raise SystemExit(main())
