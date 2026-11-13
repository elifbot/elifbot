"""ACARBOT v3.0 — dış inceleme bulgularına karşı regresyon testleri.

Kapsam:
  1. urllib transport HTTP hata gövdesini KAYBETMEZ (Binance -4046 testi)
  2. OKX sCode≠0 → HATA (sessiz başarı kaldırıldı)
  3. OKX çıkış yönü: LONG → sell (acil durum flatten dahil)
  4. OKX sunucu tarafı stop: order-algo conditional + closeFraction
  5. OKX cancel: geçerli uçlar (cancel-batch-orders / cancel-algos)
  6. OKX baz→kontrat dönüşümü (ctVal/lotSz/minSz)
  7. Stop kurulamazsa pozisyon korumasız KALMAZ (3 deneme → flatten)
  8. Stop güncelleme: eski stop iptal + yeni stop; başarısızlıkta geri al
  9. Mirror durum kalıcılığı (restart güvenli)
 10. Backtest: slippage/latency modeli
 11. Flash crash: tek stop, panik yok
 12. Kısmi dolum → pozisyon tutarlılığı (dolan kısım pozisyona dönüşür)
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from live.broker_clients import (
    BinanceFuturesTestnet,
    OkxDemoTrading,
)
from live.clients import LiveClientError, OkxSignedClient, SignedHttpClient
from live.sync import (
    EmergencyController,
    LiveMirror,
    RestartRecovery,
)

# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


class RecordingTransport:
    """URL gövdesine göre canned yanıt döner; istekleri kaydeder."""

    def __init__(self, routes: dict[str, object] | None = None) -> None:
        self.routes = routes or {}
        self.requests: list[dict] = []

    def __call__(self, url, method, headers, body):
        self.requests.append({
            "url": url, "method": method,
            "headers": headers, "body": body,
        })
        path = url.split("?")[0]
        for suffix, value in self.routes.items():
            if path.endswith(suffix):
                return 200, json.dumps(value).encode()
        return 404, json.dumps({"error": "not found"}).encode()


def _okx_client(transport: RecordingTransport) -> OkxSignedClient:
    import os
    os.environ["OKX_DEMO_API_KEY"] = "k"
    os.environ["OKX_DEMO_API_SECRET"] = "s"
    os.environ["OKX_API_PASSPHRASE"] = "p"
    return OkxSignedClient(
        "https://www.okx.com", "OKX_DEMO_API_KEY", "OKX_DEMO_API_SECRET",
        transport,
    )


def _binance_client(transport: RecordingTransport) -> SignedHttpClient:
    import os
    os.environ["BINANCE_TESTNET_API_KEY"] = "k"
    os.environ["BINANCE_TESTNET_API_SECRET"] = "s"
    return SignedHttpClient(
        "https://testnet.binancefuture.com",
        "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET",
        transport,
    )


def _last(transport, fragment):
    for request in reversed(transport.requests):
        if request["url"].split("?")[0].endswith(fragment):
            return request
    raise AssertionError(f"istek bulunamadı: {fragment}")


_OKX_INSTRUMENT = {"data": [{
    "instId": "BTC-USDT-SWAP", "ctVal": "0.01", "lotSz": "1",
    "minSz": "1", "tickSz": "0.1", "state": "live",
}]}


class TestTransportErrorBody:
    def test_http_error_body_preserved(self):
        """v3.0: HTTP 400 gövdesi mesajda — borsa hata kodları kaybolmaz."""
        served = {"done": False}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.dumps({"code": -4046, "msg": "No need to change margin type."})
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body.encode())
                served["done"] = True

            def log_message(self, *args):  # sessiz
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            from live.clients import urllib_transport
            with pytest.raises(LiveClientError) as exc_info:
                urllib_transport(
                    f"http://127.0.0.1:{server.server_port}/fapi/v1/marginType",
                    "POST", {}, b"",
                )
            assert "-4046" in str(exc_info.value)
            assert "No need to change margin type" in str(exc_info.value)
        finally:
            server.shutdown()
            server.server_close()

    def test_set_margin_type_tolerates_4046(self, monkeypatch):
        """v3.0: -4046 (zaten bu modda) gerçek ağda da sessiz geçilir."""
        monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "k")
        monkeypatch.setenv("BINANCE_TESTNET_API_SECRET", "s")
        # Sahte transport HTTP 400 + gövde döner (gerçek davranışı taklit eder)
        def transport(url, method, headers, body):
            return 400, json.dumps({
                "code": -4046, "msg": "No need to change margin type.",
            }).encode()

        broker = BinanceFuturesTestnet(
            SignedHttpClient("https://x", "BINANCE_TESTNET_API_KEY",
                             "BINANCE_TESTNET_API_SECRET", transport),
        )
        broker.set_margin_type("BTCUSDT", "isolated")  # yükseltmemeli

    def test_other_margin_errors_raise(self, monkeypatch):
        monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "k")
        monkeypatch.setenv("BINANCE_TESTNET_API_SECRET", "s")

        def transport(url, method, headers, body):
            return 400, json.dumps({"code": -1000, "msg": "bad"}).encode()

        broker = BinanceFuturesTestnet(
            SignedHttpClient("https://x", "BINANCE_TESTNET_API_KEY",
                             "BINANCE_TESTNET_API_SECRET", transport),
        )
        with pytest.raises(LiveClientError):
            broker.set_margin_type("BTCUSDT", "isolated")


OKX_ROUTES = {
    "/api/v5/public/instruments": _OKX_INSTRUMENT,
    "/api/v5/trade/order": {"data": [{
        "ordId": "1", "clOrdId": "x", "instId": "BTC-USDT-SWAP", "sCode": "0",
    }]},
    "/api/v5/trade/order-algo": {"data": [{
        "algoId": "9", "clOrdId": "y", "instId": "BTC-USDT-SWAP", "sCode": "0",
    }]},
    "/api/v5/trade/orders-pending": {"data": []},
    "/api/v5/trade/orders-algo-pending": {"data": []},
    "/api/v5/account/positions": {"data": [
        {"instId": "BTC-USDT-SWAP", "pos": "3", "avgPx": "50000", "upl": "-10"},
    ]},
}


class TestOkxClientFixes:
    def test_scode_error_raises(self):
        routes = dict(OKX_ROUTES)
        routes["/api/v5/trade/order"] = {"data": [{
            "sCode": "51008", "sMsg": "Insufficient margin",
        }]}
        transport = RecordingTransport(routes)
        okx = OkxDemoTrading(_okx_client(transport))
        with pytest.raises(LiveClientError) as exc_info:
            okx.place_market("BTC-USDT-SWAP", "LONG", 0.03, "cid")
        assert "51008" in str(exc_info.value)
        assert "Insufficient margin" in str(exc_info.value)

    def test_exit_flips_side(self):
        """v3.0 KRİTİK: LONG pozisyonu kapatmak için sell gönderilmeli."""
        transport = RecordingTransport(OKX_ROUTES)
        okx = OkxDemoTrading(_okx_client(transport))
        okx.place_reduce_only_exit("BTC-USDT-SWAP", "LONG", 0.03, "cid")
        body = json.loads(_last(transport, "/api/v5/trade/order")["body"])
        assert body["side"] == "sell"
        assert body["reduceOnly"] == "true"

    def test_exit_short_flips_to_buy(self):
        transport = RecordingTransport(OKX_ROUTES)
        okx = OkxDemoTrading(_okx_client(transport))
        okx.place_reduce_only_exit("BTC-USDT-SWAP", "SHORT", 0.03, "cid")
        body = json.loads(_last(transport, "/api/v5/trade/order")["body"])
        assert body["side"] == "buy"

    def test_market_order_contracts(self):
        """Baz 0.03 BTC, ctVal=0.01 → 3 kontrat."""
        transport = RecordingTransport(OKX_ROUTES)
        okx = OkxDemoTrading(_okx_client(transport))
        okx.place_market("BTC-USDT-SWAP", "LONG", 0.03, "cid")
        body = json.loads(_last(transport, "/api/v5/trade/order")["body"])
        assert body["sz"] == "3"
        assert body["tdMode"] == "isolated"

    def test_protective_stop_shape(self):
        """v3.0: OKX sunucu tarafı stop = order-algo conditional, tam kapanış."""
        transport = RecordingTransport(OKX_ROUTES)
        okx = OkxDemoTrading(_okx_client(transport))
        okx.place_protective_stop("BTC-USDT-SWAP", "LONG", 49_000.55, "stpid")
        request = _last(transport, "/api/v5/trade/order-algo")
        body = json.loads(request["body"])
        assert body["ordType"] == "conditional"
        assert body["side"] == "sell"       # LONG → sell stop
        assert body["closeFraction"] == "1"  # pozisyonun tamamı
        assert "sz" not in body              # closeFraction ile sz gönderilmez
        assert body["reduceOnly"] == "true"
        assert body["triggerPx"] == "49000.6"  # tickSz=0.1'e yuvarlandı
        assert body["orderPx"] == "-1"          # tetiklenince market

    def test_cancel_all_uses_valid_endpoints(self):
        """v3.0: cancel-all-orders ucu OKX v5'te YOK; geçerli uçlar kullanılır."""
        routes = dict(OKX_ROUTES)
        routes["/api/v5/trade/orders-pending"] = {"data": [
            {"instId": "BTC-USDT-SWAP", "ordId": "77"},
        ]}
        routes["/api/v5/trade/orders-algo-pending"] = {"data": [
            {"instId": "BTC-USDT-SWAP", "algoId": "88"},
        ]}
        routes["/api/v5/trade/cancel-batch-orders"] = {"code": "0", "data": []}
        routes["/api/v5/trade/cancel-algos"] = {"code": "0", "data": []}
        transport = RecordingTransport(routes)
        okx = OkxDemoTrading(_okx_client(transport))
        okx.cancel_all_orders("BTC-USDT-SWAP")
        batch = json.loads(_last(transport, "/api/v5/trade/cancel-batch-orders")["body"])
        algos = json.loads(_last(transport, "/api/v5/trade/cancel-algos")["body"])
        assert batch == [{"instId": "BTC-USDT-SWAP", "ordId": "77"}]
        assert algos == [{"instId": "BTC-USDT-SWAP", "algoId": "88"}]
        invalid = [
            r for r in transport.requests
            if "cancel-all-orders" in r["url"]
        ]
        assert not invalid  # var olmayan uç HİÇ çağrılmaz

    def test_base_to_contracts_min_size(self):
        transport = RecordingTransport(OKX_ROUTES)
        okx = OkxDemoTrading(_okx_client(transport))
        assert okx.base_to_contracts("BTC-USDT-SWAP", 0.03) == 3
        with pytest.raises(LiveClientError):
            okx.base_to_contracts("BTC-USDT-SWAP", 0.005)  # 0.5 kontrat < minSz=1


