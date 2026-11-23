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
        # USD, USDT and USDC are approximated at one USD in this paper account.
        return self.ct_type in ('linear', 'inverse') and self.quote in ('USD', 'USDT', 'USDC')


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
        return self.cash + sum(p['direction'] * (prices.get(s, p['entry']) - p['entry']) * p['units']
                               for s, p in self.positions.items())

    def available(self, prices):
        return self.equity(prices) - sum(p['margin'] for p in self.positions.values())

    def open(self, inst, price, prices, direction, now=None):
        now = time.time() if now is None else now
        if direction not in (1, -1):
            raise ValueError('direction must be 1 (LONG) or -1 (SHORT)')
        if inst.symbol in self.positions or price <= 0 or not math.isfinite(price):
            return False
        if not inst.supported or min(inst.ct_val, inst.lot, inst.minimum, inst.multiplier) <= 0:
            self.events.append({'event': 'reject_unsupported_contract', 'symbol': inst.symbol, 'ts': now})
            return False
        # An expiring contract cannot be opened if the simulation cannot
        # represent its exchange settlement. Prevent unmodeled expiry.
        if inst.expiry_ms and inst.expiry_ms / 1000 <= now + 60:
            self.events.append({'event': 'reject_expiring', 'symbol': inst.symbol, 'ts': now})
            return False
        fill = price * (1 + direction * self.slippage)
        target = self.margin * self.leverage
        contract_value = inst.ct_val * inst.multiplier
        per_contract = contract_value if inst.ct_type == 'inverse' else contract_value * fill
        lots = math.floor((target / per_contract) / inst.lot + 1e-12)
        contracts = lots * inst.lot
        notional = contracts * per_contract
        # USD-equivalent at entry. Inverse PnL translated from coin to USD is
        # direction * contract_USD * (exit/entry - 1).
        units = notional / fill
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
                                       'direction': direction, 'ct_type': inst.ct_type,
                                       'notional': notional, 'margin': margin,
                                       'opening_fee': opening_fee, 'opened': now}
        self.events.append({'event': 'open', 'direction': 'LONG' if direction == 1 else 'SHORT',
                            'symbol': inst.symbol, 'price': fill, 'contracts': contracts,
                            'notional': notional, 'fee': opening_fee, 'ts': now})
        return True

    def close(self, symbol, price, reason, now=None):
        now = time.time() if now is None else now
        p = self.positions.get(symbol)
        if p is None or price <= 0 or not math.isfinite(price):
            return None
        fill = price * (1 - p['direction'] * self.slippage)
        exit_notional = p['notional'] if p['ct_type'] == 'inverse' else p['units'] * fill
        fee = exit_notional * self.fee
        gross = p['direction'] * (fill - p['entry']) * p['units']
        net = gross - fee - p['opening_fee']
        self.cash += gross - fee
        row = {'event': 'close', 'symbol': symbol, 'direction': 'LONG' if p['direction'] == 1 else 'SHORT',
               'price': fill, 'entry': p['entry'], 'net': net, 'reason': reason,
               'ts': now, 'opened': p['opened']}
        self.closed.append(row)
        self.events.append(row)
        del self.positions[symbol]
        return row

    def update(self, symbol, price, now=None):
        p = self.positions.get(symbol)
        if p is None:
            return None
        exit_price = price * (1 - p['direction'] * self.slippage)
        exit_notional = p['notional'] if p['ct_type'] == 'inverse' else exit_price * p['units']
        net = p['direction'] * (exit_price - p['entry']) * p['units'] - p['opening_fee'] - exit_notional * self.fee
        if net <= -10:
            return self.close(symbol, price, 'stop_sampled', now)
        return None

    def liquidation(self, prices, now=None):
        if not self.positions or any(s not in prices for s in self.positions):
            return False
        maintenance = sum((p['notional'] if p['ct_type'] == 'inverse' else p['units'] * prices[s]) * .005
                          for s, p in self.positions.items())
        if self.equity(prices) > maintenance:
            return False
        for symbol in list(self.positions):
            self.close(symbol, prices[symbol], 'cross_liquidation_approx', now)
        return True

    def summary(self, prices):
        wins = sum(1 for row in self.closed if row['net'] > 0)
        return {'initial_usd': self.initial, 'cash_usd': self.cash, 'equity_usd': self.equity(prices),
                'net_usd': self.equity(prices) - self.initial, 'closed_count': len(self.closed),
                'wins': wins, 'positions': self.positions, 'closed': self.closed, 'events': self.events,
                'assumptions': 'LONG and SHORT; USD/USDT/USDC assumed 1 USD; 0.05% taker and 0.05% slippage per side; sampled stop; approximate cross maintenance 0.5%; no funding'}


def accepts_signal(rating, direction):
    # Explicit adapter for upstream spot-oriented ratings, not a claim that the
    # upstream Sell rating itself opens a short. Only a matching directional
    # signal is approved; Hold, REVIEW and conflicts never trade.
    return ((direction == 1 and rating in ('Buy', 'Overweight')) or
            (direction == -1 and rating in ('Sell', 'Underweight')))
