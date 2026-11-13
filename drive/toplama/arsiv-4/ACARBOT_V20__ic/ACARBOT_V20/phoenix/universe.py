from dataclasses import dataclass
from threading import RLock
from time import time, sleep
from typing import Callable
from .models import Market, Snapshot
from .utils_retry import RetryPolicy, with_retry

class Universe:
    def __init__(self, adapters:dict[str,object], refresh_sec=300, retry=None):
        self.adapters=adapters; self.refresh_sec=refresh_sec; self.retry=retry or RetryPolicy(); self._lock=RLock(); self._markets={}; self._last_refresh=0.0

    def _call(self, fn:Callable):
        return with_retry(fn, self.retry)

    def discover(self, now=None):
        now=now or time()
        if now-self._last_refresh<self.refresh_sec and self._markets:return list(self._markets.values())
        merged={}
        for name,adapter in self.adapters.items():
            try:
                for m in self._call(adapter.load_markets):
                    if m.active and m.quote=="USDT" and m.settle=="USDT" and m.contract_type in {"swap","future","perpetual"}:
                        merged[(m.exchange,m.symbol)]=m
            except Exception:
                continue
        with self._lock:
            self._markets=merged; self._last_refresh=now
            return list(merged.values())

    def liquid(self, snapshots:list[Snapshot]) -> list[Snapshot]:
        return [s for s in snapshots if not s.stale_book and s.quote_volume_24h>0 and s.spread_bps>=0]

    def get(self,key):
        with self._lock:return self._markets.get(key)