class TestMirrorStopSafety:
    def _binance(self):
        routes = {
            "/fapi/v1/order": {"orderId": 1, "clientOrderId": "x"},
            "/fapi/v1/openOrders": [],
            "/fapi/v2/positionRisk": [],
            "/fapi/v1/exchangeInfo": {"symbols": [{
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001",
                     "minQty": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
                ],
            }]},
        }
        return BinanceFuturesTestnet(_binance_client(RecordingTransport(routes)))

    def test_stop_failure_flattens_position(self):
        """v3.0 KRİTİK: stop 3 denemede de kurulamazsa pozisyon KAPATILIR."""
        routes = {
            "/fapi/v1/order": {"orderId": 1, "clientOrderId": "x"},
            "/fapi/v1/exchangeInfo": {"symbols": []},
            "/fapi/v1/openOrders": [],
            "/fapi/v2/positionRisk": [],
        }
        transport = RecordingTransport(routes)
        broker = BinanceFuturesTestnet(_binance_client(transport))
        calls = {"n": 0}

        def failing_stop(*args, **kwargs):
            calls["n"] += 1
            raise LiveClientError("stop reddedildi")

        broker.place_protective_stop = failing_stop  # tip: ignore
        mirror = LiveMirror(binance=broker)
        mirror.mirror_open("BTCUSDT", "LONG", 0.01, 95_000.0, "s1")
        assert calls["n"] == 3  # 3 deneme
        assert mirror.unprotected_flattened == ["BTCUSDT"]
        exit_request = _last(transport, "/fapi/v1/order")
        assert "reduceOnly=true" in exit_request["url"]
        assert "SELL" in exit_request["url"]  # LONG → sell

    def test_stop_update_replaces_old(self):
        transport = RecordingTransport({
            "/fapi/v1/order": {"orderId": 1, "clientOrderId": "x"},
            "/fapi/v1/openOrders": [],
            "/fapi/v2/positionRisk": [],
            "/fapi/v1/exchangeInfo": {"symbols": []},
        })
        mirror = LiveMirror(binance=self._binance() if False else
                            BinanceFuturesTestnet(_binance_client(transport)))
        mirror.mirror_open("BTCUSDT", "LONG", 0.01, 95_000.0, "s1")
        actions = mirror.mirror_stop_update(
            "BTCUSDT", "LONG", 96_500.0, "s1",
        )
        assert any(a.startswith("stop-update") for a in actions)
        assert mirror.stop_prices["BTCUSDT"] == 96_500.0
        [r["url"] for r in transport.requests]
        # eski stop iptali: DELETE /fapi/v1/order?...origClientOrderId
        delete_calls = [r for r in transport.requests if r["method"] == "DELETE"]
        assert delete_calls, "eski stop iptal edilmeli"

    def test_stop_update_failure_restores_old_then_flattens(self):
        transport = RecordingTransport({
            "/fapi/v1/order": {"orderId": 1, "clientOrderId": "x"},
            "/fapi/v1/openOrders": [],
            "/fapi/v2/positionRisk": [],
            "/fapi/v1/exchangeInfo": {"symbols": []},
        })
        broker = BinanceFuturesTestnet(_binance_client(transport))
        mirror = LiveMirror(binance=broker)
        mirror.mirror_open("BTCUSDT", "LONG", 0.01, 95_000.0, "s1")
        # güncelleme sırasında stop kurulumu başarısız olsun
        broker.place_protective_stop = (
            lambda *a, **k: (_ for _ in ()).throw(LiveClientError("kapasite"))
        )
        mirror.mirror_stop_update("BTCUSDT", "LONG", 96_500.0, "s1")
        # stop yok → pozisyon kapatılmalı (korumasız bırakılmamalı)
        assert mirror.unprotected_flattened == ["BTCUSDT"]

    def test_state_persisted_and_loaded(self):
        saved: dict = {}
        transport = RecordingTransport({
            "/fapi/v1/order": {"orderId": 1, "clientOrderId": "x"},
            "/fapi/v1/openOrders": [],
            "/fapi/v2/positionRisk": [],
            "/fapi/v1/exchangeInfo": {"symbols": []},
        })
        mirror = LiveMirror(
            binance=BinanceFuturesTestnet(_binance_client(transport)),
            state_saver=lambda d: saved.__setitem__("live_mirror", d),
        )
        mirror.mirror_open("BTCUSDT", "LONG", 0.01, 95_000.0, "s1")
        assert "live_mirror" in saved
        mirror2 = LiveMirror(
            binance=BinanceFuturesTestnet(_binance_client(RecordingTransport({
                "/fapi/v1/openOrders": [], "/fapi/v2/positionRisk": [],
            }))),
            state_loader=lambda: saved["live_mirror"],
        )
        # aynı sinyal tekrar gönderilmez (restart güvenli)
        assert mirror2.mirror_open("BTCUSDT", "LONG", 0.01, 95_000.0, "s1") == []
        assert mirror2.stop_prices.get("BTCUSDT") == 95_000.0

    def test_mirror_close_cancels_stop(self):
        transport = RecordingTransport({
            "/fapi/v1/order": {"orderId": 1, "clientOrderId": "x"},
            "/fapi/v1/openOrders": [],
            "/fapi/v2/positionRisk": [],
            "/fapi/v1/exchangeInfo": {"symbols": []},
        })
        mirror = LiveMirror(
            binance=BinanceFuturesTestnet(_binance_client(transport)),
        )
        mirror.mirror_open("BTCUSDT", "LONG", 0.01, 95_000.0, "s1")
        mirror.mirror_close("BTCUSDT", "LONG", 0.01, "s1")
        deletes = [r for r in transport.requests if r["method"] == "DELETE"]
        assert deletes, "kapanış sonrası koruyucu stop iptal edilmeli"


