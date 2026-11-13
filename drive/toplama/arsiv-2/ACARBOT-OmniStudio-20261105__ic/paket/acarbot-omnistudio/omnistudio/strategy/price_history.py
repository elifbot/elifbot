"""Fiyat geçmişi — sınırlı ön-ek maksimum indeksli ilk-eşleşme araması.

KÖK NEDEN
v9.4.5 probru 230.349 on_trade çağrısında en uzun dalı buldu: her tick'te
tüm fiyat geçmişini baştan tarayan doğrusal arama (det.price 140.8s) ve her
sembol için tekrarlanan genişlik hesabı (det.breadth 56.6s). Bu O(n·m) yük
event loop'u bloke edip 5.22s süreklilik boşluğuna yol açan şüpheliydi.

ÇÖZÜM
`PriceHistory` sınırlı bir halka tampon + ön-ek maksimum dizisi tutar.
`first_at_or_after(t)` ikili aramayla O(log n) çalışır. Zaman damgaları SIRALI
OLMAK ZORUNDA DEĞİL: ön-ek maksimum monotoniktir, ikili arama geçerli bir aday
verir; aday eşiği sağlamıyorsa eski doğrusal aramaya DÜŞER. Böylece çıktı
eski davranışla BİREBİR aynıdır, yalnız hızlanır.

GARANTİ SINIRI
Bu bir hız optimizasyonudur. Tick atlanmaz, eşik değişmez, sinyal mantığı
değişmez. Sentetik bileşen kıyası tüm bot hızlanması anlamına GELMEZ.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from collections import deque
from numbers import Real
from typing import Iterator


class PriceHistory:
    """(ts_ms, price) kayıtları için sınırlı tampon + O(log n) ilk-eşleşme.

    Mutasyonların TAMAMI bu sınıfın metotlarından geçer; dışarıdan `_buf`
    değiştirilirse indeks geçersizleşir. Bu yüzden `_buf` özel tutulur ve
    dış erişim yalnız okunur `items()` / `__iter__` ile yapılır.
    """

    __slots__ = ("_buf", "_prefix", "_head", "_valid", "_maxlen", "_rebuilds",
                 "seq", "monotonic", "_last_ts")

    def __init__(self, maxlen: int = 4096) -> None:
        if maxlen <= 0:
            raise ValueError("maxlen pozitif olmalı")
        self._maxlen = maxlen
        self._buf: deque[tuple[int, float]] = deque(maxlen=maxlen)
        self._prefix: list[float] = []
        self._head = 0
        self._valid = True
        self._rebuilds = 0
        #: Toplam ekleme sayısı (mutlak koordinat). Kayan toplamlar bunu kullanır.
        self.seq = 0
        #: Zaman damgaları azalmayan sırada mı? Kayan pencere ön koşulu.
        self.monotonic = True
        self._last_ts: float | None = None

    # ---------- yazma ----------
    def append(self, ts_ms: int, price: float) -> None:
        full = len(self._buf) == self._maxlen
        self._buf.append((ts_ms, price))
        self.seq += 1
        if self.monotonic:
            if isinstance(ts_ms, Real) and math.isfinite(ts_ms):
                if self._last_ts is not None and ts_ms < self._last_ts:
                    self.monotonic = False
                self._last_ts = float(ts_ms)
            else:
                self.monotonic = False
        if not self._valid:
            return
        if not isinstance(ts_ms, Real) or not math.isfinite(ts_ms):
            self._valid = False
            return
        if full:
            self._head += 1
        t = float(ts_ms)
        self._prefix.append(max(self._prefix[-1], t) if self._prefix else t)
        # Amortize yeniden kurulum: baş offset büyüyünce diziyi sıkıştır.
        if self._head >= max(1024, len(self._buf)):
            self._rebuild()

    def _rebuild(self) -> None:
        self._prefix = []
        self._head = 0
        self._valid = True
        self._rebuilds += 1
        run = None
        for t, _ in self._buf:
            if not isinstance(t, Real) or not math.isfinite(t):
                self._valid = False
                self._prefix = []
                return
            tf = float(t)
            run = tf if run is None else max(run, tf)
            self._prefix.append(run)

    def clear(self) -> None:
        self._buf.clear()
        self._prefix = []
        self._head = 0
        self._valid = True
        self.seq = 0
        self.monotonic = True
        self._last_ts = None

    # ---------- okuma ----------
    def __len__(self) -> int:
        return len(self._buf)

    def __bool__(self) -> bool:
        return bool(self._buf)

    def __iter__(self) -> Iterator[tuple[int, float]]:
        return iter(self._buf)

    def __getitem__(self, i: int) -> tuple[int, float]:
        return self._buf[i]

    @property
    def last(self) -> tuple[int, float] | None:
        return self._buf[-1] if self._buf else None

    def items(self) -> tuple[tuple[int, float], ...]:
        return tuple(self._buf)

    def first_at_or_after(self, threshold: float) -> tuple[int, float] | None:
        """ts >= threshold olan İLK kaydı döndürür (ekleme sırası).

        Eski doğrusal aramanın birebir eşdeğeri. Sırasız zamanda indeks
        geçersiz aday üretebilir; o durumda doğrusal aramaya düşer.
        """
        if not self._buf:
            return None
        if self._valid and isinstance(threshold, Real) and math.isfinite(threshold):
            i = bisect_left(self._prefix, float(threshold), lo=self._head)
            if i == len(self._prefix):
                # Ön-ek maksimumu eşiğe hiç ulaşmadı => hiçbir kayıt ulaşamaz.
                return None
            item = self._buf[i - self._head]
            if item[0] >= threshold:
                return item
            # Geçersiz aday: sırasız zaman damgası. Eski yola düş.
        for row in self._buf:
            if row[0] >= threshold:
                return row
        return None

    def stats(self) -> dict[str, float | int | bool]:
        return {"size": len(self._buf), "maxlen": self._maxlen,
                "index_valid": self._valid, "head_offset": self._head,
                "rebuilds": self._rebuilds, "seq": self.seq,
                "monotonic": self.monotonic}


def linear_first_at_or_after(rows, threshold: float) -> tuple[int, float] | None:
    """Referans (eski) implementasyon — eşdeğerlik testlerinde kullanılır."""
    for t, p in rows:
        if t >= threshold:
            return (t, p)
    return None