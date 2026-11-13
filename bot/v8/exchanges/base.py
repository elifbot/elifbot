# -*- coding: utf-8 -*-
"""base.py — borsa adaptörü arayüzü. İki borsa aynı sözleşmeyi uygular.

Canlıya çıkmadan önce her adaptör şu üçünü garanti etmek zorunda:
  * marjin modu CROSS (izole değil)
  * kaldıraç 10x
  * her pozisyon için borsada duran reduceOnly stop emri

Ağ katmanı `oturum` ile enjekte edilir; testler sahte oturumla imza/parametre
doğrular, gerçek ağa çıkılmaz.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass

from ..types import EmirIstegi, EmirSonucu, Enstruman


@dataclass
class Bakiye:
    ozkaynak_usd: float
    serbest_usd: float
    kullanilan_usd: float


class BorsaAdaptoru(abc.ABC):
    ad: str = "?"

    @abc.abstractmethod
    async def enstrumanlar(self) -> dict[str, Enstruman]:
        """Canlı USDT-M perpetual enstrümanları, normalize edilmiş."""

    @abc.abstractmethod
    async def bakiye(self) -> Bakiye: ...

    @abc.abstractmethod
    async def marjin_kur(self, sembol: str) -> bool:
        """CROSS marj + 10x kaldıraç kurar. Başarısızsa işlem yapılmaz."""

    @abc.abstractmethod
    async def emir_gonder(self, istek: EmirIstegi) -> EmirSonucu: ...

    @abc.abstractmethod
    async def emir_iptal(self, sembol: str, emir_id: str) -> bool: ...

    @abc.abstractmethod
    async def pozisyonlar(self) -> dict[str, dict]: ...

    @abc.abstractmethod
    def ws_url(self) -> str: ...

    @abc.abstractmethod
    def ws_abonelik(self, semboller: list[str]) -> list[dict]: ...

    @abc.abstractmethod
    def tick_normalize(self, mesaj: dict) -> list[dict]:
        """Ham WS mesajı -> [{sembol, baz, fiyat, delta_usd, alis_usd, ts, hacim24_usd}]"""
