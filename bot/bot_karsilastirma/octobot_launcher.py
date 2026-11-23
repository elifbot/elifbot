"""Compatibility shim for OctoBot 2.1.1; simulator-only launcher.

CCXT 4.5.44 uses OKX's retiring 8443 WS port. Dated futures have no periodic
funding; the generic upstream updater otherwise incorrectly requests it.
All market symbols remain in OctoBot's configured trading universe.
"""
import json
from pathlib import Path


def fix_ws_urls(description):
    for kind in ('api', 'test'):
        part = description.get('urls', {}).get(kind, {})
        ws = part.get('ws')
        if isinstance(ws, str) and ws.startswith(('wss://ws.okx.com:8443/', 'wss://wspap.okx.com:8443/')):
            part['ws'] = ws.replace(':8443/', ':443/')
    return description


def perpetual_pairs(pairs, swap_symbols):
    return [pair for pair in pairs if pair in swap_symbols]


def main():
    import ccxt.pro
    from octobot_trading.exchange_data.funding.channel.funding_updater import FundingUpdater
    from octobot.cli import main as octobot_main
    swaps = set(json.loads(Path('okx-swaps.json').read_text()))
    original_describe = ccxt.pro.okx.describe
    def describe(self):
        return fix_ws_urls(original_describe(self))
    ccxt.pro.okx.describe = describe
    original_get_pairs = FundingUpdater._get_pairs_to_update
    def get_pairs(self):
        if self.channel.exchange_manager.exchange_name == 'okx':
            return perpetual_pairs(original_get_pairs(self), swaps)
        return original_get_pairs(self)
    FundingUpdater._get_pairs_to_update = get_pairs
    # This entry point intentionally has no command-line switch for real trading.
    octobot_main(['--simulate', '--no_web', '--no-telegram'])


if __name__ == '__main__': main()