class TestEmergencyOkxDirection:
    def test_okx_flatten_direction_fixed(self):
        """v3.0 KRİTİK: acil durumda LONG → sell (eski kod buy gönderiyordu)."""
        transport = RecordingTransport({
            **OKX_ROUTES,
            "/api/v5/trade/orders-pending": {"data": []},
            "/api/v5/trade/orders-algo-pending": {"data": []},
        })
        okx = OkxDemoTrading(_okx_client(transport))
        controller = EmergencyController(okx=okx)
        result = controller.trigger("test")
        assert "flatten:BTC-USDT-SWAP" in result["actions"]
        body = json.loads(_last(transport, "/api/v5/trade/order")["body"])
        assert body["side"] == "sell"
        assert body["reduceOnly"] == "true"

    def test_per_position_error_isolation(self):
        """Bir sembolde hata diğerlerinin kapatılmasını engellemez."""
        routes = {
            "/api/v5/trade/order": {"data": [{
                "ordId": "1", "clOrdId": "x", "instId": "BTC-USDT-SWAP",
                "sCode": "0",
            }]},
            "/api/v5/public/instruments": {"data": [
                _OKX_INSTRUMENT["data"][0],
                {**_OKX_INSTRUMENT["data"][0], "instId": "ETH-USDT-SWAP",
                 "ctVal": "0.1", "lotSz": "1", "minSz": "1", "tickSz": "0.1"},
            ]},
            "/api/v5/account/positions": {"data": [
                {"instId": "BTC-USDT-SWAP", "pos": "3", "avgPx": "50000",
                 "upl": "-10"},
                {"instId": "ETH-USDT-SWAP", "pos": "2", "avgPx": "3000",
                 "upl": "5"},
            ]},
            "/api/v5/trade/orders-pending": {"data": []},
            "/api/v5/trade/orders-algo-pending": {"data": []},
        }

        class FlakyTransport(RecordingTransport):
            def __call__(self, url, method, headers, body):
                if "/api/v5/trade/order" in url.split("?")[0] and \
                        "ETH-USDT" in (body or b"").decode():
                    return 200, json.dumps({"data": [{
                        "sCode": "51008", "sMsg": "fail",
                    }]}).encode()
                return super().__call__(url, method, headers, body)

        transport = FlakyTransport(routes)
        okx = OkxDemoTrading(_okx_client(transport))
        controller = EmergencyController(okx=okx)
        result = controller.trigger("test")
        # ETH hata verir ama BTC flatten edilmiş olmalı
        assert "flatten:BTC-USDT-SWAP" in result["actions"]
        assert result["errors"]


