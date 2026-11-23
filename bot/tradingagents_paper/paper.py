"""OKX genel piyasa verisi + yalnızca bellek içi paper işlemler.

Bu modülde kimlik doğrulama, özel API uçları veya gerçek borsa emri yoktur.
Fiyatlar periyodik örneklenir; bu bir borsa emir defteri simülasyonu değildir.
"""
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


class PaperBook:
    def __init__(self, cash=1000.0, margin=50.0, leverage=10, fee=0.0005, slippage=0.0005):
        self.initial = self.cash = cash
        self.margin = margin
        self.leverage = leverage
        self.fee = fee
        self.slippage = slippage
        self.positions = {}
        self.closed = []
        self.events = []

    def equity(self, prices):
        return self.cash + sum((prices.get(s, p['entry']) - p['entry']) * p['units']
                               for s, p in self.positions.items())

    def available(self, prices):
        return self.equity(prices) - sum(p['margin'] for p in self.positions.values())

    def open_long(self, inst, price, prices, now=None):
        now = time.time() if now is None else now
        if inst.symbol in self.positions or price <= 0 or not math.isfinite(price):
            return False
        if min(inst.ct_val, inst.lot, inst.minimum) <= 0:
            return False
        fill = price * (1 + self.slippage)
        target = self.margin * self.leverage
        lots = math.floor((target / (fill * inst.ct_val)) / inst.lot + 1e-12)
        contracts = lots * inst.lot
        units = contracts * inst.ct_val
        notional = units * fill
        if contracts + 1e-12 < inst.minimum or notional < target * .90 or notional > target * 1.000001:
            self.events.append({'event': 'reject_size', 'symbol': inst.symbol, 'notional': notional, 'ts': now})
            return False
        opening_fee = notional * self.fee
        margin = notional / self.leverage
        if self.available(prices) < margin + opening_fee:
            self.events.append({'event': 'reject_margin', 'symbol': inst.symbol, 'ts': now})
            return False
        self.cash -= opening_fee
        self.positions[inst.symbol] = {'entry': fill, 'units': units, 'contracts': contracts,
                                       'margin': margin, 'opening_fee': opening_fee, 'opened': now}
        self.events.append({'event': 'open_long', 'symbol': inst.symbol, 'price': fill,
                            'contracts': contracts, 'notional': notional, 'fee': opening_fee, 'ts': now})
        return True

    def close(self, symbol, price, reason, now=None):
        now = time.time() if now is None else now
        p = self.positions.get(symbol)
        if p is None or price <= 0 or not math.isfinite(price):
            return None
        fill = price * (1 - self.slippage)
        fee = p['units'] * fill * self.fee
        gross = (fill - p['entry']) * p['units']
        net = gross - fee - p['opening_fee']
        self.cash += gross - fee
        row = {'event': 'close', 'symbol': symbol, 'price': fill, 'entry': p['entry'],
               'net': net, 'reason': reason, 'ts': now, 'opened': p['opened']}
        self.closed.append(row)
        self.events.append(row)
        del self.positions[symbol]
        return row

    def update(self, symbol, price, now=None):
        p = self.positions.get(symbol)
        if p is None:
            return None
        # Mark-to-close includes both fees and assumed exit slippage. Sampling may
        # skip the threshold; -10 USD is a trigger, not a guaranteed loss limit.
        exit_price = price * (1 - self.slippage)
        net = (exit_price - p['entry']) * p['units'] - p['opening_fee'] - exit_price * p['units'] * self.fee
        if net <= -10:
            return self.close(symbol, price, 'stop_sampled', now)
        return None

    def liquidation(self, prices, now=None):
        if not self.positions or any(s not in prices for s in self.positions):
            return False
        maintenance = sum(p['units'] * prices[s] * .005 for s, p in self.positions.items())
        if self.equity(prices) > maintenance:
            return False
        for symbol in list(self.positions):
            self.close(symbol, prices[symbol], 'cross_liquidation_approx', now)
        return True

    def summary(self, prices):
        wins = sum(1 for row in self.closed if row['net'] > 0)
        return {'initial_usd': self.initial, 'cash_usd': self.cash, 'equity_usd': self.equity(prices),
                'net_usd': self.equity(prices) - self.initial, 'closed_count': len(self.closed),
                'wins': wins, 'positions': self.positions, 'closed': self.closed,
                'events': self.events, 'assumptions': 'LONG-only; 0.05% taker/side; 0.05% slippage/side; sampled stop; approximate cross maintenance 0.5%; funding not modelled'}


def rating_action(rating):
    # Upstream Sell/Underweight means reduce/exit, not a futures short signal.
    if rating == 'Buy':
        return 'open_long'
    if rating in ('Sell', 'Underweight'):
        return 'close'
    return 'hold'
