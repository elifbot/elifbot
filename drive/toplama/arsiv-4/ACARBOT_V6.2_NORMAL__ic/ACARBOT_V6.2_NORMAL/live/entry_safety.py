"""Fail-closed exchange instrument validation for *new* mirrored exposure.

Uses public metadata of the selected exchange, not a spot proxy. Never rounds
up, silently invents missing filters, or sends an order. Does not affect
reduce-only exits / protective stops. Exchange still enforces other rules;
metadata may change after verification and this is not an execution guarantee.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


class EntrySafetyError(ValueError):
    """Missing/invalid exchange metadata or off-grid new order."""


def _number(value, name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise EntrySafetyError(f'{name}: geçersiz değer') from exc
    if not result.is_finite() or result <= 0:
        raise EntrySafetyError(f'{name}: pozitif ve sonlu olmalı')
    return result


def _grid(value, step, name):
    v, unit = _number(value, name), _number(step, name + ' adımı')
    # Decimal(str(x)) avoids binary float noise; tiny representational noise
    # is tolerated in units of step, not half a tick.
    ratio = v / unit
    if abs(ratio - ratio.to_integral_value()) > Decimal('0.00000001'):
        raise EntrySafetyError(f'{name}: borsa adımına hizalı değil')
    return v


def check_new_entry(adapter, venue, symbol, side, quantity, *, stop=None, limit=None):
    if side not in ('LONG', 'SHORT') or not symbol:
        raise EntrySafetyError('Sembol veya yön geçersiz')
    amount = _number(quantity, 'miktar')
    if stop is not None:
        _number(stop, 'stop')
    if limit is not None:
        _number(limit, 'fiyat')
        if stop is not None and ((side == 'LONG' and stop >= limit) or
                                 (side == 'SHORT' and stop <= limit)):
            raise EntrySafetyError('Stop giriş fiyatının yanlış tarafında')
    try:
        if venue == 'binance':
            data = adapter.client.public_request('/fapi/v1/exchangeInfo', {'symbol': symbol}).as_dict()
            matches = [r for r in (data.get('symbols') or []) if r.get('symbol') == symbol]
            if len(matches) != 1:
                raise EntrySafetyError('Vadeli sembol metadata doğrulanamadı')
            fs = {x.get('filterType'): x for x in matches[0].get('filters', [])}
            if matches[0].get('status') not in (None, 'TRADING'):
                raise EntrySafetyError('Sembol işlemde değil')
            price_filter, lot = fs.get('PRICE_FILTER', {}), fs.get('LOT_SIZE', {})
            tick = _number(price_filter.get('tickSize'), 'tickSize')
            step = _number(lot.get('stepSize'), 'stepSize')
            minimum = _number(lot.get('minQty'), 'minQty')
            _grid(amount, step, 'miktar')
            if amount < minimum:
                raise EntrySafetyError('Miktar minQty altında')
            if stop is not None:
                _grid(stop, tick, 'stop fiyatı')
            if limit is not None:
                _grid(limit, tick, 'limit fiyatı')
            # If market lot rules exist with non-zero step, respect them too.
            market = fs.get('MARKET_LOT_SIZE', {})
            if market and _number(market.get('stepSize'), 'market stepSize'):
                _grid(amount, market['stepSize'], 'market miktarı')
                if amount < _number(market.get('minQty'), 'market minQty'):
                    raise EntrySafetyError('Miktar market minQty altında')
            if limit is not None and fs.get('MIN_NOTIONAL'):
                notional = _number(fs['MIN_NOTIONAL'].get('notional'), 'minNotional')
                if amount * _number(limit, 'fiyat') < notional:
                    raise EntrySafetyError('Miktar minNotional altında')
            # The execution adapter must use this same freshly verified grid,
            # not stale cache or its historical all-zero fallback.
            cache = getattr(adapter, '_filters', None)
            if isinstance(cache, dict):
                from live.broker_clients import SymbolFilters
                min_notional = fs.get('MIN_NOTIONAL', {}).get('notional', '0')
                cache[symbol] = SymbolFilters(float(tick), float(step), float(minimum),
                                              float(min_notional))
        elif venue == 'okx':
            data = adapter.client.public_request('/api/v5/public/instruments',
                    {'instType': 'SWAP', 'instId': symbol}).as_dict()
            rows = [r for r in (data.get('data') or []) if r.get('instId') == symbol]
            if len(rows) != 1:
                raise EntrySafetyError('SWAP enstrüman metadata doğrulanamadı')
            row = rows[0]
            if row.get('state') not in (None, 'live'):
                raise EntrySafetyError('Enstrüman işlemde değil')
            tick = _number(row.get('tickSz'), 'tickSz')
            lot = _number(row.get('lotSz'), 'lotSz')
            min_size = _number(row.get('minSz'), 'minSz')
            contract = _number(row.get('ctVal'), 'ctVal')
            contracts = amount / contract
            _grid(contracts, lot, 'kontrat miktarı')
            if contracts < min_size:
                raise EntrySafetyError('Kontrat miktarı minSz altında')
            if stop is not None:
                _grid(stop, tick, 'stop fiyatı')
            if limit is not None:
                _grid(limit, tick, 'limit fiyatı')
            cache = getattr(adapter, '_instruments', None)
            if isinstance(cache, dict):
                cache[symbol] = {'tickSz': float(tick), 'lotSz': float(lot),
                                 'minSz': float(min_size), 'ctVal': float(contract)}
        else:
            raise EntrySafetyError('Borsa doğrulanamadı')
    except EntrySafetyError:
        raise
    except Exception as exc:
        raise EntrySafetyError(f'Borsa metadata okunamadı: {type(exc).__name__}') from exc
