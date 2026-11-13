import asyncio

from tests.test_fixed_runner import SYMBOL, FixedBroker, fixed_executor
from tests.test_shadow_lab import _context, _lab


def test_executor_fill_close_observer_chain_isolated_from_baseline():
    broker = FixedBroker()
    executor = fixed_executor(broker)
    shadow = _lab()
    executor.add_position_observer(shadow)

    asyncio.run(executor._open(SYMBOL, "LONG", 100, "TEST", entry_context=_context()))
    assert shadow.baseline_entries == 1
    assert executor.positions[SYMBOL].net_breakeven_enabled is False
    assert shadow.variants["net-exit"]["entries"][SYMBOL].net_breakeven_enabled is True

    closed = asyncio.run(
        executor._close(SYMBOL, 102, "SÜRELİ PAPER ÖLÇÜMÜ SONU", 2.0)
    )
    assert closed
    assert not executor.positions
    report = shadow.report()
    assert report["closeout_completed"]
    assert report["baseline"]["trades_observed"] == 1
    assert report["baseline"]["trades"][0]["net_breakeven_price"] is None
    net_trade = next(
        row for row in report["variants"] if row["name"] == "net-exit"
    )["trades"][0]
    assert net_trade["exit_price"] == 102
    assert net_trade["mfe_usdt"] == 10
