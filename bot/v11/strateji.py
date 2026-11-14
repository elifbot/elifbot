"""Sinyal kuralları. Her fonksiyon, i. barın kapanışında karar verir (geleceğe bakmaz).

Dönüş: +1 long, −1 short, 0 işlem yok.
Eşikler repodaki ölçümlerden alındı (docs/10 "Eşiklerin gerçek öngörü gücü" ve kbot3 kanıt eşikleri).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

Feat = dict  # sembol özellik sözlüğü: c,h,l,o,e9,e21,rsi,adx,bbw,funding,oi


def _kesisim(f: Feat, i: int) -> int:
    e9, e21 = f["e9"], f["e21"]
    if i < 1 or e9[i] is None or e21[i] is None or e9[i - 1] is None or e21[i - 1] is None:
        return 0
    if e9[i - 1] <= e21[i - 1] and e9[i] > e21[i]:
        return 1
    if e9[i - 1] >= e21[i - 1] and e9[i] < e21[i]:
        return -1
    return 0


def ema_kesisim(f: Feat, i: int) -> int:
    """Referans: saf EMA9/21 kesişimi. Ölçümde yönsüz çıktı (docs/10)."""
    return _kesisim(f, i)


def kanit_esik(f: Feat, i: int) -> int:
    """kbot3 eşikleri: EMA kesişimi + ADX ≥ 30 + BB genişliği ≥ %0.5 + |RSI−50| ≥ 12."""
    s = _kesisim(f, i)
    if s == 0:
        return 0
    adx, bbw, rsi = f["adx"][i], f["bbw"][i], f["rsi"][i]
    if None in (adx, bbw, rsi):
        return 0
    if adx >= 30 and bbw >= 0.005 and abs(rsi - 50) >= 12:
        return s
    return 0


@dataclass
class FonAyar:
    esik: float = 0.0005     # |funding| ≥ %0.05 (8 saatlik) → kalabalık tarafın karşısına
    # HİPOTEZ: funding aşırılığında ters yön. Repoda bu veri ölçülmemiştir.


def fon_asiri(ayar: FonAyar = FonAyar()) -> Callable[[Feat, int], int]:
    def _f(f: Feat, i: int) -> int:
        fund = f.get("funding")
        if fund is None or fund[i] is None:
            return 0
        if fund[i] >= ayar.esik:
            return -1
        if fund[i] <= -ayar.esik:
            return 1
        return 0
    return _f


STRATEJILER: dict[str, Callable[[Feat, int], int]] = {
    "ema": ema_kesisim,
    "kanit": kanit_esik,
    "fon": fon_asiri(),
}
