import asyncio
import os
import unittest

from tradebot.brokers.paper import PaperBroker
from tradebot.config import Config, EntryCfg, ScannerCfg, _build, assert_live_allowed, load_config, validate
from tradebot.exits import decide_exit
from tradebot.features import Features
from tradebot.indicators import MACD, RSI
from tradebot.models import EntryPlan, Position, Side, Signal, Trade
from tradebot.risk import RiskManager
from tradebot.safety import SafetyMonitor
from tradebot.scoring import score_entry
from tradebot.config import RiskCfg


def feats(**kw):
    base = dict(price=100.0, delta_ratio=0.6, flow_usd=50_000, vol_ratio=5.0, change_pct=0.3, rsi=60.0,
                rsi_prev=58.0, macd_hist=0.5, macd_hist_prev=0.2)
    base.update(kw)
    return Features(**base)


def make_plan(side=Side.LONG, price=100.0, cfg=None):
    cfg = cfg or Config()
    sig = Signal("binance", "X/USDT:USDT", side, 5, price, 0.0, ["t"])
    dist = cfg.stop_distance
    return EntryPlan(sig, price, 500.0, 50.0, 10, dist, price * (1 - side.sign * dist))


class TestIndicators(unittest.TestCase):
    def test_rsi_up(self):
        r = RSI(14)
        for i in range(30):
            r.update(100 + i)
        self.assertEqual(r.value, 100.0)

    def test_rsi_down(self):
        r = RSI(14)
        for i in range(30):
            r.update(100 - i)
        self.assertEqual(r.value, 0.0)

    def test_macd_ready(self):
        m = MACD()
        for i in range(40):
            m.update(100 + (i % 5))
        self.assertTrue(m.ready)


class TestConfig(unittest.TestCase):
    def test_stop_distance(self):
        self.assertAlmostEqual(Config().stop_distance, 0.05)

    def test_stop_too_wide(self):
        c = Config()
        c.risk.stop_loss_usd = 45  # %9 -> 10x tasfiyeye cok yakin
        with self.assertRaises(ValueError):
            validate(c)

    def test_unknown_key(self):
        with self.assertRaises(ValueError):
            _build(RiskCfg, {"stopp_loss_usd": 1})

    def test_example_config_loads(self):
        root = os.path.dirname(os.path.dirname(__file__))
        cfg = load_config(os.path.join(root, "config", "config.example.yaml"))
        self.assertEqual(cfg.mode, "paper")
        self.assertIsNone(cfg.risk.max_open_positions)

    def test_live_gate(self):
        c = Config()
        c.mode = "live"
        os.environ.pop("LIVE_TRADING_CONFIRM", None)
        with self.assertRaises(RuntimeError):
            assert_live_allowed(c)


class TestScoring(unittest.TestCase):
    def test_long(self):
        res = score_entry(feats(), EntryCfg(), ScannerCfg())
        self.assertEqual(res[0], Side.LONG)
        self.assertGreaterEqual(res[1], 4)

    def test_short(self):
        res = score_entry(feats(delta_ratio=-0.6, change_pct=-0.3, rsi=40, macd_hist=-0.5, macd_hist_prev=-0.2),
                          EntryCfg(), ScannerCfg())
        self.assertEqual(res[0], Side.SHORT)

    def test_no_volume_no_signal(self):
        self.assertIsNone(score_entry(feats(vol_ratio=1.0), EntryCfg(), ScannerCfg()))

    def test_thin_flow_blocked(self):
        self.assertIsNone(score_entry(feats(flow_usd=500), EntryCfg(), ScannerCfg()))


