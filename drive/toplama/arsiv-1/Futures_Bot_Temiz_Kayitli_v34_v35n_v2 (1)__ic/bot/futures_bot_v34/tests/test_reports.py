"""Rapor testleri — Sharpe bastırma ve funding etiketi."""
from __future__ import annotations

from portfolio.paper_futures import FUNDING_LABEL, LONG, SHORT, TradeRecord
from reports.pnl_report import SHARPE_SUPPRESSED_TEXT, PnLReport, render_table


def make_trade(pnl: float, side: str = LONG, margin: float = 100.0, closed_at: int = 0) -> TradeRecord:
    """Deterministik TradeRecord üretir."""
    return TradeRecord(
        exchange="binance",
        symbol="BTCUSDT",
        side=side,
        entry_price=100.0,
        exit_price=101.0,
        qty_base=5.0,
        margin=margin,
        leverage=5.0,
        entry_fee=0.25,
        exit_fee=0.25,
        gross_pnl=pnl + 0.5,
        realized_pnl=pnl,
        opened_at=closed_at - 60_000,
        closed_at=closed_at,
        reason="test",
    )


def test_sharpe_suppressed_for_29_trades() -> None:
    """29 kapalı işlemde Sharpe hesaplanmaz, açık mesaj yazılır."""
    rep = PnLReport(trades=[make_trade(1.0, closed_at=i) for i in range(29)],
                    starting_balance=1_000.0, ending_balance=1_029.0)
    text = rep.render()
    assert SHARPE_SUPPRESSED_TEXT in text
    assert "hesaplanamaz" in text and "yetersiz veri" in text
    assert rep.sharpe() is None


def test_sharpe_suppressed_for_zero_trades() -> None:
    """İşlem yoksa Sharpe hesaplanamaz."""
    rep = PnLReport(trades=[], starting_balance=1_000.0, ending_balance=1_000.0)
    text = rep.render()
    assert SHARPE_SUPPRESSED_TEXT in text
    assert "İşlem yok" in text


def test_sharpe_computed_at_30_trades() -> None:
    """30 ve üzeri işlemde Sharpe sayısal olarak hesaplanır."""
    trades = [make_trade(1.0 + (i % 3), closed_at=i) for i in range(35)]
    rep = PnLReport(trades=trades, starting_balance=1_000.0, ending_balance=1_000.0)
    assert rep.sharpe() is not None
    assert SHARPE_SUPPRESSED_TEXT not in rep.render()


def test_funding_labeled_unknown() -> None:
    """Funding 'bilinmiyor' olarak etiketlenir; teyitli sıfır gibi sunulmaz."""
    rep = PnLReport(trades=[make_trade(1.0)], starting_balance=1_000.0, ending_balance=1_001.0)
    text = rep.render()
    assert FUNDING_LABEL in text
    assert "funding hariç" in text


def test_win_rate_and_profit_factor() -> None:
    """Kazanma oranı ve profit factor doğru hesaplanır."""
    trades = [make_trade(2.0, closed_at=1), make_trade(2.0, closed_at=2),
              make_trade(-1.0, closed_at=3), make_trade(-1.0, closed_at=4)]
    rep = PnLReport(trades=trades, starting_balance=1_000.0, ending_balance=1_002.0)
    assert rep.win_rate == 0.5
    assert rep.profit_factor == 2.0
    assert rep.total_realized == 2.0


def test_long_short_split() -> None:
    """LONG/SHORT dağılımı ayrı hesaplanır."""
    trades = [make_trade(1.0, LONG, closed_at=1), make_trade(-1.0, SHORT, closed_at=2)]
    split = PnLReport(trades=trades).long_short_split()
    assert split["LONG"]["count"] == 1
    assert split["SHORT"]["count"] == 1
    assert split["SHORT"]["pnl"] == -1.0


def test_max_drawdown_positive() -> None:
    """MDD zarar serisinde pozitif olmalı."""
    trades = [make_trade(5.0, closed_at=1), make_trade(-3.0, closed_at=2),
              make_trade(-2.0, closed_at=3)]
    rep = PnLReport(trades=trades, starting_balance=1_000.0)
    assert rep.max_drawdown() == 5.0


def test_render_table_without_records() -> None:
    """Kayıt yoksa açık mesaj döner."""
    assert render_table([]) == "(işlem yok)"
