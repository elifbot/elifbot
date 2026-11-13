"""Açık ve kapanmış paper pozisyonlara kısmi public funding mutabakatı.

Kapanmış işlemler de tekrar sorgulanır; yine de public geçmişin yayın gecikmesi,
API kapsama sınırları ve OKX mark yaklaşık değeri nedeniyle sonuç kısmi kalır.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import math
import os
import time
from types import SimpleNamespace

import aiohttp
from data.feed_utils import ensure_url_allowed

log = logging.getLogger(__name__)
PARTIAL = 'funding kısmi / doğrulanmamış'


class FundingWatcher:
    def __init__(self, portfolio, *, binance_base='https://www.binance.com/fapi/v1',
                 journal_path=None, on_change=None, on_materialize=None):
        self.portfolio = portfolio
        self.binance_base = binance_base.rstrip('/')
        self.journal_path = journal_path
        self.on_change = on_change
        self.on_materialize = on_materialize
        self._closed_offset = 0
        self.applied = 0
        self.closed_applied = 0
        self.errors = 0
        self.last_error = None
        self.last_poll_ms = 0

    async def _json(self, session, url, params):
        ensure_url_allowed(url)
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=12), allow_redirects=False) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _events(self, session, pos, now_ms):
        if pos.exchange == 'binance':
            rows = await self._json(session, self.binance_base + '/fundingRate',
                # Aynı milisaniye: sıralama bilinmediğinden dışlanır, gerçek hak iddiası yok.
                {'symbol': pos.symbol, 'startTime': pos.opened_at + 1,
                 'endTime': now_ms, 'limit': 100})
            if not isinstance(rows, list):
                raise ValueError('Binance funding yaniti liste degil')
            if len(rows) >= 100:
                raise ValueError('Binance funding gecmisi kirpilmis olabilir')
            result = []
            for row in rows:
                if row.get('symbol') != pos.symbol:
                    continue
                try:
                    result.append((int(row['fundingTime']), float(row['fundingRate']),
                                   float(row['markPrice']), 'binance_event_mark'))
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f'Binance funding satiri eksik/bozuk: {exc!r}') from exc
            return result
        if pos.exchange == 'okx':
            body = await self._json(session, 'https://www.okx.com/api/v5/public/funding-rate-history',
                                    {'instId': pos.symbol, 'limit': '100'})
            if not isinstance(body, dict) or body.get('code') != '0' or not isinstance(body.get('data'), list):
                raise ValueError('OKX funding gecmisi gecersiz')
            rows = body['data']
            if not rows:
                raise ValueError('OKX funding gecmisi bos; kapsam dogrulanamiyor')
            if len(rows) >= 100 and min(int(x['fundingTime']) for x in rows) > pos.opened_at:
                raise ValueError('OKX funding gecmisi kirpilmis olabilir')
            result = []
            for row in rows:
                ts = int(row['fundingTime'])
                if row.get('instId') != pos.symbol or not (pos.opened_at < ts <= now_ms):
                    continue
                rate = row.get('realizedRate')
                if rate in ('', None):
                    raise ValueError('OKX gerceklesen funding orani yok')
                # OKX gecmisi olaydaki kesin mark fiyatini donmez. Olay
                # dakikasinin mark mumu ACILISINI yaklasim olarak kullaniriz.
                minute = ts // 60_000 * 60_000
                candles = await self._json(session,
                    'https://www.okx.com/api/v5/market/history-mark-price-candles',
                    {'instId': pos.symbol, 'bar': '1m', 'after': str(minute + 60_000), 'limit': '2'})
                if not isinstance(candles, dict) or candles.get('code') != '0':
                    raise ValueError('OKX tarihsel mark verisi yok')
                match = next((x for x in candles.get('data', []) if int(x[0]) == minute), None)
                if not match:
                    raise ValueError('OKX funding dakikasi mark mumu yok')
                result.append((ts, float(rate), float(match[1]), 'okx_1m_open_approx'))
            return result
        raise ValueError('desteklenmeyen borsa')

    def _write_event(self, event):
        """Atomik ve anahtar bazli idempotent CSV yansitmasi (tek surec varsayimi)."""
        if not self.journal_path:
            return
        fields = ['exchange', 'symbol', 'side', 'opened_at', 'funding_ts', 'rate', 'mark', 'source', 'fee']
        os.makedirs(os.path.dirname(os.path.abspath(self.journal_path)), exist_ok=True)
        rows = []
        if os.path.exists(self.journal_path) and os.path.getsize(self.journal_path):
            with open(self.journal_path, newline='', encoding='utf-8') as fh:
                reader = csv.DictReader(fh)
                if reader.fieldnames != fields:
                    raise ValueError('funding gunlugu basligi gecersiz')
                rows = list(reader)
        key = ('exchange', 'symbol', 'side', 'opened_at', 'funding_ts')
        same = [r for r in rows if all(str(r[k]) == str(event[k]) for k in key)]
        if same:
            if len(same) != 1 or any(str(same[0][k]) != str(event[k]) for k in fields):
                raise ValueError('funding gunlugunde cakisan olay')
            return
        rows.append(event)
        tmp = self.journal_path + '.tmp'
        with open(tmp, 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader(); w.writerows(rows)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, self.journal_path)

    def _flush_outbox(self):
        while self.portfolio.funding_outbox:
            event = self.portfolio.funding_outbox[0]
            self._write_event(event)
            self.portfolio.funding_outbox.pop(0)
            try:
                if self.on_change:
                    self.on_change()
            except Exception:
                self.portfolio.funding_outbox.insert(0, event)
                raise

    async def poll_once(self, session, now_ms=None):
        now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        self.last_poll_ms = now_ms
        self.last_error = None
        try:
            self._flush_outbox()
        except Exception as exc:
            self.errors += 1
            self.last_error = f'funding outbox {type(exc).__name__}: {str(exc)[:160]}'
            log.warning('funding outbox basarisiz: %s', self.last_error)
            return
        for key, pos in list(self.portfolio.positions.items()):
            try:
                events = sorted(await self._events(session, pos, now_ms), key=lambda x: x[0])
                for ts, rate, mark, source in events:
                    # Ag sorgusu surerken pozisyon kapanmis veya yeniden acilmis olabilir.
                    if self.portfolio.positions.get(key) is not pos:
                        break
                    if (not (pos.opened_at < ts <= now_ms) or ts in pos.funding_event_ts
                            or ts <= pos.funding_legacy_cursor):
                        continue
                    if not math.isfinite(rate) or not math.isfinite(mark) or mark <= 0:
                        raise ValueError('gecersiz funding oran/mark')
                    before = (self.portfolio.balance, pos.funding_fee, pos.funding_label, pos.last_funding_ts, list(pos.funding_event_ts))
                    fee = self.portfolio.apply_funding(*key, rate, mark, now_ms=ts)
                    pos.last_funding_ts = max(pos.last_funding_ts, ts)
                    pos.funding_event_ts.append(ts)
                    pos.funding_label = PARTIAL
                    event = dict(exchange=pos.exchange, symbol=pos.symbol, side=pos.side,
                                 opened_at=pos.opened_at, funding_ts=ts, rate=rate,
                                 mark=mark, source=source, fee=fee)
                    if self.journal_path:
                        self.portfolio.funding_outbox.append(event)
                    try:
                        if self.on_change:
                            self.on_change()
                    except Exception:
                        self.portfolio.balance, pos.funding_fee, pos.funding_label, pos.last_funding_ts, pos.funding_event_ts = before
                        if self.journal_path:
                            self.portfolio.funding_outbox.pop()
                        raise
                    self.applied += 1
                    self._flush_outbox()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors += 1
                self.last_error = f'{key[0]}:{key[1]} {type(exc).__name__}: {str(exc)[:160]}'
                log.warning('funding mutabakati basarisiz: %s', self.last_error)

        await self._poll_closed(session, now_ms)
        if self.on_materialize:
            try:
                self.on_materialize()
            except Exception as exc:
                self.errors += 1
                self.last_error = f'CSV mutabakat {type(exc).__name__}: {str(exc)[:160]}'
                log.warning('funding CSV mutabakati basarisiz: %s', self.last_error)

    async def _poll_closed(self, session, now_ms):
        """Kapanan işlemlerden tur başına en fazla 10 tanesini yeniden sorgula.

        Global settlement cursor kullanma: daha eski olay geç yayınlanabilir.
        Uygulama identity'si (işlem, funding timestamp) ile tutulur.
        """
        closed = list(self.portfolio.closed_trades)
        if not closed:
            return
        count = min(10, len(closed))
        offset = self._closed_offset % len(closed)
        selected = [closed[(offset+i) % len(closed)] for i in range(count)]
        self._closed_offset = (offset + count) % len(closed)
        for rec in selected:
            try:
                if (rec.side not in ('LONG', 'SHORT') or not math.isfinite(rec.qty_base)
                        or rec.qty_base <= 0 or rec.closed_at <= rec.opened_at):
                    raise ValueError('kapanmis islem verisi gecersiz')
                probe = SimpleNamespace(exchange=rec.exchange, symbol=rec.symbol,
                                        opened_at=rec.opened_at, last_funding_ts=0)
                events = sorted(await self._events(session, probe, min(now_ms, rec.closed_at)), key=lambda x:x[0])
                for ts, rate, mark, source in events:
                    if not (rec.opened_at < ts <= min(now_ms, rec.closed_at)):
                        continue
                    if ts in rec.funding_event_ts or ts <= rec.funding_legacy_cursor:
                        continue
                    if not math.isfinite(rate) or not math.isfinite(mark) or mark <= 0:
                        raise ValueError('gecersiz funding oran/mark')
                    fee = mark * rec.qty_base * rate * (1.0 if rec.side == 'LONG' else -1.0)
                    if not math.isfinite(fee) or fee > self.portfolio.balance:
                        raise ValueError('gecersiz funding veya yetersiz serbest bakiye')
                    before = (self.portfolio.balance, rec.funding_fee, rec.funding_label,
                              rec.realized_pnl, list(rec.funding_event_ts))
                    self.portfolio.balance -= fee
                    rec.funding_fee += fee
                    rec.realized_pnl -= fee
                    rec.funding_label = PARTIAL
                    rec.funding_event_ts.append(ts)
                    event = dict(exchange=rec.exchange, symbol=rec.symbol, side=rec.side,
                                 opened_at=rec.opened_at, funding_ts=ts, rate=rate,
                                 mark=mark, source=source, fee=fee)
                    if self.journal_path:
                        self.portfolio.funding_outbox.append(event)
                    try:
                        if self.on_change: self.on_change()
                    except Exception:
                        (self.portfolio.balance, rec.funding_fee, rec.funding_label,
                         rec.realized_pnl, rec.funding_event_ts) = before
                        if self.journal_path: self.portfolio.funding_outbox.pop()
                        raise
                    self.applied += 1
                    self.closed_applied += 1
                    self._flush_outbox()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors += 1
                self.last_error = f'closed:{rec.exchange}:{rec.symbol} {type(exc).__name__}: {str(exc)[:140]}'
                log.warning('kapali islem funding mutabakati basarisiz: %s', self.last_error)

    async def run(self, session, interval=30):
        while True:
            await self.poll_once(session)
            await asyncio.sleep(interval)
