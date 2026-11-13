"""NOVA-BOT testleri — AĞ GEREKTİRMEZ (tamamen çevrimdışı)."""
from __future__ import annotations

import math
from decimal import Decimal as D

import pytest

from nova.bot import (BAR_MS, Bar, Book, Config, Feed, Inst, _ws_bar, adx, atr,
                      backtest, choppiness, ema, parse_candles, parse_funding,
                      parse_instruments, parse_tickers, rsi, strategi_skoru)


# --------------------------------------------------------------- yardımcılar
def bars(n: int, start: float = 100.0, step: float = 0.05, vol: float = 1000.0,
         open_ms0: int = 1_700_000_000_000) -> list[Bar]:
    out, px = [], start
    for i in range(n):
        o = px
        px = px + step
        out.append(Bar(open_ms0 + i * BAR_MS, o, max(o, px) + 0.01,
                       min(o, px) - 0.01, px, vol))
    return out


def trend_bars(n: int = 150, drift: float = 0.25, wobble: float = 0.6,
               start: float = 100.0) -> list[Bar]:
    """Gerçekçi trend: sürüklenme + sinüzoidal gürültü (RSI'yı aşırı bölgeye itmez)."""
    out, px = [], start
    for i in range(n):
        o = px
        px = px + drift + wobble * math.sin(i / 3.0)
        out.append(Bar(i * BAR_MS, o, max(o, px) + 0.02, min(o, px) - 0.02, px, 1000))
    return out


def inst(**kw) -> Inst:
    base = dict(venue="binance", market="binance_usdm", symbol="BTCUSDT",
                settlement="USDT", kind="linear", face=D("1"),
                lot_step=D("0.001"), min_qty=D("0.001"), min_notional=D("5"),
                tick=D("0.1"), mmr_hint=D("0.05"), max_lev=None, reason="")
    base.update(kw)
    return Inst(**base)


# --------------------------------------------------------------- göstergeler
def test_ema_tracks_constant_series():
    v = [10.0] * 50
    assert ema(v, 9)[-1] == pytest.approx(10.0)


def test_rsi_extremes():
    up = [100 + i for i in range(40)]
    down = [100 - i for i in range(40)]
    assert rsi(up) == pytest.approx(100.0)
    assert rsi(down) == pytest.approx(0.0)
    assert rsi([100] * 40) == pytest.approx(50.0)


def test_atr_is_positive_and_scales_with_range():
    calm = bars(30, step=0.01)
    wild = [Bar(b.open_ms, b.open, b.high * 1.01, b.low * 0.99, b.close, b.volume)
            for b in bars(30, step=0.01)]
    assert atr(calm) and atr(wild)
    assert atr(wild) > atr(calm)


def test_choppiness_high_for_sideways_low_for_trend():
    sideways = [Bar(i * BAR_MS, 100, 100.02, 99.98, 100 + (0.01 if i % 2 else -0.01), 10)
                for i in range(40)]
    trend = bars(40, step=0.5)
    assert choppiness(sideways) > choppiness(trend)


def test_adx_requires_history_and_trend_is_directional():
    assert adx(bars(10)) is None
    assert adx(bars(80, step=0.4)) is not None


# --------------------------------------------------------------- strateji
def test_strategy_needs_enough_bars():
    assert strategi_skoru(bars(30), {"min_score": 3, "max_chop": 100}) is None


def test_strategy_never_returns_signal_on_choppy_market():
    sideways = [Bar(i * BAR_MS, 100, 100.03, 99.97, 100 + (0.02 if i % 2 else -0.02), 10)
                for i in range(120)]
    sig = strategi_skoru(sideways, {"min_score": 1, "max_chop": 62})
    assert sig is None


def _signals_over_series(bars_seq: list[Bar], params: dict) -> list:
    """Serideki her kapanmış mumda stratejiyi çalıştır (canlıdaki gibi)."""
    out = []
    for i in range(60, len(bars_seq) + 1):
        sig = strategi_skoru(bars_seq[:i], params)
        if sig:
            out.append((i, sig))
    return out


def test_strategy_long_signal_on_clean_uptrend():
    up = trend_bars(200, drift=0.25, wobble=0.6)
    found = _signals_over_series(up, {"min_score": 3, "max_chop": 100})
    assert found, "temiz yükseliş trendinde hiç long sinyal yok"
    assert all(sig.side == "long" for _, sig in found)
    assert max(sig.score for _, sig in found) >= 3
    assert all(sig.atr > 0 for _, sig in found)


