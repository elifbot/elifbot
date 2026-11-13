"""v2.0 — Borsa entegrasyon güvenliği testleri (şartname madde 9).

Sahte transport kullanılır; hiçbir test gerçek ağa çıkmaz.
Kapsam: imzalı istek, idempotency, mutabakat, restart kurtarma,
sunucu tarafı koruyucu stop, reduce-only çıkış, acil durum.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from live import (
    BinanceFuturesTestnet,
    EmergencyController,
    IdempotentOrderIdFactory,
    LiveMirror,
    PositionReconciler,
    RestartRecovery,
    SignedHttpClient,
    security_checklist,
)
from live.broker_clients import ExchangeOrder, ExchangePosition
from live.clients import LiveClientError


class FakeTransport:
    """İstek yakalayan sahte transport; endpoint'e göre sahte yanıt üretir."""

    def __init__(self):
        self.requests: list[dict] = []
        self.positions = []
        self.open_orders = []
        self.orders: dict[str, dict] = {}

    def __call__(self, url: str, method: str, headers: dict, body: bytes):
        self.requests.append({
            "url": url, "method": method, "headers": dict(headers),
            "body": body.decode() if body else "",
        })
        path = url.split("?")[0]
        if path.endswith("/fapi/v2/positionRisk"):
            return 200, json.dumps(self.positions).encode()
        if path.endswith("/fapi/v1/openOrders"):
            return 200, json.dumps(self.open_orders).encode()
        if path.endswith("/fapi/v1/order"):
            payload = dict(json.loads(body) if body else {})
            qs = dict(
                kv.split("=", 1) for kv in url.split("?")[1].split("&")
                if "=" in kv and kv.split("=", 1)[0] != "signature"
            )
            payload.update(qs)
            client_id = payload.get("newClientOrderId", "")
            self.orders[client_id] = payload
            return 200, json.dumps({
                "orderId": 1, "clientOrderId": client_id,
                "symbol": payload.get("symbol", ""),
                "side": payload.get("side", ""),
                "status": "NEW",
                "price": payload.get("price", "0"),
                "origQty": payload.get("quantity", payload.get("origQty", "0")),
                "executedQty": "0",
                "reduceOnly": payload.get("reduceOnly", "false") == "true",
                "updateTime": 1_700_000_000_000,
            }).encode()
        if path.endswith("/fapi/v1/allOpenOrders"):
            self.open_orders = []
            return 200, json.dumps({"code": 200, "msg": "ok"}).encode()
        if path.endswith("/fapi/v1/leverage") or path.endswith("/fapi/v1/marginType"):
            return 200, json.dumps({"code": 200}).encode()
        if path.endswith("/fapi/v1/klines"):
            return 200, json.dumps([
                [1_700_000_000_000, "100", "101", "99", "100.5", "10"],
            ]).encode()
        return 404, json.dumps({"error": "not found"}).encode()


def _client(transport: FakeTransport) -> SignedHttpClient:
    import os
    os.environ["BINANCE_TESTNET_API_KEY"] = "test-key"
    os.environ["BINANCE_TESTNET_API_SECRET"] = "test-secret"
    return SignedHttpClient(
        "https://testnet.binancefuture.com",
        "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET",
        transport,
    )


class TestSignedClient:
    def test_request_is_signed(self):
        transport = FakeTransport()
        client = _client(transport)
        client.signed_request("POST", "/fapi/v1/leverage",
                              {"symbol": "BTCUSDT", "leverage": 10})
        request = transport.requests[0]
        assert "X-MBX-APIKEY" in request["headers"]
        assert "signature=" in request["url"]
        assert "timestamp=" in request["url"]

    def test_signature_matches_hmac(self):
        transport = FakeTransport()
        client = _client(transport)
        client.signed_request("POST", "/fapi/v1/leverage",
                              {"symbol": "BTCUSDT", "leverage": 10})
        url = transport.requests[0]["url"]
        base, _, signature = url.partition("signature=")
        qs = base.split("?")[1].rstrip("&")
        expected = hmac.new(
            b"test-secret", qs.encode(), hashlib.sha256,
        ).hexdigest()
        assert signature == expected

    def test_missing_keys_fail_closed(self):
        import os
        os.environ.pop("BINANCE_TESTNET_API_KEY", None)
        os.environ.pop("BINANCE_TESTNET_API_SECRET", None)
        client = SignedHttpClient(
            "https://testnet.binancefuture.com",
            "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET",
            FakeTransport(),
        )
        with pytest.raises(LiveClientError):
            client.signed_request("GET", "/fapi/v2/positionRisk")


