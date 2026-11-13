"""Kaydedilmiş kapanan mumları değişiklik yapmadan, köken bilgisiyle dışa aktarır."""
import argparse,csv,sqlite3,sys
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

def export(db,out):
 db=Path(db).resolve();out=Path(out).resolve()
 if db==out or out.suffix.lower()!='.csv':raise ValueError('Çıktı farklı bir .csv dosyası olmalı.')
 with closing(sqlite3.connect('file:'+quote(str(db),safe='/')+'?mode=ro',uri=True)) as c:
  c.execute('BEGIN')
  rows=c.execute('SELECT timestamp,open,high,low,close,volume,origin,captured_at FROM candles ORDER BY timestamp').fetchall()
 if not rows:raise ValueError('Kaydedilmiş mum yok.')
 out.parent.mkdir(parents=True,exist_ok=True)
 with out.open('x',newline='',encoding='utf-8') as f:
  w=csv.writer(f);w.writerow(['timestamp','open','high','low','close','volume','origin','captured_at']);w.writerows(rows)
 return len(rows)
def main():
 p=argparse.ArgumentParser(description='OKX kapalı mum arşivini CSV olarak dışa aktar')
 p.add_argument('--db',default='data/paper.sqlite');p.add_argument('--out',required=True);a=p.parse_args()
 try:print(f"{export(a.db,a.out)} mum dışa aktarıldı: {a.out}")
 except (ValueError,OSError,sqlite3.Error) as e:p.exit(2,f'Hata: {e}\n')
if __name__=='__main__':main()
