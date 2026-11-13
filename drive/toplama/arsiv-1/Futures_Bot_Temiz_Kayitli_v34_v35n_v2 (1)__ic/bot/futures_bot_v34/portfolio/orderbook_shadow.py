"""Salt-gözlem order-book derinlik tahmini; gerçek emir veya dolum garantisi yok."""
from __future__ import annotations

import math
import time
import aiohttp
from data.feed_utils import ensure_url_allowed


def _levels(raw, factor):
    out = []
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError('gecersiz kontrat carpani')
    for level in raw:
        price, qty = float(level[0]), float(level[1]) * factor
        if not math.isfinite(price) or not math.isfinite(qty) or price <= 0 or qty <= 0:
            continue
        out.append((price, qty))
    return out


def measure(bids_raw, asks_raw, side, notional_usd, *, factor=1.0):
    """Gözlenen seviyeleri yürü; marj/kaldıraç değil, hedef USD notional alır.

    BUY ask, SELL bid tüketir. Veri anlık snapshot'tır; kuyruk, iptal, gecikme
    ve gizli emir modellenmez. Yetersiz derinlikte tam dolum uydurulmaz.
    """
    if side not in ('LONG', 'SHORT') or not math.isfinite(notional_usd) or notional_usd <= 0:
        raise ValueError('gecersiz yon veya notional')
    bids = sorted(_levels(bids_raw, factor), reverse=True)
    asks = sorted(_levels(asks_raw, factor))
    if not bids or not asks or bids[0][0] >= asks[0][0]:
        raise ValueError('bos veya capraz emir defteri')
    bid, ask = bids[0][0], asks[0][0]
    mid = (bid + ask) / 2
    target_qty = notional_usd / mid
    remain = target_qty
    filled = 0.0
    cost = 0.0
    for px, qty in (asks if side == 'LONG' else bids):
        take = min(remain, qty)
        filled += take
        cost += take * px
        remain -= take
        if remain <= target_qty * 1e-12:
            break
    vwap = cost / filled if filled else None
    return {'bid': bid, 'ask': ask, 'mid': mid,
            'spread_pct': (ask - bid) / mid * 100,
            'target_qty': target_qty, 'filled_qty': filled,
            'fill_fraction': min(1.0, filled / target_qty),
            'vwap': vwap,
            'adverse_pct': ((vwap / mid - 1) * 100 if side == 'LONG'
                            else (1 - vwap / mid) * 100) if vwap is not None else None,
            'complete': remain <= target_qty * 1e-12}


async def snapshot(session, exchange, symbol, side, notional_usd, *, factor=1.0,
                   now_ms=None, max_age_ms=5000):
    if exchange == 'binance':
        url = 'https://www.binance.com/fapi/v1/depth'
        params = {'symbol': symbol, 'limit': 50}
    elif exchange == 'okx':
        url = 'https://www.okx.com/api/v5/market/books'
        params = {'instId': symbol, 'sz': '50'}
    else:
        raise ValueError('desteklenmeyen borsa')
    ensure_url_allowed(url)
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=False) as r:
        r.raise_for_status()
        body = await r.json()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if exchange == 'okx':
        if body.get('code') != '0' or not body.get('data'):
            raise ValueError('OKX defter yaniti gecersiz')
        book = body['data'][0]
        timestamp = int(book['ts'])
    else:
        book = body
        timestamp = int(body.get('E', body.get('T', 0)))
    if timestamp <= 0 or now - timestamp > max_age_ms or timestamp - now > max_age_ms:
        raise ValueError('defter zaman damgasi bayat veya gecersiz')
    result = measure(book['bids'], book['asks'], side, notional_usd, factor=factor)
    result['ts_ms'] = timestamp
    result['age_ms'] = now - timestamp
    return result
