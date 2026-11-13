"""Çevrimdışı OHLC araştırması; canlı-paper yürütmesiyle aynı simülatör değildir."""
import argparse,hashlib,json
from pathlib import Path
from acar.data import load_csv_bytes
from acar.replay import PaperEngine,Config
from acar.strategy import Confluence,Breakout
from acar.confluence10 import ResearchConfluence10
from acar.research import walk_forward,compare_strategies

def main():
 p=argparse.ArgumentParser(description='CSV üzerinde OFFLINE araştırma, canlı motorun birebir tekrarı değildir')
 p.add_argument('csv');p.add_argument('--out',required=True);p.add_argument('--strategy',choices=('confluence','breakout','confluence10'),default='confluence');p.add_argument('--walk-forward',action='store_true');p.add_argument('--train-bars',type=int,default=250);p.add_argument('--test-bars',type=int,default=100)
 a=p.parse_args()
 try:
  if a.walk_forward and a.strategy!='confluence':raise ValueError('--walk-forward yalnız eski confluence 2/3/4 eşiklerini araştırır; bu stratejiyle kullanılamaz.')
  source=Path(a.csv).resolve();dest=Path(a.out).resolve()
  if source==dest or dest.suffix.lower()!='.json':raise ValueError('Çıktı farklı bir .json dosyası olmalı.')
  raw=source.read_bytes();bars=load_csv_bytes(raw,60)
  cfg=Config(initial_cash=1000,max_notional=250)
  strategy=Confluence() if a.strategy=='confluence' else Breakout() if a.strategy=='breakout' else ResearchConfluence10()
  result=PaperEngine(cfg,strategy).run(bars)
  result['input_sha256']=hashlib.sha256(raw).hexdigest();result['strategy_name']=a.strategy
  result['strategy_comparison']=compare_strategies(bars,cfg)
  if a.walk_forward:result['walk_forward']=walk_forward(bars,cfg,a.train_bars,a.test_bars)
  result['live_parity']=False
  result['research_warning']='Araştırma motoru sonraki mum açılışını ve sabit spreadi kullanır; canlı PAPER motorunda iki strateji uyumu, taze bid/ask ve funding kapısı vardır. Funding, likidasyon ve kısmi dolum modellenmez. Bu geçmiş sonuç gelecekte kârlılık kanıtı değildir.'
  dest.parent.mkdir(parents=True,exist_ok=True)
  with dest.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
  print(f"OFFLINE araştırma: {result['trade_count']} kapanmış işlem. Rapor: {dest}")
 except (ValueError,OSError) as e:p.exit(2,f'Hata: {e}\n')
if __name__=='__main__':main()
