"""New highs change trailing peak and must not leave durable state behind."""
import asyncio
from test_v78_bayat_risk_yeni import open_one


def test_fiyat_tick_tepeyi_dayanikli_saklar(tmp_path):
 async def check():
  ex,b,st=await open_one(tmp_path)
  before=st.load_positions()['BTC/USDT'].peak
  await ex.on_price_tick('BTC/USDT',100.5)
  ram=ex.positions['BTC/USDT'].peak
  saved=st.load_positions()['BTC/USDT'].peak
  assert ram>before and saved==ram
  assert not ex.paper_recovery_locked
  await b.close()
 asyncio.run(check())

def test_tepe_kaydi_diger_yazarin_stopunu_ezmez(tmp_path):
 from copy import deepcopy
 import pytest
 from src.state_store import paper_position_snapshot
 async def check():
  ex,b,st=await open_one(tmp_path)
  pos=ex.positions['BTC/USDT']; old=paper_position_snapshot(pos)
  other=deepcopy(pos);other.stop=95.;st.save_position(other)
  pos.peak=101.
  with pytest.raises(RuntimeError,match='state changed'):
   st.update_paper_risk_if_unchanged(old,pos)
  saved=st.load_positions()['BTC/USDT']
  assert saved.stop==95. and saved.peak==old['peak']
  await b.close()
 asyncio.run(check())

def test_tepe_kaydi_hatasi_finansal_kilidi_kapatir(tmp_path,monkeypatch):
 async def check():
  ex,b,st=await open_one(tmp_path)
  before=st.load_positions()['BTC/USDT'].peak
  def broken(*a,**k):raise OSError('sentetik disk hatası')
  monkeypatch.setattr(st,'update_paper_risk_if_unchanged',broken)
  await ex.on_price_tick('BTC/USDT',100.5)
  assert ex.paper_recovery_locked and st.load_positions()['BTC/USDT'].peak==before
  await b.close()
 asyncio.run(check())
