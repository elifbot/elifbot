"""Paper futures muhasebesi — PnL, komisyon, limit testleri."""
from __future__ import annotations

import pytest

from portfolio.paper_futures import (
    LONG,
    SHORT,
    PaperPortfolio,
    verify_pnl_formulas,
)


def _pf(balance: float = 2_000.0) -> PaperPortfolio:
    return PaperPortfolio(balance, fee_rate=0.0005)


def test_reference_pnl_formulas_are_exact() -> None:
    """Spec'teki LONG +4.4975 / SHORT +4.5025 referansları birebir tutmalı."""
    verify_pnl_formulas()


def test_long_pnl_exact() -> None:
    """LONG 5 birim 100->101: gross 5.0, fee 0.25 + 0.2525, net +4.4975."""
    pf = _pf()
    res = pf.open_position("b", "X", LONG, 100.0, 500.0, leverage=1.0, step_size=1.0, now_ms=1)
    assert res.ok and res.position is not None
    rec = pf.close_position("b", "X", 101.0, now_ms=2)
    assert rec is not None
    assert rec.gross_pnl == pytest.approx(5.0, abs=1e-10)
    assert rec.realized_pnl == pytest.approx(4.4975, abs=1e-10)


def test_short_pnl_exact() -> None:
    """SHORT 5 birim 100->99: gross 5.0, fee 0.25 + 0.2475, net +4.5025."""
    pf = _pf()
    res = pf.open_position("b", "X", SHORT, 100.0, 500.0, leverage=1.0, step_size=1.0, now_ms=1)
    assert res.ok and res.position is not None
    rec = pf.close_position("b", "X", 99.0, now_ms=2)
    assert rec is not None
    assert rec.gross_pnl == pytest.approx(5.0, abs=1e-10)
    assert rec.realized_pnl == pytest.approx(4.5025, abs=1e-10)


def test_single_entry_fee_deduction() -> None:
    """Marj ve giriş komisyonu TEK adımda düşülmeli (iki ayrı adım değil)."""
    pf = _pf(1_000.0)
    res = pf.open_position("b", "X", LONG, 100.0, 100.0, leverage=5.0, step_size=0.001, now_ms=1)
    assert res.ok and res.position is not None
    expected = 1_000.0 - 100.0 - res.position.entry_fee
    assert pf.balance == pytest.approx(expected, abs=1e-10)


def test_balance_change_equals_net_pnl_on_close() -> None:
    """Açılış+kapanış sonrası bakiye değişimi net PnL'e eşit olmalı."""
    pf = _pf(1_000.0)
    before = pf.balance
    res = pf.open_position("b", "X", LONG, 100.0, 100.0, leverage=5.0, step_size=0.001, now_ms=1)
    assert res.ok
    rec = pf.close_position("b", "X", 103.0, now_ms=2)
    assert rec is not None
    assert (pf.balance - before) == pytest.approx(rec.realized_pnl, abs=1e-9)


def test_leverage_not_multiplied_into_pnl_twice() -> None:
    """Kaldıraç yalnızca miktarı belirler; PnL'e ikinci kez çarpılmaz."""
    pf = _pf(2_000.0)
    # marj 100, kaldıraç 5 -> notional 500 -> qty 5 @100
    res = pf.open_position("b", "X", LONG, 100.0, 100.0, leverage=5.0, step_size=1.0, now_ms=1)
    assert res.ok and res.position is not None
    assert res.position.qty_base == 5.0
    rec = pf.close_position("b", "X", 101.0, now_ms=2)
    assert rec is not None
    assert rec.gross_pnl == pytest.approx(5.0, abs=1e-10)  # 5*1, 5*5*1 DEĞİL


def test_total_position_limit_post_open() -> None:
    """7. pozisyon reddedilmeli (tavan 6)."""
    pf = _pf(10_000.0)
    for i in range(6):
        side = LONG if i % 2 == 0 else SHORT  # 3 LONG + 3 SHORT
        assert pf.open_position("b", f"S{i}", side, 100.0, 100.0, leverage=5.0,
                                step_size=1.0, now_ms=1).ok
    r = pf.open_position("b", "S6", LONG, 100.0, 100.0, leverage=5.0, step_size=1.0, now_ms=1)
    assert not r.ok and "toplam pozisyon limiti" in r.reason


def test_same_direction_limit_post_open() -> None:
    """5. aynı yönlü pozisyon reddedilmeli, ters yön kabul edilmeli."""
    pf = _pf(10_000.0)
    for i in range(4):
        assert pf.open_position("b", f"S{i}", LONG, 100.0, 100.0, leverage=5.0,
                                step_size=1.0, now_ms=1).ok
    r5 = pf.open_position("b", "S4", LONG, 100.0, 100.0, leverage=5.0, step_size=1.0, now_ms=1)
    assert not r5.ok and "aynı yön limiti" in r5.reason
    r_short = pf.open_position("b", "S5", SHORT, 100.0, 100.0, leverage=5.0,
                               step_size=1.0, now_ms=1)
    assert r_short.ok