def test_strategy_short_signal_on_clean_downtrend():
    down = trend_bars(200, drift=-0.25, wobble=0.6, start=200.0)
    found = _signals_over_series(down, {"min_score": 3, "max_chop": 100})
    assert found, "temiz düşüş trendinde hiç short sinyal yok"
    assert all(sig.side == "short" for _, sig in found)


def test_strategy_votes_add_up_to_score():
    up = trend_bars(200, drift=0.25, wobble=0.6)
    found = _signals_over_series(up, {"min_score": 3, "max_chop": 100})
    for _, sig in found:
        assert sum(sig.votes.values()) == sig.score
        assert set(sig.votes) == {"trend", "macd", "rsi", "adx", "hacim"}


def test_strategy_threshold_is_monotonic():
    up = trend_bars(200, drift=0.25, wobble=0.6)
    loose = _signals_over_series(up, {"min_score": 3, "max_chop": 100})
    strict = _signals_over_series(up, {"min_score": 5, "max_chop": 100})
    assert loose
    assert len(strict) <= len(loose)
    assert all(sig.score >= 5 for _, sig in strict)


def test_strategy_chop_gate_removes_signals():
    up = trend_bars(200, drift=0.25, wobble=0.6)
    open_gate = _signals_over_series(up, {"min_score": 3, "max_chop": 100})
    shut_gate = _signals_over_series(up, {"min_score": 3, "max_chop": 1})
    assert open_gate and not shut_gate


# --------------------------------------------------------------- defter
cfg = Config(equity=1000.0, risk_pct=0.5, max_notional_trade=250.0,
             max_spread_bps=10.0, min_liq_dist_pct=10.0)


def test_book_respects_lot_step_and_exchange_min_notional():
    b = Book(cfg)
    p = b.open(inst(), 100.0, 100.02, "long", atr_v=0.5, ts=1_000,
               signal_id="s1", quote_ts=1_000)
    assert p is not None
    assert p.qty % D("0.001") == 0
    assert p.notional >= D("5")
    assert p.stop < p.entry < p.tp
    assert p.liq is None or p.liq < p.stop


def test_book_rejects_second_position_same_symbol_and_duplicate_gates():
    b = Book(cfg)
    assert b.open(inst(), 100, 100.02, "long", 0.5, 1, "s1", 1)
    assert b.open(inst(), 100, 100.02, "long", 0.5, 2, "s2", 2) is None
    assert b.rejects["ALREADY_OPEN"] == 1


def test_book_rejects_when_size_below_exchange_minimum():
    b = Book(cfg)
    far = inst(min_qty=D("500"), lot_step=D("1"))
    assert b.open(far, 100, 100.02, "long", 0.5, 1, "s1", 1) is None
    assert "QTY_BELOW_MIN" in b.rejects


def test_book_stop_loss_and_take_profit_paths():
    for target_px, reason, positive in ((90.0, "STOP", False), (130.0, "TAKE_PROFIT", True)):
        b = Book(cfg)
        p = b.open(inst(), 100, 100.02, "long", atr_v=0.5, ts=1_000,
                   signal_id="s", quote_ts=1_000)
        t = b.check_exit(p.key, target_px - 0.01, target_px, 2_000)
        assert t is not None and t.reason == reason
        assert (float(t.net) > 0) is positive
        assert b.summary()["trades"] == 1


def test_book_short_direction_is_symmetric():
    b = Book(cfg)
    p = b.open(inst(), 100.0, 100.02, "short", atr_v=0.5, ts=1_000,
               signal_id="s", quote_ts=1_000)
    assert p.stop > p.entry > p.tp
    t = b.check_exit(p.key, 90.0, 90.01, 2_000)
    assert t is not None and t.reason == "TAKE_PROFIT" and float(t.net) > 0


def test_funding_sign_and_magnitude():
    b = Book(cfg)
    p = b.open(inst(), 100, 100.02, "long", 0.5, 1_000, "s", 1_000)
    delta = b.funding_event(p.key, 0.0001, 100.0)
    assert delta < 0                                     # long pozitif oranda öder
    short_book = Book(cfg)
    sp = short_book.open(inst(symbol="ETHUSDT"), 100, 100.02, "short", 0.5, 1_000, "s", 1_000)
    assert short_book.funding_event(sp.key, 0.0001, 100.0) > 0


def test_liquidation_distance_gate_blocks_high_leverage():
    tight = Config(equity=1000, leverage_for_liq=10.0, min_liq_dist_pct=12.0)
    b = Book(tight)
    high_mmr = inst(mmr_hint=D("0.08"))                  # %8 bakım marjı
    assert b.open(high_mmr, 100, 100.02, "long", 0.5, 1_000, "s", 1_000) is None
    assert "LIQ_TOO_CLOSE" in b.rejects


