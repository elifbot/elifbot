import importlib.util
import unittest
from unittest.mock import patch

from panel.tradingagents_server import parse_annotations, technical_rehearsal


class PanelTests(unittest.TestCase):
    def test_annotations_use_observed_not_estimated_numbers(self):
        data = [
            {'title': 'OKX evreni', 'message': '839 aktif sözleşme; 558 paper uyumlu'},
            {'title': 'Paper ilerleme', 'message': '33sn; taze=839/839, sinyal=10, kuyruk=9, eski=0, karar=0'},
            {'title': 'Paper ilerleme', 'message': '265sn; taze=839/839, sinyal=578, kuyruk=577, eski=0, karar=0'},
            {'title': 'Paper sonuç', 'message': 'Karar=0, geçerli=0, kullanılabilir=0, kapanan=0, açık=0, özkaynak=1000.00 USD'},
            {'title': 'TradingAgents model hatası', 'message': 'OpenAITimeoutError: Request timed out.'},
        ]
        m, errors, progress = parse_annotations(data)
        self.assertEqual(m['universe'], 839)
        self.assertEqual(m['supported'], 558)
        self.assertEqual(m['signals_at_least'], 578)
        self.assertEqual(m['decisions'], 0)
        self.assertEqual(m['closed'], 0)
        self.assertEqual(m['open'], 0)
        self.assertEqual(m['equity_usd'], 1000)
        self.assertEqual(progress[-1]['seconds'], 265)
        self.assertIn('OpenAITimeoutError', errors[0])

    def test_missing_data_stays_unknown(self):
        m, errors, progress = parse_annotations([])
        self.assertIsNone(m['universe'])
        self.assertIsNone(m['decisions'])
        self.assertIsNone(m['closed'])
        self.assertFalse(progress)

    @unittest.skipUnless(importlib.util.find_spec('tradingagents'), 'optional TradingAgents not installed')
    def test_rehearsal_is_isolated_and_exercises_both_directions(self):
        # Any real HTTP access would contradict the offline test's promise.
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
            result = technical_rehearsal()
        self.assertEqual(result['kind'], 'synthetic_rehearsal')
        self.assertEqual(result['closed'], 2)
        self.assertGreater(result['agent_calls'], 0)
        actions = [e['detail'] for e in result['events'] if e['step'] == 'Sanal açılış']
        self.assertTrue(any('LONG' in a for a in actions))
        self.assertTrue(any('SHORT' in a for a in actions))


if __name__ == '__main__':
    unittest.main()