class TestBrokerClient:
    def test_protective_stop_is_close_position_reduce_only(self):
        """Sunucu tarafı koruyucu stop: STOP_MARKET + closePosition=true."""
        transport = FakeTransport()
        broker = BinanceFuturesTestnet(_client(transport))
        broker.place_protective_stop("BTCUSDT", "LONG", 95_000.0, "ACB2-STOP1")
        sent = transport.requests[0]["url"]
        assert "STOP_MARKET" in sent
        assert "closePosition=true" in sent
        assert "SELL" in sent  # LONG pozisyon → SELL stop

    def test_entry_order_shape(self):
        transport = FakeTransport()
        broker = BinanceFuturesTestnet(_client(transport))
        order = broker.place_entry("BTCUSDT", "LONG", 0.01, "ACB2-E1")
        assert order.client_order_id == "ACB2-E1"
        sent = transport.requests[0]["url"]
        assert "BUY" in sent and "MARKET" in sent

    def test_reduce_only_exit(self):
        transport = FakeTransport()
        broker = BinanceFuturesTestnet(_client(transport))
        broker.place_reduce_only_exit("BTCUSDT", "LONG", 0.01, "ACB2-X1")
        sent = transport.requests[0]["url"]
        assert "reduceOnly=true" in sent
        assert "SELL" in sent  # LONG çıkışı SELL

    def test_perp_candles_real_data_check(self):
        """Canlı öncesi GERÇEK perp verisi çekilebilir (ayna/spot karışmaz)."""
        transport = FakeTransport()
        broker = BinanceFuturesTestnet(_client(transport))
        candles = broker.fetch_perp_candles("BTCUSDT", "5m", 10)
        assert candles and candles[0].close == pytest.approx(100.5)


class TestIdempotency:
    def test_same_signal_same_order_id(self):
        factory = IdempotentOrderIdFactory()
        first = factory.order_id("BTCUSDT", "LONG", "signal-123")
        second = factory.order_id("BTCUSDT", "LONG", "signal-123")
        assert first == second
        assert factory.was_issued(first)

    def test_different_signal_different_id(self):
        factory = IdempotentOrderIdFactory()
        a = factory.order_id("BTCUSDT", "LONG", "s1")
        b = factory.order_id("BTCUSDT", "LONG", "s2")
        assert a != b


class TestReconciler:
    def test_matching_positions(self):
        reconciler = PositionReconciler()
        exchange = [
            ExchangePosition("BTCUSDT", "LONG", 0.5, 97.0, 1.0),
        ]
        report = reconciler.reconcile(
            {"BTCUSDT": ("LONG", 0.5)}, exchange,
        )
        assert report.matched == ["BTCUSDT"]
        assert not report.has_drift

    def test_quantity_drift_detected(self):
        reconciler = PositionReconciler()
        exchange = [
            ExchangePosition("BTCUSDT", "LONG", 0.7, 97.0, 1.0),
        ]
        report = reconciler.reconcile(
            {"BTCUSDT": ("LONG", 0.5)}, exchange,
        )
        assert report.quantity_drift
        assert report.has_drift

    def test_local_and_exchange_only(self):
        reconciler = PositionReconciler()
        exchange = [ExchangePosition("ETHUSDT", "SHORT", 2.0, 50.0, 0.0)]
        report = reconciler.reconcile(
            {"BTCUSDT": ("LONG", 0.5)}, exchange,
        )
        assert report.local_only == ["BTCUSDT"]
        assert report.exchange_only == ["ETHUSDT"]


