"""v4.0 — canlı emir katmanı sertleştirme testleri (madde 10).

429/Retry-After, zaman senkronu, hedge mode, post-only maker giriş + yedek.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from live.broker_clients import BinanceFuturesTestnet, OkxDemoTrading
from live.clients import (
    LiveClientError,
    LiveRateLimited,
    LiveServerError,
    OkxSignedClient,
    SignedHttpClient,
)
from tests.v62_test_helpers import mechanical_mirror


def _client(transport=None, **kwargs):
    client = SignedHttpClient(
        "https://testnet.binancefuture.com", "K", "S",
        transport or (lambda *a, **k: (200, b"{}")),
        clock=lambda: 1_000_000,
        **kwargs,
    )
    client.api_key, client.api_secret = "k", "s"
    return client


class RetryAfterTests(unittest.TestCase):
    def test_429_retries_with_retry_after(self):
        sleeps = []
        calls = {"n": 0}

        def transport(url, method, headers, body):
            calls["n"] += 1
            if calls["n"] == 1:
                raise LiveRateLimited("HTTP 429", retry_after_s=3.0)
            return 200, b"{}"

        client = _client(transport, rate_retries=2, sleeper=sleeps.append)
        response = client.signed_request("GET", "/fapi/v2/balance")
        self.assertEqual(response.status, 200)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(sleeps, [3.0])

    def test_429_exhausted_raises(self):
        def transport(url, method, headers, body):
            raise LiveRateLimited("HTTP 429", retry_after_s=0.1)

        client = _client(transport, rate_retries=1, sleeper=lambda s: None)
        with self.assertRaises(LiveRateLimited):
            client.signed_request("GET", "/fapi/v2/balance")

    def test_5xx_retries_with_backoff(self):
        sleeps = []
        calls = {"n": 0}

        def transport(url, method, headers, body):
            calls["n"] += 1
            if calls["n"] == 1:
                raise LiveServerError("HTTP 503")
            return 200, b"{}"

        client = _client(transport, rate_retries=2, sleeper=sleeps.append)
        client.signed_request("GET", "/fapi/v2/balance")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(sleeps, [1.0])

    def test_400_not_retried(self):
        calls = {"n": 0}

        def transport(url, method, headers, body):
            calls["n"] += 1
            raise LiveClientError("HTTP 400: {}")

        client = _client(transport, rate_retries=3, sleeper=lambda s: None)
        with self.assertRaises(LiveClientError):
            client.signed_request("GET", "/fapi/v2/balance")
        self.assertEqual(calls["n"], 1)


class TimeSyncTests(unittest.TestCase):
    def test_offset_applied_to_signed_timestamp(self):
        captured = {}

        def transport(url, method, headers, body):
            captured["url"] = url
            return 200, b"{}"

        client = _client(transport)
        client.clock = lambda: 1_000_000
        client.time_offset_ms = 2_500
        client.signed_request("GET", "/fapi/v2/balance")
        self.assertIn("timestamp=1002500", captured["url"])

    def test_sync_time_sets_offset(self):
        client = _client(lambda *a, **k: (
            200, b'{"serverTime": 1003000}',
        ))
        client.clock = lambda: 1_000_000
        offset = client.sync_time()
        self.assertEqual(offset, 3_000)
        self.assertEqual(client.time_offset_ms, 3_000)

    def test_minus_1021_resyncs_and_retries(self):
        state = {"calls": 0, "syncs": 0}

        def transport(url, method, headers, body):
            state["calls"] += 1
            if "/fapi/v1/time" in url:
                state["syncs"] += 1
                return 200, b'{"serverTime": 1005000}'
            if state["calls"] == 1:
                return 400, b'{"code":-1021,"msg":"Timestamp"}'
            return 200, b"{}"

        client = _client(transport)
        client.clock = lambda: 1_000_000
        client.last_time_sync_ms = 1  # sync daha önce yapıldı
        client.time_offset_ms = 0
        client.signed_request("GET", "/fapi/v2/balance")
        self.assertEqual(state["syncs"], 1)
        self.assertGreaterEqual(state["calls"], 3)

    def test_okx_time_endpoint(self):
        client = OkxSignedClient(
            "https://www.okx.com", "K", "S",
            lambda *a, **k: (200, b'{"code":"0","data":[{"ts":"1004000"}]}'),
            clock=lambda: 1_000_000,
        )
        client.api_key, client.api_secret = "k", "s"
        self.assertEqual(client.sync_time(), 4_000)
        self.assertEqual(OkxSignedClient.TIME_SYNC_ENDPOINT, "/api/v5/public/time")


def _resp(payload):
    response = Mock()
    response.as_dict.return_value = payload
    response.as_list.return_value = payload
    return response


def _binance_broker(payloads=None, hedge: bool = False):
    client = Mock()
    client.signed_request.return_value = _resp(payloads or {"orderId": "1"})
    broker = BinanceFuturesTestnet(client)
    if hedge:
        broker.hedge_mode = True
    broker._filters["BTCUSDT"] = SimpleNamespace(
        tick_size=0.1, step_size=0.001, min_qty=0.001, min_notional=5.0,
    )
    return broker


class HedgeModeTests(unittest.TestCase):
    def test_detect_position_mode(self):
        broker = BinanceFuturesTestnet(Mock())
        broker.client.signed_request.return_value = _resp(
            {"dualSidePosition": True},
        )
        self.assertTrue(broker.detect_position_mode())
        self.assertTrue(broker.hedge_mode)

    def test_one_way_entry_has_no_position_side(self):
        broker = _binance_broker()
        broker.place_entry("BTCUSDT", "LONG", 0.5, "cid")
        params = broker.client.signed_request.call_args[0][2]
        self.assertNotIn("positionSide", params)

    def test_hedge_entry_has_position_side(self):
        broker = _binance_broker(hedge=True)
        broker.place_entry("BTCUSDT", "LONG", 0.5, "cid")
        params = broker.client.signed_request.call_args[0][2]
        self.assertEqual(params["positionSide"], "LONG")
        self.assertEqual(params["side"], "BUY")

    def test_hedge_exit_omits_reduce_only(self):
        broker = _binance_broker(hedge=True)
        broker.place_reduce_only_exit("BTCUSDT", "LONG", 0.5, "cid")
        params = broker.client.signed_request.call_args[0][2]
        self.assertEqual(params["positionSide"], "LONG")
        self.assertEqual(params["side"], "SELL")
        self.assertNotIn("reduceOnly", params)

    def test_one_way_exit_keeps_reduce_only(self):
        broker = _binance_broker()
        broker.place_reduce_only_exit("BTCUSDT", "LONG", 0.5, "cid")
        params = broker.client.signed_request.call_args[0][2]
        self.assertNotIn("positionSide", params)
        self.assertEqual(params["reduceOnly"], "true")

    def test_hedge_stop_has_position_side(self):
        broker = _binance_broker(hedge=True)
        broker.place_protective_stop("BTCUSDT", "SHORT", 101.0, "cid")
        params = broker.client.signed_request.call_args[0][2]
        self.assertEqual(params["positionSide"], "SHORT")
        self.assertEqual(params["side"], "BUY")

    def test_fetch_order_by_client_id_not_found(self):
        from live.clients import LiveClientError as E
        broker = BinanceFuturesTestnet(Mock())
        broker.client.signed_request.side_effect = E(
            "HTTP 400: {'code':-2013,'msg':'Order does not exist'}",
        )
        self.assertIsNone(broker.fetch_order_by_client_id("BTCUSDT", "x"))


def _okx_broker(pos_mode: str | None = None):
    client = Mock()
    client.signed_request.return_value = _resp(
        {"data": [{"sCode": "0", "ordId": "1"}]},
    )
    client.public_request.return_value = _resp({
        "code": "0", "data": [{"ctVal": "0.01", "lotSz": "1", "minSz": "1",
                               "tickSz": "0.1"}],
    })
    broker = OkxDemoTrading(client)
    if pos_mode:
        broker.pos_mode = pos_mode
    return broker


class OkxPositionModeTests(unittest.TestCase):
    def test_net_mode_reduce_only(self):
        broker = _okx_broker(pos_mode="net_mode")
        broker.place_reduce_only_exit("BTC-USDT-SWAP", "LONG", 1.0, "cid")
        body = broker.client.signed_request.call_args[1]["body"]
        self.assertEqual(body["reduceOnly"], "true")
        self.assertNotIn("posSide", body)
        self.assertEqual(body["side"], "sell")

    def test_long_short_mode_pos_side(self):
        broker = _okx_broker(pos_mode="long_short_mode")
        broker.place_reduce_only_exit("BTC-USDT-SWAP", "LONG", 1.0, "cid")
        body = broker.client.signed_request.call_args[1]["body"]
        self.assertEqual(body["posSide"], "long")
        self.assertEqual(body["side"], "sell")
        self.assertNotIn("reduceOnly", body)

    def test_long_short_entry_pos_side(self):
        broker = _okx_broker(pos_mode="long_short_mode")
        broker.place_market("BTC-USDT-SWAP", "LONG", 1.0, "cid")
        body = broker.client.signed_request.call_args[1]["body"]
        self.assertEqual(body["posSide"], "long")
        self.assertNotIn("reduceOnly", body)

    def test_detect_pos_mode(self):
        broker = _okx_broker()
        broker.client.signed_request.return_value = _resp(
            {"data": [{"posMode": "long_short_mode"}]},
        )
        self.assertEqual(broker.detect_position_mode(), "long_short_mode")

    def test_post_only_body(self):
        broker = _okx_broker()
        broker.place_post_only("BTC-USDT-SWAP", "LONG", 1.0, 99.5, "cid")
        body = broker.client.signed_request.call_args[1]["body"]
        self.assertEqual(body["ordType"], "post_only")
        self.assertEqual(body["side"], "buy")
        self.assertEqual(body["px"], "99.5")



def _mirror(entry_style="post_only_market_fallback", open_orders=None,
            executed=0.0, timeout_s: float = 2.0):
    broker = Mock()
    broker.name = "binance-testnet"
    broker.hedge_mode = False
    broker.place_entry.return_value = SimpleNamespace(
        order_id="1", client_order_id="c", status="NEW", executed_quantity=0.0,
    )
    # bekleyen emir mocku, mirror'ın üreteceği gerçek client id ile dönmeli:
    # id üretimi deterministiktir (symbol|side|signal_key) → önce tüket.
    client_id = f"ACB2-{__import__('hashlib').sha1(
        b'BTCUSDT|LONG|sig').hexdigest()[:10].upper()}"
    broker.fetch_open_orders.return_value = [
        SimpleNamespace(client_order_id=client_id, status="NEW")
        if open_orders else None
    ] if open_orders else []
    broker.fetch_order_by_client_id.return_value = SimpleNamespace(
        executed_quantity=executed,
    )
    broker.place_protective_stop.return_value = SimpleNamespace(order_id="s")
    clock = {"t": 1_000_000}

    def tick():
        clock["t"] += 1_500
        return clock["t"]

    mirror = mechanical_mirror(
        binance=broker, entry_style=entry_style,
        entry_fill_timeout_s=timeout_s, poll_interval_s=0.001,
        clock=tick, sleeper=lambda s: None,
    )
    return mirror, broker


class PostOnlyMirrorTests(unittest.TestCase):
    def test_market_style_uses_market(self):
        mirror, broker = _mirror(entry_style="market")
        mirror.mirror_open("BTCUSDT", "LONG", 0.5, 99.0, "sig", 100.0)
        call = broker.place_entry.call_args
        self.assertTrue(call[1].get("market", True))  # market=True
        self.assertNotIn("price", call[1])
        self.assertEqual(mirror.entry_fallbacks, [])

    def test_post_only_filled_quickly(self):
        # açık emir listesi boş → anında doldu sayılır; MARKET çağrısı YOK
        mirror, broker = _mirror(open_orders=[])
        actions = mirror.mirror_open("BTCUSDT", "LONG", 0.5, 99.0, "sig", 100.0)
        first_call = broker.place_entry.call_args
        self.assertIs(first_call[1].get("market"), False)  # post-only limit
        self.assertEqual(first_call[1].get("price"), 100.0)
        self.assertTrue(any(a.startswith("entry:") for a in actions))
        self.assertTrue(any(a.startswith("stop:") for a in actions))
        self.assertEqual(len(broker.place_entry.call_args_list), 1)
        self.assertEqual(mirror.entry_fallbacks, [])

    def test_post_only_timeout_falls_back_to_market(self):
        order = SimpleNamespace(client_order_id="c", status="NEW")
        mirror, broker = _mirror(
            entry_style="post_only_market_fallback",
            open_orders=[order], executed=0.0,
        )
        actions = mirror.mirror_open("BTCUSDT", "LONG", 0.5, 99.0, "sig", 100.0)
        self.assertEqual(mirror.entry_fallbacks, ["BTCUSDT"])
        # 2. çağrı: kalan miktar MARKET (client_id + "M")
        self.assertEqual(len(broker.place_entry.call_args_list), 2)
        second = broker.place_entry.call_args_list[1]
        self.assertTrue(second[1].get("market", True))  # market=True
        self.assertTrue(second[0][3].endswith("M"))
        self.assertTrue(any(a.startswith("entry:") for a in actions))
        broker.cancel_order_by_client_id.assert_called_once()

    def test_post_only_pure_timeout_skips(self):
        order = SimpleNamespace(client_order_id="c", status="NEW")
        mirror, broker = _mirror(
            entry_style="post_only", open_orders=[order], executed=0.0,
        )
        actions = mirror.mirror_open("BTCUSDT", "LONG", 0.5, 99.0, "sig", 100.0)
        self.assertEqual(actions, [])  # eşleme atlandı
        self.assertIn("BTCUSDT", mirror.entry_skipped)
        self.assertEqual(len(broker.place_entry.call_args_list), 1)  # yalnız post-only
        broker.cancel_order_by_client_id.assert_called_once()

    def test_post_only_partial_fill_markets_remainder(self):
        order = SimpleNamespace(client_order_id="c", status="PARTIALLY_FILLED")
        mirror, broker = _mirror(
            entry_style="post_only_market_fallback",
            open_orders=[order], executed=0.2,
        )
        mirror.mirror_open("BTCUSDT", "LONG", 0.5, 99.0, "sig", 100.0)
        second = broker.place_entry.call_args_list[1]
        self.assertAlmostEqual(second[0][2], 0.3)  # kalan miktar

    def test_post_only_rejection_falls_back(self):
        mirror, broker = _mirror(entry_style="post_only_market_fallback")
        broker.place_entry.side_effect = [
            LiveClientError("HTTP 400: -5022 would immediately match"),
            SimpleNamespace(order_id="2", client_order_id="cM", status="FILLED",
                            executed_quantity=0.0),
        ]
        broker.fetch_open_orders.return_value = []
        actions = mirror.mirror_open("BTCUSDT", "LONG", 0.5, 99.0, "sig", 100.0)
        self.assertIn("BTCUSDT", mirror.entry_fallbacks)
        self.assertTrue(any(a.startswith("entry:") for a in actions))

    def test_mirror_dca_market_and_idempotent(self):
        mirror, broker = _mirror(entry_style="market")
        mirror.stop_prices["BTCUSDT"] = 99.0
        mirror.stop_client_ids["BTCUSDT"] = "test-stop"
        broker.fetch_positions.return_value = [SimpleNamespace(symbol="BTCUSDT", side="LONG", quantity=0.5)]
        broker.fetch_open_orders.return_value = [SimpleNamespace(client_order_id="test-stop")]
        actions = mirror.mirror_dca("BTCUSDT", "LONG", 0.5, "dca-key-1")
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].startswith("dca-entry:"))
        call = broker.place_entry.call_args
        self.assertTrue(call[1].get("market", True))  # market
        # aynı anahtar tekrar → idempotent (yeni çağrı yok)
        mirror.mirror_dca("BTCUSDT", "LONG", 0.5, "dca-key-1")
        self.assertEqual(broker.place_entry.call_count, 1)

    def test_invalid_entry_style_rejected(self):
        with self.assertRaises(ValueError):
            _mirror(entry_style="pazarlık")


if __name__ == "__main__":
    unittest.main()
