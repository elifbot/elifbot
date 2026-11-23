"""Gerçek paketlerin kurulum ve OKX public erişim tanısı; işlem simülasyonu değildir."""
import collections
import importlib
import importlib.metadata
import json
import os
import platform
import urllib.request
from pathlib import Path

PACKAGES = {'freqtrade': 'freqtrade', 'octobot': 'OctoBot', 'jesse': 'jesse'}


def main():
    bot = os.environ['BOT_NAME']
    if bot not in PACKAGES:
        raise ValueError('Bilinmeyen bot')
    report = {'bot': bot, 'test_type': 'installation_and_public_market_probe',
              'is_paper_trading': False, 'version': importlib.metadata.version(PACKAGES[bot]),
              'python': platform.python_version(), 'market': 'OKX public', 'private_api_used': False}
    rows = []
    for kind in ('SWAP', 'FUTURES'):
        url = 'https://www.okx.com/api/v5/public/instruments?instType=' + kind
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'elifbot-compatibility/1.0'}), timeout=20) as response:
            data = json.load(response)
        if data.get('code') != '0' or not isinstance(data.get('data'), list):
            raise RuntimeError('OKX returned invalid public data')
        rows += [x for x in data['data'] if x.get('state') == 'live']
    report['active_contracts'] = len(rows)
    report['by_type'] = dict(collections.Counter(x['instType'] for x in rows))
    report['by_settlement_and_type'] = dict(collections.Counter(
        (x.get('settleCcy') or 'unknown') + '/' + (x.get('ctType') or 'unknown') for x in rows))
    if bot == 'freqtrade':
        m = importlib.import_module('freqtrade.exchange.okx')
        c = importlib.import_module('ccxt')
        markets = c.okx({'enableRateLimit': True}).load_markets()
        swaps = [x for x in markets.values() if x.get('active') and x.get('type') == 'swap' and x.get('linear')]
        report['ccxt_active_linear_swaps_by_settle'] = dict(collections.Counter(x.get('settle') or 'unknown' for x in swaps))
        report['limitations'] = ['Freqtrade 2026.10 supports linear swaps, not dated futures or inverse swaps',
                                 'one open trade per pair; OKX isolated margin', 'one stake currency per bot configuration']
        report['engine_class'] = m.Okx.__name__
    elif bot == 'octobot':
        importlib.import_module('octobot.cli')
        report['limitations'] = ['Installed core only; OKX futures paper mode and strategy not yet verified']
    else:
        importlib.import_module('jesse.indicators')
        report['limitations'] = ['OKX not listed by official Jesse supported exchanges; paper mode needs licensed plugin',
                                 'No licensed plugin installed; no paper session was started']
    path = Path('runs/bot_uyumluluk') / bot / 'report.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
