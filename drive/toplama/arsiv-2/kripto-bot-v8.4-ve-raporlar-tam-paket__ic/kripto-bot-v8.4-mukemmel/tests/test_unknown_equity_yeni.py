"""Unknown prices/equity never become balance or zero in reporting."""
import asyncio
from types import SimpleNamespace
import pytest
from src.risk import Position,RiskManager
from src.telegram import InteractiveTelegramBot
from src.dashboard import ProductionBotHub
from src.state_store import StateStore


def test_panel_bilinmeyen_ozsermayeyi_bakiye_olarak_sunmaz(tmp_path):
 hub=ProductionBotHub(db_path=tmp_path/'panel.db')
 hub.store.set_meta('bot_status',{'balance_usdt':1000.,'equity_usdt':None,'unrealized_usdt':None})
 data=hub.build_state_payload()
 assert data['balance_usdt']==1000.
 assert data['equity_usdt'] is None
 assert data['unrealized_usdt'] is None
 assert data['total_return_pct'] is None


def test_panel_sifir_ozsermaye_bakiye_degildir(tmp_path):
 hub=ProductionBotHub(db_path=tmp_path/'panel.db')
 hub.store.set_meta('bot_status',{'balance_usdt':1000.,'equity_usdt':0.,'unrealized_usdt':-1000.})
 data=hub.build_state_payload()
 assert data['equity_usdt']==0. and data['unrealized_usdt']==-1000.


def test_telegram_bilinmeyen_baslangici_bakiye_diye_yazmaz(tmp_path):
 store=StateStore(tmp_path/'session.db')
 store.set_meta('paper_24h_session',{'start_ts':1.,'start_balance':1000.,'start_equity':None,'hours':24})
 class Broker:
  async def fetch_balance_usdt(self):return 1100.
 bot=InteractiveTelegramBot(executor=None,broker=Broker(),state_store=store)
 msg=asyncio.run(bot._format_daily_report()).lower()
 assert 'başlangıç özsermayesi: bilinmiyor' in msg
 assert 'net oturum k/z: bilinmiyor' in msg


def test_bilinmeyen_fiyatta_telegram_raporu_giris_fiyati_ve_sifir_pnl_uydurmaz(tmp_path):
 from src.executor import Executor
 from src.strategy import Strategy
 from tests._paper_fixtures import make_paper_broker
 e=Executor(make_paper_broker(),RiskManager(),Strategy(),state_store=StateStore(tmp_path/'s.db'))
 e.positions['BTC/USDT']=Position('BTC/USDT','LONG',100.,1.,90.)
 bot=InteractiveTelegramBot(executor=e,broker=e.broker)
 msg=asyncio.run(bot._format_status_report()).lower()
 assert 'açık k/z: bilinmiyor' in msg and 'toplam özsermaye: bilinmiyor' in msg
 assert 'fiyat: bilinmiyor' in msg


def test_ayri_istisna_yalniz_bilinmeyen_fiyati_yakalar():
 from src.equity_reporting import UnknownEquity,safe_unrealized
 class E:
  def total_unrealized_usdt(self):raise UnknownEquity('bayat')
 assert safe_unrealized(E())==(None,False)
 class Bad:
  def total_unrealized_usdt(self):raise RuntimeError('başka hata')
 with pytest.raises(RuntimeError,match='başka hata'):safe_unrealized(Bad())


def test_panel_fiyat_yokken_giris_fiyatini_canli_gostermemeli(tmp_path):
 hub=ProductionBotHub(db_path=tmp_path/'panel.db')
 hub.store.save_position(Position('BTC/USDT','LONG',100.,1.,90.))
 hub.store.set_meta('bot_status',{'balance_usdt':1000.,'equity_usdt':None,'unrealized_usdt':None})
 row=hub.build_state_payload()['open_positions'][0]
 assert row['entry']==100.
 assert row['price'] is None and row['pnl_usdt'] is None
 assert row['pnl_pct'] is None and row['roe_pct'] is None
