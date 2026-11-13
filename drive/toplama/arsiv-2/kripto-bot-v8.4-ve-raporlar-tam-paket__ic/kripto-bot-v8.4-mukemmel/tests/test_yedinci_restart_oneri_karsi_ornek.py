"""The suggested PENDING-only recovery check is insufficient (isolated DB)."""
from src.state_store import StateStore
from src.risk import Position

def proposed(store):
 with store._conn() as conn:
  for table in ('paper_intents','paper_close_intents','paper_funding_intents','paper_layer_intents'):
   if conn.execute(f"SELECT 1 FROM {table} WHERE status='PENDING' LIMIT 1").fetchone(): return True
  if conn.execute('SELECT COUNT(*) FROM open_positions').fetchone()[0] > 0:
   if not conn.execute("SELECT 1 FROM bot_meta WHERE key='paper_account'").fetchone(): return True
   if not conn.execute("SELECT 1 FROM bot_meta WHERE key='position_meta'").fetchone(): return True
  return False

def test_completed_journal_but_missing_account_is_not_safe_to_unlock(tmp_path):
 store=StateStore(tmp_path/'isolated.db')
 with store._conn() as c:
  c.execute("INSERT INTO paper_close_intents VALUES ('example','BTC/USDT','{}','CLOSED',0)")
 assert proposed(store) is False
 assert store.paper_requires_recovery() is True

def test_metadata_presence_is_not_validity(tmp_path):
 store=StateStore(tmp_path/'isolated.db')
 store.save_position(Position('BTC/USDT','LONG',100.,1.,90.))
 store.set_meta('paper_account',{})
 store.set_meta('position_meta',{})
 assert proposed(store) is False
 assert store.paper_requires_recovery() is True