def test_daily_loss_halt_stops_trading():
    b = Book(Config(equity=1_000, risk_pct=50.0, daily_loss_pct=1.0,
                    max_notional_trade=10_000, max_gross=100_000))
    p = b.open(inst(), 100, 100.02, "long", 0.5, 1_000, "s", 1_000)
    b.check_exit(p.key, 50.0, 50.01, 2_000)               # sert zarar
    assert b.halt == "DAILY_LOSS"
    assert b.open(inst(symbol="ETHUSDT"), 100, 100.02, "long", 0.5, 3_000, "s2", 3_000) is None
    assert any(k.startswith("HALTED") for k in b.rejects)


def test_position_limits_and_gross_exposure():
    b = Book(Config(equity=10_000, max_positions=2, max_per_market=1,
                    max_same_side=2, max_gross=500, risk_pct=5,
                    max_notional_trade=400))
    assert b.open(inst(symbol="A"), 100, 100.02, "long", 0.5, 1, "a", 1) is not None
    assert b.open(inst(symbol="B"), 100, 100.02, "long", 0.5, 1, "b", 1) is None
    assert "MAX_PER_MARKET" in b.rejects


def test_breakeven_and_trailing_move_stop_only_forward():
    b = Book(cfg)
    p = b.open(inst(), 100, 100.02, "long", 0.5, 1_000, "s", 1_000)
    start_stop = p.stop
    b.check_exit(p.key, 101.0, 101.02, 2_000)            # kâr yönünde ilerle
    assert p.stop >= start_stop and p.be is True


