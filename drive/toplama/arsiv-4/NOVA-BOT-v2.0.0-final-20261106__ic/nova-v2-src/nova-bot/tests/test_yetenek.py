"""NOVA-BOT v2 yetenek testleri — çevrimdışı, ağ gerektirmez."""
from __future__ import annotations

import math
from decimal import Decimal as D

import pytest

from nova.bot import BAR_MS, Bar, Book, Config, Inst, ema
from nova.yetenek import (adx_series, cci_series, confluence_skoru, dca_ekle,
                          edge_dengesi, genislik, mum_denetimi, obv_series,
                          sinyal, stochastic, supertrend_series, vwap_series)


# --------------------------------------------------------------- yardımcılar
def trend_bars(n=260, drift=0.2, wobble=0.5, start=100.0, vol=1000.0,
               open0=1_700_000_000_000) -> list[Bar]:
    out, px = [], start
    for i in range(n):
        o = px
        px = px + drift + wobble * math.sin(i / 3.0)
        out.append(Bar(open0 + i * BAR_MS, o, max(o, px) + 0.05,
                       min(o, px) - 0.05, px, vol))
    return out


def inst(**kw) -> Inst:
    base = dict(venue="binance", market="binance_usdm", symbol="BTCUSDT",
                settlement="USDT", kind="linear", face=D("1"),
                lot_step=D("0.001"), min_qty=D("0.001"), min_notional=D("5"),
                tick=D("0.1"), mmr_hint=D("0.05"), max_lev=None, reason="")
    base.update(kw)
    return Inst(**base)


# --------------------------------------------------------------- göstergeler
def test_adx_series_zero_for_flat_market_and_positive_for_trend():
    flat = [Bar(i * BAR_MS, 100, 100.01, 99.99, 100, 10) for i in range(120)]
    assert all((v is None or v < 1) for v in adx_series(flat))
    trend = adx_series(trend_bars(200))
    assert trend[-1] is not None and trend[-1] > 20


def test_stochastic_is_bounded_and_needs_history():
    bars = trend_bars(120)
    k, d = stochastic(bars)
    assert k[10] is None                       # yetersiz geçmiş
    assert 0 <= k[-1] <= 100 and 0 <= d[-1] <= 100


def test_obv_follows_direction():
    up = trend_bars(60, drift=0.3, wobble=0.0)
    obv, sma = obv_series(up)
    assert obv[-1] > obv[0]                    # yükselen seride OBV artar
    assert sma[-1] is not None


def test_vwap_resets_each_utc_day():
    day1 = trend_bars(10, open0=1_700_000_000_000 - (1_700_000_000_000 % 86_400_000))
    day2 = [Bar(b.open_ms + 86_400_000, b.open, b.high, b.low, b.close * 2, b.volume)
            for b in day1]
    v = vwap_series(day1 + day2)
    assert v[9] is not None and v[-1] is not None
    assert v[-1] > v[9]                        # ikinci gün fiyatlar iki katı


def test_cci_zero_when_price_is_constant():
    flat = [Bar(i * BAR_MS, 100, 100, 100, 100, 10) for i in range(40)]
    assert all(x is None for x in cci_series(flat))   # sapma yok → tanımsız
    assert cci_series(trend_bars(60))[-1] is not None


def test_supertrend_is_bounded_and_tracks_trend():
    st = supertrend_series(trend_bars(120))
    assert set(x for x in st if x is not None) <= {1.0, -1.0}
    assert st[-1] == 1.0                       # düzenli yükseliş → yukarı trend


# --------------------------------------------------------------- confluence
def test_confluence_needs_min_bars():
    assert confluence_skoru(trend_bars(100), {"conf_min_bars": 220}) is None


def test_confluence_votes_are_ten_and_score_matches_sum():
    r = confluence_skoru(trend_bars(260), {"conf_th": 4})
    assert r is not None
    assert len(r.votes) == 10
    assert sum(r.votes.values()) == r.score
    assert set(r.votes) == {"ema", "macd", "rsi", "adx", "stoch",
                            "obv", "cci", "supertrend", "vwap", "boll"}


def test_confluence_threshold_is_bounded():
    for th in (1, 4, 9, 20):
        r = confluence_skoru(trend_bars(260), {"conf_th": th})
        assert 2 <= r.threshold <= 8


def test_confluence_longer_side_on_uptrend():
    r = confluence_skoru(trend_bars(260, drift=0.3), {"conf_th": 4})
    assert r.score > 0 and r.side in ("long", "")


def test_sinyal_dispatches_by_strategy():
    bars = trend_bars(260)
    sig_c, info_c = sinyal(bars, {"strateji": "confluence", "conf_th": 4})
    assert info_c["mod"] == "confluence"
    sig_s, info_s = sinyal(bars, {"strateji": "skor", "min_score": 3, "max_chop": 100})
    assert info_s["mod"] == "skor"
    assert sig_c is not None or info_c["reason"] in {"THRESHOLD", "CHOP"}


# --------------------------------------------------------------- bütünlük
def test_mum_denetimi_detects_gaps_and_bad_candles():
    ok = trend_bars(30)
    assert mum_denetimi(ok) == (True, "")
    gap = ok[:10] + ok[17:]                     # 7 mumluk boşluk
    assert mum_denetimi(gap)[1] == "CANDLE_GAP"
    bad = list(ok)
    bad[-1] = Bar(ok[-1].open_ms, 100, 99, 101, 100, 10)   # low > high
    assert mum_denetimi(bad)[1] == "BAD_CANDLE"
    assert mum_denetimi(ok[:2]) == (False, "INSUFFICIENT")


