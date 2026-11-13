"""Kesin şemalı CSV mumları; eksik/bozuk seri fail-closed."""
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import io
from pathlib import Path
import math

def _finite_number(x):
    try: return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
    except OverflowError: return False

@dataclass(frozen=True)
class Bar:
    timestamp: int  # mum açılış zamanı, UTC epoch saniye
    open: float
    high: float
    low: float
    close: float
    volume: float

def validate_bars(bars, interval):
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        raise ValueError('interval pozitif tam sayı olmalı')
    if not bars:
        raise ValueError('veri boş')
    prev = None
    for b in bars:
        if isinstance(b.timestamp, bool) or not isinstance(b.timestamp, int) or b.timestamp < 0 or b.timestamp > 253402300000:
            raise ValueError('geçersiz zaman')
        if prev is not None and b.timestamp - prev != interval:
            raise ValueError('zaman sırası, yinelenen veya eksik mum')
        v=(b.open,b.high,b.low,b.close,b.volume)
        if not all(_finite_number(x) for x in v) or min(v[:4]) <= 0 or b.volume < 0:
            raise ValueError('geçersiz fiyat/hacim')
        if b.low > min(b.open,b.close) or b.high < max(b.open,b.close) or b.low > b.high:
            raise ValueError('OHLC tutarsız')
        prev=b.timestamp

def load_csv(path, interval):
    return load_csv_bytes(Path(path).read_bytes(), interval)

def load_csv_bytes(data, interval):
    try:
        text=data.decode('utf-8-sig')
    except UnicodeDecodeError as e:
        raise ValueError('CSV UTF-8 olmalı') from e
    with io.StringIO(text, newline='') as f:
        reader=csv.DictReader(f)
        expected={'timestamp','open','high','low','close','volume'}
        if not reader.fieldnames or not expected.issubset(reader.fieldnames):
            raise ValueError('CSV: timestamp,open,high,low,close,volume gerekli')
        bars=[]
        for line,row in enumerate(reader,2):
            try:
                stamp=row['timestamp'].strip()
                if stamp.isdigit(): ts=int(stamp)
                else:
                    dt=datetime.fromisoformat(stamp.replace('Z','+00:00'))
                    if dt.tzinfo is None: raise ValueError('saat dilimi gerekli')
                    if dt.microsecond: raise ValueError('saniye altı zaman desteklenmez')
                    ts=int(dt.astimezone(timezone.utc).timestamp())
                bars.append(Bar(ts,*(float(row[x]) for x in ('open','high','low','close','volume'))))
            except (KeyError,TypeError,ValueError) as e:
                raise ValueError(f'CSV satır {line}: {e}') from e
    validate_bars(bars,interval)
    return bars
