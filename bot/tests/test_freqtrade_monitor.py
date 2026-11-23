import sqlite3
import tempfile
import unittest
from pathlib import Path
from bot.bot_karsilastirma.freqtrade_live import read_stats
from bot.bot_karsilastirma.freqtrade_smoke import config

class MonitorTests(unittest.TestCase):
    def test_safe_paper_config(self):
        c = config()
        self.assertEqual(c['dry_run_wallet'], 1_000_000)
        self.assertEqual(c['max_open_trades'], -1)
        self.assertIs(c['dry_run'], True)
        self.assertTrue(all(not c['exchange'].get(x) for x in ('key','secret','password')))

    def test_snapshot_db_realized_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/'trades.db'
            self.assertFalse(read_stats(db)['database_ready'])
            with sqlite3.connect(db) as c:
                c.execute('''create table trades (id integer,pair text,is_open integer,is_short integer,
                    open_rate real,close_rate real,open_date text,close_date text,stake_amount real,
                    close_profit_abs real,exit_reason text)''')
                c.executemany('insert into trades values (?,?,?,?,?,?,?,?,?,?,?)',[
                    (1,'A/USDT:USDT',0,0,1,2,'a','b',50,3.5,'roi'),
                    (2,'B/USDT:USDT',0,1,1,2,'a','b',50,-1,'stop'),
                    (3,'C/USDT:USDT',1,1,1,None,'a',None,50,None,None)])
            s = read_stats(db)
            self.assertTrue(s['database_ready'])
            self.assertEqual(s['trades']['total'],3)
            self.assertEqual(s['trades']['open'],1)
            self.assertEqual(s['trades']['closed'],2)
            self.assertEqual(s['trades']['wins'],1)
            self.assertEqual(s['trades']['losses'],1)
            self.assertEqual(s['trades']['realized_profit'],2.5)

if __name__ == '__main__': unittest.main()
