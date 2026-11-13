"""Only fake and local offline tests. Never contacts exchanges."""
import asyncio
import copy
import pytest
from src import main
from src.config import load_config

@pytest.mark.parametrize('mode',['live','testnet','',None,'unknown'])
def test_diger_modlar_broker_kurulmadan_reddedilir(monkeypatch,mode):
 cfg=copy.deepcopy(load_config());cfg['genel']['mod']=mode
 monkeypatch.setattr(main,'load_config',lambda:cfg)
 def forbidden(*a,**kw):raise AssertionError('broker kurulmamali')
 monkeypatch.setattr(main,'ExchangeManager',forbidden)
 with pytest.raises(RuntimeError,match='YALNIZ PAPER'):
  asyncio.run(main.main())

def test_paper_ana_giris_eski_kilit_noktasini_gecer(monkeypatch):
 cfg=copy.deepcopy(load_config());cfg['genel']['mod']='paper'
 monkeypatch.setattr(main,'load_config',lambda:cfg)
 class Reached(Exception):pass
 def halt(*a,**kw):raise Reached('broker kurulum sinirina ulasildi')
 monkeypatch.setattr(main,'ExchangeManager',halt)
 monkeypatch.setattr(main,'load_optimized_params',lambda cfg:None)
 with pytest.raises(Reached,match='broker kurulum'):
  asyncio.run(main.main())

def test_katalog_baslangici_basarisizsa_broker_kapatilir(monkeypatch):
 cfg=copy.deepcopy(load_config());cfg['genel']['mod']='paper';cfg['futures']['tum_pariteler']=True
 cfg['genel']['kaldıraç']=10
 monkeypatch.setattr(main,'load_config',lambda:cfg)
 monkeypatch.setattr(main,'load_optimized_params',lambda cfg:None)
 class Fake:
  closed=False
  async def discover_futures(self,**kw):raise RuntimeError('sentetik katalog hatasi')
  async def close(self):self.closed=True
 broker=Fake()
 monkeypatch.setattr(main,'ExchangeManager',lambda cfg:broker)
 with pytest.raises(RuntimeError,match='sentetik katalog hatasi'):asyncio.run(main.main())
 assert broker.closed