class TestRestartRecoveryOkx:
    def test_okx_recovery_restores_stop(self):
        transport = RecordingTransport({
            "/api/v5/public/instruments": _OKX_INSTRUMENT,
            "/api/v5/trade/order-algo": {"data": [{
                "algoId": "9", "clOrdId": "y", "sCode": "0",
                "instId": "BTC-USDT-SWAP",
            }]},
            "/api/v5/trade/orders-pending": {"data": []},
            "/api/v5/trade/orders-algo-pending": {"data": []},
            "/api/v5/account/positions": {"data": [
                {"instId": "BTC-USDT-SWAP", "pos": "3", "avgPx": "50000",
                 "upl": "-10", "cTime": 1},
            ]},
        })
        recovery = RestartRecovery(okx=OkxDemoTrading(_okx_client(transport)))
        report = recovery.recover_okx({"BTC-USDT-SWAP": 49_000.0})
        assert report.stops_restored == ["BTC-USDT-SWAP"]
        body = json.loads(_last(transport, "/api/v5/trade/order-algo")["body"])
        assert body["ordType"] == "conditional"
        assert body["side"] == "sell"


# ---------------------------------------------------------------------------
# Backtest: slippage / latency / flash crash / kısmi dolum
# ---------------------------------------------------------------------------

