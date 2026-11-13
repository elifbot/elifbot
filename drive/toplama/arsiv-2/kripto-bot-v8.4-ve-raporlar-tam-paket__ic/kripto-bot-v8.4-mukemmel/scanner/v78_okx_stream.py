"""Opt-in OKX trade subscription lifecycle for the experimental paper source.

Tracks individual subscribe ACKs, not just an open TCP socket. Fail closed on
unacknowledged, rejected or closed subscriptions; ticker/candle tasks unchanged.
"""
import asyncio
import json
import logging
import aiohttp
from scanner.ws_scanner import OKXAkisi

log=logging.getLogger(__name__)

class OKXPaperAkisi(OKXAkisi):
    def __init__(self,*args,state_cb=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.state_cb=state_cb

    async def _baglanti(self,oturum,url,kanal,semboller,no):
        if kanal!='trades':
            return await super()._baglanti(oturum,url,kanal,semboller,no)
        allowed=set(semboller)
        while True:
            active=set()
            try:
                async with oturum.ws_connect(url,heartbeat=20,max_msg_size=16 << 20) as ws:
                    self.baglanti_sayisi+=1
                    await self._abone(ws,kanal,semboller)
                    async for msg in ws:
                        if msg.type!=aiohttp.WSMsgType.TEXT:
                            if msg.type in (aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR): break
                            continue
                        try: packet=json.loads(msg.data)
                        except (TypeError,ValueError):continue
                        arg=packet.get('arg') or {}
                        symbol=arg.get('instId'); event=packet.get('event')
                        if event=='subscribe' and arg.get('channel')=='trades' and symbol in allowed:
                            if symbol not in active:
                                active.add(symbol)
                                self.state_cb([symbol],True)
                            continue
                        if event in ('unsubscribe','error'):
                            if symbol in active:
                                active.remove(symbol);self.state_cb([symbol],False)
                            elif event=='error' and symbol is None and active:
                                self.state_cb(sorted(active),False);active.clear()
                            continue
                        if arg.get('channel')=='trades' and symbol in active:
                            await self._isle(msg.data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning('OKX trades #%d disconnected: %s',no,exc)
            finally:
                if active:
                    self.state_cb(sorted(active),False)
            await asyncio.sleep(2)