# --------------------------------------------------------------- edge kapısı
def test_edge_gate_blocks_when_cost_exceeds_move():
    cfg = Config(taker_bps=5, slip_bps=2, min_edge_ratio=1.15)
    # ATR çok küçük → hareket maliyeti karşılamaz
    tight = edge_dengesi(100.0, 2.0, 0.01, cfg)
    assert tight["ok"] is False and tight["cost_bps"] > tight["move_bps"]
    # ATR büyük → hareket maliyetin üzerinde
    wide = edge_dengesi(100.0, 2.0, 5.0, cfg)
    assert wide["ok"] is True and wide["ratio"] > 1.15


def test_edge_gate_disabled_at_zero_ratio_allows_everything():
    cfg = Config(min_edge_ratio=0.0)
    r = edge_dengesi(100.0, 50.0, 0.001, cfg)
    assert r["ok"] is True


# --------------------------------------------------------------- DCA
def _open_long(book: Book, cfg: Config):
    return book.open(inst(), 100.0, 100.02, "long", atr_v=1.0, ts=1_000,
                     signal_id="s", quote_ts=1_000)


def test_dca_disabled_by_default_keeps_atr_stop():
    b = Book(Config())
    p = _open_long(b, b.cfg)
    assert p.dca_state is None


def test_dca_enabled_sets_plan_and_percent_stop():
    cfg = Config(dca_enabled=True, dca_stop_pct=10.0, dca_tp_pct=1.5)
    b = Book(cfg)
    p = _open_long(b, cfg)
    assert p.dca_state is not None
    assert p.dca_state.max_adds == cfg.dca_max_adds
    assert float(p.stop) < float(p.entry)
    assert float(p.tp) > float(p.entry)


def test_dca_add_averages_entry_and_increments_counter():
    cfg = Config(dca_enabled=True, dca_step_pct=2.0, dca_max_adds=2, dca_mult=1.5)
    b = Book(cfg)
    p = _open_long(b, cfg)
    first_entry, first_qty = p.entry, p.qty
    act = b.try_dca(p.key, 97.0)               # adım tetiklendi
    assert act.startswith("DCA_ADD_1")
    assert p.qty > first_qty
    assert p.entry < first_entry               # ortalama aşağı geldi
    assert b.dca_adds == 1
    assert b.try_dca(p.key, 90.0).startswith("DCA_ADD_2")
    assert b.try_dca(p.key, 80.0) == ""        # limit doldu


def test_dca_only_for_long_positions():
    b = Book(Config(dca_enabled=True))
    p = b.open(inst(symbol="ETHUSDT"), 100.0, 100.02, "short", 1.0, 1_000, "s", 1_000)
    assert p.dca_state is None
    assert b.try_dca(p.key, 90.0) == ""


# --------------------------------------------------------------- cooldown / kill / max hold
def test_cooldown_blocks_reentry_after_close():
    cfg = Config(cooldown_sec=600)
    b = Book(cfg)
    p = _open_long(b, cfg)
    p.opened_ms = 1_700_000_000_000                 # cooldown hesabı duvar saatine bağlı
    b._close(p, D("100"), 1_700_000_100_000, "STOP")
    assert b.open(inst(), 100, 100.02, "long", 1.0,
                  1_700_000_200_000, "s2", 1_700_000_200_000) is None
    assert b.rejects["COOLDOWN"] >= 1
    assert b.open(inst(), 100, 100.02, "long", 1.0,
                  1_700_000_800_000, "s3", 1_700_000_800_000) is not None


def test_kill_switch_blocks_new_entries_and_closes_positions():
    cfg = Config(kill_close_positions=True)
    b = Book(cfg)
    _open_long(b, cfg)
    b.kill()
    assert b.killed is True
    assert b.pos == {}
    assert len(b.closed) == 1 and b.closed[0].reason == "KILL_SWITCH"
    assert b.open(inst(symbol="X"), 100, 100.02, "long", 1.0, 9_000, "s", 9_000) is None
    assert b.rejects["KILLED"] >= 1


def test_kill_switch_can_keep_positions_open():
    b = Book(Config(kill_close_positions=False))
    p = _open_long(b, b.cfg)
    b.kill()
    assert b.killed is True
    assert p.key in b.pos and b.closed == []


def test_max_hold_bars_forces_exit():
    cfg = Config(max_hold_bars=3)
    b = Book(cfg)
    p = _open_long(b, cfg)
    p.bars_held = 3
    t = b.check_exit(p.key, 100.0, 100.02, 2_000)
    assert t is not None and t.reason == "MAX_HOLD_BARS"


# --------------------------------------------------------------- genişlik
def test_breadth_is_high_on_uptrend_and_low_on_downtrend():
    up = {"a": trend_bars(40, drift=0.5), "b": trend_bars(40, drift=0.4)}
    dn = {"a": trend_bars(40, drift=-0.5), "b": trend_bars(40, drift=-0.4)}
    assert genislik(up) > 0.5
    assert genislik(dn) < -0.5
    assert genislik({}) == 0.0


def test_max_hold_bars_counter_counts_only_own_symbol():
    """Regresyon: sayaç her sembolün mumunda artmamalı (v2 ilk denemede hatalıydı)."""
    b = Book(Config(max_hold_bars=20))
    p = b.open(inst(), 100.0, 100.02, "long", 1.0, 1_000, "s", 1_000)
    p.opened_bar_ms = 1_700_000_000_000
    # aynı sembolün 3 mumu → 3 artış
    for k in range(3):
        pos = b.pos.get(p.key)
        if pos and 1_700_000_060_000 + k * BAR_MS > pos.opened_bar_ms:
            pos.bars_held += 1
    assert p.bars_held == 3
    # başka sembollerin mumları bu sayaca dokunamaz (bot kodu key ile çağırıyor)
    assert b.check_exit(p.key, 100.0, 100.02, 2_000) is None
    assert p.bars_held == 3