def test_utilisation_cap_post_open() -> None:
    """Marj kullanımı %45'i aşacaksa giriş reddedilmeli."""
    pf = _pf(1_000.0)
    assert pf.open_position("b", "A", LONG, 100.0, 400.0, leverage=2.0,
                            step_size=0.001, now_ms=1).ok  # 400/1000 = 0.40
    r = pf.open_position("b", "B", LONG, 100.0, 100.0, leverage=2.0, step_size=0.001, now_ms=1)
    assert not r.ok and "marj kullanım limiti" in r.reason


def test_balance_floor_blocks_entry() -> None:
    """Bakiye tabanının altına düşürecek giriş reddedilmeli."""
    pf = PaperPortfolio(200.0, fee_rate=0.0005, balance_floor=100.0, max_utilisation=1.0)
    r = pf.open_position("b", "A", LONG, 100.0, 150.0, leverage=1.0, step_size=0.001, now_ms=1)
    assert not r.ok and "bakiye tabanı" in r.reason


def test_balance_never_negative() -> None:
    """Zararlı kapanışta dahi bakiye negatife düşmez."""
    pf = PaperPortfolio(500.0, fee_rate=0.0005, max_utilisation=1.0, balance_floor=0.0)
    res = pf.open_position("b", "X", LONG, 100.0, 400.0, leverage=5.0, step_size=0.001, now_ms=1)
    assert res.ok
    pf.close_position("b", "X", 1.0, now_ms=2)  # %99 düşüş
    assert pf.balance >= 0.0


def test_daily_loss_limit_blocks_new_positions() -> None:
    """Günlük zarar limiti aşıldığında yeni giriş engellenir."""
    pf = PaperPortfolio(1_000.0, daily_loss_limit_pct=0.05, max_utilisation=1.0)
    res = pf.open_position("b", "X", LONG, 100.0, 200.0, leverage=5.0, step_size=0.001, now_ms=1)
    assert res.ok
    pf.close_position("b", "X", 90.0, now_ms=2)  # ~-100 USDT
    assert pf.daily_loss_limit_hit()
    r = pf.open_position("b", "Y", LONG, 100.0, 100.0, leverage=5.0, step_size=0.001, now_ms=3)
    assert not r.ok and "günlük zarar" in r.reason


def test_leverage_cap_enforced() -> None:
    """20x üzeri kaldıraç reddedilir."""
    pf = _pf()
    r = pf.open_position("b", "X", LONG, 100.0, 100.0, leverage=21.0, step_size=0.001, now_ms=1)
    assert not r.ok and "kaldıraç" in r.reason


def test_multi_exchange_isolation() -> None:
    """Binance BTCUSDT ile OKX BTC-USDT-SWAP ayrı anahtarlar; limitler birleşmez."""
    pf = _pf(10_000.0)
    for i in range(4):
        assert pf.open_position("binance", f"B{i}", LONG, 100.0, 100.0, leverage=5.0,
                                step_size=1.0, now_ms=1).ok
    r = pf.open_position("okx", "BTC-USDT-SWAP", LONG, 100.0, 100.0, leverage=5.0,
                         step_size=1.0, now_ms=1)
    assert r.ok, "OKX pozisyonu Binance limitine takılmamalı"
    assert ("binance", "B0") in pf.positions
    assert ("okx", "BTC-USDT-SWAP") in pf.positions


def test_stale_price_guard() -> None:
    """Bayat fiyatla (2x poll) yeni giriş reddedilir."""
    pf = _pf()
    r = pf.open_position(
        "b", "X", LONG, 100.0, 100.0, leverage=5.0, step_size=0.001,
        now_ms=300_000, price_ts=1, poll_interval_ms=60_000, stale_factor=2.0,
    )
    assert not r.ok and "bayat fiyat" in r.reason


def test_same_candle_stop_and_target_prefers_stop() -> None:
    """Aynı mumda SL ve TP varsa KONSERVATİF olarak stop seçilir."""
    out = PaperPortfolio.resolve_same_candle(high=110, low=90, stop=95, target=105, side=LONG)
    assert out == "STOP"
    out2 = PaperPortfolio.resolve_same_candle(high=110, low=90, stop=95, target=105, side=SHORT)
    assert out2 == "STOP"


def test_close_all_returns_records() -> None:
    """close_all tüm pozisyonları kapatır ve kayıt döndürür."""
    pf = _pf(5_000.0)
    pf.open_position("b", "A", LONG, 100.0, 100.0, leverage=5.0, step_size=1.0, now_ms=1)
    pf.open_position("okx", "B", SHORT, 100.0, 100.0, leverage=5.0, step_size=1.0, now_ms=1)
    recs = pf.close_all({("b", "A"): (101.0, 2), ("okx", "B"): (99.0, 2)}, reason="session_end")
    assert len(recs) == 2 and pf.open_count() == 0
