"""Sadece bellek içi vadeli paper defteri; hiçbir gerçek emir göndermez."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str
    ct_val: float
    lot: float
    minimum: float
    ct_type: str = 'linear'
    quote: str = 'USDT'
    expiry_ms: int = 0
    multiplier: float = 1.0

    @property
    def supported(self):
        return self.ct_type in ('linear', 'inverse') and self.quote in ('USD', 'USDT', 'USDC')


class PaperBook:
    """Aynı sözleşmede birden fazla LONG/SHORT sanal girişe izin verir.

    Her sinyal pozisyonu ayrı muhasebeleştirilir; gerçek OKX hedge/net pozisyon
    birleşmesi değildir. İşlem sayısı sınırı yoktur, teminat ve fizik sınırları vardır.
    """
    def __init__(self, cash=1000.0, margin=50.0, leverage=10, fee=0.0005, slippage=0.0005):
        self.initial = self.cash = cash
        self.margin, self.leverage, self.fee, self.slippage = margin, leverage, fee, slippage
        self.positions = {}
        self.by_symbol = {}
        self.closed = []
        self.events = []
        self.sequence = 0

    def equity(self, prices):
        return self.cash + sum(p['direction'] * (prices.get(p['symbol'], p['entry']) - p['entry']) * p['units']
                               for p in self.positions.values())

    def available(self, prices):
        return self.equity(prices) - sum(p['margin'] for p in self.positions.values())

    def open(self, inst, price, prices, direction, now=None, available_margin=None):
        now = time.time() if now is None else now
        if direction not in (1, -1):
            raise ValueError('direction must be 1 (LONG) or -1 (SHORT)')
        if price <= 0 or not math.isfinite(price):
            self.events.append({'event': 'reject_invalid_price', 'symbol': inst.symbol, 'ts': now})
            return False
        if not inst.supported or min(inst.ct_val, inst.lot, inst.minimum, inst.multiplier) <= 0:
            self.events.append({'event': 'reject_unsupported_contract', 'symbol': inst.symbol, 'ts': now})
            return False
        if inst.expiry_ms and inst.expiry_ms / 1000 <= now + 60:
            self.events.append({'event': 'reject_expiring', 'symbol': inst.symbol, 'ts': now})
            return False
        fill = price * (1 + direction * self.slippage)
        target = self.margin * self.leverage
        contract_value = inst.ct_val * inst.multiplier
        per_contract = contract_value if inst.ct_type == 'inverse' else contract_value * fill
        contracts = math.floor((target / per_contract) / inst.lot + 1e-12) * inst.lot
        notional = contracts * per_contract
        units = notional / fill
        if contracts + 1e-12 < inst.minimum or notional < target * .90 or notional > target * 1.000001:
            self.events.append({'event': 'reject_size', 'symbol': inst.symbol, 'notional': notional, 'ts': now})
            return False
        opening_fee, margin = notional * self.fee, notional / self.leverage
        if (self.available(prices) if available_margin is None else available_margin) < margin + opening_fee:
            self.events.append({'event': 'reject_margin', 'symbol': inst.symbol, 'ts': now})
            return False
        self.cash -= opening_fee
        self.sequence += 1
        position_id = f'{inst.symbol}#{self.sequence}'
        self.positions[position_id] = {'symbol': inst.symbol, 'position_id': position_id, 'entry': fill,
            'units': units, 'contracts': contracts, 'direction': direction, 'ct_type': inst.ct_type,
            'notional': notional, 'margin': margin, 'opening_fee': opening_fee, 'opened': now}
        self.by_symbol.setdefault(inst.symbol, set()).add(position_id)
        self.events.append({'event': 'open', 'position_id': position_id,
                            'direction': 'LONG' if direction == 1 else 'SHORT', 'symbol': inst.symbol,
                            'price': fill, 'contracts': contracts, 'notional': notional, 'fee': opening_fee, 'ts': now})
        return True

    def close(self, position_id, price, reason, now=None):
        now = time.time() if now is None else now
        p = self.positions.get(position_id)
        if p is None or price <= 0 or not math.isfinite(price):
            return None
        fill = price * (1 - p['direction'] * self.slippage)
        exit_notional = p['notional'] if p['ct_type'] == 'inverse' else p['units'] * fill
        fee = exit_notional * self.fee
        gross = p['direction'] * (fill - p['entry']) * p['units']
        net = gross - fee - p['opening_fee']
        self.cash += gross - fee
        row = {'event': 'close', 'symbol': p['symbol'], 'position_id': position_id,
               'direction': 'LONG' if p['direction'] == 1 else 'SHORT', 'price': fill,
               'entry': p['entry'], 'net': net, 'reason': reason, 'ts': now, 'opened': p['opened']}
        self.closed.append(row)
        self.events.append(row)
        del self.positions[position_id]
        self.by_symbol[p['symbol']].remove(position_id)
        if not self.by_symbol[p['symbol']]:
            del self.by_symbol[p['symbol']]
        return row

    def update(self, symbol, price, now=None):
        closed = []
        for pid in list(self.by_symbol.get(symbol, ())):
            p = self.positions[pid]
            exit_price = price * (1 - p['direction'] * self.slippage)
            exit_notional = p['notional'] if p['ct_type'] == 'inverse' else exit_price * p['units']
            net = p['direction'] * (exit_price - p['entry']) * p['units'] - p['opening_fee'] - exit_notional * self.fee
            if net <= -10:
                row = self.close(pid, price, 'stop_sampled', now)
                if row:
                    closed.append(row)
        return closed

    def liquidation(self, prices, now=None):
        if not self.positions or any(p['symbol'] not in prices for p in self.positions.values()):
            return False
        maintenance = sum((p['notional'] if p['ct_type'] == 'inverse' else p['units'] * prices[p['symbol']]) * .005
                          for p in self.positions.values())
        if self.equity(prices) > maintenance:
            return False
        for pid, p in list(self.positions.items()):
            self.close(pid, prices[p['symbol']], 'cross_liquidation_approx', now)
        return True

    def position_snapshot(self, prices, seen, now, limit=None):
        result = []
        for pid, p in self.positions.items():
            if limit is not None and len(result) >= limit:
                break
            symbol = p['symbol']
            mark = prices.get(symbol)
            age = max(0.0, now - seen[symbol]) if symbol in seen else None
            net = None
            if mark is not None and age is not None and age <= 20:
                exit_price = mark * (1 - p['direction'] * self.slippage)
                exit_notional = p['notional'] if p['ct_type'] == 'inverse' else p['units'] * exit_price
                net = (p['direction'] * (exit_price - p['entry']) * p['units']
                       - p['opening_fee'] - exit_notional * self.fee)
            result.append({'position_id': pid, 'symbol': symbol,
                           'direction': 'LONG' if p['direction'] == 1 else 'SHORT',
                           'entry': p['entry'], 'mark': mark, 'mark_age_seconds': age,
                           'net_if_closed': net, 'notional': p['notional'], 'opened': p['opened']})
        return result

    def summary(self, prices):
        return {'initial_usd': self.initial, 'cash_usd': self.cash, 'equity_usd': self.equity(prices),
                'net_usd': self.equity(prices) - self.initial, 'closed_count': len(self.closed),
                'wins': sum(1 for row in self.closed if row['net'] > 0),
                'positions': self.positions, 'closed': self.closed, 'events': self.events,
                'assumptions': 'multiple simulated LONG/SHORT entries; USD/USDT/USDC assumed 1 USD; 0.05% taker and 0.05% slippage per side; sampled stop; approximate cross maintenance 0.5%; no funding'}


def accepts_signal(rating, direction):
    return ((direction == 1 and rating in ('Buy', 'Overweight')) or
            (direction == -1 and rating in ('Sell', 'Underweight')))