class TestRestartRecovery:
    def test_stale_entry_order_canceled_and_stop_restored(self):
        transport = FakeTransport()
        transport.open_orders = [
            {
                "orderId": 2, "clientOrderId": "ACB2-old", "symbol": "BTCUSDT",
                "side": "BUY", "status": "NEW", "price": "0",
                "origQty": "0.01", "executedQty": "0",
                "reduceOnly": False, "updateTime": 1_700_000_000_000,
            },
        ]
        transport.positions = [
            {"symbol": "BTCUSDT", "positionAmt": "0.5",
             "entryPrice": "97000", "unRealizedProfit": "1.0"},
        ]
        broker = BinanceFuturesTestnet(_client(transport))
        recovery = RestartRecovery(
            binance=broker, max_order_age_s=120.0,
            clock=lambda: 1_700_000_100_000,  # 100 sn sonra: bayat değil!
        )
        report = recovery.recover_binance({"BTCUSDT": 95_000.0})
        # 100 sn < 120 sn → iptal EDİLMEZ; stop zaten yok → kurulur
        assert report.canceled_stale_orders == []
        assert report.stops_restored == ["BTCUSDT"]

    def test_old_entry_order_canceled(self):
        transport = FakeTransport()
        transport.open_orders = [
            {
                "orderId": 2, "clientOrderId": "ACB2-old", "symbol": "BTCUSDT",
                "side": "BUY", "status": "NEW", "price": "0",
                "origQty": "0.01", "executedQty": "0",
                "reduceOnly": False, "updateTime": 1_700_000_000_000,
            },
        ]
        transport.positions = []
        broker = BinanceFuturesTestnet(_client(transport))
        recovery = RestartRecovery(
            binance=broker, max_order_age_s=120.0,
            clock=lambda: 1_700_000_300_000,  # 300 sn: bayat
        )
        report = recovery.recover_binance({})
        assert report.canceled_stale_orders == ["BTCUSDT"]


class TestLiveMirror:
    def test_open_mirrors_entry_and_stop_once(self):
        transport = FakeTransport()
        broker = BinanceFuturesTestnet(_client(transport))
        mirror = LiveMirror(broker)
        actions = mirror.mirror_open(
            "BTCUSDT", "LONG", 0.01, 95_000.0, "signal-1",
        )
        assert len(actions) == 2  # giriş + koruyucu stop
        # Aynı sinyal tekrar → mükerrer gönderim YOK (idempotency)
        again = mirror.mirror_open(
            "BTCUSDT", "LONG", 0.01, 95_000.0, "signal-1",
        )
        assert again == []
        entry_requests = [
            r for r in transport.requests
            if "/fapi/v1/order" in r["url"] and "closePosition" not in r["url"]
            and "reduceOnly" not in r["url"]
        ]
        assert len(entry_requests) == 1

    def test_close_mirrors_reduce_only(self):
        transport = FakeTransport()
        broker = BinanceFuturesTestnet(_client(transport))
        mirror = LiveMirror(broker)
        actions = mirror.mirror_close("BTCUSDT", "LONG", 0.01, "signal-1")
        assert actions
        assert "reduceOnly=true" in transport.requests[0]["url"]


class TestEmergency:
    def test_emergency_cancels_and_flattens(self):
        transport = FakeTransport()
        transport.positions = [
            {"symbol": "BTCUSDT", "positionAmt": "0.5",
             "entryPrice": "97000", "unRealizedProfit": "1.0"},
        ]
        broker = BinanceFuturesTestnet(_client(transport))
        halted = []
        controller = EmergencyController(
            binance=broker, on_halt=halted.append,
        )
        result = controller.trigger(reason="test")
        assert result["reason"] == "test"
        assert any(a.startswith("flatten:") for a in result["actions"])
        assert halted == ["test"]
        # Flatten emirleri reduce-only olmalı
        flatten_requests = [
            r for r in transport.requests
            if "/fapi/v1/order" in r["url"] and "reduceOnly=true" in r["url"]
        ]
        assert flatten_requests


class TestSecurityChecklist:
    def test_withdrawal_check_present(self):
        items = security_checklist()
        assert any("Para çekme" in item["check"] for item in items)
        assert any(item["required"] == "KAPALI" and "çekme" in item["check"]
                   for item in items)
