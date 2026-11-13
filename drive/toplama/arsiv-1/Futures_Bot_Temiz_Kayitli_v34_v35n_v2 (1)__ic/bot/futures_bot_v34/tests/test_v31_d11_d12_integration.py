"""Sentetik entegrasyon: gerçek aiohttp ağ bağlantısı değildir."""
import asyncio,json
from types import SimpleNamespace
import aiohttp
import ws_bot
from scanner.ws_scanner import OKXAkisi,BinanceAkisi
from scanner.binance_flow import BinanceAggTradeFlow
from reports.process_diagnostics import Diagnostics,event_yuk_kayit

class FakeWS:
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return None
    def __aiter__(self):return self
    async def __anext__(self):return SimpleNamespace(type=aiohttp.WSMsgType.TEXT,data='{}')
class FakeSession:
    def ws_connect(self,*args,**kwargs):return FakeWS()

async def cancel(*args):raise asyncio.CancelledError()

def test_okx_receive_gercek_dongude(monkeypatch):
    obj=OKXAkisi(None,[],None);monkeypatch.setattr(obj,'_abone',lambda *x:asyncio.sleep(0))
    monkeypatch.setattr(obj,'_isle',cancel)
    async def run():
        try:await obj._baglanti(FakeSession(),'wss://dummy','x',[],0)
        except asyncio.CancelledError:pass
    asyncio.run(run());assert isinstance(obj._son_receive_utc,float)

def test_binance_ws_receive_gercek_dongude(monkeypatch):
    obj=BinanceAkisi(None,None);monkeypatch.setattr(obj,'_isle',cancel)
    async def run():
        try:await obj.calistir(FakeSession())
        except asyncio.CancelledError:pass
    asyncio.run(run());assert isinstance(obj._son_receive_utc,float)

def test_aggtrade_receive_gercek_dongude(monkeypatch):
    obj=BinanceAggTradeFlow(['BTCUSDT'],lambda *a:None)
    def stop(*args):raise asyncio.CancelledError()
    monkeypatch.setattr(obj,'_isle',stop)
    async def run():
        try:await obj._run(FakeSession(),['BTCUSDT'],0)
        except asyncio.CancelledError:pass
    asyncio.run(run());assert isinstance(obj._son_receive_utc,float)

def test_sayac_loglari_gercek_emit_ile_yazilir(tmp_path):
    d=Diagnostics(str(tmp_path));okx=SimpleNamespace(mesaj_sayisi=1,baglanti_sayisi=1,_son_receive_utc=123.)
    bnc=SimpleNamespace(mesaj_sayisi=2,aktif=True,hata=None)
    bot=SimpleNamespace(durdu=False,diagnostics=d,_bnc_akis=SimpleNamespace(_son_receive_utc=456.),
        _akis_gorevler=set(),_regime_tasks=set(),_real_volume=SimpleNamespace(tasks=set()),
        detektor=SimpleNamespace(genislik_guncelle=lambda:None),_onceki_tik=(0,0))
    event=d.event_yuk
    def finish(b):event(b);bot.durdu=True
    d.event_yuk=finish
    asyncio.run(ws_bot.Bot._sayac_dongusu(bot,okx,bnc))
    lines=[json.loads(x) for x in (tmp_path/'logs/process_diagnostics.jsonl').read_text().splitlines()]
    ping=next(x for x in lines if x.get('event')=='ws_ping')
    queue=next(x for x in lines if x.get('event')=='event_yuk')
    assert ping['rtt']=='olculmedi' and ping['binance_aggtrade_son_receive_unix']==456.
    assert queue['aggtrade_gorev']==0 and isinstance(queue['asyncio_toplam'],int)

def test_no_loop_and_olmayan_kaynak_bilinmiyor():
    x=event_yuk_kayit(SimpleNamespace())
    assert x['asyncio_toplam'] is None and x['aggtrade_gorev'] is None
