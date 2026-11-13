"""Test-only paper helpers. No real broker, keys, network or production use.

Seeding is intentionally explicit; these calls are NOT an atomic production
migration/recovery algorithm. Use only with isolated, new test databases.
"""
from __future__ import annotations

import time
from src.exchanges import PaperBroker
from src.state_store import StateStore


class FixturePaperBroker:
    mode = 'paper'
    primary = 'binance'
    paper_realistic = False

    def __init__(self, balance=1000.0, fee_pct=0.0):
        self.paper = PaperBroker(balance_usdt=balance, fee_taker_pct=fee_pct,
                                 fee_maker_pct=fee_pct)
        self.entry = None
        self.market_calls = []
        self.prices = {}

    async def fetch_balance_usdt(self):
        return self.paper.balance

    async def best_price(self, symbol, side):
        return self.primary, float(self.prices.get(symbol, 100.0))

    async def fetch_bid_ask(self, symbol, exchange=None):
        return 99.98, 100.02

    async def execute_entry(self, symbol, side, qty, **kw):
        self.entry = {'qty': qty, **kw}
        # Unlike a fabricated fill, this updates the paper position and fees.
        return self.paper.market_order(symbol, side, qty,
                                       float(kw.get('price_hint', 100.0)),
                                       exchange=kw.get('exchange') or self.primary)

    async def market_order(self, symbol, side, qty, **kw):
        self.market_calls.append({'symbol': symbol, 'side': side, 'qty': qty, **kw})
        return self.paper.market_order(symbol, side, qty,
                                       float(kw.get('price_hint', 100.0)),
                                       exchange=kw.get('exchange') or self.primary,
                                       reduce_only=kw.get('reduce_only', False))

    async def place_protection(self, *args, **kwargs):
        return {'native': False, 'kind': 'bot'}

    async def cancel_protection(self, *args, **kwargs):
        return True

    async def fetch_open_positions(self):
        return None


def make_paper_broker(balance=1000.0, fee_pct=0.0):
    return FixturePaperBroker(balance=balance, fee_pct=fee_pct)


def seed_paper_state(store: StateStore, positions: dict, balance=1000.0, *,
                     start_balance=None, entry_fees=None, funding=None):
    """Seed a NEW test DB. Fees/funding must be deliberately provided.

    Call before Executor construction so restore synchronizes broker positions.
    Never call on a real or existing account; never use for reconciliation.
    """
    if (store.paper_requires_recovery() or store.load_positions()
            or store.get_meta('paper_account', None) is not None):
        raise ValueError('seed_paper_state needs a fresh test database')
    entry_fees = entry_fees or {}
    funding = funding or {}
    now = time.time()
    account = {'balance': float(balance),
               'start_balance': float(balance if start_balance is None else start_balance),
               'total_fees_usdt': sum(float(entry_fees.get(s, 0.0)) for s in positions),
               'total_funding_usdt': sum(float(funding.get(s, 0.0)) for s in positions),
               'realistic_execution': False}
    meta = {}
    for sym, pos in positions.items():
        if sym != pos.symbol:
            raise ValueError('position symbol mismatch')
        store.save_position(pos)
        meta[sym] = {'position_id': f'test-{sym}', 'opened_ts': now,
                     'entry_context': {'side': pos.side},
                     'entry_fee_usdt': float(entry_fees.get(sym, 0.0)),
                     'funding_usdt': float(funding.get(sym, 0.0))}
    store.set_meta('paper_account', account)
    store.set_meta('position_meta', meta)
    store.set_meta('paper_funding_clock', {sym: now for sym in positions})