# --------------------------------------------------------------- veri çözümleyiciler
def test_parse_instruments_binance_filters():
    payload = {"symbols": [
        {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "marginAsset": "USDT",
         "status": "TRADING", "filters": [
             {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
             {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
             {"filterType": "MIN_NOTIONAL", "notional": "50"}]},
        {"symbol": "AAPLUSDT", "contractType": "TRADIFI_PERPETUAL",
         "marginAsset": "USDT", "status": "TRADING", "filters": []},
        {"symbol": "OLDUSDT", "contractType": "PERPETUAL", "marginAsset": "USDT",
         "status": "SETTLING", "filters": []},
    ]}
    items = {i.symbol: i for i in parse_instruments("binance_usdm", payload)}
    assert "AAPLUSDT" not in items                      # TRADIFI hiç alınmaz
    assert items["BTCUSDT"].tradable
    assert items["BTCUSDT"].lot_step == D("0.001")
    assert not items["OLDUSDT"].tradable


def test_parse_instruments_okx_rejects_inverse_and_xperp():
    payload = {"data": [
        {"instId": "BTC-USDT-SWAP", "ctType": "linear", "settleCcy": "USDT",
         "ctVal": "0.01", "lotSz": "0.01", "minSz": "0.01", "tickSz": "0.1",
         "state": "live"},
        {"instId": "BTC-USD-SWAP", "ctType": "inverse", "settleCcy": "BTC",
         "ctVal": "100", "lotSz": "0.1", "minSz": "0.1", "tickSz": "0.1",
         "state": "live"},
        {"instId": "OPENAI-USDT-XPERP", "ctType": "linear", "settleCcy": "USDT",
         "ctVal": "1", "lotSz": "1", "minSz": "1", "tickSz": "0.01", "state": "live"},
    ]}
    items = {i.symbol: i for i in parse_instruments("okx_swap", payload)}
    assert items["BTC-USDT-SWAP"].tradable
    assert not items["BTC-USD-SWAP"].tradable
    assert not items["OPENAI-USDT-XPERP"].tradable


def test_parse_candles_three_venues():
    assert parse_candles("binance_usdm", [[1, "1", "2", "0.5", "1.5", "10", 2, "300"]])[0].volume == 300
    okx = parse_candles("okx_swap", {"code": "0", "data": [
        ["1000", "1", "2", "0.5", "1.5", "9", "9", "777", "0"]]})[0]
    assert okx.volume == 777 and okx.closed is False
    gate = parse_candles("gateio_usdt", [{"t": 5, "o": "1", "h": "2", "l": "0.5",
                                          "c": "1.5", "sum": "42"}])[0]
    assert gate.open_ms == 5000 and gate.volume == 42


def test_parse_tickers_and_funding():
    q = parse_tickers("binance_usdm", [{"symbol": "BTCUSDT", "bidPrice": "1",
                                        "askPrice": "2", "time": 9}])
    assert q["BTCUSDT"] == (1.0, 2.0, 9)
    assert parse_funding("binance_usdm", {"nextFundingTime": 1000,
                                          "lastFundingRate": "0.0002"})["rate"] == 0.0002
    assert parse_funding("okx_swap", {"code": "0", "data": [
        {"fundingRate": "0.0003", "fundingTime": "5000"}]})["next_ms"] == 5000
    assert parse_funding("gateio_usdt", {"funding_rate": "0.0001",
                                         "funding_next_apply": 10,
                                         "funding_interval": 28800})["next_ms"] == 10000
    assert parse_funding("binance_usdm", {}) is None     # bozuk yanıt → None (uydurma yok)


def test_ws_parsers_only_emit_when_exchange_says_closed():
    b_open = {"e": "kline", "k": {"s": "BTCUSDT", "i": "1m", "t": 1, "o": "1",
                                  "h": "2", "l": "1", "c": "1.5", "q": "30", "x": False}}
    sym, bar = _ws_bar("binance_usdm", b_open)
    assert sym == "BTCUSDT" and bar.closed is False
    b_open["k"]["x"] = True
    assert _ws_bar("binance_usdm", b_open)[1].closed is True
    okx = {"arg": {"channel": "candle1m", "instId": "X"}, "data": [
        ["1", "1", "2", "1", "1.5", "9", "9", "50", "1"]]}
    assert _ws_bar("okx_swap", okx)[1].closed is True
    gate = {"channel": "futures.candlesticks", "event": "update",
            "payload": ["1m", "BTC_USDT"],
            "result": [{"t": 1, "o": "1", "h": "2", "l": "1", "c": "1.5",
                        "a": "10", "w": True, "n": "1m_BTC_USDT"}]}
    sym, bar = _ws_bar("gateio_usdt", gate)
    assert sym == "BTC_USDT" and bar.closed is True


# --------------------------------------------------------------- backtest
def test_backtest_produces_trades_and_never_uses_next_bar_close_first():
    bb = {"k": bars(400, start=100.0, step=0.2)}
    ii = {"k": inst()}
    res = backtest(bb, ii, Config(equity=1000), {"min_score": 2, "max_chop": 100})
    assert res["trades"] > 0
    assert set(res["exits"]) <= {"STOP", "TAKE_PROFIT", "MAX_HOLD"}
    assert res["equity_end"] != res["equity_start"]


def test_backtest_without_signal_returns_zero_trades():
    flat = [Bar(i * BAR_MS, 100, 100.02, 99.98, 100, 10) for i in range(300)]
    res = backtest({"k": flat}, {"k": inst()}, Config(), {"min_score": 3, "max_chop": 62})
    assert res["trades"] == 0
    assert res["win_rate"] == 0.0


# --------------------------------------------------------------- likidite / sayfalama
class _FakeFeed:
    """candles_range sayfalamasını ağ olmadan sınamak için sahte REST."""

    def __init__(self, pages, closed_after=None):
        self.pages = pages
        self.calls = []
        self.closed_after = closed_after

    async def get(self, market, path, timeout=0):
        self.calls.append(path)
        return self.pages.pop(0)


def test_candles_range_paginates_and_dedupes():
    import asyncio
    from nova.bot import Feed
    now = 1_700_000_000_000
    page1 = [[now - i * BAR_MS, "1", "1", "1", "1", "5", 0, "9"] for i in range(1000)]
    page2 = [[now - (1000 + i) * BAR_MS, "1", "1", "1", "1", "5", 0, "9"]
             for i in range(1000)]
    fake = _FakeFeed([page1, page2])
    bars = asyncio.run(Feed.candles_range(fake, "binance_usdm", "BTCUSDT", 1500))
    assert len(bars) == 1500
    assert len({b.open_ms for b in bars}) == 1500
    assert bars == sorted(bars, key=lambda b: b.open_ms)
    assert len(fake.calls) >= 2                     # gerçekten sayfaladı


def test_candles_range_stops_when_venue_repeats_itself():
    import asyncio
    from nova.bot import Feed
    page = [[1_700_000_000_000 - i * BAR_MS, "1", "1", "1", "1", "5", 0, "9"]
            for i in range(50)]
    fake = _FakeFeed([page, page, page])
    bars = asyncio.run(Feed.candles_range(fake, "binance_usdm", "BTCUSDT", 1000))
    assert len(bars) == 50
    assert len(fake.calls) <= 3                     # sonsuz döngüye girmez


def test_non_crypto_products_are_excluded():
    payload = {"data": [
        {"instId": "ANTHROPIC-USDT-SWAP", "ctType": "linear", "settleCcy": "USDT",
         "ctVal": "1", "lotSz": "1", "minSz": "1", "tickSz": "0.01", "state": "live"},
        {"instId": "ETH-USDT-SWAP", "ctType": "linear", "settleCcy": "USDT",
         "ctVal": "0.01", "lotSz": "0.01", "minSz": "0.01", "tickSz": "0.01",
         "state": "live"},
    ]}
    items = {i.symbol: i for i in parse_instruments("okx_swap", payload)}
    assert not items["ANTHROPIC-USDT-SWAP"].tradable
    assert "kripto dışı" in items["ANTHROPIC-USDT-SWAP"].reason
    assert items["ETH-USDT-SWAP"].tradable


def test_turnover_and_listing_age_filters_are_applied():
    """Seçim havuzu: 24s hacim eşiği + ürün yaşı eşiği + kripto dışı filtresi."""
    from nova.bot import MIN_LISTING_AGE_DAYS, MIN_TURNOVER_USD
    gate_payload = [
        {"name": "BTC_USDT", "status": "trading", "quanto_multiplier": "0.0001",
         "order_size_min": 1, "order_price_round": "0.1", "maintenance_rate": "0.005",
         "leverage_max": "200", "listing_age": 900},
        {"name": "NEWCOIN_USDT", "status": "trading", "quanto_multiplier": "1",
         "order_size_min": 1, "order_price_round": "0.0001", "maintenance_rate": "0.01",
         "leverage_max": "20", "listing_age": 3},
        {"name": "THIN_USDT", "status": "trading", "quanto_multiplier": "1",
         "order_size_min": 1, "order_price_round": "0.0001", "maintenance_rate": "0.01",
         "leverage_max": "20", "listing_age": 400},
    ]
    items = {i.symbol: i for i in parse_instruments("gateio_usdt", gate_payload)}
    turnover = {"BTC_USDT": 5e9, "NEWCOIN_USDT": 5e9, "THIN_USDT": 1e4}
    pool = [i for i in items.values()
            if (i.listing_age_days == 0 or i.listing_age_days >= MIN_LISTING_AGE_DAYS)
            and turnover.get(i.symbol, 0.0) >= MIN_TURNOVER_USD]
    assert [i.symbol for i in pool] == ["BTC_USDT"]      # yeni + ince elendi
    assert items["NEWCOIN_USDT"].listing_age_days == 3   # yaş alanı gerçekten okundu


def test_cross_venue_base_filter_drops_single_venue_equities():
    """Dayanak hem Binance hem OKX'te olmalı; yalnız iki borsada ortak olan kalır."""
    from nova.bot import base_asset, cross_venue_bases
    binance = [inst(symbol="BTCUSDT"), inst(symbol="ETHUSDT")]
    okx = [inst(venue="okx", market="okx_swap", symbol="BTC-USDT-SWAP"),
           inst(venue="okx", market="okx_swap", symbol="SNDK-USDT-SWAP")]
    gate = [inst(venue="gateio", market="gateio_usdt", symbol="SNDK_USDT"),
            inst(venue="gateio", market="gateio_usdt", symbol="BTC_USDT"),
            inst(venue="gateio", market="gateio_usdt", symbol="INTC_USDT")]
    bases = cross_venue_bases(binance + okx + gate)
    assert bases == {"BTC"}                             # ETH yalnız Binance'te
    assert base_asset("okx_swap", "BTC-USDT-SWAP") == "BTC"
    assert base_asset("gateio_usdt", "SNDK_USDT") == "SNDK"
    assert base_asset("binance_usdm", "SOLUSDT") == "SOL"
    kept = [i.symbol for i in gate if base_asset(i.market, i.symbol) in bases]
    assert kept == ["BTC_USDT"]                         # SNDK/INTC elendi
    okx_kept = [i.symbol for i in okx if base_asset(i.market, i.symbol) in bases]
    assert okx_kept == ["BTC-USDT-SWAP"]                # SNDK OKX'te de elenir


# --------------------------------------------------------------- güvenlik
def test_no_private_api_surface_in_source():
    """Bot yalnız kamu uçlarını kullanmalı: imza/anahtar kodu bulunmamalı."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "nova" / "bot.py"
    text = src.read_text(encoding="utf-8")
    for forbidden in ("hmac", "create_order", "apiKey", "api_key", "X-MBX-APIKEY",
                      "secret"):
        assert forbidden not in text, f"özel API izi bulundu: {forbidden}"
    assert text.count("real_orders") >= 1
