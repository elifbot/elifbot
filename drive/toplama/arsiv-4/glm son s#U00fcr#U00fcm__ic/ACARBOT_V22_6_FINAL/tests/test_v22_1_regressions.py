import time
from phoenix.config import Config
from phoenix.paper import PaperBroker
from tests.test_v22_regressions import signal


def test_env_default_correlation_min_samples_matches_dataclass():
    assert Config.from_env({}).correlation_min_samples == Config().correlation_min_samples == 30


def test_paper_stop_fill_worse_uses_gap_price():
    broker = PaperBroker(Config(paper_stop_fill="worse"), equity=1000)
    s = signal()
    assert broker.submit(s)["status"] == "ACCEPTED"
    mark = s.stop - 5
    closed = broker.update({("BINANCE", s.symbol): mark}, now=time.time() + 60)
    assert closed[0]["exit"] == mark


def test_summary_reports_gap_adjusted_total():
    broker = PaperBroker(Config(), equity=1000)
    s = signal()
    broker.submit(s)
    broker.update({("BINANCE", s.symbol): s.stop - 5}, now=time.time() + 60)
    out = broker.summary()
    assert out["stop_gap_excess_total_usd"] > 0
    assert out["realized_total_gap_adjusted"] < out["realized_total"]
