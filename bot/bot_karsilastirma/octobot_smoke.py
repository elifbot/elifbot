"""OctoBot futures simulator startup probe. No private keys or real trader."""
import collections
import importlib.resources
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import ccxt


def main():
    root = Path.cwd()
    profile_path = root / 'user/profiles/daily_trading/profile.json'
    if not profile_path.exists():
        raise RuntimeError('Official daily_trading profile not installed: '+str(profile_path))
    exchange = ccxt.okx({'enableRateLimit': True})
    markets = exchange.load_markets()
    eligible = [m for m in markets.values() if m.get('active') and m.get('contract') and m.get('symbol')]
    if not eligible:
        raise RuntimeError('No active OKX contracts')
    groups = collections.defaultdict(list)
    for m in eligible:
        groups[m.get('base') or m['symbol']].append(m['symbol'])
    profile = json.loads(profile_path.read_text())
    pc = profile['config']
    pc['crypto-currencies'] = {k: {'enabled': True, 'pairs': sorted(v)} for k,v in groups.items()}
    pc['exchanges'] = {'okx': {'enabled': True, 'exchange-type': 'future'}}
    pc['trader'] = {'enabled': False, 'load-trade-history': False}
    pc['trader-simulator'] = {'enabled': True, 'starting-portfolio': {'USDT': 1_000_000},
                              'fees': {'maker': 0.1, 'taker': 0.1}}
    pc['trading']['reference-market'] = 'USDT'
    profile['profile']['read_only'] = False
    profile_path.write_text(json.dumps(profile, indent=2))
    default_cfg = importlib.resources.files('octobot.config').joinpath('default_config.json').read_text()
    cfg = json.loads(default_cfg)
    cfg['profile'] = 'daily_trading'
    cfg['exchanges'] = {}
    (root/'user/config.json').write_text(json.dumps(cfg, indent=2))
    if pc['trader']['enabled'] or not pc['trader-simulator']['enabled']:
        raise RuntimeError('Paper-only safety check failed')
    outfile = root/'smoke-console.txt'
    env = dict(os.environ, MAX_ALLOWED_SYMBOLS='-1', MAX_ALLOWED_EXCHANGES='-1')
    with outfile.open('w') as out:
        proc = subprocess.Popen(['OctoBot','--simulate','--no_web','--no-telegram'],
                                stdout=out, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        try:
            code = proc.wait(timeout=180)
            early = True
        except subprocess.TimeoutExpired:
            early = False
            os.killpg(proc.pid, signal.SIGINT)
            try: code = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL); code = proc.wait()
    text = re.sub(r'\x1b\[[0-9;]*m', '', outfile.read_text(errors='replace'))
    lines = text.splitlines()
    markers = [l[:2000] for l in lines if 'Starting OctoBot with' in l]
    good = any('simulated trader' in s and 'okx[future]' in s.lower() for s in markers)
    errors = [x[:500] for x in lines if ' ERROR ' in x or 'CRITICAL' in x][-3:]
    result = {'stage':'octobot_short_simulator_probe','requested_seconds':180,'eligible_contracts':len(eligible),
              'starting_portfolio':{'USDT':1_000_000}, 'early_exit':early,'exit_code':code,
              'simulator_and_okx_future_seen':good,'errors':errors,
              'caution':'startup marker is not proof of usable prices or trades'}
    (root/'smoke-report.json').write_text(json.dumps(result,indent=2))
    print('::notice title=OctoBot paper prova::'+json.dumps(result),flush=True)
    print('\n'.join(lines[-40:]),flush=True)
    return 0 if good and not early else 1

if __name__=='__main__': sys.exit(main())
