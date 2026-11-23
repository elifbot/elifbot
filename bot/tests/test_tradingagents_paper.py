import importlib.util
import unittest

from bot.tradingagents_paper.paper import Instrument, PaperBook, accepts_signal
from bot.tradingagents_paper.run import direct_entry, fetch, instruments, quotes, signal


class PaperTests(unittest.TestCase):
    def test_long_and_short_pnl_and_stop(self):
        for direction, favorable, adverse in [(1, 102, 95), (-1, 98, 105)]:
            book = PaperBook()
            inst = Instrument('ETH-USDT-SWAP', .1, .01, .01)
            self.assertTrue(book.open(inst, 100, {inst.symbol: 100}, direction, now=1))
            p = next(iter(book.positions.values()))
            self.assertGreaterEqual(p['notional'], 450)
            self.assertLessEqual(p['notional'], 500)
            self.assertGreater(book.equity({inst.symbol: favorable}), book.cash)
            self.assertEqual(book.update(inst.symbol, 100, now=2), [])
            closed = book.update(inst.symbol, adverse, now=3)
            self.assertEqual(closed[0]['reason'], 'stop_sampled')
            self.assertLessEqual(closed[0]['net'], -10)
            self.assertAlmostEqual(book.cash - 1000, closed[0]['net'])

    def test_inverse_sizing_long_and_short(self):
        for direction in (1, -1):
            book = PaperBook()
            inst = Instrument('BTC-USD-SWAP', 100, 1, 1, ct_type='inverse', quote='USD')
            self.assertTrue(book.open(inst, 60000, {inst.symbol: 60000}, direction))
            self.assertEqual(next(iter(book.positions.values()))['contracts'], 5)
            close = book.close(next(iter(book.positions)), 60000 * (1 + direction * .02), 'test')
            self.assertGreater(close['net'], 0)
            self.assertAlmostEqual(book.cash - 1000, close['net'])

    def test_same_symbol_many_long_and_short_until_margin_runs_out(self):
        book = PaperBook()
        inst = Instrument('A-USDT-SWAP', .1, .01, .01)
        prices = {inst.symbol: 100}
        self.assertTrue(book.open(inst, 100, prices, 1))
        self.assertTrue(book.open(inst, 100, prices, 1))
        self.assertTrue(book.open(inst, 100, prices, -1))
        self.assertEqual(len(book.positions), 3)
        self.assertEqual({p['direction'] for p in book.positions.values()}, {1, -1})
        while book.open(inst, 100, prices, 1):
            pass
        self.assertGreater(len(book.positions), 3)
        self.assertEqual(book.events[-1]['event'], 'reject_margin')
        self.assertGreaterEqual(book.available(prices), 0)

    def test_insufficient_margin_and_coarse_contract(self):
        inst = Instrument('BTC-USDT-SWAP', .01, .01, .01)
        self.assertFalse(PaperBook(cash=10).open(inst, 60000, {inst.symbol: 60000}, 1))
        self.assertFalse(PaperBook().open(Instrument('X-USDT-SWAP', 100, 1, 1), 100, {}, -1))

    def test_directional_agent_approval(self):
        self.assertTrue(accepts_signal('Buy', 1))
        self.assertTrue(accepts_signal('Overweight', 1))
        self.assertTrue(accepts_signal('Sell', -1))
        self.assertTrue(accepts_signal('Underweight', -1))
        self.assertFalse(accepts_signal('Sell', 1))
        self.assertFalse(accepts_signal('Buy', -1))
        self.assertFalse(accepts_signal('REVIEW', -1))
        self.assertFalse(accepts_signal('Hold', 1))

    def test_signal_both_directions_and_warmup(self):
        self.assertEqual(signal([(0, 100), (60, 101)])['direction'], 1)
        self.assertEqual(signal([(0, 100), (60, 99)])['direction'], -1)
        self.assertIsNone(signal([(0, 100), (10, 101)]))
        self.assertIsNone(signal([(0, 100), (60, 100)]))

    def test_direct_entries_do_not_wait_for_model_or_deduplicate_symbol(self):
        book = PaperBook()
        inst = Instrument('A-USDT-SWAP', .1, .01, .01)
        prices, seen = {inst.symbol: 100}, {inst.symbol: 100}
        for direction in (1, 1, -1):
            opened, event = direct_entry(book, inst, 100, prices, seen, 100, 1900, {'direction': direction})
            self.assertTrue(opened)
            self.assertEqual(event['event'], 'open')
        self.assertEqual(len(book.positions), 3)
        self.assertEqual({p['direction'] for p in book.positions.values()}, {1, -1})
        opened, event = direct_entry(book, inst, 100, prices, seen, 121, 1900, {'direction': 1})
        self.assertFalse(opened)
        self.assertEqual(event['event'], 'reject_stale_portfolio')

    def test_batch_margin_matches_full_book_accounting(self):
        book = PaperBook(cash=1_000_000)
        inst = Instrument('A-USDT-SWAP', .1, .01, .01)
        prices, seen = {inst.symbol: 100}, {inst.symbol: 100}
        free_margin = book.available(prices)
        for direction in ([1, -1, 1] * 100):
            opened, event = direct_entry(book, inst, 100, prices, seen, 100, 1900,
                                         {'direction': direction}, False, free_margin)
            self.assertTrue(opened)
            p = book.positions[event['position_id']]
            free_margin -= p['margin'] + p['opening_fee'] + p['direction'] * (p['entry'] - 100) * p['units']
            self.assertAlmostEqual(free_margin, book.available(prices), places=5)
        self.assertEqual(len(book.by_symbol[inst.symbol]), 300)
        book.close(next(iter(book.positions)), 100, 'test')
        self.assertEqual(len(book.by_symbol[inst.symbol]), 299)

    def test_private_endpoint_cannot_be_used(self):
        with self.assertRaises(ValueError):
            fetch('/api/v5/trade/order')

    def test_all_futures_types_and_stale_quotes(self):
        base = {'state': 'live', 'ctVal': '0.1', 'lotSz': '0.01', 'minSz': '0.01', 'ctMult': '1'}
        rows = [dict(base, instId='ETH-USDT-SWAP', instType='SWAP', ctType='linear'),
                dict(base, instId='BTC-USD-SWAP', instType='SWAP', ctType='inverse'),
                dict(base, instId='ETH-USDC-261225', instType='FUTURES', ctType='linear'),
                dict(base, instId='ETH-EUR-261225', instType='FUTURES', ctType='linear'),
                dict(base, instId='GRVT-USD_UM_XPERP-310801', instType='FUTURES', ctType='linear', settleCcy='USD'),
                dict(base, instId='BTC-USD_UM-261127', instType='FUTURES', ctType='linear', settleCcy='USD')]
        got = instruments(rows)
        self.assertEqual(len(got), 6)
        self.assertTrue(got['GRVT-USD_UM_XPERP-310801'].supported)
        self.assertTrue(got['BTC-USD_UM-261127'].supported)
        self.assertTrue(got['BTC-USD-SWAP'].supported)
        self.assertTrue(got['ETH-USDC-261225'].supported)
        self.assertFalse(got['ETH-EUR-261225'].supported)
        ticker = {'instId': 'ETH-USDT-SWAP', 'last': '100', 'ts': '99000', 'volCcy24h': '12',
                  'open24h': '99', 'high24h': '110', 'low24h': '90'}
        self.assertIn('ETH-USDT-SWAP', quotes([ticker], 100))
        self.assertEqual(quotes([ticker], 121), {})

    def test_liquidation_closes_entire_book(self):
        book = PaperBook()
        inst = Instrument('A-USDT-SWAP', .1, .01, .01)
        book.open(inst, 100, {inst.symbol: 100}, -1)
        book.cash = 0
        self.assertTrue(book.liquidation({inst.symbol: 101}))
        self.assertEqual(book.closed[-1]['reason'], 'cross_liquidation_approx')


@unittest.skipUnless(importlib.util.find_spec('tradingagents'), 'optional TradingAgents not installed')
class AgentTests(unittest.TestCase):
    def test_upstream_graph_uses_supplied_market_snapshot(self):
        from langchain_core.messages import AIMessage
        from bot.tradingagents_paper.agents import create_graph, decide

        class FakeLLM:
            def with_structured_output(self, *args, **kwargs):
                raise NotImplementedError()
            def invoke(self, *args, **kwargs):
                return AIMessage(content='Rating: Buy\nBased on provided data.')

        graph = create_graph('unused', FakeLLM())
        rating, decision, report = decide(graph, 'ETH-USDT-SWAP', 'ONLY_OKX_DATA')
        self.assertEqual(rating, 'Buy')
        self.assertIn('ONLY_OKX_DATA', report)
        self.assertIn('Rating: Buy', decision)


if __name__ == '__main__':
    unittest.main()
