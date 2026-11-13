"""Demo panel must not fabricate equity and per-position prices."""
from src.dashboard import LiveBotHub
from src.risk import Position


def test_demo_panel_bilinmeyen_piyasa_fiyati_ozsermayeyi_uydurmaz(tmp_path):
 hub=LiveBotHub(db_path=tmp_path/'demo.db')
 symbol='BTC/USDT'
 hub.executor.positions[symbol]=Position(symbol,'LONG',100.,1.,90.)
 hub.executor.last_prices.pop(symbol,None)
 hub.executor._price_receipt_mono.pop(symbol,None)
 payload=hub.build_state_payload()
 assert payload['equity_usdt'] is None and payload['unrealized_usdt'] is None
 assert payload['total_return_pct'] is None
 row=next(p for p in payload['open_positions'] if p['symbol']==symbol)
 assert row['price'] is None and row['pnl_usdt'] is None


def test_demo_heartbeat_bilinmeyen_ozsermayeyi_sifir_saymaz(tmp_path):
 hub=LiveBotHub(db_path=tmp_path/'demo.db')
 hub.executor.positions['BTC/USDT']=Position('BTC/USDT','LONG',100.,1.,90.)
 hub.executor.last_prices.pop('BTC/USDT',None)
 hub.executor._price_receipt_mono.pop('BTC/USDT',None)
 hub._sync_health_meta()
 saved=hub.store.get_meta('bot_status')
 assert saved['equity_usdt'] is None and saved['unrealized_usdt'] is None