from backtest.costs import CostModel  # noqa: E402
from backtest.engine import BacktestEngine  # noqa: E402
from core.risk import RiskManager  # noqa: E402
from dataclasses import replace as dc_replace  # noqa: E402
from exec.paper import PaperBroker  # noqa: E402
from infra.market_data.models import Candle  # noqa: E402
from tests.helpers import INTERVAL_MS, legacy_ttl, make_candles, apex_config  # noqa: E402


def _fade_setup_candles(symbol: str, volume=10.0, spike_volume=40.0):
    """FADE-LONG senaryosu: yatay serinin sonunda ~%2 düşüş + hacim patlaması.
    (test_backtest.py'de kanıtlanmış giriş senaryosunun kopyası)"""
    closes = [100.0] * 80
    volumes = [volume] * 80
    closes[-2] = 98.2
    closes[-1] = 98.0
    volumes[-1] = spike_volume
    return make_candles(closes, volumes=volumes)


def _touch_candle(setup, offset=1, low=97.85):
    return Candle(
        timestamp=setup[-1].timestamp + INTERVAL_MS * offset,
        open=98.0, high=98.1, low=low, close=97.95, volume=15.0,
    )


def _config(slippage=0.0, latency=0):
    config = apex_config()
    config.data = dc_replace(
        config.data, bt_slippage_bps=slippage, bt_latency_ms=latency,
    )
    return config


