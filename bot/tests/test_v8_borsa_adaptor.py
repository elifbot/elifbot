# -*- coding: utf-8 -*-
"""Adaptör testleri — ağa çıkmadan imza, parametre ve normalizasyon doğrular.

Canlıya çıkmadan önce yanlış imza = 401, yanlış ctVal = 10 kat yanlış pozisyon.
Bu testler ikisini de kilitler.
"""
from __future__ import annotations

import hashlib
import hmac

from bot.v8.exchanges import binance, okx
from bot.v8.types import EmirIstegi, EmirTipi, Yon


# ------------------------------------------------------------------ binance
def test_binance_imza_hmac():
    beklenen = hmac.new(b"secret", b"symbol=BTCUSDT&timestamp=1",
                        hashlib.sha256).hexdigest()
    assert binance.imzala("secret", "symbol=BTCUSDT&timestamp=1") == beklenen


def test_binance_sorgu_timestamp_ve_imza():
    q = binance.sorgu_olustur({"symbol": "BTCUSDT"}, "s", ts_ms=1700000000000)
    assert "timestamp=1700000000000" in q
    assert q.endswith(binance.imzala("s", q.split("&signature=")[0]))


def test_binance_stop_market_reduce_only():
    p = binance.emir_tipi(EmirIstegi("binance", "BTCUSDT", Yon.LONG, EmirTipi.STOP_MARKET,
                                     0.01, fiyat=60000.0, reduce_only=True, istemci_id="sl-1"))
    assert p["type"] == "STOP_MARKET"
    assert p["reduceOnly"] == "true"
    assert p["stopPrice"] == 60000.0
    assert p["workingType"] == "MARK_PRICE"
    assert p["side"] == "BUY"


def test_binance_filtre_coz():
    sembol = {
        "symbol": "BTCUSDT", "baseAsset": "BTC", "status": "TRADING",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
        ],
    }
    e = binance.filtre_coz(sembol)
    assert e.fiyat_adimi == 0.10 and e.miktar_adimi == 0.001
    assert e.kontrat_carpani == 1.0 and e.durum == "live"


def test_binance_tick_normalize():
    adaptor = binance.BinanceAdaptoru("k", "s", None)
    mesaj = {"data": {"e": "aggTrade", "s": "BTCUSDT", "p": "60000", "q": "0.01",
                      "m": False, "T": 1700000000000}}
    d = adaptor.tick_normalize(mesaj)
    assert len(d) == 1
    assert d[0]["baz"] == "BTC" and d[0]["fiyat"] == 60000.0
    assert d[0]["delta_usd"] == 600.0
    assert d[0]["alis_usd"] == 600.0     # m=False -> agresif alıcı


def test_binance_ws_abonelik():
    a = binance.BinanceAdaptoru("k", "s", None)
    ab = a.ws_abonelik(["BTCUSDT", "ETHUSDT"])
    assert "btcusdt@aggTrade" in ab[0]["url"]


# ---------------------------------------------------------------------- okx
def test_okx_imza_deterministik():
    imza = okx.imzala("secret", "2020-12-08T09:08:57.715Z", "POST", "/api/v5/trade/order",
                      '{"instId":"BTC-USDT-SWAP"}')
    assert isinstance(imza, str) and len(imza) > 20
    assert imza == okx.imzala("secret", "2020-12-08T09:08:57.715Z", "POST",
                              "/api/v5/trade/order", '{"instId":"BTC-USDT-SWAP"}')


def test_okx_zaman_damgasi_bicimi():
    z = okx.zaman_damgasi(1607332137715)
    assert z.endswith("Z") and "T" in z and z.endswith(".715Z")


def test_okx_zaman_damgasi_ms():
    z = okx.zaman_damgasi(1607332137715)
    assert len(z) == 24 and z[10] == "T" and z.endswith(".715Z")


def test_okx_emir_cross_majin():
    g = okx.emir_govdesi(EmirIstegi("okx", "BTC-USDT-SWAP", Yon.SHORT, EmirTipi.MARKET,
                                    1.0, istemci_id="a1"))
    assert g["tdMode"] == "cross"          # izole DEĞİL
    assert g["side"] == "sell"
    assert g["ordType"] == "market"


def test_okx_conditional_stop():
    g = okx.emir_govdesi(EmirIstegi("okx", "BTC-USDT-SWAP", Yon.LONG, EmirTipi.STOP_MARKET,
                                    1.0, fiyat=59000.0, reduce_only=True, istemci_id="sl"))
    assert g["ordType"] == "conditional"
    assert g["slTriggerPx"] == "59000.0"
    assert g["slOrdPx"] == "-1"            # tetiklenince market
    assert g["reduceOnly"] == "true"


def test_okx_kontrat_carpani():
    i = {"instId": "BTC-USDT-SWAP", "uly": "BTC-USDT", "tickSz": "0.1", "lotSz": "0.01",
         "minSz": "0.01", "ctVal": "0.01", "ctMult": "1", "lever": "100", "state": "live"}
    e = okx.enstruman_coz(i)
    assert e.kontrat_carpani == 0.01
    assert e.baz == "BTC"
    assert e.durum == "live"


def test_okx_tick_normalize():
    a = okx.OkxAdaptoru("k", "s", "p", None)
    mesaj = {"arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
             "data": [{"px": "60000", "sz": "0.01", "side": "buy", "ts": "1700000000000"}]}
    d = a.tick_normalize(mesaj)
    assert d[0]["sembol"] == "BTC-USDT-SWAP" and d[0]["baz"] == "BTC"
    assert d[0]["delta_usd"] == 600.0
