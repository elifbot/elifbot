"""Gerçek sentetik paper hesabında gecikmeli eşzamanlı açılış kontrolü."""
import asyncio,sqlite3
from test_v78_bayat_risk_yeni import open_one

def test_ayni_sembol_gecikmis_ikinci_acilis_yeni_fill_yapmaz(tmp_path):
 async def check():
  # Var olan örneği kapatıp kendi sıfır risk senaryomuz için durumu resetlemeyiz;
  # aynı sembol üzerinde geciktirilmiş başka bir çağrıyı gösteririz.
  ex,b,st=await open_one(tmp_path)
  paper=b.paper
  before=(paper.balance,paper.total_fees_usdt,ex.positions['BTC/USDT'].qty)
  await ex._open('BTC/USDT','LONG',100.,'DUPLICATE')
  after=(paper.balance,paper.total_fees_usdt,ex.positions['BTC/USDT'].qty)
  with sqlite3.connect(tmp_path/'s.db') as c:
   count=c.execute('select count(*) from paper_intents').fetchone()[0]
  assert after==before and count==1
  await b.close()
 asyncio.run(check())

def test_yarista_ayni_sembol_ikinci_acilis_kazanan_sonrasi_tekrar_kontrol_edilir(tmp_path):
 async def check():
  ex,b,st=await open_one(tmp_path,opened=False)
  arrived=asyncio.Event();release=asyncio.Event()
  original=b.best_price
  async def controlled(symbol,side):
   if asyncio.current_task().get_name()=='second':
    arrived.set();await release.wait()
   return await original(symbol,side)
  b.best_price=controlled
  second=asyncio.create_task(ex._open('BTC/USDT','LONG',100.,'SECOND'),name='second')
  await arrived.wait()
  await ex._open('BTC/USDT','LONG',100.,'FIRST')
  before=(b.paper.balance,b.paper.total_fees_usdt,ex.positions['BTC/USDT'].qty)
  release.set();await second
  after=(b.paper.balance,b.paper.total_fees_usdt,ex.positions['BTC/USDT'].qty)
  with sqlite3.connect(tmp_path/'s.db') as c:
   count=c.execute('select count(*) from paper_intents').fetchone()[0]
  assert after==before and count==1
  await b.close()
 asyncio.run(check())

def test_firsat_takasi_sonrasi_giris_yeniden_hesaplanir(tmp_path):
 import time
 async def check():
  ex,b,st=await open_one(tmp_path)
  ex.risk.margin_mode='cross'
  ex.opportunity_swap_enabled=True
  ex.opportunity_swap_min_age_sec=5
  await ex.on_price_tick('BTC/USDT',100.)
  await ex.on_price_tick('ETH/USDT',100.)
  ex._position_opened_ts['BTC/USDT']=time.time()-1000
  ex.risk.cross_pool_ok=lambda *a,**k: (('BTC/USDT' not in ex.positions),'test')
  await ex._open('ETH/USDT','LONG',100.,'SWAP')
  assert 'BTC/USDT' not in ex.positions and 'ETH/USDT' in ex.positions
  assert len(st.get_trades())==1
  await b.close()
 asyncio.run(check())