class TestBacktestResilience:
    def test_slippage_worsens_fill(self):
        """v3.0: kayma > 0 → LONG dolum fiyatı yükselir ve 'slipped' işaretlenir."""
        setup = _fade_setup_candles("TESTUSDT")
        # v5.1: maliyetsiz TABAN artık açıkça kapatılmalı (varsayılan açık)
        base = legacy_ttl(BacktestEngine(_config(), initial_balance=1000)).run(
            {"TESTUSDT": setup + [_touch_candle(setup)]},
            cost_model=CostModel.disabled(),
        )
        slipped = legacy_ttl(
            BacktestEngine(_config(slippage=5.0), initial_balance=1000),
        ).run(
            {"TESTUSDT": setup + [_touch_candle(setup)]},
            cost_model=CostModel.disabled(),
        )
        base_fills = [t for t in base.trades if t["type"] == "ORDER_FILL"]
        slip_fills = [t for t in slipped.trades if t["type"] == "ORDER_FILL"]
        assert base_fills and slip_fills
        assert base_fills[0]["slipped"] is False
        assert slip_fills[0]["slipped"] is True
        # LONG girişte 5 bps kayma: fiyat yukarı kayar
        assert slip_fills[0]["price"] == pytest.approx(
            base_fills[0]["price"] * 1.0005, rel=1e-6,
        )
        assert base.latency_ms == 0 and base.slippage_bps == 0.0

    def test_latency_defers_fill(self):
        """v3.0: gecikme 2 mum boyutunda → dolum bir mum sonraya atlar."""
        setup = _fade_setup_candles("TESTUSDT")
        candles = setup + [_touch_candle(setup, 1), _touch_candle(setup, 2)]
        base = legacy_ttl(BacktestEngine(_config(), initial_balance=1000)).run(
            {"TESTUSDT": candles}, cost_model=CostModel.disabled(),
        )
        delayed = legacy_ttl(BacktestEngine(
            _config(latency=600_000), initial_balance=1000,
        )).run({"TESTUSDT": candles}, cost_model=CostModel.disabled())
        base_fills = [t for t in base.trades if t["type"] == "ORDER_FILL"]
        delay_fills = [t for t in delayed.trades if t["type"] == "ORDER_FILL"]
        assert base_fills and delay_fills
        assert delay_fills[0]["timestamp"] > base_fills[0]["timestamp"]

    def test_default_zero_keeps_v2_behavior(self):
        """Varsayılan (0/0) v2.0 davranışıyla birebir aynı sonuç."""
        setup = _fade_setup_candles("TESTUSDT")
        r1 = BacktestEngine(apex_config(), initial_balance=1000).run(
            {"TESTUSDT": setup + [_touch_candle(setup)]},
        )
        r2 = BacktestEngine(_config(0.0, 0), initial_balance=1000).run(
            {"TESTUSDT": setup + [_touch_candle(setup)]},
        )
        assert r1.final_balance == r2.final_balance


