import unittest
from unittest.mock import patch

from bot.tradingagents_paper.telemetry import CheckPublisher


class TelemetryTests(unittest.TestCase):
    def test_publish_live_and_complete_without_leaking_token(self):
        requests = []
        def mock_request(self, method, path, payload):
            requests.append((method, path, payload))
            return {'id': 123}
        with patch.object(CheckPublisher, '_request', mock_request):
            pub = CheckPublisher('private-test-token', 'elifbot/elifbot', 'abcdef', '99', interval=999)
            pub.record({'type':'start', 'time':'now', 'universe':839, 'supported':558, 'duration_seconds':1800, 'model':'mock'})
            pub.record({'type':'progress','seconds':20,'universe':839,'fresh_symbols':800,'signals':15,
                        'queued':14,'stale_signals':0,'decisions':0,'open_positions':0,'cash':1000,'equity':1000})
            pub.record({'type':'agent_error','error':'timeout','symbol':'BTC-USDT-SWAP'})
            pub._publish()
            pub.record({'type':'finish','signals':15,'decisions':1,'open_positions':0,'closed':0,'equity':1000,
                        'usable_decisions':1,'valid':True})
            pub.finish()
            pub.finish()
        self.assertEqual(len(requests), 3)
        self.assertEqual(requests[0][0], 'POST')
        self.assertEqual(requests[-1][2]['conclusion'], 'success')
        self.assertNotIn('private-test-token', str(requests))
        self.assertIn('timeout', requests[1][2]['output']['summary'])

    def test_fail_closed_if_run_aborts(self):
        outputs = []
        with patch.object(CheckPublisher, '_request', lambda self, method, path, payload: outputs.append(payload) or {'id': 1}):
            p = CheckPublisher('token','elifbot/elifbot','abcdef','3',interval=999)
            p.finish()
        self.assertEqual(outputs[-1]['conclusion'], 'failure')

    def test_untrusted_repository_disallowed(self):
        with self.assertRaises(ValueError):
            CheckPublisher('token', 'other/repo', 'abcdef', '123')


if __name__ == '__main__':
    unittest.main()
