import unittest
from bot.bot_karsilastirma.octobot_launcher import fix_ws_urls, perpetual_pairs

class CompatTests(unittest.TestCase):
    def test_funding_only_for_swaps_no_limit_to_trading(self):
        self.assertEqual(perpetual_pairs(['BTC/USDT:USDT','BTC/USD:USD-261225'], {'BTC/USDT:USDT'}), ['BTC/USDT:USDT'])
    def test_okx_port_only(self):
        data = {'urls': {'api': {'ws':'wss://ws.okx.com:8443/ws/v5'}, 'test': {'ws':'wss://wspap.okx.com:8443/ws/v5'}}}
        self.assertEqual(fix_ws_urls(data)['urls']['api']['ws'],'wss://ws.okx.com:443/ws/v5')
        self.assertEqual(data['urls']['test']['ws'],'wss://wspap.okx.com:443/ws/v5')
        other={'urls': {'api': {'ws':'wss://other:8443/ws'}}}
        self.assertEqual(fix_ws_urls(other)['urls']['api']['ws'],'wss://other:8443/ws')

if __name__ == '__main__': unittest.main()
