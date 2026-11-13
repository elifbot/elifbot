"""Explicit simulated exchange wiring for legacy order-mechanics tests only.

The test configuration intentionally allows the 5m timeframe with proof off;
this is NOT a production default. Fresh safety tests use the real guard.
"""
from dataclasses import replace
from unittest.mock import Mock

from core.config import SuperConfig
from live.sync import LiveMirror

FAKE_INFO = {'symbols': [{'symbol': 'BTCUSDT', 'filters': [
    {'filterType': 'PRICE_FILTER', 'tickSize': '0.1'},
    {'filterType': 'LOT_SIZE', 'stepSize': '0.001', 'minQty': '0.001'},
    {'filterType': 'MIN_NOTIONAL', 'notional': '5'},
]}]}


def mechanical_mirror(*args, **kwargs):
    cfg = replace(SuperConfig().v2.live, enabled=True,
                  live_allowed_timeframes=('5m',), live_requires_edge_proof=False)
    kwargs.setdefault('entry_timeframe', '5m')
    kwargs.setdefault('live_cfg', cfg)
    kwargs.setdefault('state_saver', lambda _state: None)
    kwargs.setdefault('state_loader', lambda: {})
    broker = kwargs.get('binance') or (args[0] if args else None)
    if isinstance(broker, Mock):
        broker.client.public_request.return_value.as_dict.return_value = FAKE_INFO
    elif broker is not None and hasattr(broker.client.transport, 'routes'):
        broker.client.transport.routes['/fapi/v1/exchangeInfo'] = FAKE_INFO
    return LiveMirror(*args, **kwargs)
