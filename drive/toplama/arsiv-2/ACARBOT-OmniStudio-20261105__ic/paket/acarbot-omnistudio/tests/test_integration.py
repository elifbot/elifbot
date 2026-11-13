"""ACARBOT × OmniStudio entegrasyon testleri — AĞ GEREKTİRMEZ.

Kapsam: sözleşme metaverisi → Decimal spec, çoklu borsa PAPER defteri,
funding yönü, likidasyon mesafesi, akış birim dönüşümü, MTF/genişlik ölçümü,
WS/REST çözümleyicileri, strateji tazelik kapısı ve konsey paritesi.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal as D

import pytest

from acarbot.contracts import (Instrument, parse_binance, parse_gateio, parse_okx,
                               summarize)
from acarbot.flow import (FlowWindow, breadth, mtf_alignment, parse_ticks,
                          roundtrip_cost_bps)
from acarbot import marketdata as md
from acarbot.paperbook import PaperBook, PaperConfig
from acarbot.strategy import closed_candles, decide
from omnistudio.ai.council import AICouncil
from omnistudio.core.types import Candle, Quote, Side, Signal

NOW = 1_800_000_000_000


# ---------------------------------------------------------------- fixtures
def binance_usdm_payload():
    return {"symbols": [
        {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "marginAsset": "USDT",
         "status": "TRADING", "liquidationFee": "0.0125",
         "requiredMarginPercent": "5.0",
         "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001",
                      "maxQty": "1000"},
                     {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                     {"filterType": "MIN_NOTIONAL", "notional": "50"}]},
        {"symbol": "AAPLUSDT", "contractType": "TRADIFI_PERPETUAL",
         "marginAsset": "USDT", "status": "TRADING",
         "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.01", "minQty": "0.01"}]},
        {"symbol": "OLDUSDT", "contractType": "PERPETUAL", "marginAsset": "USDT",
         "status": "SETTLING", "filters": []},
        {"symbol": "BTCUSDC", "contractType": "PERPETUAL", "marginAsset": "USDC",
         "status": "TRADING",
         "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"}]},
    ]}


def okx_swap_payload():
    return {"code": "0", "data": [
        {"instId": "BTC-USDT-SWAP", "ctType": "linear", "ctVal": "0.01",
         "ctValCcy": "BTC", "settleCcy": "USDT", "lotSz": "0.01", "minSz": "0.01",
         "tickSz": "0.1", "lever": "100", "state": "live", "expTime": ""},
        {"instId": "BTC-USD-SWAP", "ctType": "inverse", "ctVal": "100",
         "ctValCcy": "USD", "settleCcy": "BTC", "lotSz": "0.1", "minSz": "0.1",
         "tickSz": "0.1", "state": "live", "expTime": ""},
        {"instId": "AAPL-USDT-XPERP", "ctType": "linear", "ctVal": "0.01",
         "ctValCcy": "AAPL", "settleCcy": "USDT", "lotSz": "0.01", "minSz": "0.01",
         "tickSz": "0.01", "state": "live", "expTime": ""},
        {"instId": "BTC-USDT-251226", "ctType": "linear", "ctVal": "0.01",
         "ctValCcy": "BTC", "settleCcy": "USDT", "lotSz": "0.01", "minSz": "0.01",
         "tickSz": "0.1", "state": "live", "expTime": "1798000000000"},
    ]}


def candles(n=260, start=NOW - 260 * 300_000, step=100.0, drift=0.0, closed=True):
    out = []
    px = 1000.0
    for i in range(n):
        o = px
        px = px + drift
        out.append(Candle(symbol="X", exchange="binance_usdm",
                          open_ms=start + i * 300_000, open=o, high=max(o, px) + 1,
                          low=min(o, px) - 1, close=px, quote_volume=1_000.0 + i,
                          closed=closed))
    return out


def inst(**kw):
    base = dict(venue="binance", market="binance_usdm", symbol="BTCUSDT",
                settlement="USDT", kind="linear", product="perpetual",
                face=D("1"), lot_step=D("0.001"), min_qty=D("0.001"), max_qty=None,
                tick_size=D("0.1"), min_notional=D("50"), liq_fee_rate=D("0.0125"),
                maintenance_rate=D("0.05"), max_leverage=None, funding_interval_h=None,
                expires_ms=None, raw_status="TRADING", executable=True,
                reject_reason="")
    base.update(kw)
    return Instrument(**base)


# ---------------------------------------------------------------- contracts
def test_binance_metadata_only_eligible_contracts_are_executable():
    items = parse_binance(binance_usdm_payload(), "binance_usdm")
    by = {i.symbol: i for i in items}
    assert by["BTCUSDT"].executable is True
    assert by["BTCUSDT"].lot_step == D("0.001")
    assert by["BTCUSDT"].tick_size == D("0.10")
    # tokenize hisse PAPER dışı
    assert by["AAPLUSDT"].executable is False
    assert "TRADIFI" in by["AAPLUSDT"].reject_reason
    # durumu TRADING olmayan sözleşme alınmaz
    assert by["OLDUSDT"].executable is False
    # USDC marjlı sözleşme PAPER dışı (1:1 varsayımı yok)
    assert by["BTCUSDC"].executable is False


def test_coinm_parsing_uses_contract_size_and_status_field():
    payload = {"symbols": [{"symbol": "BTCUSD_PERP", "contractType": "PERPETUAL",
                            "marginAsset": "BTC", "contractSize": 100,
                            "contractStatus": "TRADING",
                            "filters": [{"filterType": "LOT_SIZE", "stepSize": "1",
                                         "minQty": "1"},
                                        {"filterType": "PRICE_FILTER", "tickSize": "0.1"}]}]}
    (i,) = parse_binance(payload, "binance_coinm")
    assert i.kind == "inverse"
    assert i.face == D("100")
    assert i.executable is False           # ters sözleşme henüz bağlı değil
    assert "inverse" in i.reject_reason


def test_okx_metadata_xperp_and_dated_are_rejected():
    items = parse_okx(okx_swap_payload(), "okx_swap")
    by = {i.symbol: i for i in items}
    assert by["BTC-USDT-SWAP"].executable is True
    assert by["BTC-USDT-SWAP"].face == D("0.01")
    assert by["BTC-USD-SWAP"].executable is False
    assert by["AAPL-USDT-XPERP"].executable is False
    assert "X-PERP" in by["AAPL-USDT-XPERP"].reject_reason
    assert by["BTC-USDT-251226"].executable is False
    assert "vadeli" in by["BTC-USDT-251226"].reject_reason


def test_gate_contract_parsing_matches_real_fields():
    g = {"name": "BTC_USDT", "status": "trading", "quanto_multiplier": "0.0001",
         "order_size_min": 1, "order_size_max": 12000000,
         "order_price_round": "0.1", "maintenance_rate": "0.003",
         "leverage_max": "200", "funding_interval": 28800}
    i = parse_gateio(g, "gateio_usdt")
    assert i.executable and i.face == D("0.0001")
    assert i.funding_interval_h == D("8")


def test_coverage_summary_counts_and_percentages():
    items = (parse_binance(binance_usdm_payload(), "binance_usdm")
             + parse_okx(okx_swap_payload(), "okx_swap"))
    s = summarize(items)
    assert s["_totals"]["total"] == 8
    assert s["_totals"]["executable"] == 2
    assert 0 < s["_totals"]["coverage_pct"] < 100
    assert s["binance_usdm"]["reasons"]


def test_spec_rejects_non_executable_instrument():
    i = inst(executable=False, reject_reason="test")
    with pytest.raises(ValueError):
        i.spec()


# ---------------------------------------------------------------- paperbook
def test_paper_sizing_respects_lot_step_and_min_notional():
    book = PaperBook(PaperConfig(equity_start=D("10000")))
    q = Quote("binance_usdm", "BTCUSDT", 76000, 76001, NOW)
    p = book.open(inst(), q, Side.LONG, 1200.0, NOW, "s1", "trend", 15.0)
    assert p is not None
    assert p.qty % D("0.001") == 0             # borsa lot adımı
    assert p.notional >= D("50")               # borsa min notional
    assert p.stop < p.entry < p.target
    assert p.liq_price_estimate < p.stop       # likidasyon stop'un ötesinde


def test_paper_rejects_duplicate_signal_and_second_position_same_symbol():
    book = PaperBook()
    q = Quote("binance_usdm", "BTCUSDT", 76000, 76001, NOW)
    assert book.open(inst(), q, Side.LONG, 1200.0, NOW, "sig", "trend", 15.0)
    assert book.open(inst(), q, Side.LONG, 1200.0, NOW, "sig", "trend", 15.0) is None
    assert book.rejects["DUPLICATE_SIGNAL"] == 1
    assert book.open(inst(), q, Side.LONG, 1200.0, NOW, "other", "trend", 15.0) is None
    assert book.rejects["ALREADY_OPEN"] == 1


def test_paper_stop_loss_closes_and_records_r_multiple():
    book = PaperBook()
    q = Quote("binance_usdm", "BTCUSDT", 76000, 76001, NOW)
    p = book.open(inst(), q, Side.LONG, 1200.0, NOW, "s", "trend", 15.0)
    trade = book.evaluate_exit(p.key, Quote("binance_usdm", "BTCUSDT", 70000, 70001,
                                            NOW + 300_000), NOW + 300_000)
    assert trade is not None and trade.exit_reason == "STOP_LOSS"
    assert float(trade.net) < 0
    assert trade.r_multiple < 0
    assert book.summary()["closed_trades"] == 1


def test_paper_take_profit_closes_positive():
    book = PaperBook()
    q = Quote("binance_usdm", "BTCUSDT", 76000, 76001, NOW)
    p = book.open(inst(), q, Side.LONG, 1200.0, NOW, "s", "trend", 15.0)
    trade = book.evaluate_exit(p.key, Quote("binance_usdm", "BTCUSDT", 83000, 83001,
                                            NOW + 300_000), NOW + 300_000)
    assert trade.exit_reason == "TAKE_PROFIT"
    assert float(trade.net) > 0


def test_funding_sign_long_pays_positive_rate_short_receives():
    for side, expect_negative in ((Side.LONG, True), (Side.SHORT, False)):
        book = PaperBook()
        q = Quote("binance_usdm", "BTCUSDT", 76000, 76001, NOW)
        p = book.open(inst(), q, side, 1200.0, NOW, f"s{side.value}", "trend", 15.0)
        delta = book.apply_funding(p.key, 0.0001, 76000)
        assert (delta < 0) is expect_negative
        assert book.funding_events == 1


def test_daily_loss_breaker_stops_new_positions():
    book = PaperBook(PaperConfig(equity_start=D("1000"),
                                 daily_loss_limit_pct=1.0,
                                 max_notional_per_trade=D("400")))
    q = Quote("binance_usdm", "BTCUSDT", 76000, 76001, NOW)
    p = book.open(inst(min_notional=D("1")), q, Side.LONG, 1200.0, NOW, "a", "trend", 15.0)
    book.close(p.key, Quote("binance_usdm", "BTCUSDT", 60000, 60001, NOW + 1),
               NOW + 1, "STOP_LOSS")
    assert book.breaker is True
    q2 = Quote("binance_usdm", "ETHUSDT", 3000, 3001, NOW + 2)
    assert book.open(inst(symbol="ETHUSDT", min_notional=D("1")), q2, Side.LONG,
                     40.0, NOW + 2, "b", "trend", 15.0) is None
    assert any(k.startswith("BREAKER") for k in book.rejects)


def test_liquidation_distance_gate_rejects_high_leverage_setups():
    """lev=20 & mmr=%5 → likidasyon mesafesi %0 → giriş reddedilmeli."""
    cfg = PaperConfig(leverage_assumed=D("20"))
    book = PaperBook(cfg)
    q = Quote("binance_usdm", "BTCUSDT", 76000, 76001, NOW)
    assert book.open(inst(maintenance_rate=D("5.0")), q, Side.LONG, 1200.0, NOW,
                     "s", "trend", 15.0) is None
    assert "LIQUIDATION_TOO_CLOSE" in book.rejects
    # düşük kaldıraçta aynı sözleşme geçer ve likidasyon stop'un ötesinde kalır
    ok = PaperBook(PaperConfig(leverage_assumed=D("3")))
    p = ok.open(inst(maintenance_rate=D("0.005")), q, Side.LONG, 1200.0, NOW,
                "s2", "trend", 15.0)
    assert p is not None and p.liq_price_estimate < p.stop


def test_instrument_leverage_cap_is_applied():
    """Borsanın izin verdiği maksimum kaldıraç defter kaldıracını aşağı çeker."""
    book = PaperBook(PaperConfig(leverage_assumed=D("10")))
    q = Quote("binance_usdm", "BTCUSDT", 76000, 76001, NOW)
    p = book.open(inst(max_leverage=D("2"), maintenance_rate=D("0.005")), q,
                  Side.LONG, 1200.0, NOW, "s3", "trend", 15.0)
    assert p is not None and p.leverage == D("2")


# ---------------------------------------------------------------- flow
def test_tick_parsing_marks_aggressor_for_three_venues():
    b = parse_ticks("binance_usdm",
                    [{"p": "100", "q": "2", "T": 1, "m": False},
                     {"p": "100", "q": "1", "T": 2, "m": True}], "BTCUSDT")
    assert b[0].is_buyer_maker is False and b[0].signed_quote > 0
    assert b[1].is_buyer_maker is True and b[1].signed_quote < 0
    o = parse_ticks("okx_swap", {"code": "0", "data": [
        {"px": "100", "sz": "5", "ts": "1", "side": "buy"}]}, "X")
    assert o[0].is_buyer_maker is False           # alıcı agresif
    g = parse_ticks("gateio_usdt",
                    [{"price": "100", "size": "-3", "create_time_ms": 1793909137.002}],
                    "X")
    assert g[0].is_buyer_maker is True
    assert g[0].ts_ms == 1793909137002            # saniye → ms dönüşümü


def test_tick_units_are_converted_to_base_amounts():
    linear = parse_ticks("okx_swap", {"code": "0", "data": [
        {"px": "100", "sz": "2", "ts": "1", "side": "buy"}]}, "X", face=0.01)
    assert linear[0].qty == pytest.approx(0.02)
    inverse = parse_ticks("binance_coinm",
                          [{"p": "200", "q": "3", "T": 1, "m": False}], "X",
                          face=100, kind="inverse")
    assert inverse[0].qty == pytest.approx(3 * 100 / 200)
    assert inverse[0].quote == pytest.approx(inverse[0].qty * 200)


def test_flow_window_pressure_and_unavailable_state():
    fw = FlowWindow(window_ms=60_000)
    tick = lambda px, q, ts, buy: parse_ticks(
        "binance_usdm", [{"p": str(px), "q": str(q), "T": ts, "m": not buy}], "X")[0]
    fw.add([tick(100, 3, 1000, True), tick(100, 1, 2000, False)])
    m = fw.measure(2500)
    assert m["available"] and m["pressure"] == pytest.approx(0.5)
    assert FlowWindow().measure(1000)["available"] is False


def test_mtf_alignment_builds_15m_from_5m_bars():
    up = candles(300, drift=+2.0)
    r = mtf_alignment(up, "LONG", up[-1].open_ms + 300_000)
    assert r["available"] is True and r["aligned"] is True and r["regime"] == "UP"
    down = candles(300, drift=-2.0)
    r2 = mtf_alignment(down, "LONG", down[-1].open_ms + 300_000)
    assert r2["aligned"] is False
    assert mtf_alignment(up[:40], "LONG", NOW)["available"] is False


def test_breadth_requires_minimum_sample():
    assert breadth({}, NOW)["available"] is False
    many = {f"s{i}": candles(3, drift=1.0) for i in range(10)}
    r = breadth(many, NOW)
    assert r["available"] and r["ratio"] == pytest.approx(1.0)


def test_roundtrip_cost_includes_funding_proportionally():
    base = roundtrip_cost_bps(2.0)
    with_f = roundtrip_cost_bps(2.0, funding_rate=0.01, funding_interval_h=8.0,
                               expected_hold_hours=2.0)
    assert with_f["total"] > base["total"]
    assert with_f["funding"] == pytest.approx(0.01 * 10_000 * (2 / 8), rel=1e-6)


# ---------------------------------------------------------------- marketdata
def test_rest_candle_parsers_for_all_venues():
    b = md.parse_candles("binance_usdm", [[1, "1", "2", "0.5", "1.5", "10", 2,
                                           "300", 5, "7", "0", "0"]])
    assert b[0].quote_volume == 300 and b[0].close == 1.5
    coinm = md.parse_candles("binance_coinm", [[1, "1", "2", "0.5", "2", "10", 2,
                                               "5", 5, "7", "0", "0"]])
    assert coinm[0].quote_volume == 10.0        # 5 kontrat × 2 fiyat (etiketli tahmin)
    o = md.parse_candles("okx_swap", {"code": "0", "data": [
        ["1000", "1", "2", "0.5", "1.5", "9", "9", "777", "0"]]})
    assert o[0].quote_volume == 777 and o[0].closed is False
    g = md.parse_candles("gateio_usdt", [{"t": 100, "o": "1", "h": "2", "l": "0.5",
                                          "c": "1.5", "sum": "420"}])
    assert g[0].open_ms == 100_000 and g[0].quote_volume == 420


def test_ws_message_parsers_only_emit_on_closed():
    binance_open = {"e": "kline", "k": {"s": "BTCUSDT", "i": "5m", "t": 1, "o": "1",
                                        "h": "2", "l": "1", "c": "1.5", "v": "3",
                                        "q": "30", "x": False}}
    sym, c = md.parse_ws_message("binance_usdm", binance_open)
    assert sym == "BTCUSDT" and c.closed is False and c.quote_volume == 30
    binance_open["k"]["x"] = True
    assert md.parse_ws_message("binance_usdm", binance_open)[1].closed is True
    okx = {"arg": {"channel": "candle5m", "instId": "BTC-USDT-SWAP"},
           "data": [["1", "1", "2", "1", "1.5", "9", "9", "777", "1"]]}
    assert md.parse_ws_message("okx_swap", okx)[1].closed is True
    gate = {"channel": "futures.candlesticks", "event": "update",
            "payload": ["5m", "BTC_USDT"],
            "result": [{"t": 100, "o": "1", "h": "2", "l": "1", "c": "1.5",
                        "a": "500", "w": True, "n": "5m_BTC_USDT"}]}
    sym, c = md.parse_ws_message("gateio_usdt", gate)
    assert sym == "BTC_USDT" and c.closed is True and c.quote_volume == 500


def test_ticker_and_funding_parsers():
    q = md.parse_tickers("binance_usdm",
                         [{"symbol": "BTCUSDT", "bidPrice": "1", "askPrice": "2",
                           "time": 5}])
    assert q["BTCUSDT"] == (1.0, 2.0, 5)
    q2 = md.parse_tickers("okx_swap", {"code": "0", "data": [
        {"instId": "A", "bidPx": "1", "askPx": "2", "ts": "7"}]})
    assert q2["A"] == (1.0, 2.0, 7)
    f = md.parse_funding("binance_usdm", {"nextFundingTime": 1000,
                                          "lastFundingRate": "0.0001"})
    assert f["next_ms"] == 1000 and f["interval_h"] == 8.0
    assert md.parse_funding("okx_swap", {"code": "0", "data": [
        {"fundingRate": "0.0002", "fundingTime": "2000"}]})["rate"] == 0.0002


# ---------------------------------------------------------------- strategy
def test_open_bar_is_never_decided_and_gap_is_rejected():
    bars = candles(260)
    open_bar = Candle("X", "binance_usdm", bars[-1].open_ms + 300_000, 1, 2, 0.5, 1.5,
                      10, closed=False)
    now = open_bar.open_ms + 1000
    assert closed_candles(bars + [open_bar], now)[-1].open_ms == bars[-1].open_ms
    gapped = bars[:100] + candles(160, start=bars[100].open_ms + 600_000)
    r = decide(gapped, gapped[-1].open_ms + 300_000 + 1000, "trend")
    assert r.reason == "CANDLE_GAP"


def test_stale_candle_cannot_signal():
    bars = candles(260, drift=1.0)
    now = bars[-1].open_ms + 300_000 + 200_000     # 200 sn > 90 sn
    assert decide(bars, now, "trend").reason == "STALE_CANDLE"


# ---------------------------------------------------------------- council
def _sig(side=Side.SHORT):
    return Signal(exchange="binance_usdm", symbol="BTCUSDT", side=side, price=100.0,
                  ts_ms=NOW, ret_pct=-0.5, rvol=1.4, volume_usd=1e6, window_ms=300_000,
                  signal_id="s1")


def test_council_quant_only_matches_async_evaluate():
    metrics = {"entry_side": "SHORT", "spread_bps": 1.0, "roundtrip_cost_bps": 15.0,
               "expected_move_bps": 40.0, "mtf_aligned": True, "breadth_ratio": 0.3,
               "flow_score": -0.4, "choppiness": 45.0, "minutes_to_funding": 120.0}
    c1, c2 = AICouncil(), AICouncil()
    ctx = c1.build_context(_sig(), metrics)
    sync_verdict = c1.quant_only(ctx)
    async_verdict = asyncio.run(c2.evaluate(_sig(), metrics))
    assert sync_verdict.mode == async_verdict.mode == "RULE_BASED_QUANT"
    assert sync_verdict.approved == async_verdict.approved
    assert sync_verdict.score == pytest.approx(async_verdict.score)
    assert sync_verdict.ai_generated is False


def test_council_hard_gate_blocks_costlier_than_edge_setup():
    c = AICouncil()
    metrics = {"entry_side": "LONG", "spread_bps": 1.0, "roundtrip_cost_bps": 40.0,
               "expected_move_bps": 5.0}
    v = c.quant_only(c.build_context(_sig(Side.LONG), metrics))
    assert v.approved is False
    assert v.reject_code == "COUNCIL_EDGE_BELOW_COST"