class TestFlashCrash:
    def test_flash_crash_single_stop_no_panic(self):
        """%20 çökme: stop BİR kez çalışır, panik yeniden girişi yok."""
        config = apex_config()
        broker = PaperBroker(config, 1000.0)
        risk = RiskManager(config)
        plan = risk.plan(100.0, 0.02, "LONG", motor="fade")
        ts = 1_700_000_000_000
        order = broker.place_entry("BTCUSDT", plan, ts)
        broker.bind_plan(order, plan, "fade", {})
        # trade-through: fiyat limanın altına sarkar → kalanın tamamı dolar
        broker.process_entry_tick("BTCUSDT", 99.9, 50.0, ts)
        assert "BTCUSDT" in broker.portfolio.positions
        # flash crash: anlık %20 düşüş → stop BİR kez
        events = broker.manage_position_tick("BTCUSDT", 80.0, ts + 1_000, atr=None)
        closes = [e for e in events if e.get("type") == "CLOSE"]
        assert len(closes) == 1
        assert closes[0]["reason"] in ("stop_loss", "position_loss_stop", "trailing_stop", "liquidation")
        assert "BTCUSDT" not in broker.portfolio.positions
        # toparlanma: broker seviyesinde kendiliğinden yeni pozisyon AÇILMAZ
        broker.process_entry_tick("BTCUSDT", 99.0, 50.0, ts + 2_000)
        assert "BTCUSDT" not in broker.portfolio.positions


class TestPartialFill:
    def test_partial_then_expiry_opens_partial_position(self):
        """v3.0: kısmen dolan emir süresi dolarsa dolan kısım pozisyondur."""
        config = apex_config()
        config.exit = dc_replace(config.exit, order_ttl_seconds=0.05)
        broker = PaperBroker(config, 1000.0)
        risk = RiskManager(config)
        plan = risk.plan(100.0, 0.02, "LONG", motor="fade")
        ts = 1_700_000_000_000
        order = broker.place_entry("BTCUSDT", plan, ts)
        broker.bind_plan(order, plan, "fade", {})
        limit_price = order.limit_price
        # limana DOKUNAN küçük hacim → kısmi dolum (kuyruk 0, çünkü baseline=0)
        fill = broker.process_entry_tick("BTCUSDT", limit_price, 2.0, ts)
        assert fill is not None
        filled_qty = order.filled_quantity
        assert 0 < filled_qty < plan.quantity
        # TTL dolar → dolan kısım pozisyona dönüşmeli (v3.0 düzeltmesi)
        broker.process_entry_tick(
            "BTCUSDT", limit_price, 0.0,
            ts + int(config.exit.order_ttl_seconds * 1000) + 1,
        )
        position = broker.portfolio.positions.get("BTCUSDT")
        assert position is not None
        assert position.quantity == pytest.approx(filled_qty)
        assert position.initial_quantity == pytest.approx(filled_qty)
        open_records = [
            t for t in broker.trades
            if t.get("type") == "OPEN" and t.get("partial")
        ]
        assert open_records, "kısmi OPEN kaydı üretilmeli"
        # muhasebe: giriş ücreti yalnızca dolan kısım için
        assert position.entry_fee == pytest.approx(
            position.entry * position.quantity * config.account.maker_fee_rate,
            rel=1e-6,
        )
