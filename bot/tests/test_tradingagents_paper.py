import importlib.util
import unittest

from bot.tradingagents_paper.paper import Instrument, PaperBook, rating_action
from bot.tradingagents_paper.run import fetch, instruments, quotes


class PaperTests(unittest.TestCase):
    def test_size_fee_and_stop(self):
        book = PaperBook()
        inst = Instrument('ETH-USDT-SWAP', .1, .01, .01)
        self.assertTrue(book.open_long(inst, 100, {inst.symbol: 100}, now=1))
        p = book.positions[inst.symbol]
        self.assertGreaterEqual(p['units'] * p['entry'], 450)
        self.assertLessEqual(p['units'] * p['entry'], 500)
        self.assertLess(book.cash, 1000)
        self.assertIsNone(book.update(inst.symbol, 100, now=2))
        closed = book.update(inst.symbol, 95, now=3)
        self.assertEqual(closed['reason'], 'stop_sampled')
        self.assertLessEqual(closed['net'], -10)
        self.assertAlmostEqual(book.cash - 1000, closed['net'])
        self.assertEqual(len(book.positions), 0)

    def test_insufficient_margin_and_coarse_contract(self):
        inst = Instrument('BTC-USDT-SWAP', .01, .01, .01)
        self.assertFalse(PaperBook(cash=10).open_long(inst, 60000, {inst.symbol: 60000}))
        self.assertFalse(PaperBook().open_long(Instrument('X-USDT-SWAP', 100, 1, 1), 100, {}))

    def test_long_only_mapping(self):
        self.assertEqual(rating_action('Buy'), 'open_long')
        self.assertEqual(rating_action('Sell'), 'close')
        self.assertEqual(rating_action('Underweight'), 'close')
        self.assertEqual(rating_action('REVIEW'), 'hold')
        self.assertEqual(rating_action('Overweight'), 'hold')

    def test_private_endpoint_cannot_be_used(self):
        with self.assertRaises(ValueError):
            fetch('/api/v5/trade/order')

    def test_instruments_and_stale_quotes(self):
        row = {'instId': 'ETH-USDT-SWAP', 'state': 'live', 'ctType': 'linear', 'settleCcy': 'USDT',
               'ctVal': '0.1', 'lotSz': '0.01', 'minSz': '0.01'}
        self.assertIn('ETH-USDT-SWAP', instruments([row]))
        row['ctType'] = 'inverse'
        self.assertEqual(instruments([row]), {})
        ticker = {'instId': 'ETH-USDT-SWAP', 'last': '100', 'ts': '99000', 'volCcy24h': '12',
                  'open24h': '99', 'high24h': '110', 'low24h': '90'}
        self.assertEqual(quotes([ticker], 100)['ETH-USDT-SWAP']['volume_usd'], 1200)
        self.assertEqual(quotes([ticker], 121), {})

    def test_liquidation_closes_entire_book(self):
        book = PaperBook()
        inst = Instrument('A-USDT-SWAP', .1, .01, .01)
        book.open_long(inst, 100, {inst.symbol: 100})
        book.cash = 0
        self.assertTrue(book.liquidation({inst.symbol: 99}))
        self.assertEqual(book.closed[-1]['reason'], 'cross_liquidation_approx')


@unittest.skipUnless(importlib.util.find_spec('tradingagents'), 'optional TradingAgents not installed')
class AgentTests(unittest.TestCase):
    def test_upstream_graph_uses_only_supplied_market_snapshot(self):
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
