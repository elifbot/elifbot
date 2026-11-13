"""Cevrimdisi simulasyon: sentetik islem akisi ile tum boru hattini (ozellik -> sinyal -> risk -> paper
broker -> cikis) test eder. GERCEK PIYASA SONUCU DEGILDIR; sadece yazilimin calistigini dogrular."""
from __future__ import annotations

import random
import tempfile

from .alerts import Alerter
from .brokers.paper import PaperBroker
from .config import Config
from .engine import Engine
from .models import Trade
from .safety import SafetyMonitor
from .storage import Storage


class _Market:
    def __init__(self, ex: str, sym: str, rnd: random.Random):
        self.ex, self.sym, self.rnd = ex, sym, rnd
        self.price = rnd.uniform(0.5, 500.0)
        self.burst_left = 0
        self.dir = 1
        self.avg = rnd.uniform(1500.0, 4000.0)

    def step(self, ts: float) -> list[Trade]:
        r = self.rnd
        if self.burst_left == 0 and r.random() < 1 / 240:
            self.burst_left, self.dir = r.randint(30, 60), r.choice((1, -1))
        bursting = self.burst_left > 0
        rate = 14 if bursting else 2
        p_buy = (0.5 + 0.38 * self.dir) if bursting else 0.5
        out = []
        for _ in range(max(1, int(r.gauss(rate, rate ** 0.5)))):
            drift = 0.00012 * self.dir if bursting else 0.0
            self.price *= 1 + r.gauss(drift, 0.00006)
            usd = r.expovariate(1 / self.avg)
            out.append(Trade(self.ex, self.sym, ts + r.random() * 0.99, self.price, usd, r.random() < p_buy))
        if bursting:
            self.burst_left -= 1
        return out


async def run_simulation(cfg: Config, seconds: int = 7200, symbols_per_exchange: int = 12, seed: int = 7,
                         start_ts: float = 1_700_000_040.0) -> Engine:
    rnd = random.Random(seed)
    brokers = {ex: PaperBroker(ex, cfg, ec, lambda k, p: None)
               for ex, ec in cfg.exchanges.items() if ec.enabled}
    engine = Engine(cfg, brokers, Alerter(), Storage(":memory:"), SafetyMonitor(cfg.safety),
                    control_dir=tempfile.mkdtemp())
    markets = [_Market(ex, f"SIM{i}/USDT:USDT", rnd) for ex in brokers for i in range(symbols_per_exchange)]
    for t in range(seconds):
        ts = start_ts + t
        for m in markets:
            for tr in m.step(ts):
                engine.on_trade(tr)
        await engine.evaluate(ts + 0.99)
    return engine
