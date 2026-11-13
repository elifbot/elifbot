"""Phoenix Bot v2 — giriş noktası.

Komutlar:
  python main.py scan --watch              # anahtarsız sinyal taraması (sürekli)
  python main.py trade                     # paper test (sanal para, gerçek veri)
  python main.py trade --timeframe 1h      # farklı zaman dilimi (paralel oturum)
  python main.py trade --live --yes        # canlı (API anahtarı + onay gerekir)
  python backtest.py --symbol BTC/USDT:USDT
  python selftest.py                       # sistem sağlık kontrolü
"""
import argparse
import logging
import os
import sys
import time

import pandas as pd

from core.config import load_config
from core.exchange import Exchange
from core.trader import Trader
from core.scanner import SignalScanner

log = logging.getLogger('bot')


def setup_log(tf=None):
    name = f'bot_{tf}.log' if tf else 'bot.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(name, encoding='utf-8')])


def next_close_sleep(tf: str) -> float:
    """Bir sonraki mum kapanışına kadar bekleme (sn)."""
    tf_sec = pd.Timedelta(tf).total_seconds()
    return max(5.0, tf_sec - (time.time() % tf_sec) + 3)


def cmd_scan(args, cfg):
    tf = args.timeframe or cfg['timeframe']
    ex = Exchange(cfg, dry=True)
    sc = SignalScanner(ex, cfg, tf=tf)
    log.info(f'TARAMA: {cfg["symbols"]} tf={sc.tf} mtf={sc.mtf_tf} '
             f'(API anahtarı gerekmiyor)')
    while True:
        try:
            sc.scan_once()
        except Exception as e:
            log.exception(f'tarama hatası: {e}')
        if not args.watch:
            break
        time.sleep(next_close_sleep(sc.tf))


def cmd_trade(args, cfg):
    tf = args.timeframe or cfg['timeframe']
    live = args.live and args.yes
    if live and not os.getenv('BINANCE_API_KEY'):
        raise SystemExit('[HATA] Canlı mod için .env içinde BINANCE_API_KEY/SECRET '
                         'gerekli. Önce paper modda test edin.')
    if not live and cfg['mode'] == 'live':
        log.warning('config\'te mode: live olsa da --live --yes verilmedi → '
                    'PAPER modda çalışıyor (güvenlik).')
    ex = Exchange(cfg, dry=not live)
    tr = Trader(ex, cfg, tf_override=tf)
    mode = 'CANLI' if live else 'PAPER'
    log.info(f'İŞLEM: mod={mode} semboller={cfg["symbols"]} tf={tr.tf} '
             f'lev={cfg["leverage"]}x state={tr.state_path}')
    while True:
        try:
            for sym in cfg['symbols']:
                df = ex.ohlcv(sym, tr.tf, 400).iloc[:-1]   # oluşan mumu at
                if len(df) < cfg['strategy']['ema_trend'] + 5:
                    continue
                tr.manage(sym, df)
        except KeyboardInterrupt:
            log.info('kullanıcı tarafından durduruldu')
            break
        except Exception as e:
            log.exception(f'döngü hatası (devam ediliyor): {e}')
        time.sleep(next_close_sleep(tr.tf))


def main():
    ap = argparse.ArgumentParser(description='Phoenix Bot v2 — kripto futures')
    ap.add_argument('--config', default='config.yaml')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p1 = sub.add_parser('scan', help='sinyal taraması (API gerekmez)')
    p1.add_argument('--timeframe', default=None)
    p1.add_argument('--watch', action='store_true', help='sürekli tara')

    p2 = sub.add_parser('trade', help='paper/canlı işlem motoru')
    p2.add_argument('--timeframe', default=None)
    p2.add_argument('--live', action='store_true')
    p2.add_argument('--yes', action='store_true', help='canlı onayı (--live --yes)')

    args = ap.parse_args()
    cfg = load_config(args.config)
    tf = args.timeframe or cfg['timeframe']
    setup_log(tf)
    if args.cmd == 'scan':
        cmd_scan(args, cfg)
    elif args.cmd == 'trade':
        cmd_trade(args, cfg)


if __name__ == '__main__':
    main()