class TestRisk(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.safety = SafetyMonitor(self.cfg.safety)
        self.risk = RiskManager(self.cfg, self.safety)

    def acct(self, available=500.0, equity=500.0):
        from tradebot.models import AccountView
        return AccountView(equity, available, 0, 0)

    def sig(self, side=Side.LONG):
        return Signal("binance", "X/USDT:USDT", side, 5, 100.0, 0.0, [])

    def test_stop_prices(self):
        p = self.risk.approve(self.sig(), self.acct(), [], 0.0, False)
        self.assertAlmostEqual(p.stop_price, 95.0)
        self.assertEqual(p.notional, 500.0)
        s = self.risk.approve(self.sig(Side.SHORT), self.acct(), [], 0.0, False)
        self.assertAlmostEqual(s.stop_price, 105.0)

    def test_no_margin(self):
        self.assertEqual(self.risk.approve(self.sig(), self.acct(available=40), [], 0.0, False), "no_margin")

    def test_reserve(self):
        # 50$ marjin + %5 rezerv (25$) = 75$ gerekir
        self.assertEqual(self.risk.approve(self.sig(), self.acct(available=70), [], 0.0, False), "no_margin")
        self.assertNotIsInstance(self.risk.approve(self.sig(), self.acct(available=80), [], 0.0, False), str)

    def test_cooldown(self):
        self.risk.mark("binance", "X/USDT:USDT", 0.0)
        self.assertEqual(self.risk.approve(self.sig(), self.acct(), [], 10.0, False), "cooldown")
        self.assertNotIsInstance(self.risk.approve(self.sig(), self.acct(), [], 400.0, False), str)

    def test_halted(self):
        self.safety.halt("binance", "x", "test", manual=True)
        self.assertEqual(self.risk.approve(self.sig(), self.acct(), [], 0.0, False), "halted")

    def test_optional_limits_off_by_default(self):
        many = [object()] * 50
        self.assertNotIsInstance(self.risk.approve(self.sig(), self.acct(), many, 0.0, False), str)

    def test_optional_limit_on(self):
        self.cfg.risk.max_open_positions = 3
        from tradebot.models import AccountView
        self.assertEqual(self.risk.approve(self.sig(), AccountView(500, 500, 3, 0), [], 0.0, False),
                         "max_positions")


class TestPaper(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.events = []
        self.b = PaperBroker("binance", self.cfg, self.cfg.exchanges["binance"],
                             lambda k, p: self.events.append((k, p)))

    def t(self, price, ts):
        return Trade("binance", "X/USDT:USDT", ts, price, 1000, True)

    def test_maker_needs_price_through(self):
        asyncio.run(self.b.place_entry(make_plan(), 0.0))
        self.b.on_trade(self.t(100.0, 1))      # sadece dokunus: dolmaz
        self.assertEqual(len(self.b.positions), 0)
        self.b.on_trade(self.t(99.9, 2))       # icinden gecti: dolar
        self.assertEqual(len(self.b.positions), 1)

    def test_pending_expires(self):
        asyncio.run(self.b.place_entry(make_plan(), 0.0))
        asyncio.run(self.b.tick(10.0))
        self.assertEqual(len(self.b.pending), 0)
        self.assertEqual(self.events[-1][0], "entry_cancel")

    def test_stop_loss_is_about_25_usd(self):
        asyncio.run(self.b.place_entry(make_plan(), 0.0))
        self.b.on_trade(self.t(99.9, 1))
        pos = self.b.positions["X/USDT:USDT"]
        self.assertAlmostEqual(pos.stop_price, 95.0)   # maker emir limit fiyattan (100) dolar
        self.b.on_trade(self.t(pos.stop_price - 0.01, 2))
        self.assertEqual(len(self.b.positions), 0)
        ex = [p for k, p in self.events if k == "exit"][0]
        self.assertEqual(ex["reason"], "stop")
        self.assertLess(ex["pnl_net"], -25.0)          # komisyon + kayma eklenir
        self.assertGreater(ex["pnl_net"], -27.5)

    def test_short_stop(self):
        asyncio.run(self.b.place_entry(make_plan(Side.SHORT), 0.0))
        self.b.on_trade(self.t(100.1, 1))
        pos = self.b.positions["X/USDT:USDT"]
        self.b.on_trade(self.t(pos.stop_price + 0.01, 2))
        ex = [p for k, p in self.events if k == "exit"][0]
        self.assertLess(ex["pnl_net"], -25.0)
        self.assertGreater(ex["pnl_net"], -27.5)

    def test_margin_locked_and_released(self):
        asyncio.run(self.b.place_entry(make_plan(), 0.0))
        self.assertAlmostEqual(self.b.account().available, 450.0)
        self.b.on_trade(self.t(99.9, 1))
        self.assertAlmostEqual(self.b.account().available, 450.0 - 0.1, places=1)


class TestSafety(unittest.TestCase):
    def test_stale_halts_and_resumes(self):
        s = SafetyMonitor(Config().safety)
        s.touch("okx", 100.0)
        self.assertTrue(s.can_enter("okx"))
        s.check(120.0)                       # 20 sn veri yok
        self.assertFalse(s.can_enter("okx"))
        self.assertTrue(s.can_enter("binance"))   # sadece o borsa
        s.touch("okx", 121.0)
        s.check(122.0)                       # veri geri geldi, bekleme basladi
        self.assertFalse(s.can_enter("okx"))
        s.touch("okx", 140.0)
        s.check(140.0)                       # 15 sn taze veri
        self.assertTrue(s.can_enter("okx"))

    def test_api_errors_halt(self):
        s = SafetyMonitor(Config().safety)
        for i in range(5):
            s.api_error("binance", 0.0, "x")
        self.assertFalse(s.can_enter("binance"))
        s.check(61.0)
        self.assertTrue(s.can_enter("binance"))

    def test_manual_halt_needs_manual_resume(self):
        s = SafetyMonitor(Config().safety)
        s.halt("*", "recon", "uyumsuz", manual=True)
        s.touch("okx", 1.0)
        s.check(500.0)
        self.assertFalse(s.can_enter("binance"))
        s.resume("*", "recon")
        self.assertTrue(s.can_enter("binance"))


class TestExits(unittest.TestCase):
    def pos(self, peak=0.0):
        return Position("binance", "X", Side.LONG, 100.0, 5.0, 500.0, 50.0, 95.0, 0.0, 0.1, [], 4, peak)

    def test_trailing(self):
        r = decide_exit(self.pos(peak=10.0), None, 5.0, 60.0, Config())
        self.assertEqual(r[0], "trailing")

    def test_flow_reversal_with_profit(self):
        f = feats(delta_ratio=-0.2, vol_ratio=0.5, macd_hist=0.1, macd_hist_prev=0.3, change_pct=-0.2)
        r = decide_exit(self.pos(), f, 2.0, 60.0, Config())
        self.assertEqual(r[0], "flow_reversal")

    def test_small_profit_not_exit(self):
        f = feats(delta_ratio=-0.2, vol_ratio=0.5, macd_hist=0.1, macd_hist_prev=0.3, change_pct=-0.2)
        self.assertIsNone(decide_exit(self.pos(), f, 0.2, 60.0, Config()))

    def test_time_stop(self):
        r = decide_exit(self.pos(), None, 0.1, 31 * 60, Config())
        self.assertEqual(r[0], "time_stop")


class TestFilterHook(unittest.TestCase):
    def test_filter_blocks_entries(self):
        from tradebot.simulate import run_simulation
        from tradebot.engine import Engine
        orig = Engine.__init__

        def patched(self, *a, **k):
            orig(self, *a, **k)
            self.entry_filters.append(lambda sig: "macro_event")
        Engine.__init__ = patched
        try:
            eng = asyncio.run(run_simulation(Config(), seconds=60 * 60, symbols_per_exchange=6, seed=3))
        finally:
            Engine.__init__ = orig
        self.assertGreater(eng.stats["signals"], 0)
        self.assertEqual(eng.stats["entry_requested"], 0)
        self.assertEqual(eng.stats["entry"], 0)


class TestSimulation(unittest.TestCase):
    def test_pipeline_smoke(self):
        from tradebot.simulate import run_simulation
        cfg = Config()
        eng = asyncio.run(run_simulation(cfg, seconds=75 * 60, symbols_per_exchange=8, seed=3))
        self.assertGreater(eng.stats["signals"], 0)
        rows = eng.storage.db.execute("select pnl_net, reason from trades").fetchall()
        self.assertGreater(len(rows), 0)
        for pnl, reason in rows:
            self.assertGreater(pnl, -40.0)     # tek islem zarari stop + kayma sinirinda
        for b in eng.brokers.values():
            self.assertGreaterEqual(b.account().available, -1e-6)


if __name__ == "__main__":
    unittest.main()
