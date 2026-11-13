"""Borsa entegrasyonu (ccxt) — retry, testnet, stop/TP emirleri, türev verileri.

Not: fetch_ohlcv / funding / OI gibi PÜBLİK uçlar API anahtarı olmadan çalışır;
yalnızca emir ve bakiye işlemleri anahtar ister. Bu sayede `scan` modu anahtarsızdır.
"""
import os
import time
import logging
import ccxt
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger('bot')


class Exchange:
    def __init__(self, cfg: dict, dry: bool = True):
        self.cfg = cfg
        self.dry = dry
        self.paper = float(cfg.get('paper_equity', 10000))
        klass = getattr(ccxt, cfg['exchange'])
        self.x = klass({
            'apiKey': os.getenv('BINANCE_API_KEY', ''),
            'secret': os.getenv('BINANCE_API_SECRET', ''),
            'enableRateLimit': True,
            'options': {'defaultType': 'future'},
        })
        if (not dry) and cfg.get('testnet', True) and os.getenv('BINANCE_API_KEY'):
            self.x.set_sandbox_mode(True)     # testnet.binancefuture.com
            log.info('TESTNET modu etkin')
        self._lev_done = set()

    # ---------- alt seviye ----------
    def _retry(self, fn, *a, **k):
        last = None
        for i in range(3):
            try:
                return fn(*a, **k)
            except (ccxt.NetworkError, ccxt.RequestTimeout,
                    ccxt.ExchangeNotAvailable) as e:
                last = e
                log.warning(f'ağ hatası, tekrar {i+1}/3: {e}')
                time.sleep(2 * (i + 1))
        raise RuntimeError(f'borsaya ulaşılamıyor: {last}')

    # ---------- pazar verisi (anahtarsız) ----------
    def ohlcv(self, symbol, tf, limit=400) -> pd.DataFrame:
        raw = self._retry(self.x.fetch_ohlcv, symbol, tf, None, limit)
        df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        return df.set_index('ts')

    def funding_rate(self, symbol):
        try:
            fr = self._retry(self.x.fetch_funding_rate, symbol)
            v = fr.get('fundingRate')
            return float(v) if v is not None else None
        except Exception as e:
            log.debug(f'funding alınamadı {symbol}: {e}')
            return None

    def open_interest_delta(self, symbol, hours=4):
        """Son N saatteki açık pozisyon (OI) değişimi (%). None = veri yok."""
        try:
            hist = self._retry(self.x.fetch_open_interest_history,
                               symbol, '1h', None, hours + 2)
            vals = [float(h.get('openInterestAmount') or 0) for h in hist or []
                    if h.get('openInterestAmount')]
            if len(vals) < 2 or vals[0] <= 0:
                return None
            return (vals[-1] - vals[0]) / vals[0] * 100
        except Exception as e:
            log.debug(f'OI alınamadı {symbol}: {e}')
            return None

    # ---------- hesap / emir ----------
    def balance_usdt(self) -> float:
        if self.dry:
            return self.paper
        b = self._retry(self.x.fetch_balance)
        usdt = b.get('USDT') or {}
        return float(usdt.get('total') or usdt.get('free') or 0.0)

    def ensure_leverage(self, symbol, lev=None):
        if self.dry or not os.getenv('BINANCE_API_KEY'):
            return
        lev = int(lev or self.cfg['leverage'])
        if symbol in self._lev_done:
            return
        try:
            self.x.set_leverage(lev, symbol)
            self.x.set_margin_mode(self.cfg.get('margin_mode', 'isolated'), symbol)
        except Exception as e:
            if '-4046' not in str(e):        # zaten ayarlı → sorun değil
                log.warning(f'lev/margin ayarı: {e}')
        self._lev_done.add(symbol)

    def amount_precision(self, symbol, qty) -> float:
        try:
            return float(self.x.amount_to_precision(symbol, qty))
        except Exception:
            return round(qty, 6)

    def market_order(self, symbol, side, qty):
        if self.dry:
            return {'id': 'dry'}
        return self._retry(self.x.create_order, symbol, 'market', side, qty)

    def stop_orders(self, symbol, side_close, qty, sl, tp2, tp1=None, tp1_qty=0.0):
        """Koruma emirleri. side_close: LONG için 'sell', SHORT için 'buy'.
        SL tam miktar, TP2 tam miktar, TP1 kısmi (varsa) — tümü reduceOnly."""
        if self.dry:
            return
        base = {'reduceOnly': True}
        self._retry(self.x.create_order, symbol, 'market', side_close, qty,
                    None, {**base, 'stopLossPrice': sl})
        self._retry(self.x.create_order, symbol, 'market', side_close, qty,
                    None, {**base, 'takeProfitPrice': tp2})
        if tp1 and tp1_qty > 0:
            self._retry(self.x.create_order, symbol, 'market', side_close, tp1_qty,
                        None, {**base, 'takeProfitPrice': tp1})

    def cancel_stops(self, symbol):
        if self.dry:
            return
        try:
            for o in self._retry(self.x.fetch_open_orders, symbol):
                self._retry(self.x.cancel_order, o['id'], symbol)
        except Exception as e:
            log.warning(f'stop emir iptali: {e}')

    def positions(self, symbol):
        if self.dry or not os.getenv('BINANCE_API_KEY'):
            return []
        try:
            ps = self._retry(self.x.fetch_positions, [symbol])
            return [p for p in ps if float(p.get('contracts') or 0) > 0]
        except Exception as e:
            log.warning(f'pozisyon sorgusu: {e}')
            return []
