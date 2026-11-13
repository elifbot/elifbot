"""Kapanmış paper işlemlere funding geçmişini ayrı rapor olarak hesaplar.

Orijinal işlem dosyasını ve bot bakiyesini DEĞİŞTİRMEZ. Olay anı OKX mark
fiyatı 1 dakikalık mark mumunun açılışından tahmindir. Geçmişin eksik/truncated
olduğu veya halka açık API'nin hata verdiği işlemler net sonucu hesaplanmadan
'belirsiz' olarak işaretlenir.
"""
from __future__ import annotations
import asyncio
import csv
import math
import os
from types import SimpleNamespace
import aiohttp
from data.extended.funding_events import FundingWatcher


async def reconcile_rows(rows, session):
    watcher = FundingWatcher(None)
    output = []
    for row in rows:
        result = dict(row)
        result.update(funding_reconciled='bilinmiyor', pnl_reconciled='bilinmiyor',
                      funding_source='', funding_error='')
        try:
            opened, closed = int(row['opened_at']), int(row['closed_at'])
            qty = float(row['qty_base'])
            if opened < 0 or closed <= opened or not math.isfinite(qty) or qty <= 0:
                raise ValueError('gecersiz pozisyon araligi/miktari')
            if row['side'] not in ('LONG', 'SHORT'):
                raise ValueError('gecersiz yon')
            if row['exchange'] not in ('binance', 'okx'):
                raise ValueError('gecersiz borsa')
            p = SimpleNamespace(exchange=row['exchange'], symbol=row['symbol'],
                                opened_at=opened, last_funding_ts=0)
            events = await watcher._events(session, p, closed)
            selected = []
            for ts, rate, mark, source in events:
                if not (opened < ts <= closed):
                    continue
                if not math.isfinite(rate) or not math.isfinite(mark) or mark <= 0:
                    raise ValueError('gecersiz funding verisi')
                selected.append((ts, rate, mark, source))
            if len({e[0] for e in selected}) != len(selected):
                raise ValueError('tekrarli funding olayi')
            direction = 1 if row['side'] == 'LONG' else -1
            funding = sum(rate * mark * qty * direction for ts, rate, mark, source in selected)
            gross = float(row['gross_pnl']); entry = float(row['entry_fee']); exit_fee = float(row['exit_fee'])
            if not all(math.isfinite(x) for x in (gross, entry, exit_fee, funding)):
                raise ValueError('gecersiz muhasebe verisi')
            result['funding_reconciled'] = round(funding, 10)
            result['pnl_reconciled'] = round(gross-entry-exit_fee-funding, 10)
            result['funding_source'] = ','.join(sorted({x[3] for x in selected})) or 'no_event_in_interval'
        except Exception as exc:
            result['funding_error'] = f'{type(exc).__name__}: {str(exc)[:180]}'
        output.append(result)
    return output


async def reconcile_file(input_file, output_file):
    if os.path.abspath(input_file) == os.path.abspath(output_file):
        raise ValueError('Orijinal dosyanin uzerine yazilamaz')
    with open(input_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f); fields = list(reader.fieldnames or []); rows = list(reader)
    extra = ['funding_reconciled', 'pnl_reconciled', 'funding_source', 'funding_error']
    if not fields: raise ValueError('Islem dosyasi bos veya basliksiz')
    async with aiohttp.ClientSession() as session:
        results = await reconcile_rows(rows, session)
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields + [x for x in extra if x not in fields])
        writer.writeheader(); writer.writerows(results)
    return len(results), sum(r['funding_reconciled'] == 'bilinmiyor' for r in results)
