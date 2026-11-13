# -*- coding: utf-8 -*-
"""feed.py — veri besleme katmanı. Üç kaynak, tek normalize şema.

  SentetikBesleme : ağ yoksa motor davranışını ölçmek için (TEST, kenar ölçmez)
  CsvReplayBesleme: kaydedilmiş tick arşivini aynen oynatır (gerçek veri, kenar ölçer)
  CanliBesleme    : Binance/OKX WS adaptörü (gerçek zamanlı)

Hepsi `types.Tick` üretir; motor hangi kaynaktan geldiğini bilmez. Bu ayrım
sayesinde aynı motor kodu hem testte hem canlıda çalışır.
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from .types import Tick

_BURASI = Path(__file__).resolve().parent
_ARACLAR = _BURASI.parent / "tools"
if str(_ARACLAR) not in sys.path:
    sys.path.insert(0, str(_ARACLAR))


def tick_yap(d: dict) -> Tick:
    return Tick(
        borsa=d.get("exchange") or d.get("borsa") or "?",
        sembol=d["symbol"] if "symbol" in d else d["sembol"],
        baz=d.get("baz") or str(d.get("symbol", d.get("sembol", ""))).split("-")[0].replace("USDT", ""),
        fiyat=float(d["price"] if "price" in d else d["fiyat"]),
        delta_usd=float(d.get("delta_usd") or 0.0),
        alis_usd=float(d.get("buy_usd") or d.get("alis_usd") or 0.0),
        ts=float(d.get("ts") or 0.0),
        hacim24_usd=float(d.get("quote_vol_24h") or d.get("hacim24_usd") or 0.0),
    )


@dataclass
class SentetikBesleme:
    """`bot/tools/sentetik_besleme.py` üretecini Tick'e çevirir."""

    semboller: list[str]
    seed: int = 20261113
    bucket_sn: float = 0.5
    baslangic_ts: float = 0.0

    def __post_init__(self) -> None:
        from sentetik_besleme import PiyasaAyari, SentetikPiyasa
        self._p = SentetikPiyasa(self.semboller, PiyasaAyari(seed=self.seed,
                                                             bucket_sn=self.bucket_sn))
        self.adim = 0

    def sonraki(self) -> list[Tick]:
        ts = self.baslangic_ts + self.adim * self.bucket_sn
        self.adim += 1
        return [tick_yap(d) for d in self._p.ticks(ts)]

    def fiyatlar(self) -> dict[str, float]:
        return {k: float(v) for k, v in self._p.fiyatlar.items()}


class CsvReplayBesleme:
    """tick arşivi: zaman,sembol,fiyat,delta_usd,buy_usd,hacim24_usd"""

    def __init__(self, yol: str) -> None:
        self.satirlar: list[dict] = []
        with open(yol, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                self.satirlar.append(r)
        self.i = 0

    def sonraki(self) -> list[Tick]:
        if self.i >= len(self.satirlar):
            return []
        satir = self.satirlar[self.i]
        self.i += 1
        return [tick_yap(satir)]

    def bitti(self) -> bool:
        return self.i >= len(self.satirlar)


class CanliBesleme:
    """Binance/OKX WS adaptörünü asyncio kuyruğuna bağlar (canlı mod)."""

    def __init__(self, adaptor, semboller: list[str]) -> None:
        self.adaptor = adaptor
        self.semboller = semboller

    async def dinle(self, kuyruk) -> None:  # pragma: no cover - ağ gerektirir
        import asyncio

        import aiohttp
        async with aiohttp.ClientSession() as oturum:
            async with oturum.ws_connect(self.adaptor.ws_url(), heartbeat=20) as ws:
                for ablone in self.adaptor.ws_abonelik(self.semboller):
                    await ws.send_json(ablone)
                async for mesaj in ws:
                    if mesaj.type != aiohttp.WSMsgType.TEXT:
                        continue
                    import json
                    for d in self.adaptor.tick_normalize(json.loads(mesaj.data)):
                        await kuyruk.put(tick_yap(d))
                    await asyncio.sleep(0)
