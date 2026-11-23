"""Upstream Freqtrade sample, OKX, dry-run only; never creates exchange orders."""
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import importlib.resources

ROOT = Path('runs/freqtrade_smoke').resolve()


def config():
    return {
        'dry_run': True, 'dry_run_wallet': 1_000_000, 'initial_state': 'running',
        'trading_mode': 'futures', 'margin_mode': 'isolated', 'max_open_trades': -1,
        'stake_currency': 'USDT', 'stake_amount': 50, 'tradable_balance_ratio': 1,
        'unfilledtimeout': {'entry': 10, 'exit': 10, 'exit_timeout_count': 0, 'unit': 'minutes'},
        'entry_pricing': {'price_side': 'same', 'use_order_book': True, 'order_book_top': 1},
        'exit_pricing': {'price_side': 'same', 'use_order_book': True, 'order_book_top': 1},
        'exchange': {'name': 'okx', 'key': '', 'secret': '', 'password': '',
                     'pair_whitelist': ['.*/USDT:USDT'], 'pair_blacklist': []},
        'pairlists': [{'method': 'StaticPairList'}], 'telegram': {'enabled': False},
        'api_server': {'enabled': False}, 'internals': {'process_throttle_secs': 5},
    }


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    strategies = ROOT / 'strategies'
    strategies.mkdir(exist_ok=True)
    source = importlib.resources.files('freqtrade.templates').joinpath('sample_strategy.py').read_text()
    if 'can_short: bool = False' not in source:
        raise RuntimeError('Upstream sample changed; refusing to silently modify the strategy')
    # Only modification to the upstream example enables its existing short rules.
    (strategies / 'SampleStrategy.py').write_text(source.replace('can_short: bool = False', 'can_short: bool = True', 1))
    cfg = config()
    assert cfg['dry_run'] is True and not cfg['exchange']['key'] and not cfg['exchange']['secret']
    (ROOT / 'config.json').write_text(json.dumps(cfg, indent=2))
    db = ROOT / 'trades.dryrun.sqlite'
    log = ROOT / 'freqtrade.log'
    args = ['freqtrade', 'trade', '--userdir', str(ROOT), '--config', str(ROOT / 'config.json'),
            '--strategy', 'SampleStrategy', '--db-url', f'sqlite:///{db}', '--logfile', str(log)]
    print('Gerçek Freqtrade örneği; yalnızca dry-run. USDT teminatlı lineer swap evreni, izole marj.', flush=True)
    print('Bu kısa deneme tüm OKX kontratlarını kapsamaz; üretim veya kârlılık kanıtı değildir.', flush=True)
    console = (ROOT / 'console.txt').open('w', encoding='utf-8')
    proc = subprocess.Popen(args, stdout=console, stderr=subprocess.STDOUT)
    duration = int(os.environ.get('FREQ_SMOKE_SECONDS', '180'))
    try:
        code = proc.wait(timeout=duration)
        prematurely_exited = True
    except subprocess.TimeoutExpired:
        prematurely_exited = False
        proc.send_signal(signal.SIGINT)
        try:
            code = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = proc.wait()
    console.close()
    text = log.read_text(errors='replace') if log.exists() else (ROOT / 'console.txt').read_text(errors='replace')
    print(text[-16000:], flush=True)
    # A running process alone is not proof that Freqtrade reached the trade loop.
    heartbeat = 'state=\'RUNNING\'' in text
    report = {'mode': 'actual_freqtrade_dry_run', 'starting_usdt': 1_000_000,
              'strategy': 'upstream SampleStrategy, shorts enabled', 'timeframe': '5m',
              'scope': 'active USDT-settled linear swaps recognized by Freqtrade',
              'excludes': 'dated futures, inverse contracts and other settlement currencies',
              'one_position_per_pair': True, 'requested_seconds': duration,
              'premature_exit': prematurely_exited, 'exit_code': code, 'running_heartbeat': heartbeat,
              'paper_trades': None, 'open_trades': None}
    if db.exists():
        try:
            with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
                report['paper_trades'], report['open_trades'] = conn.execute(
                    'select count(*), coalesce(sum(is_open), 0) from trades').fetchone()
        except sqlite3.Error as e:
            report['database_error'] = str(e)
    if prematurely_exited or not heartbeat:
        report['diagnostic_log_tail'] = text[-1500:]
        report['diagnostic_error_lines'] = [line[:700] for line in text.splitlines()
                                            if 'Invalid configuration. Reason:' in line or 'Configuration error:' in line or 'ERROR -' in line][-3:]
    (ROOT / 'report.json').write_text(json.dumps(report, indent=2))
    # JSON escapes newlines, keeping the annotation valid and useful even when
    # Actions log/artifact downloads are unavailable in the preview environment.
    print('::notice title=Freqtrade kısa dry-run::' + json.dumps(report, ensure_ascii=False), flush=True)
    if prematurely_exited or not heartbeat:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
