"""Binance USDⓈ-M üretim `/market/` aggTrade para-akışı.

2026 endpoint ayrımı sonrası aggTrade market kanalındadır. Eski `/ws` ve
testnet `stream.binancefuture.com` kullanılmaz. Combined stream üzerinden
REST weight tüketmeden gerçek taker yönü alınır.
"""
from __future__ import annotations
import asyncio
import json
import logging
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)
BINANCE_MARKET_STREAM = "wss://fstream.binance.com/market/stream?streams="
BINANCE_EXCHANGE_INFO = "https://www.binance.com/fapi/v1/exchangeInfo"


async def binance_sembolleri(oturum: aiohttp.ClientSession) -> set[str]:
    async with oturum.get(BINANCE_EXCHANGE_INFO, timeout=aiohttp.ClientTimeout(total=25)) as r:
        govde = await r.json()
    if not isinstance(govde, dict):
        raise RuntimeError("Binance exchangeInfo beklenmeyen yanıt")
    return {x["symbol"] for x in govde.get("symbols", [])
            if x.get("contractType") == "PERPETUAL" and x.get("quoteAsset") == "USDT"
            and x.get("status") == "TRADING"}


class BinanceAggTradeFlow:
    def __init__(self, semboller, trade_cb, parti_boyutu: int = 200):
        self.semboller = sorted(set(semboller))
        self.trade_cb = trade_cb
        self.parti_boyutu = max(1, min(int(parti_boyutu), 1024))
        self.mesaj_sayisi = 0
        self.trade_sayisi = 0
        self.baglanti_sayisi = 0
        self.hata_sayisi = 0
        self.callback_hata_sayisi = 0
        self.son_hata: str | None = None
        self.son_trade_ts = 0
        self._son_id: dict[str, int] = {}
        self._aktif_partiler: set[int] = set()

    @property
    def aktif(self) -> bool:
        return bool(self._aktif_partiler)

    @staticmethod
    def _url(parti: list[str]) -> str:
        streams = "/".join(quote(f"{s.lower()}@aggTrade", safe="@") for s in parti)
        return BINANCE_MARKET_STREAM + streams

    async def calistir(self, oturum: aiohttp.ClientSession) -> None:
        if not self.semboller:
            return
        partiler = [self.semboller[i:i + self.parti_boyutu]
                    for i in range(0, len(self.semboller), self.parti_boyutu)]
        await asyncio.gather(*(self._run(oturum, parti, i) for i, parti in enumerate(partiler)))

    async def _run(self, oturum, parti: list[str], no: int) -> None:
        url = self._url(parti)
        while True:
            try:
                async with oturum.ws_connect(url, heartbeat=20, max_msg_size=16 << 20) as ws:
                    self.baglanti_sayisi += 1
                    self._aktif_partiler.add(no)
                    self.son_hata = None
                    log.info("binance aggTrade market #%d bağlandı (%d sembol)", no, len(parti))
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                            continue
                        self._isle(msg.data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.hata_sayisi += 1
                self.son_hata = str(exc)[:180]
                log.warning("binance aggTrade market #%d koptu: %s — 2 sn sonra tekrar", no, exc)
            finally:
                self._aktif_partiler.discard(no)
            await asyncio.sleep(2)

    def _isle(self, ham: str) -> None:
        try:
            paket = json.loads(ham)
            satir = paket.get("data", paket)
            if satir.get("e") != "aggTrade":
                return
            sembol = satir["s"]
            aggregate_id = int(satir["a"])
            fiyat = float(satir["p"])
            base = float(satir["q"])
            ts = int(satir["T"])
            # m=true: alıcı maker => satıcı taker; yön SELL.
            yon = "sell" if bool(satir["m"]) else "buy"
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return
        self.mesaj_sayisi += 1
        if aggregate_id <= self._son_id.get(sembol, -1):
            return
        if fiyat <= 0 or base <= 0 or ts <= 0:
            return
        self._son_id[sembol] = aggregate_id
        self.trade_sayisi += 1
        self.son_trade_ts = max(self.son_trade_ts, ts)
        try:
            self.trade_cb("binance", sembol, fiyat, base, yon, ts)
        except Exception:  # noqa: BLE001
            self.callback_hata_sayisi += 1
            if self.callback_hata_sayisi <= 3:
                log.exception("binance akış callback hatası: %s", sembol)
